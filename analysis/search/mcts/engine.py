#!/usr/bin/env python3
"""engine.py — MCTS/UCT search engine main entry point.

Orchestrates:
1. Determinized world creation (DUCT)
2. MCTS main loop: select -> expand -> evaluate -> backpropagate
3. Single-pass deep search: tree naturally explores full turn sequences
4. Best sequence extraction from tree path

The tree explores complete action sequences within a single search pass.
Each branch from root follows: PLAY -> PLAY -> ATTACK -> ... -> END_TURN,
so the engine discovers card ordering effects, mana synergy, and combo plays
through simulation rather than greedy single-step decisions.

Usage:
    engine = MCTSEngine(config)
    result = engine.search(game_state, time_budget_ms=8000)
    for action in result.best_sequence:
        execute(action)
"""

from __future__ import annotations

import random
import time
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analysis.search.mcts.config import MCTSConfig, MCTSStats, get_phase_overrides
from analysis.search.mcts.node import MCTSNode
from analysis.search.mcts.uct import select_child
from analysis.search.mcts.expansion import Expander
from analysis.search.mcts.simulation import evaluate_leaf
from analysis.search.mcts.backprop import backpropagate
from analysis.search.mcts.pruning import ActionPruner
from analysis.search.mcts.determinization import Determinizer, DeterminizedWorld
from analysis.search.mcts.transposition import TranspositionTable, compute_state_hash
from analysis.search.abilities.actions import Action, ActionType, action_key
from analysis.search.abilities.enumeration import enumerate_legal_actions
from analysis.search.abilities.simulation import apply_action
from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


@dataclass
class ActionStats:
    """Per-action statistics from MCTS root node children."""
    action: Action
    visit_count: int = 0
    total_reward: float = 0.0
    q_value: float = 0.0
    visit_probability: float = 0.0
    win_rate: float = 0.0


@dataclass
class DetailedMCTSLog:
    """Detailed MCTS search log entries for parameter tuning analysis."""
    entries: List[dict] = field(default_factory=list)


@dataclass
class SearchResult:
    """Result from MCTS search, compatible with existing pipeline."""
    best_sequence: List[Action]
    fitness: float
    alternatives: List[Tuple[List[Action], float]] = field(default_factory=list)
    source: str = "mcts"
    mcts_stats: Optional[MCTSStats] = None
    action_stats: List[ActionStats] = field(default_factory=list)
    detailed_log: Optional[DetailedMCTSLog] = None


@dataclass
class _SearchContext:
    """Internal context for a single MCTS search invocation."""
    root_state: GameState
    worlds: List[DeterminizedWorld]
    root_node: MCTSNode
    tt: TranspositionTable
    config: MCTSConfig
    pruner: ActionPruner
    expander: Expander
    start_time: float
    time_budget_ms: float
    iterations_done: int = 0
    nodes_created: int = 0
    evaluations_done: int = 0

    @property
    def time_remaining_ms(self) -> float:
        return max(0, self.time_budget_ms - (time.time() * 1000 - self.start_time))

    @property
    def should_stop(self) -> bool:
        return self.time_remaining_ms <= 0


class MCTSEngine:
    """MCTS/UCT search engine for Hearthstone.

    Single-pass deep search: the MCTS tree naturally explores complete
    turn action sequences (PLAY -> PLAY -> ATTACK -> ... -> END_TURN),
    discovering card ordering effects, mana curve synergy, and combo
    plays through multi-dimensional simulation.
    """

    def __init__(self, config: Optional[MCTSConfig] = None):
        self.config = config or MCTSConfig()
        self._last_root: Optional[MCTSNode] = None
        self._last_action_key: Optional[tuple] = None

    def search(
        self,
        state: GameState,
        time_budget_ms: Optional[float] = None,
        bayesian_model=None,
        opp_playstyle: str = "unknown",
    ) -> SearchResult:
        """Execute MCTS search and return action sequence.

        Single-pass deep search: the tree explores full turn sequences
        so card ordering, mana efficiency, and combos are evaluated
        through simulation, not greedy single-step decisions.

        Args:
            state: Current game state (may have incomplete information).
            time_budget_ms: Time budget in ms. None = use config default.
            bayesian_model: Pre-loaded BayesianOpponentModel with observed
                opponent cards. If None, Determinizer creates a fresh model.
            opp_playstyle: Opponent playstyle from Bayesian prediction
                (aggro/control/combo/midrange/unknown).

        Returns:
            SearchResult with best_sequence and stats.
        """
        self._bayesian_model = bayesian_model
        budget = time_budget_ms or self.config.time_budget_ms

        overrides = get_phase_overrides(state.turn_number, opp_playstyle=opp_playstyle)
        effective_config = MCTSConfig(**{
            **{f.name: getattr(self.config, f.name)
               for f in self.config.__dataclass_fields__.values()},
            **overrides,
            "time_budget_ms": budget,
        })

        start = time.time() * 1000

        ctx = self._create_context(state, effective_config)
        detailed_log = self._run_mcts_loop(ctx)

        root = ctx.root_node
        action_stats = self._collect_action_stats(root)

        best_sequence = self._extract_best_sequence(root, state)

        elapsed = time.time() * 1000 - start

        final_state = state
        for a in best_sequence:
            final_state = apply_action(final_state, a)

        from analysis.evaluators.composite import evaluate_delta
        fitness = evaluate_delta(state, final_state)

        alternatives = self._extract_alternatives(root, state)

        stats = MCTSStats(
            iterations=ctx.iterations_done,
            nodes_created=ctx.nodes_created,
            evaluations_done=ctx.evaluations_done,
            time_used_ms=elapsed,
            world_count=len(ctx.worlds),
        )

        self._last_root = root
        self._last_action_key = root.best_child_key

        return SearchResult(
            best_sequence=best_sequence,
            fitness=fitness,
            source="mcts",
            mcts_stats=stats,
            action_stats=action_stats,
            detailed_log=detailed_log,
            alternatives=alternatives,
        )

    # ── Sequence extraction ────────────────────────────

    def _extract_best_sequence(
        self,
        root: MCTSNode,
        root_state: GameState,
    ) -> List[Action]:
        """Extract the best action sequence by following highest-Q children.

        Uses robust_best_child_key (highest Q-value among well-visited
        children) instead of most-visited, so END_TURN never wins over
        high-value card plays.

        At each step, validates the chosen action is still legal in the
        current state (tree may cache children from earlier game states).
        """
        from analysis.search.abilities.enumeration import enumerate_legal_actions

        actions: List[Action] = []
        node = root
        state = root_state
        max_steps = 15

        for _ in range(max_steps):
            if not node.children:
                break

            # Build set of currently legal action keys for validation
            legal = enumerate_legal_actions(state)
            legal_keys = {action_key(a) for a in legal}

            # Pick best child whose action is still legal
            best_ak = None
            # Sort children by Q-value descending, pick first legal one
            candidates = sorted(
                node.children.items(),
                key=lambda kv: kv[1].q_value,
                reverse=True,
            )
            for ak, child in candidates:
                if child.visit_count < 3:
                    continue
                if ak in legal_keys:
                    best_ak = ak
                    break

            if best_ak is None:
                break

            edge = node.action_edges.get(best_ak)
            if edge is None:
                break

            action = edge.action
            actions.append(action)

            if action.action_type == ActionType.END_TURN:
                break

            # Advance state to validate next step
            from analysis.search.abilities.simulation import apply_action
            state = apply_action(state, action)

            child = node.children.get(best_ak)
            if child is None:
                break
            node = child

        if not actions or actions[-1].action_type != ActionType.END_TURN:
            actions.append(Action(action_type=ActionType.END_TURN))

        return actions

    def _extract_alternatives(
        self,
        root: MCTSNode,
        root_state: GameState,
    ) -> List[Tuple[List[Action], float]]:
        """Extract alternative action sequences from root's top children."""
        if not root.children:
            return []

        alternatives: List[Tuple[List[Action], float]] = []
        sorted_children = sorted(
            root.children.items(),
            key=lambda kv: kv[1].visit_count,
            reverse=True,
        )

        best_ak = root.best_child_key
        for ak, child in sorted_children[:4]:
            if ak == best_ak:
                continue

            edge = root.action_edges.get(ak)
            if edge is None:
                continue

            first_action = edge.action
            seq = [first_action]

            sub_node = child
            for _ in range(10):
                sub_best_ak = sub_node.best_child_key
                if sub_best_ak is None:
                    break
                sub_edge = sub_node.action_edges.get(sub_best_ak)
                if sub_edge is None:
                    break
                seq.append(sub_edge.action)
                if sub_edge.action.action_type == ActionType.END_TURN:
                    break
                sub_child = sub_node.children.get(sub_best_ak)
                if sub_child is None:
                    break
                sub_node = sub_child

            if not seq or seq[-1].action_type != ActionType.END_TURN:
                seq.append(Action(action_type=ActionType.END_TURN))

            qv = child.q_value
            fitness = (qv + 1.0) / 2.0
            alternatives.append((seq, fitness))

        return alternatives[:3]

    # ── Context creation ───────────────────────────────

    def _create_context(
        self,
        state: GameState,
        config: MCTSConfig,
    ) -> _SearchContext:
        """Set up search context: worlds, root node, transposition table."""
        tt = TranspositionTable(max_size=config.transposition_max_size)

        state_hash = compute_state_hash(state, is_player_turn=True)
        root = MCTSNode(
            node_id=0,
            state_hash=state_hash,
            is_player_turn=True,
        )

        bayesian = getattr(self, '_bayesian_model', None)
        determinizer = Determinizer(config, bayesian_model=bayesian)
        worlds = determinizer.create_worlds(state)

        pruner = ActionPruner(
            enable_tree=config.enable_tree_pruning,
            enable_sim=config.enable_sim_pruning,
        )
        expander = Expander(config, pruner)

        return _SearchContext(
            root_state=state,
            worlds=worlds,
            root_node=root,
            tt=tt,
            config=config,
            pruner=pruner,
            expander=expander,
            start_time=time.time() * 1000,
            time_budget_ms=config.time_budget_ms,
        )

    # ── Statistics ─────────────────────────────────────

    def _collect_action_stats(self, root: MCTSNode) -> List[ActionStats]:
        """Extract per-action statistics from root node's children."""
        if not root.children:
            return []

        total_visits = sum(
            child.visit_count for child in root.children.values()
        )
        if total_visits == 0:
            return []

        stats_list: List[ActionStats] = []
        for ak, child in root.children.items():
            edge = root.action_edges.get(ak)
            action = edge.action if edge else None
            if action is None:
                continue

            vc = child.visit_count
            tr = child.total_reward
            qv = child.q_value
            prob = vc / total_visits if total_visits > 0 else 0.0
            wr = (qv + 1.0) / 2.0

            stats_list.append(ActionStats(
                action=action,
                visit_count=vc,
                total_reward=tr,
                q_value=qv,
                visit_probability=prob,
                win_rate=wr,
            ))

        stats_list.sort(key=lambda s: s.visit_count, reverse=True)
        return stats_list

    # ── Main MCTS loop ─────────────────────────────────

    def _run_mcts_loop(self, ctx: _SearchContext) -> Optional[DetailedMCTSLog]:
        """Main MCTS iteration loop.

        Each iteration: select a determinized world, traverse the tree
        (which naturally follows PLAY -> PLAY -> ATTACK -> END_TURN paths),
        evaluate the leaf, and backpropagate.

        Returns DetailedMCTSLog when debug_mode is enabled, else None.
        """
        config = ctx.config
        log_interval = config.log_interval
        max_iters = 200000
        time_check_every = 50

        detailed_log = DetailedMCTSLog() if config.debug_mode else None

        while ctx.iterations_done < max_iters:
            if ctx.iterations_done % time_check_every == 0 and ctx.should_stop:
                break

            world = random.choice(ctx.worlds)
            world_state = world.state

            path, leaf, leaf_state = self._traverse(ctx, world_state)

            reward = evaluate_leaf(
                leaf_state, ctx.root_state, config,
                turn_depth=leaf.turn_depth,
            )
            ctx.evaluations_done += 1

            if leaf.is_terminal and leaf.terminal_reward is not None:
                reward = leaf.terminal_reward

            backpropagate(path, reward, leaf=leaf)

            ctx.iterations_done += 1

            redet_interval = config.log_interval * 5
            if ctx.iterations_done > 0 and ctx.iterations_done % redet_interval == 0:
                self._refresh_worlds(ctx)

            if ctx.iterations_done % log_interval == 0:
                root = ctx.root_node
                best_ak = root.best_child_key
                best_q = 0.0
                if best_ak and best_ak in root.children:
                    best_q = root.children[best_ak].q_value

                log.info(
                    "MCTS iter=%d nodes=%d evals=%d remaining=%.0fms best_q=%.4f",
                    ctx.iterations_done, ctx.expander._next_id,
                    ctx.evaluations_done, ctx.time_remaining_ms, best_q,
                )

                if ctx.iterations_done % (log_interval * 5) == 0:
                    self._log_root_children(root, ctx.iterations_done)

                if detailed_log is not None:
                    detailed_log.entries.append({
                        "iter": ctx.iterations_done,
                        "nodes": ctx.expander._next_id,
                        "evals": ctx.evaluations_done,
                        "remaining_ms": ctx.time_remaining_ms,
                        "best_q": best_q,
                        "depth": leaf.depth if leaf else 0,
                    })

        return detailed_log

    # ── Tree traversal ─────────────────────────────────

    def _traverse(
        self,
        ctx: _SearchContext,
        world_state: GameState,
    ) -> Tuple[List[MCTSNode], MCTSNode, GameState]:
        """Selection + Expansion: traverse tree to a leaf.

        The tree naturally follows action sequences:
        root(PLAY A) -> child(PLAY B) -> grandchild(ATTACK) -> ... -> END_TURN

        Returns:
            (path, leaf_node, leaf_state)
        """
        node = ctx.root_node
        state = world_state
        path: List[MCTSNode] = []
        max_depth = ctx.config.max_tree_depth
        steps = 0
        max_steps = 30

        while (not node.is_leaf and not node.is_terminal
               and node.children and node.depth < max_depth
               and steps < max_steps):
            result = select_child(node, state, ctx.config)
            if result is None:
                break

            ak, child = result

            from analysis.search.mcts.config import NodeType
            if child.node_type == NodeType.CHANCE:
                edge = node.action_edges.get(ak)
                if edge:
                    state = apply_action(state, edge.action)
                path.append(node)
                node = child

                outcome_result = select_child(node, state, ctx.config)
                if outcome_result is None:
                    break
                _, outcome_child = outcome_result
                path.append(node)
                node = outcome_child
                steps += 2
                continue

            edge = node.action_edges.get(ak)
            if edge:
                state = apply_action(state, edge.action)

            path.append(node)
            node = child
            steps += 1

        if not node.is_terminal and node.is_leaf and node.depth < ctx.config.max_tree_depth:
            if node.turn_depth >= ctx.config.max_turns_ahead:
                pass
            else:
                child_result = ctx.expander.expand_node(node, state, ctx.tt)
                if child_result is not None:
                    child_node, child_state = child_result
                    path.append(node)
                    node = child_node
                    state = child_state
                    ctx.nodes_created += 1

        return path, node, state

    # ── Helpers ────────────────────────────────────────

    def _refresh_worlds(self, ctx: _SearchContext) -> None:
        """Re-determinize a portion of worlds."""
        if len(ctx.worlds) <= 1:
            return

        bayesian = getattr(self, '_bayesian_model', None)
        determinizer = Determinizer(ctx.config, bayesian_model=bayesian)

        n_refresh = max(1, len(ctx.worlds) // 2)
        for i in range(n_refresh):
            idx = i * 2
            if idx < len(ctx.worlds):
                new_state = determinizer._determinize(ctx.root_state)
                ctx.worlds[idx] = DeterminizedWorld(
                    world_id=ctx.worlds[idx].world_id,
                    state=new_state,
                    weight=ctx.worlds[idx].weight,
                )

        log.debug(
            "Re-determinized %d/%d worlds at iter=%d",
            n_refresh, len(ctx.worlds), ctx.iterations_done,
        )

    def _log_root_children(self, root: MCTSNode, iteration: int) -> None:
        """Log per-action visit counts and Q values for debugging."""
        if not root.children:
            return
        total_visits = sum(c.visit_count for c in root.children.values())
        lines = [f"MCTS root children at iter={iteration} total_visits={total_visits}:"]
        sorted_children = sorted(
            root.children.items(),
            key=lambda kv: kv[1].visit_count,
            reverse=True,
        )
        for ak, child in sorted_children[:8]:
            edge = root.action_edges.get(ak)
            action_desc = str(edge.action) if edge else str(ak)
            vc = child.visit_count
            qv = child.q_value
            wr = (qv + 1.0) / 2.0
            lines.append(
                f"  {action_desc}: visits={vc} q={qv:+.4f} winrate={wr:.1%}"
            )
        log.info("\n".join(lines))

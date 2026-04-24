#!/usr/bin/env python3
"""engine.py — MCTS/UCT search engine main entry point.

Orchestrates:
1. Determinized world creation (DUCT)
2. MCTS main loop: select → expand → evaluate → backpropagate
3. Multi-step action sequence with exponential time decay
4. Tree reuse between consecutive action decisions

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
from analysis.search.rhea.actions import Action, ActionType, action_key
from analysis.search.rhea.enumeration import enumerate_legal_actions
from analysis.search.rhea.simulation import apply_action
from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


@dataclass
class ActionStats:
    """Per-action statistics from MCTS root node children."""
    action: Action
    visit_count: int = 0
    total_reward: float = 0.0
    q_value: float = 0.0
    visit_probability: float = 0.0  # visit_count / total_root_visits
    win_rate: float = 0.0           # (q_value + 1) / 2, mapped to [0, 1]


@dataclass
class DetailedMCTSLog:
    """Detailed MCTS search log entries for parameter tuning analysis."""
    entries: List[dict] = field(default_factory=list)
    # Each entry: {"iter": int, "nodes": int, "evals": int,
    #              "remaining_ms": float, "best_q": float, "depth": int}


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
    """MCTS/UCT search engine for Hearthstone."""

    def __init__(self, config: Optional[MCTSConfig] = None):
        self.config = config or MCTSConfig()
        self._last_root: Optional[MCTSNode] = None
        self._last_action_key: Optional[tuple] = None

    def search(
        self,
        state: GameState,
        time_budget_ms: Optional[float] = None,
        bayesian_model=None,
    ) -> SearchResult:
        """Execute MCTS search and return action sequence.

        Args:
            state: Current game state (may have incomplete information).
            time_budget_ms: Time budget in ms. None = use config default.
            bayesian_model: Pre-loaded BayesianOpponentModel with observed
                opponent cards. If None, Determinizer creates a fresh model.

        Returns:
            SearchResult with best_sequence and stats.
        """
        self._bayesian_model = bayesian_model
        budget = time_budget_ms or self.config.time_budget_ms

        # Apply phase overrides
        overrides = get_phase_overrides(state.turn_number)
        effective_config = MCTSConfig(**{
            **{f.name: getattr(self.config, f.name)
               for f in self.config.__dataclass_fields__.values()},
            **overrides,
            "time_budget_ms": budget,
        })

        # Search action sequence (multi-step)
        start = time.time() * 1000
        total_stats = MCTSStats()
        actions, action_stats, detailed_log = self._search_action_sequence(state, effective_config, total_stats)
        elapsed = time.time() * 1000 - start

        # Evaluate final fitness
        final_state = state
        for a in actions:
            final_state = apply_action(final_state, a)

        from analysis.evaluators.composite import evaluate_delta
        fitness = evaluate_delta(state, final_state)

        stats = MCTSStats(
            iterations=total_stats.iterations,
            nodes_created=total_stats.nodes_created,
            evaluations_done=total_stats.evaluations_done,
            time_used_ms=elapsed,
            world_count=effective_config.num_worlds,
        )

        return SearchResult(
            best_sequence=actions,
            fitness=fitness,
            source="mcts",
            mcts_stats=stats,
            action_stats=action_stats,
            detailed_log=detailed_log,
        )

    def search_single_action(
        self,
        state: GameState,
        time_budget_ms: float,
    ) -> Tuple[Action, MCTSStats, List[ActionStats], Optional[DetailedMCTSLog]]:
        """Search for a single best action.

        Returns:
            (best_action, stats, action_stats_list, detailed_log)
        """
        start = time.time() * 1000

        ctx = self._create_context(state, time_budget_ms)
        detailed_log = self._run_mcts_loop(ctx)

        root = ctx.root_node
        best_ak = root.best_child_key
        if best_ak is None:
            action = Action(action_type=ActionType.END_TURN)
        else:
            edge = root.action_edges.get(best_ak)
            action = edge.action if edge else Action(action_type=ActionType.END_TURN)

        # Collect per-action statistics from root node children
        action_stats_list = self._collect_action_stats(root)

        elapsed = time.time() * 1000 - start
        stats = MCTSStats(
            iterations=ctx.iterations_done,
            nodes_created=ctx.nodes_created,
            evaluations_done=ctx.evaluations_done,
            time_used_ms=elapsed,
            world_count=len(ctx.worlds),
            transposition_hits=ctx.tt.hit_rate,
        )

        # Store for tree reuse
        self._last_root = root
        self._last_action_key = best_ak

        return action, stats, action_stats_list, detailed_log

    # ── Internal: multi-step search ────────────────────

    def _search_action_sequence(
        self,
        state: GameState,
        config: MCTSConfig,
        accum_stats: Optional[MCTSStats] = None,
    ) -> Tuple[List[Action], List[ActionStats], Optional[DetailedMCTSLog]]:
        """Search for a complete action sequence with exponential time decay.

        Returns:
            (actions, action_stats_list, detailed_log)
            action_stats_list contains per-action stats from the *first* search step only.
        """
        actions: List[Action] = []
        current_state = state
        remaining_budget = config.time_budget_ms
        gamma = config.time_decay_gamma
        step = 0
        first_step_action_stats: List[ActionStats] = []
        detailed_log: Optional[DetailedMCTSLog] = None

        # Compute first-step budget
        # Total = t0 * (1 + gamma + gamma^2 + ...) = t0 / (1 - gamma)
        if gamma < 1.0:
            t0 = remaining_budget * (1.0 - gamma)
        else:
            t0 = remaining_budget

        while remaining_budget > config.min_step_budget_ms:
            # Step budget with exponential decay
            step_budget = t0 * (gamma ** step)
            step_budget = max(step_budget, config.min_step_budget_ms)
            step_budget = min(step_budget, remaining_budget * 0.85)

            if step_budget < config.min_step_budget_ms:
                break

            # Quick play check
            legal = enumerate_legal_actions(current_state)
            non_end = [a for a in legal if a.action_type != ActionType.END_TURN]
            if not non_end:
                actions.append(Action(action_type=ActionType.END_TURN))
                break
            if len(legal) <= 2:
                # With 1-2 actions, just pick the best without full MCTS
                best = max(legal, key=lambda a: (
                    0 if a.action_type == ActionType.END_TURN else 1
                ))
                actions.append(best)
                if best.action_type == ActionType.END_TURN:
                    break
                current_state = apply_action(current_state, best)
                remaining_budget -= step_budget * 0.1
                step += 1
                continue

            # Search for best action at this step
            best_action, stats, a_stats, d_log = self.search_single_action(
                current_state, step_budget
            )

            # Capture first-step stats and detailed log
            if step == 0:
                first_step_action_stats = a_stats
                detailed_log = d_log

            # Accumulate stats
            if accum_stats is not None:
                accum_stats.iterations += stats.iterations
                accum_stats.nodes_created += stats.nodes_created
                accum_stats.evaluations_done += stats.evaluations_done

            actions.append(best_action)

            if best_action.action_type == ActionType.END_TURN:
                break

            current_state = apply_action(current_state, best_action)
            remaining_budget -= step_budget
            step += 1

            if step >= config.max_actions_per_turn:
                break

        # Ensure sequence ends with END_TURN
        if not actions or actions[-1].action_type != ActionType.END_TURN:
            actions.append(Action(action_type=ActionType.END_TURN))

        return actions, first_step_action_stats, detailed_log

    # ── Internal: single-step MCTS ─────────────────────

    def _create_context(
        self,
        state: GameState,
        budget_ms: float,
    ) -> _SearchContext:
        """Set up search context: worlds, root node, transposition table."""
        config = self.config

        # Try tree reuse
        root = self._try_reuse_tree(state)

        # Create transposition table
        tt = TranspositionTable(max_size=config.transposition_max_size)

        if root is None:
            state_hash = compute_state_hash(state, is_player_turn=True)
            root = MCTSNode(
                node_id=0,
                state_hash=state_hash,
                is_player_turn=True,
            )
        else:
            # Reuse existing TT data if available
            pass

        # Create determinized worlds
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
            time_budget_ms=budget_ms,
        )

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
            wr = (qv + 1.0) / 2.0  # Map from [-1,1] to [0,1]

            stats_list.append(ActionStats(
                action=action,
                visit_count=vc,
                total_reward=tr,
                q_value=qv,
                visit_probability=prob,
                win_rate=wr,
            ))

        # Sort by visit count descending (best first)
        stats_list.sort(key=lambda s: s.visit_count, reverse=True)
        return stats_list

    def _run_mcts_loop(self, ctx: _SearchContext) -> Optional[DetailedMCTSLog]:
        """Main MCTS iteration loop with hard iteration limit.

        Returns DetailedMCTSLog when debug_mode is enabled, else None.
        """
        config = ctx.config
        log_interval = config.log_interval
        max_iters = 200000  # Hard safety cap
        time_check_every = 50  # Check wall-clock every N iterations

        detailed_log = DetailedMCTSLog() if config.debug_mode else None

        while ctx.iterations_done < max_iters:
            # Time check (every N iterations to reduce syscalls)
            if ctx.iterations_done % time_check_every == 0 and ctx.should_stop:
                break

            # 1. Select world
            world = random.choice(ctx.worlds)
            world_state = world.state

            # 2. Selection + Expansion + Evaluation + Backpropagation
            path, leaf, leaf_state = self._traverse(ctx, world_state)

            # 3. Evaluate leaf
            reward = evaluate_leaf(leaf_state, ctx.root_state, config, turn_depth=leaf.turn_depth)
            ctx.evaluations_done += 1

            # 4. Override with terminal reward if available
            if leaf.is_terminal and leaf.terminal_reward is not None:
                reward = leaf.terminal_reward

            # 5. Backpropagate
            backpropagate(path, reward)

            ctx.iterations_done += 1

            # Periodic logging
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

                # Collect detailed log entries for parameter tuning
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

    def _traverse(
        self,
        ctx: _SearchContext,
        world_state: GameState,
    ) -> Tuple[List[MCTSNode], MCTSNode, GameState]:
        """Selection + Expansion: traverse tree to a leaf.

        Returns:
            (path, leaf_node, leaf_state)
        """
        node = ctx.root_node
        state = world_state
        path: List[MCTSNode] = []
        max_depth = ctx.config.max_tree_depth
        steps = 0
        max_steps = 30  # Hard safety cap on traversal depth

        while (not node.is_leaf and not node.is_terminal
               and node.children and node.depth < max_depth
               and steps < max_steps):
            # Select child
            result = select_child(node, state, ctx.config)
            if result is None:
                break

            ak, child = result

            # For chance nodes, select an outcome
            from analysis.search.mcts.config import NodeType
            if child.node_type == NodeType.CHANCE:
                # Apply the stochastic action to get to the chance node
                edge = node.action_edges.get(ak)
                if edge:
                    state = apply_action(state, edge.action)
                path.append(node)
                node = child

                # Now select an outcome from the chance node
                outcome_result = select_child(node, state, ctx.config)
                if outcome_result is None:
                    break
                _, outcome_child = outcome_result
                path.append(node)
                node = outcome_child
                steps += 2  # chance node + outcome
                # State already reflects the outcome (sampled in expansion)
                continue

            # Apply action to advance state
            edge = node.action_edges.get(ak)
            if edge:
                state = apply_action(state, edge.action)

            path.append(node)
            node = child
            steps += 1
        if not node.is_terminal and node.is_leaf and node.depth < ctx.config.max_tree_depth:
            # Don't expand cross-turn nodes beyond budget
            if node.turn_depth >= ctx.config.max_turns_ahead:
                pass  # Will be evaluated statically (with rollout if configured)
            else:
                child_result = ctx.expander.expand_node(node, state, ctx.tt)
                if child_result is not None:
                    child_node, child_state = child_result
                    path.append(node)
                    node = child_node
                    state = child_state
                    ctx.nodes_created += 1

        return path, node, state

    def _try_reuse_tree(self, state: GameState) -> Optional[MCTSNode]:
        """Try to reuse subtree from previous search step."""
        if self._last_root is None or self._last_action_key is None:
            return None

        child = self._last_root.children.get(self._last_action_key)
        if child is not None:
            child.parent = None
            return child

        return None

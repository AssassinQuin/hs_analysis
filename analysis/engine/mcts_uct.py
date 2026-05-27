"""
Pure action-space MCTS UCT search engine.

Builds a tree from GameState by iterating:
  SELECT → EXPAND → SIMULATE → BACKPROPAGATE

Uses the v2 engine API (enumerate_legal / apply_action) so it
works on any GameState without needing game-specific heuristics.
"""
from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.rules import (
    check_game_over,
    enumerate_legal,
    enumerate_opponent_legal,
)
from analysis.card.engine.simulation import apply_action
from analysis.engine.opponent_scoring import HeuristicRolloutScorer
from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MCTSConfig:
    """Tunable parameters for the UCT search."""
    exploration_constant: float = 1.414  # UCB1: higher = more exploration
    iterations: int = 300
    rollout_depth: int = 15
    time_budget_ms: int = 1500         # 实时对战收敛拐点（~170次迭代）
    use_heuristic_rollout: bool = True   # if True use heuristic opponent policy
    verbose: bool = False

    # multi-turn lookahead
    max_turns_ahead: int = 1            # how many of OUR turns to expand in tree (1=current only)
    max_opponent_tree_actions: int = 5   # limit opponent branch expansion in tree

    # pruning
    expand_all_children: bool = True     # expand all legal actions on first visit
    rave_weight: float = 0.5            # RAVE factor (0 = pure UCB1, 1 = full RAVE)

    # 进度感知探索：搜索前期高探索，后期低探索（更利用）
    exploration_decay: bool = True       # 是否启用探索衰减
    exploration_min: float = 0.7         # 衰减下限

    # rollout 奖励
    use_evaluator_reward: bool = True    # 使用 CompositeEvaluator 替代简单启发式
    discount_factor: float = 0.95        # 反向传播衰减因子（<1 时深层奖励折扣）

    @property
    def time_budget_s(self) -> float:
        return self.time_budget_ms / 1000.0


# ---------------------------------------------------------------------------
# Tree Node
# ---------------------------------------------------------------------------

@dataclass
class MCTSNode:
    """A node in the UCT search tree."""
    state: GameState
    action: Optional[Action]             # action that led to this node (None = root)
    parent: Optional["MCTSNode"] = None  # noqa: F821
    children: List["MCTSNode"] = field(default_factory=list)  # noqa: F821

    visit_count: int = 0
    total_reward: float = 0.0

    # RAVE (Rapid Action Value Estimation) 统计
    rave_visit_count: int = 0
    rave_total_reward: float = 0.0

    untried_actions: List[Action] = field(default_factory=list)
    is_terminal: bool = False
    depth: int = 0

    # Multi-turn tracking
    turn_depth: int = 0       # how many of OUR turns deep (0 = current turn)
    is_player_turn: bool = True  # True = our turn, False = opponent turn

    @property
    def q_value(self) -> float:
        """Mean reward for this node."""
        if self.visit_count == 0:
            return 0.0
        return self.total_reward / self.visit_count

    @property
    def rave_q(self) -> float:
        """RAVE mean reward."""
        if self.rave_visit_count == 0:
            return 0.0
        return self.rave_total_reward / self.rave_visit_count

    def ucb1(self, iteration: int = 0, total_iterations: int = 0) -> float:
        """
        UCB1 score with RAVE + progress-aware exploration.

        Formula:
          UCB = (1-β)·Q_UCB + β·Q_RAVE
          Q_UCB = exploitation + exploration
          β = rave_weight · max(0, 1 - N / b)  (b = equivalence parameter)
          exploration_constant decays with search progress
        """
        if self.parent is None:
            return self.q_value
        if self.visit_count == 0:
            return float("inf")

        config = self.parent.config if hasattr(self.parent, 'config') else None
        base_c = config.exploration_constant if config else 1.414

        # 进度感知探索常数衰减
        if config and config.exploration_decay and total_iterations > 0:
            progress = min(iteration / total_iterations, 1.0)
            c = base_c * (1.0 - progress * (1.0 - config.exploration_min))
        else:
            c = base_c

        exploitation = self.q_value
        exploration = c * math.sqrt(
            math.log(self.parent.visit_count) / self.visit_count
        )
        ucb_score = exploitation + exploration

        # RAVE 融合
        if config and config.rave_weight > 0 and self.rave_visit_count > 0:
            b = 300.0
            beta = config.rave_weight * max(0.0, 1.0 - self.visit_count / b)
            if beta > 0:
                ucb_score = (1.0 - beta) * ucb_score + beta * self.rave_q

        return ucb_score

    def best_child(self, iteration: int = 0, total_iterations: int = 0) -> Optional["MCTSNode"]:
        """Select child with highest UCB1 score."""
        if not self.children:
            return None
        return max(self.children, key=lambda c: c.ucb1(iteration, total_iterations))

    def best_action_child(self) -> Optional[Tuple[Action, "MCTSNode"]]:
        """Return the (action, child) pair with the highest visit count."""
        if not self.children:
            return None
        best = max(self.children, key=lambda c: c.visit_count)
        return (best.action, best)

    def get_action_sequence(self) -> List[Action]:
        """Return the action sequence from root to this node."""
        actions: List[Action] = []
        current: Optional[MCTSNode] = self
        while current is not None and current.action is not None:
            actions.append(current.action)
            current = current.parent
        actions.reverse()
        return actions

    def __repr__(self) -> str:
        desc = self.action.describe()[:40] if self.action else "ROOT"
        turn_label = "P" if self.is_player_turn else "O"
        return (f"Node({desc} | v={self.visit_count} "
                f"q={self.q_value:.3f} td={self.turn_depth} {turn_label})")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class MCTSResult:
    """Return value from a full UCT search."""
    best_action: Optional[Action]
    best_node: Optional[MCTSNode]
    root_node: MCTSNode
    action_values: Dict[str, float]       # action_key → q_value
    visit_counts: Dict[str, int]
    search_stats: Dict                     # timing, depth, etc.
    num_nodes: int = 0
    tree_depth: int = 0
    best_sequence: List[Action] = field(default_factory=list)  # full action plan

    def top_actions(self, k: int = 5) -> List[Tuple[str, float, int]]:
        """Return top-k (description, q_value, visit_count) triples."""
        items = [
            (desc, self.action_values[desc], self.visit_counts[desc])
            for desc in self.action_values
        ]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:k]


# ---------------------------------------------------------------------------
# Reward Function
# ---------------------------------------------------------------------------

def _default_reward(state: GameState) -> float:
    """
    Heuristic reward for a terminal or leaf state.
    Range: [-1, 1] where +1 = we're winning.

    优先使用 CompositeEvaluator（BSV 融合评估器），
    回退到简单 HP/board/hand 启发式。
    """
    if state is None:
        return -1.0

    # terminal check
    game_over = check_game_over(state)
    if game_over == 0:      # we won
        return 1.0
    elif game_over == 1:    # opponent won
        return -1.0

    # 尝试使用 CompositeEvaluator
    try:
        from analysis.evaluators.composite import evaluate
        raw = evaluate(state)
        return math.tanh(raw / 50.0)  # 归一化到 [-1, 1]
    except Exception:
        pass

    # 回退：简单启发式
    our_hp = state.hero.hp + state.hero.armor if state.hero else 1
    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor if state.opponent and state.opponent.hero else 1

    hp_ratio = our_hp / max(opp_hp, 1)
    hp_score = math.tanh(hp_ratio - 1.0) * 0.5

    our_board_total = sum(m.total_stats for m in state.board)
    opp_board_total = sum(m.total_stats for m in state.opponent.board)
    board_score = math.tanh(
        (our_board_total - opp_board_total) / max(opp_board_total + our_board_total, 1)
    ) * 0.3

    hand_score = math.tanh(
        (len(state.hand) - state.opponent.hand_count) / 10.0
    ) * 0.2

    return hp_score + board_score + hand_score


def _random_rollout(state: GameState, depth: int,
                     reward_fn: Callable[[GameState], float]) -> float:
    """
    Simulate random play from `state` up to `depth` actions.
    Alternates between our turn and opponent turn based on
    state.is_opponent_turn. Imports the dispatch inline so that
    turn transitions (set by apply_action's _end_turn handler)
    are automatically followed.
    Returns the reward at the end (from our perspective).
    """
    s = state
    for _ in range(depth):
        game_over = check_game_over(s)
        if game_over is not None:
            break

        if s.is_opponent_turn:
            legal = enumerate_opponent_legal(s)
        else:
            legal = enumerate_legal(s)
        if not legal:
            break
        action = random.choice(legal)
        s = apply_action(s, action)
    return reward_fn(s)


# 全局单例：启发式 Rollout 评分器
_ROLLOUT_SCORER = HeuristicRolloutScorer()


def _heuristic_rollout(state: GameState, depth: int,
                       reward_fn: Callable[[GameState], float]) -> float:
    """
    Rollout with heuristic opponent policy.

    Our actions: still random (exploration).
    Opponent actions: weighted random based on HeuristicRolloutScorer.

    This gives more realistic opponent behavior in rollouts while
    maintaining the stochastic diversity that MCTS needs.
    """
    s = state
    for _ in range(depth):
        game_over = check_game_over(s)
        if game_over is not None:
            break

        if s.is_opponent_turn:
            legal = enumerate_opponent_legal(s)
        else:
            legal = enumerate_legal(s)
        if not legal:
            break

        if s.is_opponent_turn and len(legal) > 1:
            action = _ROLLOUT_SCORER.select(s, legal)
        else:
            action = random.choice(legal)
        s = apply_action(s, action)
    return reward_fn(s)


# ---------------------------------------------------------------------------
# MCTS UCT Engine
# ---------------------------------------------------------------------------

class MCTSUCT:
    """
    Upper Confidence Bounds applied to Trees (UCT) search.
    """

    def __init__(self, config: Optional[MCTSConfig] = None,
                 reward_fn: Optional[Callable[[GameState], float]] = None):
        self.config = config or MCTSConfig()
        self.reward_fn = reward_fn or _default_reward

    # ------------------------------------------------------------------ public

    def search(self, state: GameState) -> MCTSResult:
        """Run UCT search from root_state. Returns the best action found."""
        root = MCTSNode(state=state, action=None)
        root.untried_actions = self._legal_actions(state)
        root.config = self.config  # stash config on root for child access
        root.is_terminal = check_game_over(state) is not None
        root.turn_depth = 0
        root.is_player_turn = not state.is_opponent_turn

        start_time = time.monotonic()
        deadline = start_time + self.config.time_budget_s

        iteration = 0
        max_depth_reached = 0
        max_turn_depth = 0

        while iteration < self.config.iterations:
            if time.monotonic() >= deadline:
                if self.config.verbose:
                    print(f"[MCTS] Stopped after {iteration} iterations "
                          f"(time budget {self.config.time_budget_ms}ms)")
                break

            node = self._select(root, iteration, self.config.iterations)
            if node is None:
                break

            if not node.is_terminal and node.untried_actions:
                node = self._expand(node)
                if node is None:
                    break

            reward = self._simulate(node)
            self._backpropagate(node, reward)

            if node.depth > max_depth_reached:
                max_depth_reached = node.depth
            if node.turn_depth > max_turn_depth:
                max_turn_depth = node.turn_depth
            iteration += 1

        # Build result
        result = self._build_result(root, iteration, max_depth_reached,
                                    time.monotonic() - start_time)

        # Extract best sequence: follow the greedy visit-count path from root
        if result.best_node:
            seq: List[Action] = []
            current = root
            while current.children:
                best_child = max(current.children, key=lambda c: c.visit_count)
                seq.append(best_child.action)
                current = best_child
            result.best_sequence = seq

        if self.config.verbose:
            print(f"[MCTS] {iteration} iter | {result.num_nodes} nodes | "
                  f"depth={max_depth_reached} | turns={max_turn_depth} | "
                  f"best={result.best_action.describe() if result.best_action else 'N/A'}")

        return result

    def search_with_timeout(self, state: GameState,
                            time_budget_ms: int) -> MCTSResult:
        """Convenience: override time budget and search."""
        cfg = MCTSConfig(
            exploration_constant=self.config.exploration_constant,
            time_budget_ms=time_budget_ms,
            rollout_depth=self.config.rollout_depth,
            use_heuristic_rollout=self.config.use_heuristic_rollout,
            max_turns_ahead=self.config.max_turns_ahead,
            max_opponent_tree_actions=self.config.max_opponent_tree_actions,
            verbose=self.config.verbose,
            rave_weight=self.config.rave_weight,
            exploration_decay=self.config.exploration_decay,
            exploration_min=self.config.exploration_min,
            use_evaluator_reward=self.config.use_evaluator_reward,
            discount_factor=self.config.discount_factor,
        )
        engine = MCTSUCT(cfg, self.reward_fn)
        return engine.search(state)

    def predict_opponent_turn(self, state: GameState,
                              time_budget_ms: int = 500,
                              iterations: int = 200) -> Optional[Action]:
        """Predict the opponent's most likely action by running MCTS
        with the opponent as the root player.

        Call this when state.is_opponent_turn is True to predict what
        the opponent will do. The opponent's actions are explored in
        the tree, and the most-visited action is returned.

        The reward function is INVERTED (opponent's perspective) so
        MCTS finds the action the opponent would think is best.

        Returns None if no legal opponent actions exist.
        """
        if not state.is_opponent_turn:
            log.debug("predict_opponent_turn called on player turn, skipping")
            return None

        legal = enumerate_opponent_legal(state)
        if not legal:
            return None

        # Use opponent-perspective reward (negate our default reward)
        def opponent_reward(s: GameState) -> float:
            return -self.reward_fn(s)

        cfg = MCTSConfig(
            exploration_constant=self.config.exploration_constant,
            iterations=iterations,
            time_budget_ms=time_budget_ms,
            rollout_depth=self.config.rollout_depth,
            use_heuristic_rollout=self.config.use_heuristic_rollout,
            max_turns_ahead=1,
            max_opponent_tree_actions=10,
            expand_all_children=True,
            verbose=False,
            rave_weight=self.config.rave_weight,
            exploration_decay=self.config.exploration_decay,
            exploration_min=self.config.exploration_min,
            use_evaluator_reward=self.config.use_evaluator_reward,
            discount_factor=self.config.discount_factor,
        )
        engine = MCTSUCT(cfg, opponent_reward)
        result = engine.search(state)

        if result.best_action:
            return result.best_action
        return None

    # ------------------------------------------------------------------ steps

    def _select(self, node: MCTSNode,
                iteration: int = 0, total_iterations: int = 0) -> Optional[MCTSNode]:
        """TREE POLICY: traverse to the most promising expandable node."""
        current = node
        while not current.is_terminal and not current.untried_actions:
            if not current.children:
                return current
            current = current.best_child(iteration, total_iterations)
            if current is None:
                return None
        return current

    def _expand(self, node: MCTSNode) -> Optional[MCTSNode]:
        """Expand one untried action, returning the new child node.

        Tracks turn_depth (number of OUR turns explored) and
        is_player_turn. Expansion is limited by max_turns_ahead:
        - We always expand the first turn (turn_depth=0)
        - Opponent turn nodes are always expanded (they're "free" depth)
        - Additional OUR turns are only expanded if turn_depth < max_turns_ahead

        我方回合动作按启发式排序：出牌 > 攻击 > 英雄技能 > 结束回合，
        优先扩展高价值动作，提高搜索效率。
        """
        if not node.untried_actions:
            return None

        # 我方回合：按启发式排序，优先扩展高价值动作
        if node.is_player_turn and len(node.untried_actions) > 1:
            node.untried_actions = self._sort_actions(node.untried_actions, node.state)

        action = node.untried_actions.pop()
        try:
            next_state = apply_action(node.state, action)
        except Exception as exc:
            if self.config.verbose:
                print(f"[MCTS] apply_action failed: {action} → {exc}")
            return node

        child_turn_depth = node.turn_depth
        child_is_player = not next_state.is_opponent_turn

        if child_is_player and not node.is_player_turn:
            child_turn_depth = node.turn_depth + 1

        child = MCTSNode(
            state=next_state,
            action=action,
            parent=node,
            depth=node.depth + 1,
            is_terminal=check_game_over(next_state) is not None,
            turn_depth=child_turn_depth,
            is_player_turn=child_is_player,
        )

        if child_is_player and child_turn_depth >= self.config.max_turns_ahead:
            child.untried_actions = []
        else:
            actions = self._legal_actions(next_state)
            if not child_is_player and len(actions) > self.config.max_opponent_tree_actions:
                opp_actions = [a for a in actions if a.action_type == ActionKind.END_TURN]
                opp_actions += [a for a in actions if a.action_type == ActionKind.HERO_POWER]
                attack_actions = [a for a in actions if a.action_type == ActionKind.ATTACK]
                opp_actions += attack_actions[:self.config.max_opponent_tree_actions - len(opp_actions)]
                child.untried_actions = opp_actions
            else:
                child.untried_actions = actions

        child.config = self.config

        node.children.append(child)

        if self.config.expand_all_children and child.untried_actions:
            for a in list(node.untried_actions):
                node.untried_actions.remove(a)
                try:
                    s = apply_action(node.state, a)
                except Exception:
                    continue

                td = node.turn_depth
                ipt = not s.is_opponent_turn
                if ipt and not node.is_player_turn:
                    td = node.turn_depth + 1

                if ipt and td >= self.config.max_turns_ahead:
                    continue

                c = MCTSNode(
                    state=s,
                    action=a,
                    parent=node,
                    depth=node.depth + 1,
                    is_terminal=check_game_over(s) is not None,
                    turn_depth=td,
                    is_player_turn=ipt,
                )
                c.untried_actions = self._legal_actions(s) if not (ipt and td >= self.config.max_turns_ahead) else []
                c.config = self.config
                node.children.append(c)

        return child

    def _simulate(self, node: MCTSNode) -> float:
        """DEFAULT POLICY: run a rollout from node state, return reward."""
        if self.config.use_heuristic_rollout:
            return _heuristic_rollout(node.state, self.config.rollout_depth,
                                       self.reward_fn)
        return _random_rollout(node.state, self.config.rollout_depth,
                                self.reward_fn)

    def _backpropagate(self, node: MCTSNode, reward: float) -> None:
        """Backpropagate reward up the tree to the root.

        1. 标准反向传播：每个祖先累加 reward
        2. 衰减因子：深层节点的 reward 按 discount_factor^depth 折扣
        3. RAVE 更新：同层级兄弟节点共享全局动作统计
        """
        discount = self.config.discount_factor
        current = node
        depth = 0
        while current is not None:
            current.visit_count += 1
            # 衰减：越深的祖先折扣越小（但 root 永远是全值）
            discounted_reward = reward * (discount ** depth) if depth > 0 else reward
            current.total_reward += discounted_reward

            # RAVE 更新：同层级兄弟节点共享动作统计
            if current.parent is not None:
                for sibling in current.parent.children:
                    if sibling is not current:
                        sibling.rave_visit_count += 1
                        sibling.rave_total_reward += discounted_reward

            current = current.parent
            depth += 1

    # --------------------------------------------------------------- helpers

    def _sort_actions(self, actions: List[Action], state: GameState) -> List[Action]:
        """我方动作启发式排序：高优先级放末尾（pop 先取）。

        优先级（高→低）：
          PLAY/PLAY_WITH_TARGET > CHOOSE_ONE > DISCOVER_PICK >
          ATTACK > HERO_POWER > ACTIVATE_LOCATION > HERO_REPLACE >
          TRANSFORM > END_TURN > PASS

        同类内部再按子启发式排序（如出牌按卡牌分数、攻击按目标价值）。
        """
        _PRIORITY = {
            ActionKind.PLAY: 80,
            ActionKind.PLAY_WITH_TARGET: 80,
            ActionKind.CHOOSE_ONE: 70,
            ActionKind.DISCOVER_PICK: 65,
            ActionKind.ATTACK: 50,
            ActionKind.HERO_POWER: 40,
            ActionKind.ACTIVATE_LOCATION: 35,
            ActionKind.HERO_REPLACE: 30,
            ActionKind.TRANSFORM: 20,
            ActionKind.END_TURN: 10,
            ActionKind.PASS: 5,
        }

        def _action_key(a: Action) -> Tuple[int, float]:
            base = _PRIORITY.get(a.action_type, 15)
            sub = 0.0

            if a.action_type in (ActionKind.PLAY, ActionKind.PLAY_WITH_TARGET):
                if 0 <= a.card_index < len(state.hand):
                    card = state.hand[a.card_index]
                    sub = getattr(card, "score", 0.0) or 0.0
                    if getattr(card, "card_type", "") == "MINION":
                        sub += 1.0
                    if getattr(card, "mechanics", None):
                        mechs = card.mechanics or []
                        if "RUSH" in mechs or "CHARGE" in mechs:
                            sub += 2.0
                        if "TAUNT" in mechs:
                            sub += 1.5
                        if "BATTLECRY" in mechs:
                            sub += 1.0
                    eff_cost = state.effective_cost(card) if hasattr(state, "effective_cost") else getattr(card, "cost", 0)
                    if eff_cost <= state.mana.available:
                        sub += 0.5

            elif a.action_type == ActionKind.ATTACK:
                if 0 <= a.target_index < len(state.opponent.board):
                    target = state.opponent.board[a.target_index]
                    sub = (target.attack + target.health) * 0.1
                    if target.health <= 0:
                        sub += 5.0
                elif a.target_index == -1:
                    sub = 3.0

            elif a.action_type == ActionKind.HERO_POWER:
                sub = 1.0

            return (base, sub)

        return sorted(actions, key=_action_key)

    def _legal_actions(self, state: GameState) -> List[Action]:
        """Get legal actions, dispatched by whose turn it is.

        When state.is_opponent_turn is True, uses opponent.hand and
        opponent.board for action generation — creating genuine
        prediction diversity across worlds with different opponent.hand
        content during MCTS rollouts.
        """
        try:
            if state.is_opponent_turn:
                actions = enumerate_opponent_legal(state)
            else:
                actions = enumerate_legal(state)
        except Exception:
            return []
        # Filter END_TURN during early search depth (encourage exploration)
        # but keep it as a last-resort option
        return actions

    def _build_result(self, root: MCTSNode, iterations: int,
                      max_depth: int, elapsed: float) -> MCTSResult:
        """Assemble the search result from the completed tree."""
        action_values: Dict[str, float] = {}
        visit_counts: Dict[str, int] = {}

        for child in root.children:
            desc = child.action.describe() if child.action else "UNKNOWN"
            action_values[desc] = child.q_value
            visit_counts[desc] = child.visit_count

        best_action, best_node = None, None
        if root.children:
            pair = root.best_action_child()
            if pair:
                best_action, best_node = pair

        num_nodes = self._count_nodes(root)

        return MCTSResult(
            best_action=best_action,
            best_node=best_node,
            root_node=root,
            action_values=action_values,
            visit_counts=visit_counts,
            search_stats={
                "iterations": iterations,
                "max_depth": max_depth,
                "time_s": round(elapsed, 3),
                "num_nodes": num_nodes,
                "config_exploration": self.config.exploration_constant,
                "config_iterations": self.config.iterations,
                "max_turns_ahead": self.config.max_turns_ahead,
            },
            num_nodes=num_nodes,
            tree_depth=max_depth,
        )

    @staticmethod
    def _count_nodes(node: MCTSNode) -> int:
        """Count total nodes in the tree."""
        count = 1
        for child in node.children:
            count += MCTSUCT._count_nodes(child)
        return count

"""
对手动作评分策略 (Opponent Action Scoring Strategies)

Strategy Pattern: 统一对手动作评分的接口，
允许消费者（MCTS rollout, 手牌推断）切换不同的评分策略。

- HeuristicRolloutScorer:  加权随机采样，用于 MCTS rollout 阶段的对手行为模拟
- GreedyActionScorer:      贪心最优动作选择，用于对手手牌推断的场景评分
"""

from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from typing import List, Optional

from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 抽象策略接口
# ═══════════════════════════════════════════════════════════


class OpponentScorer(ABC):
    """对手动作评分抽象策略"""

    @abstractmethod
    def score(self, state: GameState, action: Action) -> float:
        """返回 action 在 state 下的评分（越高表示越可能被对手选中）"""
        ...

    def select(self, state: GameState, actions: List[Action]) -> Optional[Action]:
        """从动作列表中选择最佳动作（默认实现：按 score 加权随机）"""
        if not actions:
            return None
        scores = [self.score(state, a) for a in actions]
        total = sum(scores)
        if total > 0:
            weights = [sc / total for sc in scores]
            return random.choices(actions, weights=weights)[0]
        return random.choice(actions)


# ═══════════════════════════════════════════════════════════
# 策略 1: 启发式加权 Rollout 评分
# 来源: analysis/engine/mcts_uct.py — _score_opponent_action()
# ═══════════════════════════════════════════════════════════


class HeuristicRolloutScorer(OpponentScorer):
    """启发式对手动作评分，用于 MCTS rollout 阶段的加权随机采样。

    评分逻辑:
    - 有利交换: 高效消灭我方随从
    - 优势打脸: 无嘲讽时高攻打脸
    - 出牌: 优先低费（曲线效率）
    - 英雄技能: 中等优先级
    - 结束回合: 最低优先级
    """

    def score(self, state: GameState, action: Action) -> float:
        if action.action_type == ActionKind.END_TURN:
            return 0.1

        if action.action_type == ActionKind.HERO_POWER:
            return 25.0

        if action.action_type == ActionKind.ATTACK:
            return self._score_attack(state, action)

        if action.action_type in (ActionKind.PLAY, ActionKind.PLAY_WITH_TARGET):
            return self._score_play_card(state, action)

        return 10.0

    def _score_attack(self, state: GameState, action: Action) -> float:
        src_idx = action.source_index
        if src_idx < 0 or src_idx >= len(state.opponent.board):
            return 5.0
        source = state.opponent.board[src_idx]
        score = 10.0

        tgt_idx = action.target_index
        if tgt_idx == 0:
            our_taunts = [m for m in state.board if m.has_taunt]
            if our_taunts:
                score = 1.0
            else:
                score = 15.0 + source.attack
        elif tgt_idx > 0:
            our_idx = tgt_idx - 1
            if our_idx < len(state.board):
                target = state.board[our_idx]
                if target.attack >= source.health:
                    score = 30.0
                elif source.attack >= target.health:
                    if source.health > target.attack:
                        score = 35.0
                    else:
                        score = 25.0
                else:
                    score = 20.0
                if target.has_divine_shield:
                    score += 10.0
                score += target.attack * 0.5
        return max(0.1, score)

    def _score_play_card(self, state: GameState, action: Action) -> float:
        card_idx = action.card_index
        if card_idx < 0 or card_idx >= len(state.opponent.hand):
            return 5.0
        card = state.opponent.hand[card_idx]
        cost = getattr(card, 'cost', 0)
        card_type = (getattr(card, 'card_type', '') or '').upper()

        score = 20.0 - cost * 0.5

        if card_type == 'MINION':
            atk = getattr(card, 'attack', 0)
            hp = getattr(card, 'health', 0)
            score += (atk + hp) * 0.3
            mechanics = set(getattr(card, 'mechanics', []) or [])
            if 'RUSH' in mechanics or 'CHARGE' in mechanics:
                score += 8.0
        elif card_type == 'SPELL':
            score += 5.0

        return max(0.1, score)


# ═══════════════════════════════════════════════════════════
# 策略 2: 贪心最优动作选择
# 来源: analysis/engine/opponent_hand_mcts.py — _select_best_action() + _evaluate_state()
# ═══════════════════════════════════════════════════════════


class GreedyActionScorer(OpponentScorer):
    """贪心最优动作选择器，用于对手手牌推断的场景模拟。

    评估维度:
    1. 场面价值（随从总属性的变化）
    2. 伤害效率（打脸伤害）
    3. 法力效率（消耗法力越多的动作权重越高）

    优先使用 CompositeEvaluator，回退到简单启发式。
    """

    def __init__(self):
        self._use_evaluator = False
        self._evaluate_delta = None
        self._try_load_evaluator()

    def _try_load_evaluator(self):
        try:
            from analysis.evaluators.composite import evaluate_delta
            self._evaluate_delta = evaluate_delta
            self._use_evaluator = True
        except ImportError:
            pass

    def score(self, state: GameState, action: Action) -> float:
        if action.action_type == ActionKind.END_TURN:
            return 0.0

        try:
            from analysis.card.engine.simulation import apply_action

            new_state = apply_action(state, action)
            if self._use_evaluator and self._evaluate_delta is not None:
                return self._evaluate_delta(state, new_state)

            return self._heuristic_score(new_state, state)
        except Exception:
            return float('-inf')

    def select(self, state: GameState, actions: List[Action]) -> Optional[Action]:
        """贪心选择：遍历动作取评分最高的一个"""
        if not actions:
            return None

        non_end = [a for a in actions if a.action_type != ActionKind.END_TURN]
        if not non_end:
            return actions[0]

        best_action = None
        best_score = float('-inf')

        for action in non_end[:15]:
            score = self.score(state, action)
            if score > best_score:
                best_score = score
                best_action = action

        if best_action is None or best_score < 0:
            end_turns = [a for a in actions if a.action_type == ActionKind.END_TURN]
            if end_turns:
                return end_turns[0]

        return best_action or non_end[0]

    @staticmethod
    def _heuristic_score(new_state: GameState, old_state: GameState) -> float:
        """简单启发式评分（回退方案）。"""
        score = 0.0

        our_board_value = sum(m.attack + m.health for m in new_state.board)
        old_board_value = sum(m.attack + m.health for m in old_state.board)
        score += (our_board_value - old_board_value) * 0.5

        opp_hp_change = new_state.opponent.hero.hp - old_state.opponent.hero.hp
        score += max(0, -opp_hp_change) * 1.0

        mana_used = old_state.mana.available - new_state.mana.available
        score += mana_used * 0.3

        score += len(new_state.board) * 0.5

        return score

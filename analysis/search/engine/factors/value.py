from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class ValueFactor(EvaluationFactor):
    def name(self) -> str:
        return "value"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_before = len(state_before.hand) + len(state_before.board)
        enemy_before = state_before.opponent.hand_count + len(state_before.opponent.board)
        friend_after = len(state_after.hand) + len(state_after.board)
        enemy_after = state_after.opponent.hand_count + len(state_after.opponent.board)

        card_adv_delta = (friend_after - enemy_after) - (friend_before - enemy_before)

        draw_delta = len(state_after.hand) - len(state_before.hand)
        cards_played = len(state_after.cards_played_this_turn) - len(state_before.cards_played_this_turn)
        net_cards = draw_delta + cards_played

        quality_delta = self._quality_delta(state_before, state_after)

        raw = card_adv_delta * 0.5 + net_cards * 0.3 + quality_delta * 0.2
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 1.3
        if context.phase == Phase.EARLY:
            return 0.6
        return 1.0

    @staticmethod
    def _quality_delta(state_before: GameState, state_after: GameState) -> float:
        before_q = sum(getattr(c, 'score', 3.0) for c in state_before.hand)
        after_q = sum(getattr(c, 'score', 3.0) for c in state_after.hand)

        before_count = max(len(state_before.hand), 1)
        after_count = max(len(state_after.hand), 1)

        before_avg = before_q / before_count
        after_avg = after_q / after_count

        delta = after_avg - before_avg
        return max(-1.0, min(1.0, delta / 3.0))

"""ValueFactor — resource quantity and card advantage."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action
from hs_analysis.search.engine.factors.factor_base import (
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

        raw = card_adv_delta * 0.5 + net_cards * 0.3
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 1.3
        if context.phase == Phase.EARLY:
            return 0.6
        return 1.0

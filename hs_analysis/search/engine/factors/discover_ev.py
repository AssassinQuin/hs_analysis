"""DiscoverEVFactor — expected value of discover/generation effects."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action
from hs_analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor,
)


class DiscoverEVFactor(EvaluationFactor):
    def name(self) -> str:
        return "discover_ev"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        hand_delta = len(state_after.hand) - len(state_before.hand)

        cards_played = len(state_after.cards_played_this_turn) - len(state_before.cards_played_this_turn)
        net_generation = hand_delta + cards_played

        if net_generation <= 0:
            return 0.0

        try:
            from hs_analysis.evaluators.siv import siv_score
            new_cards_score = 0.0
            before_ids = {getattr(c, "dbf_id", id(c)) for c in state_before.hand}
            for card in state_after.hand:
                cid = getattr(card, "dbf_id", id(card))
                if cid not in before_ids:
                    new_cards_score += siv_score(card, state_after) * 0.1
            return max(-1.0, min(1.0, new_cards_score))
        except Exception:
            return min(0.5, net_generation * 0.15)

    def weight(self, context: EvalContext) -> float:
        return 0.6

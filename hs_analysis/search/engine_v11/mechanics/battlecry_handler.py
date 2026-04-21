"""BattlecryHandler — wraps V10 battlecry_dispatcher."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class BattlecryHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        if (context.card.card_type or "").upper() != "MINION":
            return state
        try:
            from hs_analysis.search.battlecry_dispatcher import dispatch_battlecry
            return dispatch_battlecry(state, context.card, context.source_minion)
        except Exception:
            return state

    def priority(self) -> int:
        return 50

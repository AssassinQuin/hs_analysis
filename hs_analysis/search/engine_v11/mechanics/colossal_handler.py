"""ColossalHandler — wraps V10 colossal appendage summoning."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class ColossalHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None or context.source_minion is None:
            return state
        if (context.card.card_type or "").upper() != "MINION":
            return state
        try:
            from hs_analysis.search.colossal import parse_colossal_value, summon_colossal_appendages
            if parse_colossal_value(context.card) > 0:
                pos = context.action.position if context.action else 0
                return summon_colossal_appendages(
                    state, context.source_minion, context.card,
                    pos, state.herald_count,
                )
        except Exception:
            pass
        return state

    def priority(self) -> int:
        return 20

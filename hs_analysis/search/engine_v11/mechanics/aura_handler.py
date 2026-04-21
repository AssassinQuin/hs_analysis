"""AuraHandler — wraps V10 aura engine recomputation."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class AuraHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        try:
            from hs_analysis.search.aura_engine import recompute_auras
            return recompute_auras(state)
        except Exception:
            return state

    def priority(self) -> int:
        return 90

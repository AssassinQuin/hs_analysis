"""DeathrattleHandler — wraps V10 deathrattle resolver."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class DeathrattleHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_death"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        try:
            from hs_analysis.search.deathrattle import resolve_deaths
            return resolve_deaths(state)
        except Exception:
            return state

    def priority(self) -> int:
        return 10

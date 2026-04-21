"""DiscoverHandler — wraps V10 discover module."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class DiscoverHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        card_text = getattr(context.card, "text", "") or ""
        if "发现" not in card_text and "discover" not in card_text.lower():
            return state
        try:
            from hs_analysis.search.discover import resolve_discover
            return resolve_discover(state, context.card)
        except Exception:
            return state

    def priority(self) -> int:
        return 55

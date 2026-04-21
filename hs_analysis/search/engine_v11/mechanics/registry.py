"""MechanicRegistry — dispatch mechanic handlers by trigger point and keyword."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)

_TRIGGER_ORDER = {
    "on_play": [
        "outcast", "colossal", "kindred", "battlecry", "choose_one",
        "dormant", "herald", "trigger_on_play", "aura",
    ],
    "on_attack": ["trigger_on_attack", "secret_on_attack"],
    "on_death": ["deathrattle", "corpse", "reborn", "trigger_on_death"],
    "on_spell_cast": ["trigger_on_spell", "quest"],
    "on_turn_end": ["trigger_on_turn_end", "enchantment_tick"],
    "on_turn_start": ["trigger_on_turn_start", "overload_recover"],
    "on_draw": ["shatter", "corrupt"],
    "on_heal": ["trigger_on_heal"],
    "on_damage": ["trigger_on_damage"],
}


class MechanicRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, List[MechanicHandler]] = defaultdict(list)
        self._keyword_map: Dict[str, str] = {}

    def register(self, keyword: str, handler: MechanicHandler) -> None:
        if not handler.enabled():
            return
        tp = handler.trigger_point()
        self._handlers[tp].append(handler)
        self._handlers[tp].sort(key=lambda h: h.priority())
        self._keyword_map[handler.__class__.__name__] = keyword

    def dispatch(self, trigger: str, state: GameState,
                 context: ActionContext) -> GameState:
        handlers = self._handlers.get(trigger, [])
        order = _TRIGGER_ORDER.get(trigger, [])
        ordered = self._sort_by_order(handlers, order)
        for handler in ordered:
            try:
                state = handler.apply(state, context)
            except Exception:
                continue
        return state

    def dispatch_all(self, triggers: List[str], state: GameState,
                     context: ActionContext) -> GameState:
        for trigger in triggers:
            state = self.dispatch(trigger, state, context)
        return state

    @staticmethod
    def _sort_by_order(handlers: List[MechanicHandler],
                       order: List[str]) -> List[MechanicHandler]:
        if not order:
            return handlers
        result: List[MechanicHandler] = []
        remaining: List[MechanicHandler] = list(handlers)
        for keyword in order:
            matched = [h for h in remaining
                       if keyword in h.__class__.__name__.lower()]
            for h in matched:
                result.append(h)
                remaining.remove(h)
        result.extend(remaining)
        return result

    def registered_triggers(self) -> List[str]:
        return list(self._handlers.keys())

    def handler_count(self) -> int:
        return sum(len(v) for v in self._handlers.values())

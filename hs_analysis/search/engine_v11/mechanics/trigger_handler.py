"""TriggerHandler — wraps V10 trigger system dispatcher."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class TriggerOnPlayHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.source_minion is None:
            return state
        try:
            from hs_analysis.search.trigger_system import TriggerDispatcher
            return TriggerDispatcher().on_minion_played(
                state, context.source_minion, context.card,
            )
        except Exception:
            return state

    def priority(self) -> int:
        return 70


class TriggerOnDeathHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_death"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        try:
            from hs_analysis.search.trigger_system import TriggerDispatcher
            return TriggerDispatcher().on_minion_dies(state, context.source_minion)
        except Exception:
            return state

    def priority(self) -> int:
        return 20


class TriggerOnAttackHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_attack"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.source_minion is None:
            return state
        try:
            from hs_analysis.search.trigger_system import TriggerDispatcher
            return TriggerDispatcher().on_attack(state, context.source_minion)
        except Exception:
            return state

    def priority(self) -> int:
        return 10


class TriggerOnSpellHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_spell_cast"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        try:
            from hs_analysis.search.trigger_system import TriggerDispatcher
            return TriggerDispatcher().on_spell_cast(state, context.card)
        except Exception:
            return state

    def priority(self) -> int:
        return 10

"""Mechanic handlers for V10 Phase 3 mechanics (outcast, kindred, herald, quest, imbue, dormant)."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.engine_v11.mechanics.handler_base import (
    ActionContext, MechanicHandler,
)


class OutcastHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        card_idx = context.action.card_index
        try:
            from hs_analysis.search.outcast import check_outcast, apply_outcast_bonus
            if check_outcast(state, card_idx, context.card):
                return apply_outcast_bonus(state, card_idx, context.card)
        except Exception:
            pass
        return state

    def priority(self) -> int:
        return 15


class KindredHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        try:
            from hs_analysis.search.kindred import apply_kindred
            return apply_kindred(state, context.card)
        except Exception:
            return state

    def priority(self) -> int:
        return 22


class HeraldHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        try:
            from hs_analysis.search.herald import check_herald, apply_herald
            if check_herald(context.card):
                return apply_herald(state, context.card)
        except Exception:
            pass
        return state

    def priority(self) -> int:
        return 60


class QuestHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_spell_cast"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        try:
            from hs_analysis.search.quest import track_quest_progress
            return track_quest_progress(state, "PLAY", context.card)
        except Exception:
            return state

    def priority(self) -> int:
        return 50


class ImbueHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None:
            return state
        try:
            from hs_analysis.search.imbue import apply_imbue
            return apply_imbue(state, context.card)
        except Exception:
            return state

    def priority(self) -> int:
        return 65


class DormantHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        if context.card is None or context.source_minion is None:
            return state
        try:
            from hs_analysis.search.dormant import is_dormant_card, apply_dormant
            if is_dormant_card(context.card):
                context.source_minion = apply_dormant(context.source_minion, context.card)
        except Exception:
            pass
        return state

    def priority(self) -> int:
        return 35

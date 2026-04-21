"""LethalThreatFactor — can we kill the opponent this or next turn."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action
from hs_analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor,
)


class LethalThreatFactor(EvaluationFactor):
    def name(self) -> str:
        return "lethal_threat"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        opp = state_after.opponent.hero
        opp_hp = opp.hp + opp.armor
        if opp_hp <= 0:
            return 1.0

        max_dmg = self._max_damage(state_after)
        ratio = max_dmg / max(opp_hp, 1)
        if ratio >= 1.0:
            return 0.8
        if ratio >= 0.5:
            return 0.3 * ratio
        return 0.0

    @staticmethod
    def _max_damage(state: GameState) -> int:
        dmg = sum(m.attack for m in state.board if m.can_attack)
        for m in state.board:
            if m.has_windfury and m.can_attack:
                dmg += m.attack
        if state.hero.weapon is not None:
            dmg += state.hero.weapon.attack
        return dmg

    def weight(self, context: EvalContext) -> float:
        if context.phase == "late":
            return 2.0
        if context.phase == "mid":
            return 1.5
        return 1.0

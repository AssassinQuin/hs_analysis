"""SurvivalFactor — hero health and safety."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action
from hs_analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class SurvivalFactor(EvaluationFactor):
    def name(self) -> str:
        return "survival"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        hero_hp_after = state_after.hero.hp + state_after.hero.armor
        hero_hp_before = state_before.hero.hp + state_before.hero.armor
        hp_delta = hero_hp_after - hero_hp_before

        enemy_damage_potential = sum(
            m.attack for m in state_after.opponent.board
            if m.can_attack or m.has_charge or m.has_rush
        )
        if state_after.opponent.hero.weapon is not None:
            enemy_damage_potential += state_after.opponent.hero.weapon.attack

        danger = 0.0
        if enemy_damage_potential >= hero_hp_after:
            danger = -0.8
        elif enemy_damage_potential >= hero_hp_after * 0.7:
            danger = -0.4

        hp_change_norm = hp_delta / 30.0
        raw = max(-1.0, min(1.0, hp_change_norm)) + danger
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 1.8
        if context.phase == Phase.MID:
            return 1.2
        return 0.8

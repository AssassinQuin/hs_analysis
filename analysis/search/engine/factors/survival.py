"""SurvivalFactor — hero health and safety."""

from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.search.rhea_engine import Action
from analysis.search.engine.factors.factor_base import (
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

        spell_threat = self._opponent_spell_damage_threat(state_after)
        enemy_damage_potential += spell_threat

        taunt_protection = self._taunt_protection_value(state_after)
        effective_enemy_dmg = max(0, enemy_damage_potential - taunt_protection)

        danger = 0.0
        if effective_enemy_dmg >= hero_hp_after:
            danger = -0.8
        elif effective_enemy_dmg >= hero_hp_after * 0.7:
            danger = -0.4
        elif effective_enemy_dmg >= hero_hp_after * 0.5:
            danger = -0.15

        hp_change_norm = hp_delta / 30.0
        raw = max(-1.0, min(1.0, hp_change_norm)) + danger
        return max(-1.0, min(1.0, raw))

    @staticmethod
    def _taunt_protection_value(state: GameState) -> float:
        total = 0.0
        for m in state.board:
            if m.has_taunt:
                effective_health = m.health
                if m.has_divine_shield:
                    effective_health += m.attack
                if getattr(m, 'has_reborn', False):
                    effective_health += m.health * 0.5
                total += effective_health
        return total

    @staticmethod
    def _opponent_spell_damage_threat(state: GameState) -> int:
        threat = 0
        opp_hand_count = len(state.opponent.hand) if hasattr(state.opponent, 'hand') else 0
        if opp_hand_count == 0:
            return 0
        estimated_spell_count = max(1, opp_hand_count // 3)
        estimated_damage_per_spell = 2
        return estimated_spell_count * estimated_damage_per_spell

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 1.8
        if context.phase == Phase.MID:
            return 1.2
        return 0.8

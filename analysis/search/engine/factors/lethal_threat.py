from __future__ import annotations

import re

from analysis.search.game_state import GameState
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
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
        spell_dmg = self._hand_spell_damage(state_after)
        hero_power_dmg = self._hero_power_damage(state_after)
        total_dmg = max_dmg + spell_dmg + hero_power_dmg

        ratio = total_dmg / max(opp_hp, 1)
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

    @staticmethod
    def _hand_spell_damage(state: GameState) -> int:
        total = 0
        available = state.mana.available
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() != 'SPELL':
                continue
            cost = getattr(card, 'cost', 0)
            if cost > available:
                continue
            text = getattr(card, 'text', '') or ''
            dmg = 0
            m = re.search(r'Deal\s*\$?(\d+)\s*damage', text, re.IGNORECASE)
            if not m:
                m = re.search(r'造成\s*\$?\s*(\d+)\s*点伤害', text)
            if m:
                dmg = int(m.group(1))
                if 'all enemies' in text.lower() or '所有敌人' in text:
                    dmg = dmg * max(len(state.opponent.board), 1)
                total += dmg
                available -= cost
        return total

    @staticmethod
    def _hero_power_damage(state: GameState) -> int:
        hp_cost = state.hero.hero_power_cost
        if state.hero.hero_power_used:
            return 0
        if state.mana.available < hp_cost:
            return 0
        hero_class = state.hero.hero_class.upper() if state.hero.hero_class else ""
        if state.hero.hero_power_damage > 0:
            return state.hero.hero_power_damage
        if hero_class == "MAGE":
            return 1
        if hero_class == "HUNTER":
            return 2
        return 0

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 2.0
        if context.phase == Phase.MID:
            return 1.5
        return 1.0

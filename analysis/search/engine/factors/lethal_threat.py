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

        # Check two-turn lethal probability
        two_turn_prob = self._two_turn_lethal_probability(state_after)
        if two_turn_prob > 0:
            return two_turn_prob * 0.4  # scale down: two-turn is less certain

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

    @staticmethod
    def _two_turn_lethal_probability(state: GameState) -> float:
        """Estimate probability of achieving lethal within 2 turns.
        
        Uses heuristic estimation based on:
        - Current board damage potential (with windfury)
        - Hand spell damage (affordable this turn + next turn mana)
        - Hero power damage
        - Weapon damage
        - Expected damage from next draw (topdeck lethal)
        
        Returns float in [0.0, 1.0]:
          1.0 = lethal exists this turn (confirmed)
          0.7+ = high probability (can kill from hand + board next turn)
          0.3-0.7 = moderate probability 
          0.0 = very unlikely
        """
        # --- Turn 1 damage (current resources) ---
        board_dmg = 0
        for m in state.board:
            if m.can_attack or m.has_charge:
                board_dmg += m.attack
                if m.has_windfury:
                    board_dmg += m.attack

        spell_dmg_t1 = 0
        mana_t1 = state.mana.available
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() != 'SPELL':
                continue
            cost = getattr(card, 'cost', 0)
            if cost > mana_t1:
                continue
            text = getattr(card, 'text', '') or ''
            m = re.search(r'Deal\s*\$?(\d+)\s*damage', text, re.IGNORECASE)
            if not m:
                m = re.search(r'造成\s*\$?\s*(\d+)\s*点伤害', text)
            if m:
                spell_dmg_t1 += int(m.group(1))
                mana_t1 -= cost

        weapon_dmg = state.hero.weapon.attack if state.hero.weapon else 0
        hp_dmg = 0
        hero_class = state.hero.hero_class.upper() if state.hero.hero_class else ""
        if not state.hero.hero_power_used and state.mana.available >= state.hero.hero_power_cost:
            hp_dmg = state.hero.hero_power_damage or (1 if hero_class == "MAGE" else 2 if hero_class == "HUNTER" else 0)

        t1_total = board_dmg + spell_dmg_t1 + weapon_dmg + hp_dmg

        # --- Turn 2 damage estimate (next turn resources) ---
        # Board: same minions + those that will awaken/lose summoning sickness
        board_dmg_t2 = 0
        for m in state.board:
            # Next turn: minions that can't attack now might be able to
            can_attack_next = True
            if m.is_dormant:
                can_attack_next = False  # still dormant (simplified)
            if m.cant_attack:
                can_attack_next = False
            if can_attack_next:
                board_dmg_t2 += m.attack
                if m.has_windfury:
                    board_dmg_t2 += m.attack

        # New minion from hand (estimate: average 3 attack for a playable minion)
        next_mana = min(state.mana.max_mana + 1, 10)
        estimated_new_minion_atk = 0
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() == 'MINION':
                cost = getattr(card, 'cost', 0)
                if cost <= next_mana:
                    atk = getattr(card, 'attack', 0)
                    if atk > estimated_new_minion_atk:
                        estimated_new_minion_atk = atk

        # Spell damage next turn (full mana available)
        spell_dmg_t2 = 0
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() != 'SPELL':
                continue
            cost = getattr(card, 'cost', 0)
            if cost > next_mana:
                continue
            text = getattr(card, 'text', '') or ''
            m = re.search(r'Deal\s*\$?(\d+)\s*damage', text, re.IGNORECASE)
            if not m:
                m = re.search(r'造成\s*\$?\s*(\d+)\s*点伤害', text)
            if m:
                spell_dmg_t2 += int(m.group(1))

        t2_total = board_dmg_t2 + estimated_new_minion_atk + spell_dmg_t2 + hp_dmg

        # Topdeck bonus: ~2 damage per card in deck (rough estimate)
        deck_size = getattr(state, 'deck_remaining', 0) or 10  # default assumption
        topdeck_bonus = min(3, deck_size * 0.15)  # up to 3 extra damage expected from draw

        opp_hp = state.opponent.hero.hp + state.opponent.hero.armor

        # Turn 1 lethal = 1.0
        if t1_total >= opp_hp:
            return 1.0

        # Two-turn lethal estimate
        two_turn_dmg = t1_total + t2_total + topdeck_bonus
        ratio = two_turn_dmg / max(opp_hp, 1)

        if ratio >= 1.0:
            return 0.7  # high probability two-turn lethal
        if ratio >= 0.7:
            return 0.5  # moderate probability
        if ratio >= 0.4:
            return 0.2  # low probability but possible
        return 0.0

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 2.0
        if context.phase == Phase.MID:
            return 1.5
        return 1.0

"""Evaluation factors for Hearthstone search engine.

Decomposable multi-factor evaluation: each factor implements EvaluationFactor
and is registered with FactorGraphEvaluator for combined scoring.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analysis.card.abilities.definition import Action
from analysis.card.engine.state import GameState, Minion
from analysis.models import Phase, detect_phase


# ===================================================================
# EvalContext + EvaluationFactor (base)
# ===================================================================

@dataclass
class EvalContext:
    phase: Phase = Phase.MID
    turn_number: int = 5
    is_lethal: bool = False
    time_budget_ms: float = 100.0

    @staticmethod
    def from_state(state: GameState) -> EvalContext:
        tn = state.turn_number
        return EvalContext(phase=detect_phase(tn), turn_number=tn)


class EvaluationFactor(ABC):

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, state_before: GameState, state_after: GameState,
                action: Optional[Action], context: EvalContext) -> float:
        ...

    def weight(self, context: EvalContext) -> float:
        return 1.0


# ===================================================================
# FactorScores + FactorGraphEvaluator (orchestrator)
# ===================================================================

@dataclass
class FactorScores:
    board_control: float = 0.0
    lethal_threat: float = 0.0
    tempo: float = 0.0
    value: float = 0.0
    survival: float = 0.0
    resource_efficiency: float = 0.0
    discover_ev: float = 0.0
    total: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "board_control": self.board_control,
            "lethal_threat": self.lethal_threat,
            "tempo": self.tempo,
            "value": self.value,
            "survival": self.survival,
            "resource_efficiency": self.resource_efficiency,
            "discover_ev": self.discover_ev,
            "total": self.total,
        }

    def describe(self) -> str:
        parts = []
        for k, v in self.as_dict().items():
            if k != "total" and abs(v) > 0.01:
                parts.append(f"{k}={v:+.2f}")
        return ", ".join(parts) if parts else "neutral"


class FactorGraphEvaluator:
    def __init__(self) -> None:
        self._factors: List[EvaluationFactor] = []

    def register(self, factor: EvaluationFactor) -> None:
        self._factors.append(factor)

    def evaluate(self, state_before: GameState, state_after: GameState,
                 action: Optional[Action] = None,
                 context: Optional[EvalContext] = None) -> FactorScores:
        if context is None:
            context = EvalContext.from_state(state_after)

        scores: Dict[str, float] = {}
        for f in self._factors:
            try:
                scores[f.name()] = f.compute(state_before, state_after, action, context)
            except Exception:
                scores[f.name()] = 0.0

        total = 0.0
        for f in self._factors:
            w = f.weight(context)
            total += scores.get(f.name(), 0.0) * w

        return FactorScores(
            board_control=scores.get("board_control", 0.0),
            lethal_threat=scores.get("lethal_threat", 0.0),
            tempo=scores.get("tempo", 0.0),
            value=scores.get("value", 0.0),
            survival=scores.get("survival", 0.0),
            resource_efficiency=scores.get("resource_efficiency", 0.0),
            discover_ev=scores.get("discover_ev", 0.0),
            total=total,
        )

    def quick_eval(self, state: GameState,
                   context: Optional[EvalContext] = None) -> float:
        scores = self.evaluate(state, state, context=context)
        return scores.total

    def factor_names(self) -> List[str]:
        return [f.name() for f in self._factors]


# ===================================================================
# Factor implementations
# ===================================================================

class BoardControlFactor(EvaluationFactor):
    """Board presence and keyword synergy evaluation."""

    def name(self) -> str:
        return "board_control"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_after = self._board_value(state_after.board)
        enemy_after = self._board_value(state_after.opponent.board)
        friend_before = self._board_value(state_before.board)
        enemy_before = self._board_value(state_before.opponent.board)

        delta_friend = friend_after - friend_before
        delta_enemy = enemy_after - enemy_before

        raw = delta_friend - delta_enemy
        scale = max(friend_before + enemy_before, 1)
        return max(-1.0, min(1.0, raw / scale))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 1.3
        if context.phase == Phase.LATE:
            return 0.9
        return 1.1

    def _board_value(self, board: list) -> float:
        total = 0.0
        for m in board:
            base = m.attack + m.health
            kw_bonus = self._keyword_synergy_value(m)
            threat_bonus = self._threat_value(m)
            total += base * kw_bonus + threat_bonus
        return total

    def _keyword_synergy_value(self, m: Minion) -> float:
        multiplier = 1.0

        if m.has_taunt:
            multiplier += 0.15
            if m.health >= 5:
                multiplier += 0.2

        if m.has_divine_shield:
            multiplier += 0.3
            if m.attack >= 3:
                multiplier += 0.4

        if m.has_windfury and m.attack >= 2:
            multiplier += 0.35

        if m.has_poisonous:
            multiplier += 0.25
            if m.attack >= 1:
                multiplier += 0.1

        if m.has_stealth:
            if m.attack >= 3:
                multiplier += 0.2

        if m.has_rush:
            multiplier += 0.1

        if m.has_charge:
            multiplier += 0.15

        if m.has_reborn:
            if m.attack + m.health >= 4:
                multiplier += 0.2

        if getattr(m, 'has_ward', False):
            multiplier += 0.2

        # Keyword combos: synergistic pairs worth more than sum
        if m.has_taunt and m.has_divine_shield:
            multiplier += 0.35
        if m.has_taunt and m.has_reborn:
            multiplier += 0.25
        if m.has_poisonous and m.has_stealth:
            multiplier += 0.4
        if m.has_windfury and m.has_divine_shield:
            multiplier += 0.3
        if m.has_charge and m.has_windfury:
            multiplier += 0.25
        if m.has_rush and m.has_divine_shield:
            multiplier += 0.2
        if m.has_poisonous and m.has_rush:
            multiplier += 0.3

        return multiplier

    def _threat_value(self, m: Minion) -> float:
        threat = 0.0
        if m.attack >= 5:
            threat += m.attack * 0.3
        if m.has_windfury and m.attack >= 3:
            threat += m.attack * 0.5
        if m.has_charge and m.attack >= 3:
            threat += m.attack * 0.4
        return threat


class LethalThreatFactor(EvaluationFactor):
    """Lethal threat detection and multi-turn lethal probability."""

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
            return two_turn_prob * 0.4

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
        board_dmg_t2 = 0
        for m in state.board:
            can_attack_next = True
            if m.is_dormant:
                can_attack_next = False
            if m.cant_attack:
                can_attack_next = False
            if can_attack_next:
                board_dmg_t2 += m.attack
                if m.has_windfury:
                    board_dmg_t2 += m.attack

        next_mana = min(state.mana.max_mana + 1, 10)
        estimated_new_minion_atk = 0
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() == 'MINION':
                cost = getattr(card, 'cost', 0)
                if cost <= next_mana:
                    atk = getattr(card, 'attack', 0)
                    if atk > estimated_new_minion_atk:
                        estimated_new_minion_atk = atk

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

        deck_size = getattr(state, 'deck_remaining', 0) or 10
        topdeck_bonus = min(3, deck_size * 0.15)

        opp_hp = state.opponent.hero.hp + state.opponent.hero.armor

        if t1_total >= opp_hp:
            return 1.0

        two_turn_dmg = t1_total + t2_total + topdeck_bonus
        ratio = two_turn_dmg / max(opp_hp, 1)

        if ratio >= 1.0:
            return 0.7
        if ratio >= 0.7:
            return 0.5
        if ratio >= 0.4:
            return 0.2
        return 0.0

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 2.0
        if context.phase == Phase.MID:
            return 1.5
        return 1.0


class TempoFactor(EvaluationFactor):
    """Mana efficiency and board development."""

    def name(self) -> str:
        return "tempo"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_cost_after = sum(m.cost for m in state_after.board)
        enemy_cost_after = sum(m.cost for m in state_after.opponent.board)
        friend_cost_before = sum(m.cost for m in state_before.board)
        enemy_cost_before = sum(m.cost for m in state_before.opponent.board)

        board_delta = (friend_cost_after - enemy_cost_after) - \
                      (friend_cost_before - enemy_cost_before)

        max_mana = max(state_before.mana.max_mana, 1)
        mana_spent = state_before.mana.available - state_after.mana.available
        mana_eff = mana_spent / max_mana

        raw = board_delta * 0.3 + mana_eff * 0.7
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 1.5
        if context.phase == Phase.LATE:
            return 0.7
        return 1.0


class ValueFactor(EvaluationFactor):
    """Card advantage and hand quality evaluation."""

    def name(self) -> str:
        return "value"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_before = len(state_before.hand) + len(state_before.board)
        enemy_before = state_before.opponent.hand_count + len(state_before.opponent.board)
        friend_after = len(state_after.hand) + len(state_after.board)
        enemy_after = state_after.opponent.hand_count + len(state_after.opponent.board)

        card_adv_delta = (friend_after - enemy_after) - (friend_before - enemy_before)

        draw_delta = len(state_after.hand) - len(state_before.hand)
        cards_played = len(state_after.cards_played_this_turn) - len(state_before.cards_played_this_turn)
        net_cards = draw_delta + cards_played

        quality_delta = self._quality_delta(state_before, state_after)

        raw = card_adv_delta * 0.5 + net_cards * 0.3 + quality_delta * 0.2
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.LATE:
            return 1.3
        if context.phase == Phase.EARLY:
            return 0.6
        return 1.0

    @staticmethod
    def _quality_delta(state_before: GameState, state_after: GameState) -> float:
        before_q = sum(getattr(c, 'score', 3.0) for c in state_before.hand)
        after_q = sum(getattr(c, 'score', 3.0) for c in state_after.hand)

        before_count = max(len(state_before.hand), 1)
        after_count = max(len(state_after.hand), 1)

        before_avg = before_q / before_count
        after_avg = after_q / after_count

        delta = after_avg - before_avg
        return max(-1.0, min(1.0, delta / 3.0))


class SurvivalFactor(EvaluationFactor):
    """Hero health and safety."""

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
                if m.has_reborn:
                    effective_health += m.health * 0.5
                total += effective_health
        return total

    @staticmethod
    def _opponent_spell_damage_threat(state: GameState) -> int:
        threat = 0
        opp_hand_count = len(state.opponent.hand) if state.opponent.hand else state.opponent.hand_count
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


class ResourceEfficiencyFactor(EvaluationFactor):
    """Mana utilization."""

    def name(self) -> str:
        return "resource_efficiency"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        max_mana = max(state_before.mana.max_mana, 1)
        available_before = state_before.mana.available
        available_after = state_after.mana.available
        spent = available_before - available_after

        efficiency = spent / max_mana

        overloaded = state_after.mana.overloaded
        overload_penalty = overloaded / max_mana * 0.5 if max_mana > 0 else 0

        raw = efficiency - overload_penalty
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 0.8
        return 0.5


class DiscoverEVFactor(EvaluationFactor):
    """Expected value of discover/generation effects."""

    def name(self) -> str:
        return "discover_ev"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        hand_delta = len(state_after.hand) - len(state_before.hand)

        cards_played = len(state_after.cards_played_this_turn) - len(state_before.cards_played_this_turn)
        net_generation = hand_delta + cards_played

        if net_generation <= 0:
            return 0.0

        try:
            from analysis.evaluators.siv import siv_score
            new_cards_score = 0.0
            before_ids = {getattr(c, "dbf_id", id(c)) for c in state_before.hand}
            for card in state_after.hand:
                cid = getattr(card, "dbf_id", id(card))
                if cid not in before_ids:
                    new_cards_score += siv_score(card, state_after) * 0.1
            return max(-1.0, min(1.0, new_cards_score))
        except Exception:
            return min(0.5, net_generation * 0.15)

    def weight(self, context: EvalContext) -> float:
        return 0.6

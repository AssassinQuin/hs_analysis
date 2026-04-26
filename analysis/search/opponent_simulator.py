"""opponent_simulator.py — 1-turn greedy opponent simulation.

Simulates the opponent's best-response turn using a greedy heuristic:
favorable trades first, then face damage. Enhanced with Bayesian opponent
modeling to estimate spell/removal threats from predicted hand cards.

Threat estimation pipeline:
  1. If BayesianOpponentModel available → predict_hand() → scan for
     damage spells, removal, board clears, weapons
  2. Weight by archetype posterior probability
  3. Fall back to hero-class heuristic when model unavailable
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, TYPE_CHECKING

from analysis.search.game_state import GameState
from analysis.constants.effect_keywords import (
    DAMAGE_KEYWORDS, BOARD_CLEAR_KEYWORDS, REMOVAL_KEYWORDS, WEAPON_KEYWORDS,
)

if TYPE_CHECKING:
    from analysis.utils.bayesian_opponent import BayesianOpponentModel
    from analysis.models.card import Card


# ===================================================================
# Data structures
# ===================================================================

@dataclass
class SimulatedOpponentTurn:
    """Result of simulating the opponent's greedy best response."""

    board_resilience_delta: float = 0.0  # fraction of our board value surviving
    friendly_deaths: int = 0             # how many of our minions die
    lethal_exposure: bool = False        # can opponent kill us
    worst_case_damage: int = 0           # max damage to our hero
    spell_threat: float = 0.0
    removal_threat: float = 0.0          # probability opponent has removal
    predicted_damage_cards: int = 0      # number of damage cards in predicted hand
    predicted_removal_cards: int = 0     # number of removal cards in predicted hand

    def estimated_opp_damage(self) -> float:
        return float(self.worst_case_damage) + float(self.spell_threat)


# ===================================================================
# Card threat classification
# ===================================================================

# Known damage spell database: (dbfId → estimated damage)
# Covers the most common meta spells
_KNOWN_DAMAGE_SPELLS: Dict[int, int] = {}  # populated lazily from card data

# Known removal spells: dbfId set
_KNOWN_REMOVAL_SPELLS: Dict[int, str] = {}  # dbfId → type ('destroy' | 'transform' | 'aoe')


def classify_card_threat(card) -> Dict[str, float]:
    """Classify a card's threat potential from its text and properties.

    Returns dict with keys: 'damage', 'removal', 'aoe', 'weapon', 'heal'
    Values are threat scores 0.0-1.0.
    """
    result = {'damage': 0.0, 'removal': 0.0, 'aoe': 0.0, 'weapon': 0.0, 'heal': 0.0}

    text = (getattr(card, 'text', '') or '').lower()
    card_type = getattr(card, 'card_type', '').lower() if hasattr(card, 'card_type') else ''
    if not card_type:
        card_type = getattr(card, 'type', '').lower() if hasattr(card, 'type') else ''

    cost = getattr(card, 'cost', 0) or 0
    attack = getattr(card, 'attack', 0) or 0

    # Check for damage spell
    for kw in DAMAGE_KEYWORDS:
        if kw in text:
            # Estimate damage: try to extract number from pattern like "deal $X"
            result['damage'] = min(1.0, (cost + 1) / 5.0)  # rough: higher cost = more damage
            break

    # Check for board clear
    for kw in BOARD_CLEAR_KEYWORDS:
        if kw in text:
            result['aoe'] = 0.8
            break

    # Check for single-target removal
    for kw in REMOVAL_KEYWORDS:
        if kw in text:
            result['removal'] = 0.7
            break

    # Check for weapon
    if card_type == 'weapon' or any(kw in text for kw in WEAPON_KEYWORDS):
        result['weapon'] = min(1.0, attack / 5.0)

    return result


# ===================================================================
# OpponentSimulator
# ===================================================================

class OpponentSimulator:
    """Greedy 1-turn opponent simulator with Bayesian threat estimation.

    Given the current game state, simulates what a rational opponent
    would do on their next turn and returns a summary of the outcome
    from the friendly player's perspective.

    When a BayesianOpponentModel is provided, uses predicted opponent
    hand cards for more accurate spell/removal threat estimation.
    """

    def __init__(
        self,
        eval_fn: Optional[Callable[[GameState], float]] = None,
        bayesian_model: Optional['BayesianOpponentModel'] = None,
    ):
        self.eval_fn = eval_fn
        self.bayesian = bayesian_model

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def simulate_best_response(
        self,
        state: GameState,
        time_budget_ms: float = 10.0,
    ) -> SimulatedOpponentTurn:
        """Simulate opponent's greedy best response within *time_budget_ms*."""
        deadline = time.perf_counter() + (time_budget_ms / 1000.0)
        try:
            # Fast-path: no opponent board → nothing to simulate
            if not state.opponent.board:
                result = SimulatedOpponentTurn(
                    board_resilience_delta=1.0,
                    friendly_deaths=0,
                    lethal_exposure=False,
                    worst_case_damage=0,
                    spell_threat=self._estimate_spell_threat(state),
                )
                # Still check Bayesian spell/removal threat
                self._enrich_with_bayesian(state, result)
                return result

            our_health = state.hero.hp + state.hero.armor

            # Snapshot our board as mutable tuples (atk, hp, taunt, name)
            our_board: list[tuple[int, int, bool, str]] = [
                (m.attack, m.health, m.has_taunt, m.name) for m in state.board
            ]

            # Snapshot opponent board sorted by attack descending (greedy)
            opp_board: list[tuple[int, int, str]] = sorted(
                [(m.attack, m.health, m.name) for m in state.opponent.board],
                key=lambda t: t[0],
                reverse=True,
            )

            has_taunt = any(t[2] for t in our_board)

            friendly_deaths = 0
            remaining_opp_attack = 0

            for opp_atk, opp_hp, opp_name in opp_board:
                if time.perf_counter() > deadline:
                    break

                traded = False

                # 1) Look for a favorable trade: kill our minion, survive
                for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                    if has_taunt and not our_taunt:
                        continue  # must go through taunt first
                    if opp_atk >= our_hp and our_atk < opp_hp:
                        our_board.pop(i)
                        friendly_deaths += 1
                        traded = True
                        break

                if traded:
                    continue

                # 2) Look for an even trade: kill our minion, also dies
                for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                    if has_taunt and not our_taunt:
                        continue
                    if opp_atk >= our_hp:
                        our_board.pop(i)
                        friendly_deaths += 1
                        traded = True
                        break

                if traded:
                    continue

                # 3) If we have taunt, must attack a taunt minion
                if has_taunt:
                    for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                        if our_taunt:
                            new_hp = our_hp - opp_atk
                            if new_hp <= 0:
                                our_board.pop(i)
                                friendly_deaths += 1
                            else:
                                our_board[i] = (our_atk, new_hp, our_taunt, our_name)
                            break
                    continue

                # 4) No favorable trade and no taunt → go face
                remaining_opp_attack += opp_atk

            weapon_attack = (
                state.opponent.hero.weapon.attack
                if state.opponent.hero.weapon is not None
                else 0
            )
            hero_power_damage = self._estimate_hero_power_damage(state)
            spell_threat = self._estimate_spell_threat(state)
            worst_case_damage = remaining_opp_attack + weapon_attack + hero_power_damage
            lethal_exposure = (our_health - worst_case_damage) <= 0

            # Board resilience delta
            our_value_before = sum(m.attack + m.health for m in state.board)
            our_value_after = sum(atk + hp for atk, hp, _, _ in our_board)
            board_resilience_delta = our_value_after / max(our_value_before, 1)

            result = SimulatedOpponentTurn(
                board_resilience_delta=board_resilience_delta,
                friendly_deaths=friendly_deaths,
                lethal_exposure=lethal_exposure,
                worst_case_damage=worst_case_damage,
                spell_threat=spell_threat,
            )

            # Enhance with Bayesian predictions
            self._enrich_with_bayesian(state, result)

            # Re-check lethal with spell threat included
            total_threat = worst_case_damage + result.spell_threat
            if (our_health - total_threat) <= 0:
                result.lethal_exposure = True

            return result
        except Exception:
            return SimulatedOpponentTurn()  # safe default

    # ---------------------------------------------------------------
    # Bayesian threat estimation
    # ---------------------------------------------------------------

    def _enrich_with_bayesian(self, state: GameState, result: SimulatedOpponentTurn) -> None:
        """Enrich threat estimates using Bayesian opponent hand prediction."""
        if self.bayesian is None:
            return

        opp = state.opponent
        current_turn = getattr(state, 'turn_number', 0)

        try:
            predicted = self.bayesian.predict_hand(opp, state, current_turn)
        except Exception:
            return

        if not predicted:
            return

        # Scan predicted cards for threats
        total_damage = 0.0
        total_removal = 0.0
        total_aoe = 0.0
        total_weapon_dmg = 0.0
        damage_cards = 0
        removal_cards = 0

        for card in predicted:
            threat = classify_card_threat(card)
            if threat['damage'] > 0:
                cost = getattr(card, 'cost', 0) or 0
                # Rough damage estimate: cost * 1.5 (typical damage/cost ratio)
                total_damage += cost * 1.5 * threat['damage']
                damage_cards += 1
            if threat['removal'] > 0:
                total_removal += threat['removal']
                removal_cards += 1
            if threat['aoe'] > 0:
                total_aoe += threat['aoe']
            if threat['weapon'] > 0:
                total_weapon_dmg += (getattr(card, 'attack', 0) or 0) * threat['weapon']

        # Scale by hand probability (predicted pool is larger than actual hand)
        hand_count = getattr(opp, 'hand_count', 0)
        if hand_count > 0 and len(predicted) > 0:
            sample_ratio = hand_count / max(len(predicted), 1)
            # Only count a fraction — opponent doesn't have ALL predicted cards
            total_damage *= sample_ratio
            total_removal *= sample_ratio
            total_aoe *= sample_ratio
            total_weapon_dmg *= sample_ratio

        # Override heuristic spell_threat with Bayesian estimate if available
        if total_damage > 0 or total_weapon_dmg > 0:
            result.spell_threat = max(result.spell_threat, total_damage + total_weapon_dmg)

        result.removal_threat = min(1.0, total_removal)
        result.predicted_damage_cards = damage_cards
        result.predicted_removal_cards = removal_cards

        # Board resilience: if opponent likely has AOE, reduce resilience
        if total_aoe > 0.5:
            result.board_resilience_delta *= max(0.3, 1.0 - total_aoe * 0.5)

    # ---------------------------------------------------------------
    # Heuristic fallbacks (when no Bayesian model)
    # ---------------------------------------------------------------

    def _estimate_hero_power_damage(self, state: GameState) -> int:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls == "HUNTER":
            return 2
        if cls == "MAGE":
            return 1
        return 0

    def _estimate_spell_threat(self, state: GameState) -> float:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls in {"MAGE", "WARLOCK", "SHAMAN"}:
            return 2.0
        if cls in {"ROGUE", "HUNTER"}:
            return 1.0
        return 0.5

"""V10 Board State Value (BSV) — three-axis board evaluation.

Axes:
  1. Tempo  — board presence + mana efficiency
  2. Value  — hand quality + card advantage
  3. Survival — hero safety + lethal threat

Fusion via softmax-weighted combination with phase-dependent weights.
Lethal override: returns 999.0 when lethal is detected.
"""

from __future__ import annotations

import math
from typing import List, Tuple

from hs_analysis.search.game_state import GameState, Minion

# Import SIV for per-card scoring
from hs_analysis.evaluators.siv import siv_score

# Import lethal checker
try:
    from hs_analysis.search.lethal_checker import check_lethal
except ImportError:
    def check_lethal(state, time_budget_ms=5.0):  # type: ignore[misc]
        return None

# ===================================================================
# Constants
# ===================================================================
ABSOLUTE_LETHAL_VALUE = 999.0
LETHAL_SCALE = 3.0
TEMPERATURE = 0.5

# Phase weights: (tempo, value, survival)
PHASE_WEIGHTS = {
    "early": (1.3, 0.7, 0.5),  # turns 1-4: tempo matters most
    "mid":   (1.0, 1.0, 1.0),  # turns 5-7: balanced
    "late":  (0.7, 1.2, 1.5),  # turns 8+: value + survival
}


# ===================================================================
# Softmax utility
# ===================================================================

def softmax(values: List[float], temperature: float = TEMPERATURE) -> List[float]:
    """Numerically stable softmax with temperature scaling.

    Args:
        values: Raw values to normalize.
        temperature: Temperature parameter (lower = sharper).

    Returns:
        Probability distribution summing to 1.0.
    """
    if not values:
        return []

    scaled = [v / temperature for v in values]

    # Shift for numerical stability
    max_val = max(scaled)
    exps = [math.exp(s - max_val) for s in scaled]
    total = sum(exps)

    if total == 0:
        return [1.0 / len(values)] * len(values)

    return [e / total for e in exps]


# ===================================================================
# Phase selection
# ===================================================================

def _get_phase(turn_number: int) -> str:
    """Determine game phase from turn number."""
    if turn_number <= 4:
        return "early"
    elif turn_number <= 7:
        return "mid"
    else:
        return "late"


def _get_phase_weights(turn_number: int) -> Tuple[float, float, float]:
    """Get (tempo, value, survival) weights for the current turn."""
    phase = _get_phase(turn_number)
    return PHASE_WEIGHTS.get(phase, (1.0, 1.0, 1.0))


# ===================================================================
# Helper: minion-to-card-like wrapper
# ===================================================================

class _MinionCardLike:
    """Wraps a Minion to provide Card-like interface for SIV scoring."""

    def __init__(self, minion: Minion):
        self.dbf_id = getattr(minion, "dbf_id", 0)
        self.name = minion.name or ""
        self.cost = getattr(minion, "cost", 0)
        self.original_cost = self.cost
        self.card_type = "MINION"
        self.attack = minion.attack
        self.health = minion.health
        self.v7_score = minion.attack * 1.0 + minion.health * 0.8  # crude estimate
        self.text = ""
        self.mechanics = []
        self.race = getattr(minion, "race", "") or ""

        # Translate Minion flags to mechanics
        if minion.has_taunt:
            self.mechanics.append("TAUNT")
        if minion.has_divine_shield:
            self.mechanics.append("DIVINE_SHIELD")
        if minion.has_charge:
            self.mechanics.append("CHARGE")
        if minion.has_rush:
            self.mechanics.append("RUSH")
        if minion.has_windfury:
            self.mechanics.append("WINDFURY")
        if minion.has_poisonous:
            self.mechanics.append("POISONOUS")
        if minion.has_stealth:
            self.mechanics.append("STEALTH")


def _minion_to_card_like(minion: Minion) -> _MinionCardLike:
    """Convert a Minion to a Card-like object for SIV scoring."""
    return _MinionCardLike(minion)


# ===================================================================
# Axis 1: Tempo
# ===================================================================

def eval_tempo_v10(state: GameState) -> float:
    """Tempo axis: board presence + mana efficiency.

    = Σ siv_score(friendly minion) - Σ siv_score(enemy minion) × 1.2
    + mana_efficiency × 5.0
    + weapon_attack × 1.5
    """
    # Friendly board SIV
    friendly_siv = 0.0
    for m in state.board:
        card_like = _minion_to_card_like(m)
        friendly_siv += siv_score(card_like, state)

    # Enemy board SIV (penalised ×1.2)
    enemy_siv = 0.0
    for m in state.opponent.board:
        card_like = _minion_to_card_like(m)
        enemy_siv += siv_score(card_like, state) * 1.2

    # Mana efficiency: (used / total) → higher = more tempo
    max_mana = max(state.mana.max_mana, 1)
    mana_efficiency = (max_mana - state.mana.available) / max_mana

    # Weapon value
    weapon_value = 0.0
    if state.hero.weapon is not None:
        weapon_value = state.hero.weapon.attack * 1.5

    return friendly_siv - enemy_siv + mana_efficiency * 5.0 + weapon_value


# ===================================================================
# Axis 2: Value
# ===================================================================

def eval_value_v10(state: GameState) -> float:
    """Value axis: hand quality + card advantage.

    = Σ siv_score(hand card)
    + card_advantage × 2.0
    + resource_generation × 1.5
    """
    # Hand SIV sum
    hand_siv = 0.0
    for card in state.hand:
        hand_siv += siv_score(card, state)

    # Card advantage: (hand + board) - (opp_hand + opp_board)
    friendly_resources = len(state.hand) + len(state.board)
    enemy_resources = state.opponent.hand_count + len(state.opponent.board)
    card_advantage = friendly_resources - enemy_resources

    # Resource generation proxy
    resource_gen = len(state.cards_played_this_turn) * 1.5

    return hand_siv + card_advantage * 2.0 + resource_gen


# ===================================================================
# Axis 3: Survival
# ===================================================================

def eval_survival_v10(state: GameState) -> float:
    """Survival axis: hero safety.

    = (hero.hp + hero.armor) / 30.0 × 10.0
    - enemy_observable_damage × 0.5
    - lethal_threat × 50.0
    + healing_potential × 0.3
    """
    hero = state.hero
    hero_safety = (hero.hp + hero.armor) / 30.0 * 10.0

    # Enemy observable damage
    enemy_damage = 0.0
    for m in state.opponent.board:
        if m.can_attack or m.has_charge or m.has_rush:
            enemy_damage += m.attack
    if state.opponent.hero.weapon is not None:
        enemy_damage += state.opponent.hero.weapon.attack

    # Lethal threat: if enemy can kill us
    lethal_threat = 0.0
    total_defense = hero.hp + hero.armor
    if enemy_damage >= total_defense:
        lethal_threat = 1.0

    # Healing potential: scan hand for heal cards
    heal_potential = 0.0
    for card in state.hand:
        text = getattr(card, "text", "") or ""
        if "恢复" in text or "治疗" in text or "heal" in text.lower():
            heal_potential += 1.0

    return (
        hero_safety
        - enemy_damage * 0.5
        - lethal_threat * 50.0
        + heal_potential * 0.3
    )


# ===================================================================
# Fusion
# ===================================================================

def bsv_fusion(state: GameState) -> float:
    """Combine three axes with phase-weighted softmax fusion.

    Lethal override: returns ABSOLUTE_LETHAL_VALUE (999.0) if lethal detected.
    """
    # Lethal check
    try:
        lethal_result = check_lethal(state)
        if lethal_result is not None:
            return ABSOLUTE_LETHAL_VALUE
    except Exception:
        pass

    # Compute raw axes
    tempo = eval_tempo_v10(state)
    value = eval_value_v10(state)
    survival = eval_survival_v10(state)

    # Phase weights
    w_tempo, w_value, w_survival = _get_phase_weights(state.turn_number)

    # Weighted axes
    weighted = [
        tempo * w_tempo,
        value * w_value,
        survival * w_survival,
    ]

    # Softmax fusion
    weights = softmax(weighted, TEMPERATURE)
    bsv = sum(w * a for w, a in zip(weights, weighted))

    return bsv

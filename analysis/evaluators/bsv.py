"""V10 Board State Value (BSV) — archetype-aware board evaluation.

Three axes, all concrete metrics weighted by archetype profile:

  1. Tempo  — board impact + mana efficiency
  2. Value  — resource advantage (hand/deck/board)
  3. Survival — hero safety weighted by archetype:
      Aggro:   self_hp LOW weight, opp_hp HIGH weight
      Control: self_hp HIGH weight, opp_hp LOW weight
      Combo:   self_hp MEDIUM, draw VERY HIGH
"""

from __future__ import annotations

import math
from typing import List, Tuple

from analysis.search.game_state import GameState, Minion
from analysis.models.phase import Phase, detect_phase
from analysis.evaluators.archetype_profile import get_profile
from analysis.evaluators.card_impact import (
    _minion_impact,
    _weapon_impact,
    _location_impact,
)

TEMPERATURE = 0.5

PHASE_WEIGHTS = {
    Phase.EARLY: (1.3, 0.7, 0.5),
    Phase.MID:   (1.0, 1.0, 1.0),
    Phase.LATE:  (0.7, 1.2, 1.5),
}

_ARCHETYPE_AXIS_ADJUST = {
    "aggro":    (0.4, -0.1, -0.3),
    "tempo":    (0.2,  0.0, -0.1),
    "midrange": (0.0,  0.1,  0.0),
    "control":  (-0.3, 0.2,  0.4),
    "combo":    (-0.2, 0.3,  0.2),
}

_OPP_THREAT_ADJUST = {
    "aggro":    (-0.1, -0.1, 0.5),
    "tempo":    (0.0,  -0.1, 0.2),
    "midrange": (0.0,   0.0, 0.0),
    "control":  (0.1,   0.0, -0.2),
    "combo":    (0.0,   0.1, 0.1),
}


def softmax(values: List[float], temperature: float = TEMPERATURE) -> List[float]:
    if not values:
        return []
    scaled = [v / temperature for v in values]
    max_val = max(scaled)
    exps = [math.exp(s - max_val) for s in scaled]
    total = sum(exps)
    if total == 0:
        return [1.0 / len(values)] * len(values)
    return [e / total for e in exps]


def _get_weights(state: GameState) -> Tuple[float, float, float]:
    base = PHASE_WEIGHTS.get(detect_phase(state.turn_number), (1.0, 1.0, 1.0))
    our_adj = _ARCHETYPE_AXIS_ADJUST.get(state.our_playstyle, (0.0, 0.0, 0.0))
    opp_adj = _OPP_THREAT_ADJUST.get(state.opp_playstyle, (0.0, 0.0, 0.0))
    return tuple(max(0.1, b + o + p) for b, o, p in zip(base, our_adj, opp_adj))


def eval_tempo_v10(state: GameState) -> float:
    """Tempo: concrete board impact + mana efficiency, archetype-weighted."""
    profile = get_profile(state.our_playstyle)

    friendly_impact = 0.0
    for m in state.board:
        if m.health > 0:
            friendly_impact += _minion_impact(m, state)

    enemy_impact = 0.0
    for m in state.opponent.board:
        if m.health > 0:
            enemy_impact += _minion_impact(m, state)
    enemy_impact *= 1.2

    max_mana = max(state.mana.max_mana, 1)
    mana_efficiency = (max_mana - state.mana.available) / max_mana

    weapon_value = 0.0
    if state.hero.weapon is not None:
        weapon_value = _weapon_impact(state.hero.weapon, state)

    location_value = _location_impact(state)

    board_weight = profile["board_control_weight"]
    return (friendly_impact - enemy_impact) * board_weight + mana_efficiency * 5.0 + weapon_value + location_value


def eval_value_v10(state: GameState) -> float:
    """Value: resource advantage, archetype-weighted."""
    profile = get_profile(state.our_playstyle)

    our_hand = len(state.hand)
    opp_hand = state.opponent.hand_count
    card_advantage = our_hand - opp_hand

    hand_quality = 0.0
    if state.hand:
        total_cost = sum(getattr(c, 'cost', 0) or 0 for c in state.hand)
        avg_cost = total_cost / len(state.hand)
        hand_quality = avg_cost * len(state.hand) * 0.3

    board_advantage = len(state.board) - len(state.opponent.board)

    deck_safety = 0.0
    if state.deck_remaining <= 3:
        deck_safety = -2.0 * (3 - state.deck_remaining)

    ca_w = profile["card_advantage_weight"]
    draw_w = profile["draw_value"]

    return card_advantage * 1.5 * ca_w + hand_quality * draw_w + board_advantage * 1.0 + deck_safety


def eval_survival_v10(state: GameState) -> float:
    """Survival: hero safety weighted by archetype.

    Key insight from user:
    - Aggro: self_hp barely matters, opp_hp matters a LOT
    - Control: self_hp matters a LOT, opp_hp barely matters
    - Combo: self_hp matters moderately, draw matters most
    """
    profile = get_profile(state.our_playstyle)

    hero = state.hero
    self_hp_total = hero.hp + hero.armor

    self_hp_value = (self_hp_total / 30.0 * 10.0) * profile["self_hp_sensitivity"]

    enemy_damage = 0.0
    for m in state.opponent.board:
        if m.can_attack or m.has_charge or m.has_rush:
            enemy_damage += m.attack
    if state.opponent.hero.weapon is not None:
        enemy_damage += state.opponent.hero.weapon.attack

    lethal_threat = 0.0
    if enemy_damage >= self_hp_total:
        lethal_threat = 1.0

    damage_pressure = enemy_damage * 0.5 * profile["self_hp_sensitivity"]

    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor
    opp_pressure = 0.0
    if opp_hp > 0 and opp_hp <= 15:
        opp_pressure = (15 - opp_hp) / 15.0 * 5.0 * profile["opp_hp_sensitivity"]

    heal_potential = 0.0
    for card in state.hand:
        text = getattr(card, "text", "") or ""
        etext = getattr(card, "english_text", "") or ""
        if "heal" in etext.lower() or "restore" in etext.lower() or "heal" in text.lower() or "恢复" in text or "治疗" in text:
            heal_potential += 1.0 * profile["heal_value"]

    taunt_defense = 0.0
    for m in state.board:
        if m.has_taunt and m.health > 0:
            taunt_defense += (m.health * 0.2) * profile["taunt_value"]

    return (
        self_hp_value
        - damage_pressure
        - lethal_threat * 50.0
        + heal_potential * 0.3
        + taunt_defense
        + opp_pressure
    )


def bsv_fusion(state: GameState) -> float:
    """Combine three axes with archetype-aware softmax fusion."""
    tempo = eval_tempo_v10(state)
    value = eval_value_v10(state)
    survival = eval_survival_v10(state)

    w_tempo, w_value, w_survival = _get_weights(state)

    weighted = [
        tempo * w_tempo,
        value * w_value,
        survival * w_survival,
    ]

    weights = softmax(weighted, TEMPERATURE)
    return sum(w * a for w, a in zip(weights, weighted))

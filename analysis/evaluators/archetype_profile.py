"""archetype_profile.py — Archetype-specific resource weight profiles.

Each archetype has a different relationship with resources:

  Aggro:   "Kill opponent before resources matter"
           → opponent HP weight HIGH, self HP weight LOW
           → damage value HIGH, taunt/heal value LOW
           → doesn't care about card advantage

  Tempo:   "Efficient resource usage each turn"
           → balanced but leans aggressive
           → damage + board control weighted high

  Midrange: "Trade efficiently, maintain board"
           → balanced across all dimensions
           → trade value slightly elevated

  Control: "Survive, exhaust opponent, win late"
           → self HP weight HIGH, opponent HP weight LOW
           → taunt/heal/draw value HIGH, damage value LOW
           → card advantage critical

  Combo:   "Survive until combo assembled, then OTK"
           → self HP weight MEDIUM, opponent HP weight LOW (pre-combo)
           → draw value VERY HIGH, damage value LOW (pre-combo)
           → heal/taunt value HIGH
"""

from __future__ import annotations

_ARCHETYPE_PROFILES = {
    "aggro": {
        "opp_hp_sensitivity":    1.8,
        "self_hp_sensitivity":   0.4,
        "damage_weight":         1.6,
        "resource_drain_weight": 0.6,
        "taunt_value":           0.5,
        "heal_value":            0.3,
        "draw_value":            0.6,
        "trade_value":           0.8,
        "lethal_bonus":          2.0,
        "card_advantage_weight": 0.5,
        "board_control_weight":  1.2,
    },
    "tempo": {
        "opp_hp_sensitivity":    1.3,
        "self_hp_sensitivity":   0.7,
        "damage_weight":         1.3,
        "resource_drain_weight": 0.8,
        "taunt_value":           0.8,
        "heal_value":            0.5,
        "draw_value":            0.8,
        "trade_value":           1.1,
        "lethal_bonus":          1.5,
        "card_advantage_weight": 0.8,
        "board_control_weight":  1.3,
    },
    "midrange": {
        "opp_hp_sensitivity":    1.0,
        "self_hp_sensitivity":   1.0,
        "damage_weight":         1.0,
        "resource_drain_weight": 1.0,
        "taunt_value":           1.0,
        "heal_value":            0.8,
        "draw_value":            1.0,
        "trade_value":           1.2,
        "lethal_bonus":          1.5,
        "card_advantage_weight": 1.0,
        "board_control_weight":  1.0,
    },
    "control": {
        "opp_hp_sensitivity":    0.5,
        "self_hp_sensitivity":   1.6,
        "damage_weight":         0.5,
        "resource_drain_weight": 1.4,
        "taunt_value":           1.8,
        "heal_value":            1.5,
        "draw_value":            1.5,
        "trade_value":           1.0,
        "lethal_bonus":          1.0,
        "card_advantage_weight": 1.5,
        "board_control_weight":  0.8,
    },
    "combo": {
        "opp_hp_sensitivity":    0.3,
        "self_hp_sensitivity":   1.2,
        "damage_weight":         0.3,
        "resource_drain_weight": 0.7,
        "taunt_value":           1.3,
        "heal_value":            1.4,
        "draw_value":            2.0,
        "trade_value":           0.6,
        "lethal_bonus":          1.0,
        "card_advantage_weight": 1.3,
        "board_control_weight":  0.6,
    },
}

_DEFAULT_PROFILE = _ARCHETYPE_PROFILES["midrange"]


def get_profile(archetype: str) -> dict:
    """Get resource weight profile for the given archetype."""
    return _ARCHETYPE_PROFILES.get(archetype, _DEFAULT_PROFILE)

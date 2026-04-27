"""eval_logger.py — Structured evaluation logging for research & tuning.

Outputs JSONL (one JSON object per line) to the file log, containing:
- Archetype profile weights used
- Per-axis BSV scores and fusion weights
- Per-minion impact breakdown (damage/drain/keyword/trigger)
- Hero HP state and pressure metrics
- Archetype sensitivity values

This data enables:
- Post-game analysis of decision quality
- Statistical comparison across matchups
- Weight tuning based on outcome correlation
- Research into evaluation dimension importance
"""
from __future__ import annotations

import json
import time
from typing import TextIO, Optional

from analysis.card.engine.state import GameState, Minion
from analysis.evaluators.archetype_profile import get_profile


def log_evaluation(
    file_log: Optional[TextIO],
    *,
    state: GameState,
    action_desc: str,
    tempo: float,
    value: float,
    survival: float,
    final_score: float,
    axis_weights: tuple,
    elapsed_ms: float,
) -> None:
    """Write a structured evaluation record to the file log."""
    if file_log is None:
        return

    profile = get_profile(state.our_playstyle)

    minions = []
    for m in state.board:
        if m.health > 0:
            minions.append(_minion_record(m, state))

    opp_minions = []
    for m in state.opponent.board:
        if m.health > 0:
            opp_minions.append(_minion_record(m, state))

    hero = state.hero
    opp_hero = state.opponent.hero

    weapon = None
    if hero.weapon is not None:
        weapon = {
            "name": hero.weapon.name or "?",
            "attack": hero.weapon.attack,
            "durability": hero.weapon.health,
        }

    opp_weapon = None
    if opp_hero.weapon is not None:
        opp_weapon = {
            "name": opp_hero.weapon.name or "?",
            "attack": opp_hero.weapon.attack,
            "durability": opp_hero.weapon.health,
        }

    record = {
        "type": "eval",
        "ts": time.strftime("%H:%M:%S"),
        "turn": state.turn_number,
        "archetype": state.our_playstyle,
        "opp_archetype": state.opp_playstyle,
        "action": action_desc[:60],
        "elapsed_ms": round(elapsed_ms, 1),

        "eval": {
            "tempo": round(tempo, 2),
            "value": round(value, 2),
            "survival": round(survival, 2),
            "final": round(final_score, 2),
            "weights": {
                "tempo_w": round(axis_weights[0], 2),
                "value_w": round(axis_weights[1], 2),
                "survival_w": round(axis_weights[2], 2),
            },
        },

        "profile": {
            "opp_hp_sensitivity": profile["opp_hp_sensitivity"],
            "self_hp_sensitivity": profile["self_hp_sensitivity"],
            "damage_weight": profile["damage_weight"],
            "resource_drain_weight": profile["resource_drain_weight"],
            "taunt_value": profile["taunt_value"],
            "heal_value": profile["heal_value"],
            "draw_value": profile["draw_value"],
            "trade_value": profile["trade_value"],
            "lethal_bonus": profile["lethal_bonus"],
            "card_advantage_weight": profile["card_advantage_weight"],
            "board_control_weight": profile["board_control_weight"],
        },

        "board": {
            "our_minions": minions,
            "opp_minions": opp_minions,
            "our_count": len(state.board),
            "opp_count": len(state.opponent.board),
        },

        "heroes": {
            "our_hp": hero.hp,
            "our_armor": hero.armor,
            "opp_hp": opp_hero.hp,
            "opp_armor": opp_hero.armor,
            "our_weapon": weapon,
            "opp_weapon": opp_weapon,
        },

        "resources": {
            "mana_available": state.mana.available,
            "mana_max": state.mana.max_mana,
            "hand_size": len(state.hand),
            "opp_hand": state.opponent.hand_count,
            "deck_remaining": state.deck_remaining,
            "fatigue": state.fatigue_damage,
        },
    }

    file_log.write(json.dumps(record, ensure_ascii=False) + "\n")
    file_log.flush()


def log_minion_impact(
    file_log: Optional[TextIO],
    *,
    minion: Minion,
    state: GameState,
    damage: float,
    drain: float,
    keywords: float,
    triggers: float,
    total: float,
) -> None:
    """Write a detailed per-minion impact breakdown."""
    if file_log is None:
        return

    profile = get_profile(state.our_playstyle)

    record = {
        "type": "minion_impact",
        "ts": time.strftime("%H:%M:%S"),
        "turn": state.turn_number,
        "minion": minion.name or "?",
        "card_id": getattr(minion, "card_id", ""),
        "attack": minion.attack,
        "health": minion.health,
        "can_attack": minion.can_attack,
        "mechanics": list(getattr(minion, "mechanics", []) or []),

        "impact": {
            "damage_raw": round(damage / max(profile["damage_weight"], 0.01), 2),
            "damage_weighted": round(damage, 2),
            "drain_raw": round(drain / max(profile["resource_drain_weight"], 0.01), 2),
            "drain_weighted": round(drain, 2),
            "keywords": round(keywords, 2),
            "triggers": round(triggers, 2),
            "total": round(total, 2),
        },

        "weights_used": {
            "damage_w": profile["damage_weight"],
            "drain_w": profile["resource_drain_weight"],
            "taunt_w": profile["taunt_value"],
            "heal_w": profile["heal_value"],
        },
    }

    file_log.write(json.dumps(record, ensure_ascii=False) + "\n")
    file_log.flush()


def _minion_record(m: Minion, state: GameState) -> dict:
    """Create a compact minion summary for logging."""
    return {
        "name": m.name or "?",
        "atk": m.attack,
        "hp": m.health,
        "cost": getattr(m, "cost", 0),
        "can_atk": m.can_attack,
        "tags": _minion_tags(m),
    }


def _minion_tags(m: Minion) -> list:
    """Collect boolean keyword tags for logging."""
    tags = []
    for attr in ("has_taunt", "has_divine_shield", "has_charge", "has_rush",
                 "has_stealth", "has_windfury", "has_poisonous", "has_lifesteal",
                 "has_reborn"):
        if getattr(m, attr, False):
            tags.append(attr.replace("has_", ""))
    return tags

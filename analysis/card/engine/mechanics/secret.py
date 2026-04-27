# [从 analysis/search/secret_triggers.py 迁移而来]
# 原文件仍保留，后续 Phase 统一 import 路径后删除原文件。
from __future__ import annotations

"""secret_triggers.py — Secret trigger resolution for Hearthstone AI.

Checks opponent secrets and triggers them when conditions are met.
Currently supports the most common standard secrets by trigger condition.

TODO: Full secret pool enumeration per class (Paladin, Hunter, Mage, Rogue).
TODO: Multi-secret ordering (oldest first).
TODO: Counter/Spellbane interactions.
"""

import logging
from typing import List, Optional, Tuple

from analysis.card.engine.state import GameState, Minion

logger = logging.getLogger(__name__)


# ===================================================================
# Secret definitions: name -> (trigger_event, effect_fn)
# ===================================================================

SECRET_DEFS = {
    # --- Hunter ---
    "EXPLOSIVE_TRAP": ("on_attack_hero", "aoe_friendly_2"),
    "FREEZING_TRAP": ("on_attack_minion", "return_attacker"),
    "WANDERING_MONSTER": ("on_attack_hero", "summon_3_3"),
    "PACK_TACTICS": ("on_minion_survives_damage", "copy_minion"),
    # --- Mage ---
    "ICE_BARRIER": ("on_attack_hero", "gain_armor_8"),
    "VAPORIZE": ("on_attack_hero", "destroy_attacker"),
    "ICE_BLOCK": ("on_hero_lethal", "hero_immune"),
    "RINGING_IN_THE_EARS": ("on_play_minion", "add_mana_2"),
    # --- Paladin ---
    "NOBLE_SACRIFICE": ("on_attack_hero", "summon_defender_2_1"),
    "REDEMPTION": ("on_minion_dies", "resummon_1_hp"),
    "REPENTANCE": ("on_play_minion", "halve_minion_health"),
    # --- Rogue ---
    "AMBUSH": ("on_attack_hero", "summon_2_2"),
    "BAMBOZLE": ("on_minion_survives_damage", "transform_random"),
    "SUDDEN_BETRAYAL": ("on_attack_hero", "copy_attack_to_attacker"),
    # --- Generic (Chinese names from data) ---
    "爆炸陷阱": ("on_attack_hero", "aoe_friendly_2"),
    "冰冻陷阱": ("on_attack_minion", "return_attacker"),
    "寒冰屏障": ("on_hero_lethal", "hero_immune"),
}


def check_secrets(
    state: GameState,
    event: str,
    context: dict = None,
) -> GameState:
    """Check and trigger opponent secrets matching the event.

    Args:
        state: Current game state (copied by caller).
        event: Trigger event string (e.g. "on_attack_hero", "on_play_minion").
        context: Dict with contextual info (e.g. {"attacker": Minion, "damage": int}).

    Returns:
        Modified state with triggered secrets removed and effects applied.
    """
    if not state.opponent.secrets:
        return state

    context = context or {}
    triggered = []

    for i, secret_name in enumerate(state.opponent.secrets):
        defn = SECRET_DEFS.get(secret_name.upper().replace(" ", "_"), None)
        if defn is None:
            continue
        trigger_event, effect_key = defn
        if trigger_event == event:
            triggered.append((i, secret_name, effect_key))
            break  # Only one secret triggers per event

    for idx, name, effect_key in reversed(triggered):
        state.opponent.secrets.pop(idx)
        state = _apply_secret_effect(state, effect_key, context)
        logger.debug("Secret triggered: %s → %s", name, effect_key)

    return state


def _apply_secret_effect(state: GameState, effect_key: str, context: dict) -> GameState:
    s = state

    if effect_key == "aoe_friendly_2":
        for m in s.board:
            if m.has_divine_shield:
                m.has_divine_shield = False
            else:
                m.health -= 2

    elif effect_key == "return_attacker":
        attacker = context.get("attacker")
        if attacker is not None:
            for i, m in enumerate(s.board):
                if m is attacker:
                    s.board.pop(i)
                    break

    elif effect_key == "summon_3_3":
        if len(s.opponent.board) < 7:
            s.opponent.board.append(Minion(
                name="Snake", attack=3, health=3, max_health=3, owner="enemy"
            ))

    elif effect_key == "gain_armor_8":
        s.opponent.hero.armor += 8

    elif effect_key == "destroy_attacker":
        attacker = context.get("attacker")
        if attacker is not None:
            attacker.health = 0

    elif effect_key == "hero_immune":
        if s.opponent.hero.hp <= 0:
            s.opponent.hero.hp = 1

    elif effect_key == "summon_defender_2_1":
        if len(s.opponent.board) < 7:
            s.opponent.board.append(Minion(
                name="Defender", attack=2, health=1, max_health=1, owner="enemy"
            ))

    elif effect_key == "resummon_1_hp":
        pass  # TODO: track last dead minion

    elif effect_key == "halve_minion_health":
        target = context.get("played_minion")
        if target is not None:
            target.max_health = max(1, target.max_health // 2)
            target.health = min(target.health, target.max_health)

    elif effect_key == "add_mana_2":
        pass  # Opponent gains 2 mana next turn (tracked elsewhere)

    return s

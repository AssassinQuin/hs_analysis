"""Location card support for Hearthstone AI decision engine.

Handles location activation, cooldown ticking, and effect resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState


@dataclass
class Location:
    """A location card on the board."""

    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    durability: int = 0          # charges remaining
    cooldown_current: int = 0    # turns until next activation (0 = ready)
    cooldown_max: int = 2        # typical cooldown (most locations have 2-turn cooldown)
    text: str = ""               # card text for effect parsing


def activate_location(state: "GameState", location_index: int) -> "GameState":
    """Activate a location card by index.

    Validates the location is ready (durability > 0, cooldown == 0).
    Reduces durability by 1 and sets cooldown to cooldown_max.
    Attempts to resolve the location's text effect.

    Returns a modified copy of state, or unchanged copy if invalid.
    """
    s = state.copy()

    # Validate index
    if location_index < 0 or location_index >= len(s.locations):
        return s

    loc = s.locations[location_index]

    # Validate ready state
    if loc.durability <= 0:
        return s
    if loc.cooldown_current > 0:
        return s

    # Resolve location effect from text
    try:
        s = _resolve_location_effect(s, loc)
    except Exception:
        pass  # graceful degradation — still consume charge

    # Consume durability and start cooldown
    loc.durability -= 1
    loc.cooldown_current = loc.cooldown_max

    return s


def tick_location_cooldowns(state: "GameState") -> "GameState":
    """Tick cooldowns on all locations at end of turn.

    Decrements cooldown_current by 1 for all locations with cooldown > 0.
    Returns a modified copy of state.
    """
    s = state.copy()

    for loc in s.locations:
        if loc.cooldown_current > 0:
            loc.cooldown_current -= 1

    return s


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _resolve_location_effect(state: "GameState", loc: Location) -> "GameState":
    """Parse location text and apply effect via unified dispatcher.

    Supported patterns (Chinese/English card text):
      - 造成N点伤害 → damage to enemy hero
      - 恢复N点生命 → heal friendly hero
      - 使一个随从获得+N/+N → buff first friendly minion
      - 召唤一个N/N → summon a token
      - 发现 → discover (no-op for now)
    """
    from analysis.search.effects import EffectKind, EffectSpec, dispatch

    text = loc.text or ""

    # --- Try card_effects regex patterns first (structured lookup) ---
    from analysis.data.card_effects import (
        _DAMAGE_CN, _DAMAGE_EN, _HEAL_CN, _HEAL_EN,
        _BUFF_ATK_CN, _BUFF_ATK_EN, _SUMMON_STATS_CN, _SUMMON_STATS_EN,
    )

    dmg_match = _DAMAGE_EN.search(text) or _DAMAGE_CN.search(text)
    if dmg_match:
        damage = int(dmg_match.group(1))
        return dispatch(state, EffectSpec(kind=EffectKind.DAMAGE, value=damage, target_filter="enemy_hero"))

    heal_match = _HEAL_EN.search(text) or _HEAL_CN.search(text)
    if heal_match:
        heal_amount = int(heal_match.group(1))
        return dispatch(state, EffectSpec(kind=EffectKind.HEAL, value=heal_amount, target_filter="hero"))

    buff_match = re.search(r"Give\s*\+(\d+)/\+(\d+)", text, re.IGNORECASE)
    if not buff_match:
        buff_match = re.search(r"Gain\s*\+(\d+)/\+(\d+)", text, re.IGNORECASE)
    if not buff_match:
        buff_match = re.search(r'获得\+?(\d+)/\+?(\d+)', text)
    if buff_match:
        atk_bonus = int(buff_match.group(1))
        hp_bonus = int(buff_match.group(2))
        return dispatch(state, EffectSpec(kind=EffectKind.BUFF, value=atk_bonus, value2=hp_bonus, target_filter="friendly"))

    summon_match = _SUMMON_STATS_EN.search(text) or _SUMMON_STATS_CN.search(text)
    if summon_match:
        atk = int(summon_match.group(1))
        hp = int(summon_match.group(2))
        return dispatch(state, EffectSpec(kind=EffectKind.SUMMON, value=atk, value2=hp))

    if '发现' in text or re.search(r'Discover', text, re.IGNORECASE):
        # Discover is handled separately by the discover framework
        return state

    return state

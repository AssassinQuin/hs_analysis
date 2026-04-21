"""Location card support for Hearthstone AI decision engine.

Handles location activation, cooldown ticking, and effect resolution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hs_analysis.search.game_state import GameState


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
    """Parse location text and apply effect.

    Supported patterns (Chinese card text):
      - 造成N点伤害 → damage to enemy hero (simplest default)
      - 恢复N点生命 → heal friendly hero
      - 使一个随从获得+N/+N → buff first friendly minion
      - 召唤一个N/N → summon a token
      - 发现 → discover (no-op for now, delegates to discover framework)
    """
    text = loc.text or ""
    s = state

    # Damage: 造成N点伤害
    dmg_match = re.search(r"Deal\s*(\d+)\s*damage", text, re.IGNORECASE)
    if not dmg_match:
        dmg_match = re.search(r'造成\s*(\d+)\s*点伤害', text)
    if dmg_match:
        damage = int(dmg_match.group(1))
        # Default: damage enemy hero
        s.opponent.hero.hp -= damage
        return s

    # Heal: 恢复N点生命
    heal_match = re.search(r"Restore\s*(\d+)\s*(?:Health|health)", text, re.IGNORECASE)
    if not heal_match:
        heal_match = re.search(r'恢复\s*(\d+)\s*点生命', text)
    if heal_match:
        heal_amount = int(heal_match.group(1))
        s.hero.hp = min(s.hero.hp + heal_amount, 30)
        return s

    # Buff: 使一个随从获得+ATK/+HP
    buff_match = re.search(r"Give\s*\+(\d+)/\+(\d+)", text, re.IGNORECASE)
    if not buff_match:
        buff_match = re.search(r"Gain\s*\+(\d+)/\+(\d+)", text, re.IGNORECASE)
    if not buff_match:
        buff_match = re.search(r'获得\+?(\d+)/\+?(\d+)', text)
    if buff_match:
        atk_bonus = int(buff_match.group(1))
        hp_bonus = int(buff_match.group(2))
        if s.board:
            target = s.board[0]  # buff first friendly minion
            target.attack += atk_bonus
            target.health += hp_bonus
            target.max_health += hp_bonus
        return s

    # Summon: 召唤一个N/N
    summon_match = re.search(r"Summon\s*(?:a\s+)?(\d+)/(\d+)", text, re.IGNORECASE)
    if not summon_match:
        summon_match = re.search(r'召唤一个(\d+)/(\d+)', text)
    if summon_match:
        from hs_analysis.search.game_state import Minion
        atk = int(summon_match.group(1))
        hp = int(summon_match.group(2))
        if not s.board_full():
            token = Minion(
                name=f"Token({atk}/{hp})",
                attack=atk,
                health=hp,
                max_health=hp,
                can_attack=False,
                owner="friendly",
            )
            s.board.append(token)
        return s

    # Discover: 发现 — delegate to discover framework
    if '发现' in text or re.search(r'Discover', text, re.IGNORECASE):
        try:
            from hs_analysis.search.discover import generate_discover_options
            # No-op for search: discover is too complex for deterministic simulation
            pass
        except Exception:
            pass
        return s

    # Unknown effect — no-op
    return s

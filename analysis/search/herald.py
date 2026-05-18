"""Herald mechanic for Hearthstone RHEA engine.

Handles the Herald (兆示) mechanic: when a card with herald is played,
it increments the herald counter and summons a class-specific soldier minion.

Herald count milestones affect colossal appendage upgrades (handled in colossal.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState


# Per-class soldier minion definitions
HERALD_SOLDIERS = {
    "DEMONHUNTER": {"name": "伊利达雷士兵", "attack": 2, "health": 2},
    "ROGUE": {"name": "暗影刺客", "attack": 2, "health": 1},
    "HUNTER": {"name": "猎手", "attack": 3, "health": 1},
    "MAGE": {"name": "奥术学徒", "attack": 1, "health": 2},
    "PALADIN": {"name": "白银之手新兵", "attack": 2, "health": 2},
    "PRIEST": {"name": "暗影祭司", "attack": 1, "health": 3},
    "WARRIOR": {"name": "战歌士兵", "attack": 3, "health": 1},
    "WARLOCK": {"name": "小鬼军团", "attack": 2, "health": 2},
    "SHAMAN": {"name": "图腾战士", "attack": 2, "health": 2},
    "DRUID": {"name": "树人战士", "attack": 2, "health": 3},
    "DEATHKNIGHT": {"name": "亡灵士兵", "attack": 2, "health": 2},
    "NEUTRAL": {"name": "雇佣兵", "attack": 2, "health": 2},
}


def check_herald(card) -> bool:
    """Check if a card has the Herald mechanic.

    Returns True if the card text contains '兆示' or mechanics contains 'HERALD'.
    """
    mechanics = getattr(card, 'mechanics', []) or []
    text = getattr(card, 'text', '') or ''
    return '兆示' in text or 'HERALD' in mechanics


def apply_herald(state: 'GameState', card) -> 'GameState':
    """Apply herald effect: increment counter and summon a soldier minion.

    Args:
        state: Current game state (will be mutated).
        card: The card with herald mechanic being played.

    Returns:
        Modified game state with herald counter incremented and
        soldier summoned (if board has room).
    """
    from analysis.search.game_state import Minion as _Minion

    if not check_herald(card):
        return state

    # Increment herald counter
    state.herald_count += 1

    # Determine card class for soldier lookup
    card_class = getattr(card, 'card_class', '') or ''
    card_class_upper = card_class.upper()
    soldier_def = HERALD_SOLDIERS.get(
        card_class_upper, HERALD_SOLDIERS["NEUTRAL"]
    )

    # Summon soldier if board not full
    if len(state.board) < 7:
        soldier = _Minion(
            dbf_id=0,
            name=soldier_def["name"],
            attack=soldier_def["attack"],
            health=soldier_def["health"],
            max_health=soldier_def["health"],
            cost=0,
            can_attack=False,
            owner="friendly",
        )
        state.board.append(soldier)  # rightmost position

    return state

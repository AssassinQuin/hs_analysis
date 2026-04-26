"""Colossal appendage summoning for Hearthstone RHEA engine.

Handles the COLOSSAL mechanic: when a colossal minion is played,
it summons N appendage minions to its right side.

Herald upgrades: at herald_count >= 2, appendages gain +1/+1;
at herald_count >= 4, appendages gain +2/+2.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion


# Per-class appendage definitions
COLOSSAL_APPENDAGES = {
    "DEMONHUNTER": {"name": "末日之翼的附肢", "attack": 2, "health": 2},
    "ROGUE": {"name": "暗影附肢", "attack": 2, "health": 1},
    "HUNTER": {"name": "野兽附肢", "attack": 3, "health": 2},
    "MAGE": {"name": "奥术附肢", "attack": 1, "health": 3},
    "PALADIN": {"name": "圣光附肢", "attack": 2, "health": 3},
    "PRIEST": {"name": "暗影附肢", "attack": 1, "health": 4},
    "WARRIOR": {"name": "战甲附肢", "attack": 3, "health": 1},
    "WARLOCK": {"name": "恶魔附肢", "attack": 2, "health": 2},
    "SHAMAN": {"name": "元素附肢", "attack": 2, "health": 2},
    "DRUID": {"name": "自然附肢", "attack": 2, "health": 2},
    "DEATHKNIGHT": {"name": "亡灵附肢", "attack": 2, "health": 2},
    "NEUTRAL": {"name": "虚空附肢", "attack": 1, "health": 1},
}


def parse_colossal_value(card) -> int:
    """Parse the colossal appendage count from a card.

    Checks mechanics for 'COLOSSAL' and parses 'Colossal +N' from English
    card text, falling back to Chinese '巨型+N' for backward compatibility.
    Returns N, or 0 if the card is not colossal.
    """
    mechanics = getattr(card, 'mechanics', []) or []
    english_text = getattr(card, 'english_text', '') or ''
    text = getattr(card, 'text', '') or ''

    if 'COLOSSAL' not in mechanics and 'Colossal' not in english_text and '巨型' not in text:
        return 0

    match = re.search(r'Colossal\s*\+\s*(\d+)', english_text)
    if match:
        return int(match.group(1))

    match = re.search(r'巨型\+(\d+)', text)
    if match:
        return int(match.group(1))

    return 1


def summon_colossal_appendages(
    state: 'GameState',
    main_minion: 'Minion',
    card,
    insert_pos: int,
    herald_count: int = 0,
) -> 'GameState':
    """Summon colossal appendages to the right of the main minion.

    Args:
        state: Current game state (will be mutated).
        main_minion: The colossal minion just played.
        card: The card data for the colossal minion.
        insert_pos: Board position where the main minion was inserted.
        herald_count: Current herald counter for upgrade bonuses.

    Returns:
        Modified game state with appendages added.
    """
    from analysis.search.game_state import Minion as _Minion

    appendage_count = parse_colossal_value(card)
    if appendage_count <= 0:
        return state

    # Determine card class for appendage lookup
    card_class = getattr(card, 'card_class', '') or ''
    card_class_upper = card_class.upper()
    appendage_def = COLOSSAL_APPENDAGES.get(
        card_class_upper, COLOSSAL_APPENDAGES["NEUTRAL"]
    )

    # Herald upgrade bonuses
    bonus_atk = 0
    bonus_hp = 0
    if herald_count >= 4:
        bonus_atk = 2
        bonus_hp = 2
    elif herald_count >= 2:
        bonus_atk = 1
        bonus_hp = 1

    # Summon appendages to the right of the main body
    current_pos = insert_pos + 1  # right of the main minion
    for i in range(appendage_count):
        if len(state.board) >= 7:
            break  # board full, skip remaining

        appendage = _Minion(
            dbf_id=0,
            name=appendage_def["name"],
            attack=appendage_def["attack"] + bonus_atk,
            health=appendage_def["health"] + bonus_hp,
            max_health=appendage_def["health"] + bonus_hp,
            cost=0,
            can_attack=False,
            owner="friendly",
        )
        # Insert at current_pos (shifts existing minions right)
        insert_at = min(current_pos, len(state.board))
        state.board.insert(insert_at, appendage)
        current_pos += 1  # next appendage goes one position further right

    return state

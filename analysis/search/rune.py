"""rune.py — DK 符文 (Rune) system for Hearthstone search engine.

Rune types (Blood/Frost/Unholy) are used for:
1. Discover pool filtering — "发现一张冰霜符文牌"
2. Conditional effects — "如果你使用的上一张牌拥有邪恶符文"

Mapping strategy:
- Primary: spellSchool field → FROST→冰霜, SHADOW→邪恶, FIRE→鲜血
- Secondary: hardcoded lookup for known minion/weapon cards with rune affiliations
"""

from __future__ import annotations

import logging
from typing import Optional

from analysis.search.game_state import GameState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rune type mapping
# ---------------------------------------------------------------------------

# spellSchool → rune name (Chinese)
RUNE_MAP: dict[str, str] = {
    "FROST": "冰霜符文",
    "SHADOW": "邪恶符文",
    "FIRE": "鲜血符文",
}

# Hardcoded rune affiliations for cards that don't have spellSchool
# Key: card dbfId, Value: rune name
RUNE_LOOKUP: dict[int, str] = {
    # 血液魔术师 (Hematurge) — blood rune discover
    # 畸怪符文剑 (Grotesque Runeblade) — references blood + unholy
    # 死灵殡葬师 (Necrotic Mortician) — unholy rune discover
    # These are discover sources, not cards with rune identity themselves.
    # Most minion/weapon rune cards don't have explicit rune fields.
}


# ---------------------------------------------------------------------------
# Rune type detection
# ---------------------------------------------------------------------------

def get_rune_type(card: dict) -> str | None:
    """Determine the rune type of a card.

    Checks spellSchool first, then hardcoded lookup.
    Returns rune name in Chinese (e.g., "冰霜符文") or None.
    """
    # Check spellSchool
    school = card.get("spellSchool", "") or ""
    if isinstance(school, str) and school.upper() in RUNE_MAP:
        return RUNE_MAP[school.upper()]

    # Check hardcoded lookup
    dbf_id = card.get("dbfId") or card.get("dbf_id")
    if dbf_id is not None:
        try:
            return RUNE_LOOKUP[int(dbf_id)]
        except (KeyError, ValueError, TypeError):
            pass

    return None


# ---------------------------------------------------------------------------
# Discover pool filtering
# ---------------------------------------------------------------------------

def filter_by_rune(pool: list[dict], rune_name: str) -> list[dict]:
    """Filter a discover pool to cards with the given rune type.

    rune_name should be Chinese: "冰霜符文", "邪恶符文", "鲜血符文".
    """
    return [c for c in pool if get_rune_type(c) == rune_name]


# ---------------------------------------------------------------------------
# Conditional checks
# ---------------------------------------------------------------------------

def check_last_played_rune(state: GameState, rune_name: str) -> bool:
    """Check if the last played card has the given rune type."""
    if state.last_played_card is None:
        return False
    return get_rune_type(state.last_played_card) == rune_name


# ---------------------------------------------------------------------------
# Discover integration helper
# ---------------------------------------------------------------------------

def parse_rune_discover_target(card_text: str) -> str | None:
    """Parse "发现一张XX符文牌" from card text.

    Returns the rune name in Chinese, or None.
    """
    if not card_text or not isinstance(card_text, str):
        return None

    # "发现一张冰霜符文牌" / "发现一张邪恶符文牌" / "发现一张鲜血符文牌"
    for rune_name in RUNE_MAP.values():
        if rune_name in card_text:
            return rune_name

    return None

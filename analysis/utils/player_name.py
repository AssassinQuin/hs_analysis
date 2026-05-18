"""player_name.py — Player name normalization utilities.

Handles edge cases in Hearthstone player names from Power.log:
- Empty / whitespace-only names
- "UNKNOWN HUMAN PLAYER" and variants
- Names with special characters (#, @, etc.)
- Case-insensitive matching for BattleTag-style names
"""

import re
from typing import Optional

_ANON_PATTERNS = re.compile(
    r'^UNKNOWN(\s|$)',
    re.IGNORECASE,
)

_SPECIAL_CHARS = re.compile(r'[\s\ufeff\u200b\u200c\u200d]+')

_BATTLETAG_RE = re.compile(r'#\d+$')


def normalize_player_name(name: str) -> str:
    """Normalize a raw player name from Power.log into a canonical form.

    Returns an empty string for invalid / anonymous names.
    """
    if not name:
        return ""
    cleaned = _SPECIAL_CHARS.sub(' ', name).strip()
    if not cleaned:
        return ""
    if _ANON_PATTERNS.match(cleaned):
        return ""
    return cleaned


def is_anonymous_name(name: str) -> bool:
    """Return True if the name represents an anonymous / unknown player."""
    if not name:
        return True
    cleaned = _SPECIAL_CHARS.sub(' ', name).strip()
    if not cleaned:
        return True
    return bool(_ANON_PATTERNS.match(cleaned))


def name_matches(haystack: str, needle: str) -> bool:
    """Check if two player names refer to the same player.

    Handles:
    - Exact match
    - Case-insensitive match (BattleTags like "Player#1234")
    - Whitespace normalization
    - BattleTag suffix stripping: "Player#1234" matches "Player"
      but "Player#1234" does NOT match "Player#5678"
    """
    a = normalize_player_name(haystack)
    b = normalize_player_name(needle)
    if not a or not b:
        return False
    if a == b:
        return True
    if a.lower() == b.lower():
        return True
    a_has_tag = bool(_BATTLETAG_RE.search(a))
    b_has_tag = bool(_BATTLETAG_RE.search(b))
    if a_has_tag != b_has_tag:
        a_base = _BATTLETAG_RE.sub('', a).lower()
        b_base = _BATTLETAG_RE.sub('', b).lower()
        if a_base and b_base and a_base == b_base:
            return True
    return False


ANON_DISPLAY = "UNKNOWN HUMAN PLAYER"

"""dark_gift.py — Dark Gift enchantment system.

Dark Gift is a discover modifier: when discovering a card with Dark Gift,
a random enchantment from a fixed pool is applied to the discovered card.

~20 cards in standard pool reference Dark Gift.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from analysis.search.game_state import GameState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dark Gift enchantment pool
# ---------------------------------------------------------------------------

@dataclass
class DarkGiftEnchantment:
    """A predefined Dark Gift bonus."""
    name: str
    attack_bonus: int = 0
    health_bonus: int = 0
    keyword: str = ""  # WINDFURY, LIFESTEAL, DIVINE_SHIELD, TAUNT, etc.
    effect: str = ""    # Descriptive effect text


# ~10 predefined Dark Gift enchantments (based on game data)
DARK_GIFT_ENCHANTMENTS: list[DarkGiftEnchantment] = [
    DarkGiftEnchantment(name="Chaos Power", attack_bonus=2, health_bonus=2),
    DarkGiftEnchantment(name="Shadow Embrace", attack_bonus=1, health_bonus=3),
    DarkGiftEnchantment(name="Frenzy Gift", attack_bonus=3, health_bonus=1),
    DarkGiftEnchantment(name="Wind Gift", keyword="WINDFURY"),
    DarkGiftEnchantment(name="Lifesteal Gift", keyword="LIFESTEAL"),
    DarkGiftEnchantment(name="Divine Shield Gift", keyword="DIVINE_SHIELD"),
    DarkGiftEnchantment(name="Taunt Gift", keyword="TAUNT"),
    DarkGiftEnchantment(name="Rush Gift", keyword="RUSH"),
    DarkGiftEnchantment(name="Deathrattle Damage", effect="deathrattle_damage:2"),
    DarkGiftEnchantment(name="Battlecry Draw", effect="battlecry_draw:1"),
]


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def apply_dark_gift(card: dict) -> dict:
    """Apply a random Dark Gift enchantment to a card dict.

    Modifies attack/health or adds keyword/effect in-place.
    Returns the modified card.
    """
    if not DARK_GIFT_ENCHANTMENTS:
        return card

    gift = random.choice(DARK_GIFT_ENCHANTMENTS)

    # Apply stat bonuses
    if gift.attack_bonus:
        card["attack"] = card.get("attack", 0) + gift.attack_bonus
    if gift.health_bonus:
        card["health"] = card.get("health", 0) + gift.health_bonus

    # Apply keyword
    if gift.keyword:
        mechanics = card.get("mechanics", [])
        if not isinstance(mechanics, list):
            mechanics = []
        mechanics.append(gift.keyword)
        card["mechanics"] = mechanics

    # Track dark gift application
    card["dark_gift"] = gift.name

    return card


def has_dark_gift_in_hand(hand: list) -> bool:
    """Check if any card in hand has been granted Dark Gift.

    Cards with dark_gift field set are considered Dark Gift cards.
    Also checks english_text as a fallback (Standard 1: English-Only Logic Layer).
    """
    for card in hand:
        if isinstance(card, dict):
            if card.get("dark_gift"):
                return True
            en_text = card.get("english_text", "") or ""
            if "dark gift" in en_text.lower():
                return True
        elif hasattr(card, 'dark_gift') and card.dark_gift:
            return True
        elif hasattr(card, 'english_text'):
            en_text = getattr(card, 'english_text', '') or ''
            if "dark gift" in en_text.lower():
                return True
    return False


def filter_dark_gift_pool(pool: list[dict], constraint: str = "") -> list[dict]:
    """Filter a discover pool for cards eligible for Dark Gift.

    constraint: type filter like "DEATHRATTLE", "DRAGON", etc.
    Returns cards matching the constraint (all cards if constraint is empty).
    """
    if not constraint:
        return pool

    result = []
    for card in pool:
        mechanics = card.get("mechanics", []) or []
        race = card.get("race", "") or ""
        card_type = card.get("type", "") or card.get("card_type", "") or ""

        if constraint == "DEATHRATTLE":
            if "DEATHRATTLE" in mechanics:
                result.append(card)
        elif constraint == "DRAGON":
            if "DRAGON" in race.upper():
                result.append(card)
        elif constraint in mechanics:
            result.append(card)
        elif constraint.upper() in race.upper():
            result.append(card)

    return result


# Declarative constraint map — English keyword → mechanics constraint.
# Extensible: add new races/types here without touching logic.
_DARK_GIFT_CONSTRAINT_MAP: list[tuple[str, str]] = [
    ("deathrattle", "DEATHRATTLE"),
    ("dragon",      "DRAGON"),
    ("demon",       "DEMON"),
    ("undead",      "UNDEAD"),
    ("elemental",   "ELEMENTAL"),
    ("beast",       "BEAST"),
    ("murloc",      "MURLOC"),
    ("pirate",      "PIRATE"),
    ("mech",        "MECH"),
    ("naga",        "NAGA"),
]


def parse_dark_gift_constraint(english_text: str) -> str:
    """Parse the type constraint from a Dark Gift discover card.

    Uses English text keyword matching only — no regex, no Chinese text.
    Design standard: Standard 4 (Constraint Parsing via Structured Data).

    E.g., "Discover a Dark Gift Deathrattle minion" -> "DEATHRATTLE"
    """
    en = (english_text or "").lower()
    if "dark gift" not in en:
        return ""
    for keyword, constraint in _DARK_GIFT_CONSTRAINT_MAP:
        if keyword in en:
            return constraint
    return ""


def has_dark_gift_discover(english_text: str) -> bool:
    """Check if card text triggers a Dark Gift discover.

    Uses English text only — Standard 1 (English-Only Logic Layer).
    """
    return "dark gift" in (english_text or "").lower()

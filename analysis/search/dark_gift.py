"""dark_gift.py — 黑暗之赐 (Dark Gift) enchantment system.

Dark Gift is a discover modifier: when discovering a card "具有黑暗之赐",
a random enchantment from a fixed pool is applied to the discovered card.

20 cards in standard pool reference 黑暗之赐.
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
    DarkGiftEnchantment(name="混沌之力", attack_bonus=2, health_bonus=2),
    DarkGiftEnchantment(name="暗影之拥", attack_bonus=1, health_bonus=3),
    DarkGiftEnchantment(name="狂乱之赐", attack_bonus=3, health_bonus=1),
    DarkGiftEnchantment(name="风行之赐", keyword="WINDFURY"),
    DarkGiftEnchantment(name="吸血之赐", keyword="LIFESTEAL"),
    DarkGiftEnchantment(name="圣盾之赐", keyword="DIVINE_SHIELD"),
    DarkGiftEnchantment(name="嘲讽之赐", keyword="TAUNT"),
    DarkGiftEnchantment(name="突袭之赐", keyword="RUSH"),
    DarkGiftEnchantment(name="亡语伤害", effect="deathrattle_damage:2"),
    DarkGiftEnchantment(name="战吼抽牌", effect="battlecry_draw:1"),
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
    Also checks for "黑暗之赐" in card text as a fallback.
    """
    for card in hand:
        if isinstance(card, dict):
            if card.get("dark_gift"):
                return True
            text = card.get("text", "") or ""
            if "黑暗之赐" in text:
                return True
        elif hasattr(card, 'dark_gift') and card.dark_gift:
            return True
        elif hasattr(card, 'text') and "黑暗之赐" in (getattr(card, 'text', '') or ''):
            return True
    return False


def filter_dark_gift_pool(pool: list[dict], constraint: str = "") -> list[dict]:
    """Filter a discover pool for cards eligible for Dark Gift.

    constraint: type filter like "亡语" (deathrattle), "龙" (dragon), etc.
    Returns cards matching the constraint (all cards if constraint is empty).
    """
    if not constraint:
        return pool

    result = []
    for card in pool:
        text = card.get("text", "") or ""
        card_type = card.get("type", "") or card.get("card_type", "") or ""
        race = card.get("race", "") or ""
        mechanics = card.get("mechanics", []) or []

        # Check constraint match
        if constraint == "亡语":
            if "亡语" in text or "DEATHRATTLE" in mechanics:
                result.append(card)
        elif constraint == "龙":
            if "龙" in text or "DRAGON" in race.upper():
                result.append(card)
        elif constraint in text:
            result.append(card)
        elif constraint.upper() in race.upper():
            result.append(card)

    return result


def parse_dark_gift_constraint(card_text: str) -> str:
    """Parse the type constraint from a Dark Gift discover card.

    E.g., "发现一张具有黑暗之赐的亡语随从牌" → "亡语"
    E.g., "发现一张具有黑暗之赐的龙牌" → "龙"
    """
    if not card_text:
        return ""

    # Look for pattern: "具有黑暗之赐的XX牌"
    import re
    m = re.search(r'具有.*?黑暗之赐.*?的\s*(\S+?)\s*牌', card_text)
    if m:
        return m.group(1)

    return ""


def has_dark_gift_discover(card_text: str) -> bool:
    """Check if card text triggers a Dark Gift discover."""
    return "黑暗之赐" in (card_text or "")

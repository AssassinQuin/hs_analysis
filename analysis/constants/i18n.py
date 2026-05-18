# -*- coding: utf-8 -*-
"""Internationalization utilities for card name mapping.

All internal logic uses card IDs (e.g. 'EX1_001').
Display names are resolved at the presentation layer via these utilities.
"""
from __future__ import annotations
from typing import Optional

# Card type display names by locale
CARDTYPE_DISPLAY = {
    "zh_CN": {4: "随从", 5: "法术", 7: "武器", 3: "英雄牌", 39: "地点", 10: "英雄技能"},
    "en_US": {4: "Minion", 5: "Spell", 7: "Weapon", 3: "Hero", 39: "Location", 10: "Hero Power"},
}

# Default locale
DEFAULT_LOCALE = "zh_CN"


def card_type_display(card_type: int, locale: str = DEFAULT_LOCALE) -> str:
    """Get display name for a card type.

    Args:
        card_type: Numeric CardType value (4=MINION, 5=SPELL, etc.)
        locale: Target locale string.

    Returns:
        Localized display name, or 'Unknown' if not found.
    """
    return CARDTYPE_DISPLAY.get(locale, CARDTYPE_DISPLAY["en_US"]).get(card_type, "Unknown")


def card_name_lookup(card_id: str, locale: str = DEFAULT_LOCALE) -> str:
    """Look up card display name by card_id from the card database.

    Args:
        card_id: Hearthstone card ID like 'EX1_001'.
        locale: Target locale ('zh_CN' or 'en_US').

    Returns:
        Localized card name, or card_id as fallback.
    """
    try:
        from analysis.data.card_data import get_db
        db = get_db()
        card = db.get_card(card_id)
        if card:
            if locale == "zh_CN":
                return card.get("name", card.get("englishName", card_id))
            return card.get("englishName", card.get("name", card_id))
    except Exception:
        pass
    return card_id

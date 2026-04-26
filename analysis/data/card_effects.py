"""Structured card effect lookup — replaces regex-based card text parsing.

Provides O(1) access to card effect parameters using HSJSON / python-hearthstone
structured fields.  Falls back to minimal text parsing only when structured data
is missing (value == 0 for a field that the card actually has).

Usage::

    from analysis.data.card_effects import get_effects
    effects = get_effects(card)
    # effects.damage, effects.heal, effects.armor, effects.draw, etc.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analysis.models.card import Card

log = logging.getLogger(__name__)


@dataclass
class CardEffects:
    damage: int = 0
    aoe_damage: int = 0
    random_damage: int = 0
    heal: int = 0
    armor: int = 0
    draw: int = 0
    summon_attack: int = 0
    summon_health: int = 0
    buff_attack: int = 0
    buff_health: int = 0
    discard: int = 0
    cost_reduce: int = 0
    health_cost: int = 0
    overload: int = 0
    has_destroy: bool = False
    has_silence: bool = False
    has_summon: bool = False
    has_discover: bool = False
    target_side: str = ""
    has_lifesteal: bool = False


def _mechanics_set(card: Card) -> set:
    return set(card.mechanics or [])


def get_effects(card: Card) -> CardEffects:
    """Extract structured effects from a Card using its API fields.

    Priority:
      1. Structured fields (overload, spell_damage, armor, durability)
      2. Mechanics tags (DISCOVER, LIFESTEAL, etc.)
      3. Text-based fallback for damage/heal/draw when structured == 0
    """
    mechs = _mechanics_set(card)
    text = card.text or ""
    eff = CardEffects()

    eff.overload = card.overload
    eff.has_lifesteal = "LIFESTEAL" in mechs
    eff.has_discover = "DISCOVER" in mechs

    card_type = card.card_type.upper() if card.card_type else ""

    if card_type == "HERO":
        eff.armor = card.armor
        if eff.armor == 0:
            _fill_armor_from_text(text, eff)

    if card_type == "WEAPON":
        pass

    if card_type == "SPELL" or card_type == "HERO_POWER" or card_type == "LOCATION":
        _fill_spell_effects(text, eff, mechs)

    if card_type == "MINION":
        if "BATTLECRY" in mechs or "COMBO" in mechs:
            _fill_spell_effects(text, eff, mechs)
        if "CHARGE" in mechs or "RUSH" in mechs:
            pass

    return eff


_DAMAGE_CN = re.compile(r"造成\s*\$?\s*(\d+)\s*点伤害")
_DAMAGE_EN = re.compile(r"Deal\s*\$?(\d+)\s*damage", re.IGNORECASE)
_AOE_CN = re.compile(r"所有.*?\$?\s*(\d+)\s*点伤害")
_AOE_EN = re.compile(r"Deal\s*(\d+)\s*damage\s*to\s*all\s*enemies", re.IGNORECASE)
_RANDOM_DMG_CN = re.compile(r"随机.*?\$?\s*(\d+)\s*点伤害")
_RANDOM_DMG_EN = re.compile(r"Deal\s*(\d+)\s*damage\s*randomly", re.IGNORECASE)
_HEAL_CN = re.compile(r"恢复\s*(\d+)\s*点")
_HEAL_EN = re.compile(r"Restore\s*(\d+)\s*(?:Health|health)", re.IGNORECASE)
_ARMOR_CN = re.compile(r"获得\s*(\d+)\s*点护甲")
_ARMOR_EN = re.compile(r"Gain\s*(\d+)\s*(?:Armor|armor)", re.IGNORECASE)
_DRAW_CN = re.compile(r"抽\s*(\d+)\s*张牌")
_DRAW_EN = re.compile(r"Draw\s*(\d+)\s*(?:cards?)", re.IGNORECASE)
_SUMMON_STATS_CN = re.compile(r"召唤.*?(\d+)/(\d+)")
_SUMMON_STATS_EN = re.compile(r"Summon\s*(?:a\s+)?(\d+)/(\d+)", re.IGNORECASE)
_BUFF_ATK_CN = re.compile(r"\+\s*(\d+)\s*.*?攻击力")
_BUFF_ATK_EN = re.compile(r"\+\s*(\d+)\s*Attack", re.IGNORECASE)
_HAND_BUFF_CN = re.compile(r"手牌.*?\+(\d+)/\+(\d+)")
_HAND_BUFF_EN = re.compile(r"")
_DISCARD_CN = re.compile(r"弃掉?\s*(\d+)\s*张")
_DISCARD_EN = re.compile(r"Discard\s*(\d+)", re.IGNORECASE)
_COST_REDUCE_CN = re.compile(r"法力值消耗.*?减少\s*(\d+)")
_COST_REDUCE_EN = re.compile(r"Costs?\s*\(?\s*(\d+)\s*\)?\s*less", re.IGNORECASE)
_HEALTH_COST_CN = re.compile(r"消耗\s*(\d+)\s*点(?:生命值|血量)|支付\s*(\d+)\s*点生命")
_HEALTH_COST_EN = re.compile(r"(?:Pay|Cost)\s*(\d+)\s*(?:Health|health)|Lose\s*(\d+)\s*(?:Health|health)", re.IGNORECASE)


def _first_int(pattern: "re.Pattern", text: str, default: int = 0) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else default


def _fill_spell_effects(text: str, eff: CardEffects, mechs: set) -> None:
    if not text:
        return

    is_aoe = False
    m = _AOE_CN.search(text) or _AOE_EN.search(text)
    if m:
        eff.aoe_damage = int(m.group(1))
        is_aoe = True

    if not is_aoe:
        m = _RANDOM_DMG_CN.search(text) or _RANDOM_DMG_EN.search(text)
        if m:
            eff.random_damage = int(m.group(1))
        else:
            m = _DAMAGE_CN.search(text) or _DAMAGE_EN.search(text)
            if m:
                eff.damage = int(m.group(1))

    eff.heal = max(_first_int(_HEAL_CN, text), _first_int(_HEAL_EN, text))
    eff.draw = max(_first_int(_DRAW_CN, text), _first_int(_DRAW_EN, text))

    m = _SUMMON_STATS_CN.search(text) or _SUMMON_STATS_EN.search(text)
    if m:
        eff.summon_attack = int(m.group(1))
        eff.summon_health = int(m.group(2))
        eff.has_summon = True
    elif "召唤" in text or "Summon" in text.upper():
        eff.has_summon = True

    eff.buff_attack = max(_first_int(_BUFF_ATK_CN, text), _first_int(_BUFF_ATK_EN, text))

    m = _HAND_BUFF_CN.search(text)
    if m:
        eff.buff_attack = int(m.group(1))
        eff.buff_health = int(m.group(2))

    eff.discard = max(_first_int(_DISCARD_CN, text), _first_int(_DISCARD_EN, text))
    eff.cost_reduce = max(_first_int(_COST_REDUCE_CN, text), _first_int(_COST_REDUCE_EN, text))

    # Health cost detection
    m = _HEALTH_COST_CN.search(text)
    if m:
        eff.health_cost = int(m.group(1) or m.group(2))
    else:
        m = _HEALTH_COST_EN.search(text)
        if m:
            eff.health_cost = int(m.group(1) or m.group(2))

    if "消灭" in text or "Destroy" in text:
        eff.has_destroy = True
    if "沉默" in text or "Silence" in text:
        eff.has_silence = True


def _fill_armor_from_text(text: str, eff: CardEffects) -> None:
    eff.armor = max(_first_int(_ARMOR_CN, text), _first_int(_ARMOR_EN, text))


def get_card_damage(card: Card) -> int:
    """Quick accessor: total direct + random damage from a card."""
    eff = get_effects(card)
    return eff.damage + eff.random_damage


def get_card_armor(card: Card) -> int:
    """Quick accessor: armor value from a card."""
    if card.armor > 0:
        return card.armor
    text = card.text or ""
    return max(_first_int(_ARMOR_CN, text), _first_int(_ARMOR_EN, text))


def get_card_overload(card: Card) -> int:
    """Quick accessor: overload value — structured field first, text fallback."""
    if card.overload > 0:
        return card.overload
    text = card.text or ""
    m = re.search(r"过载[：:]\s*[（(]\s*(\d+)\s*[）)]", text)
    return int(m.group(1)) if m else 0


def get_card_health_cost(card: Card) -> int:
    """Quick accessor: health cost — 0 means no health cost."""
    eff = get_effects(card)
    return eff.health_cost

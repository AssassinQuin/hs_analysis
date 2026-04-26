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
    has_hand_transform: bool = False
    transform_attack: int = 0
    transform_health: int = 0
    has_spell_transform: bool = False  # "transform into copy of cast spell"


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

    # Spell-transform: "Each time you cast a spell, transform this into a copy of it."
    # Zero card-id hardcoding — pure effect text pattern.
    if card_type == "SPELL":
        _detect_spell_transform(card, eff)

    if card_type == "MINION":
        # Always parse text effects for minions — many have battlecry/discover/draw
        # text without the BATTLECRY mechanics tag
        _fill_spell_effects(text, eff, mechs)
        if "CHARGE" in mechs or "RUSH" in mechs:
            pass
        # Hand-transform: "while in your hand, becomes a X/Y copy of ..."
        _detect_hand_transform(card, eff)

    return eff


_DAMAGE_CN = re.compile(r"造成\s*\$?\s*[#＃]?\s*[（(]?\s*(\d+)\s*[）)]?\s*点伤害")
_DAMAGE_EN = re.compile(r"Deal\s*\$?(\d+)\s*damage", re.IGNORECASE)
_AOE_CN = re.compile(r"所有.*?\$?\s*[#＃]?\s*[（(]?\s*(\d+)\s*[）)]?\s*点伤害")
_AOE_EN = re.compile(r"Deal\s*(\d+)\s*damage\s*to\s*all\s*enemies", re.IGNORECASE)
_RANDOM_DMG_CN = re.compile(r"随机.*?\$?\s*[#＃]?\s*[（(]?\s*(\d+)\s*[）)]?\s*点伤害")
_RANDOM_DMG_EN = re.compile(r"Deal\s*(\d+)\s*damage\s*randomly", re.IGNORECASE)
_HEAL_CN = re.compile(r"恢复\s*[#＃\$]?\s*[（(]?\s*(\d+)\s*[）)]?\s*点")
_HEAL_EN = re.compile(r"Restore\s*(\d+)\s*(?:Health|health)", re.IGNORECASE)
_ARMOR_CN = re.compile(r"获得\s*[#＃\$]?\s*[（(]?\s*(\d+)\s*[）)]?\s*点?\s*护甲")
_ARMOR_EN = re.compile(r"Gain\s*(\d+)\s*(?:Armor|armor)", re.IGNORECASE)
_DRAW_CN = re.compile(r"抽\s*(?:[一两二三四五六七八九十]+|\d+)\s*张牌")
_DRAW_EN = re.compile(r"Draw\s*(\d+)\s*(?:cards?)", re.IGNORECASE)
_SUMMON_STATS_CN = re.compile(r"召唤.*?(\d+)/(\d+)")
_SUMMON_STATS_EN = re.compile(r"Summon\s*(?:a\s+)?(\d+)/(\d+)", re.IGNORECASE)
_BUFF_ATK_CN = re.compile(r"\+\s*[#＃\$]?\s*[（(]?\s*(\d+)\s*[）)]?\s*攻击力")
_BUFF_ATK_EN = re.compile(r"\+\s*(\d+)\s*Attack", re.IGNORECASE)
_HAND_BUFF_CN = re.compile(r"手牌.*?\+(\d+)/\+(\d+)")
_HAND_BUFF_EN = re.compile(r"")
_DISCARD_CN = re.compile(r"弃掉?\s*(\d+)\s*张")
_DISCARD_EN = re.compile(r"Discard\s*(\d+)", re.IGNORECASE)
_COST_REDUCE_CN = re.compile(r"法力值消耗.*?减少\s*(\d+)")
_COST_REDUCE_EN = re.compile(r"Costs?\s*\(?\s*(\d+)\s*\)?\s*less", re.IGNORECASE)
_HEALTH_COST_CN = re.compile(r"消耗\s*(\d+)\s*点(?:生命值|血量)|支付\s*(\d+)\s*点生命")
_HEALTH_COST_EN = re.compile(r"(?:Pay|Cost)\s*(\d+)\s*(?:Health|health)|Lose\s*(\d+)\s*(?:Health|health)", re.IGNORECASE)

# Chinese number → digit mapping
_CN_DIGITS = {'一': 1, '两': 2, '二': 2, '三': 3, '四': 4, '五': 5,
              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}


def _first_int(pattern: "re.Pattern", text: str, default: int = 0) -> int:
    m = pattern.search(text)
    return int(m.group(1)) if m else default


def _extract_draw(text: str) -> int:
    """Extract draw count, handling both Arabic and Chinese numbers."""
    # English pattern first
    m = _DRAW_EN.search(text)
    if m:
        return int(m.group(1))
    # Chinese pattern: 抽X张牌
    m = _DRAW_CN.search(text)
    if m:
        matched = m.group(0)
        # Try to find Arabic digit
        dm = re.search(r'(\d+)', matched)
        if dm:
            return int(dm.group(1))
        # Try Chinese number
        for cn, val in _CN_DIGITS.items():
            if cn in matched:
                return val
    return 0


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
    eff.draw = _extract_draw(text)

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

    # Armor (for spells like 盾牌格挡 "Gain 5 Armor. Draw a card")
    if eff.armor == 0:
        eff.armor = max(_first_int(_ARMOR_CN, text), _first_int(_ARMOR_EN, text))

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
    # Text-based DISCOVER detection (when mechanics tag is missing)
    if "发现" in text or "Discover" in text:
        eff.has_discover = True


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


# ── Hand-transform detection (zero card-id hardcoding) ──────────────

# Pattern: "while in hand, becomes a X/Y copy of [opponent's last minion]"
_HAND_TRANSFORM_CN = re.compile(
    r"手牌中.*?变成.*?(\d+)/(\d+)\s*(?:的)?复制"
)
_HAND_TRANSFORM_EN = re.compile(
    r"(?:while|whilst).*?(?:in )?(?:your )?hand.*?"
    r"(?:becomes?|turns? into).*?"
    r"(\d+)/(\d+)",
    re.IGNORECASE,
)


def _detect_hand_transform(card: Card, eff: CardEffects) -> None:
    """Detect hand-transform effects via text patterns.

    Triggers on: "此牌在你的手牌中时，会变成...的3/4复制" (CN)
                 "While in your hand, becomes a 3/4 copy of ..." (EN)
    Sets has_hand_transform=True and transform_attack/health.
    """
    text = card.text or ""
    eng = getattr(card, "english_text", "") or card.text or ""

    m = _HAND_TRANSFORM_CN.search(text)
    if not m:
        m = _HAND_TRANSFORM_EN.search(eng)
    if m:
        eff.has_hand_transform = True
        eff.transform_attack = int(m.group(1))
        eff.transform_health = int(m.group(2))


# ── Spell-transform detection (zero card-id hardcoding) ─────────────

_SPELL_TRANSFORM_PATTERNS = [
    re.compile(r"变形成为该法术的复制", re.IGNORECASE),  # CN
    re.compile(r"transform\s+this\s+into\s+a\s+copy", re.IGNORECASE),  # EN
]


def _detect_spell_transform(card: Card, eff: CardEffects) -> None:
    """Detect spell-transform effects via text patterns.

    Triggers on: "每当你施放一个法术，变形成为该法术的复制" (CN)
                 "Each time you cast a spell, transform this into a copy of it" (EN)
    Sets has_spell_transform=True.
    """
    text = card.text or ""
    eng = getattr(card, "english_text", "") or ""

    for pat in _SPELL_TRANSFORM_PATTERNS:
        if pat.search(text) or pat.search(eng):
            eff.has_spell_transform = True
            return

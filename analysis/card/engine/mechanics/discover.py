#!/usr/bin/env python3
# [从 analysis/search/discover.py 迁移而来]
# 原文件仍保留，后续 Phase 统一 import 路径后删除原文件。
"""discover.py — Discover framework for Hearthstone AI search.

Generates discover card pools via CardIndex, resolves discover
effects by selecting the best card and adding it to hand.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from analysis.card.data.card_data import get_index
from analysis.card.engine.deterministic import DeterministicRNG, det_top_k
from analysis.card.models.card import Card
from analysis.card.constants.hs_enums import RACE_ZH_MAP as _RACE_MAP, RACE_EN_NORMALIZE as _RACE_EN_MAP

logger = logging.getLogger(__name__)

_DISCOVER_COST_RED_CN = re.compile(r'发现.*?法力值消耗减少[（(]\s*(\d+)\s*[）)]')
_DISCOVER_COST_RED_EN = re.compile(r'discover.*?costs?\s*(\d+)\s*less', re.IGNORECASE)

def _card_score(card: dict) -> float:
    """Score a discover option from raw card stats — no external scoring data."""
    card_type = (card.get('type') or '').upper()
    if card_type == 'MINION':
        atk = card.get('attack', 0) or 0
        hp = card.get('health', 0) or 0
        cost = max(card.get('cost', 0) or 0, 1)
        return (atk * 1.0 + hp * 0.8) / cost * 3.0
    cost = card.get('cost', 0) or 0
    return cost * 1.5


def get_discover_cost_reduction(source_card_text: str, english_text: str = '') -> int:
    """Check if the source card's text indicates discovered cards should cost less.
    
    Example: 宝库闯入者 "在你发现一张卡牌后，使其法力值消耗减少（1）点" → 1
    """
    # Try EN first
    if english_text:
        m = _DISCOVER_COST_RED_EN.search(english_text)
        if m:
            return int(m.group(1))
    # CN fallback
    m = _DISCOVER_COST_RED_CN.search(source_card_text or "")
    if m:
        return int(m.group(1))
    return 0


# ===================================================================
# Race name mapping (Chinese → JSON race value) — imported from hs_enums
# _RACE_MAP is now imported from analysis.card.constants.hs_enums

_TYPE_NORMALIZE = {
    '装备': 'WEAPON',
    '武器': 'WEAPON',
    '随从': 'MINION',
    '法术': 'SPELL',
    '英雄': 'HERO',
    '地标': 'LOCATION',
}

# English race normalization — imported from hs_enums as _RACE_EN_MAP


# ===================================================================
# Constraint parser
# ===================================================================

_SCHOOL_MAP_CN = {
    '火焰': 'FIRE', '冰霜': 'FROST', '暗影': 'SHADOW', '神圣': 'HOLY',
    '奥术': 'ARCANE', '自然': 'NATURE', '邪能': 'FEL',
}
_SCHOOL_MAP_EN = {
    'fire': 'FIRE', 'frost': 'FROST', 'shadow': 'SHADOW', 'holy': 'HOLY',
    'arcane': 'ARCANE', 'nature': 'NATURE', 'fel': 'FEL',
}

_COST_CEIL_CN = re.compile(r'(\d+)费(?:法术|随从|牌)')
_COST_CEIL_EN = re.compile(r'(\d+)\s*-?\s*cost', re.IGNORECASE)
_COST_LE_CN = re.compile(r'法力值消耗(?:小于等于?|不超过|≤?|<=?)\s*(\d+)')
_COST_LE_EN = re.compile(r'costs?\s*(?:at most|<=?|≤)\s*(\d)', re.IGNORECASE)


def _parse_discover_constraint(text: str, english_text: str = '') -> dict:
    if not text and not english_text:
        return {}
    result = {}
    t = text or ''
    tl = t.lower()
    el = (english_text or '').lower()

    # Card type — EN first
    if 'spell' in el:
        result['card_type'] = 'SPELL'
    elif 'minion' in el:
        result['card_type'] = 'MINION'
    elif 'weapon' in el:
        result['card_type'] = 'WEAPON'

    # CN fallback for card type
    if 'card_type' not in result:
        if '法术' in t:
            result['card_type'] = 'SPELL'
        elif '随从' in t:
            result['card_type'] = 'MINION'
        elif '武器' in t or '装备' in t:
            result['card_type'] = 'WEAPON'

    # Race — EN first
    for en, race_val in _RACE_EN_MAP.items():
        if en in el:
            result['race'] = race_val
            if 'card_type' not in result:
                result['card_type'] = 'MINION'
            break

    if 'race' not in result:
        for cn, race_val in _RACE_MAP.items():
            if cn in t:
                result['race'] = race_val
                if 'card_type' not in result:
                    result['card_type'] = 'MINION'
                break

    # Spell school filter — EN first
    if 'school' not in result:
        for en, school_val in _SCHOOL_MAP_EN.items():
            if en in el:
                result['school'] = school_val
                break
    if 'school' not in result:
        for cn, school_val in _SCHOOL_MAP_CN.items():
            if cn in t:
                result['school'] = school_val
                break

    # Cost ceiling filter — EN first
    if 'cost_max' not in result:
        m = _COST_CEIL_EN.search(el)
        if m:
            result['cost_max'] = int(m.group(1))
        else:
            m = _COST_LE_EN.search(el)
            if m:
                result['cost_max'] = int(m.group(1))
            else:
                m = _COST_CEIL_CN.search(t)
                if m:
                    result['cost_max'] = int(m.group(1))
                else:
                    m = _COST_LE_CN.search(t)
                    if m:
                        result['cost_max'] = int(m.group(1))

    return result


# ===================================================================
# Pool generation — delegates to CardIndex
# ===================================================================

def generate_discover_pool(
    hero_class: str,
    card_type: Optional[str] = None,
    race: Optional[str] = None,
    school: Optional[str] = None,
    cost_max: Optional[int] = None,
    card_set: Optional[str] = None,
    use_wild_pool: bool = False,
    from_past_only: bool = False,
) -> List[dict]:
    """Generate discover pool via CardIndex.discover_pool()."""
    try:
        idx = get_index()
        pool_kwargs: dict = {}
        if card_type:
            pool_kwargs["card_type"] = card_type
        if school:
            pool_kwargs["school"] = school
        if cost_max is not None:
            pool_kwargs["cost_max"] = cost_max
        if card_set:
            pool_kwargs["card_set"] = card_set

        if from_past_only:
            wild_pool = idx.discover_pool(
                hero_class, format="wild", **pool_kwargs,
            )
            std_pool = idx.discover_pool(
                hero_class, format="standard", **pool_kwargs,
            )
            std_dbf = {c.get("dbfId") for c in std_pool if c.get("dbfId") is not None}
            pool = [c for c in wild_pool if c.get("dbfId") not in std_dbf]
        else:
            fmt = "wild" if use_wild_pool else "standard"
            pool = idx.discover_pool(
                hero_class, format=fmt, **pool_kwargs,
            )
        if race:
            pool = [c for c in pool if race in (c.get('race', '') or '')]
        return pool
    except (ImportError, OSError) as exc:
        logger.error('Discover pool generation failed: %s', exc)
        return []


# ===================================================================
# Inlined from analysis.search.rune — DK rune system
# ===================================================================

# spellSchool → rune name (Chinese)
RUNE_MAP: dict[str, str] = {
    "FROST": "冰霜符文",
    "SHADOW": "邪恶符文",
    "FIRE": "鲜血符文",
}


def get_rune_type(card: dict) -> str | None:
    """Determine the rune type of a card.

    Checks spellSchool first, then hardcoded lookup.
    Returns rune name in Chinese (e.g., "冰霜符文") or None.
    """
    # Check spellSchool
    school = card.get("spellSchool", "") or ""
    if isinstance(school, str) and school.upper() in RUNE_MAP:
        return RUNE_MAP[school.upper()]

    return None


def filter_by_rune(pool: list[dict], rune_name: str) -> list[dict]:
    """Filter a discover pool to cards with the given rune type.

    rune_name should be Chinese: "冰霜符文", "邪恶符文", "鲜血符文".
    """
    return [c for c in pool if get_rune_type(c) == rune_name]


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


# ===================================================================
# Inlined from analysis.search.dark_gift — Dark Gift enchantment system
# ===================================================================

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


def apply_dark_gift(card: dict, rng: Optional[DeterministicRNG] = None) -> dict:
    """Apply a random Dark Gift enchantment to a card dict.

    Uses DeterministicRNG for MCTS-compatible deterministic simulation.
    If no rng is provided, creates one with default seed 0 (deterministic).

    Modifies attack/health or adds keyword/effect in-place.
    Returns the modified card.
    """
    if not DARK_GIFT_ENCHANTMENTS:
        return card

    if rng is None:
        rng = DeterministicRNG(0)
    gift = rng.choice(DARK_GIFT_ENCHANTMENTS)

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
    m = re.search(r'具有.*?黑暗之赐.*?的\s*(\S+?)\s*牌', card_text)
    if m:
        return m.group(1)

    return ""


def has_dark_gift_discover(card_text: str) -> bool:
    """Check if card text triggers a Dark Gift discover."""
    return "黑暗之赐" in (card_text or "")


# ===================================================================
# Discover resolution
# ===================================================================

def resolve_discover(state, card_text: str, hero_class: str = '', english_text: str = ''):
    try:
        if not hero_class:
            hero_class = getattr(state, 'hero', None)
            if hero_class:
                hero_class = getattr(hero_class, 'hero_class', '') or ''

        constraints = _parse_discover_constraint(card_text, english_text)
        ct = constraints.get('card_type')
        race = constraints.get('race')
        school = constraints.get('school')
        cost_max = constraints.get('cost_max')

        rune_name = parse_rune_discover_target(card_text)

        from_past_only = '来自过去' in card_text or 'from the past' in (english_text or '').lower()
        use_wild_pool = from_past_only

        pool = generate_discover_pool(
            hero_class, card_type=ct, race=race,
            school=school, cost_max=cost_max,
            use_wild_pool=use_wild_pool,
            from_past_only=from_past_only,
        )

        if rune_name and pool:
            pool = filter_by_rune(pool, rune_name)

        dark_gift_active = has_dark_gift_discover(english_text or '')
        if dark_gift_active and pool:
            dg_constraint = parse_dark_gift_constraint(english_text or '')
            if dg_constraint:
                pool = filter_dark_gift_pool(pool, dg_constraint)

        if not pool:
            chosen_raw = {
                'dbfId': 0,
                'name': '发现的随从',
                'cost': 1,
                'attack': 1,
                'health': 1,
                'type': 'MINION',
                'cardClass': 'NEUTRAL',
                'text': '',
                'rarity': '',
                'race': '',
                'mechanics': [],
            }
        else:
            sample = det_top_k(pool, min(3, len(pool)), score_fn=_card_score)
            if dark_gift_active:
                discover_rng = DeterministicRNG.from_state(state)
                sample = [apply_dark_gift(c.copy(), rng=discover_rng) for c in sample]
            chosen_raw = max(sample, key=lambda c: _card_score(c))

        chosen_card = Card.from_hsdb_dict(chosen_raw)

        # Apply discover cost reduction if source card has it
        cost_red = get_discover_cost_reduction(card_text, english_text)
        if cost_red > 0 and hasattr(chosen_card, 'cost'):
            chosen_card.cost = max(0, chosen_card.cost - cost_red)

        hand = getattr(state, 'hand', None)
        if hand is not None:
            if len(hand) >= 10:
                pass  # overdraw: discovered card is burned
            else:
                hand.append(chosen_card)

    except Exception as exc:
        logger.warning('Discover resolution failed: %s', exc)

    return state


def resolve_discover_top_k(
    state, card_text: str, hero_class: str = '', k: int = 3,
    english_text: str = '',
) -> List[tuple]:
    """Return top-k discover choices as (state, probability) pairs.

    Each state has the respective discovered card added to hand.
    Probability is uniform 1/k (random pick from pool).
    """
    if not hero_class:
        hero = getattr(state, 'hero', None)
        if hero:
            hero_class = getattr(hero, 'hero_class', '') or ''

    constraints = _parse_discover_constraint(card_text, english_text)
    ct = constraints.get('card_type')
    race = constraints.get('race')
    school = constraints.get('school')
    cost_max = constraints.get('cost_max')

    from_past_only = '来自过去' in card_text or 'from the past' in (english_text or '').lower()
    use_wild_pool = from_past_only

    pool = generate_discover_pool(
        hero_class, card_type=ct, race=race,
        school=school, cost_max=cost_max,
        use_wild_pool=use_wild_pool,
        from_past_only=from_past_only,
    )

    if not pool:
        s = state.copy()
        return [(s, 1.0)]

    sample = det_top_k(pool, min(3, len(pool)), score_fn=_card_score)
    sample.sort(key=lambda c: _card_score(c), reverse=True)
    sample = sample[:k]

    branches: List[tuple] = []
    for chosen_raw in sample:
        chosen_card = Card.from_hsdb_dict(chosen_raw)

        # Apply discover cost reduction if source card has it
        cost_red = get_discover_cost_reduction(card_text, english_text)
        if cost_red > 0 and hasattr(chosen_card, 'cost'):
            chosen_card.cost = max(0, chosen_card.cost - cost_red)

        s = state.copy()
        if len(s.hand) < 10:
            s.hand.append(chosen_card)
        prob = 1.0 / len(sample)
        branches.append((s, prob))

    if not branches:
        branches.append((state.copy(), 1.0))

    return branches

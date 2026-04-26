#!/usr/bin/env python3
"""discover.py — Discover framework for Hearthstone AI search.

Generates discover card pools via CardIndex, resolves discover
effects by selecting the best card and adding it to hand.
"""

from __future__ import annotations

import logging
import random
import re
from typing import List, Optional

from analysis.data.card_index import get_index
from analysis.models.card import Card
from analysis.utils.score_provider import ScoreProvider

logger = logging.getLogger(__name__)

_DISCOVER_COST_RED_CN = re.compile(r'发现.*?法力值消耗减少[（(]\s*(\d+)\s*[）)]')
_DISCOVER_COST_RED_EN = re.compile(r'discover.*?costs?\s*(\d+)\s*less', re.IGNORECASE)

_score_provider: Optional[ScoreProvider] = None


def _get_score_provider() -> ScoreProvider:
    global _score_provider
    if _score_provider is None:
        _score_provider = ScoreProvider()
    return _score_provider


def _card_score(card: dict) -> float:
    dbf_id = card.get('dbfId') or card.get('dbf_id')
    if dbf_id is not None:
        try:
            siv = _get_score_provider().get_score(int(dbf_id))
            if siv > 0:
                return siv
        except (TypeError, ValueError):
            pass
    card_type = (card.get('type') or '').upper()
    if card_type == 'MINION':
        return (card.get('attack', 0) + card.get('health', 0) + card.get('cost', 0)) / 3.0
    return card.get('cost', 0) * 0.8


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
# Race name mapping (Chinese → JSON race value)
# ===================================================================

_RACE_MAP = {
    '野兽': 'BEAST',
    '龙': 'DRAGON',
    '鱼人': 'MURLOC',
    '恶魔': 'DEMON',
    '元素': 'ELEMENTAL',
    '海盗': 'PIRATE',
    '机械': 'MECHANICAL',
    '亡灵': 'UNDEAD',
    '图腾': 'TOTEM',
}

_TYPE_NORMALIZE = {
    '装备': 'WEAPON',
    '武器': 'WEAPON',
    '随从': 'MINION',
    '法术': 'SPELL',
    '英雄': 'HERO',
    '地标': 'LOCATION',
}

_RACE_EN_MAP = {
    'beast': 'BEAST',
    'dragon': 'DRAGON',
    'murloc': 'MURLOC',
    'demon': 'DEMON',
    'elemental': 'ELEMENTAL',
    'pirate': 'PIRATE',
    'mechanical': 'MECHANICAL',
    'undead': 'UNDEAD',
    'totem': 'TOTEM',
}


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

        rune_name = None
        try:
            from analysis.search.rune import parse_rune_discover_target, filter_by_rune
            rune_name = parse_rune_discover_target(card_text)
        except ImportError:
            pass

        from_past_only = '来自过去' in card_text or 'from the past' in (english_text or '').lower()
        use_wild_pool = from_past_only

        pool = generate_discover_pool(
            hero_class, card_type=ct, race=race,
            school=school, cost_max=cost_max,
            use_wild_pool=use_wild_pool,
            from_past_only=from_past_only,
        )

        if rune_name and pool:
            try:
                pool = filter_by_rune(pool, rune_name)
            except (ValueError, TypeError):
                pass

        dark_gift_active = False
        try:
            from analysis.search.dark_gift import (
                has_dark_gift_discover, filter_dark_gift_pool,
                parse_dark_gift_constraint, apply_dark_gift,
            )
            dark_gift_active = has_dark_gift_discover(english_text or '')
            if dark_gift_active and pool:
                dg_constraint = parse_dark_gift_constraint(english_text or '')
                if dg_constraint:
                    pool = filter_dark_gift_pool(pool, dg_constraint)
        except ImportError:
            pass

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
            sample = random.sample(pool, min(3, len(pool)))
            if dark_gift_active:
                try:
                    from analysis.search.dark_gift import apply_dark_gift as _apply_dg
                    sample = [_apply_dg(c.copy()) for c in sample]
                except (ImportError, TypeError, ValueError):
                    pass
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

    sample = random.sample(pool, min(3, len(pool)))
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

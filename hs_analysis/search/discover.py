#!/usr/bin/env python3
"""discover.py — Discover framework for Hearthstone AI search.

Generates discover card pools from unified_standard.json, resolves discover
effects by selecting the best card and adding it to hand.
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path
from typing import List, Optional

from hs_analysis.models.card import Card

logger = logging.getLogger(__name__)

# ===================================================================
# Module-level card cache (lazy-loaded)
# ===================================================================

_CARD_CACHE: Optional[List[dict]] = None
_WILD_CACHE: Optional[List[dict]] = None


def _load_cards() -> List[dict]:
    """Lazy-load unified_standard.json, cache at module level."""
    global _CARD_CACHE
    if _CARD_CACHE is not None:
        return _CARD_CACHE
    try:
        # Resolve relative to project root
        p = Path(__file__).resolve().parent.parent.parent / 'hs_cards' / 'unified_standard.json'
        with open(p, 'r', encoding='utf-8') as f:
            _CARD_CACHE = json.load(f)
        logger.debug('Loaded %d cards from unified_standard.json', len(_CARD_CACHE))
    except Exception as exc:
        logger.error('Failed to load unified_standard.json: %s', exc)
        _CARD_CACHE = []
    return _CARD_CACHE


def _load_wild_cards() -> List[dict]:
    """Lazy-load unified_wild.json, cache at module level.

    The wild pool (~5209 cards) is used when discover text contains "来自过去"
    (from the past), indicating the player should discover from wild card pool.
    """
    global _WILD_CACHE
    if _WILD_CACHE is not None:
        return _WILD_CACHE
    try:
        p = Path(__file__).resolve().parent.parent.parent / 'hs_cards' / 'unified_wild.json'
        with open(p, 'r', encoding='utf-8') as f:
            _WILD_CACHE = json.load(f)
        logger.debug('Loaded %d cards from unified_wild.json', len(_WILD_CACHE))
    except Exception as exc:
        logger.error('Failed to load unified_wild.json: %s', exc)
        _WILD_CACHE = []
    return _WILD_CACHE


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

# Wild JSON uses Chinese/mixed type names; normalize to standard UPPERCASE
_TYPE_NORMALIZE = {
    '装备': 'WEAPON',
    '武器': 'WEAPON',
    '随从': 'MINION',
    '法术': 'SPELL',
    '英雄': 'HERO',
    '地标': 'LOCATION',
}

# English race aliases
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

def _parse_discover_constraint(text: str) -> dict:
    """Parse card text to determine discover pool constraints.

    Returns dict with optional 'card_type' and 'race' keys.
    """
    if not text:
        return {}
    result = {}
    t = text

    # Chinese patterns
    if '法术' in t:
        result['card_type'] = 'SPELL'
    elif '随从' in t:
        result['card_type'] = 'MINION'
    elif '武器' in t:
        result['card_type'] = 'WEAPON'

    # Check for race in Chinese
    for cn, race_val in _RACE_MAP.items():
        if cn in t:
            result['race'] = race_val
            # Race implies minion
            if 'card_type' not in result:
                result['card_type'] = 'MINION'
            break

    # English patterns (fallback)
    tl = t.lower()
    if not result:
        if 'spell' in tl:
            result['card_type'] = 'SPELL'
        elif 'minion' in tl:
            result['card_type'] = 'MINION'
        elif 'weapon' in tl:
            result['card_type'] = 'WEAPON'

    if 'race' not in result:
        for en, race_val in _RACE_EN_MAP.items():
            if en in tl:
                result['race'] = race_val
                if 'card_type' not in result:
                    result['card_type'] = 'MINION'
                break

    return result


# ===================================================================
# Pool generation
# ===================================================================

def generate_discover_pool(
    hero_class: str,
    card_type: Optional[str] = None,
    race: Optional[str] = None,
    use_wild_pool: bool = False,
) -> List[dict]:
    """Generate discover pool from card database.

    Filters cards by:
    - cardClass matches hero_class OR 'NEUTRAL'
    - type matches card_type if specified
    - race contains race string if specified
    - Excludes HERO and LOCATION types

    Args:
        hero_class: Hero class string (e.g. 'MAGE')
        card_type: Optional type filter (SPELL, MINION, WEAPON)
        race: Optional race filter (e.g. 'BEAST')
        use_wild_pool: If True, load from unified_wild.json instead of standard

    Returns list of card dicts (raw JSON, not Card objects).
    """
    try:
        all_cards = _load_wild_cards() if use_wild_pool else _load_cards()
    except Exception:
        return []

    pool = []
    hero_upper = hero_class.upper()
    for c in all_cards:
        cc = c.get('cardClass', '')
        ct_raw = c.get('type', '')
        # Normalize type: wild JSON may use Chinese names like '装备'
        ct = _TYPE_NORMALIZE.get(ct_raw, ct_raw).upper()

        # Class filter (case-insensitive: wild JSON uses Title Case)
        if cc.upper() != hero_upper and cc.upper() != 'NEUTRAL':
            continue

        # Exclude HERO and LOCATION
        if ct in ('HERO', 'LOCATION'):
            continue

        # Type filter
        if card_type and ct != card_type:
            continue

        # Race filter
        if race:
            card_race = c.get('race', '') or ''
            if race not in card_race:
                continue

        pool.append(c)

    return pool


# ===================================================================
# Discover resolution
# ===================================================================

def resolve_discover(state, card_text: str, hero_class: str = ''):
    """Resolve a discover effect: pick best card and add to hand.

    For search, we pick the highest-cost card (simple heuristic).
    If hand is full (>=10), card is burned.

    Args:
        state: GameState with .hand list and .hero.hero_class
        card_text: Card text containing discover effect
        hero_class: Hero class string (e.g. 'MAGE'), falls back to state

    Returns:
        state (mutated in place for search performance)
    """
    try:
        # Determine hero class
        if not hero_class:
            hero_class = getattr(state, 'hero', None)
            if hero_class:
                hero_class = getattr(hero_class, 'hero_class', '') or ''

        # Parse constraints
        constraints = _parse_discover_constraint(card_text)
        ct = constraints.get('card_type')
        race = constraints.get('race')

        # V10 Feedback: Rune discover filtering
        rune_name = None
        try:
            from hs_analysis.search.rune import parse_rune_discover_target, filter_by_rune
            rune_name = parse_rune_discover_target(card_text)
        except Exception:
            pass

        # V10 Feedback: Wild pool for "来自过去" (from the past) discover
        use_wild_pool = '来自过去' in card_text

        # Generate pool
        pool = generate_discover_pool(
            hero_class, card_type=ct, race=race,
            use_wild_pool=use_wild_pool,
        )

        # Apply rune filter if needed
        if rune_name and pool:
            try:
                pool = filter_by_rune(pool, rune_name)
            except Exception:
                pass

        # V10 Feedback: Dark Gift discover — filter + enchant
        dark_gift_active = False
        try:
            from hs_analysis.search.dark_gift import (
                has_dark_gift_discover, filter_dark_gift_pool,
                parse_dark_gift_constraint, apply_dark_gift,
            )
            dark_gift_active = has_dark_gift_discover(card_text)
            if dark_gift_active and pool:
                dg_constraint = parse_dark_gift_constraint(card_text)
                if dg_constraint:
                    pool = filter_dark_gift_pool(pool, dg_constraint)
        except Exception:
            pass

        # Fallback if pool empty
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
            # Sample up to 3, pick highest cost
            sample = random.sample(pool, min(3, len(pool)))
            # V10 Feedback: Apply Dark Gift enchantment to each sample
            if dark_gift_active:
                try:
                    from hs_analysis.search.dark_gift import apply_dark_gift as _apply_dg
                    sample = [_apply_dg(c.copy()) for c in sample]
                except Exception:
                    pass
            chosen_raw = max(sample, key=lambda c: c.get('cost', 0))

        # Convert to Card for hand compatibility
        chosen_card = Card.from_unified(chosen_raw)

        # Add to hand if not full
        hand = getattr(state, 'hand', None)
        if hand is not None and len(hand) < 10:
            hand.append(chosen_card)

    except Exception as exc:
        logger.warning('Discover resolution failed: %s', exc)

    return state

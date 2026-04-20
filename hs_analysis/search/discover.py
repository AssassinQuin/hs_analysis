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
) -> List[dict]:
    """Generate discover pool from unified_standard.json.

    Filters cards by:
    - cardClass matches hero_class OR 'NEUTRAL'
    - type matches card_type if specified
    - race contains race string if specified
    - Excludes HERO and LOCATION types

    Returns list of card dicts (raw JSON, not Card objects).
    """
    try:
        all_cards = _load_cards()
    except Exception:
        return []

    pool = []
    for c in all_cards:
        cc = c.get('cardClass', '')
        ct = c.get('type', '')

        # Class filter
        if cc != hero_class and cc != 'NEUTRAL':
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

        # Generate pool
        pool = generate_discover_pool(hero_class, card_type=ct, race=race)

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

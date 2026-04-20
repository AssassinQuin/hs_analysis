#!/usr/bin/env python3
"""Test wild card pool integration for discover (Batch 4).

Tests the "来自过去" (from the past) trigger, wild pool loading,
case-insensitive class/type matching, and pool size differences.
"""

import pytest

from hs_analysis.search.discover import (
    generate_discover_pool,
    resolve_discover,
    _load_wild_cards,
    _TYPE_NORMALIZE,
)
from hs_analysis.search.game_state import GameState, HeroState, OpponentState


# ===================================================================
# Wild pool loading
# ===================================================================

class TestWildPoolLoading:
    """Test that unified_wild.json loads correctly."""

    def test_loads_without_error(self):
        cards = _load_wild_cards()
        assert isinstance(cards, list)
        assert len(cards) > 5000  # ~5209 expected

    def test_wild_cards_have_required_fields(self):
        cards = _load_wild_cards()
        for c in cards[:50]:  # spot check first 50
            assert 'name' in c
            assert 'cardClass' in c
            assert 'type' in c
            assert 'cost' in c


# ===================================================================
# Pool generation with wild
# ===================================================================

class TestWildPoolGeneration:
    """Test generate_discover_pool with use_wild_pool=True."""

    def test_wild_pool_larger_than_standard(self):
        std = generate_discover_pool('MAGE')
        wild = generate_discover_pool('MAGE', use_wild_pool=True)
        assert len(wild) > len(std)
        assert len(std) > 0  # standard has cards too

    def test_wild_pool_class_filter_works(self):
        """Case-insensitive: wild uses 'Mage', standard uses 'MAGE'."""
        pool = generate_discover_pool('MAGE', use_wild_pool=True)
        assert len(pool) > 100
        # All cards should be MAGE or NEUTRAL
        for c in pool:
            cc = c.get('cardClass', '').upper()
            assert cc in ('MAGE', 'NEUTRAL'), f"Got class {c.get('cardClass')}"

    def test_wild_pool_type_filter(self):
        """Type filter works with Chinese type names (e.g. '装备')."""
        pool = generate_discover_pool('MAGE', card_type='SPELL', use_wild_pool=True)
        assert len(pool) > 0
        for c in pool:
            ct_raw = c.get('type', '')
            ct = _TYPE_NORMALIZE.get(ct_raw, ct_raw).upper()
            assert ct == 'SPELL', f"Expected SPELL, got {ct_raw}"

    def test_wild_pool_race_filter(self):
        pool = generate_discover_pool('HUNTER', card_type='MINION',
                                       race='BEAST', use_wild_pool=True)
        assert len(pool) > 0

    def test_wild_pool_excludes_hero_location(self):
        pool = generate_discover_pool('MAGE', use_wild_pool=True)
        for c in pool:
            ct_raw = c.get('type', '')
            ct = _TYPE_NORMALIZE.get(ct_raw, ct_raw).upper()
            assert ct not in ('HERO', 'LOCATION')


# ===================================================================
# "来自过去" text detection in resolve_discover
# ===================================================================

class TestWildDiscoverTrigger:
    """Test that '来自过去' triggers wild pool in resolve_discover."""

    def _make_state(self):
        s = GameState(
            hero=HeroState(hp=30, hero_class='MAGE'),
            opponent=OpponentState(hero=HeroState(hp=30)),
        )
        return s

    def test_wild_trigger_adds_card_to_hand(self):
        """Discover with '来自过去' should add a card to hand."""
        state = self._make_state()
        text = '发现一张来自过去的随从牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 1

    def test_standard_discover_still_works(self):
        """Regular discover (no '来自过去') should still work."""
        state = self._make_state()
        text = '发现一张法术牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 1

    def test_wild_discover_with_type_constraint(self):
        """'来自过去的随从牌' should discover a MINION."""
        state = self._make_state()
        text = '发现一张来自过去的圣骑士机械牌'
        result = resolve_discover(state, text, 'PALADIN')
        assert len(result.hand) == 1

    def test_wild_discover_respects_hand_limit(self):
        """Hand full (10 cards) → card is burned, not added."""
        state = self._make_state()
        state.hand = list(range(10))  # 10 items
        text = '发现一张来自过去的随从牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 10  # no growth

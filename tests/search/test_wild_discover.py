import pytest
pytest.skip("Deleted module", allow_module_level=True)
#!/usr/bin/env python3
"""Test wild card pool integration for discover (Batch 4).

Tests the "来自过去" (from the past) trigger, wild pool via CardIndex,
and pool size differences.
"""

import pytest

from analysis.data.card_index import get_index
from analysis.engine.mechanics.discover import (
    generate_discover_pool,
    resolve_discover,
    _TYPE_NORMALIZE,
)
from analysis.engine.state import GameState, HeroState, OpponentState


class TestWildPoolGeneration:
    """Test generate_discover_pool with use_wild_pool=True."""

    def test_wild_pool_larger_than_standard(self):
        std = generate_discover_pool('MAGE')
        wild = generate_discover_pool('MAGE', use_wild_pool=True)
        assert len(wild) > len(std)
        assert len(std) > 0

    def test_wild_pool_class_filter_works(self):
        pool = generate_discover_pool('MAGE', use_wild_pool=True)
        assert len(pool) > 0
        for c in pool:
            cc = c.get('cardClass', '').upper()
            assert cc in ('MAGE', 'NEUTRAL'), f"Got class {c.get('cardClass')}"

    def test_wild_pool_type_filter(self):
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


class TestWildDiscoverTrigger:
    """Test that '来自过去' triggers wild pool in resolve_discover."""

    def _make_state(self):
        s = GameState(
            hero=HeroState(hp=30, hero_class='MAGE'),
            opponent=OpponentState(hero=HeroState(hp=30)),
        )
        return s

    def test_wild_trigger_adds_card_to_hand(self):
        state = self._make_state()
        text = '发现一张来自过去的随从牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 1

    def test_standard_discover_still_works(self):
        state = self._make_state()
        text = '发现一张法术牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 1

    def test_wild_discover_with_type_constraint(self):
        state = self._make_state()
        text = '发现一张来自过去的圣骑士机械牌'
        result = resolve_discover(state, text, 'PALADIN')
        assert len(result.hand) == 1

    def test_wild_discover_respects_hand_limit(self):
        state = self._make_state()
        state.hand = list(range(10))
        text = '发现一张来自过去的随从牌'
        result = resolve_discover(state, text, 'MAGE')
        assert len(result.hand) == 10


class TestCardIndexWildSupport:
    """Test CardIndex wild format support."""

    def test_index_has_wild_cards(self):
        idx = get_index()
        wild = idx.get_pool(format="wild")
        assert len(wild) > 5000

    def test_index_wild_discover_pool(self):
        idx = get_index()
        pool = idx.discover_pool("MAGE", format="wild")
        assert len(pool) > 0
        for c in pool:
            cc = c.get('cardClass', '').upper()
            assert cc in ('MAGE', 'NEUTRAL')

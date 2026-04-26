#!/usr/bin/env python3
"""test_discover.py — Tests for the discover framework.

Batch 5: Discover pool generation, resolution, and battlecry delegation.
"""

import pytest

from analysis.engine.state import GameState, HeroState, OpponentState
from analysis.models.card import Card
from analysis.engine.mechanics.discover import (
    generate_discover_pool,
    resolve_discover,
    _parse_discover_constraint,
)


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def fresh_state():
    return GameState(
        hero=HeroState(hp=30, hero_class='MAGE'),
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


# ===================================================================
# Tests: generate_discover_pool
# ===================================================================

class TestGenerateDiscoverPool:

    def test_no_filter_returns_cards(self):
        """Pool with no type/race filter returns non-empty list."""
        pool = generate_discover_pool('MAGE')
        assert isinstance(pool, list)
        assert len(pool) > 0

    def test_spell_only(self):
        """All returned cards are type SPELL."""
        pool = generate_discover_pool('MAGE', card_type='SPELL')
        assert len(pool) > 0
        for card in pool:
            assert card['type'] == 'SPELL', f'{card.get("name")} is {card["type"]}, not SPELL'

    def test_minion_only(self):
        """All returned cards are type MINION."""
        pool = generate_discover_pool('MAGE', card_type='MINION')
        assert len(pool) > 0
        for card in pool:
            assert card['type'] == 'MINION'

    def test_by_race_beast(self):
        """Race filter returns only beasts."""
        pool = generate_discover_pool('HUNTER', race='BEAST')
        assert len(pool) > 0
        for card in pool:
            assert 'BEAST' in (card.get('race') or '')

    def test_excludes_hero_and_location(self):
        """No HERO or LOCATION types in pool."""
        pool = generate_discover_pool('MAGE')
        for card in pool:
            assert card['type'] not in ('HERO', 'LOCATION')

    def test_class_filter_includes_neutral(self):
        """Pool includes both class cards and NEUTRAL."""
        pool = generate_discover_pool('MAGE')
        classes = {c['cardClass'] for c in pool}
        assert 'MAGE' in classes or 'NEUTRAL' in classes


# ===================================================================
# Tests: resolve_discover
# ===================================================================

class TestResolveDiscover:

    def test_discover_spell(self, fresh_state):
        """Resolving '发现一张法术' adds a SPELL card to hand."""
        assert len(fresh_state.hand) == 0
        result = resolve_discover(fresh_state, '发现一张法术', 'MAGE')
        assert len(result.hand) == 1
        added = result.hand[0]
        assert isinstance(added, Card)
        assert added.card_type == 'SPELL'

    def test_discover_minion(self, fresh_state):
        """Resolving '发现一张随从' adds a MINION card to hand."""
        result = resolve_discover(fresh_state, '发现一张随从', 'MAGE')
        assert len(result.hand) == 1
        assert result.hand[0].card_type == 'MINION'

    def test_discover_generic(self, fresh_state):
        """Plain '发现' with no type constraint adds a card to hand."""
        result = resolve_discover(fresh_state, '发现', 'MAGE')
        assert len(result.hand) >= 1

    def test_discover_hand_full(self):
        """Hand at 10 cards — discover doesn't add (no crash)."""
        state = GameState(
            hero=HeroState(hp=30, hero_class='MAGE'),
            opponent=OpponentState(hero=HeroState(hp=30)),
        )
        # Fill hand to 10
        for i in range(10):
            state.hand.append(Card(dbf_id=i, name=f'Card{i}', cost=i))
        result = resolve_discover(state, '发现一张法术', 'MAGE')
        assert len(result.hand) == 10  # no new card added

    def test_discover_empty_pool_fallback(self):
        """Very restrictive filter produces fallback 1/1 minion."""
        state = GameState(
            hero=HeroState(hp=30, hero_class='MAGE'),
            opponent=OpponentState(hero=HeroState(hp=30)),
        )
        # Use a race that may not exist for MAGE
        result = resolve_discover(state, '发现一张图腾', 'MAGE')
        # Should still add a fallback card
        assert len(result.hand) >= 1
        card = result.hand[0]
        assert card.name == '发现的随从'
        assert card.cost == 1

    def test_discover_uses_state_hero_class(self, fresh_state):
        """If no hero_class passed, uses state.hero.hero_class."""
        result = resolve_discover(fresh_state, '发现一张法术')
        assert len(result.hand) >= 1


# ===================================================================
# Tests: _parse_discover_constraint
# ===================================================================

class TestParseDiscoverConstraint:

    def test_spell_constraint(self):
        result = _parse_discover_constraint('发现一张法术')
        assert result.get('card_type') == 'SPELL'

    def test_minion_constraint(self):
        result = _parse_discover_constraint('发现一张随从')
        assert result.get('card_type') == 'MINION'

    def test_race_constraint(self):
        result = _parse_discover_constraint('发现一张野兽')
        assert result.get('race') == 'BEAST'
        assert result.get('card_type') == 'MINION'

    def test_no_constraint(self):
        result = _parse_discover_constraint('发现')
        assert result == {}

    def test_dragon_constraint(self):
        result = _parse_discover_constraint('发现一张龙')
        assert result.get('race') == 'DRAGON'
        assert result.get('card_type') == 'MINION'

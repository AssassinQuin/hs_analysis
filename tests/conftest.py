#!/usr/bin/env python3
"""Shared pytest fixtures for evaluator tests.

Provides _make_card and _make_state helpers used across all evaluator test files.
Import via: from tests.conftest import make_card, make_state
"""

from __future__ import annotations

import pytest

from analysis.models.card import Card
from analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)


@pytest.fixture
def make_card():
    """Factory fixture: returns a _make_card(**overrides) -> Card function."""
    def _make_card(**kwargs) -> Card:
        defaults = dict(
            dbf_id=1,
            name="Test Card",
            cost=3,
            original_cost=3,
            card_type="MINION",
            attack=3,
            health=3,
            score=5.0,
            text="",
            mechanics=[],
        )
        defaults.update(kwargs)
        return Card(**defaults)
    return _make_card


@pytest.fixture
def make_state():
    """Factory fixture: returns a _make_state(**overrides) -> GameState function."""
    def _make_state(**kwargs) -> GameState:
        defaults = dict(
            hero=HeroState(hp=30, armor=0),
            mana=ManaState(available=5, max_mana=5),
            board=[],
            hand=[],
            cards_played_this_turn=[],
            opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
            turn_number=5,
        )
        defaults.update(kwargs)
        return GameState(**defaults)
    return _make_state

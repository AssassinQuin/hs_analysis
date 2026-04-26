#!/usr/bin/env python3
"""Shared pytest fixtures for evaluator tests.

Provides _make_card and _make_state helpers used across all evaluator test files.
Import via: from tests.conftest import make_card, make_state
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from analysis.models.card import Card
from analysis.engine.state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)

# ---------------------------------------------------------------------------
#  Power.log fixtures (session-scoped to avoid redundant parsing)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_POWER_LOG = _PROJECT_ROOT / "Power.log"


@pytest.fixture(scope="session")
def power_log_path():
    """Return the path to Power.log, skip session if not found."""
    if not _POWER_LOG.exists():
        pytest.skip("Power.log not found in project root", allow_module_level=True)
    return str(_POWER_LOG)


@pytest.fixture(scope="session")
def parsed_power_log(power_log_path):
    """Parse Power.log once per test session via power_parser."""
    from analysis.search.power_parser import parse_power_log

    game = parse_power_log(power_log_path)
    if not game:
        pytest.skip("Power.log parse returned None", allow_module_level=True)
    return game


@pytest.fixture(scope="session")
def game_tracker_loaded(power_log_path):
    """GameTracker with Power.log pre-loaded (session-scoped)."""
    pytest.importorskip("hslog")
    pytest.importorskip("hearthstone")
    from analysis.watcher.game_tracker import GameTracker

    tracker = GameTracker()
    tracker.load_file(power_log_path)
    return tracker


@pytest.fixture(scope="session")
def exported_game(game_tracker_loaded):
    """Exported entity tree from the pre-loaded GameTracker."""
    return game_tracker_loaded.export_entities()


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

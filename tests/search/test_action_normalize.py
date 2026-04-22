#!/usr/bin/env python3
"""test_action_normalize.py — Tests for action normalization utilities."""

import pytest

from analysis.search.rhea_engine import Action
from analysis.search.game_state import GameState
from analysis.search.action_normalize import (
    action_hash,
    are_commutative,
    normalize_chromosome,
    is_canonical,
)


@pytest.fixture
def state():
    return GameState()


def test_action_hash_deterministic():
    """Same action produces same hash."""
    a = Action(action_type="ATTACK", source_index=0, target_index=0)
    assert action_hash(a) == action_hash(a)


def test_action_hash_different_types():
    """Different action types produce different hashes."""
    a1 = Action(action_type="ATTACK", source_index=0, target_index=0)
    a2 = Action(action_type="PLAY", card_index=0)
    assert action_hash(a1) != action_hash(a2)


def test_are_commutative_two_attacks(state):
    """Two ATTACK actions with different sources are commutative."""
    a1 = Action(action_type="ATTACK", source_index=0, target_index=0)
    a2 = Action(action_type="ATTACK", source_index=1, target_index=0)
    assert are_commutative(a1, a2, state) is True


def test_are_commutative_play_actions(state):
    """PLAY actions are NOT commutative."""
    a1 = Action(action_type="PLAY", card_index=0)
    a2 = Action(action_type="PLAY", card_index=1)
    assert are_commutative(a1, a2, state) is False


def test_normalize_sorts_commutative_group(state):
    """Consecutive commutative attacks get sorted by action_hash."""
    a1 = Action(action_type="ATTACK", source_index=2, target_index=0)
    a2 = Action(action_type="ATTACK", source_index=0, target_index=0)
    chromo = [a1, a2]
    result = normalize_chromosome(chromo, state)
    # After normalization, lower source_index should come first
    assert result[0].source_index == 0
    assert result[1].source_index == 2


def test_normalize_preserves_non_commutative(state):
    """PLAY actions stay in original order."""
    a1 = Action(action_type="PLAY", card_index=1)
    a2 = Action(action_type="PLAY", card_index=0)
    chromo = [a1, a2]
    result = normalize_chromosome(chromo, state)
    assert result[0].card_index == 1
    assert result[1].card_index == 0


def test_is_canonical_true(state):
    """Already normalized chromosome → True."""
    a1 = Action(action_type="ATTACK", source_index=0, target_index=0)
    a2 = Action(action_type="ATTACK", source_index=2, target_index=0)
    chromo = [a1, a2]
    assert is_canonical(chromo, state) is True


def test_is_canonical_false(state):
    """Unsorted commutative group → False."""
    a1 = Action(action_type="ATTACK", source_index=2, target_index=0)
    a2 = Action(action_type="ATTACK", source_index=0, target_index=0)
    chromo = [a1, a2]
    assert is_canonical(chromo, state) is False


def test_empty_chromosome(state):
    """Empty list stays empty."""
    assert normalize_chromosome([], state) == []


def test_single_action(state):
    """Single action is always canonical."""
    a = Action(action_type="ATTACK", source_index=0, target_index=0)
    chromo = [a]
    assert is_canonical(chromo, state) is True

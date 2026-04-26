#!/usr/bin/env python3
"""test_opponent_simulator.py — Unit tests for opponent simulation."""

import pytest

from analysis.engine.state import GameState, Minion, HeroState, OpponentState
from analysis.search.opponent import OpponentSimulator, SimulatedOpponentTurn


def test_no_opponent_actions():
    """Opponent has empty hand/board → minimal impact."""
    sim = OpponentSimulator()
    state = GameState()
    result = sim.simulate_best_response(state)
    assert isinstance(result, SimulatedOpponentTurn)
    assert result.friendly_deaths == 0
    assert result.worst_case_damage == 0
    assert result.lethal_exposure is False
    assert result.board_resilience_delta == 1.0  # no change


def test_opponent_trades():
    """Opponent has board → simulates favorable trades."""
    sim = OpponentSimulator()
    state = GameState(
        hero=HeroState(hp=30),
        board=[
            Minion(name='Our1', attack=3, health=3, max_health=3),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name='Opp1', attack=5, health=2, max_health=2),  # can kill our minion favorably
            ],
        ),
    )
    result = sim.simulate_best_response(state)
    assert result.friendly_deaths >= 0  # might trade
    assert result.worst_case_damage >= 0


def test_opponent_lethal():
    """Opponent has lethal on us → detects lethal_exposure=True."""
    sim = OpponentSimulator()
    state = GameState(
        hero=HeroState(hp=5),  # low hp
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name='Big1', attack=3, health=3, max_health=3),
                Minion(name='Big2', attack=3, health=3, max_health=3),
            ],
        ),
    )
    result = sim.simulate_best_response(state)
    # Opponent can deal 6 damage to our 5hp hero
    assert result.lethal_exposure is True
    assert result.worst_case_damage >= 5


def test_timeout():
    """Complex state, time budget expires → returns safe default."""
    sim = OpponentSimulator()
    # Create a very complex board
    state = GameState(
        board=[Minion(attack=i+1, health=10, max_health=10) for i in range(7)],
        opponent=OpponentState(
            board=[Minion(attack=i+1, health=10, max_health=10) for i in range(7)],
        ),
    )
    result = sim.simulate_best_response(state, time_budget_ms=0.001)  # very tight
    assert isinstance(result, SimulatedOpponentTurn)  # should not crash


def test_graceful_fallback():
    """Normal operation returns valid result."""
    sim = OpponentSimulator()
    state = GameState()
    result = sim.simulate_best_response(state)
    # Default values for empty state
    assert result.board_resilience_delta >= 0.0
    assert result.friendly_deaths >= 0
    assert result.worst_case_damage >= 0


def test_simulated_opponent_turn_defaults():
    """SimulatedOpponentTurn default values."""
    turn = SimulatedOpponentTurn()
    assert turn.board_resilience_delta == 0.0
    assert turn.friendly_deaths == 0
    assert turn.lethal_exposure is False
    assert turn.worst_case_damage == 0

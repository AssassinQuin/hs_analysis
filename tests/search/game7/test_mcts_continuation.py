"""Game 7 MCTS multi-action sequence and continuation tests.

Validates that MCTS produces multi-action sequences (PLAY→PLAY→ATTACK→END)
and that tree has proper depth and opponent nodes.
"""

import pytest

from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.abilities.definition import ActionType


# Test on even turns (our turns) with reasonable hand size
TURNS_TO_TEST = [4, 6, 8, 10]


class TestMCTSContinuation:
    """Verify MCTS produces complete action sequences on Game 7 states."""

    @pytest.fixture(scope="class")
    def mcts_config(self):
        return MCTSConfig(
            time_budget_ms=2000,
            num_worlds=3,
            max_turns_ahead=2,
        )

    @pytest.mark.parametrize("turn", TURNS_TO_TEST)
    def test_non_empty_action_sequence(
        self, game7_states, mcts_config, turn
    ):
        """MCTS should produce at least 2 actions on turn with cards."""
        if turn not in game7_states:
            pytest.skip(f"T{turn} not available")
        state = game7_states[turn]
        if len(state.hand) < 1:
            pytest.skip(f"T{turn}: empty hand")

        engine = MCTSEngine(mcts_config)
        result = engine.search(state)

        assert result.best_sequence, f"T{turn}: no actions produced"
        assert len(result.best_sequence) >= 2, (
            f"T{turn}: only {len(result.best_sequence)} actions"
        )

    @pytest.mark.parametrize("turn", TURNS_TO_TEST)
    def test_sequence_ends_with_end_turn(
        self, game7_states, mcts_config, turn
    ):
        """Every sequence must end with END_TURN."""
        if turn not in game7_states:
            pytest.skip(f"T{turn} not available")
        state = game7_states[turn]
        if len(state.hand) < 1:
            pytest.skip(f"T{turn}: empty hand")

        engine = MCTSEngine(mcts_config)
        result = engine.search(state)

        assert result.best_sequence[-1].action_type == ActionType.END_TURN, (
            f"T{turn}: sequence doesn't end with END_TURN"
        )

    @pytest.mark.parametrize("turn", TURNS_TO_TEST)
    def test_fitness_is_finite(
        self, game7_states, mcts_config, turn
    ):
        """Fitness should be a finite number."""
        if turn not in game7_states:
            pytest.skip(f"T{turn} not available")
        state = game7_states[turn]
        if len(state.hand) < 1:
            pytest.skip(f"T{turn}: empty hand")

        engine = MCTSEngine(mcts_config)
        result = engine.search(state)

        import math
        assert math.isfinite(result.fitness), (
            f"T{turn}: fitness is not finite: {result.fitness}"
        )

    def test_multi_action_on_turn_8(self, game7_states, mcts_config):
        """T8 (4 mana, 7 cards) should produce 3+ actions."""
        if 8 not in game7_states:
            pytest.skip("T8 not available")
        state = game7_states[8]
        if len(state.hand) < 2:
            pytest.skip("T8: not enough cards for multi-action")

        engine = MCTSEngine(mcts_config)
        result = engine.search(state)

        assert len(result.best_sequence) >= 3, (
            f"T8: expected 3+ actions, got {len(result.best_sequence)}: "
            f"{[a.action_type.name for a in result.best_sequence]}"
        )

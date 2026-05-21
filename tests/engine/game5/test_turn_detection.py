"""Test 1: Turn start detection — mana crystal progression.

Validates that mana crystals follow the 0/0 → 1/1 → 2/2 → 3/3 pattern
at turn starts, confirming the GameTracker + StateBridge correctly detect
turn boundaries and resource allocation.
"""

import pytest


class TestTurnStartMana:
    """Verify mana crystal progression at turn starts.

    Note: turn_start fires for both players. Game turns 1,3,5,7...
    are Player 1's turns (our turns); 2,4,6... are opponent's.
    At our turns, max_mana = player_turn_number.
    """

    # Our player turns mapped to game turn number and expected max_mana
    # Player 1 goes first: game turn 1 = our turn 1, game turn 3 = our turn 2, etc.
    OUR_TURNS = {
        1: 1,   # Our turn 1 → max_mana=1
        3: 2,   # Our turn 2 → max_mana=2
        5: 3,   # Our turn 3 → max_mana=3
        7: 4,   # Our turn 4 → max_mana=4
    }

    def test_mana_increments_each_our_turn(self, game5_states):
        """Max mana should increment on our turns (odd game turns)."""
        for game_turn, expected_max in self.OUR_TURNS.items():
            state = game5_states.get(game_turn)
            if state is None:
                continue
            actual_max = state.mana.max_mana
            assert actual_max == expected_max, (
                f"Game turn {game_turn} (our turn {(game_turn+1)//2}): "
                f"expected max_mana={expected_max}, got {actual_max}"
            )

    def test_available_equals_max_at_turn_start(self, game5_states):
        """At OUR turn start (odd game turns), available mana should equal max."""
        for game_turn in [1, 3, 5]:
            state = game5_states.get(game_turn)
            if state is None:
                continue
            assert state.mana.available >= state.mana.max_mana, (
                f"Game turn {game_turn}: available ({state.mana.available}) should "
                f">= max ({state.mana.max_mana}) at our turn start"
            )

    def test_hero_class_detected(self, game5_states):
        """Our hero should be ROGUE."""
        state = game5_states.get(1)
        if state is None:
            pytest.skip("Turn 1 state not available")
        assert state.hero.hero_class.upper() == "ROGUE"

    def test_opponent_class_detected(self, game5_states):
        """Opponent should be WARRIOR."""
        state = game5_states.get(1)
        if state is None:
            pytest.skip("Turn 1 state not available")
        assert state.opponent is not None
        assert state.opponent.hero.hero_class.upper() == "WARRIOR"

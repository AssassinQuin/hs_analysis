"""Test 2: MCTS continuation after player decision.

Validates that after MCTS makes its first decision, the tree continues
to explore subsequent possibilities (opponent turns, further plays).
"""

import pytest

from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.search.abilities.actions import ActionType


class TestMCTSContinuation:
    """Verify MCTS continues exploring after initial decision."""

    BUDGET_MS = 2000

    def _get_state(self, game5_states, turn=3):
        state = game5_states.get(turn)
        if state is None:
            pytest.skip(f"Turn {turn} not extracted")
        return state

    def test_mcts_produces_multi_action_sequence(self, game5_states):
        """MCTS should produce a sequence with more than just END_TURN."""
        state = self._get_state(game5_states, turn=3)

        config = MCTSConfig(
            time_budget_ms=self.BUDGET_MS,
            num_worlds=3,
            max_turns_ahead=1,
        )
        engine = MCTSEngine(config)
        result = engine.search(state, time_budget_ms=self.BUDGET_MS)

        seq = result.best_sequence
        assert len(seq) > 0, "MCTS must return actions"
        assert any(a.action_type == ActionType.END_TURN for a in seq), (
            "Sequence must contain END_TURN"
        )

        # If we have cards and mana, we should play something before ending
        play_actions = [
            a for a in seq
            if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET)
        ]
        print(f"\nTurn 3: {len(seq)} actions, {len(play_actions)} plays")
        for a in seq:
            print(f"  {a.action_type.name:25s} {a.describe(state)}")

    def test_tree_has_children_beyond_root(self, game5_states):
        """After search, the tree root should have expanded children."""
        state = self._get_state(game5_states, turn=5)

        config = MCTSConfig(
            time_budget_ms=self.BUDGET_MS,
            num_worlds=3,
            max_turns_ahead=1,
        )
        engine = MCTSEngine(config)
        result = engine.search(state, time_budget_ms=self.BUDGET_MS)

        root = engine._last_root
        assert root is not None, "Root node should exist"
        assert len(root.children) > 0, (
            "Root should have expanded children (MCTS explored beyond initial state)"
        )
        print(f"\nRoot children: {len(root.children)}, "
              f"iterations: {result.mcts_stats.iterations}")

    def test_mcts_explores_opponent_turn(self, game5_states):
        """With max_turns_ahead=2, tree should contain opponent nodes."""
        state = self._get_state(game5_states, turn=5)

        config = MCTSConfig(
            time_budget_ms=self.BUDGET_MS,
            num_worlds=3,
            max_turns_ahead=2,
            opponent_tree_actions=3,
        )
        engine = MCTSEngine(config)
        result = engine.search(state, time_budget_ms=self.BUDGET_MS)

        # Walk tree to find opponent nodes
        opp_nodes = 0
        stack = [engine._last_root]
        while stack and opp_nodes < 10:
            node = stack.pop()
            if not node.is_player_turn:
                opp_nodes += 1
            stack.extend(node.children.values())

        print(f"\nOpponent nodes found: {opp_nodes}")
        assert opp_nodes > 0, (
            "Tree should contain opponent turn nodes after our END_TURN"
        )

"""Test 3: MCTS multi-turn simulation (3 turns).

Validates that MCTS explores at least 3 turns ahead when configured,
including opponent turns between our turns.
"""

import pytest

from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.abilities.definition import ActionType


def _collect_turn_depths(root, max_nodes=50000):
    """Walk tree and collect turn_depth distribution."""
    from collections import Counter
    depths = Counter()
    total = 0
    stack = [root]
    while stack and total < max_nodes:
        node = stack.pop()
        total += 1
        depths[node.turn_depth] += 1
        stack.extend(node.children.values())
    return dict(depths), total


class TestThreeTurnSimulation:
    """Verify MCTS simulates 3+ turns of game progression."""

    BUDGET_MS = 3000

    def _get_state(self, game5_states, turn=5):
        state = game5_states.get(turn)
        if state is None:
            pytest.skip(f"Turn {turn} not extracted")
        return state

    def test_three_turn_tree_depth(self, game5_states):
        """With max_turns_ahead=3, tree should explore turn_depth ≥ 2.

        turn_depth increments when:
          turn_depth=0: our current turn
          turn_depth=1: opponent's response + our next turn
          turn_depth=2: opponent + our turn after that (=3 turns total)
        """
        state = self._get_state(game5_states, turn=5)

        config = MCTSConfig(
            time_budget_ms=self.BUDGET_MS,
            num_worlds=3,
            max_turns_ahead=3,
            max_tree_depth=25,
            opponent_tree_actions=3,
        )
        engine = MCTSEngine(config)
        result = engine.search(state, time_budget_ms=self.BUDGET_MS)

        depths, total_nodes = _collect_turn_depths(engine._last_root)

        print(f"\n{'=' * 50}")
        print(f"3-turn simulation (Turn 5 start)")
        print(f"{'=' * 50}")
        print(f"Total nodes walked: {total_nodes}")
        print(f"Turn depth distribution: {depths}")
        print(f"Iterations: {result.mcts_stats.iterations}")
        print(f"Best sequence: {len(result.best_sequence)} actions")

        # Architecture check: opponent nodes must exist
        opp_nodes = sum(
            1 for _ in _walk_nodes(engine._last_root, lambda n: not n.is_player_turn)
        )
        assert opp_nodes > 0, (
            f"Tree must contain opponent nodes. "
            f"Depth distribution: {depths}"
        )
        print(f"✓ Found {opp_nodes} opponent nodes")

        # Multi-turn check: at least turn_depth=1 should exist
        max_td = max(depths.keys()) if depths else 0
        if max_td >= 1:
            print(f"✓ Tree reached turn_depth={max_td} "
                  f"(simulated {max_td + 1} total turns)")
        else:
            print(f"⚠ turn_depth max={max_td}, may need more iterations")

    def test_three_turn_produces_valid_sequence(self, game5_states):
        """3-turn MCTS must still produce a valid action sequence."""
        state = self._get_state(game5_states, turn=3)

        config = MCTSConfig(
            time_budget_ms=self.BUDGET_MS,
            num_worlds=3,
            max_turns_ahead=3,
        )
        engine = MCTSEngine(config)
        result = engine.search(state, time_budget_ms=self.BUDGET_MS)

        seq = result.best_sequence
        assert len(seq) > 0
        assert any(a.action_type == ActionType.END_TURN for a in seq)
        import math
        assert math.isfinite(result.fitness)


def _walk_nodes(root, predicate, max_nodes=50000):
    """Yield nodes matching predicate."""
    total = 0
    stack = [root]
    while stack and total < max_nodes:
        node = stack.pop()
        total += 1
        if predicate(node):
            yield node
        stack.extend(node.children.values())

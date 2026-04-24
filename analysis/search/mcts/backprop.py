#!/usr/bin/env python3
"""backprop.py — Backpropagation for MCTS.

Standard negamax backpropagation:
- Player nodes accumulate reward as-is
- Opponent nodes negate reward (zero-sum game)

Supports DUCT multi-world aggregation: all worlds share the same
tree and statistics are merged.
"""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from analysis.search.mcts.node import MCTSNode

if TYPE_CHECKING:
    pass


def backpropagate(path: List[MCTSNode], reward: float) -> None:
    """Backpropagate reward along the selection path.

    Args:
        path: Nodes visited during selection (root → leaf), not including leaf.
        reward: Evaluation result in [-1, 1] from the current player's perspective.
    """
    for node in reversed(path):
        node.visit_count += 1

        if node.is_player_turn:
            # Player node: good result → positive
            node.total_reward += reward
        else:
            # Opponent node: good result for opponent = bad for us → negate
            node.total_reward += -reward


def backpropagate_with_edges(
    path: List[MCTSNode],
    reward: float,
    actions_taken: List[tuple],
) -> None:
    """Backpropagate with edge statistics update (for future DAG/UCD support).

    Args:
        path: Nodes visited during selection.
        reward: Reward value in [-1, 1].
        actions_taken: Action keys for each step in the path.
    """
    for i, node in enumerate(reversed(path)):
        # Update node statistics
        if node.is_player_turn:
            node.total_reward += reward
        else:
            node.total_reward += -reward
        node.visit_count += 1

        # Update edge statistics
        if i < len(actions_taken) and node.parent is not None:
            ak = actions_taken[-(i + 1)]
            edge = node.parent.action_edges.get(ak)
            if edge is not None:
                edge.visit_count += 1
                edge.total_reward += reward

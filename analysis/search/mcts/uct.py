#!/usr/bin/env python3
"""uct.py — UCB1 selection policy for MCTS.

Standard UCT formula:
    UCT(n, a) = Q(n,a) + c * sqrt(ln(N(n)) / N(a))

Handles three node types:
- DECISION nodes: UCB1 over children
- CHANCE nodes: average child value (no exploration bonus)
- Opponent turn nodes: select child that minimises our Q (negamax)
"""

from __future__ import annotations

import math
import random
import logging
from typing import Optional, Tuple, List, TYPE_CHECKING

from analysis.search.mcts.config import MCTSConfig, NodeType
from analysis.search.mcts.node import MCTSNode, ActionEdge
from analysis.search.abilities.actions import action_key, ActionType

if TYPE_CHECKING:
    from analysis.search.abilities.actions import Action
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


def uct_select(
    node: MCTSNode,
    config: MCTSConfig,
) -> Optional[Tuple[tuple, MCTSNode]]:
    """Select the best child from an expanded decision node using UCB1.

    Returns:
        (action_key, child_node) or None if no children exist.
    """
    if not node.children:
        return None

    # Prioritise unvisited children (infinite UCB score)
    for ak, child in node.children.items():
        if child.visit_count == 0:
            return ak, child

    c = config.uct_constant
    log_parent = math.log(max(node.visit_count, 1))

    best_score = -float('inf')
    best_pair = None

    for ak, child in node.children.items():
        # Exploitation: Q value from this node's perspective
        q = _perspective_q(child, node)

        # Exploration: UCB bonus
        exploration = c * math.sqrt(log_parent / max(child.visit_count, 1))

        score = q + exploration
        if score > best_score:
            best_score = score
            best_pair = (ak, child)

    return best_pair


def chance_select(node: MCTSNode) -> Optional[Tuple[tuple, MCTSNode]]:
    """Select a child from a chance node by weighted sampling.

    Chance nodes represent stochastic outcomes. We sample proportional
    to visit counts (which approximates the outcome distribution).
    For unvisited children, use uniform weight.
    """
    if not node.children:
        return None

    items = list(node.children.items())
    # If any child is unvisited, pick uniformly
    if any(child.visit_count == 0 for _, child in items):
        return random.choice(items)

    # Weighted sample by visit count
    weights = [child.visit_count for _, child in items]
    total = sum(weights)
    r = random.uniform(0, total)
    cumulative = 0
    for i, (ak, child) in enumerate(items):
        cumulative += weights[i]
        if r <= cumulative:
            return ak, child
    return items[-1]


def opponent_select(
    node: MCTSNode,
    state: 'GameState',
    config: MCTSConfig,
) -> Optional[Tuple[tuple, MCTSNode]]:
    """Select action for opponent turn (non-UCT, greedy/random mix).

    80% greedy (pick child with lowest Q from our perspective),
    20% random (maintain diversity).
    """
    if not node.children:
        return None

    items = list(node.children.items())

    if random.random() < config.opponent_greedy_prob:
        # Greedy: pick the child that is worst for us (opponent maximises their gain)
        return min(items, key=lambda pair: _perspective_q(pair[1], node))
    else:
        return random.choice(items)


def select_child(
    node: MCTSNode,
    state: 'GameState',
    config: MCTSConfig,
) -> Optional[Tuple[tuple, MCTSNode]]:
    """Route to the correct selection strategy based on node type and turn."""
    if node.node_type == NodeType.CHANCE:
        return chance_select(node)

    if not node.is_player_turn:
        return opponent_select(node, state, config)

    return uct_select(node, config)


def _perspective_q(child: MCTSNode, parent: MCTSNode) -> float:
    """Get child's Q value from the parent's perspective (negamax).

    In a two-player zero-sum game, the opponent's gain is our loss.
    When parent and child have different turns, flip the Q value.
    """
    if child.visit_count == 0:
        return 0.0

    child_q = child.q_value

    # Different perspective → negate
    if parent.is_player_turn != child.is_player_turn:
        return -child_q
    return child_q

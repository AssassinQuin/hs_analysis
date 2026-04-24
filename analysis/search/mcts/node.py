#!/usr/bin/env python3
"""node.py — MCTS tree node and edge data structures.

Design decisions:
- state_hash instead of full GameState reference: saves memory, enables transposition lookup
- children indexed by action_key: O(1) lookup for expanded children
- untried_actions lazily computed: first access only, avoids cost on unvisited nodes
- NodeType distinguishes DECISION (player choice) from CHANCE (stochastic outcome)
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional, List, Dict, TYPE_CHECKING

from analysis.search.mcts.config import NodeType

if TYPE_CHECKING:
    from analysis.search.rhea.actions import Action
    from analysis.search.mcts.pruning import ActionPruner
    from analysis.search.game_state import GameState


@dataclass
class ActionEdge:
    """Directed edge in MCTS tree: parent_node → action → child_node.

    Edge statistics are kept separate from node statistics to support
    future DAG / UCD extension.
    """
    action: 'Action'
    child_node: Optional['MCTSNode'] = None

    # Edge-level statistics (for future DAG extension)
    visit_count: int = 0
    total_reward: float = 0.0

    @property
    def is_expanded(self) -> bool:
        return self.child_node is not None


@dataclass
class MCTSNode:
    """MCTS search tree node.

    Supports two node types:
    - DECISION: player makes a choice among legal actions
    - CHANCE: stochastic outcome (discover pick, random effect) —
      children represent sampled outcomes
    """

    # === Identity ===
    node_id: int
    state_hash: int
    node_type: NodeType = NodeType.DECISION
    is_terminal: bool = False
    terminal_reward: Optional[float] = None  # ±1.0 for terminal, None for non-terminal

    # === Tree structure ===
    parent: Optional['MCTSNode'] = None
    children: Dict[tuple, 'MCTSNode'] = field(default_factory=dict)
        # key = action_key(action), value = child node
    action_edges: Dict[tuple, ActionEdge] = field(default_factory=dict)
        # key = action_key(action), value = edge metadata

    # === Statistics ===
    visit_count: int = 0
    total_reward: float = 0.0

    # === Expansion control ===
    untried_actions: Optional[List['Action']] = None  # None = not yet initialized
    is_expanded: bool = False

    # === Context ===
    is_player_turn: bool = True
    depth: int = 0

    # === Progressive widening ===
    pw_threshold: int = 0

    # === Chance node fields ===
    chance_outcome: Optional[object] = None  # the sampled outcome this node represents
    stochastic_action: Optional['Action'] = None  # the action that created this chance node

    # ── Derived properties ──────────────────────────────

    @property
    def q_value(self) -> float:
        """Average reward Q(n) = total_reward / visit_count."""
        return self.total_reward / max(self.visit_count, 1)

    @property
    def is_leaf(self) -> bool:
        """Whether this node is a leaf (unexpanded or no children)."""
        return not self.children or not self.is_expanded

    @property
    def best_child_key(self) -> Optional[tuple]:
        """Key of child with highest visit count."""
        if not self.children:
            return None
        return max(self.children.keys(),
                   key=lambda k: self.children[k].visit_count)

    # ── Methods ─────────────────────────────────────────

    def get_untried_actions(
        self,
        state: 'GameState',
        pruner: Optional['ActionPruner'] = None,
    ) -> List['Action']:
        """Lazily compute untried actions on first call, then cache."""
        if self.untried_actions is None:
            from analysis.search.rhea.enumeration import enumerate_legal_actions
            all_actions = enumerate_legal_actions(state)
            if pruner is not None:
                self.untried_actions = pruner.filter(all_actions, state)
            else:
                self.untried_actions = list(all_actions)
            # Shuffle to avoid bias
            random.shuffle(self.untried_actions)
        return self.untried_actions

    def update(self, reward: float) -> None:
        """Update statistics with a reward value."""
        self.visit_count += 1
        self.total_reward += reward

    def child_for_action(self, action_key: tuple) -> Optional['MCTSNode']:
        """Look up existing child for an action key."""
        return self.children.get(action_key)

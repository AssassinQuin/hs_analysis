#!/usr/bin/env python3
"""expansion.py — Node expansion strategies for MCTS.

Features:
- Basic expansion: pop one untried action
- Progressive Widening: limit children count as function of visit count
- Chance node creation: for stochastic actions (discover, random effects)
- Heuristic action ordering: expand promising actions first
"""

from __future__ import annotations

import math
import random
import logging
from typing import Optional, Tuple, List, TYPE_CHECKING

from analysis.search.mcts.config import MCTSConfig, NodeType, ExpansionOrder
from analysis.search.mcts.node import MCTSNode, ActionEdge
from analysis.search.mcts.pruning import ActionPruner
from analysis.search.rhea.actions import Action, ActionType, action_key
from analysis.search.rhea.simulation import apply_action

if TYPE_CHECKING:
    from analysis.search.game_state import GameState
    from analysis.search.mcts.transposition import TranspositionTable

log = logging.getLogger(__name__)


class Expander:
    """Node expansion with progressive widening and chance node support."""

    def __init__(self, config: MCTSConfig, pruner: ActionPruner):
        self.config = config
        self.pruner = pruner
        self._next_id = 0

    def expand_node(
        self,
        node: MCTSNode,
        state: 'GameState',
        tt: 'TranspositionTable',
    ) -> Optional[Tuple[MCTSNode, 'GameState']]:
        """Expand a leaf node by adding one child.

        Returns:
            (child_node, new_state) or None if no expansion possible.
        """
        if node.is_terminal:
            return None

        # Check progressive widening limit
        pw_limit = int(self.config.pw_constant * (node.visit_count ** self.config.pw_alpha))
        if len(node.children) >= pw_limit and node.is_expanded:
            return None

        # Get untried actions
        untried = node.get_untried_actions(state, self.pruner)
        if not untried:
            node.is_expanded = True
            return None

        # Select action to expand
        action = self._select_expansion_action(untried, state)

        # Determine if this action produces stochastic outcomes
        if self._is_stochastic(action, state):
            return self._expand_chance_node(node, state, action, tt)
        else:
            return self._expand_deterministic(node, state, action, tt)

    def _expand_deterministic(
        self,
        node: MCTSNode,
        state: 'GameState',
        action: Action,
        tt: 'TranspositionTable',
    ) -> Optional[Tuple[MCTSNode, 'GameState']]:
        """Expand a deterministic action into a child node."""
        from analysis.search.mcts.transposition import compute_state_hash

        # Apply action to get new state
        new_state = apply_action(state, action)

        # Determine turn ownership
        is_player_turn = node.is_player_turn
        if action.action_type == ActionType.END_TURN:
            is_player_turn = not is_player_turn

        # Compute hash
        state_hash = compute_state_hash(new_state, is_player_turn)

        # Check transposition table
        if self.config.enable_transposition:
            existing = tt.get(state_hash)
            if existing is not None:
                # Reuse existing node but register as child
                ak = action_key(action)
                node.children[ak] = existing
                node.action_edges[ak] = ActionEdge(action=action, child_node=existing)
                return existing, new_state

        # Create child node
        child = MCTSNode(
            node_id=self._next_id,
            state_hash=state_hash,
            node_type=NodeType.DECISION,
            parent=node,
            is_player_turn=is_player_turn,
            depth=node.depth + 1,
        )
        self._next_id += 1

        # Check terminal
        terminal = self._check_terminal(new_state)
        if terminal is not None:
            child.is_terminal = True
            child.terminal_reward = terminal

        # Register edge
        ak = action_key(action)
        edge = ActionEdge(action=action, child_node=child)
        node.children[ak] = child
        node.action_edges[ak] = edge

        # Register in transposition table
        if self.config.enable_transposition:
            tt.put(state_hash, child)

        return child, new_state

    def _expand_chance_node(
        self,
        node: MCTSNode,
        state: 'GameState',
        action: Action,
        tt: 'TranspositionTable',
    ) -> Optional[Tuple[MCTSNode, 'GameState']]:
        """Expand a stochastic action into a chance node with sampled outcomes.

        The chance node itself doesn't correspond to a specific state.
        Its children are the sampled outcomes.
        """
        from analysis.search.mcts.transposition import compute_state_hash

        ak = action_key(action)

        # Check if chance node already exists for this action
        chance_node = node.children.get(ak)
        if chance_node is None:
            # Create the chance node
            chance_node = MCTSNode(
                node_id=self._next_id,
                state_hash=hash((node.state_hash, ak, "chance")),
                node_type=NodeType.CHANCE,
                parent=node,
                is_player_turn=node.is_player_turn,  # same turn, outcome pending
                depth=node.depth + 1,
                stochastic_action=action,
            )
            self._next_id += 1

            edge = ActionEdge(action=action, child_node=chance_node)
            node.children[ak] = chance_node
            node.action_edges[ak] = edge

        # Sample an outcome and add as child of chance node
        outcome_state = self._sample_outcome(state, action)

        # Check how many outcomes we've already sampled
        max_samples = self.config.discover_samples
        if len(chance_node.children) >= max_samples:
            # Reuse existing sampled outcomes
            existing_ak = list(chance_node.children.keys())
            chosen_ak = random.choice(existing_ak)
            outcome_node = chance_node.children[chosen_ak]
            # Reconstruct state for this outcome
            outcome_state = self._apply_outcome(state, action, outcome_node.chance_outcome)
            return outcome_node, outcome_state

        # Create a new outcome node
        outcome_hash = compute_state_hash(outcome_state, node.is_player_turn)
        outcome_node = MCTSNode(
            node_id=self._next_id,
            state_hash=outcome_hash,
            node_type=NodeType.DECISION,
            parent=chance_node,
            is_player_turn=node.is_player_turn,
            depth=chance_node.depth + 1,
            chance_outcome=self._last_outcome,
        )
        self._next_id += 1

        # Check terminal
        terminal = self._check_terminal(outcome_state)
        if terminal is not None:
            outcome_node.is_terminal = True
            outcome_node.terminal_reward = terminal

        outcome_ak = ("outcome", len(chance_node.children))
        chance_node.children[outcome_ak] = outcome_node
        chance_node.action_edges[outcome_ak] = ActionEdge(
            action=action, child_node=outcome_node
        )

        if self.config.enable_transposition:
            tt.put(outcome_hash, outcome_node)

        return outcome_node, outcome_state

    # ── Outcome sampling ───────────────────────────────

    _last_outcome: object = None

    def _is_stochastic(self, action: Action, state: 'GameState') -> bool:
        """Determine if an action produces stochastic outcomes.

        Stochastic actions include:
        - Cards with "发现" / "Discover" in text
        - Cards with "随机" / "Random" in text
        - Hero powers that discover
        """
        if action.action_type == ActionType.DISCOVER_PICK:
            return True

        card = None
        if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            idx = action.card_index
            if 0 <= idx < len(state.hand):
                card = state.hand[idx]

        if card is not None:
            text = (getattr(card, 'text', '') or '').lower()
            if any(kw in text for kw in ('发现', 'discover', '随机', 'random')):
                return True

        return False

    def _sample_outcome(self, state: 'GameState', action: Action) -> 'GameState':
        """Sample one outcome of a stochastic action.

        For discover: simulate picking a random card from discover pool.
        For random effects: just apply the action (randomness is in the effect).
        """
        # For now, just apply the action — the randomness in effects
        # will produce different outcomes naturally.
        # A more sophisticated implementation would use DiscoverModel
        # to sample specific discover choices.
        self._last_outcome = ("sampled", action.action_type.name)
        return apply_action(state, action)

    def _apply_outcome(
        self,
        state: 'GameState',
        action: Action,
        outcome: object,
    ) -> 'GameState':
        """Reconstruct state for a previously sampled outcome."""
        return apply_action(state, action)

    # ── Action selection ───────────────────────────────

    def _select_expansion_action(
        self,
        untried: List[Action],
        state: 'GameState',
    ) -> Action:
        """Select next action to expand from untried list."""
        order = self.config.expansion_order

        if order == ExpansionOrder.RANDOM:
            return untried.pop()

        elif order == ExpansionOrder.HEURISTIC:
            best = max(untried, key=lambda a: self._heuristic_score(a, state))
            untried.remove(best)
            return best

        elif order == ExpansionOrder.BALANCED:
            if random.random() < 0.5:
                return untried.pop()
            else:
                best = max(untried, key=lambda a: self._heuristic_score(a, state))
                untried.remove(best)
                return best

        return untried.pop()

    def _heuristic_score(self, action: Action, state: 'GameState') -> float:
        """Quick heuristic score for action ordering.

        Higher score = expand first.
        """
        score = 0.0

        if action.action_type == ActionType.ATTACK:
            # Prefer face attacks when opponent is low
            if action.target_index == 0:
                opp_hp = state.opponent.hero.hp
                score += max(0, 15 - opp_hp) * 0.5
            else:
                # Prefer efficient trades
                src_idx = action.source_index
                tgt_idx = action.target_index - 1
                if 0 <= src_idx < len(state.board) and 0 <= tgt_idx < len(state.opponent.board):
                    src = state.board[src_idx]
                    tgt = state.opponent.board[tgt_idx]
                    if tgt.health <= src.attack and src.health > tgt.attack:
                        score += 3.0  # favourable trade

        elif action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            card_idx = action.card_index
            if 0 <= card_idx < len(state.hand):
                card = state.hand[card_idx]
                cost = getattr(card, 'cost', 0) or 0
                atk = getattr(card, 'attack', 0) or 0
                hp = getattr(card, 'health', 0) or 0
                # Prefer high tempo plays
                score += (atk + hp - cost) * 0.3

        elif action.action_type == ActionType.HERO_POWER:
            score += 0.5  # hero power is usually decent

        elif action.action_type == ActionType.END_TURN:
            score -= 1.0  # deprioritise end turn

        return score

    # ── Helpers ────────────────────────────────────────

    def _check_terminal(self, state: 'GameState') -> Optional[float]:
        """Check if state is terminal. Returns reward or None."""
        if state.opponent.hero.hp <= 0:
            return 1.0
        if state.hero.hp <= 0:
            return -1.0
        return None

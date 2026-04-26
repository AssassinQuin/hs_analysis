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
from analysis.search.abilities.actions import Action, ActionType, action_key
from analysis.search.abilities.simulation import apply_action

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
        turn_depth = node.turn_depth
        if action.action_type == ActionType.END_TURN:
            is_player_turn = not is_player_turn
            # When opponent ends their turn, we advance a full turn
            if not node.is_player_turn:  # opponent just ended
                turn_depth += 1
                # Preserve our overload across opponent's turn.
                # Opponent's _apply_end_turn incorrectly overwrites our
                # mana.overloaded with their overload_next (0).
                our_overloaded = state.mana.overloaded
                new_state.mana.overloaded = our_overloaded
                # Advance state to our next turn
                new_state = self._advance_after_opponent_turn(new_state)

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
            turn_depth=turn_depth,
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
        """Expand a stochastic action as a single DECISION node.

        Collapses the previous CHANCE→OUTCOME 2-level structure into one node.
        Each expansion samples a fresh outcome, creating different children
        for the same stochastic action. This halves the tree depth cost.
        """
        from analysis.search.mcts.transposition import compute_state_hash

        ak = action_key(action)

        # Sample an outcome by applying the action
        outcome_state = self._sample_outcome(state, action)

        # Determine turn ownership (same logic as deterministic)
        is_player_turn = node.is_player_turn
        turn_depth = node.turn_depth
        if action.action_type == ActionType.END_TURN:
            is_player_turn = not is_player_turn
            if not node.is_player_turn:
                turn_depth += 1
                our_overloaded = state.mana.overloaded
                outcome_state.mana.overloaded = our_overloaded
                outcome_state = self._advance_after_opponent_turn(outcome_state)

        # Compute hash
        state_hash = compute_state_hash(outcome_state, is_player_turn)

        # Check transposition table
        if self.config.enable_transposition:
            existing = tt.get(state_hash)
            if existing is not None:
                # Use unique key per outcome sample to allow multiple children
                sample_ak = (ak, len(node.children))
                node.children[sample_ak] = existing
                node.action_edges[sample_ak] = ActionEdge(action=action, child_node=existing)
                return existing, outcome_state

        # Create a single DECISION child (not CHANCE)
        child = MCTSNode(
            node_id=self._next_id,
            state_hash=state_hash,
            node_type=NodeType.DECISION,
            parent=node,
            is_player_turn=is_player_turn,
            depth=node.depth + 1,  # Only +1, not +2!
            turn_depth=turn_depth,
            chance_outcome=self._last_outcome,
        )
        self._next_id += 1

        # Check terminal
        terminal = self._check_terminal(outcome_state)
        if terminal is not None:
            child.is_terminal = True
            child.terminal_reward = terminal

        # Use unique key per sample so multiple outcomes of same action can coexist
        sample_ak = (ak, len(node.children))
        edge = ActionEdge(action=action, child_node=child)
        node.children[sample_ak] = child
        node.action_edges[sample_ak] = edge

        if self.config.enable_transposition:
            tt.put(state_hash, child)

        return child, outcome_state

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
        Includes: tempo value, combo detection, hold value for early turns.
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
                card_score = getattr(card, 'score', 0) or 0

                # Use card score as base tempo value; fallback to stat/cost ratio
                if card_score > 0:
                    score += card_score * 0.2
                else:
                    atk = getattr(card, 'attack', 0) or 0
                    hp = getattr(card, 'health', 0) or 0
                    score += (atk + hp - cost) * 0.3

                # --- Combo detection for 0-cost spells ---
                # When a 0-cost card is played, boost score of highest-cost
                # spell in hand that becomes affordable (combo potential).
                if cost == 0 and len(state.hand) > 1:
                    from analysis.data.card_effects import get_effects
                    max_boost = 0.0
                    for other in state.hand:
                        if other is card:
                            continue
                        other_cost = getattr(other, 'cost', 0) or 0
                        other_type = (getattr(other, 'card_type', '') or '').upper()
                        if other_type == 'SPELL' and other_cost >= 3:
                            other_eff = get_effects(other)
                            if other_eff.damage > 0 or other_eff.draw > 0:
                                # High-value spell enabled by 0-cost prep
                                max_boost = max(max_boost, other_cost * 0.15)
                    score += max_boost

                # --- Hold value for low-impact early plays ---
                # On T1-T2, penalise low-value plays when opponent has no board.
                # Value: (atk + hp) / cost < 1.5 → not worth playing early.
                mana = getattr(state.mana, 'available', 0) or 0
                if mana <= 2:
                    opp_board = len(state.opponent.board)
                    if opp_board == 0:
                        atk = getattr(card, 'attack', 0) or 0
                        hp = getattr(card, 'health', 0) or 0
                        value_ratio = (atk + hp) / max(cost, 1)
                        if value_ratio < 1.5:
                            score -= 1.5  # hold for better value later

        elif action.action_type == ActionType.HERO_POWER:
            score += 0.3  # hero power worth considering but lower priority

        elif action.action_type == ActionType.ACTIVATE_LOCATION:
            score += 1.0  # location activations are strong tempo

        elif action.action_type == ActionType.END_TURN:
            # Penalise end turn, but less harshly if mana is nearly spent
            mana = getattr(state.mana, 'available', 0) or 0
            max_mana = getattr(state.mana, 'max_mana', 0) or 1
            unspent_ratio = mana / max(max_mana, 1)
            score -= 3.0 - (1.0 - unspent_ratio) * 2.0  # -3 when all mana unused, -1 when all spent

        return score

    # ── Helpers ────────────────────────────────────────

    def _check_terminal(self, state: 'GameState') -> Optional[float]:
        """Check if state is terminal. Returns reward or None."""
        if state.opponent.hero.hp <= 0:
            return 1.0
        if state.hero.hp <= 0:
            return -1.0
        return None

    def _advance_after_opponent_turn(self, state: 'GameState') -> 'GameState':
        """After opponent END_TURN, advance state to our next turn start."""
        if self.config.max_turns_ahead <= 0:
            return state

        from analysis.search.mcts.turn_advance import advance_full_turn
        return advance_full_turn(state, greedy_opponent=True)

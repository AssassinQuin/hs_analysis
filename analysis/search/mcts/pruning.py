#!/usr/bin/env python3
"""pruning.py — Action pruning for MCTS.

Two-level filtering:
1. Tree phase (lenient): remove obviously self-destructive actions
2. Simulation phase (strict): only keep clearly reasonable actions

Also handles "obliged actions" — unconditionally beneficial actions
that should be forced (free plays, free face attacks).
"""

from __future__ import annotations

import logging
from typing import List, Optional, Set, TYPE_CHECKING

from analysis.search.abilities.actions import Action, ActionType, action_key

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)

# Target constants
TARGET_MY_HERO = -1
TARGET_OPPO_HERO = 0


class ActionPruner:
    """Action pruning for MCTS tree and simulation phases."""

    def __init__(self, enable_tree: bool = True, enable_sim: bool = True):
        self.enable_tree = enable_tree
        self.enable_sim = enable_sim

    def filter(self, actions: List[Action], state: 'GameState') -> List[Action]:
        """Filter actions for the tree phase (lenient)."""
        if not self.enable_tree:
            return list(actions)

        filtered = []
        for action in actions:
            if not self._should_prune_tree(action, state):
                filtered.append(action)
        return filtered

    def filter_simulate(self, actions: List[Action], state: 'GameState') -> List[Action]:
        """Filter actions for the simulation phase (strict)."""
        if not self.enable_sim:
            return list(actions)

        filtered = []
        for action in actions:
            if not self._should_prune_simulate(action, state):
                filtered.append(action)
        return filtered

    def get_obliged_actions(
        self,
        actions: List[Action],
        state: 'GameState',
    ) -> List[Action]:
        """Return obliged actions (unconditionally beneficial).

        If any exist, END_TURN should be removed from legal actions
        to force the obliged action.
        """
        obliged = []
        for action in actions:
            # Free face attack with no taunt blocking
            if action.action_type == ActionType.ATTACK:
                if action.target_index == TARGET_OPPO_HERO:
                    if self._no_taunt_blocking(state):
                        src_idx = action.source_index
                        if 0 <= src_idx < len(state.board):
                            if state.board[src_idx].attack > 0:
                                obliged.append(action)

            # Zero-cost card play that doesn't harm us
            elif action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
                card_idx = action.card_index
                if 0 <= card_idx < len(state.hand):
                    card = state.hand[card_idx]
                    cost = getattr(card, 'cost', 1) or 1
                    if cost <= 0 and not self._is_self_harm(action, state):
                        obliged.append(action)

        return obliged

    def _should_prune_tree(self, action: Action, state: 'GameState') -> bool:
        """Tree-phase pruning: remove obviously bad actions."""
        if action.action_type == ActionType.ATTACK:
            return self._prune_attack(action, state)

        if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            return self._prune_play(action, state)

        return False

    def _should_prune_simulate(self, action: Action, state: 'GameState') -> bool:
        """Simulation-phase pruning: stricter than tree phase."""
        if self._should_prune_tree(action, state):
            return True

        # Additional sim-phase pruning
        if action.action_type == ActionType.ATTACK:
            src_idx = action.source_index
            if src_idx >= 0 and src_idx < len(state.board):
                source = state.board[src_idx]
                target_idx = action.target_index
                # Don't attack enemy minions with much higher attack (bad trade)
                if target_idx > 0:
                    enemy_idx = target_idx - 1
                    if enemy_idx < len(state.opponent.board):
                        target = state.opponent.board[enemy_idx]
                        if target.attack > source.health + source.attack:
                            return True

        return False

    def _prune_attack(self, action: Action, state: 'GameState') -> bool:
        """Prune obviously bad attacks."""
        src_idx = action.source_index

        # Hero weapon attack — keep
        if src_idx == -1:
            return False

        if src_idx < 0 or src_idx >= len(state.board):
            return True

        source = state.board[src_idx]

        # Zero-attack minions shouldn't attack
        if source.attack <= 0:
            return True

        return False

    def _prune_play(self, action: Action, state: 'GameState') -> bool:
        """Prune obviously bad card plays."""
        card_idx = action.card_index
        if card_idx < 0 or card_idx >= len(state.hand):
            return True

        card = state.hand[card_idx]
        card_text = (getattr(card, 'text', '') or '').lower()
        card_name = getattr(card, 'name', '') or ''

        # Self-damage spell targeting own hero
        if action.action_type == ActionType.PLAY_WITH_TARGET:
            if action.target_index == TARGET_MY_HERO:
                # Damage spell to own hero
                if any(kw in card_text for kw in ('造成', '伤害', 'damage')):
                    return True

            # Heal full-health target
            target = self._resolve_target(action, state)
            if target is not None:
                if any(kw in card_text for kw in ('恢复', '治疗', 'heal', 'restore')):
                    target_health = getattr(target, 'health', 0)
                    target_max = getattr(target, 'max_health', target_health)
                    if target_health >= target_max:
                        return True

        return False

    def _resolve_target(self, action: Action, state: 'GameState'):
        """Resolve the target entity of an action."""
        tgt = action.target_index
        if tgt < 0:
            return None
        if tgt == 0:
            return state.opponent.hero
        elif tgt <= len(state.opponent.board):
            return state.opponent.board[tgt - 1]
        elif tgt <= len(state.opponent.board) + len(state.board):
            idx = tgt - len(state.opponent.board) - 1
            if idx < len(state.board):
                return state.board[idx]
        return None

    def _no_taunt_blocking(self, state: 'GameState') -> bool:
        """Check if no enemy taunt minions are blocking face attacks."""
        return not any(
            getattr(m, 'has_taunt', False)
            for m in state.opponent.board
        )

    def _is_self_harm(self, action: Action, state: 'GameState') -> bool:
        """Quick check if a card play harms us."""
        card_idx = action.card_index
        if 0 <= card_idx < len(state.hand):
            card = state.hand[card_idx]
            text = (getattr(card, 'text', '') or '').lower()
            if any(kw in text for kw in ('对友方', '对所有友方', 'destroy your own')):
                return True
        return False

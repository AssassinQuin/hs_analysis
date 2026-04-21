"""ActionPruner — domain-knowledge pruning to reduce search space."""

from __future__ import annotations

from typing import List

from hs_analysis.search.game_state import GameState, Minion
from hs_analysis.search.rhea_engine import Action


class ActionPruner:

    def prune(self, actions: List[Action], state: GameState) -> List[Action]:
        pruned = [a for a in actions if not self._is_dominated(a, state)]
        if not any(a.action_type == "END_TURN" for a in pruned):
            end_turns = [a for a in actions if a.action_type == "END_TURN"]
            pruned.extend(end_turns)
        return pruned

    def _is_dominated(self, action: Action, state: GameState) -> bool:
        if action.action_type == "ATTACK":
            return self._attack_dominated(action, state)
        if action.action_type == "PLAY":
            return self._play_dominated(action, state)
        return False

    def _attack_dominated(self, action: Action, state: GameState) -> bool:
        if action.source_index == -1:
            return False
        if action.source_index < 0 or action.source_index >= len(state.board):
            return True

        attacker = state.board[action.source_index]

        if action.target_index == 0:
            return self._face_attack_dominated(attacker, state)

        enemy_idx = action.target_index - 1
        if enemy_idx < 0 or enemy_idx >= len(state.opponent.board):
            return True
        target = state.opponent.board[enemy_idx]

        if attacker.attack == 1 and target.has_divine_shield:
            return True

        if (target.health > attacker.attack and
                attacker.health <= target.attack and
                not attacker.has_divine_shield and
                not attacker.has_poisonous):
            value_ratio = attacker.cost / max(target.cost, 1)
            if value_ratio > 1.2:
                return True

        return False

    def _face_attack_dominated(self, attacker: Minion,
                               state: GameState) -> bool:
        enemy_taunts = [m for m in state.opponent.board if m.has_taunt]
        if enemy_taunts:
            return True
        return False

    def _play_dominated(self, action: Action, state: GameState) -> bool:
        if action.card_index < 0 or action.card_index >= len(state.hand):
            return True

        card = state.hand[action.card_index]
        card_type = (card.card_type or "").upper()

        if card_type == "MINION":
            if state.board_full():
                return True

        if card_type == "MINION" and action.position >= 0:
            if len(state.board) <= 1 and action.position > 0:
                pass

        return False

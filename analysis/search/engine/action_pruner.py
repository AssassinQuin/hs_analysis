from __future__ import annotations

from typing import List, Set, Tuple

from analysis.search.game_state import GameState, Minion
from analysis.search.rhea_engine import Action


class ActionPruner:

    def prune(self, actions: List[Action], state: GameState) -> List[Action]:
        pruned = [a for a in actions if not self._is_dominated(a, state)]
        if not any(a.action_type == "END_TURN" for a in pruned):
            end_turns = [a for a in actions if a.action_type == "END_TURN"]
            pruned.extend(end_turns)
        return pruned

    def prune_sequence(self, actions: List[Action], state: GameState) -> List[Action]:
        pruned: List[Action] = []
        used_cards: Set[int] = set()
        used_attackers: Set[Tuple[int, int]] = set()

        for action in actions:
            if self._is_dominated(action, state):
                continue
            if self._is_redundant_in_sequence(action, used_cards, used_attackers):
                continue
            pruned.append(action)
            if action.action_type in ("PLAY", "PLAY_WITH_TARGET", "HERO_REPLACE"):
                used_cards.add(action.card_index)
            if action.action_type == "ATTACK":
                key = (action.source_index, action.target_index)
                used_attackers.add(key)

        if not pruned or pruned[-1].action_type != "END_TURN":
            pruned.append(Action(action_type="END_TURN"))
        return pruned

    def _is_dominated(self, action: Action, state: GameState) -> bool:
        if action.action_type == "ATTACK":
            return self._attack_dominated(action, state)
        if action.action_type in ("PLAY", "PLAY_WITH_TARGET"):
            return self._play_dominated(action, state)
        if action.action_type == "HERO_REPLACE":
            return self._hero_replace_dominated(action, state)
        if action.action_type == "TRANSFORM":
            return self._transform_dominated(action, state)
        return False

    def _is_redundant_in_sequence(
        self,
        action: Action,
        used_cards: Set[int],
        used_attackers: Set[Tuple[int, int]],
    ) -> bool:
        if action.action_type in ("PLAY", "PLAY_WITH_TARGET", "HERO_REPLACE"):
            return action.card_index in used_cards
        if action.action_type == "ATTACK":
            return (action.source_index, action.target_index) in used_attackers
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

        if action.action_type == "PLAY_WITH_TARGET":
            if action.target_index > 0:
                enemy_idx = action.target_index - 1
                if enemy_idx >= len(state.opponent.board):
                    return True
                target = state.opponent.board[enemy_idx]
                text = getattr(card, 'text', '') or ''
                if '敌方随从' in text or 'enemy minion' in text.lower():
                    if target.attack <= 1 and target.health <= 1:
                        pass

        return False

    def _hero_replace_dominated(self, action: Action, state: GameState) -> bool:
        if action.card_index < 0 or action.card_index >= len(state.hand):
            return True
        card = state.hand[action.card_index]
        if (card.card_type or "").upper() != "HERO":
            return True
        return False

    def _transform_dominated(self, action: Action, state: GameState) -> bool:
        if action.target_index <= 0:
            return True
        enemy_idx = action.target_index - 1
        if enemy_idx >= len(state.opponent.board):
            return True
        target = state.opponent.board[enemy_idx]
        if target.attack <= 1 and target.health <= 1:
            return True
        return False

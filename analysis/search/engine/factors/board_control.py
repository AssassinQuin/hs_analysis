from __future__ import annotations

from analysis.search.game_state import GameState, Minion
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class BoardControlFactor(EvaluationFactor):
    def name(self) -> str:
        return "board_control"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_after = self._board_value(state_after.board)
        enemy_after = self._board_value(state_after.opponent.board)
        friend_before = self._board_value(state_before.board)
        enemy_before = self._board_value(state_before.opponent.board)

        delta_friend = friend_after - friend_before
        delta_enemy = enemy_after - enemy_before

        raw = delta_friend - delta_enemy
        scale = max(friend_before + enemy_before, 1)
        return max(-1.0, min(1.0, raw / scale))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 1.3
        if context.phase == Phase.LATE:
            return 0.9
        return 1.1

    def _board_value(self, board: list) -> float:
        total = 0.0
        for m in board:
            base = m.attack + m.health
            kw_bonus = self._keyword_synergy_value(m)
            threat_bonus = self._threat_value(m)
            total += base * kw_bonus + threat_bonus
        return total

    def _keyword_synergy_value(self, m: Minion) -> float:
        multiplier = 1.0

        if m.has_taunt:
            multiplier += 0.15
            if m.health >= 5:
                multiplier += 0.2

        if m.has_divine_shield:
            multiplier += 0.3
            if m.attack >= 3:
                multiplier += 0.4

        if m.has_windfury and m.attack >= 2:
            multiplier += 0.35

        if m.has_poisonous:
            multiplier += 0.25
            if m.attack >= 1:
                multiplier += 0.1

        if m.has_stealth:
            if m.attack >= 3:
                multiplier += 0.2

        if m.has_rush:
            multiplier += 0.1

        if m.has_charge:
            multiplier += 0.15

        if m.has_reborn:
            if m.attack + m.health >= 4:
                multiplier += 0.2

        if getattr(m, 'has_ward', False):
            multiplier += 0.2

        # Keyword combos: synergistic pairs worth more than sum
        if m.has_taunt and m.has_divine_shield:
            multiplier += 0.35
        if m.has_taunt and m.has_reborn:
            multiplier += 0.25
        if m.has_poisonous and m.has_stealth:
            multiplier += 0.4
        if m.has_windfury and m.has_divine_shield:
            multiplier += 0.3
        if m.has_charge and m.has_windfury:
            multiplier += 0.25
        if m.has_rush and m.has_divine_shield:
            multiplier += 0.2
        if m.has_poisonous and m.has_rush:
            multiplier += 0.3

        return multiplier

    def _threat_value(self, m: Minion) -> float:
        threat = 0.0
        if m.attack >= 5:
            threat += m.attack * 0.3
        if m.has_windfury and m.attack >= 3:
            threat += m.attack * 0.5
        if m.has_charge and m.attack >= 3:
            threat += m.attack * 0.4
        return threat

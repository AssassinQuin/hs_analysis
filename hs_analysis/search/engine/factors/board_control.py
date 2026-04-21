"""BoardControlFactor — who controls the board."""

from __future__ import annotations

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action
from hs_analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class BoardControlFactor(EvaluationFactor):
    def name(self) -> str:
        return "board_control"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_after = sum(m.attack + m.health for m in state_after.board)
        enemy_after = sum(m.attack + m.health for m in state_after.opponent.board)
        friend_before = sum(m.attack + m.health for m in state_before.board)
        enemy_before = sum(m.attack + m.health for m in state_before.opponent.board)

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

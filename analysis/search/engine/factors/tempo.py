"""TempoFactor — mana efficiency and board development."""

from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.search.rhea import Action
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class TempoFactor(EvaluationFactor):
    def name(self) -> str:
        return "tempo"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        friend_cost_after = sum(m.cost for m in state_after.board)
        enemy_cost_after = sum(m.cost for m in state_after.opponent.board)
        friend_cost_before = sum(m.cost for m in state_before.board)
        enemy_cost_before = sum(m.cost for m in state_before.opponent.board)

        board_delta = (friend_cost_after - enemy_cost_after) - \
                      (friend_cost_before - enemy_cost_before)

        max_mana = max(state_before.mana.max_mana, 1)
        mana_spent = state_before.mana.available - state_after.mana.available
        mana_eff = mana_spent / max_mana

        raw = board_delta * 0.3 + mana_eff * 0.7
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 1.5
        if context.phase == Phase.LATE:
            return 0.7
        return 1.0

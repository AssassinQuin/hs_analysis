"""ResourceEfficiencyFactor — mana utilization."""

from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.search.rhea import Action
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor, Phase,
)


class ResourceEfficiencyFactor(EvaluationFactor):
    def name(self) -> str:
        return "resource_efficiency"

    def compute(self, state_before: GameState, state_after: GameState,
                action, context: EvalContext) -> float:
        max_mana = max(state_before.mana.max_mana, 1)
        available_before = state_before.mana.available
        available_after = state_after.mana.available
        spent = available_before - available_after

        efficiency = spent / max_mana

        overloaded = state_after.mana.overloaded
        overload_penalty = overloaded / max_mana * 0.5 if max_mana > 0 else 0

        raw = efficiency - overload_penalty
        return max(-1.0, min(1.0, raw))

    def weight(self, context: EvalContext) -> float:
        if context.phase == Phase.EARLY:
            return 0.8
        return 0.5

"""FactorGraphEvaluator — decomposable multi-factor evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analysis.search.game_state import GameState
from analysis.search.rhea_engine import Action
from analysis.search.engine.factors.factor_base import (
    EvalContext, EvaluationFactor,
)


@dataclass
class FactorScores:
    board_control: float = 0.0
    lethal_threat: float = 0.0
    tempo: float = 0.0
    value: float = 0.0
    survival: float = 0.0
    resource_efficiency: float = 0.0
    discover_ev: float = 0.0
    total: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "board_control": self.board_control,
            "lethal_threat": self.lethal_threat,
            "tempo": self.tempo,
            "value": self.value,
            "survival": self.survival,
            "resource_efficiency": self.resource_efficiency,
            "discover_ev": self.discover_ev,
            "total": self.total,
        }

    def describe(self) -> str:
        parts = []
        for k, v in self.as_dict().items():
            if k != "total" and abs(v) > 0.01:
                parts.append(f"{k}={v:+.2f}")
        return ", ".join(parts) if parts else "neutral"


class FactorGraphEvaluator:
    def __init__(self) -> None:
        self._factors: List[EvaluationFactor] = []

    def register(self, factor: EvaluationFactor) -> None:
        self._factors.append(factor)

    def evaluate(self, state_before: GameState, state_after: GameState,
                 action: Optional[Action] = None,
                 context: Optional[EvalContext] = None) -> FactorScores:
        if context is None:
            context = EvalContext.from_state(state_after)

        scores: Dict[str, float] = {}
        for f in self._factors:
            try:
                scores[f.name()] = f.compute(state_before, state_after, action, context)
            except Exception:
                scores[f.name()] = 0.0

        total = 0.0
        for f in self._factors:
            w = f.weight(context)
            total += scores.get(f.name(), 0.0) * w

        return FactorScores(
            board_control=scores.get("board_control", 0.0),
            lethal_threat=scores.get("lethal_threat", 0.0),
            tempo=scores.get("tempo", 0.0),
            value=scores.get("value", 0.0),
            survival=scores.get("survival", 0.0),
            resource_efficiency=scores.get("resource_efficiency", 0.0),
            discover_ev=scores.get("discover_ev", 0.0),
            total=total,
        )

    def quick_eval(self, state: GameState,
                   context: Optional[EvalContext] = None) -> float:
        scores = self.evaluate(state, state, context=context)
        return scores.total

    def factor_names(self) -> List[str]:
        return [f.name() for f in self._factors]

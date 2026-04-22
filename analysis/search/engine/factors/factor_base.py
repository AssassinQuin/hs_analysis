"""EvaluationFactor ABC — interface for evaluation factors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from analysis.search.game_state import GameState
from analysis.search.rhea_engine import Action
from analysis.models.phase import Phase, detect_phase


@dataclass
class EvalContext:
    phase: Phase = Phase.MID
    turn_number: int = 5
    is_lethal: bool = False
    time_budget_ms: float = 100.0

    @staticmethod
    def from_state(state: GameState) -> EvalContext:
        tn = state.turn_number
        return EvalContext(phase=detect_phase(tn), turn_number=tn)


class EvaluationFactor(ABC):

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, state_before: GameState, state_after: GameState,
                action: Optional[Action], context: EvalContext) -> float:
        ...

    def weight(self, context: EvalContext) -> float:
        return 1.0

"""DecisionPipeline — main entry point.

Orchestrates: Strategy → Prune → Tactical Plan → Factor Eval → Decision
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action, enumerate_legal_actions
from hs_analysis.search.engine.strategic import strategic_decision, StrategicMode
from hs_analysis.search.engine.tactical import TacticalPlanner, TacticalCandidate
from hs_analysis.search.engine.action_pruner import ActionPruner
from hs_analysis.search.engine.attack_planner import AttackPlanner, AttackPlan
from hs_analysis.search.engine.factors.factor_graph import (
    FactorGraphEvaluator, FactorScores,
)
from hs_analysis.search.engine.factors.factor_base import EvalContext
from hs_analysis.search.engine.factors.board_control import BoardControlFactor
from hs_analysis.search.engine.factors.lethal_threat import LethalThreatFactor
from hs_analysis.search.engine.factors.tempo import TempoFactor
from hs_analysis.search.engine.factors.value import ValueFactor
from hs_analysis.search.engine.factors.survival import SurvivalFactor
from hs_analysis.search.engine.factors.resource_efficiency import ResourceEfficiencyFactor
from hs_analysis.search.engine.factors.discover_ev import DiscoverEVFactor


@dataclass
class Decision:
    best_plan: List[Action]
    best_score: float
    factor_scores: FactorScores
    strategic_mode: StrategicMode
    alternatives: List[TacticalCandidate]
    confidence: float
    reasoning: str
    time_elapsed_ms: float = 0.0

    def describe(self, state: Optional[GameState] = None) -> str:
        lines = [f"模式: {self.strategic_mode.mode} — {self.strategic_mode.reason}"]
        lines.append(f"置信度: {self.confidence:.2f}")
        lines.append(f"因子评分: {self.factor_scores.describe()}")
        lines.append("行动序列:")
        for i, action in enumerate(self.best_plan):
            lines.append(f"  {i + 1}. {action.describe(state)}")
        return "\n".join(lines)


def _build_default_evaluator() -> FactorGraphEvaluator:
    evaluator = FactorGraphEvaluator()
    evaluator.register(BoardControlFactor())
    evaluator.register(LethalThreatFactor())
    evaluator.register(TempoFactor())
    evaluator.register(ValueFactor())
    evaluator.register(SurvivalFactor())
    evaluator.register(ResourceEfficiencyFactor())
    evaluator.register(DiscoverEVFactor())
    return evaluator


class DecisionPipeline:
    def __init__(self, evaluator: Optional[FactorGraphEvaluator] = None,
                 time_budget_ms: float = 100.0) -> None:
        self._evaluator = evaluator or _build_default_evaluator()
        self._pruner = ActionPruner()
        self._time_budget_ms = time_budget_ms

    def decide(self, state: GameState) -> Decision:
        t0 = time.perf_counter()

        mode = strategic_decision(state)

        if mode.mode == "LETHAL":
            decision = self._lethal_search(state, mode, t0)
            if decision is not None:
                decision.time_elapsed_ms = (time.perf_counter() - t0) * 1000
                return decision

        candidates = self._development_search(state, mode, t0)

        if not candidates:
            plan = [Action(action_type="END_TURN")]
            decision = Decision(
                best_plan=plan,
                best_score=0.0,
                factor_scores=FactorScores(),
                strategic_mode=mode,
                alternatives=[],
                confidence=0.0,
                reasoning="无可用行动",
            )
            decision.time_elapsed_ms = (time.perf_counter() - t0) * 1000
            return decision

        best = candidates[0]
        best_plan = list(best.play_actions) + list(best.attack_plan.attacks)
        best_plan.append(Action(action_type="END_TURN"))

        second_score = candidates[1].combined_score if len(candidates) > 1 else 0.0
        gap = best.combined_score - second_score
        confidence = min(1.0, gap / max(abs(best.combined_score), 0.01))

        reasoning = f"{mode.reason} | "
        reasoning += f"总分={best.combined_score:.2f} ({best.factor_scores.describe()})"

        decision = Decision(
            best_plan=best_plan,
            best_score=best.combined_score,
            factor_scores=best.factor_scores,
            strategic_mode=mode,
            alternatives=candidates[1:4],
            confidence=confidence,
            reasoning=reasoning,
        )
        decision.time_elapsed_ms = (time.perf_counter() - t0) * 1000
        return decision

    def _lethal_search(self, state: GameState, mode: StrategicMode,
                       t0: float) -> Optional[Decision]:
        try:
            from hs_analysis.search.lethal_checker import check_lethal
            result = check_lethal(state, time_budget_ms=self._time_budget_ms * 0.3)
            if result is not None:
                return Decision(
                    best_plan=result + [Action(action_type="END_TURN")],
                    best_score=10000.0,
                    factor_scores=FactorScores(total=10000.0),
                    strategic_mode=mode,
                    alternatives=[],
                    confidence=1.0,
                    reasoning="致命! 找到击杀序列",
                )
        except Exception:
            pass
        return None

    def _development_search(self, state: GameState, mode: StrategicMode,
                            t0: float) -> List[TacticalCandidate]:
        planner = TacticalPlanner(
            evaluator=self._evaluator,
            max_combo_depth=self._combo_depth_for_phase(state.turn_number),
        )
        return planner.plan(state, mode.mode)

    @staticmethod
    def _combo_depth_for_phase(turn_number: int) -> int:
        if turn_number <= 4:
            return 2
        if turn_number <= 7:
            return 3
        return 4

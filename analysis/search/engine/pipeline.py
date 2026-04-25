"""DecisionPipeline — main entry point.

Orchestrates: Strategy → Prune → Tactical Plan → Factor Eval → Decision
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

from analysis.search.game_state import GameState
from analysis.search.rhea import Action, ActionType, enumerate_legal_actions
from analysis.search.engine.strategic import strategic_decision, StrategicMode
from analysis.search.engine.tactical import TacticalPlanner, TacticalCandidate
from analysis.search.engine.action_pruner import ActionPruner
from analysis.search.engine.attack_planner import AttackPlanner, AttackPlan
from analysis.search.engine.factors.factor_graph import (
    FactorGraphEvaluator, FactorScores,
)
from analysis.search.engine.factors.factor_base import EvalContext
from analysis.search.engine.factors.board_control import BoardControlFactor
from analysis.search.engine.factors.lethal_threat import LethalThreatFactor
from analysis.search.engine.factors.tempo import TempoFactor
from analysis.search.engine.factors.value import ValueFactor
from analysis.search.engine.factors.survival import SurvivalFactor
from analysis.search.engine.factors.resource_efficiency import ResourceEfficiencyFactor
from analysis.search.engine.factors.discover_ev import DiscoverEVFactor
from analysis.search.engine.models.probability_panel import (
    ProbabilityPanel,
    compute_panel,
)
from analysis.search.engine.turn_plan import TurnPlan, NextTurnOuts


@dataclass
class Decision:
    best_plan: List[Action]
    best_score: float
    factor_scores: FactorScores
    strategic_mode: StrategicMode
    alternatives: List[TacticalCandidate]
    confidence: float
    reasoning: str
    probability_panel: Optional[ProbabilityPanel] = None
    turn_plan: Optional[TurnPlan] = None
    time_elapsed_ms: float = 0.0

    def describe(self, state: Optional[GameState] = None) -> str:
        lines = [f"模式: {self.strategic_mode.mode} — {self.strategic_mode.reason}"]
        lines.append(f"置信度: {self.confidence:.2f}")
        lines.append(f"因子评分: {self.factor_scores.describe()}")
        if self.probability_panel is not None:
            lines.append("抉择期望(命中率>=5%):")
            panel_lines = self.probability_panel.format_category_lines(min_prob=0.05)
            if panel_lines:
                for line in panel_lines:
                    lines.append(f"  {line}")
            else:
                lines.append("  (无显著分类概率)")
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
                self._attach_turn_plan(decision, state)
                return decision

        candidates = self._development_search(state, mode, t0)

        if not candidates:
            plan = [Action(action_type=ActionType.END_TURN)]
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
            self._attach_turn_plan(decision, state)
            return decision

        best = candidates[0]
        best_plan = list(best.play_actions) + list(best.attack_plan.attacks)
        best_plan.append(Action(action_type=ActionType.END_TURN))

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
        self._attach_turn_plan(decision, state)
        decision.time_elapsed_ms = (time.perf_counter() - t0) * 1000
        return decision

    def _lethal_search(self, state: GameState, mode: StrategicMode,
                       t0: float) -> Optional[Decision]:
        try:
            from analysis.search.lethal_checker import check_lethal
            result = check_lethal(state, time_budget_ms=self._time_budget_ms * 0.3)
            if result is not None:
                return Decision(
                    best_plan=result + [Action(action_type=ActionType.END_TURN)],
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

    def _attach_turn_plan(self, decision: Decision, state: GameState) -> None:
        panel = compute_panel(state)
        outs = NextTurnOuts(
            clear_prob=panel.draw_clear_1,
            heal_prob=panel.draw_heal_1,
            board_prob=panel.draw_board_1,
            burst_prob=panel.draw_burst_1,
        )
        backup_lines = []
        for alt in decision.alternatives[:3]:
            seq = list(alt.play_actions) + list(alt.attack_plan.attacks)
            if not seq or seq[-1].action_type != ActionType.END_TURN:
                seq.append(Action(action_type=ActionType.END_TURN))
            backup_lines.append(seq)

        decision.probability_panel = panel
        decision.turn_plan = TurnPlan(
            objective=decision.strategic_mode.mode,
            primary_line=list(decision.best_plan),
            backup_lines=backup_lines,
            reserve_resources=[],
            next_turn_outs=outs,
            probability_panel=panel,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
        )

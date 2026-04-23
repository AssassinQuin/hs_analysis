from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analysis.search.game_state import GameState
from analysis.search.rhea_engine import Action, apply_action, enumerate_legal_actions
from analysis.search.engine.factors.factor_graph import (
    FactorGraphEvaluator, FactorScores,
)
from analysis.search.engine.factors.factor_base import EvalContext


@dataclass
class UnifiedPlan:
    actions: List[Action]
    state_after: GameState
    score: float


class UnifiedTacticalPlanner:

    def __init__(
        self,
        evaluator: FactorGraphEvaluator,
        beam_width: int = 5,
        max_steps: int = 10,
        time_budget_ms: float = 100.0,
    ) -> None:
        self._evaluator = evaluator
        self._beam_width = beam_width
        self._max_steps = max_steps
        self._time_budget_ms = time_budget_ms

    def plan(self, state: GameState) -> List[UnifiedPlan]:
        t0 = time.perf_counter()
        deadline = t0 + self._time_budget_ms / 1000.0

        ctx = EvalContext.from_state(state)
        initial_score = self._evaluator.evaluate(state, state, context=ctx).total

        beam: List[UnifiedPlan] = [
            UnifiedPlan(actions=[], state_after=state.copy(), score=0.0),
        ]
        best_plans: List[UnifiedPlan] = []

        for step in range(self._max_steps):
            if time.perf_counter() > deadline:
                break

            expanded: List[UnifiedPlan] = []
            for plan in beam:
                if plan.state_after.is_lethal():
                    best_plans.append(plan)
                    continue

                legal = enumerate_legal_actions(plan.state_after)
                non_end = [a for a in legal if a.action_type != "END_TURN"]

                if not non_end:
                    best_plans.append(plan)
                    continue

                for action in non_end:
                    if time.perf_counter() > deadline:
                        break
                    new_state = apply_action(plan.state_after.copy(), action)
                    step_score = self._evaluator.evaluate(
                        state, new_state, context=ctx,
                    ).total - initial_score

                    if new_state.is_lethal():
                        step_score += 1000.0

                    expanded.append(UnifiedPlan(
                        actions=plan.actions + [action],
                        state_after=new_state,
                        score=step_score,
                    ))

            if not expanded:
                break

            expanded.sort(key=lambda p: -p.score)
            seen_keys: set = set()
            deduped: List[UnifiedPlan] = []
            for p in expanded:
                key = tuple((a.action_type, a.card_index, a.target_index) for a in p.actions)
                if key not in seen_keys:
                    seen_keys.add(key)
                    deduped.append(p)
                if len(deduped) >= self._beam_width * 3:
                    break

            beam = deduped[:self._beam_width]

            if all(p.state_after.is_lethal() for p in beam):
                best_plans.extend(beam)
                break

        all_plans = best_plans + beam
        for p in all_plans:
            if p.actions and p.actions[-1].action_type != "END_TURN":
                end_state = apply_action(p.state_after.copy(), Action(action_type="END_TURN"))
                end_score = self._evaluator.evaluate(
                    state, end_state, context=ctx,
                ).total - initial_score
                if end_state.is_lethal():
                    end_score += 1000.0
                p.actions.append(Action(action_type="END_TURN"))
                p.state_after = end_state
                p.score = end_score

        all_plans.sort(key=lambda p: -p.score)
        return all_plans[:self._beam_width]

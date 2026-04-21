"""Tactical layer — enumerates card combinations and evaluates them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from hs_analysis.search.game_state import GameState
from hs_analysis.search.rhea_engine import Action, apply_action
from hs_analysis.search.engine.factors.factor_graph import (
    FactorGraphEvaluator, FactorScores,
)
from hs_analysis.search.engine.factors.factor_base import EvalContext
from hs_analysis.search.engine.attack_planner import AttackPlanner, AttackPlan


@dataclass
class TacticalCandidate:
    play_actions: List[Action]
    attack_plan: AttackPlan
    factor_scores: FactorScores
    state_after: GameState
    combined_score: float = 0.0


class TacticalPlanner:

    def __init__(self, evaluator: FactorGraphEvaluator,
                 max_combo_depth: int = 3) -> None:
        self._evaluator = evaluator
        self._max_combo_depth = max_combo_depth

    def plan(self, state: GameState, mode: str = "DEVELOPMENT") -> List[TacticalCandidate]:
        combos = self._enumerate_card_combos(state)
        candidates: List[TacticalCandidate] = []

        for combo in combos:
            current = state.copy()
            play_actions: List[Action] = []
            valid = True

            for card_idx, pos in combo:
                if card_idx >= len(current.hand):
                    valid = False
                    break
                card = current.hand[card_idx]
                if card.cost > current.mana.available:
                    valid = False
                    break

                action = Action(
                    action_type="PLAY",
                    card_index=card_idx,
                    position=pos,
                )
                play_actions.append(action)
                current = apply_action(current, action)

                if current.is_lethal():
                    break

            if not valid:
                continue

            attack_planner = AttackPlanner(evaluator=self._evaluator)
            attack_plan = attack_planner.plan(current)

            for atk in attack_plan.attacks:
                current = apply_action(current, atk)

            end_action = Action(action_type="END_TURN")
            current = apply_action(current, end_action)

            ctx = EvalContext.from_state(state)
            scores = self._evaluator.evaluate(state, current, context=ctx)

            lethal_bonus = 1000.0 if current.is_lethal() else 0.0
            combined = scores.total + lethal_bonus

            candidates.append(TacticalCandidate(
                play_actions=play_actions,
                attack_plan=attack_plan,
                factor_scores=scores,
                state_after=current,
                combined_score=combined,
            ))

        if not candidates:
            attack_planner = AttackPlanner(evaluator=self._evaluator)
            attack_plan = attack_planner.plan(state.copy())
            current = state.copy()
            for atk in attack_plan.attacks:
                current = apply_action(current, atk)
            current = apply_action(current, Action(action_type="END_TURN"))

            ctx = EvalContext.from_state(state)
            scores = self._evaluator.evaluate(state, current, context=ctx)
            lethal_bonus = 1000.0 if current.is_lethal() else 0.0

            candidates.append(TacticalCandidate(
                play_actions=[],
                attack_plan=attack_plan,
                factor_scores=scores,
                state_after=current,
                combined_score=scores.total + lethal_bonus,
            ))

        candidates.sort(key=lambda c: -c.combined_score)
        return candidates

    def _enumerate_card_combos(self, state: GameState) -> List[List[Tuple[int, int]]]:
        combos: List[List[Tuple[int, int]]] = []
        affordable = []
        for idx, card in enumerate(state.hand):
            if card.cost <= state.mana.available:
                affordable.append((idx, card))

        queue: List[Tuple[List[Tuple[int, int]], int, int]] = [([], 0, 0)]

        while queue:
            current_combo, total_cost, depth = queue.pop(0)
            if depth > 0:
                combos.append(current_combo)
            if depth >= self._max_combo_depth:
                continue

            last_idx = current_combo[-1][0] if current_combo else -1
            for card_idx, card in affordable:
                if card_idx <= last_idx:
                    continue
                new_cost = total_cost + card.cost
                if new_cost > state.mana.available:
                    continue

                if (card.card_type or "").upper() == "MINION":
                    if len(state.board) + len([c for c in current_combo
                                               if (state.hand[c[0]].card_type or "").upper() == "MINION"]) >= 7:
                        continue
                    for pos in range(min(len(state.board) + depth, 7) + 1):
                        queue.append(
                            (current_combo + [(card_idx, pos)], new_cost, depth + 1)
                        )
                else:
                    queue.append(
                        (current_combo + [(card_idx, -1)], new_cost, depth + 1)
                    )

        return combos

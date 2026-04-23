#!/usr/bin/env python3
"""engine.py — RHEAEngine evolutionary search class.

Rolling Horizon Evolutionary Algorithm for Hearthstone turn planning.
Uses adaptive time budgets, layered decision pipeline, and cross-turn evaluation.
"""

from __future__ import annotations

import copy
import logging
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analysis.search.rhea.actions import Action, action_key, action_in_list
from analysis.search.rhea.enumeration import enumerate_legal_actions
from analysis.search.rhea.simulation import (
    apply_action,
    next_turn_lethal_check,
)
from analysis.search.rhea.result import SearchResult

from analysis.search.game_state import GameState
from analysis.models.phase import detect_phase
from analysis.evaluators.composite import evaluate, evaluate_delta, quick_eval
from analysis.utils.score_provider import load_scores_into_hand

log = logging.getLogger(__name__)

# Optional imports with graceful degradation
try:
    from analysis.search.lethal_checker import check_lethal
except ImportError:
    check_lethal = None

try:
    from analysis.search.risk_assessor import RiskAssessor, RiskReport
except ImportError:
    RiskAssessor = None
    RiskReport = None

try:
    from analysis.search.opponent_simulator import OpponentSimulator
except ImportError:
    OpponentSimulator = None

try:
    from analysis.search.action_normalize import normalize_chromosome
except ImportError:
    normalize_chromosome = None

try:
    from analysis.evaluators.composite import (
        evaluate_with_risk,
        evaluate_delta_with_risk,
    )
except ImportError:
    evaluate_with_risk = None
    evaluate_delta_with_risk = None


class RHEAEngine:
    """Rolling Horizon Evolutionary Algorithm for Hearthstone turn planning.

    V11: Cross-turn planning with adaptive time budgets (3-5s normal / 5-15s complex).

    Time budget allocation:
        Layer 0  Lethal Check     5ms
        Layer 0.5 UTP (beam)      10%
        Layer 1  RHEA evolution    50%
        Phase B  Multi-turn setup  10%
        Opp Sim  Opponent sim      10%
        Phase C  Cross-turn sim    20%
    """

    COMPLEXITY_NORMAL = 0
    COMPLEXITY_HARD = 1

    def __init__(
        self,
        pop_size: int = 50,
        tournament_size: int = 5,
        crossover_rate: float = 0.8,
        mutation_rate: Optional[float] = None,
        elite_count: int = 2,
        max_gens: int = 200,
        time_limit: float = 75.0,
        max_chromosome_length: int = 6,
        cross_turn: bool = True,
    ):
        self.pop_size = pop_size
        self.tournament_size = tournament_size
        self.crossover_rate = crossover_rate
        self.mutation_rate = (
            mutation_rate if mutation_rate is not None else 1.0 / max_chromosome_length
        )
        self.elite_count = elite_count
        self.max_gens = max_gens
        self.time_limit = time_limit
        self.max_chromosome_length = max_chromosome_length
        self.cross_turn = cross_turn
        self._target_diversity = 0.5
        self._adaptive_mutation_rate = self.mutation_rate
        self._time_limit_explicit = time_limit != 75.0

    # ---------------------------------------------------------------
    # Main search entry point
    # ---------------------------------------------------------------

    def search(
        self,
        initial_state: GameState,
        weights: Optional[dict] = None,
    ) -> SearchResult:
        """Run the RHEA search with layered decision pipeline."""
        t_start = time.perf_counter()
        timings = {}

        budget_ms = self._adaptive_time_limit(initial_state)
        budget_s = budget_ms / 1000.0

        load_scores_into_hand(initial_state)

        # ========== Layer 0: Lethal Check (5ms budget) ==========
        t_lethal_start = time.perf_counter()
        if check_lethal is not None:
            try:
                lethal_result = check_lethal(initial_state, time_budget_ms=5.0)
                if lethal_result is not None:
                    lethal_actions = lethal_result + [Action(action_type="END_TURN")]
                    timings['lethal'] = (time.perf_counter() - t_lethal_start) * 1000.0
                    timings['total'] = (time.perf_counter() - t_start) * 1000.0
                    log.info(
                        "RHEA: Turn %d | LETHAL found | %.1fms",
                        initial_state.turn_number, timings['total'],
                    )
                    return SearchResult(
                        best_chromosome=lethal_actions,
                        best_fitness=10000.0,
                        alternatives=[],
                        generations_run=0,
                        time_elapsed=(time.perf_counter() - t_start) * 1000.0,
                        population_diversity=0.0,
                        confidence=1.0,
                        pareto_front=[],
                    )
            except Exception:
                log.warning("RHEA: lethal check failed", exc_info=True)

        # ========== Phase Detection + Adaptive Params ==========
        phase = self._detect_phase(initial_state)
        phase_params = self._get_phase_params(phase)
        desperate = self._is_desperate(initial_state)
        if desperate:
            phase_params["max_gens"] = max(phase_params["max_gens"], 80)
            phase_params["weights"]["w_threat"] = phase_params["weights"].get("w_threat", 1.0) * 2.0
            log.debug("RHEA: desperate mode detected, increasing gens and threat weight")

        # ========== Layer 0.5: UnifiedTacticalPlanner (10% of budget) ==========
        t_utp_start = time.perf_counter()
        utp_plans = None
        if not desperate:
            try:
                from analysis.search.engine.unified_tactical import (
                    UnifiedTacticalPlanner,
                )
                from analysis.search.engine.factors.factor_graph import (
                    FactorGraphEvaluator,
                )

                fg = FactorGraphEvaluator()
                for _factor_cls_name in (
                    "BoardControlFactor", "LethalThreatFactor",
                    "TempoFactor", "ValueFactor", "SurvivalFactor",
                ):
                    try:
                        mod = __import__(
                            f"analysis.search.engine.factors.{_factor_cls_name.lower()}",
                            fromlist=[_factor_cls_name],
                        )
                        fg.register(getattr(mod, _factor_cls_name)())
                    except Exception:
                        pass

                utp = UnifiedTacticalPlanner(
                    evaluator=fg,
                    beam_width=5,
                    max_steps=self.max_chromosome_length,
                    time_budget_ms=budget_ms * 0.10,
                )
                utp_plans = utp.plan(initial_state)

                if utp_plans and utp_plans[0].state_after.is_lethal():
                    best_plan = utp_plans[0]
                    timings['utp'] = (time.perf_counter() - t_utp_start) * 1000.0
                    timings['total'] = (time.perf_counter() - t_start) * 1000.0
                    log.info(
                        "RHEA: Turn %d | UTP LETHAL | %.1fms",
                        initial_state.turn_number, timings['total'],
                    )
                    return SearchResult(
                        best_chromosome=best_plan.actions,
                        best_fitness=10000.0,
                        alternatives=[
                            (p.actions, p.score) for p in utp_plans[1:4]
                        ],
                        generations_run=0,
                        time_elapsed=timings['total'],
                        population_diversity=0.0,
                        confidence=1.0,
                        pareto_front=[],
                    )
            except Exception:
                log.debug("RHEA: UnifiedTacticalPlanner failed, falling back to RHEA", exc_info=True)

        timings['utp'] = (time.perf_counter() - t_utp_start) * 1000.0

        # Override instance params with phase-appropriate ones
        saved_pop_size = self.pop_size
        saved_max_gens = self.max_gens
        saved_max_chrom_len = self.max_chromosome_length

        self.pop_size = phase_params["pop_size"]
        self.max_gens = phase_params["max_gens"]
        self.max_chromosome_length = phase_params["max_chromosome_length"]

        effective_weights = {**phase_params["weights"], **(weights or {})}

        # ========== Layer 1: RHEA Evolutionary Search (50% of budget) ==========
        t_rhea_start = time.perf_counter()
        risk_report = None
        if RiskAssessor is not None:
            try:
                assessor = RiskAssessor()
                risk_report = assessor.assess(initial_state)
            except Exception:
                log.debug("RHEA: risk assessment failed", exc_info=True)
        population = self._init_population(initial_state)

        if utp_plans:
            for i, plan in enumerate(utp_plans[: min(3, len(population))]):
                if plan.actions:
                    population[i] = list(plan.actions)

        fitnesses: List[float] = [
            self._evaluate_chromosome(
                initial_state, chromo, effective_weights, risk_report
            )
            for chromo in population
        ]

        best_ever = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
        best_ever_chromo = list(population[best_ever])
        best_ever_fit = fitnesses[best_ever]

        gen = 0
        rhea_budget_ms = budget_ms * 0.50
        for gen in range(1, self.max_gens + 1):
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            if elapsed_ms >= rhea_budget_ms:
                break

            indexed = sorted(
                range(len(fitnesses)),
                key=lambda i: fitnesses[i],
                reverse=True,
            )

            new_pop: List[List[Action]] = []
            for ei in indexed[: self.elite_count]:
                new_pop.append(list(population[ei]))

            while len(new_pop) < self.pop_size:
                parent1 = self._tournament_select(population, fitnesses)
                parent2 = self._tournament_select(population, fitnesses)

                if random.random() < self.crossover_rate:
                    child = self._crossover(parent1, parent2, initial_state)
                else:
                    child = list(parent1)

                child = self._mutate(child, initial_state)
                new_pop.append(child)

            population = new_pop
            fitnesses = [
                self._evaluate_chromosome(
                    initial_state, chromo, effective_weights, risk_report
                )
                for chromo in population
            ]

            gen_best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
            if fitnesses[gen_best_idx] > best_ever_fit:
                best_ever_fit = fitnesses[gen_best_idx]
                best_ever_chromo = list(population[gen_best_idx])

        # ---- Phase B: Multi-turn lethal setup bonus (10% of budget) ----
        t_phase_b_start = time.perf_counter()
        try:
            phase_b_start = time.perf_counter()
            phase_b_budget_s = budget_s * 0.10

            indexed_by_fitness = sorted(
                range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
            )
            top3_indices = indexed_by_fitness[:3]

            for idx in top3_indices:
                elapsed_b = time.perf_counter() - phase_b_start
                if elapsed_b >= phase_b_budget_s:
                    break

                end_state = self._replay_chromosome(initial_state, population[idx])

                if end_state is not None and not end_state.is_lethal():
                    if next_turn_lethal_check(end_state):
                        fitnesses[idx] += 5000.0
                        if fitnesses[idx] > best_ever_fit:
                            best_ever_fit = fitnesses[idx]
                            best_ever_chromo = list(population[idx])
        except Exception:
            log.debug("RHEA: Phase B failed", exc_info=True)

        timings['phase_b'] = (time.perf_counter() - t_phase_b_start) * 1000.0

        # ---- Opponent Simulation (10% of budget) ----
        t_opp_start = time.perf_counter()
        if OpponentSimulator is not None:
            try:
                sim = OpponentSimulator()
                opp_budget_ms = budget_ms * 0.10
                opp_start = time.perf_counter()

                indexed_sorted = sorted(
                    range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
                )
                top_k = indexed_sorted[:5]

                for idx in top_k:
                    if (time.perf_counter() - opp_start) * 1000.0 >= opp_budget_ms:
                        break

                    end_state = self._replay_chromosome(initial_state, population[idx])

                    if end_state is not None:
                        opp_result = sim.simulate_best_response(
                            end_state, time_budget_ms=opp_budget_ms / 5.0
                        )
                        resilience_penalty = (
                            1.0 - opp_result.board_resilience_delta
                        ) * 200.0
                        fitnesses[idx] -= resilience_penalty
                        if opp_result.lethal_exposure:
                            fitnesses[idx] -= 2000.0

                        if fitnesses[idx] > best_ever_fit:
                            best_ever_fit = fitnesses[idx]
                            best_ever_chromo = list(population[idx])
            except Exception:
                log.debug("RHEA: Opponent sim failed", exc_info=True)

        timings['opp_sim'] = (time.perf_counter() - t_opp_start) * 1000.0

        # ---- Phase C: Cross-turn simulation (20% of budget) ----
        t_cross_start = time.perf_counter()
        if self.cross_turn:
            try:
                self._cross_turn_evaluation(
                    initial_state, population, fitnesses,
                    effective_weights, budget_s * 0.20, t_start,
                )
                gen_best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
                if fitnesses[gen_best_idx] > best_ever_fit:
                    best_ever_fit = fitnesses[gen_best_idx]
                    best_ever_chromo = list(population[gen_best_idx])
            except Exception:
                log.debug("RHEA: Phase C cross-turn failed", exc_info=True)

        timings['cross_turn'] = (time.perf_counter() - t_cross_start) * 1000.0

        # ========== Restore original params ==========
        self.pop_size = saved_pop_size
        self.max_gens = saved_max_gens
        self.max_chromosome_length = saved_max_chrom_len

        # ========== Layer 3: Selection & Confidence ==========
        mean_f = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0
        variance = (
            sum((f - mean_f) ** 2 for f in fitnesses) / len(fitnesses)
            if fitnesses
            else 0.0
        )
        diversity = variance**0.5

        if diversity < self._target_diversity * 0.5:
            self._adaptive_mutation_rate = min(self.mutation_rate * 2.0, 1.0)
        elif diversity > self._target_diversity * 2.0:
            self._adaptive_mutation_rate = max(self.mutation_rate * 0.5, 0.01)
        else:
            self._adaptive_mutation_rate = self.mutation_rate

        sorted_fits = sorted(fitnesses, reverse=True)
        if len(sorted_fits) >= 2:
            if sorted_fits[0] == 0:
                confidence = 0.5
            elif sorted_fits[1] < 0 and sorted_fits[0] > 0:
                confidence = 1.0
            else:
                ratio = sorted_fits[1] / sorted_fits[0] if sorted_fits[0] != 0 else 0
                confidence = max(0.0, min(1.0, 1.0 - ratio))
        else:
            confidence = 1.0

        indexed_sorted = sorted(
            range(len(fitnesses)),
            key=lambda i: fitnesses[i],
            reverse=True,
        )
        alternatives: List[Tuple[List[Action], float]] = []
        for idx in indexed_sorted:
            chromo = population[idx]
            if len(alternatives) >= 3:
                break
            if population[idx] is not population[indexed_sorted[0]]:
                alternatives.append((list(chromo), fitnesses[idx]))

        elapsed = (time.perf_counter() - t_start) * 1000.0

        # Pareto front
        pareto_front_list: List[Tuple[List[Action], float]] = []
        try:
            scored = []
            for i, chromo in enumerate(population):
                end_state = self._replay_chromosome(initial_state, chromo)
                if end_state is not None:
                    try:
                        delta = evaluate(end_state) - evaluate(initial_state)
                        scored.append((delta, i))
                    except Exception:
                        log.debug("pareto: evaluate failed", exc_info=True)

            scored.sort(key=lambda x: -x[0])
            for score_val, idx in scored[:5]:
                pareto_front_list.append((list(population[idx]), score_val))
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)

        timings['total'] = (time.perf_counter() - t_start) * 1000.0
        timings['rhea'] = (t_phase_b_start - t_rhea_start) * 1000.0

        complexity_str = "HARD" if self._assess_complexity(initial_state) else "NORMAL"
        log.info(
            "RHEA: Turn %d | %s | phase=%s | pop=%d gens=%d/%d | "
            "score=%.2f | conf=%.2f | div=%.2f | "
            "budget=%.0fms total=%.0fms [utp=%.0f rhea=%.0f phaseB=%.0f oppSim=%.0f crossTurn=%.0f]",
            initial_state.turn_number,
            complexity_str,
            phase,
            self.pop_size, gen, self.max_gens,
            best_ever_fit, confidence, diversity,
            budget_ms, timings['total'],
            timings.get('utp', 0),
            timings.get('rhea', 0),
            timings.get('phase_b', 0),
            timings.get('opp_sim', 0),
            timings.get('cross_turn', 0),
        )

        return SearchResult(
            best_chromosome=best_ever_chromo,
            best_fitness=best_ever_fit,
            alternatives=alternatives,
            generations_run=gen,
            time_elapsed=elapsed,
            population_diversity=diversity,
            confidence=confidence,
            pareto_front=pareto_front_list,
            timings=timings,
        )

    # ---------------------------------------------------------------
    # Population initialisation
    # ---------------------------------------------------------------

    def _assess_complexity(self, state: GameState) -> int:
        """Assess board complexity to determine time budget tier."""
        score = 0
        board_total = len(state.board) + len(state.opponent.board)
        score += board_total * 2
        score += len(state.hand) * 2
        score += state.mana.available * 3

        if state.opponent.secrets:
            score += len(state.opponent.secrets) * 5

        opp_health = state.opponent.hero.hp + state.opponent.hero.armor
        our_attack = sum(m.attack for m in state.board)
        if our_attack > 0 and opp_health <= our_attack + 10:
            score += 8

        our_health = state.hero.hp + state.hero.armor
        opp_attack = sum(m.attack for m in state.opponent.board)
        if opp_attack > 0 and our_health <= opp_attack + 5:
            score += 10

        if state.mana.available >= 8:
            score += 5

        if state.opponent.hand_count >= 6:
            score += 3

        for m in state.board:
            if m.has_windfury or m.has_mega_windfury:
                score += 3
            if m.has_divine_shield:
                score += 2

        threshold = 35
        return self.COMPLEXITY_HARD if score >= threshold else self.COMPLEXITY_NORMAL

    def _adaptive_time_limit(self, state: GameState) -> float:
        """Compute adaptive time limit in ms based on board complexity."""
        complexity = self._assess_complexity(state)
        turn = max(state.turn_number, 1)

        if complexity == self.COMPLEXITY_HARD:
            base = 5000.0
            ceiling = 15000.0
            turn_scale = min(turn / 15.0, 1.0)
            budget = base + (ceiling - base) * turn_scale
        else:
            base = 3000.0
            ceiling = 5000.0
            turn_scale = min(turn / 12.0, 1.0)
            budget = base + (ceiling - base) * turn_scale

        if self._time_limit_explicit:
            budget = self.time_limit

        log.debug(
            "RHEA: complexity=%s turn=%d budget=%.0fms",
            "HARD" if complexity else "NORMAL",
            turn,
            budget,
        )
        return budget

    def _detect_phase(self, state: GameState) -> str:
        """Detect game phase using unified Phase enum."""
        return detect_phase(state.turn_number).value

    def _get_phase_params(self, phase: str) -> dict:
        """Get search parameters for game phase."""
        params = {
            "early": {
                "pop_size": 30,
                "max_gens": 100,
                "max_chromosome_length": 4,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 0.8,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
            "mid": {
                "pop_size": 50,
                "max_gens": 200,
                "max_chromosome_length": 6,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 1.5,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
            "late": {
                "pop_size": 60,
                "max_gens": 150,
                "max_chromosome_length": 8,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 2.0,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
        }
        return params.get(phase, params["mid"])

    @staticmethod
    def _replay_chromosome(
        initial_state: GameState, chromo: List[Action]
    ) -> Optional[GameState]:
        """Replay a chromosome from initial_state and return end state."""
        end_state = initial_state.copy()
        for action in chromo:
            legal = enumerate_legal_actions(end_state)
            if not action_in_list(action, legal):
                return None
            end_state = apply_action(end_state, action)
        return end_state

    def _is_desperate(self, state: GameState) -> bool:
        """Detect if we are in a desperate situation."""
        friendly_board_power = sum(m.attack + m.health for m in state.board)
        enemy_board_power = sum(m.attack + m.health for m in state.opponent.board)
        if state.opponent.board and not state.board and enemy_board_power > 15:
            return True
        if enemy_board_power > friendly_board_power * 3 + 10:
            return True
        if state.hero.hp <= 10 and enemy_board_power > 10:
            return True
        return False

    def _cross_turn_evaluation(
        self,
        initial_state: GameState,
        population: List[List[Action]],
        fitnesses: List[float],
        weights: dict,
        budget_s: float,
        t_start: float,
    ) -> None:
        """Phase C: Cross-turn simulation for top-K chromosomes."""
        deadline = time.perf_counter() + budget_s * 0.9

        indexed = sorted(
            range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
        )
        top_k = indexed[:5]

        sim = None
        if OpponentSimulator is not None:
            sim = OpponentSimulator()

        alpha = 0.3

        for idx in top_k:
            if time.perf_counter() >= deadline:
                break

            end_state = self._replay_chromosome(initial_state, population[idx])
            if end_state is None or end_state.is_lethal():
                continue

            opp_end = self._simulate_opponent_response(end_state, sim, deadline)
            if opp_end is None:
                continue

            next_value = self._simulate_our_next_turn(opp_end, deadline)
            if next_value is None:
                continue

            current_value = evaluate(end_state, weights)
            cross_turn_delta = next_value - current_value
            fitnesses[idx] += alpha * cross_turn_delta

            if sim is not None:
                opp_result = sim.simulate_best_response(
                    end_state, time_budget_ms=50.0
                )
                if opp_result.lethal_exposure:
                    fitnesses[idx] -= 1500.0

    def _simulate_opponent_response(
        self,
        state: GameState,
        sim,
        deadline: float,
    ) -> Optional[GameState]:
        """Simulate opponent's best response to our turn end state."""
        if time.perf_counter() >= deadline:
            return None

        opp_state = state.copy()

        next_mana = min(opp_state.mana.max_mana + 1, opp_state.mana.max_mana_cap)
        opp_mana_available = next_mana - opp_state.mana.overloaded

        opp_state.mana.available = max(0, opp_mana_available)
        opp_state.mana.max_mana = next_mana
        opp_state.mana.overloaded = opp_state.mana.overload_next
        opp_state.mana.overload_next = 0

        for m in opp_state.opponent.board:
            if not m.has_rush:
                m.can_attack = True
            m.has_attacked_once = False

        opp_state.hero.is_immune = False
        for m in opp_state.board:
            m.frozen_until_next_turn = False
            m.has_immune = False

        if opp_state.deck_remaining > 0:
            opp_state.deck_remaining -= 1

        return opp_state

    def _simulate_our_next_turn(
        self,
        state: GameState,
        deadline: float,
    ) -> Optional[float]:
        """Simulate our next turn value after opponent's response."""
        if time.perf_counter() >= deadline:
            return None

        next_state = state.copy()

        next_mana = min(next_state.mana.max_mana + 1, next_state.mana.max_mana_cap)
        next_state.mana.max_mana = next_mana
        next_state.mana.available = max(0, next_mana - next_state.mana.overloaded)
        next_state.mana.overloaded = next_state.mana.overload_next
        next_state.mana.overload_next = 0
        next_state.mana.modifiers = []

        for m in next_state.board:
            m.can_attack = True
            m.has_attacked_once = False
            m.frozen_until_next_turn = False
            m.has_immune = False

        if next_state.deck_remaining > 0:
            next_state.deck_remaining -= 1

        next_state.turn_number += 1

        return evaluate(next_state)

    def _init_population(self, state: GameState) -> List[List[Action]]:
        """Create initial population of random legal action sequences."""
        population: List[List[Action]] = []
        for _ in range(self.pop_size):
            chromo = self._random_chromosome(state)
            if normalize_chromosome is not None:
                try:
                    chromo = normalize_chromosome(chromo, state)
                except Exception:
                    log.debug("apply_action: optional mechanic failed", exc_info=True)
            population.append(chromo)
        return population

    def _random_chromosome(self, state: GameState) -> List[Action]:
        """Generate one random legal action sequence ending with END_TURN."""
        chromo: List[Action] = []
        current = state.copy()

        for _ in range(self.max_chromosome_length):
            legal = enumerate_legal_actions(current)
            non_end = [a for a in legal if a.action_type != "END_TURN"]

            if not non_end:
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            if random.random() < 0.15:
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            action = random.choice(non_end)
            chromo.append(action)
            current = apply_action(current, action)

        if not chromo or chromo[-1].action_type != "END_TURN":
            chromo.append(Action(action_type="END_TURN"))

        return chromo

    # ---------------------------------------------------------------
    # Fitness evaluation
    # ---------------------------------------------------------------

    def _evaluate_chromosome(
        self,
        initial_state: GameState,
        chromo: List[Action],
        weights: Optional[dict],
        risk_report=None,
    ) -> float:
        """Apply all actions and return evaluate_delta."""
        current = initial_state
        legal_cache = enumerate_legal_actions(current)
        legal_action_keys = {action_key(a) for a in legal_cache}

        for action in chromo:
            ak = action_key(action)
            if ak not in legal_action_keys:
                return -9999.0

            current = apply_action(current, action)
            if current.is_lethal():
                return 10000.0

            legal_cache = enumerate_legal_actions(current)
            legal_action_keys = {action_key(a) for a in legal_cache}

        if evaluate_delta_with_risk is not None and risk_report is not None:
            try:
                return evaluate_delta_with_risk(
                    initial_state, current, weights, risk_report
                )
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return evaluate_delta(initial_state, current, weights)

    # ---------------------------------------------------------------
    # Tournament selection
    # ---------------------------------------------------------------

    def _tournament_select(
        self,
        population: List[List[Action]],
        fitnesses: List[float],
    ) -> List[Action]:
        """Pick tournament_size random individuals; return the fittest."""
        candidates = random.sample(
            range(len(population)),
            min(self.tournament_size, len(population)),
        )
        best = max(candidates, key=lambda i: fitnesses[i])
        return population[best]

    # ---------------------------------------------------------------
    # Crossover
    # ---------------------------------------------------------------

    def _crossover(
        self,
        parent1: List[Action],
        parent2: List[Action],
        state: GameState,
    ) -> List[Action]:
        """Sequence-preserving n-point crossover."""
        if not parent1 or not parent2:
            return list(parent1) if parent1 else list(parent2)

        max_len = min(len(parent1), len(parent2))
        if max_len <= 1:
            return copy.deepcopy(parent1)

        cp = random.randint(1, max_len - 1)
        child = [copy.deepcopy(a) for a in parent1[:cp]]
        child += [copy.deepcopy(a) for a in parent2[cp:]]

        if child and child[-1].action_type != "END_TURN":
            child.append(Action(action_type="END_TURN"))

        if normalize_chromosome is not None:
            try:
                child = normalize_chromosome(child, state)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return child

    # ---------------------------------------------------------------
    # Chromosome validation
    # ---------------------------------------------------------------

    def _validate_chromosome(self, state: GameState, chromosome: List[Action]) -> bool:
        """Replay chromosome from state; return True if all actions legal."""
        current = state.copy()
        for action in chromosome:
            legal = enumerate_legal_actions(current)
            if not action_in_list(action, legal):
                return False
            current = apply_action(current, action)
        return True

    # ---------------------------------------------------------------
    # Mutation
    # ---------------------------------------------------------------

    def _mutate(
        self,
        chromo: List[Action],
        state: GameState,
    ) -> List[Action]:
        """With probability mutation_rate, replace a random gene."""
        result = [copy.deepcopy(a) for a in chromo]

        if random.random() < self._adaptive_mutation_rate and result:
            pos = random.randrange(len(result))

            current = state.copy()
            for i in range(pos):
                legal = enumerate_legal_actions(current)
                act = result[i]
                if action_in_list(act, legal):
                    current = apply_action(current, act)
                else:
                    break

            legal = enumerate_legal_actions(current)
            if legal:
                result[pos] = random.choice(legal)

        if normalize_chromosome is not None:
            try:
                result = normalize_chromosome(result, state)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return result

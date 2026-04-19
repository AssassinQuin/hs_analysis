# V9 Decision Engine v2 — Implementation Plan

**Design**: `thoughts/shared/designs/2026-04-19-v9-decision-engine-v2-design.md`
**Supersedes**: `thoughts/shared/plans/2026-04-18-v9-decision-engine.md`

## Overview

| Phase | Tasks | Parallelism | Depends On |
|-------|-------|-------------|------------|
| 0 | 0.1 + 0.2 | 2 parallel | None |
| 1 | 1.1 + 1.2 + 1.3 | 3 parallel | None |
| 2 | 2.1 + 2.2 | 2 parallel | Phase 0, 1 |
| 3 | 3.1 + 3.2 | 2 parallel | Phase 1, 2 |
| 4 | 4.1 | Sequential | Phase 2, 3 |
| 5 | 5.1 + 5.2 | 2 parallel | Phase 4 |
| 6 | 6.1 + 6.2 + 6.3 | 3 parallel | Phase 5 |

**Total**: 15 micro-tasks across 7 phases.

---

## Phase 0: Data Model Updates (2 parallel)

### Task 0.1: GameState — Add deck_list and secrets fields

- **File**: `hs_analysis/search/game_state.py`
- **What**: Add two optional fields to `GameState` dataclass:
  - `deck_list: Optional[List[Card]]` — remaining cards in player's deck (for draw probability)
  - Add `secrets: List[str]` field to `OpponentState` (for opponent secret tracking)
- **Constraint**: Fields default to `None` / `[]` — fully backward compatible
- **Verification**: Run existing tests in `game_state.py __main__` block

### Task 0.2: RiskReport dataclass

- **File**: `hs_analysis/search/risk_assessor.py` (NEW — create with dataclass only)
- **What**: Define `RiskReport` dataclass with fields:
  - `aoe_vulnerability: float` (0.0 = no minions at risk, higher = more minions die)
  - `overextension_penalty: float` (0.0 = safe minion count)
  - `survival_score: float` (1.0 = healthy, approaches 0.0 as health drops)
  - `secret_threat: float` (0.0 = no secrets)
  - `total_risk: float` (weighted composite)
  - `is_safe: bool` (total_risk below threshold)
- **Verification**: Import the dataclass, instantiate with defaults

---

## Phase 1: Core New Components (3 parallel)

### Task 1.1: Lethal Checker

- **File**: `hs_analysis/search/lethal_checker.py` (NEW)
- **What**: Exhaustive lethal detection
  - `max_damage_bound(state: GameState) -> int` — sum all possible damage: minion attacks (sum of attack values for can-attack minions) + hand spell damage (regex parse damage from spell text) + weapon damage + hero power damage
  - `check_lethal(state: GameState, time_budget_ms: float = 5.0) -> Optional[List[Action]]`
    - If `max_damage_bound < enemy_health` → return None immediately (fast path)
    - If possible: DFS over damage-dealing actions only (ATTACK minions, PLAY damage spells, weapon attacks, hero power)
    - Pruning: sort actions by damage/cost ratio, early termination when remaining max damage < remaining enemy health
    - Time budget: if exceeded, return None (fallback to RHEA)
  - `_enumerate_damage_actions(state) -> List[Action]` — only damage-dealing subset of legal actions
  - `_dfs_lethal(state, actions, remaining_health, depth, deadline) -> Optional[List[Action]]`
- **Constraint**: Must be exhaustive within time budget. Missing lethal is catastrophic.
- **Verification**: Test with constructed states where lethal exists and doesn't exist

### Task 1.2: Risk Assessor

- **File**: `hs_analysis/search/risk_assessor.py` (UPDATE — add logic to existing dataclass file)
- **What**: Risk evaluation functions
  - `RiskAssessor` class:
    - `__init__()`: load AoE response data (hardcoded top threats per class, graceful fallback)
    - `aoe_vulnerability(state: GameState) -> float` — for each friendly minion, check if it would die to common AoE thresholds (2 dmg, 3 dmg, 4 dmg, 5 dmg). Return weighted count of vulnerable minions. Weight by opponent class if known.
    - `overextension_penalty(state: GameState) -> float` — count friendly minions. 0-3 = 0.0, 4 = 0.1, 5 = 0.3, 6 = 0.5, 7 = 0.8. Diminishing returns curve.
    - `survival_score(state: GameState) -> float` — based on hero health: 30-20hp = 1.0, 20-15 = 0.8, 15-10 = 0.5, 10-5 = 0.3, <5 = 0.1
    - `secret_threat(state: GameState) -> float` — if opponent has N secrets: N × 0.3 (rough estimate)
    - `assess(state: GameState) -> RiskReport` — combine all with default weights (α=0.3, β=0.2, γ=0.2, δ=0.3 for survival)
  - AoE thresholds hardcoded for top classes (Mage: 2/3/6 dmg, Warlock: 2/3, Paladin: 2, Priest: 2/3, Hunter: 1/3)
- **Constraint**: All calculations must complete in < 1ms
- **Verification**: Unit test with known board states

### Task 1.3: Opponent Simulator

- **File**: `hs_analysis/search/opponent_simulator.py` (NEW)
- **What**: 1-turn greedy opponent simulation
  - `SimulatedOpponentTurn` dataclass: `board_resilience_delta: float`, `friendly_deaths: int`, `lethal_exposure: bool`, `worst_case_damage: int`
  - `OpponentSimulator` class:
    - `__init__(eval_fn=None)`: takes optional evaluation function (defaults to composite evaluator)
    - `simulate_best_response(state: GameState, time_budget_ms: float = 10.0) -> SimulatedOpponentTurn`
      - Create opponent's perspective: swap hero/opponent, swap board
      - Enumerate top opponent actions (PLAY minions, ATTACK with existing minions, use removal)
      - For each action: evaluate resulting board from opponent's perspective
      - Pick best opponent action, compute delta from our perspective
    - `_enumerate_opponent_actions(state) -> List[Action]` — simplified action enumeration for opponent
    - `_evaluate_from_opponent_perspective(state) -> float` — negate our eval score
  - Graceful degradation: if timeout or error, return `SimulatedOpponentTurn(0.0, 0, False, 0)`
- **Constraint**: Must complete in < 10ms
- **Verification**: Test with known board states

---

## Phase 2: Action Normalization + Evaluation Enhancement (2 parallel)

### Task 2.1: Action Normalization

- **File**: `hs_analysis/search/action_normalize.py` (NEW)
- **What**: Normalize chromosome action sequences to eliminate equivalent orderings
  - `action_hash(action: Action) -> tuple` — returns (action_type, source_key, target_key)
  - `are_commutative(a1: Action, a2: Action, state: GameState) -> bool` — two actions are commutative if:
    - Both are ATTACK actions on different source minions targeting different targets
    - Neither action changes the other's validity (no buff→attack dependency)
  - `normalize_chromosome(chromosome: List[Action], state: GameState) -> List[Action]`:
    - Group consecutive commutative actions
    - Sort within groups by action_hash (canonical ordering)
    - Preserve non-commutative action ordering (PLAY before dependent ATTACK)
  - `is_canonical(chromosome: List[Action], state: GameState) -> bool` — for filtering in mutation
- **Constraint**: Must preserve semantics — normalized chromosome must produce same state when applied
- **Verification**: Test that normalized and original chromosomes produce identical results

### Task 2.2: Composite Evaluator — Risk-Adjusted Path

- **File**: `hs_analysis/evaluators/composite.py` (MODIFY)
- **What**: Add risk-adjusted evaluation method
  - `evaluate_with_risk(state: GameState, weights: dict, risk_report: RiskReport) -> float`
    - base_score = existing `evaluate(state, weights)`
    - risk_penalty = risk_report.total_risk * risk_weight (default 0.3)
    - return base_score * (1.0 - risk_penalty)
  - `evaluate_delta_with_risk(initial: GameState, current: GameState, weights: dict, risk: RiskReport) -> float`
    - Same as evaluate_delta but using evaluate_with_risk for current state
  - Import `RiskReport` from `hs_analysis.search.risk_assessor`
  - Backward compatible: existing `evaluate()` and `evaluate_delta()` unchanged
- **Verification**: Existing composite evaluator tests still pass; new method returns different scores for risky vs safe states

---

## Phase 3: RHEA Engine Integration (2 parallel)

### Task 3.1: RHEA — Action Normalization Integration

- **File**: `hs_analysis/search/rhea_engine.py` (MODIFY)
- **What**: Integrate action normalization into evolutionary loop
  - Import `normalize_chromosome` from `action_normalize`
  - In `_init_population()`: normalize each random chromosome after generation
  - In `_mutate()`: normalize result after mutation
  - In `_crossover()`: normalize child after crossover
  - Skip normalization if action_normalize import fails (graceful fallback)
- **Constraint**: Must not slow down search loop noticeably
- **Verification**: Existing RHEA tests pass; normalized chromosomes produce valid action sequences

### Task 3.2: RHEA — Adaptive Parameters + Phase Detection

- **File**: `hs_analysis/search/rhea_engine.py` (MODIFY)
- **What**: Adaptive search parameters based on game phase
  - `_detect_phase(state: GameState) -> str` — "early" (turns 1-3), "mid" (4-7), "late" (8+)
  - `_get_phase_params(phase: str) -> dict`:
    - early: pop_size=30, max_gens=100, max_chromosome_length=4
    - mid: pop_size=50, max_gens=200, max_chromosome_length=6 (current defaults)
    - late: pop_size=60, max_gens=150, max_chromosome_length=8
  - Override constructor defaults at search time based on phase
  - Phase-based weight presets for fitness evaluation:
    - early: tempo-heavy (w_t=0.5, w_v=0.2, w_s=0.1, w_d=0.2)
    - mid: balanced (w_t=0.3, w_v=0.3, w_s=0.2, w_d=0.2)
    - late: survival-heavy (w_t=0.2, w_v=0.2, w_s=0.4, w_d=0.2)
- **Constraint**: Backward compatible — if no phase detected, use current defaults
- **Verification**: Existing tests pass; phase detection returns correct values

---

## Phase 4: Layered Pipeline Wiring (Sequential)

### Task 4.1: RHEA — Full Layered Pipeline

- **File**: `hs_analysis/search/rhea_engine.py` (MODIFY)
- **What**: Wire all layers into the search method
  - Import `check_lethal` from `lethal_checker`, `RiskAssessor` from `risk_assessor`, `OpponentSimulator` from `opponent_simulator`
  - All imports wrapped in try/except — if missing, skip that layer
  - Modify `search()` method flow:
    ```
    1. Layer 0: result = check_lethal(initial_state, time_budget_ms=5.0)
       → if lethal found: return SearchResult(actions=result, fitness=10000.0, confidence=1.0)
    2. Phase detection → adaptive params + weights
    3. Layer 1: existing RHEA evolutionary loop (enhanced with normalization + risk-aware fitness)
       → fitness function now calls evaluate_with_risk() when risk assessor available
    4. Layer 2: for top-K candidates from Layer 1
       → simulate_best_response() for each
       → apply resilience penalty: fitness -= (1 - board_resilience_delta) * resilience_weight
       → if lethal_exposure: fitness -= 2000.0
    5. Layer 3: existing Pareto front + confidence scoring (unchanged)
    6. Return SearchResult
    ```
  - Time budget allocation:
    - Lethal check: 5ms
    - RHEA search: budget * 0.65
    - Opponent sim: budget * 0.15 (applied to top-5 candidates)
    - Buffer: budget * 0.15
- **Constraint**: All layers wrapped in try/except. Each layer's failure does NOT crash the engine.
- **Verification**: All existing tests pass. New pipeline produces SearchResult for various game states.

---

## Phase 5: Tests — New Components (2 parallel)

### Task 5.1: Lethal Checker Tests

- **File**: `hs_analysis/search/test_lethal_checker.py` (NEW)
- **What**: Unit tests for lethal checker
  - `test_no_lethal_possible`: Board where max damage < enemy health → returns None
  - `test_simple_lethal`: One minion can attack for lethal → finds it
  - `test_multi_minion_lethal`: Multiple minions combine for lethal → finds correct sequence
  - `test_spell_lethal`: Spell in hand provides exact lethal → finds it
  - `test_lethal_with_taunt`: Must attack taunt first → correctly finds path through taunt
  - `test_timeout`: Very complex board, time budget expires → returns None (not crash)
  - `test_empty_board`: No damage sources → returns None immediately
- **Verification**: `python -m pytest hs_analysis/search/test_lethal_checker.py`

### Task 5.2: Risk Assessor + Opponent Sim Tests

- **File**: `hs_analysis/search/test_risk_assessor.py` (NEW)
- **What**: Unit tests for risk assessor
  - `test_no_risk`: Empty board → zero risk
  - `test_aoe_vulnerability`: Board of 2-health minions → high vulnerability to 2-dmg AoE
  - `test_overextension`: 7 minions → high overextension penalty
  - `test_survival_low_hp`: Hero at 5hp → very low survival score
  - `test_secret_threat`: Opponent has 2 secrets → moderate threat
  - `test_composite_risk`: Multiple risk factors → weighted composite

- **File**: `hs_analysis/search/test_opponent_simulator.py` (NEW)
- **What**: Unit tests for opponent simulator
  - `test_no_opponent_actions`: Opponent has empty hand/board → minimal impact
  - `test_opponent_trades`: Opponent has board → simulates favorable trades
  - `test_opponent_lethal`: Opponent has lethal on us → detects lethal_exposure=True
  - `test_timeout`: Complex state, time budget expires → returns safe default
  - `test_graceful_fallback`: Import error → returns default SimulatedOpponentTurn
- **Verification**: `python -m pytest hs_analysis/search/test_risk_assessor.py hs_analysis/search/test_opponent_simulator.py`

---

## Phase 6: Integration Tests + Verification (3 parallel)

### Task 6.1: Full Pipeline Integration Test

- **File**: `hs_analysis/search/test_v9_pipeline.py` (NEW)
- **What**: End-to-end test of the complete layered pipeline
  - `test_pipeline_returns_result`: Any valid GameState → SearchResult with valid actions
  - `test_lethal_short_circuits`: Lethal state → search returns immediately with lethal sequence
  - `test_no_lethal_proceeds_to_search`: Non-lethal state → RHEA search runs
  - `test_risk_adjusts_ranking`: Risky board → different action selection than safe board
  - `test_opponent_sim_adjusts_scores`: Opponent has board → resilience penalty applied
  - `test_all_layers_degradation`: Mock import failures → engine still returns result
  - `test_time_budget_respected`: Full pipeline completes within budget

### Task 6.2: Regression Test — V9 vs V8

- **File**: `hs_analysis/search/test_v8_v9_regression.py` (NEW)
- **What**: Ensure V9 decisions are never catastrophically worse than V8
  - `test_v9_finds_lethal_when_v8_might_miss`: Lethal state that V8 search might not find in time
  - `test_v9_avoids_obvious_overextension`: Board where V8 would overcommit, V9 doesn't
  - `test_v9_same_as_v8_for_safe_boards`: Low-risk board → V9 and V8 produce similar fitness rankings
  - Run both V8-style (risk disabled) and V9-style (risk enabled) evaluations, compare

### Task 6.3: Full Test Suite Verification

- **What**: Run ALL tests — existing 44 + new tests
  - `cd hs_analysis && python -m pytest ../scripts/ ../tests/ -v`
  - Also run standalone `__main__` tests in key modules
  - Verify no regressions in:
    - `game_state.py` self-test
    - `score_provider.py` self-test
    - `submodel_evaluator.py` self-test
    - `composite_evaluator.py` self-test
    - `rhea_engine.py` self-test
    - `v8_contextual_scorer.py` self-test
    - `test_integration.py`
- **Verification**: All tests green, zero regressions

---

## Dependency Graph

```
Phase 0 (0.1, 0.2) ──┐
                       ├─→ Phase 2 (2.1, 2.2) ──┐
Phase 1 (1.1, 1.2, 1.3) ─┘                      ├─→ Phase 3 (3.1, 3.2) ──→ Phase 4 (4.1)
                                                  │
                                                  └─→ Phase 5 (5.1, 5.2) ──→ Phase 6 (6.1, 6.2, 6.3)
```

Phases 0 and 1 can start immediately (no dependencies).
Phase 2 depends on 0 and 1 (risk assessor dataclass from 0.2, imports from 1.2).
Phase 3 depends on 2 (action_normalize + composite risk path needed).
Phase 4 depends on 2 and 3 (all components wired together).
Phase 5 can start after Phase 1 components exist (test the new modules).
Phase 6 depends on Phase 4 (full pipeline must be wired before integration testing).

## Estimated Effort

| Phase | New Lines (est.) | Modified Lines (est.) | Risk |
|-------|-----------------|----------------------|------|
| 0 | ~30 | ~20 | Low |
| 1 | ~400 | 0 | Medium (lethal checker complexity) |
| 2 | ~80 | ~40 | Low |
| 3 | ~60 | ~100 | Medium (RHEA is core engine) |
| 4 | 0 | ~120 | High (integration point) |
| 5 | ~250 | 0 | Low (tests only) |
| 6 | ~200 | 0 | Low (tests only) |
| **Total** | **~1020** | **~280** | |

## Risk Mitigation

1. **Lethal checker timeout**: DFS with deadline, falls back to RHEA search
2. **Risk assessor wrong weights**: Default weights are conservative, can be tuned later
3. **Opponent sim too slow**: Time-budgeted, returns safe default on timeout
4. **Action normalization bugs**: Preserves original as fallback, normalization is additive
5. **Phase 4 integration**: Every layer is optional (try/except), engine works without any new layer

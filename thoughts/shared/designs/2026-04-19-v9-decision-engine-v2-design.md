---
date: 2026-04-19
topic: "V9 Decision Engine - Research-Informed Redesign"
status: draft
supersedes: thoughts/shared/designs/2026-04-18-v9-decision-engine-design.md
---

# V9 Decision Engine - Research-Informed Redesign

## Problem Statement

The current RHEA engine searches well but evaluates poorly. Research into SilverFish, peter1591's MCTS+NN, and EA-optimized agents confirms: evaluation function quality matters more than search algorithm sophistication. The engine cannot distinguish "good board but vulnerable to AoE" from "good board and safe." Missing: risk awareness, opponent turn simulation, action normalization, exhaustive lethal check.

## Constraints

- Backward compatible (all 44 existing tests must pass)
- Python only, no C extensions, no GPU
- Time budget: 75ms base, adaptive up to 150ms
- No external API calls during search
- Graceful degradation (missing data → simpler evaluation)
- Must work with existing package structure (hs_analysis/)

## Approach: Layered Decision Pipeline

Research shows that layered pipelines (like SilverFish's) outperform monolithic search for Hearthstone. Rather than replacing RHEA with MCTS, we enhance it with pre/post-search layers:

**Layer 0: Exhaustive Lethal Check** (new)
- Fast max-damage bounding to prune impossible lethals
- If lethal exists, return immediately (skip remaining layers)
- Inspired by SilverFish's TAGGS.cs dedicated lethal path

**Layer 1: Enhanced RHEA Search** (modify existing)
- Action normalization (collapse equivalent orderings)
- Adaptive parameters by game phase
- Risk-aware fitness function
- Inspired by EA-optimized agents that beat MCTS at CIG 2018

**Layer 2: Opponent Turn Simulation** (new)
- 1-turn greedy simulation of opponent's best play
- Board resilience scoring
- Inspired by SilverFish's EnemyTurnSimulator
- NOT full IS-MCTS (too expensive for real-time)

**Layer 3: Selection + Confidence** (enhance existing)
- Risk-adjusted Pareto front
- Phase-aware weight selection
- Confidence scoring enhanced with risk signal

## Architecture

### New Components

**hs_analysis/search/lethal_checker.py**
- `check_lethal(state: GameState) -> Optional[List[Action]]`
- Max-damage bounding: sum all possible damage sources (minion attacks + hand spell damage + weapon + hero power)
- If max_damage < enemy health → no lethal possible, return None
- If possible: exhaustive DFS over damage-dealing actions
- Pruning: sort actions by damage efficiency, early termination when remaining damage insufficient
- Must be exhaustive — missing lethal is catastrophic

**hs_analysis/search/risk_assessor.py**
- `RiskAssessor` class with methods:
  - `aoe_vulnerability(state: GameState) -> float` — count minions that die to class-specific AoE (weighted by archetype likelihood)
  - `overextension_penalty(state: GameState) -> float` — diminishing returns beyond 4-5 minions
  - `survival_score(state: GameState) -> float` — health-based urgency (scales up below 15hp)
  - `secret_threat(state: GameState) -> float` — estimate worst-case secret penalty
  - `assess(state: GameState) -> RiskReport` — composite risk score

**hs_analysis/search/opponent_simulator.py**
- `OpponentSimulator` class:
  - `simulate_best_response(state: GameState) -> SimulatedOpponentTurn`
  - Uses greedy evaluation (enumerate top actions, score resulting boards)
  - NOT full MCTS — just best single opponent action sequence
  - Returns board resilience delta and lethal exposure flag

### Modified Components

**hs_analysis/search/rhea_engine.py**
- Add Layer 0 lethal check before search loop
- Integrate RiskAssessor into fitness function
- Add action normalization (normalize_chromosome method)
- Adaptive parameters: early_game (pop=30, gens=100), mid_game (pop=50, gens=200), late_game (pop=60, gens=150, longer chromosomes)
- Layer 2 opponent sim applied post-search to top-K candidates

**hs_analysis/evaluators/composite.py**
- Add `evaluate_with_risk(state, weights, risk_report)` method
- V9 fitness = composite_score - risk_penalty + resilience_bonus

**hs_analysis/search/game_state.py**
- Add `deck_list: Optional[List[Card]]` field for draw probability
- Add `secrets: List[str]` field for opponent secret tracking

### Data Flow

```
GameState input
    │
    ▼
┌─────────────────────────┐
│ Layer 0: Lethal Check   │ ──→ Lethal found? ──→ Return lethal sequence
└───────────┬─────────────┘
            │ No lethal
            ▼
┌─────────────────────────┐
│ Phase Detection         │ ──→ Select weights + params for early/mid/late
└───────────┬─────────────┘
            │
            ▼
┌─────────────────────────┐
│ Layer 1: RHEA Search    │ ──→ Top-K candidate sequences
│ (enhanced fitness)      │     Fitness = V(state_after) - V(before) - Risk
└───────────┬─────────────┘
            │ Top-K candidates
            ▼
┌─────────────────────────┐
│ Layer 2: Opponent Sim   │ ──→ Risk-adjusted scores per candidate
│ (1-turn greedy)         │     Board resilience penalty applied
└───────────┬─────────────┘
            │ Risk-adjusted rankings
            ▼
┌─────────────────────────┐
│ Layer 3: Selection      │ ──→ SearchResult with confidence
│ (Pareto + confidence)   │
└─────────────────────────┘
```

## V9 Fitness Formula

```
V9_fitness = base_value_delta - risk_penalty + resilience_bonus

where:
  base_value_delta = composite_eval(after) - composite_eval(before)
  risk_penalty = α × aoe_vulnerability + β × overextension + γ × secret_threat
  resilience_bonus = δ × board_survival_rate (from opponent sim)
  
  weights (α, β, γ, δ) scale by game phase:
    early (turns 1-3): tempo-heavy, low risk weight
    mid (turns 4-7): balanced
    late (turns 8+): survival-heavy, high risk weight
```

## Action Normalization Strategy

Problem: Chromosomes [Attack A→B, Attack B→A] and [Attack B→A, Attack A→B] produce identical states.

Solution:
1. Hash each action as (action_type, card_index_or_source, target_index)
2. Identify commutable action groups (attacks between independent minions)
3. Sort within commutable groups by hash (canonical ordering)
4. Preserve combo-dependent orderings (buff before attack, charge enables attack)
5. During mutation: reject mutations that create non-canonical orderings

This reduces effective search space by ~60% for typical mid-game turns.

## Error Handling

- Lethal checker timeout (5ms budget): fall back to RHEA search without lethal guarantee
- Risk assessor data missing: use zero risk (current behavior)
- Opponent sim timeout (10ms budget): skip Layer 2, use Layer 1 scores directly
- Invalid action in chromosome: existing -9999.0 penalty preserved
- All layers wrapped in try/except: never crash, always return a SearchResult

## Testing Strategy

### Unit Tests (new)
- `test_lethal_checker.py`: Known lethal puzzles (checkmate-like scenarios)
- `test_risk_assessor.py`: AoE vulnerability counts, overextension curves
- `test_opponent_simulator.py`: Board resilience scoring
- `test_action_normalization.py`: Canonical ordering verification

### Integration Tests (extend existing)
- All 44 existing tests must continue to pass
- New test: full pipeline (lethal → search → opponent sim → selection)
- Regression test: V9 decisions never worse than V8 on benchmark states

### Performance Tests
- Lethal checker: < 5ms for any state
- Opponent sim: < 10ms for any state
- Full V9 pipeline: < 150ms for any state (75ms typical)

## Open Questions

1. AoE damage thresholds per class — hardcode top-4 classes or load from data?
2. Action normalization: how to handle charge minions (attack depends on play)?
3. Opponent sim: use same evaluation function or simpler heuristic?
4. Phase detection: mana-based (0-3, 4-7, 8+) or adaptive?
5. Risk weight calibration: start with equal weights or use SilverFish's ratios?

## Relationship to Previous V9 Design

This design supersedes the earlier V9 design (2026-04-18). Key differences:
- Replaces 6 new component files with 3 (YAGNI)
- Simplified opponent modeling (greedy sim vs. Bayesian)
- No Discover branching (expected-value approximation)
- No response catalog generator (premature)
- Time budget 75-150ms (vs. fixed 200ms)
- Added action normalization (missing from original design)
- Added lethal check as mandatory Layer 0

The design doc at `thoughts/shared/designs/2026-04-18-v9-decision-engine-design.md` should be archived but kept for reference.

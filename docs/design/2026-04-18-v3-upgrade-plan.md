# V3 Decision Engine Upgrade — Implementation Plan

## Overview

Upgrade the decision engine with spell simulation, multi-objective evaluation, particle filter opponent model, and multi-turn planning.

**Design doc**: `thoughts/shared/designs/2026-04-18-v3-upgrade-design.md`

## Task Dependency Graph

```
T012 ─────────────────────────────────────┐
T013 ──────────────────────┐              │
T014 ──────────────────────│──────────────┤
                          ↓              ↓
T015 (needs T013) → T016 (needs T015) → T018 (needs T012+T016)
T017 ─────────────────────────────────────┤
                                          ↓
                                    T019 (needs all)
```

## Batch Execution Order

| Batch | Tasks | Parallelism |
|-------|-------|-------------|
| 1 | T012 + T013 + T014 + T017 | All independent, run in parallel |
| 2 | T015 | Depends on T013 |
| 3 | T016 | Depends on T015 |
| 4 | T018 | Depends on T012 + T016 |
| 5 | T019 | Depends on all |

---

## T012: Spell Effect Simulator

**File**: `scripts/spell_simulator.py` (NEW)
**Complexity**: L
**Dependencies**: None

### What to implement

1. **EffectParser class**: Parse card text using regex to extract effect types and parameters
   - Reuse L3 regex patterns from `v2_scoring_engine.py` (19 patterns)
   - Output: list of `(effect_type, params)` tuples

2. **EffectApplier class**: Apply effects to GameState copies
   - `apply_damage(state, target, amount)` — reduce HP, check death
   - `apply_heal(state, target, amount)` — increase HP up to max_health
   - `apply_draw(state, count)` — add random cards from remaining deck pool
   - `apply_summon(state, attack, health, position)` — add minion to board
   - `apply_buff(state, target, attack_delta, health_delta)` — modify minion stats
   - `apply_aoe(state, amount, side)` — damage all minions on one side
   - `apply_weapon(state, attack, durability)` — equip weapon
   - `apply_armor(state, amount)` — increase hero armor
   - `apply_destroy(state, target)` — remove minion regardless of HP
   - `apply_silence(state, target)` — clear keywords and enchantments

3. **resolve_effects(state, card)**: Main entry point
   - Parse card text → extract effects
   - For each effect, determine target (from action data or heuristic)
   - Apply all effects to state copy
   - Resolve deaths (remove dead minions, trigger deathrattles)
   - Return modified state

4. **Integration hook**: Modify `rhea_engine.py:apply_action()` to call `resolve_effects()` for SPELL type cards instead of just removing from hand

### Verification
- Unit tests: each effect type independently
- Test: Fireball (6 damage) reduces target HP by 6
- Test: AOE clears multiple minions
- Test: Buff increases minion attack/health
- Test: Draw adds cards to hand

---

## T013: Fix Double-Counting in Evaluator

**File**: `scripts/composite_evaluator.py` (MODIFY)
**Complexity**: S
**Dependencies**: None

### What to change

In `evaluate()` function (line ~85-86):
- **Remove** `board_v2 = sum(m.attack + m.health for m in state.board)` from `v2_adj`
- Keep `hand_v2 = sum(c.l6_score for c in state.hand)`
- Now `v2_adj = hand_v2` only (hand card quality)
- Board evaluation is handled entirely by `eval_board()` in submodel_evaluator

This eliminates the ~1.8× over-weighting of board stats.

### Verification
- Run existing integration tests — fitness values will change (lower magnitude) but scenarios should still PASS
- Verify minion stats contribute exactly once in evaluation chain

---

## T014: Fix Crossover Operator in RHEA

**File**: `scripts/rhea_engine.py` (MODIFY)
**Complexity**: M
**Dependencies**: None

### What to change

1. Replace `_crossover()` method (line ~263-280) with sequence-preserving n-point crossover:
   - Pick 1-2 crossover points
   - Swap contiguous subsequence between parents
   - Validate child chromosome (replay to check legality)
   - If illegal, fall back to cloning fitter parent

2. Add `_validate_chromosome(state, chromosome)` helper:
   - Replay chromosome from state
   - Return True if all actions are legal in sequence
   - Return False and last-legal-index if any action is illegal

3. Add adaptive mutation rate:
   - Track population diversity (std of fitnesses)
   - If diversity < 0.5 of target: double mutation rate
   - If diversity > 2.0 of target: halve mutation rate
   - Target diversity = 0.5 (configurable)

### Verification
- Run existing integration tests
- Add test: crossover of two valid chromosomes produces valid child
- Add test: mutation rate adapts when population converges

---

## T015: Multi-Objective Evaluator

**File**: `scripts/multi_objective_evaluator.py` (NEW)
**Complexity**: L
**Dependencies**: T013 (fixed evaluator as reference)

### What to implement

1. **EvaluatonResult dataclass**:
   ```python
   @dataclass
   class EvaluationResult:
       v_tempo: float      # Board control + mana efficiency + burst
       v_value: float      # Hand quality + resources + card advantage
       v_survival: float   # Hero safety + threat reduction
       
       def scalarize(self, turn_number: int) -> float:
           """Phase-adaptive scalarization"""
           if turn_number <= 4:    # Early
               return 1.2 * self.v_tempo + 0.8 * self.v_value + 0.6 * self.v_survival
           elif turn_number <= 7:  # Mid
               return 1.0 * self.v_tempo + 1.0 * self.v_value + 1.0 * self.v_survival
           else:                   # Late
               return 0.8 * self.v_tempo + 1.2 * self.v_value + 1.5 * self.v_survival
   ```

2. **eval_tempo(state)**:
   - board_control = Σ friendly minion value - Σ enemy minion threat
   - mana_efficiency = mana_spent_this_turn / mana_available
   - burst_potential = Σ(damage in hand) + Σ(attacking minion attack)
   - Return: board_control + mana_efficiency * 5 + burst_potential * 0.5

3. **eval_value(state)**:
   - hand_quality = Σ(c.l6_score for c in state.hand)
   - resource_gen = cards generated this turn
   - card_advantage = (hand_size + board_count) - (opp_hand_count + opp_board_count)
   - Return: hand_quality + resource_gen * 3 + card_advantage * 2

4. **eval_survival(state)**:
   - hero_safety = (hero.hp + hero.armor) / 30.0
   - threat_reduction = -Σ(enemy minion attack × urgency_weight)
   - lethal_defense = -50 if opponent has lethal on board
   - Return: hero_safety * 10 + threat_reduction + lethal_defense

5. **evaluate(state) → EvaluationResult**: Returns the 3-tuple
6. **evaluate_delta(before, after) → EvaluationResult**: Delta of two evaluations

### Verification
- Test: empty board → (0, hand_quality, hero_safety=1.0)
- Test: lethal threat detected → v_survival << 0
- Test: scalarization weights change with turn_number

---

## T016: Pareto Selector + RHEA Integration

**Files**: `scripts/multi_objective_evaluator.py` (ADD), `scripts/rhea_engine.py` (MODIFY)
**Complexity**: M
**Dependencies**: T015

### What to implement

1. **is_dominated(a, b)**: Returns True if EvaluationResult `a` is Pareto-dominated by `b`
   - a is dominated if b is >= a on ALL dimensions AND strictly > on at least one

2. **pareto_filter(results)**: Filter list of EvaluationResult to Pareto front
   - O(n²) pairwise comparison (n=50 population, fast enough)

3. **Modify RHEA fitness evaluation**:
   - Replace `evaluate_delta()` scalar with `evaluate_delta().scalarize(turn_number)`
   - Track EvaluationResult for each chromosome (not just scalar)
   - After search, return Pareto-optimal top actions

4. **Modify SearchResult**:
   - Add `pareto_front: List[EvaluationResult]` field
   - Decision presenter can show "this action is best for tempo, that one for survival"

### Verification
- Test: Pareto filter correctly identifies non-dominated set
- Test: Two actions with different tradeoffs both survive Pareto filter
- Run integration tests with new evaluator

---

## T017: Particle Filter Opponent Model

**File**: `scripts/bayesian_opponent.py` (MAJOR REFACTOR)
**Complexity**: L
**Dependencies**: None

### What to implement

1. **Particle dataclass**:
   ```python
   @dataclass
   class Particle:
       deck_id: str
       deck_cards: List[int]
       played_cards: Set[int]
       weight: float
       remaining_cards: List[int]  # computed property
   ```

2. **ParticleFilter class**:
   - `__init__(archetypes, K=10)`: Initialize K particles from HSReplay archetype data
   - `update(observed_card)`: Bayesian weight update for all particles
   - `resample()`: Systematic resampling when effective sample size < K/2
   - `get_confidence() -> float`: max weight across particles
   - `get_effective_sample_size() -> float`: 1 / Σ(w_k²)
   - `sample_opponent_hand(n_cards) -> List[int]`: Sample likely opponent hand from top particles
   - `predict_opponent_play(state) -> Action`: Predict opponent's best play using weighted particles

3. **Confidence gating logic**:
   - confidence > 0.60: use full particle-weighted opponent model
   - confidence > 0.30: use top-3 particles only
   - confidence <= 0.30: NO opponent model (return None)

4. **Backward compatibility**: Keep existing `OpponentModel` class interface, add ParticleFilter as new backend

### Verification
- Test: weights update correctly when opponent plays a card
- Test: resampling prevents degeneracy
- Test: confidence gating returns None at low confidence
- Test: top particle matches expected archetype after several observations

---

## T018: Multi-Turn Setup Planning

**File**: `scripts/rhea_engine.py` (MODIFY)
**Complexity**: M
**Dependencies**: T012 (spell sim) + T016 (pareto selector)

### What to implement

1. **Two-phase search in RHEAEngine.search()**:
   - Phase A: Current turn search (existing RHEA loop, with improved operators)
   - Phase B: Next-turn evaluation for top-3 Phase A results

2. **next_turn_lethal_check(state, particles)**:
   - Predict available mana next turn = min(current_max + 1, 10)
   - Calculate burst damage potential:
     - Direct damage spells in hand + predicted draw
     - Attacking minion damage
     - Weapon damage
   - If burst >= opponent HP + armor: return True

3. **Multi-turn fitness bonus**:
   - If next_turn_lethal_check returns True: add +5000 to fitness
   - This causes RHEA to prefer "set up lethal" over "maximize immediate value"

4. **Opponent response simulation** (when confidence-gated):
   - Sample opponent play from particle filter
   - Apply to state
   - Evaluate resulting state

5. **Time budget split**: 70% Phase A, 30% Phase B

### Verification
- Test: Engine finds 2-turn lethal setup over greedy immediate play
- Test: Time budget respected (Phase B doesn't exceed 30% of budget)
- Test: Lethal setup bonus only applied when actually achievable

---

## T019: Integration Tests + Validation

**File**: `scripts/test_integration.py` (MAJOR UPGRADE)
**Complexity**: M
**Dependencies**: All previous tasks

### What to implement

1. **Test Scenario: Spell Effects**
   - Hand: Fireball (6 damage), 4 mana
   - Opponent: minion with 5 HP
   - Expected: Engine plays Fireball to kill minion

2. **Test Scenario: Multi-Objective Trade-off**
   - Situation where tempo play (play minion) vs survival play (heal) conflict
   - Verify both options survive Pareto filter

3. **Test Scenario: Particle Filter Update**
   - Start with uniform weights
   - Opponent plays 3 cards from known archetype
   - Verify top particle matches expected archetype

4. **Test Scenario: Multi-Turn Lethal Setup**
   - Turn 7, opponent at 15 HP
   - Hand: 8-cost minion + direct damage spell (too expensive this turn)
   - Verify engine plays minion setup + saves spell for lethal next turn

5. **Test Scenario: Confidence Gating**
   - Start with no deck identification
   - Verify opponent model is NOT used (RHEA evaluates own actions only)
   - After enough observations, verify model activates

6. **Performance benchmarks**:
   - Full pipeline with all upgrades: < 3 seconds
   - Single evaluation (multi-objective): < 100 µs
   - Particle filter update: < 1 ms

### Verification
- All scenarios PASS
- Performance targets met
- Compare decision quality against V2 baseline on same scenarios

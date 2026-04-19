# V10 Scoring Implementation Plan

**Design doc**: `thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md`
**Date**: 2026-04-19
**Status**: Ready for execution

---

## Batch 1 — Static Tables (No Dependencies)

These two files are pure data with no imports from other new files.

### Task 1.1: keyword_interactions.py
- **File**: `hs_analysis/scorers/keyword_interactions.py`
- **Create**: `tests/test_keyword_interactions.py`
- **What**:
  - `INTERACTIONS: Dict[Tuple[str,str], float]` constant dict with 8 entries
  - `get_interaction_multiplier(card_keywords: List[str], target_keywords: List[str]) -> float`
    - Checks all keyword pairs, returns product of all applicable multipliers
    - Returns 1.0 if no interactions match
  - 8 pairs: (poisonous, divine_shield)→0.1, (stealth, taunt)→0.0 taunt, (immune, taunt)→0.0 taunt, (freeze, windfury)→0.5, (lifesteal, divine_shield_enemy)→0.0 heal, (reborn, deathrattle)→1.5, (brann, battlecry)→2.0, (rivendare, deathrattle)→2.0
- **Tests**: verify all 8 pairs, verify no-interaction returns 1.0, verify mixed interactions multiply correctly

### Task 1.2: mechanic_base_values.py
- **File**: `hs_analysis/scorers/mechanic_base_values.py`
- **Create**: `tests/test_mechanic_base_values.py`
- **What**:
  - `MECHANIC_FORMULAS` dict mapping mechanic name to formula function
  - `get_mechanic_base_value(mechanic: str, params: dict) -> float`
    - Returns 0.0 for unknown mechanics
  - 9 formulas:
    - imbue: `sum(base_hp * 0.8^(k-1) for k in range(1, max_level+1))`
    - herald: `soldier_value * (1 + jump(floor(count/2)))` where jump=0.5
    - shatter: `(half_value * 2) * merge_bonus` where merge_bonus=1.3
    - kindred: `base_value * match_probability`
    - rewind: `max(branch_a, branch_b)`
    - dark_gift: `avg(gift_values)` from list param
    - colossal: `(body_value + n * appendage_value) * space_penalty` where space_penalty=1.0 if board_size+n<=7 else 0.7
    - dormant: `awakened_value * survival_probability`
    - quest: `reward_value * completion_probability`
- **Tests**: verify each formula with sample params, verify unknown mechanic returns 0.0

---

## Batch 2 — SIV Module (Depends on Batch 1)

### Task 2.1: siv.py — skeleton + imports
- **File**: `hs_analysis/evaluators/siv.py`
- **What**: Create skeleton with `siv_score(card, state)` entry point, import V8ContextualScorer for CIV base, import keyword_interactions. All 8 modifiers start as `return 1.0` stubs.

### Task 2.2: siv.py — lethal_awareness modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `lethal_modifier(card, state)`:
  - Read `state.opponent.hero.hp + state.opponent.hero.armor`
  - If card is damage spell (check text for 造成/伤害), charge/rush minion, or weapon: apply `1 + (1 - enemy_total_hp/30)² × 3.0`
  - Return 1.0 for non-damage cards
- **Test**: boundary cases — 30hp enemy→1.0×, 1hp enemy→7.0×, non-damage card→1.0×

### Task 2.3: siv.py — taunt_constraint modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `taunt_modifier(card, state)`:
  - Count enemy taunts from `state.opponent.board`
  - Base: `1 + 0.3 × count`
  - Check card text/mechanics for silence (沉默) or destroy (消灭): +0.5
  - Check card mechanics for poisonous: +0.3
  - Return 1.0 if no enemy taunts
- **Test**: 0 taunts→1.0, 2 taunts→1.6, silence card vs taunts→2.1, no taunts→1.0

### Task 2.4: siv.py — curve/tempo_window modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `curve_modifier(card, state)`:
  - Read `state.mana.available`, `card.cost`, `state.turn_number`
  - On-curve (cost <= available): 1.0
  - 1 off: 0.9
  - Further: `0.8 - 0.05 × (cost - available - 1)`
  - Overflow penalty: `max(0, cost - turn - 1) × 0.1` subtracted
  - Floor at 0.5
- **Test**: exact mana→1.0, 1 over→0.9, 3 over→0.7, late game high cost→0.5+

### Task 2.5: siv.py — hand_position modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `position_modifier(card, state)`:
  - Find card index in `state.hand`
  - Outcast (外域): if index==0 or index==len(hand)-1 → 1 + OUTCAST_BONUS (0.3), else 1.0
  - Shatter (裂变): estimate merge probability based on hand size → 1 + prob × MERGE_BONUS (0.3)
  - Default: 1.0
- **Test**: outcast at edge→1.3, outcast in middle→1.0, regular card→1.0

### Task 2.6: siv.py — trigger_probability modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `trigger_modifier(card, state)`:
  - Check `card.mechanics` for BATTLECRY, DEATHRATTLE, END_OF_TURN
  - Check `state.board` for Brann (battlecry trigger), Rivendare (deathrattle trigger), Drakkari (EOT trigger)
  - Check for race aura on board matching card.race
  - Multipliers: Brann×2.0, Rivendare×2.0, Drakkari×2.0, aura×1.3
  - These multiply together
- **Test**: no triggers→1.0, Brann+battlecry→2.0, aura+deathrattle→1.3, Brann+Rivendare→4.0

### Task 2.7: siv.py — race_synergy modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `synergy_modifier(card, state)`:
  - Count same-race minions on board + same-race cards in hand
  - `1 + 0.1 × total_count`
  - Kindred bonus: if card has 延系 and last-turn race matches → extra bonus
- **Test**: no same race→1.0, 3 same race on board→1.3, 2 board + 2 hand→1.4

### Task 2.8: siv.py — progress_tracker modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `progress_modifier(card, state)`:
  - Imbue: read `state.hero` for imbue level (may not exist yet → return 1.0). Formula: `1 + 0.3 × (1 - 0.15 × level)`
  - Herald: read herald count from state. Threshold at 1→1.5, at 3→1.5, else 1.0
  - Quest: read quest progress. Formula: `1 + completion_pct² × 2.0`
  - Default: 1.0 if no progress mechanic matches
- **Test**: no progress mechanics→1.0, imbue level 0→1.3, imbue level 5→1.075, herald count 1→1.5

### Task 2.9: siv.py — counter_awareness modifier
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **What**: Implement `counter_modifier(card, state)`:
  - Freeze threat: if opponent class in freeze classes and card is key minion → -0.1
  - Secret threat: if opponent has secrets, penalize battlecry (-0.05) and high-attack minions (attack>=3 → -0.1)
  - AoE potential: if enemy board has AoE indicators, boost stealth cards (+0.2)
  - Default: 1.0
- **Test**: no threats→1.0, freeze class key minion→0.9, secrets+high attack→0.9, AoE+stealth→1.2

### Task 2.10: siv.py — integration + tests
- **File**: `hs_analysis/evaluators/siv.py` (modify)
- **Create**: `hs_analysis/evaluators/test_siv.py`
- **What**: Wire all 8 modifiers in `siv_score(card, state)`:
  - CIV = `contextual_score(card, state)` from V8 (or `card.v7_score` as fallback)
  - Multiply all 8 modifiers
  - Clamp to [0.01, 100.0]
  - Add `hand_siv_sum(state)` helper that sums SIV for all hand cards
- **Tests**: integration test with all modifiers active, test clamping, test V8 fallback

---

## Batch 3 — BSV Module (Depends on Batch 2)

### Task 3.1: bsv.py — skeleton + softmax
- **File**: `hs_analysis/evaluators/bsv.py`
- **Create**: `hs_analysis/evaluators/test_bsv.py`
- **What**:
  - `softmax(values: List[float], temperature: float) -> List[float]`
  - `PHASE_WEIGHTS` dict: early=(1.3,0.7,0.5), mid=(1.0,1.0,1.0), late=(0.7,1.2,1.5)
  - `ABSOLUTE_LETHAL_VALUE = 999.0`
  - `LETHAL_SCALE = 3.0`
- **Tests**: softmax correctness, phase weight selection by turn

### Task 3.2: bsv.py — tempo axis
- **File**: `hs_analysis/evaluators/bsv.py` (modify)
- **What**: `eval_tempo_v10(state)`:
  - Import `siv_score` from siv.py
  - `Σ siv_score(m_card, state)` for friendly minions on board (using minion.card or creating a Card-like wrapper)
  - Minus `Σ siv_score(e_card, state) × 1.2` for enemy minions
  - Plus `mana_efficiency × 5.0` where mana_efficiency = (mana_max - mana_available) / mana_max
  - Plus weapon attack value if weapon equipped
  - Note: Minion objects need to be wrapped for SIV — create a helper `_minion_to_card_like(minion)` that extracts card-like attributes

### Task 3.3: bsv.py — value axis
- **File**: `hs_analysis/evaluators/bsv.py` (modify)
- **What**: `eval_value_v10(state)`:
  - `Σ siv_score(card, state)` for all hand cards
  - Plus card_advantage × 2.0 where card_advantage = (hand_size + board_size) - (opp_hand + opp_board)
  - Plus resource_generation: len(state.cards_played_this_turn) × 1.5
  - Plus discover_pool_ev (from pool quality data if available)

### Task 3.4: bsv.py — survival axis
- **File**: `hs_analysis/evaluators/bsv.py` (modify)
- **What**: `eval_survival_v10(state)`:
  - Hero safety: `(hero.hp + hero.armor) / 30.0 × 10.0`
  - Minus enemy observable damage × 0.5
  - Minus lethal threat × 50.0 (if enemy total attack >= hero total health)
  - Plus healing potential × 0.3 (parse hand for heal cards)

### Task 3.5: bsv.py — fusion + lethal override
- **File**: `hs_analysis/evaluators/bsv.py` (modify)
- **What**: `bsv_fusion(state) -> float`:
  - Get 3 axes via eval_tempo_v10, eval_value_v10, eval_survival_v10
  - Select phase weights based on state.turn_number
  - Apply weights to raw axes
  - `weights = softmax(weighted_axes / 0.5)`
  - `BSV = Σ weights[i] × weighted_axes[i]`
  - Lethal override: import and call `check_lethal` from lethal_checker; if True → return 999.0
- **Tests**: verify softmax produces correct weights, verify lethal override, verify phase switching

---

## Batch 4 — Composite Integration (Depends on Batch 3)

### Task 4.1: composite.py — V10 integration
- **File**: `hs_analysis/evaluators/composite.py` (modify)
- **Create**: `hs_analysis/evaluators/test_composite_v10.py`
- **What**:
  - Add `V10_ENABLED = False` module-level flag
  - Add `evaluate_v10(state) -> float` that calls `bsv_fusion(state)`
  - Modify `evaluate()` to check `V10_ENABLED` and route to `evaluate_v10` if True
  - Keep all existing code paths untouched when V10_ENABLED=False
  - Add `set_v10_enabled(enabled: bool)` function
- **Tests**: verify V10_ENABLED=False gives same results as before, verify V10_ENABLED=True routes to bsv_fusion

---

## Batch 5 — Validation (Depends on Batch 4)

### Task 5.1: Regression test suite
- **What**: Run full pytest suite (233 tests). All must pass with V10_ENABLED=False.

### Task 5.2: A/B comparison test
- **Create**: `hs_analysis/evaluators/test_v10_ab_comparison.py`
- **What**:
  - Create sample GameState with known properties
  - Run evaluate() with V10_ENABLED=False → get legacy score
  - Run evaluate() with V10_ENABLED=True → get V10 score
  - Verify V10 score is different from legacy (not equal)
  - Verify V10 gives higher score to lethal-proximity state
  - Verify V10 gives higher score to synergized state
  - Clean up: set V10_ENABLED=False after test

### Task 5.3: Performance benchmark
- **Create**: `hs_analysis/evaluators/test_v10_performance.py`
- **What**:
  - Benchmark siv_score for a single card: assert <0.1ms per modifier
  - Benchmark bsv_fusion for a full state: assert <1ms total
  - Use time.perf_counter for measurement
  - Mark as @pytest.mark.slow or similar

### Task 5.4: Final commit
- **What**: Commit all new files with message `feat: V10 state-aware scoring (SIV + BSV + keyword interactions + mechanic base values)`

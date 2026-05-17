# V8 Contextual Expected Value — Implementation Plan

**Design**: `thoughts/shared/designs/2026-04-18-v8-contextual-ev-design.md`
**Date**: 2026-04-18

## Overview

V8 adds a contextual scoring layer on top of V7 static scores. Instead of `sum(c.v7_score)`, the evaluator calls `contextual_score(card, state)` which applies 7 modifiers based on game state.

**New files**: 4 (2 generators, 1 core module, 1 scorer test)
**Modified files**: 3 (composite_evaluator.py, multi_objective_evaluator.py, test_integration.py)
**Generated data**: 2 (pool_quality_report.json, rewind_delta_report.json)

---

## Batch 1: Offline Data Generators (2 tasks, parallel)

### Task 1.1: Pool Quality Generator

**Create**: `scripts/pool_quality_generator.py`
**Create**: `scripts/test_pool_quality_generator.py`

**pool_quality_generator.py** — reads unified_standard.json + v7_scoring_report.json, outputs pool_quality_report.json.

Key logic:
- Load unified_standard.json (1015 cards)
- Load v7_scoring_report.json for scores
- Build pools by filtering on `race` field and `type` field and `cardClass` field
- Race pools: 龙, 恶魔, 野兽, 鱼人, 海盗, 元素, 亡灵, 图腾, 机械, 纳迦, 德莱尼
- Spell school pools: 火焰, 冰霜, 奥术, 自然, 暗影, 神圣, 邪能
- Type pools: MINION, SPELL, WEAPON
- For each pool compute: avg_v7, top_10_pct_v7, pool_size, quality_std
- Output to `hs_cards/pool_quality_report.json`
- Also load HSReplay avg_turns from hsreplay_cache.db → output as `hs_cards/card_turn_data.json` (dbfId → {optimal_turn, confidence})

**test_pool_quality_generator.py** — 8 tests:
- Pool sizes are positive integers
- Dragon pool avg_v7 is a float > 0
- Unknown pool returns empty/zero defaults
- top_10_pct > avg (for pools > 5 cards)
- Output JSON is valid and parseable
- avg_turns lookup works for known cards
- avg_turns fallback for unknown cards
- Re-running is idempotent

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python scripts/pool_quality_generator.py && python -m pytest scripts/test_pool_quality_generator.py -v`

### Task 1.2: Rewind Delta Generator

**Create**: `scripts/rewind_delta_generator.py`
**Create**: `scripts/test_rewind_delta_generator.py`

**rewind_delta_generator.py** — identifies rewind cards, computes delta vs original.

Key logic:
- Load unified_standard.json
- Find all cards with "回溯" in text
- For each rewind card: try to find the "original" version (same name without 回溯 keyword, or text analysis)
- Load v7_scoring_report.json for both versions' scores
- Compute delta = rewind_v7 - original_v7
- Output to `hs_cards/rewind_delta_report.json`: {dbfId: {name, original_dbfId, original_v7, rewind_v7, delta}}
- If original cannot be found, set delta = 0.0 and flag as "unpaired"

**test_rewind_delta_generator.py** — 6 tests:
- Finds rewind cards (count > 0)
- Output JSON structure is valid
- Paired cards have non-zero delta
- Unpaired cards have delta = 0.0
- Empty input produces empty output
- Re-running is idempotent

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python scripts/rewind_delta_generator.py && python -m pytest scripts/test_rewind_delta_generator.py -v`

---

## Batch 2: Core V8 Module (1 task)

### Task 2.1: V8 Contextual Scorer

**Create**: `scripts/v8_contextual_scorer.py`
**Create**: `scripts/test_v8_contextual_scorer.py`

**v8_contextual_scorer.py** — Main module with `contextual_score(card, state)` function.

Dependencies: Batch 1 output files (pool_quality_report.json, rewind_delta_report.json, card_turn_data.json)

Module structure:

```
class V8ContextualScorer:
    def __init__(self):
        # Load pool_quality_report.json
        # Load rewind_delta_report.json
        # Load card_turn_data.json
        # Fallback: if files missing, use defaults (graceful degradation)
    
    def contextual_score(self, card, state) -> float:
        base = card.v7_score
        result = base
        result *= self._turn_factor(card, state)       # Component 1
        result *= self._type_factor(card, state)        # Component 2
        result += self._pool_ev_bonus(card)             # Component 3
        result += self._deathrattle_ev_bonus(card, state) # Component 4
        result *= self._lethal_boost(card, state)       # Component 5
        result += self._rewind_ev_delta(card, state)    # Component 6
        return result
    
    def hand_contextual_value(self, state) -> float:
        base_sum = sum(self.contextual_score(c, state) for c in state.hand)
        synergy = self._synergy_bonus(state)            # Component 7
        return base_sum + synergy
    
    # --- Component 1: Turn Curve Adjuster ---
    def _turn_factor(self, card, state) -> float:
        # Get optimal turn from card_turn_data or fallback cost+1
        # Compute |current_turn - optimal_turn|
        # Apply decay: 1.0 - 0.08 * delta, clamped to [0.5, 1.2]
    
    # --- Component 2: Type Context Modifier ---
    def _type_factor(self, card, state) -> float:
        # Phase: early(1-4), mid(5-7), late(8+)
        # Base type factor from phase×type table
        # Board saturation modifier for minions
        # AOE value modifier for spells when opponent board is strong
    
    # --- Component 3: Pool Quality Assessor ---
    def _pool_ev_bonus(self, card) -> float:
        # Check card.text for discover/random patterns
        # Match to pool name (race, school, type)
        # Look up pool_quality_report for avg and top_10_pct
        # Return weighted EV bonus
    
    # --- Component 4: Deathrattle EV Resolver ---
    def _deathrattle_ev_bonus(self, card, state) -> float:
        # If card.text contains "亡语"
        # Parse specific deathrattle patterns (summon N/N, damage N, draw N, equip)
        # Trigger probability based on board state
        # Return parsed EV bonus, or fallback to L5 fixed model
    
    # --- Component 5: Lethal-Aware Booster ---
    def _lethal_boost(self, card, state) -> float:
        # Compute lethal_gap = opp_hp + opp_armor - total_attack
        # Check if card is damage-type (text has 造成/消灭 or type=WEAPON)
        # Apply boost table based on lethal_gap and damage_type
        # Return multiplier (0.8 ~ 1.5)
    
    # --- Component 6: Rewind Decision Maker ---
    def _rewind_ev_delta(self, card, state) -> float:
        # If card.text contains "回溯"
        # Look up rewind_delta_report for delta
        # If state has board pressure (opponent attack high), reduce delta
        # Return delta
    
    # --- Component 7: Combo Synergy Detector ---
    def _synergy_bonus(self, state) -> float:
        # Count races in hand
        # If 3+ same race, bonus per card
        # Check spell + spell-trigger combos
        # Check buff + high-attack minion combos
        # Check curve completeness
        # Return total synergy bonus
```

**Graceful degradation**:
- If pool_quality_report.json missing: all pool_ev_bonus returns 0
- If rewind_delta_report.json missing: all rewind_ev_delta returns 0
- If card_turn_data.json missing: use fallback optimal_turn = cost + 1
- Module-level `get_scorer()` function returns singleton (lazy init)

**test_v8_contextual_scorer.py** — 15 tests:
- Pure V7 fallback when no V8 data files exist
- Turn factor: same card at turn 3 vs turn 8 gives different values
- Turn factor: clamped to [0.5, 1.2]
- Type factor: minion valued higher early, spell higher late
- Type factor: board saturation reduces minion factor
- Pool EV: discover dragon card gets bonus when pool_quality exists
- Pool EV: non-discover card gets zero pool bonus
- Deathrattle: "亡语：召唤 3/3" parsed correctly
- Deathrattle: non-deathrattle card gets zero bonus
- Lethal boost: damage card boosted when opponent low HP
- Lethal boost: non-damage card not boosted
- Lethal boost: no boost when opponent full HP
- Rewind: rewind card with positive delta gets bonus
- Synergy: 3+ same race cards in hand trigger bonus
- Synergy: no synergy with diverse hand
- Integration: contextual_score != raw v7_score for a real card+state

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python -m pytest scripts/test_v8_contextual_scorer.py -v`

---

## Batch 3: Integration (3 tasks, parallel)

### Task 3.1: Modify composite_evaluator.py

**Modify**: `scripts/composite_evaluator.py`

Changes:
1. Add import: `from v8_contextual_scorer import get_scorer`
2. In `evaluate()` (around line 105): Replace `hand_v2 = sum(c.v7_score for c in state.hand)` with `v8_scorer = get_scorer(); hand_v7 = v8_scorer.hand_contextual_value(state)`
3. In `quick_eval()` (around line 139): Replace `v2_adj = sum(c.v7_score for c in state.hand)` with `v8_scorer = get_scorer(); v2_adj = v8_scorer.hand_contextual_value(state)`
4. Update variable names: `hand_v2` → `hand_v7`, `v2_adj` → `v7_adj` (semantic clarity)
5. Weight key already renamed to `w_v7` from previous V7 integration
6. Keep self-test at bottom working

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python scripts/composite_evaluator.py`

### Task 3.2: Modify multi_objective_evaluator.py

**Modify**: `scripts/multi_objective_evaluator.py`

Changes:
1. Add import: `from v8_contextual_scorer import get_scorer`
2. In `eval_value()` (around line 95): Replace `hand_quality = sum(getattr(c, "v7_score", 0.0) for c in state.hand)` with `v8_scorer = get_scorer(); hand_quality = v8_scorer.hand_contextual_value(state)`
3. Keep demo data at bottom working
4. Keep all existing tests passing

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python scripts/multi_objective_evaluator.py`

### Task 3.3: Update test_integration.py

**Modify**: `scripts/test_integration.py`

Changes:
1. Ensure all test cards have v7_score set (already done in V7 integration)
2. Tests should still pass with V8 active — V8 is additive and degrades gracefully
3. If any test asserts specific numeric scores, they may need tolerance adjustment since V8 modifies the values
4. Add 2-3 new test cases specifically testing V8 contextual behavior:
   - Test that RHEA search works end-to-end with V8 scorer
   - Test that V8 scorer is used (mock it and verify it's called)
   - Test graceful degradation when V8 data files are missing

**Verify**: `cd /Users/ganjie/code/personal/hs_analysis && python -m pytest scripts/test_integration.py -v`

---

## Batch 4: End-to-End Verification (1 task)

### Task 4.1: Run All Tests

Run all test suites in sequence:
1. `python scripts/test_pool_quality_generator.py -v` or `python -m pytest scripts/test_pool_quality_generator.py -v`
2. `python scripts/test_rewind_delta_generator.py -v` or `python -m pytest scripts/test_rewind_delta_generator.py -v`
3. `python -m pytest scripts/test_v8_contextual_scorer.py -v`
4. `python scripts/composite_evaluator.py` (self-test)
5. `python scripts/multi_objective_evaluator.py` (self-test)
6. `python -m pytest scripts/test_integration.py -v`
7. `python scripts/rhea_engine.py` (sanity check)

All must pass with exit code 0.

---

## Summary

| Batch | Tasks | Parallelism | New Files | Modified Files |
|-------|-------|-------------|-----------|----------------|
| 1 | 1.1 + 1.2 | 2 parallel | pool_quality_generator.py, test_pool_quality_generator.py, rewind_delta_generator.py, test_rewind_delta_generator.py | — |
| 2 | 2.1 | 1 | v8_contextual_scorer.py, test_v8_contextual_scorer.py | — |
| 3 | 3.1 + 3.2 + 3.3 | 3 parallel | — | composite_evaluator.py, multi_objective_evaluator.py, test_integration.py |
| 4 | 4.1 | Sequential verification | — | — |

**Total**: 7 micro-tasks, 4 batches, ~8 new files, 3 modified files, ~600-800 lines new code

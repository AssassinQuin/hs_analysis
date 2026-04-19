---
version: 1.0
created: 2026-04-19
last_changed: 2026-04-19
---

# Project State: hs_analysis

> Single source of truth for progress. Update after each significant change.

## Current Phase: V9 Decision Engine + Data Completion

## ✅ DONE

### Data Infrastructure
- [x] Multi-source data pipeline (HearthstoneJSON + iyingdi + HSReplay)
- [x] 984+ standard cards in unified_standard.json
- [x] CardIndex with O(1) multi-dimensional lookup
- [x] Card cleaner: race/mechanic/school normalization (56 keywords)
- [x] Card data model (dataclass) with full type hints

### Scoring Engines
- [x] V2: Power-law curve fitting (MAE 0.66, 70% improvement over V1)
- [x] V7: Data-driven scoring with HSReplay Rankings calibration
- [x] V8: 7 contextual correction factors (turn curve, type context, pool quality, etc.)
- [x] L6: Real-world composite scoring

### Search & Decision
- [x] RHEA evolutionary search engine
- [x] Lethal checker (DFS-based)
- [x] Game state management (GameState, HeroState)
- [x] Action normalization (including crossover fix)
- [x] Risk assessor
- [x] Opponent simulator
- [x] Bayesian opponent modeling
- [x] Spell simulator
- [x] Score provider with lazy loading + cache

### Test Coverage
- [x] 189 tests, 189 passing
- [x] test_card_cleaner.py (51 tests)
- [x] test_card_index.py (35 tests)
- [x] test_score_provider.py (11 tests)
- [x] test_v8_contextual_scorer.py (16 tests)
- [x] test_wild_dedup.py (6 tests)
- [x] test_pool_quality_generator.py (8 tests)
- [x] test_rewind_delta_generator.py (6 tests)
- [x] test_action_normalize.py (10 tests)
- [x] test_game_state.py (16 tests)
- [x] Internal module tests in hs_analysis/search/ (73 tests total)
- [x] V9 HDT batch01 integration tests (10 tests)
- [x] V9 HDT batch02 deck-based random tests (10 tests, real parsed decks)
- [x] V9 HDT batch03 engine path tests (10 tests: hero power, windfury, armor, secrets, poisonous, hero card, overload, boundaries)
- [x] V9 HDT batch04 spell sim + engine tests (10 tests: spell damage, AoE, draw, summon, death cleanup, opponent sim, next-turn lethal, Pareto front, risk eval, armor/heal)

### Wild Pool Data
- [x] Wild format card fetch from iyingdi API (6174 cards total, 5209 wild-only)
- [x] Wild database built (unified_wild.json, deduplicated against standard pool)
- [x] Race-based pool quality metrics (11 race pools + 3 type pools = 14 total)
- [x] Fixed test_dragon_pool_avg_v7 (Chinese→English race name mismatch)
- [x] fetch_wild.py enhanced with wild=True parameter support

## 🔄 WIP

### V9 Decision Engine v2
- [ ] Cascading pipeline: lethal → enhanced RHEA → opponent sim → risk assess → select
- [ ] Integration tests for full pipeline
- Design: thoughts/shared/designs/2026-04-19-v9-decision-engine-v2-design.md

## ⏳ TODO (by priority)

### P1: V9 Pipeline
- [ ] Complete V9 cascading decision pipeline
- [ ] Integration tests for end-to-end decision flow

### P2: Polish
- [ ] Wild format support in scoring engines
- [ ] Performance benchmarking (75ms target for RHEA)
- [ ] HSReplay archetype integration

## 🚫 BLOCKED
(none currently)

## Data Inventory

| File | Description | Size |
|------|-------------|------|
| hs_cards/unified_standard.json | Cleaned standard pool | 984+ cards |
| hs_cards/hsjson_standard.json | HSJSON raw data | ~1000 cards |
| hs_cards/iyingdi_standard_raw.json | iyingdi raw (standard) | ~900 cards |
| hs_cards/v7_scoring_report.json | V7 scores | all standard |
| hs_cards/v2_scoring_report.json | V2 scores | all standard |
| hs_cards/l6_scoring_report.json | L6 scores | all standard |
| hs_cards/pool_quality_report.json | Pool quality metrics | 3 type pools |
| hs_cards/card_turn_data.json | Avg turn data | from HSReplay |
| hs_cards/rewind_delta_report.json | V7 rewind deltas | generated |
| hs_cards/v2_curve_params.json | V2 curve parameters | fitted |
| hs_cards/v2_keyword_params.json | V2 keyword parameters | calibrated |
| hs_cards/hsreplay_cache.db | HSReplay SQLite cache | cached |
| hs_cards/iyingdi_all_raw.json | iyingdi raw (all cards) | 6174 cards |
| hs_cards/iyingdi_all_normalized.json | iyingdi normalized (all cards) | 6174 cards |
| hs_cards/unified_wild.json | Cleaned wild-only pool | 5209 cards |

## Active Designs
- thoughts/shared/designs/2026-04-19-v9-decision-engine-v2-design.md
- thoughts/shared/designs/2026-04-19-card-index-and-cleanup-design.md
- thoughts/shared/designs/2026-04-19-package-restructure-design.md
- thoughts/shared/designs/2026-04-19-project-state-tracking-design.md

## Next Actions
1. Complete V9 decision engine pipeline
2. Integration tests for cascading pipeline
3. Wild format support in V7/V8 scoring engines

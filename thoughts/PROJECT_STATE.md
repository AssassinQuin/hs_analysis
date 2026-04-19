---
version: 1.0
created: 2026-04-19
last_changed: 2026-04-19 (batch14 complex real-deck scenario tests)
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
- [x] 352 tests, 351 passing (1 known flaky stochastic test in batch01: test_02_dh_weapon_trade)
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
- [x] V9 HDT batch05 edge-case + complex board tests (10 tests)
- [x] V9 HDT batch06 real deck data-driven tests (10 tests: quest+discover, weapon-attack sequence, RUSH propagation, taunt defense, stealth behavior, deathrattle play, outcast, 0-cost chain, complex late-game)
- [x] V9 HDT batch07 advanced combat + multi-system tests (10 tests: lethal paths, death chains, mana boundaries, taunt-through-lethal, spell destroy/armor, engine edge cases)
- [x] V9 HDT batch08 position-awareness tests (10 tests: summon rightmost, OUTCAST positions, generated card rightmost, taunt multi-minion, board reindexing, heal no-cap, complex multi-mechanic, hand order)
- [x] V9 HDT batch09 position strategy tests (10 tests: PLAY position variants, insert leftmost/between/rightmost, death cleanup reindex, deathrattle inheritance gap, engine position search, full board boundary, multi-death reindex chain)
- [x] V9 HDT batch10 advanced scenario tests (10 tests: weapon replacement, overload gap, fatigue gap, stealth targeting gap, poisonous gap, windfury gap, Hunter deck T5, Warlock deck T6, risk AoE, lethal-through-taunt)
- [x] V9 HDT batch11 complex real-game scenario tests (10 tests: T4 lethal push, T5 discover resource mgmt, T7 druid ramp, T8 AoE decision, T3 DH tempo, T6 stealth combo, T9 full board 7v7, T7 near-death defense, T6 discover+draw chain, T12 fatigue endgame)
- [x] V9 HDT batch12 complex real-game scenario tests round 2 (10 tests: T6 board recovery after wipe, T5 weapon durability mgmt, T4 divine shield trade, T6 mana squeeze, T7 lethal threat risk, T8 multi-spell combo, T5 taunt placement, T15 resource exhaustion, T7 draw+discover chain, T6 Pareto tempo vs value)
- [x] V9 HDT batch13 complex real-game scenario tests round 3 (10 tests: T10 max actions, T7 cascading deaths, T8 lethal 5 sources, T9 weapon break mid combo, T6 fatigue boundary, T7 taunt death unlocks face, chromosome normalization, T8 opponent sim worst case, T5 spell buff chain, T9 multi-objective conflict)
- [x] V9 HDT batch14 complex real-deck scenario tests (10 tests: Hunter T3 aggro push, Warlock Quest T5 discover chain, Warlock Dragon T8 charge finisher, DH T4 weapon+rush tempo, Druid T7 ramp big turn, Rogue-style Warlock T6 stealth+weapon, full 7v7 late-game T9, near-death taunt save T6, Hunter T4 deathrattle+rush combo, Druid T5 innervate big play)

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

### P1.5: Position-Based Mechanics (位置机制)
- [ ] Hand position tracking (slot index per card) — required for OUTCAST
- [ ] OUTCAST (流放) mechanic — bonus when played from leftmost/rightmost hand position
- [ ] Generated card rightmost placement — explicit position-aware card insertion
- [ ] Board position index on Minion — support adjacency queries
- [ ] Board adjacency barriers — dormant minions / locations block attack paths
- [ ] Adjacency buffs — "相邻的随从" only affects immediate board neighbors
- [ ] Position-aware buff targeting — leftmost/rightmost/adjacent selectors
- [ ] Summon positioning: ✅ already correct (append = rightmost)

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

---
version: 3.0
created: 2026-04-19
last_changed: 2026-04-19 (Complete game rules + V10 scoring design)
---

# Project State: hs_analysis

> Single source of truth for progress. Update after each significant change.

## Current Phase: V10 Engine Overhaul + Scoring Framework Redesign

## ✅ DONE

### Data Infrastructure
- [x] Multi-source data pipeline (HearthstoneJSON + iyingdi + HSReplay)
- [x] 1015 standard cards in unified_standard.json (2026 Year of the Scarab)
- [x] CardIndex with O(1) multi-dimensional lookup
- [x] Card cleaner: race/mechanic/school normalization (56 keywords)
- [x] Card data model (dataclass) with full type hints

### Scoring Engines
- [x] V2: Power-law curve fitting (MAE 0.66, 70% improvement over V1)
- [x] V7: Data-driven scoring with HSReplay Rankings calibration
- [x] V8: 7 contextual correction factors (turn curve, type context, pool quality, etc.)
- [x] L6: Real-world composite scoring

### Search & Decision (V9)
- [x] RHEA evolutionary search engine
- [x] Lethal checker (DFS-based)
- [x] Game state management (GameState, HeroState)
- [x] Action normalization (including crossover fix)
- [x] Risk assessor
- [x] Opponent simulator
- [x] Bayesian opponent modeling
- [x] Spell simulator
- [x] Score provider with lazy loading + cache

### V10 Phase 1: Foundation Fixes ✅ (2026-04-19)
- [x] Lethal checker: charge minions now respect taunt (charge-vs-taunt bug fix)
- [x] Windfury second attack: `has_attacked_once` flag enables double attack
- [x] Overload parsing + application: regex parse on PLAY, apply on END_TURN
- [x] Poisonous instant kill: target.health = 0 when attacker has poisonous
- [x] Combo tracking: `cards_played_this_turn` list populated by apply_action
- [x] Fatigue damage: incrementing counter on empty deck draw
- [x] Stealth break on attack: clears `has_stealth` when minion attacks
- [x] Freeze effect: `frozen_until_next_turn` flag skips attack enumeration
- [x] game_state.py: added `has_attacked_once`, `frozen_until_next_turn` to Minion
- [x] rhea_engine.py: all 6 mechanic fixes integrated into apply_action + enumerate
- [x] lethal_checker.py: removed charge-bypasses-taunt block
- **Design doc:** `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-19-v10-phase1-foundation-fixes.md`
- **Commit:** `3d1a409`

### Complete Game Rules Reference ✅ (2026-04-19)
- [x] 10章61节完整规则文档 (1017行)
- [x] 覆盖：游戏区域、法力系统、战斗系统、关键词机制、触发/光环、奥秘、英雄技能、抽牌/疲劳、2026特殊机制、阶段解析
- [x] 研究来源：wiki.gg Advanced Rulebook、Blizzard补丁说明、outof.games
- **文档：** `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md`
- **Commit:** `c76e902`

### V10 Scoring Framework Design ✅ (2026-04-19)
- [x] 诊断当前模型3个根本缺陷：线性叠加、静态vs动态脱节、规则脱节
- [x] 设计三层状态感知评分架构：CIV(基础层) + SIV(交互层) + BSV(全局层)
- [x] 8个状态修正器：斩杀感知、嘲讽约束、节奏窗口、手牌位置、触发概率、种族协同、累积进度、对手反制
- [x] 关键词交互价值表（从规则文档推导）
- [x] 2026机制基础价值公式（灌注递增、兆示阈值跳跃、裂变合并等）
- [x] 非线性融合替代线性加权（softmax + 温度参数）
- **文档：** `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`

### Test Coverage
- [x] 233 tests passing (213 existing + 20 new batch16, zero regressions)
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
- [x] V9 HDT batch01–batch15 integration tests (150 tests)
- [x] V10 HDT batch16 mechanic tests (20 tests)

### Wild Pool Data
- [x] Wild format card fetch from iyingdi API (6174 cards total, 5209 wild-only)
- [x] Wild database built (unified_wild.json, deduplicated against standard pool)
- [x] Race-based pool quality metrics (11 race pools + 3 type pools = 14 total)

### 2026 Environment Research
- [x] 4 expansions analyzed: Emerald Dream, Un'Goro, Timeways, CATACLYSM
- [x] 37 unique mechanic keywords catalogued from 1015 cards
- [x] New 2026 mechanics documented: Imbue, Herald, Shatter, Kindred, Rewind, Fabled, Colossal, Dark Gift, Hand Targeting, Location
- [x] Engine gap analysis: P0 (enchantments, deathrattle, battlecry), P1 (combo, overload, windfury), 2026 gaps

## 🔄 WIP

### V10 Engine Phase 2: Enchantment Framework + Trigger System
- [ ] Enchantment data model (`Enchantment` dataclass with deltas, keywords, triggers)
- [ ] Trigger dispatcher (on_minion_played, on_minion_dies, on_turn_end, on_attack, on_spell_cast)
- [ ] Battlecry dispatcher (parse card text → apply effect on play)
- [ ] Deathrattle queue (collect + execute in board-position order)
- [ ] Aura engine (continuous enchantments that recompute after state changes)
- [ ] Discover framework (generate 3 options, evaluate each, pick best)
- [ ] Location card support (new card type with durability/cooldown)
- **Design:** Phase 2 section in `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### V10 Scoring Phase: State-Aware Scoring Implementation
- [ ] SIV module (8 state modifiers in `evaluators/siv.py`)
- [ ] BSV module (non-linear fusion in `evaluators/bsv.py`)
- [ ] Keyword interaction table (`scorers/keyword_interactions.py`)
- [ ] 2026 mechanic base values (`scorers/mechanic_base_values.py`)
- [ ] Integration into composite.py
- **Design:** `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`

## ⏳ TODO (by priority)

### P1: V10 Engine Phase 2 — Enchantment Framework
- [ ] Enchantment dataclass with attack/health/keyword deltas and trigger_type
- [ ] Computed stats on Minion (base + enchantment deltas)
- [ ] TriggerDispatcher class with event hooks
- [ ] Battlecry text parser + effect dispatch
- [ ] Deathrattle queue with cascade (max 5 depth)
- [ ] Aura recomputation engine
- [ ] Discover pool generation + option evaluation
- [ ] Location card type support
- [ ] ~40 new tests (batch17–batch20)

### P1: V10 Scoring — SIV + BSV Implementation
- [ ] Keyword interaction value table (derived from rules doc)
- [ ] 2026 mechanic CIV base values (Imbue, Herald, Shatter, etc.)
- [ ] 8 SIV state modifiers (lethal, taunt, curve, position, trigger, synergy, progress, counter)
- [ ] Non-linear BSV fusion (softmax + temperature)
- [ ] Lethal detection module (integrate lethal_checker into BSV)
- [ ] ~55 new tests (basic + interaction + global layers)

### P2: V10 Engine Phase 3 — 2026 Modern Mechanics
- [ ] Imbue hero power upgrade system (per-class upgrade paths)
- [ ] Hand position system (index-aware hand, Shatter split/merge, Outcast, Hand Targeting)
- [ ] Herald progressive counter + Colossal appendage summoning
- [ ] Kindred previous-turn race/school tracking
- [ ] Quest progress tracking with reward
- [ ] Dark Gift pool (10 random bonuses for Discover)
- [ ] Rewind branching simulation
- [ ] ~40 new tests (batch21–batch24)

### P3: Polish
- [ ] Wild format support in scoring engines
- [ ] Performance benchmarking (75ms target for RHEA)
- [ ] HSReplay archetype integration
- [ ] Risk assessor: add DH, DK, Rogue, Shaman, Warrior class AoE thresholds
- [ ] Opponent simulator: consider hand size, hero power, windfury, divine shield

## 🚫 BLOCKED
(none currently)

## Architecture Decisions (see DECISIONS.md for full details)
- D009: Three-phase layered overhaul (not full rewrite)
- D010: Enchantment framework as the key domino for all trigger-based mechanics
- D011: Regex + manual dispatch for effect parsing (not ML)
- D012: Graceful degradation — unknown effects → vanilla behavior, never crash
- D014: Three-layer state-aware scoring (CIV + SIV + BSV, not pure ML or MC simulation)
- D015: Non-linear value fusion via softmax (not linear weighted sum)
- D016: Rule-derived keyword interaction table (not empirical constants)

## Data Inventory

| File | Description | Size |
|------|-------------|------|
| hs_cards/unified_standard.json | Cleaned standard pool | 1015 cards |
| hs_cards/hsjson_standard.json | HSJSON raw data | ~1015 cards |
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
- thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md ⭐ (engine)
- thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md ⭐ (scoring)
- thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md ⭐ (reference)
- thoughts/shared/designs/2026-04-19-v9-decision-engine-v2-design.md
- thoughts/shared/designs/2026-04-19-card-index-and-cleanup-design.md
- thoughts/shared/designs/2026-04-19-package-restructure-design.md
- thoughts/shared/designs/2026-04-19-project-state-tracking-design.md

## Next Actions
1. Execute V10 Engine Phase 2: Enchantment framework + trigger system
2. Execute V10 Scoring: SIV + BSV implementation
3. Execute V10 Engine Phase 3: 2026 modern mechanics
4. Performance benchmarking and polish

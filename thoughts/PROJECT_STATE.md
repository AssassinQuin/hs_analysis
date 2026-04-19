---
version: 4.0
created: 2026-04-19
last_changed: 2026-04-19 (V10 scoring implementation complete)
---

# Project State: hs_analysis

> Single source of truth for progress. Update after each significant change.

## Current Phase: V10 Engine Overhaul — Phase 2 (Enchantment Framework) Next

## ✅ DONE

### Data Infrastructure
- [x] Multi-source data pipeline (HearthstoneJSON + iyingdi + HSReplay)
- [x] 1015 standard cards in unified_standard.json (2026 Year of the Scarab)
- [x] CardIndex with O(1) multi-dimensional lookup
- [x] Card cleaner: race/mechanic/school normalization (56 keywords)
- [x] Card data model (dataclass) with full type hints
- [x] Wild format: 6174 cards fetched, 5209 wild-only after dedup

### Scoring Engines (Offline Pipeline)
- [x] V2: Power-law curve fitting (MAE 0.66, 70% improvement over V1)
- [x] V7: Data-driven scoring with HSReplay Rankings calibration
- [x] V8: 7 contextual correction factors (turn curve, type context, pool quality, etc.)
- [x] L6: Real-world composite scoring (V2 × (1-θ) + CPI × θ)

### Search & Decision (V9)
- [x] RHEA evolutionary search engine
- [x] Lethal checker (DFS-based)
- [x] Game state management (GameState, HeroState, Minion, ManaState)
- [x] Action normalization (including crossover fix)
- [x] Risk assessor (AoE vulnerability, overextension, secret threat)
- [x] Opponent simulator (greedy model)
- [x] Bayesian opponent modeling
- [x] Spell simulator (10 regex patterns)
- [x] Score provider with lazy loading + cache

### V10 Phase 1: Foundation Fixes ✅ (2026-04-19, commit `3d1a409`)
- [x] Lethal checker: charge minions now respect taunt
- [x] Windfury second attack: `has_attacked_once` flag
- [x] Overload parsing + application
- [x] Poisonous instant kill
- [x] Combo tracking: `cards_played_this_turn`
- [x] Fatigue damage: incrementing counter
- [x] Stealth break on attack
- [x] Freeze effect: `frozen_until_next_turn`
- **Design:** `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### Complete Game Rules Reference ✅ (2026-04-19, commit `c76e902`)
- [x] 10章61节完整规则文档 (1017行)
- [x] Sources: wiki.gg, Blizzard patch notes, outof.games
- **Doc:** `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md`

### V10 State-Aware Scoring ✅ (2026-04-19, commit `a1b3221`)
- [x] **SIV module** (`evaluators/siv.py`): 8 state modifiers
  - Lethal awareness: `1 + (1-hp/30)² × 3.0`
  - Taunt constraint: `1 + 0.3 × count(enemy_taunts)`
  - Tempo window: curve matching penalty
  - Hand position: Outcast/Shatter position bonus
  - Trigger probability: Brann/Rivendare/aura multipliers
  - Race synergy: same-race count × 0.1
  - Progress tracker: Imbue/Herald/Quest threshold jumps
  - Counter awareness: freeze/secret/AoE threat adjustments
- [x] **BSV module** (`evaluators/bsv.py`): Non-linear 3-axis fusion
  - Tempo axis: Σ SIV(friendly) - Σ SIV(enemy) + mana efficiency
  - Value axis: Σ SIV(hand) + card advantage + resource generation
  - Survival axis: hero safety - threats - lethal exposure
  - Softmax fusion with temperature=0.5
  - Phase weights: early(1.3,0.7,0.5) / mid(1.0,1.0,1.0) / late(0.7,1.2,1.5)
  - Lethal override: BSV = 999.0 when lethal possible
- [x] **Keyword interactions** (`scorers/keyword_interactions.py`): 8 rule-derived pairs
- [x] **2026 mechanic base values** (`scorers/mechanic_base_values.py`): 9 formulas
- [x] **Composite integration** (`evaluators/composite.py`): V10_ENABLED flag + evaluate_v10()
- [x] **260 new tests**, 493 total, zero regressions
- **Design:** `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`
- **Design (impl):** `thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-19-v10-scoring-implementation.md`

### Test Coverage
- [x] **493 tests passing** (as of 2026-04-19)
- [x] Card data tests: 51+35+6 = 92
- [x] V8 contextual scorer: 16
- [x] V9 search engine + HDT batches: 150+
- [x] V10 Phase 1 mechanic tests: 20
- [x] V10 scoring (SIV+BSV+interactions+mechanics+integration): 260

### Architecture & Research Documentation
- [x] 7 design documents in `thoughts/shared/designs/`
- [x] 4 implementation plans in `thoughts/shared/plans/`
- [x] PROGRESS.md — complete development log
- [x] PROJECT_STATE.md — progress tracker (this file)
- [x] DECISIONS.md — 16 architectural decisions (D001-D016)
- [x] PROJECT_CHARTER.md — immutable goals & constraints

## 🔄 WIP

(none currently)

## ⏳ TODO (by priority)

### P1: V10 Engine Phase 2 — Enchantment Framework + Trigger System
- [ ] Enchantment dataclass (attack/health/keyword deltas, trigger_type, duration)
- [ ] Computed stats on Minion (base + enchantment deltas)
- [ ] TriggerDispatcher class (on_minion_played, on_minion_dies, on_turn_end, on_attack, on_spell_cast)
- [ ] Battlecry dispatcher (parse card text → apply effect)
- [ ] Deathrattle queue (board-position order, max 5 cascade)
- [ ] Aura engine (recompute after state changes, max 10 iterations)
- [ ] Discover framework (pool gen + evaluate best of 3)
- [ ] Location card support (new zone, durability, cooldown)
- **Design:** Phase 2 in `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### P2: V10 Engine Phase 3 — 2026 Modern Mechanics
- [ ] Imbue hero power upgrade (per-class paths, diminishing marginal value)
- [ ] Hand position system (Shatter split/merge, Outcast edges, Hand Targeting)
- [ ] Herald counter + Colossal appendage summoning
- [ ] Kindred previous-turn race/school tracking
- [ ] Quest progress tracking with reward
- [ ] Dark Gift pool (10 random bonuses)
- [ ] Rewind branching simulation (2-branch evaluate, pick best)
- **Design:** Phase 3 in `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### P3: Polish & Calibration
- [ ] Scoring calibration (temperature, LETHAL_SCALE, phase weights)
- [ ] Performance benchmarking (75ms RHEA target)
- [ ] Wild format scoring support (5209 cards)
- [ ] Risk assessor: additional class AoE thresholds
- [ ] Opponent simulator: consider hand size, hero power, divine shield

## 🚫 BLOCKED
(none currently)

## Architecture Decisions
See `thoughts/DECISIONS.md` for full details (D001-D016).

## Data Inventory

| File | Description | Size |
|------|-------------|------|
| hs_cards/unified_standard.json | Cleaned standard pool | 1015 cards |
| hs_cards/unified_wild.json | Cleaned wild-only pool | 5209 cards |
| hs_cards/v7_scoring_report.json | V7 scores | all standard |
| hs_cards/v2_scoring_report.json | V2 scores | all standard |
| hs_cards/l6_scoring_report.json | L6 scores | all standard |
| hs_cards/pool_quality_report.json | Pool quality metrics | 3 type pools |
| hs_cards/card_turn_data.json | Avg turn data | from HSReplay |
| hs_cards/rewind_delta_report.json | V7 rewind deltas | generated |
| hs_cards/hsreplay_cache.db | HSReplay SQLite cache | cached |

## Active Design Docs
- `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md` ⭐ (engine, Phase 2+3)
- `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md` ⭐ (scoring framework)
- `thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md` ⭐ (scoring impl)
- `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md` ⭐ (rules reference)

## Next Actions
1. **V10 Phase 2**: Enchantment framework + trigger system (designed, ready to implement)
2. **V10 Phase 3**: 2026 modern mechanics (designed, blocked on Phase 2)
3. **Scoring calibration**: temperature/weight tuning with real game data
4. **Performance**: benchmark and optimize to 75ms target

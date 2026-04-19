---
session: ses_25bf
updated: 2026-04-19T13:18:57.046Z
---

# Session Summary

## Goal
Research 2026 Hearthstone mechanics, build complete game rules reference, design V10 state-aware scoring framework, and update project documentation to reflect all progress.

## Constraints & Preferences
- Large files (>500 lines): skeleton first, then fill in chunks of <200 lines
- Design docs must have 9 sections: Problem Statement, Constraints, Approach, Architecture, Components, Data Flow, Error Handling, Testing Strategy, Open Questions
- Pipeline: brainstormer(调研+设计) → planner(拆任务) → executor(实现) → reviewer(验证)
- All card text is Chinese; all parsers must handle Chinese regex patterns
- Backward compatibility: 233 existing tests must pass
- Commit format: `feat: / fix: / cleanup: 简述`

## Progress
### Done
- [x] **Complete Game Rules Reference** — 1017 lines, 10 chapters, 61 subsections, 0 TODOs
  - `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md`
  - Ch1: Game zones (hand=10, board=7, secrets=5), card types (minion/spell/weapon/hero/location)
  - Ch2: Mana system (crystal growth, overload, temporary mana, cost modification)
  - Ch3: Combat system (6-phase attack sequence, taunt/charge/rush/windfury/divine shield/poisonous/stealth/freeze/immune/lifesteal)
  - Ch4: Keyword mechanics (battlecry/deathrattle/discover/choose one/combo/inspire/overload/outcast/reborn/overkill/corrupt)
  - Ch5: Trigger & aura system (Phase/Sequence structure, Whenever vs After, aura recalculation, enchantment system)
  - Ch6: Secret system (trigger conditions per class, Counterspell special rules)
  - Ch7: Hero power system (11 classes, Imbue upgrade paths, refresh mechanics)
  - Ch8: Card draw & fatigue (overdraw → graveyard, fatigue scaling 1/2/3/...)
  - Ch9: 2026 special mechanics (Herald/Shatter/Kindred/Rewind/Dark Gift/Fabled/Colossal/Dormant/Hand Targeting/Quest)
  - Ch10: Appendix (phase resolution, death creation step, trigger queue immutability, engine implementation mapping)
  - **Commit:** `c76e902`
- [x] **V10 State-Aware Scoring Framework Design**
  - `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`
  - Diagnosed 3 root flaws: linear superposition, static vs dynamic disconnect, rule-keyword disconnect
  - Designed 3-layer architecture: CIV (base, offline) + SIV (8 runtime state modifiers) + BSV (non-linear fusion)
  - 8 SIV modifiers: lethal awareness, taunt constraint, tempo window, hand position, trigger probability, race synergy, progress tracker, counter awareness
  - Key formulas: `damage_value = base × (1 + (1 - enemy_hp/30)² × 3.0)` for lethal proximity
  - Non-linear BSV fusion via softmax + temperature parameter
  - Keyword interaction table derived from rules (e.g., Poisonous vs Divine Shield = ×0.1)
  - 2026 mechanic CIV formulas: Imbue (diminishing marginal), Herald (threshold jumps), Shatter (merge bonus)
  - **Commit:** `788c461`
- [x] **Current evaluation model deep analysis** — Full audit of all scoring/evaluation code
  - Score flow: L1→L2→L3→L4→L5→V2→L6→V7→V8→Composite→scalar V
  - `composite.py`: weighted sum `V = w_v7×v7_adj + w_board×board + w_threat×threat + w_lingering×lingering + w_trigger×trigger`
  - `submodel.py`: 4 sub-models (board control, threat assessment, lingering effects, trigger/RNG EV)
  - `multi_objective.py`: 3 dimensions (tempo/value/survival) with phase-adaptive scalarization
  - `spell_simulator.py`: 10 regex patterns, auto-target highest-attack enemy, no deathrattle chains
  - `v8_contextual.py`: 7 contextual modifiers (turn factor, type factor, pool quality, deathrattle EV, lethal boost, rewind EV, synergy)
- [x] **PROJECT_STATE.md** updated to v3.0 — added rules reference, scoring design, reorganized TODOs
- [x] **DECISIONS.md** updated with D014-D016 (three-layer scoring, softmax fusion, rule-derived interactions)
- [x] **Prior work (from compressed blocks):** (b1) V10 engine overhaul design, (b2) Phase 1 execution (8 fixes, 233 tests), (b3) docs/conventions update

### In Progress
- [ ] V10 Engine Phase 2 (enchantment framework) — designed but not yet implemented
- [ ] V10 Scoring implementation (SIV + BSV) — designed but not yet implemented

### Blocked
- (none)

## Key Decisions
- **D014: Three-layer state-aware scoring (CIV+SIV+BSV)**: Replaces linear weighted sum with architecture that maps game rules → value modifiers. Each of 8 SIV modifiers corresponds to specific rule chapters.
- **D015: Non-linear fusion via softmax**: Linear weights cannot capture "lethal = infinite value". Softmax with temperature emphasizes dominant dimension. Lethal override to ABSOLUTE_LETHAL_VALUE.
- **D016: Rule-derived keyword interactions**: Replace empirical constants (power=1.5, mechanical=0.75) with interaction table derived from complete rules document.
- **D009: Three-phase engine overhaul**: Phase 1 (done) → Phase 2 (enchantment framework) → Phase 3 (2026 mechanics)
- **D010: Enchantment framework as key domino**: All trigger-based mechanics (battlecry, deathrattle, aura, discover) build on this one abstraction

## Next Steps
1. Execute V10 Engine Phase 2: Enchantment framework + trigger system (battlecry dispatcher, deathrattle queue, aura engine, discover framework)
2. Execute V10 Scoring: Implement SIV (8 state modifiers in `evaluators/siv.py`) + BSV (non-linear fusion in `evaluators/bsv.py`)
3. Execute V10 Engine Phase 3: 2026 modern mechanics (Imbue, Herald, Shatter, Kindred, Rewind, etc.)
4. Performance benchmarking and polish

## Critical Context
- **Scoring pipeline flow:** Card data → L1(vanilla curve) → L2(keyword tiers) → L3(text regex) → L4(type adapters) → L5(conditional EV) → V2 score → L6(HSReplay blend, θ=0.3) → V7(extended keywords) → V8(7 contextual modifiers) → Composite(5-component weighted sum) → scalar V
- **SIV formula:** `SIV(card, state) = CIV(card) × lethal × taunt × curve × position × trigger × synergy × progress × counter`
- **Lethal proximity formula:** `damage_multiplier = 1 + (1 - enemy_hp/30)² × 3.0` — gives 1.0× at 30HP, 7.0× at 1HP
- **233 tests currently passing** — any implementation must maintain zero regressions
- **Research sources:** wiki.gg Advanced Rulebook, Blizzard patch notes, outof.games (only reliable sources; fandom, topdecks, liquipedia all blocked/403)
- **4 expansions analyzed:** Emerald Dream (Imbue, Dark Gift), Un'Goro (Kindred, Quest), Timeways (Rewind, Fabled), CATACLYSM (Herald, Shatter, Colossal return)
- **1015 cards** in unified_standard.json with 37 unique mechanic keywords

## File Operations
### Read
- `/Users/ganjie/code/personal/hs_analysis/.opencode/CONVENTIONS.md`
- `/Users/ganjie/code/personal/hs_analysis/.opencode/agent.md`
- `/Users/ganjie/code/personal/hs_analysis/thoughts/DECISIONS.md`
- `/Users/ganjie/code/personal/hs_analysis/thoughts/PROJECT_STATE.md`

### Modified
- `/Users/ganjie/code/personal/hs_analysis/thoughts/DECISIONS.md` — Added D014-D016
- `/Users/ganjie/code/personal/hs_analysis/thoughts/PROJECT_STATE.md` — Updated to v3.0
- `/Users/ganjie/code/personal/hs_analysis/thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md` — NEW: 1017 lines, 10 chapters
- `/Users/ganjie/code/personal/hs_analysis/thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md` — NEW: scoring framework design

---
version: 1.0
created: 2026-04-19
last_changed: 2026-04-19
---

# Decision Log: hs_analysis

> Append-only record of key architectural and design decisions.
> Format: **D###** | Date | Decision | Context | Alternatives Considered

---

## D001 | 2026-04-18 | HearthstoneJSON as primary data source
**Context**: Need reliable, complete card data for standard format. iyingdi API was missing ~49 cards.
**Decision**: Use HearthstoneJSON as primary source, iyingdi as supplementary.
**Alternatives**: (A) iyingdi only — incomplete. (B) Blizzard CN API — no public docs. (C) python-hearthstone package — good but needed custom parsing.
**Rationale**: HSJSON provides 100% card coverage with structured JSON, well-maintained by community.

---

## D002 | 2026-04-18 | Lightweight EV modeling over full simulator
**Context**: Need card value estimation for arena decision support. Academic projects use full game simulators (Metastone, SabberStone).
**Decision**: Build lightweight Expected Value (EV) model with mathematical formulas, not a game simulator.
**Alternatives**: (A) Full simulator — too complex, 100K+ LOC. (B) Pure ML — needs training data we don't have. (C) EV formulas — fast, interpretable, sufficient.
**Rationale**: EV approach gives 80% of accuracy at 10% of complexity. Enables real-time decision support.

---

## D003 | 2026-04-18 | Multi-version scoring engine evolution
**Context**: Card scoring needs to be both interpretable and accurate.
**Decision**: Maintain parallel scoring versions (V2 → V7 → V8 → L6) rather than replacing.
**Alternatives**: (A) Single evolving engine — loses ability to compare. (B) Final version only — no audit trail.
**Rationale**: Each version builds on the previous. V2 baseline (MAE 0.66) → V7 data-driven → V8 contextual → L6 real-world. Enables regression testing.

---

## D004 | 2026-04-18 | 7 submodel EV framework
**Context**: Different card types need different evaluation approaches (minions vs spells vs weapons).
**Decision**: 7 specialized submodels covering all 984 cards: A: board state, B: opponent threats, C: ongoing effects, D: trigger probabilities, E: environment, F: card pool, G: player choice.
**Alternatives**: (A) Single unified model — can't capture type differences. (B) Per-card-type only — misses cross-type interactions.
**Rationale**: Submodel decomposition lets each handle its domain well. Composite evaluator combines them.

---

## D005 | 2026-04-18 | Package structure with hs_analysis/ core
**Context**: Project grew from scripts/ to need proper Python package structure.
**Decision**: All core logic in `hs_analysis/` package, `scripts/` only for thin CLI wrappers and standalone tools.
**Alternatives**: (A) Keep everything in scripts/ — no reusability. (B) Multiple packages — over-engineering.
**Rationale**: Single package with clear modules (data, scorers, search, evaluators, models, utils). Scripts import from package, never the reverse.

---

## D006 | 2026-04-18 | RHEA evolutionary search for play optimization
**Context**: Need efficient search over possible play sequences within time budget.
**Decision**: Use Rolling Horizon Evolution Algorithm (RHEA) with adaptive parameters and time budget control.
**Alternatives**: (A) Minimax — needs perfect information. (B) MCTS — too slow for 75ms budget. (C) Beam search — less adaptive. (D) Greedy — poor multi-turn planning.
**Rationale**: RHEA balances exploration/exploitation, works with partial information, meets 75ms time budget. Well-established in General Video Game AI competitions.

---

## D007 | 2026-04-18 | Card cleaner with 56-keyword regex extraction
**Context**: Card mechanics stored inconsistently across data sources (Chinese text, English tags, mixed formats).
**Decision**: Build card_cleaner.py with 56 regex patterns from hearthstone_enums.json for keyword extraction.
**Alternatives**: (A) NLP-based extraction — overkill. (B) Manual mapping — unmaintainable. (C) Use existing mechanics field only — incomplete (missing from iyingdi).
**Rationale**: Regex approach is deterministic, fast, and covers 100% of known keywords. Chinese-specific patterns handle iyingdi data.

---

## D008 | 2026-04-19 | Project state tracking for LLM session continuity
**Context**: Each LLM session starts fresh — no memory of project state, decisions, or progress.
**Decision**: Create PROJECT_CHARTER.md (immutable goals), PROJECT_STATE.md (progress tracker), DECISIONS.md (this file) — read at session start via .opencode/agent.md.
**Alternatives**: (A) Rely on memory tools only — fragile, not persistent across tools. (B) README only — too long, not focused. (C) Separate state.json — gets stale.
**Rationale**: Markdown files are version-controlled, human-readable, and can be updated by any LLM session. Bootstrap sequence in agent.md ensures consistent reads.

---

## D009 | 2026-04-19 | Three-phase layered overhaul for V10 (not full rewrite)
**Context**: Engine simulates 2018-level Hearthstone but 2026 Standard has 37 mechanic keywords. Need massive capability expansion.
**Decision**: Three-phase incremental overhaul: Phase 1 (fix broken basics), Phase 2 (enchantment framework), Phase 3 (2026 mechanics). Not a full rewrite.
**Alternatives**: (A) Full engine rewrite — risks regression on 233 tests, wastes solid RHEA core. (B) Plugin architecture — over-engineered. (C) ML-based text parser — fragile, needs training data.
**Rationale**: RHEA evolutionary loop, evaluation, and action normalization are solid. Problem is simulation fidelity, not search algorithm.

---

## D010 | 2026-04-19 | Enchantment framework as the key architectural domino
**Context**: 33% of cards have Battlecry, 14% have Deathrattle, but neither is simulated. Need a foundation layer for ALL trigger-based mechanics.
**Decision**: Build Enchantment dataclass + TriggerDispatcher as core abstraction. Every trigger-based mechanic builds on this.
**Alternatives**: (A) Hardcode each mechanic — duplicated logic. (B) Event sourcing — over-complex. (C) Fix battlecry/deathrattle without framework — blocks Phase 3.
**Rationale**: Framework is a force multiplier. Battlecry, deathrattle, aura, Dark Gift, Imbue, Quest all compose naturally on top.

---

## D011 | 2026-04-19 | Regex + manual dispatch for card effect parsing
**Context**: Card text is Chinese, follows predictable patterns. Need effects from ~1000 cards.
**Decision**: Continue regex pattern matching + manual dispatch. Extend spell_simulator patterns to battlecry/deathrattle.
**Alternatives**: (A) ML text parser — needs labeled data. (B) Full NLP — overkill. (C) Per-card mapping — unmaintainable.
**Rationale**: Card descriptions follow strict templates. Regex is deterministic, fast, already working.

---

## D012 | 2026-04-19 | Graceful degradation for unknown effects
**Context**: Not all card effects can be parsed. Novel text patterns exist.
**Decision**: Unparseable effects → log warning + treat card as vanilla. Engine never crashes.
**Alternatives**: (A) Fail loudly — crashes search, unacceptable. (B) Skip card — loses stats value. (C) Best guess — may produce wrong simulation.
**Rationale**: Working search that underestimates a card > crashed search.

---

## D013 | 2026-04-19 | Phase 1 design choices (8 mechanic fixes)
**Context**: Foundation bug fixes before building new systems.
**Decisions**:
- Poisonous does NOT bypass divine shield (official game rules)
- Windfury uses `has_attacked_once` flag for two-attack tracking
- Overload: `overload_next` on PLAY → `overloaded` on END_TURN → deduct next turn
- Freeze: flag-based skip in enumerate, reset on END_TURN
- Fatigue: standalone `apply_draw()` with incrementing counter

---

<!-- Append new decisions below this line -->

---

## D014 | 2026-04-19 | Three-layer state-aware scoring architecture (CIV + SIV + BSV)
**Context**: Current V2→V7→V8→Composite pipeline has three fundamental flaws: linear superposition, static vs dynamic disconnect, keyword scoring disconnected from game rules.
**Decision**: Redesign as three-layer architecture: CIV (Card Intrinsic Value, offline) + SIV (State Interaction Value, runtime, 8 modifiers) + BSV (Board State Value, non-linear fusion).
**Alternatives**: (A) Pure ML model — no training data, not interpretable. (B) Monte Carlo simulation — too slow for 250ms RHEA budget. (C) Keep linear weighted sum — cannot capture non-linear value jumps like lethal proximity.
**Rationale**: Each layer has clear responsibility. SIV maps game rules to value modifiers (each of the 8 modifiers corresponds to specific rule chapters). Non-linear fusion via softmax captures lethal/value jumps. Incremental: each modifier is independent and can be added one at a time.

---

## D015 | 2026-04-19 | Non-linear value fusion via softmax (not linear weighted sum)
**Context**: Current composite.py uses `V = w1×v1 + w2×v2 + ...` which cannot represent "lethal = infinite value" or "1 HP vs 30 HP opponent" value differences.
**Decision**: Use softmax normalization with temperature parameter for BSV fusion. Lethal detection as independent module that overrides BSV to ABSOLUTE_LETHAL_VALUE.
**Alternatives**: (A) Keep linear weights — proven inadequate for lethal scenarios. (B) Full neural network — overkill, not interpretable. (C) Threshold-based rules — too brittle, many edge cases.
**Rationale**: Softmax naturally emphasizes the dominant dimension (survival when threatened, tempo when ahead). Temperature parameter allows tuning exploration vs exploitation. Lethal override ensures search always finds kill when available.

---

## D016 | 2026-04-19 | Rule-derived keyword interaction table (not empirical constants)
**Context**: Current keyword scoring uses hardcoded constants (power=1.5, mechanical=0.75) with no basis in game rules. Interactions like Poisonous+Divine Shield are not modeled.
**Decision**: Build keyword interaction table directly from the complete rules document. Each interaction has a rule reference and a precise value impact.
**Alternatives**: (A) Keep empirical constants — proven inaccurate. (B) Learn from HSReplay data — interaction effects are confounded with too many variables. (C) Per-card manual tuning — unmaintainable for 1000+ cards.
**Rationale**: Rules document provides deterministic interaction logic (e.g., "Divine Shield absorbs damage → Poisonous does not trigger → Poisonous value × 0.1 vs shielded targets"). This is ground truth, not approximation.

## D017 | 2026-04-20 | Effect string protocol for cross-module trigger/deathrattle/aura dispatch
**Context**: Triggers, deathrattles, and auras all need to express "deal N damage to random enemy" or "summon N/N" etc. Without a protocol, each module invents its own representation.
**Decision**: Colon-separated effect strings like `"damage:random_enemy:N"`, `"summon:N:N"`, `"draw:N"`, `"buff:friendly:N:N"`, `"heal:hero:N"`, `"armor:N"`. All dispatch modules (trigger_system, deathrattle, battlecry_dispatcher) use the same format.
**Alternatives**: (A) Enum-based effect types — more type-safe but harder to parse from card text. (B) Callable effect objects — overkill for search simulation. (C) Per-module ad-hoc — leads to inconsistency.
**Rationale**: String protocol is human-readable, easy to parse from Chinese card text with regex, and consistent across all dispatch points. Search doesn't need type safety.

## D018 | 2026-04-20 | Greedy target selection for battlecry (highest-attack enemy, most-damaged friendly)
**Context**: Battlecry effects need target selection but RHEA search can't afford Monte Carlo target simulation for every battlecry.
**Decision**: Deterministic greedy: damage → highest-attack enemy, heal → most-damaged friendly, buff → highest-cost friendly. Simple, fast, and produces reasonable search outcomes.
**Alternatives**: (A) Random target — non-deterministic, makes search unstable. (B) Exhaustive target enumeration — explodes search space. (C) Heuristic scoring per target — adds complexity for marginal gain.
**Rationale**: In arena, battlecry targets usually have an obvious best choice (kill the biggest threat, heal the most damaged). Greedy captures this well enough for search.

## D019 | 2026-04-20 | Graceful degradation: try/except on all new dispatch points in rhea_engine
**Context**: Phase 2 adds battlecry dispatch, trigger dispatch, deathrattle resolution, aura recomputation, discover resolution, and location activation — all wired into the critical `apply_action` path. Any bug in these new modules could crash the entire search.
**Decision**: Every integration point in `apply_action` is wrapped in `try/except: pass`. If a new module fails, the search continues with the vanilla behavior (play the card without battlecry, resolve combat without deathrattles, etc.).
**Alternatives**: (A) Let exceptions propagate — one bug kills the entire decision engine. (B) Logging on failure — adds I/O overhead in hot path. (C) Feature flags — adds config complexity.
**Rationale**: Search robustness is paramount. A degraded search that plays vanilla Hearthstone is infinitely better than a crashed search. The 274 baseline tests already verify vanilla behavior works.

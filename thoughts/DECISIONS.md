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

<!-- Append new decisions below this line -->

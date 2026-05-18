# Project Known Defects — hs_analysis

> Auto-maintained by hs-refactor skill. Update when new defects are discovered or resolved.

## Architecture Smells

| ID | Smell | Location | Lines | Impact | Status |
|----|-------|----------|-------|--------|--------|
| AS1 | **God Object** | `analysis/search/packet_replayer.py` | 2200 | 15+ subsystems in one file: entity parsing, zone tracking, card play, deathrattle, triggers, secrets, quest, spell damage, location, discover | 🔴 Open |
| AS2 | **God Object** | `analysis/search/rhea/engine.py` (legacy rhea_engine.py) | 2084 | Action enum, simulation, card play, attack, hero power all inline | 🟡 In Progress (docs/refactoring_plan.md Phase 4) |
| AS3 | **Feature Envy** | `analysis/rhea/simulation.py` | ~900 | 30+ lazy imports, calls internals of 15+ other modules | 🔴 Open |
| AS4 | **Mixed Responsibilities** | `analysis/watcher/global_tracker.py` | 1079 | Card tracking + game state + secret probability + opponent modeling | 🔴 Open |
| AS5 | **Primitive Obsession** | `analysis/search/game_state.py` | ~362 | 25+ raw fields, 50-line `copy()`, new mechanics always add fields | 🟡 Planned (docs/refactoring_plan.md Phase 2) |
| AS6 | **Scattered Mechanics** | `analysis/search/*.py` (~25 files) | — | No shared interface, each module imports GameState and mutates directly | 🟡 Planned (docs/refactoring_plan.md Phase 1-2) |
| AS7 | **Shotgun Surgery** | GameState mutation | — | `game_state` fields mutated from 15+ files. Any schema change touches all of them | 🔴 Open |

## Duplications

| ID | Type | Locations | Description | Status |
|----|------|-----------|-------------|--------|
| D1 | Dual search() | `rhea/engine.py` vs `mcts/engine.py` | Two independent search implementations with shared logic but no shared base | 🟡 Partial (rhea extracted to rhea/) |
| D2 | apply_draw() | Multiple sim files | Draw logic reimplemented in each simulation variant | 🔴 Open |
| D3 | Effect parsing | `deathrattle.py`, `trigger_system.py`, `location.py` | String-based effect parsing ×3 (planned fix in refactoring_plan Phase 1) | 🟡 Planned |
| D4 | handle_full_entity() | 3 locations in packet_replayer | Entity update handler repeated with minor variations | 🔴 Open |
| D5 | Card data loading | `hsdb.py`, `card_index.py`, `build_unified_db.py` | Three different card data loading paths with overlapping logic | ✅ Resolved (card_data refactoring) |
| D6 | load_json() | Was 36 locations | JSON loading without error handling scattered everywhere | ✅ Resolved (R7) |
| D7 | http_get_json() | Was 3 locations | HTTP JSON fetch duplicated | ✅ Resolved (R3) |
| D8 | STANDARD_SETS constant | `hsdb.py`, `build_unified_db.py`, `build_wild_db.py` | Same set definition in 3 files | ✅ Resolved (card_data refactoring) |
| D9 | _clean_text() | `build_unified_db.py`, `build_wild_db.py` | Identical text cleaning function | ✅ Resolved (card_data refactoring) |

## Reinvented Wheels

| ID | What | Location | Better Alternative | Status |
|----|------|----------|--------------------|--------|
| RW1 | Custom JSON loading | `utils/load_json()` | Standard `json.load()` with Path.read_text() + error handling | ✅ Resolved (R7) |
| RW2 | Custom HTTP client | `utils/http.py` | `httpx` with retry/timeout built-in | 🟡 Consider |
| RW3 | Manual card text parsing | `card_effects.py`, `card_cleaner.py` | Structured data from HSJSON `mechanics` field where available | 🔴 Open |
| RW4 | Custom singleton pattern | `hsdb.get_db()`, `card_index.get_index()` | Module-level lazy initialization or `functools.lru_cache` | ✅ Resolved (card_data refactoring) |
| RW5 | Manual frozenset indexing | `card_index.py` | Pre-built library indices or database (SQLite FTS) for search | 🟡 Under review |

## Test Coverage Gaps

### Critical (no tests, high-impact code)

| Module | Lines | Risk |
|--------|-------|------|
| `packet_replayer.py` | 2200 | Core game replay logic |
| `global_tracker.py` | 1079 | Live game state tracking |
| `rhea/simulation.py` | ~900 | RHEA simulation engine |
| `state_bridge.py` | ~400 | Watcher→GameState bridge |
| `spell_target_resolver.py` | ~300 | Spell targeting logic |
| `battlecry_dispatcher.py` | ~250 | Battlecry execution |
| `secret_probability.py` | ~300 | Secret prediction |
| `lethal_checker.py` | ~200 | Lethal detection |

### Modules with Tests

| Module | Test File | Coverage |
|--------|-----------|----------|
| `card_index.py` | `tests/test_card_index.py` (288 lines) | Good |
| `card_cleaner.py` | `tests/test_card_cleaner.py` (240 lines) | Good |
| `card_effects.py` | Covered via card tests | Partial |
| `scoring_engine.py` | `tests/test_scoring*.py` | Good |

### Stats (as of last audit)

- **46 modules** with zero test coverage
- **~15 test files** total
- **736 tests passing**

## Dead Code Candidates

| Location | Evidence | Risk |
|----------|----------|------|
| `card_cleaner.py` | Marked DEPRECATED, kept for legacy JSON builds | Low — still used by build scripts |
| `build_wild_db.py` | Wild format not currently used in analysis | Low — may be needed later |
| Legacy `rhea_engine.py` | Replaced by `rhea/` package structure | Medium — verify no imports remain |

## File Size Hotspots (>500 lines)

| File | Lines | Recommendation |
|------|-------|----------------|
| `packet_replayer.py` | 2200 | Decompose into 6-8 focused modules |
| `rhea/engine.py` (legacy) | 2084 | Follow refactoring_plan.md Phase 4 |
| `global_tracker.py` | 1079 | Extract card tracking, opponent model |
| `rhea/simulation.py` | ~900 | Reduce lazy imports, extract helpers |
| `card_updater.py` | 560 | Merge into unified card_data module |
| `hsdb.py` | 634 | Merge with card_index (DONE) |
| `card_index.py` | 554 | Merge into hsdb (DONE) |
| `card_cleaner.py` | 440 | Deprecate once JSON builds updated |

## Severity Priority

**P0 — Fix Now (blocks other work):**
- AS1 (packet_replayer God Object) — blocks all search engine improvements

**P1 — Fix Next Sprint:**
- AS5 (GameState primitive obsession) — every new mechanic requires touching 15+ files
- AS7 (Shotgun Surgery on GameState) — same root cause as AS5

**P2 — Fix When Touched:**
- AS3 (rhea/simulation Feature Envy) — refactor when rhea engine changes
- AS4 (global_tracker mixed responsibilities) — refactor when watcher changes
- D2 (apply_draw duplication) — consolidate when simulation changes

**P3 — Monitor:**
- D1 (dual search) — intentional for now, MCTS and RHEA serve different purposes
- RW3 (card text parsing) — limited by HSJSON data quality

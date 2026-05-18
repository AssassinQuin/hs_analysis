# Completed Refactorings — hs_analysis

> History of all completed refactoring work. Prevents re-discovery and documents lessons learned.

## Summary

| Metric | Value |
|--------|-------|
| Total refactorings completed | 11 |
| Total LOC reduced | ~350+ |
| Test suite status | 736 tests passing |
| Zero test regressions | All refactorings maintained green tests |

---

## R1: Kill Dynamic Imports in simulation.py

- **Status:** ✅ Completed
- **Target:** `analysis/rhea/simulation.py`
- **LOC Delta:** -71
- **Problem:** Used `__import__()` and `importlib.import_module()` to dynamically load 15+ modules at runtime. Made debugging impossible, broke IDE navigation, hid import cycles.
- **Solution:** Replaced all dynamic imports with static imports at module top level. Added proper error handling for optional dependencies.
- **Lesson:** Dynamic imports in Python are almost never justified. If you need lazy loading, use function-level imports, not `__import__()`.

## R2: Consolidate Score Functions in scoring_engine.py

- **Status:** ✅ Completed
- **Target:** `analysis/scorers/scoring_engine.py`
- **Problem:** 5 separate `score_*` functions (`score_minion`, `score_spell`, `score_weapon`, etc.) with duplicated rating logic and inconsistent parameter signatures.
- **Solution:** Unified into a single `score_card(card, context)` dispatcher with type-specific branches. Shared rating calculations extracted to helpers.
- **Lesson:** When multiple functions differ only by type dispatch, a single dispatcher is cleaner.

## R3: Shared http_get_json

- **Status:** ✅ Completed
- **Target:** `analysis/utils/http.py`
- **LOC Delta:** 3 copies → 1 shared utility
- **Problem:** Three separate implementations of "fetch JSON from URL" with different error handling, timeout values, and retry logic.
- **Solution:** Single `http_get_json(url, **kwargs)` with configurable timeout, retry, and user-agent. All consumers updated.
- **Lesson:** Network utility code should always be centralized. Different timeout/retry values are configuration, not different implementations.

## R4: Narrow Exception Blocks

- **Status:** ✅ Completed
- **Target:** 11 files, 49 blocks
- **Problem:** 49 instances of bare `except Exception:` catching everything including KeyboardInterrupt and SystemExit. Masked real bugs.
- **Solution:** Replaced with specific exception types (`except (ValueError, KeyError):`, `except requests.RequestException:`, etc.). Added logging where errors were silently swallowed.
- **Lesson:** `except Exception` is acceptable only at the outermost boundary (CLI handler, event loop). Inner code should catch specific exceptions.

## R5-lite: Extract GlobalTracker Dataclasses

- **Status:** ✅ Completed
- **Target:** `analysis/watcher/global_tracker.py`
- **LOC Delta:** 1079 → 879 (-200)
- **Problem:** Tracker state mixed with tracking logic. Data structures defined inline alongside methods.
- **Solution:** Extracted `TrackedCard`, `PlayerState`, `SideStats` dataclasses to separate definitions. Methods reference these types.
- **Lesson:** Extracting data types from God Objects is a safe, testable first step before deeper decomposition.

## R6: Import Cycle Audit

- **Status:** ✅ Completed
- **Target:** Project-wide
- **Problem:** Suspected circular imports causing startup failures.
- **Solution:** Systematic audit of all import chains. Found **0 real cycles**. Most "cycle" errors were actually module-level side effects (singleton initialization during import).
- **Lesson:** Before fixing import cycles, verify they actually exist. Module-level singletons that call `get_db()` during import are the real problem, not import cycles.

## R7: Shared load_json Utility

- **Status:** ✅ Completed
- **Target:** `analysis/utils/__init__.py`
- **LOC Delta:** 36 copies → 1 shared utility
- **Problem:** 36 locations with `json.load(open(path))` or `json.loads(text)`, no error handling, inconsistent encoding.
- **Solution:** Single `load_json(path)` with proper Path handling, encoding, error messages, and optional default value.
- **Lesson:** Any utility used >5 times should be extracted. The threshold for "shared utility" is lower than most developers think.

## R8: Merge Scoring Helpers (FALSE POSITIVE)

- **Status:** ✅ Verified — Already merged
- **Problem:** Suspected duplicate scoring helpers in two files.
- **Solution:** Investigation showed the duplication was already resolved in R2. No action needed.
- **Lesson:** Always verify the problem still exists before planning a fix. Memory can be stale.

## R9: Mechanic Registry (Merged into R1)

- **Status:** ✅ Completed (as part of R1)
- **Problem:** Planned separate mechanic registry pattern.
- **Solution:** Mechanic dispatch was simplified during R1's import cleanup. A full registry pattern was deemed over-engineering (see anti-patterns.md #7).
- **Lesson:** When a simpler change resolves the same issue, prefer simplicity over architectural purity.

## R10: Move scoring_engine to scripts/

- **Status:** ✅ Completed
- **Target:** `analysis/scorers/scoring_engine.py` → `scripts/scoring_engine.py`
- **Problem:** `scoring_engine.py` was a CLI script (argparse + main) living in the library package.
- **Solution:** Moved to `scripts/` where all other CLI tools live. Library code in `analysis/scorers/` remains importable.
- **Lesson:** Scripts with `if __name__ == "__main__"` blocks don't belong in library packages.

## R11: Move secret_probability to watcher/

- **Status:** ✅ Completed
- **Target:** `analysis/search/secret_probability.py` → `analysis/watcher/secret_probability.py`
- **Problem:** Secret probability tracking is a watcher concern (monitors live game state) but lived in the search engine package.
- **Solution:** Moved to `analysis/watcher/` alongside other live monitoring modules.
- **Lesson:** Module placement should reflect the module's primary concern, not where it was first written.

## Card Data Consolidation (R12)

- **Status:** ✅ Completed (full 4-phase refactor)
- **Target:** `analysis/data/card_data.py` (NEW), `hsdb.py` (shim), `card_index.py` (shim)
- **LOC Delta:** hsdb 634→14, card_index 554→14, card_updater 560→0 (deleted), build_unified_db 121→0 (deleted), build_wild_db 146→0 (deleted), card_data.py 0→1467. Net ~614 lines removed from active code.
- **Problem:** Two parallel card databases (HSCardDB + CardIndex) with near-identical APIs. Card data scattered across 10+ files. No multi-dimensional search. No auto-update. Card updater CLI-only.
- **Solution:** Created single `card_data.py` with CardDB class. Merged HSCardDB loading + CardIndex frozenset indexes + pool cache. Added `search(**kwargs)` with two-phase filter (frozenset intersection + linear scan). Added auto-update (mtime check → sync fetch → graceful degradation). Added `build_databases()`. hsdb.py and card_index.py are now re-export shims.
- **Tests:** 769 pass, 0 fail (zero regressions)
- **Lesson:** When two modules have the same API surface, they should be one module. Accept card list in constructor for test backward compat. Don't override format field if already set.

---

## Anti-Patterns Avoided

These refactorings were proposed but rejected during pruning:

| Proposal | Rejection Reason |
|----------|-----------------|
| Protocol-based mechanic dispatch | Only 1 consumer, YAGNI |
| Event bus for game state updates | Synchronous 1:1 flow, anti-pattern #8 |
| Abstract base for search engines | Only 2 implementations, dict dispatch sufficient |
| Plugin system for card effects | <5 effect types, if/else is clearer |

## Patterns That Worked

| Pattern | Used In | Why It Worked |
|---------|---------|---------------|
| Shared utility extraction | R3, R7 | Low risk, high LOC reduction |
| Narrow exception types | R4 | Caught real bugs during the change |
| File relocation by concern | R10, R11 | Zero logic changes, just better organization |
| Merge duplicate APIs | Card Data | Performance improvement + API simplification |
| Incremental extraction from God Objects | R5-lite | Safe first step before deeper decomposition |

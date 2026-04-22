---
version: 1.0
created: 2026-04-20
---

# Retrieval Optimization — Implementation Plan

> Design: `thoughts/shared/designs/2026-04-20-retrieval-optimization-design.md`

## Batch 1: CardIndex Enhancement

**Goal**: Add dbfId-based intersection + LRU query cache to CardIndex.

### Task 1.1: Pre-build dbfId frozensets
- **File**: `hs_analysis/data/card_index.py`
- **Changes**:
  - In `_build_indexes()`, after existing indexes, build `_dbf_sets` dict
  - `_dbf_sets` maps index name → {key: frozenset[dbfId]}
  - Cover: by_mechanic, by_type, by_class, by_race, by_school, by_cost, by_format, by_set, by_rarity, _class_type, _mechanic_type
- **Verify**: Existing 797 tests pass

### Task 1.2: Add LRU query cache to get_pool()
- **File**: `hs_analysis/data/card_index.py`
- **Changes**:
  - Add `_pool_cache: Dict[frozenset, List[CardDict]]` (maxsize=256)
  - At top of `get_pool()`, compute cache key from frozenset of filter items
  - On cache hit, return copy of cached list (prevent mutation)
  - On cache miss, compute result, store, return
  - `rebuild=True` in `get_index()` clears cache
- **Verify**: get_pool() returns same results for identical queries

### Task 1.3: Rewrite intersection to use dbfId frozensets
- **File**: `hs_analysis/data/card_index.py`
- **Changes**:
  - Replace `set(id(c))` pattern with `frozenset` intersection from `_dbf_sets`
  - Resolve final dbfIds to card dicts via `dbf_lookup`
  - Fallback to current behavior if any index has no dbfId
- **Verify**: All existing tests pass (same results, faster)

### Task 1.4: Add tests for cache behavior
- **File**: `tests/test_card_index_cache.py` (new)
- **Tests**:
  - Same query returns same results (correctness)
  - Second call is faster than first (cache hit)
  - `get_index(rebuild=True)` clears cache
  - Complex multi-filter query cached correctly
  - Range filters (cost_min/cost_max) work with cache
  - exclude_dbfids works with cache

---

## Batch 2: ScoreProvider Singleton Cache (independent of Batch 1)

**Goal**: Eliminate per-search ScoreProvider JSON re-read.

### Task 2.1: Add module-level provider cache
- **File**: `hs_analysis/utils/score_provider.py`
- **Changes**:
  - Add `_PROVIDERS: Dict[Tuple[str, str], ScoreProvider] = {}`
  - Add `_get_provider(path, field) → ScoreProvider` helper
  - Update `load_scores_into_hand()` to use `_get_provider()`
  - Keep ScoreProvider class unchanged
- **Verify**: All existing tests pass

### Task 2.2: Add tests for ScoreProvider caching
- **File**: `tests/test_score_provider_cache.py` (new)
- **Tests**:
  - Two calls to load_scores_into_hand use same provider
  - Different source ("v7" vs "l6") creates different provider
  - Hand loading still populates card.v7_score correctly

---

## Batch 3: discover.py Reuse CardIndex (depends on Batch 1)

**Goal**: Remove duplicate card caches, delegate to CardIndex.

### Task 3.1: Rewrite generate_discover_pool()
- **File**: `hs_analysis/search/discover.py`
- **Changes**:
  - Remove `_CARD_CACHE`, `_WILD_CACHE`, `_load_cards()`, `_load_wild_cards()`
  - Import `get_index` from card_index
  - `generate_discover_pool()` calls `get_index().discover_pool()` + race post-filter
  - Keep `_parse_discover_constraint()`, `_RACE_MAP`, `_TYPE_NORMALIZE` unchanged
  - Path: uses CardIndex's data loading (which uses config.DATA_DIR)
- **Verify**: All discover tests pass (test_discover.py, test_wild_discover.py)

### Task 3.2: Verify search integration
- **File**: No new file
- **Action**: Run full test suite (797+) to confirm discover integration works
- **Verify**: rhea_engine tests pass, discover resolution unchanged

### Task 3.3: Update discover tests if needed
- **File**: `hs_analysis/search/test_discover.py`, `hs_analysis/search/test_wild_discover.py`
- **Changes**: Only if test setup mocks _CARD_CACHE directly (unlikely — most tests mock at higher level)
- **Verify**: All tests pass

---

## Batch 4: Performance Verification (depends on Batch 1-3)

**Goal**: Measure improvement, verify 75ms RHEA budget met.

### Task 4.1: Write performance benchmark
- **File**: `tests/test_retrieval_performance.py` (new)
- **Tests**:
  - get_pool() 1000-query throughput benchmark
  - generate_discover_pool() 100-call benchmark
  - load_scores_into_hand() 100-call benchmark
  - RHEA search() single-run timing
- **Verify**: All benchmarks complete, log results

### Task 4.2: Update PROJECT_STATE.md
- **File**: `thoughts/PROJECT_STATE.md`
- **Changes**: Add optimization to DONE section, update test counts

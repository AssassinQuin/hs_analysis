---
version: 1.0
created: 2026-04-20
---

# Retrieval Optimization Design

## 1. Problem Statement

Current system has 4 performance bottlenecks in data retrieval:

| # | Issue | Impact | Location |
|---|-------|--------|----------|
| P1 | Card data loaded 3-4x independently | ~4x memory waste (~40MB for wild pool) | CardIndex, discover.py, DeckTestGenerator, scorers |
| P2 | ScoreProvider rebuilt every RHEA search | ~1ms wasted per search (JSON parse + dict build) | rhea_engine.py:676 |
| P3 | discover.py linear O(n) scan per call | ~5000 comparisons for wild discover | discover.py:191 |
| P4 | CardIndex.get_pool() no query cache | Rebuilds `set(id(c))` per call, same filters re-intersect | card_index.py:300 |

**Target**: Eliminate redundant loading, add query caching, ensure discover reuses CardIndex.

## 2. Constraints

- **No new dependencies** — must use only stdlib + existing deps (numpy, scipy)
- **Zero regression** — 797 tests must continue passing
- **Backward compatible** — all public APIs (get_index, get_pool, ScoreProvider, load_scores_into_hand) keep same signatures
- **Thread safety** — RHEA may run in threaded context; singletons must be safe for single-process use
- **Process-lifetime caching** — no eviction needed, data immutable after load

## 3. Approach

**Self-built optimization (Option C)** — enhance existing CardIndex and ScoreProvider with caching, eliminate duplicate loads via centralized data loading.

### Rejected Alternatives

| Alternative | Why Rejected |
|-------------|-------------|
| ducks (PyPI) | New dependency; ~6200 cards too small to benefit from B-tree; adds complexity for marginal gain |
| TinyDB | Oriented toward persistence, not in-memory queries; slower than dict lookups for our scale |
| SQLite :memory: | Serialization overhead for Python dict objects; query parsing slower than direct dict access at ~6000 rows |

## 4. Architecture

### Before (Current)
```
unified_standard.json ──→ CardIndex._cards (singleton)
                       ──→ discover._CARD_CACHE (module cache)
                       ──→ DeckTestGenerator.card_db (test singleton)
                       ──→ scorer main() (per-call load)

v7_scoring_report.json ──→ ScoreProvider (per-search new instance)
```

### After (Proposed)
```
unified_standard.json ──→ CardIndex._cards (sole data owner)
                       ──→ discover.py reuses CardIndex via get_index()
                       ──→ DeckTestGenerator reuses CardIndex

v7_scoring_report.json ──→ ScoreProvider._global_cache (module singleton)
```

### Component Changes

#### 4.1 CardIndex: dbfId-based intersection + LRU query cache

**Key insight**: Replace `id(c)` set intersection with `dbfId` integer set intersection (faster hash + enables caching).

```python
# Before: O(k * n) set creation per query
result = set(id(c) for c in candidate_lists[0])
for lst in candidate_lists[1:]:
    result &= set(id(c) for c in lst)

# After: pre-built dbfId sets + LRU cache
# In _build_indexes(), also build:
self._dbf_sets: Dict[str, Dict[Any, frozenset[int]]] = {
    "mechanic": {k: frozenset(c.get("dbfId", i) for i, c in enumerate(v)) for k, v in self.by_mechanic.items()},
    "type":     {k: frozenset(c.get("dbfId", i) for i, c in enumerate(v)) for k, v in self.by_type.items()},
    ...
}
# Intersection uses frozenset &= (faster than set(id(c)))
# Cache key = frozenset of (filter_name, value) pairs
```

**Query cache**: `functools.lru_cache` pattern on `get_pool()`, keyed by frozen filter kwargs. Since cards are immutable after load, results are safe to cache indefinitely.

**Cache size**: ~200 entries covers all realistic query combinations.

#### 4.2 ScoreProvider: module-level singleton

```python
# Before: new instance per call
def load_scores_into_hand(state, source="v7"):
    provider = ScoreProvider(report_path=path, score_field=field)  # re-reads JSON!

# After: module-level cache by (report_path, score_field)
_PROVIDERS: Dict[Tuple[str, str], ScoreProvider] = {}

def _get_provider(report_path: str, score_field: str) -> ScoreProvider:
    key = (report_path, score_field)
    if key not in _PROVIDERS:
        _PROVIDERS[key] = ScoreProvider(report_path, score_field)
    return _PROVIDERS[key]
```

No change to ScoreProvider class itself — only `load_scores_into_hand()` uses the cached provider.

#### 4.3 discover.py: reuse CardIndex

```python
# Before: independent cache + linear scan
_CARD_CACHE = json.load(...)
pool = [c for c in all_cards if filter(c)]  # O(n)

# After: delegate to CardIndex
from hs_analysis.data.card_index import get_index

def generate_discover_pool(hero_class, card_type=None, race=None, use_wild_pool=False):
    idx = get_index()
    fmt = "wild" if use_wild_pool else "standard"
    pool = idx.discover_pool(hero_class, card_type=card_type, format=fmt, exclude_dbfids=None)
    if race:
        pool = [c for c in pool if race in (c.get("race") or "")]
    return pool
```

CardIndex already has `discover_pool()` method that uses indexed lookups. The only gap is race filtering, which is a linear post-filter but on a much smaller result set (~200-400 cards after class+format filter).

#### 4.4 Path normalization

All paths via `config.DATA_DIR`. Remove `Path(__file__).resolve().parent...` patterns from discover.py.

## 5. Components

| File | Change | Lines |
|------|--------|-------|
| `data/card_index.py` | Add `_dbf_sets` pre-built sets, `_pool_cache` LRU, update `get_pool()` intersection | ~50 new |
| `utils/score_provider.py` | Add `_PROVIDERS` module cache, update `load_scores_into_hand()` | ~10 new |
| `search/discover.py` | Remove `_CARD_CACHE`/`_WILD_CACHE`, use `get_index()` | ~30 removed, ~15 new |
| `config.py` | No change | 0 |

## 6. Data Flow

### get_pool() optimized flow
```
caller → get_pool(mechanics="TAUNT", card_type="MINION")
  → check _pool_cache[frozenset(filters)]
  → cache hit → return cached result
  → cache miss → collect candidate _dbf_sets
  → frozenset intersection (int hash, no object allocation)
  → resolve dbfIds to card dicts via dbf_lookup
  → apply range/exclusion filters
  → store in cache → return
```

### discover flow
```
rhea_engine → resolve_discover()
  → generate_discover_pool()
    → get_index().discover_pool(class, format)  # indexed O(1) lookup
    → post-filter by race if needed
  → sample 3, pick highest cost
```

### score loading flow
```
rhea_engine.search()
  → load_scores_into_hand(state, "v7")
    → _get_provider(path, "v7_score")  # returns cached singleton
    → provider.load_into_hand(hand)     # already loaded, O(n) dict lookup
```

## 7. Error Handling

- CardIndex not built yet: `get_index()` lazy-loads as before
- JSON file missing: existing warning + empty fallback behavior preserved
- Cache corruption impossible: caches are derived from immutable data, never mutated
- Race filtering in discover: graceful empty list if CardIndex returns no matches

## 8. Testing Strategy

| Batch | Tests | What |
|-------|-------|------|
| Existing | 797 | All must pass — zero regression |
| New: card_index | ~10 | dbfId intersection correctness, cache hit/miss, cache invalidation on rebuild |
| New: score_provider | ~5 | Singleton behavior, multiple sources, hand loading |
| New: discover | ~8 | Reuse CardIndex, race filter, wild pool, backward compat |

**Total new tests: ~23**

## 9. Open Questions

- Q: Should `_pool_cache` have a max size? A: Yes, 256 entries (covers all realistic queries + margin). `functools.lru_cache` handles eviction.
- Q: Should discover.py's `_CARD_CACHE` be kept as fallback? A: No — CardIndex is always available, dual caches cause inconsistency.
- Q: Thread safety for `_PROVIDERS` dict? A: Acceptable for single-process use. If threading needed later, add `threading.Lock`.

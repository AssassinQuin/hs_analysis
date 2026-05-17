---
date: 2026-04-19
topic: "Card Index + Wild Pool + Cleanup Implementation"
status: active
---

## Overview

4 new modules + 2 modified modules + cleanup operations. Estimated 2,000+ lines of new code.

## Micro-Tasks

### Phase 0: Data Analysis Prerequisites
- **0.1** Examine `hearthstone_enums.json` to extract all 56 keyword zh names + 13 race zh names + 7 school zh names
- **0.2** Examine `unified_standard.json` to catalog all 93 dirty race values for normalization mapping

### Phase 1: Card Cleaner (`hs_analysis/data/card_cleaner.py`)
- **1.1** Create card_cleaner.py with:
  - RACE_ZH_MAP: 13 race Chinese→English mapping
  - SCHOOL_ZH_MAP: 7 spell school Chinese→English mapping  
  - KEYWORD_PATTERNS: 56 keyword Chinese text→enum ID regex patterns
  - `normalize_race(card)` — clean race field, split multi-tags, extract spell schools
  - `extract_mechanics(card_text, existing_mechanics)` — re-scan with 56 keywords
  - `clean_card(card_dict) → card_dict` — full cleaning pipeline
  - `clean_card_pool(input_path, output_path)` — batch process with backup

### Phase 2: Wild Card Fetcher (`hs_analysis/data/fetch_wild.py`)
- **2.1** Create fetch_wild.py:
  - Reuse iyingdi API logic from fetch_iyingdi.py
  - Change `standard=1` → remove or set `standard=0`
  - Save raw to `hs_cards/iyingdi_wild_raw.json`
  - Save normalized to `hs_cards/iyingdi_wild_normalized.json`
  - CLI entry point with `if __name__`

### Phase 3: Wild DB Builder (`hs_analysis/data/build_wild_db.py`)
- **3.1** Create build_wild_db.py:
  - Load `unified_standard.json` (standard pool)
  - Load wild normalized data
  - Dedup by dbfId — remove cards that exist in standard
  - Write `unified_wild.json` (wild-only cards)
  - Print statistics (total wild, deduped, final count)

### Phase 4: Card Index (`hs_analysis/data/card_index.py`)
- **4.1** Create card_index.py:
  - `CardIndex` class with pre-computed indexes
  - Single-attribute indexes: by_mechanic, by_type, by_class, by_race, by_school, by_cost, by_format
  - Composite indexes: class+type, mechanic+type, race+mechanic
  - `dbf_lookup` dict for O(1) dbfId lookup
  - `get_pool(**filters) → List[Card]` — flexible query
  - `get_by_dbf(dbf_id) → Optional[Card]`
  - `random_pool(size, **filters) → List[Card]` — for discover sampling
  - `stats() → dict` — index statistics
  - Module-level `get_index()` function (lazy singleton)
  - Loads from both `unified_standard.json` and `unified_wild.json`

### Phase 5: Tests
- **5.1** `tests/test_card_cleaner.py` — race normalization, mechanic extraction, school parsing
- **5.2** `tests/test_card_index.py` — index building, queries, edge cases
- **5.3** `tests/test_wild_dedup.py` — wild dedup verification

### Phase 6: Cleanup
- **6.1** Delete 17 migrated scripts from `scripts/`
- **6.2** Delete all `__pycache__/` directories
- **6.3** Migrate 5 test files from `scripts/` to `tests/` (update imports)
- **6.4** Archive superseded design docs (9 files → `thoughts/archive/designs/`)
- **6.5** Archive completed plans (12 files → `thoughts/archive/plans/`)
- **6.6** Archive old ledgers (9 files → `thoughts/archive/ledgers/`)
- **6.7** Delete old log `thoughts/shared/logs/T001.md`
- **6.8** Update README.md to reflect new structure
- **6.9** Run full test suite — verify 0 regressions

### Phase 7: Integration Verification
- **7.1** Clean standard data → rebuild index → query smoke test
- **7.2** Verify V8/V9 engines still work with cleaned data
- **7.3** Git commit all changes

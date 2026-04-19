---
date: 2026-04-19
topic: "Card Data Index + Wild Pool + Cleanup"
status: draft
---

## Problem Statement

Two problems:

1. **No fast card lookup**: The decision engine (V8/V9) needs to query card pools by mechanic, type, class, race, cost — but currently every query means scanning all 1,015 cards in `unified_standard.json`. V8's pool quality, V9's discover branches, and opponent simulation all need structured indexes.

2. **Messy data + missing wild pool**: The `race` field has 93 unique values (should be ~13). `mechanics` only has 29 tags extracted from 28 regex patterns, while `hearthstone_enums.json` defines 56 keywords. Wild format cards don't exist in our data at all.

3. **Technical debt from restructure**: 17 migrated scripts still sit in `scripts/`, 960KB of `__pycache__`, 9+ superseded design docs, 12 completed plans, and 5 test files that need migration to `tests/`.

## Constraints

- **Backward compatible**: All existing tests must pass after changes
- **No external API calls at index time**: Indexes are built from local JSON files
- **Enums as source of truth**: `hearthstone_enums.json` defines the canonical keyword/race/school sets
- **Wild cards from iyingdi only**: Use the existing iyingdi API (just change the format parameter)
- **Dedup by dbfId**: Standard cards appearing in wild pool must be removed from wild
- **All paths via pathlib**: No hardcoded paths

## Approach

### Part 1: Card Data Cleaner

A data cleaning pipeline that:
1. Reads `unified_standard.json` + `hearthstone_enums.json`
2. Normalizes `race` field using the 13 canonical races from enums
3. Re-extracts `mechanics` using all 56 keywords from enums (replacing the current 28-pattern extraction)
4. Extracts spell school from race field for SPELL/LOCATION/HERO cards
5. Writes cleaned data back to `unified_standard.json` (with backup)

### Part 2: Wild Card Fetcher

Extend the iyingdi fetcher to:
1. Fetch all wild-eligible cards (change `standard=1` to `standard=0` or remove it)
2. Normalize using the same pipeline
3. Dedup against standard pool by `dbfId`
4. Save wild-only cards to `unified_wild.json`

### Part 3: CardIndex

A pre-computed in-memory index structure that provides O(1) lookup by any combination of attributes:

```
CardIndex
├── by_mechanic: Dict[str, List[Card]]     # 56 keyword indexes
├── by_type: Dict[str, List[Card]]          # MINION/SPELL/WEAPON/LOCATION/HERO
├── by_class: Dict[str, List[Card]]         # 12 classes + NEUTRAL
├── by_race: Dict[str, List[Card]]          # 13 races (cleaned)
├── by_school: Dict[str, List[Card]]        # 7 spell schools
├── by_cost: Dict[int, List[Card]]          # 0-10+ mana buckets
├── by_format: Dict[str, List[Card]]        # standard/wild
├── composite: Dict[tuple, List[Card]]      # (class, type), (mechanic, type), etc.
└── dbf_lookup: Dict[int, Card]             # dbfId → Card
```

Key query methods:
- `get_pool(mechanics=None, card_class=None, card_type=None, race=None, school=None, cost=None, format=None) → List[Card]`
- `get_by_dbf(dbf_id: int) → Card`
- `random_pool(size: int, **filters) → List[Card]` — for discover/disjoint pool sampling

### Part 4: Cleanup

| Action | Details |
|--------|---------|
| Delete 17 migrated scripts | All have counterparts in `hs_analysis/` |
| Delete `__pycache__/` everywhere | ~960KB stale bytecode |
| Migrate 5 test files to `tests/` | Update imports to `hs_analysis.*` |
| Archive 9 superseded designs | Move to `thoughts/archive/designs/` |
| Archive 12 completed plans | Move to `thoughts/archive/plans/` |
| Archive 9 old ledgers | Move to `thoughts/archive/ledgers/` |
| Delete old logs | `thoughts/shared/logs/T001.md` |
| Update README.md | Reflect new package structure |
| Update PROGRESS.md | Document restructure completion |

## Architecture

### New Files

| File | Purpose |
|------|---------|
| `hs_analysis/data/card_cleaner.py` | Race normalization, mechanic re-extraction, spell school parsing |
| `hs_analysis/data/card_index.py` | CardIndex class with multi-attribute indexes + query API |
| `hs_analysis/data/fetch_wild.py` | Wild card fetcher (extends iyingdi fetch logic) |
| `hs_analysis/data/build_wild_db.py` | Dedup wild vs standard, produce unified_wild.json |

### Modified Files

| File | Changes |
|------|---------|
| `hs_analysis/data/build_unified_db.py` | Use card_cleaner for normalization instead of inline KEYWORD_PATTERNS |

### Data Flow

```
hearthstone_enums.json ──→ CardCleaner ──→ cleaned cards
                                        │
unified_standard.json ─────→ CardCleaner ──→ unified_standard.json (cleaned)
                                        │
iyingdi API (wild) ──→ fetch_wild ──→ normalize ──→ CardCleaner ──→ unified_wild.json
                                        │
                                        └──→ CardIndex (in-memory)
                                              ├── standard pool (1,015 cards)
                                              └── wild-only pool (TBD cards)
```

### Data Cleaning Rules

**Race normalization**:
- Map Chinese race names to canonical English enum IDs (e.g., "野兽" → "BEAST", "恶魔" → "DEMON")
- Split multi-tag values (e.g., "亡灵 野兽" → ["UNDEAD", "BEAST"])
- For SPELL/LOCATION cards with race values like "冰霜"/"火焰" → extract as spell school, set race to ""

**Mechanics re-extraction**:
- Use all 56 keywords from enums as patterns
- Match against `text` field with Chinese keyword names from enums
- Add keyword-specific patterns (e.g., "战吼" → BATTLECRY, "亡语" → DEATHRATTLE, "发现" → DISCOVER)
- Union with existing mechanics (keep any that were from HSJSON source with English tags)

**Spell school extraction**:
- Only for cards with type in [SPELL, LOCATION, HERO]
- Map race field values: "冰霜"→FROST, "火焰"→FIRE, "奥术"→ARCANE, "神圣"→HOLY, "自然"→NATURE, "暗影"→SHADOW, "恶魔"→FEL
- Store in new `spellSchool` field

## Error Handling

- Card cleaner: log warnings for cards that fail normalization, skip them from index (don't crash)
- Wild fetcher: same graceful degradation as existing iyingdi fetcher (retry, sleep between pages)
- CardIndex: returns empty list for queries with no matches (never raises)
- All new code wrapped in try/except with logger.warning, consistent with existing patterns

## Testing Strategy

1. **card_cleaner tests**: Verify race normalization, mechanic extraction, spell school parsing against known cards
2. **card_index tests**: Verify index building, query by single/multiple attributes, empty result handling
3. **wild fetcher tests**: Mock API responses, verify dedup logic
4. **Regression**: Run full existing test suite after cleanup to ensure nothing breaks
5. **Integration**: Load cleaned data → build index → query for discover pool → verify results

## Open Questions

1. Should wild cards be stored in the same `unified_standard.json` with a `format` field, or in a separate `unified_wild.json`? (Leaning toward separate file — cleaner separation)
2. How many cards are in the wild pool? (Unknown until we fetch — could be 5,000+)
3. Should CardIndex be a singleton or module-level instance? (Leaning toward module-level for simplicity)
4. Should we add a `mana_cost` field to replace the ambiguous `cost` field name? (No — YAGNI, `cost` is clear enough in context)

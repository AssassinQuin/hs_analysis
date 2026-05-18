---
date: 2026-04-18
topic: "V7 Score Integration into Downstream Pipeline"
status: validated
---

## Problem Statement

The V7 scoring engine generates `v7_scoring_report.json` but the downstream pipeline (composite evaluator → RHEA) still reads `l6_score`. Worse, no loader exists — no code reads ANY scoring report JSON and populates runtime `Card` objects. Scores are hard-coded in demo/test code.

## Constraints

- **Backward compatible** — L6 scores must keep working; don't remove `l6_score`
- **V7 report uses `dbfId`** (camelCase), Card uses `dbf_id` (snake_case) — loader must handle
- **Minions carry no scores** — when cards are played, score info is discarded. This is existing behavior, won't change minion architecture
- **Multi-objective path** also reads scores via `getattr()` — must update
- **V7 report path**: `hs_cards/v7_scoring_report.json` with key `"v7_score"` per card entry

## Approach: Score Provider Pattern

Instead of simple find-replace, introduce a **ScoreProvider** that knows how to load card scores from the correct source. Benefits:

- Single place to swap V7↔L6↔future
- Lazy loading (loads JSON on first access, caches)
- Clean separation — evaluators don't know where scores come from

**Rejected**: Direct replacement of `l6_score` with `v7_score` on Card. Breaks backward compat and makes A/B comparison hard.

## Architecture

### New Component: `ScoreProvider` (new file: `score_provider.py`)

Responsibilities:
- Load scores from scoring report JSON (lazy, cached)
- Look up card scores by `dbf_id`
- Support multiple score sources (V7, L6) with configurable defaults
- Handle `dbfId`/`dbf_id` naming mismatch

Behavior:
- Construct with source path: `ScoreProvider("hs_cards/v7_scoring_report.json")`
- Lazy-load JSON on first `get_score(dbf_id)` call
- Return `float`, fallback `0.0` if card not found
- Configurable score field name (V7 uses `"v7_score"`, L6 uses `"L6"`)

### Card Dataclass Update (`game_state.py`)

- Add `v7_score: float = 0.0` as new field (alongside `l6_score`)
- Keep `l6_score` and `v2_score` for backward compatibility
- New field is last positional field with default — won't break existing constructors

### Evaluator Switch (`composite_evaluator.py`)

Two read sites switch from `l6_score` to `v7_score`:
- `evaluate()` — `sum(c.l6_score ...)` → `sum(c.v7_score ...)`
- `quick_eval()` — `sum(c.l6_score ...)` → `sum(c.v7_score ...)`

Weight key rename: `w_v2` → `w_v7` for semantic clarity.
Variable rename: `hand_v2`/`v2_adj` → `hand_v7`/`v7_adj`.

### Multi-Objective Switch (`multi_objective_evaluator.py`)

- `getattr(c, "l6_score", 0.0)` → `getattr(c, "v7_score", 0.0)`

### Score Loading Bridge (in `score_provider.py`)

Convenience function `load_scores_into_hand(hand, source="v7")`:
- Constructs correct `ScoreProvider`
- Iterates each `Card` in `GameState.hand`
- Populates `card.v7_score` with loaded score
- Connects the provider to Card objects

### RHEA Engine Entry Point Update (`rhea_engine.py`)

- `RHEAEngine` constructor or `search()` should call `load_scores_into_hand()` before evaluation
- Ensures cards have scores before RHEA touches them

## Data Flow

```
v7_scoring_report.json
        ↓
   ScoreProvider (lazy loads, caches by dbf_id)
        ↓
   load_scores_into_hand(state.hand)
        ↓
   Card.v7_score populated on each card
        ↓
   composite_evaluator.evaluate() reads c.v7_score
        ↓
   RHEA._evaluate_chromosome() → evaluate_delta() → evaluate()
        ↓
   Fitness score drives chromosome selection
```

## Error Handling

- **JSON not found**: ScoreProvider logs warning, returns `0.0` for all scores. Evaluator degrades gracefully (hand quality component zeroes out, other sub-models still work)
- **Missing card**: If `dbf_id` not in report, return `0.0` — matches current default behavior
- **Malformed score**: Try/except float conversion, return `0.0` and log warning

## Testing Strategy

- **Unit tests**: ScoreProvider with temp JSON — verify lazy loading, caching, dbfId mapping, missing cards
- **Integration tests**: Update existing test fixtures to use `v7_score` instead of `l6_score`
- **Regression**: Verify evaluator still produces same structure with `v7_score=0.0` (empty hand case)
- **A/B comparison**: Keep `l6_score` field so we can compare V7 vs L6 results side-by-side

## Open Questions

None. Design is straightforward. The minion evaluation is intentionally independent of pre-computed scores — minions are evaluated from raw stats by the board control sub-model, which is correct for board state evaluation.

## All Touch Points (Complete List)

1. **NEW FILE**: `score_provider.py` — ScoreProvider class + load_scores_into_hand()
2. `game_state.py:57` — add `v7_score: float = 0.0` to Card dataclass
3. `composite_evaluator.py:105` — change `c.l6_score` to `c.v7_score`
4. `composite_evaluator.py:139` — change `c.l6_score` to `c.v7_score`
5. `composite_evaluator.py:76` — rename weight key `w_v2` to `w_v7`
6. `composite_evaluator.py:116` — update weight key reference
7. `composite_evaluator.py:170,172` — demo data: `l6_score=` → `v7_score=`
8. `multi_objective_evaluator.py:95` — change `getattr(c, "l6_score")` to `getattr(c, "v7_score")`
9. `multi_objective_evaluator.py:281` — demo data update
10. `test_integration.py:109` — test helper: `l6_score=` → `v7_score=`
11. `test_integration.py:631-632` — test fixtures update
12. `test_integration.py:756-757` — test fixtures update
13. `rhea_engine.py` — call `load_scores_into_hand()` in search pipeline

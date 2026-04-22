# V7 Score Integration — Implementation Plan

**Goal:** Wire V7 scoring report into the downstream pipeline so evaluators read `v7_score` instead of `l6_score`, via a new `ScoreProvider` class.

**Architecture:** Introduce a `ScoreProvider` (lazy-loading JSON cache) that maps `dbfId` → score. A bridge function `load_scores_into_hand()` populates `Card.v7_score` fields. Evaluators switch from `l6_score` to `v7_score`. Backward compat preserved — `l6_score` field stays on `Card`.

**Design:** [thoughts/shared/designs/2026-04-18-v7-score-integration-design.md](../designs/2026-04-18-v7-score-integration-design.md)

---

## Dependency Graph

```
Batch 1 (parallel): 1.1 [Card dataclass field], 1.2 [ScoreProvider + test]
  → 1.1 has zero deps (just adds a defaulted field)
  → 1.2 has zero deps (imports game_state, but only for type hints — file is self-contained)

Batch 2 (parallel): 2.1 [composite_evaluator], 2.2 [multi_objective_evaluator], 2.3 [test_integration fixtures]
  → All depend on 1.1 (Card now has v7_score field)
  → Independent of each other

Batch 3 (sequential): 3.1 [rhea_engine score loading]
  → Depends on 1.2 (imports ScoreProvider) and 2.1 (calls composite_evaluator)

Batch 4 (sequential): 4.1 [end-to-end smoke test]
  → Depends on everything above
```

---

## Batch 1: Foundation (2 implementers, parallel)

### Task 1.1: Add `v7_score` field to Card dataclass

**File:** `scripts/game_state.py`  
**Test:** Verified by existing `python3 scripts/game_state.py` self-test (no new test needed — field has default, nothing breaks)  
**Depends:** none

**Implementation** — Add `v7_score: float = 0.0` as the last field before `text` on the `Card` dataclass (line ~45):

```python
# scripts/game_state.py — Card dataclass (lines 42-51 currently)
@dataclass
class Card:
    """A card in hand."""

    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    original_cost: int = 0
    card_type: str = ""  # MINION, SPELL, WEAPON, HERO
    attack: int = 0
    health: int = 0
    v2_score: float = 0.0
    l6_score: float = 0.0
    v7_score: float = 0.0   # <-- NEW FIELD (V7 scoring report score)
    text: str = ""
```

**Why after `l6_score`, before `text`:** Keeps score fields grouped. Field has a default so ALL existing constructors (positional and keyword) remain valid.

**Verify:** `python3 scripts/game_state.py`  
**Commit:** `feat(card): add v7_score field to Card dataclass`

---

### Task 1.2: Create ScoreProvider module with tests

**File:** `scripts/score_provider.py` (NEW FILE)  
**Test:** `scripts/test_score_provider.py` (NEW FILE)  
**Depends:** none (imports `game_state.Card` for type hint only)

**Implementation:**

```python
# scripts/score_provider.py
"""ScoreProvider — loads card scores from V7 (or L6) scoring report JSON.

Lazy-loads on first access, caches by dbf_id. Handles the camelCase
dbfId / snake_case dbf_id naming mismatch between report and Card.

Usage:
    from score_provider import ScoreProvider, load_scores_into_hand

    provider = ScoreProvider("hs_cards/v7_scoring_report.json")
    score = provider.get_score(123146)   # returns 32.131

    # Or bulk-load into a GameState hand:
    load_scores_into_hand(state, source="v7")
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Dict, List, Optional

# Ensure sibling modules importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_state import Card  # type: ignore[import]

logger = logging.getLogger(__name__)

# Default paths relative to project root
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_V7_PATH = os.path.join(_PROJECT_ROOT, "hs_cards", "v7_scoring_report.json")


class ScoreProvider:
    """Lazy-loading, cached score lookup from a scoring report JSON.

    Parameters
    ----------
    report_path : str
        Path to the scoring report JSON (e.g. v7_scoring_report.json).
    score_field : str
        Key to read from each card entry in the JSON.
        V7 uses "v7_score", L6 uses "L6".
    """

    def __init__(self, report_path: str = DEFAULT_V7_PATH, score_field: str = "v7_score"):
        self._report_path = report_path
        self._score_field = score_field
        self._cache: Optional[Dict[int, float]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_score(self, dbf_id: int) -> float:
        """Return the score for *dbf_id*, or 0.0 if not found."""
        if self._cache is None:
            self._load()
        return self._cache.get(dbf_id, 0.0)

    def load_into_hand(self, hand: List[Card]) -> int:
        """Populate card.v7_score for every Card in *hand*.

        Returns the number of cards that received a non-zero score.
        """
        if self._cache is None:
            self._load()
        loaded = 0
        for card in hand:
            score = self._cache.get(card.dbf_id, 0.0)
            card.v7_score = score
            if score != 0.0:
                loaded += 1
        return loaded

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Parse JSON, build dbf_id → score mapping. Logs warnings on errors."""
        self._cache = {}
        if not os.path.isfile(self._report_path):
            logger.warning("ScoreProvider: report not found at %s — all scores default to 0.0",
                           self._report_path)
            return

        try:
            with open(self._report_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("ScoreProvider: failed to read %s — %s", self._report_path, exc)
            return

        if not isinstance(data, list):
            logger.warning("ScoreProvider: expected a JSON array at top level, got %s",
                           type(data).__name__)
            return

        for entry in data:
            # Handle camelCase "dbfId" in report vs snake_case "dbf_id" on Card
            dbf_id = entry.get("dbfId") or entry.get("dbf_id")
            if dbf_id is None:
                continue
            try:
                dbf_id = int(dbf_id)
            except (TypeError, ValueError):
                continue

            raw_score = entry.get(self._score_field, 0.0)
            try:
                score = float(raw_score)
            except (TypeError, ValueError):
                logger.warning("ScoreProvider: malformed score for dbf_id=%s: %r",
                               dbf_id, raw_score)
                score = 0.0

            self._cache[dbf_id] = score


# ======================================================================
# Convenience bridge function
# ======================================================================

def load_scores_into_hand(state_or_hand, source: str = "v7", report_path: Optional[str] = None):
    """Load scores from the scoring report into Card.v7_score fields.

    Parameters
    ----------
    state_or_hand : GameState | list[Card]
        Either a GameState (uses state.hand) or a list of Cards directly.
    source : str
        "v7" or "l6" — determines which score field to read from the JSON.
    report_path : str | None
        Override the default report path.
    """
    from game_state import GameState  # type: ignore[import]

    if isinstance(state_or_hand, GameState):
        hand = state_or_hand.hand
    elif isinstance(state_or_hand, list):
        hand = state_or_hand
    else:
        raise TypeError(f"Expected GameState or list[Card], got {type(state_or_hand).__name__}")

    # Map source to score field name in JSON
    field_map = {"v7": "v7_score", "l6": "L6"}
    score_field = field_map.get(source.lower(), source)

    path = report_path or DEFAULT_V7_PATH
    provider = ScoreProvider(report_path=path, score_field=score_field)
    provider.load_into_hand(hand)


# ======================================================================
# Self-test
# ======================================================================

if __name__ == "__main__":
    import tempfile

    errors: list[str] = []

    # Test 1: ScoreProvider with temp JSON
    sample_data = [
        {"dbfId": 123, "name": "Test Card A", "v7_score": 4.5, "L6": 3.0},
        {"dbfId": 456, "name": "Test Card B", "v7_score": 7.2, "L6": 6.1},
        {"dbf_id": 789, "name": "Snake Case Card", "v7_score": 2.0, "L6": 1.5},
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(sample_data, f)
        tmp_path = f.name

    try:
        # 1a. V7 scores
        sp = ScoreProvider(tmp_path, score_field="v7_score")
        assert sp.get_score(123) == 4.5, f"Expected 4.5, got {sp.get_score(123)}"
        assert sp.get_score(456) == 7.2
        assert sp.get_score(789) == 2.0, "snake_case dbf_id not handled"
        assert sp.get_score(999) == 0.0, "missing card should return 0.0"

        # 1b. L6 scores
        sp_l6 = ScoreProvider(tmp_path, score_field="L6")
        assert sp_l6.get_score(123) == 3.0
        assert sp_l6.get_score(456) == 6.1

        # 1c. Lazy loading — cache starts None
        sp2 = ScoreProvider(tmp_path)
        assert sp2._cache is None, "Should not load until first access"
        _ = sp2.get_score(123)
        assert sp2._cache is not None, "Should load on first access"

        # 1d. load_into_hand
        cards = [Card(dbf_id=123, name="A"), Card(dbf_id=456, name="B"), Card(dbf_id=999, name="Missing")]
        count = sp.load_into_hand(cards)
        assert cards[0].v7_score == 4.5, f"Expected 4.5, got {cards[0].v7_score}"
        assert cards[1].v7_score == 7.2
        assert cards[2].v7_score == 0.0
        assert count == 2, f"Expected 2 loaded, got {count}"

    finally:
        os.unlink(tmp_path)

    # Test 2: Missing file — graceful degradation
    sp_missing = ScoreProvider("/nonexistent/path.json")
    assert sp_missing.get_score(1) == 0.0, "Missing file should return 0.0"

    # Test 3: Malformed score
    bad_data = [{"dbfId": 100, "v7_score": "not_a_number"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(bad_data, f)
        tmp_bad = f.name
    try:
        sp_bad = ScoreProvider(tmp_bad, score_field="v7_score")
        assert sp_bad.get_score(100) == 0.0, "Malformed score should default to 0.0"
    finally:
        os.unlink(tmp_bad)

    if errors:
        print("❌ Tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("✅ All score_provider tests passed.")
```

**Test file:**

```python
# scripts/test_score_provider.py
#!/usr/bin/env python3
"""Unit tests for score_provider module.

Run: python3 scripts/test_score_provider.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_state import Card, GameState
from score_provider import ScoreProvider, load_scores_into_hand


def test_basic_lookup():
    """V7 scores loaded and returned by dbf_id."""
    data = [
        {"dbfId": 100, "v7_score": 5.5, "L6": 3.0},
        {"dbfId": 200, "v7_score": 8.1, "L6": 7.0},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="v7_score")
        assert sp.get_score(100) == 5.5
        assert sp.get_score(200) == 8.1
        assert sp.get_score(999) == 0.0
    finally:
        os.unlink(path)


def test_snake_case_dbf_id():
    """Handle entries using dbf_id (snake_case) instead of dbfId (camelCase)."""
    data = [{"dbf_id": 300, "v7_score": 2.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="v7_score")
        assert sp.get_score(300) == 2.0
    finally:
        os.unlink(path)


def test_lazy_loading():
    """Cache is None until first get_score call."""
    data = [{"dbfId": 1, "v7_score": 1.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path)
        assert sp._cache is None
        sp.get_score(1)
        assert sp._cache is not None
    finally:
        os.unlink(path)


def test_missing_file():
    """Missing JSON file returns 0.0 for all scores (graceful degradation)."""
    sp = ScoreProvider("/nonexistent/file.json")
    assert sp.get_score(1) == 0.0
    assert sp.get_score(2) == 0.0


def test_malformed_score():
    """Non-numeric score defaults to 0.0 without crashing."""
    data = [{"dbfId": 10, "v7_score": "bad"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="v7_score")
        assert sp.get_score(10) == 0.0
    finally:
        os.unlink(path)


def test_malformed_dbf_id():
    """Non-numeric dbfId is skipped gracefully."""
    data = [{"dbfId": "not_a_number", "v7_score": 5.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="v7_score")
        assert sp.get_score(0) == 0.0  # nothing loaded
    finally:
        os.unlink(path)


def test_load_into_hand():
    """load_into_hand populates card.v7_score for matched cards."""
    data = [
        {"dbfId": 500, "v7_score": 3.3},
        {"dbfId": 501, "v7_score": 6.6},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="v7_score")
        cards = [Card(dbf_id=500, name="A"), Card(dbf_id=501, name="B"), Card(dbf_id=999, name="Missing")]
        count = sp.load_into_hand(cards)
        assert cards[0].v7_score == 3.3
        assert cards[1].v7_score == 6.6
        assert cards[2].v7_score == 0.0
        assert count == 2
    finally:
        os.unlink(path)


def test_load_scores_into_hand_with_gamestate():
    """Convenience function works with a GameState object."""
    data = [{"dbfId": 600, "v7_score": 9.9}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        state = GameState(hand=[Card(dbf_id=600, name="Test")])
        load_scores_into_hand(state, source="v7", report_path=path)
        assert state.hand[0].v7_score == 9.9
    finally:
        os.unlink(path)


def test_load_scores_into_hand_with_list():
    """Convenience function works with a plain list of Cards."""
    data = [{"dbfId": 700, "v7_score": 4.4}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        cards = [Card(dbf_id=700, name="Test")]
        load_scores_into_hand(cards, source="v7", report_path=path)
        assert cards[0].v7_score == 4.4
    finally:
        os.unlink(path)


def test_l6_source():
    """Source='l6' reads the L6 field from JSON."""
    data = [{"dbfId": 800, "v7_score": 10.0, "L6": 5.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="L6")
        assert sp.get_score(800) == 5.0
    finally:
        os.unlink(path)


def test_empty_json_array():
    """Empty JSON array produces empty cache — all scores 0.0."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([], f)
        path = f.name
    try:
        sp = ScoreProvider(path)
        assert sp.get_score(1) == 0.0
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for func in test_funcs:
        try:
            func()
            print(f"  ✅ {func.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {func.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {func.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
```

**Verify:** `python3 scripts/test_score_provider.py`  
**Commit:** `feat(scores): add ScoreProvider with lazy-loading and load_scores_into_hand`

---

## Batch 2: Evaluator Switches (3 implementers, parallel)

All tasks in this batch depend on **Task 1.1** (Card now has `v7_score` field).

### Task 2.1: Switch composite_evaluator from l6_score to v7_score

**File:** `scripts/composite_evaluator.py`  
**Test:** `python3 scripts/composite_evaluator.py` (built-in self-test)  
**Depends:** 1.1

**Changes (6 edit sites):**

**Edit A — Weight key rename (line 76):** `"w_v2"` → `"w_v7"`
```python
# BEFORE (line 76):
    "w_v2":        1.0,
# AFTER:
    "w_v7":        1.0,
```

**Edit B — evaluate() function (lines 96, 105-106, 116):**
```python
# BEFORE (line 96 comment):
    v2_adj      – V2+L6 adjusted scores of hand cards + board minions
# AFTER:
    v7_adj      – V7 adjusted scores of hand cards + board minions

# BEFORE (line 105):
    hand_v2 = sum(c.l6_score for c in state.hand)
    v2_adj = hand_v2
# AFTER:
    hand_v7 = sum(c.v7_score for c in state.hand)
    v7_adj = hand_v7

# BEFORE (line 116):
        w["w_v2"]        * v2_adj
# AFTER:
        w["w_v7"]        * v7_adj
```

**Edit C — quick_eval() function (lines 139, 141):**
```python
# BEFORE (line 139):
    v2_adj = sum(c.l6_score for c in state.hand)
    threat = -(max(0, 30 - state.hero.hp - state.hero.armor) * 0.5)
    return v2_adj + 1.5 * threat
# AFTER:
    v7_adj = sum(c.v7_score for c in state.hand)
    threat = -(max(0, 30 - state.hero.hp - state.hero.armor) * 0.5)
    return v7_adj + 1.5 * threat
```

**Edit D — Demo data (lines 170, 172):**
```python
# BEFORE (line 170):
            Card(dbf_id=1, name="Fireball", cost=4, original_cost=4,
                 card_type="spell", attack=0, health=0, l6_score=5.2, text="Deal 6 damage."),
            Card(dbf_id=2, name="Frostbolt", cost=2, original_cost=2,
                 card_type="spell", attack=0, health=0, l6_score=3.1, text="Deal 3 damage."),
# AFTER:
            Card(dbf_id=1, name="Fireball", cost=4, original_cost=4,
                 card_type="spell", attack=0, health=0, v7_score=5.2, text="Deal 6 damage."),
            Card(dbf_id=2, name="Frostbolt", cost=2, original_cost=2,
                 card_type="spell", attack=0, health=0, v7_score=3.1, text="Deal 3 damage."),
```

**Edit E — Custom weights demo (line 249):**
```python
# BEFORE (line 249):
    custom_w = {"w_v2": 2.0, "w_threat": 3.0}
# AFTER:
    custom_w = {"w_v7": 2.0, "w_threat": 3.0}
```

**Edit F — Custom weights print (line 251):**
```python
# BEFORE (line 251):
    print(f"\n--- Custom weights (w_v2=2, w_threat=3) ---")
# AFTER:
    print(f"\n--- Custom weights (w_v7=2, w_threat=3) ---")
```

**Verify:** `python3 scripts/composite_evaluator.py`  
**Commit:** `feat(evaluator): switch composite_evaluator from l6_score to v7_score`

---

### Task 2.2: Switch multi_objective_evaluator from l6_score to v7_score

**File:** `scripts/multi_objective_evaluator.py`  
**Test:** `python3 scripts/multi_objective_evaluator.py` (built-in self-test)  
**Depends:** 1.1

**Changes (2 edit sites):**

**Edit A — eval_value() getattr (line 95):**
```python
# BEFORE:
    hand_quality = sum(getattr(c, "l6_score", 0.0) for c in state.hand)
# AFTER:
    hand_quality = sum(getattr(c, "v7_score", 0.0) for c in state.hand)
```

**Edit B — Self-test demo data (line 281):**
```python
# BEFORE:
            Card(name="Fireball", cost=4, card_type="SPELL", l6_score=5.0),
# AFTER:
            Card(name="Fireball", cost=4, card_type="SPELL", v7_score=5.0),
```

**Also update the self-test comment (line 220):**
```python
# BEFORE:
    # v_value = 0 (no l6_scores) + 0*3 + 0*2 = 0
# AFTER:
    # v_value = 0 (no v7_scores) + 0*3 + 0*2 = 0
```

**Verify:** `python3 scripts/multi_objective_evaluator.py`  
**Commit:** `feat(evaluator): switch multi_objective_evaluator from l6_score to v7_score`

---

### Task 2.3: Update test_integration.py fixtures

**File:** `scripts/test_integration.py`  
**Test:** `python3 scripts/test_integration.py`  
**Depends:** 1.1

**Changes (5 edit sites):**

**Edit A — create_test_card helper (line 109):**
```python
# BEFORE:
        l6_score=kwargs.get("l6_score", 0.0),
# AFTER:
        l6_score=kwargs.get("l6_score", 0.0),
        v7_score=kwargs.get("v7_score", kwargs.get("l6_score", 0.0)),
```

**Design decision:** The helper now also populates `v7_score`. If caller passes `v7_score=` explicitly, that's used. If they pass `l6_score=` (backward compat), that value is mirrored to `v7_score`. This means existing test calls like `create_test_card(..., l6_score=2.0)` will automatically set `v7_score=2.0` too — no need to update every single call site. Callers can override with explicit `v7_score=` if they want different values.

**Edit B — test_multi_objective_tradeoff (lines 631-632):**
```python
# BEFORE:
    heal_spell = create_test_card(9002, "Healing Touch", 2, "SPELL", text="恢复8点", l6_score=2.0)
    big_minion = create_test_card(9003, "Big Minion", 4, "MINION", attack=5, health=5, l6_score=4.0)
# AFTER (these still work as-is because Edit A mirrors l6_score → v7_score,
#         but for clarity, switch to explicit v7_score):
    heal_spell = create_test_card(9002, "Healing Touch", 2, "SPELL", text="恢复8点", v7_score=2.0)
    big_minion = create_test_card(9003, "Big Minion", 4, "MINION", attack=5, health=5, v7_score=4.0)
```

**Edit C — test_multi_turn_lethal_setup (lines 756-757):**
```python
# BEFORE:
    big_minion = create_test_card(9004, "Big Minion", 4, "MINION", attack=6, health=6, l6_score=5.0)
    damage_spell = create_test_card(9005, "Pyroblast", 6, "SPELL", text="造成10点伤害", l6_score=6.0)
# AFTER:
    big_minion = create_test_card(9004, "Big Minion", 4, "MINION", attack=6, health=6, v7_score=5.0)
    damage_spell = create_test_card(9005, "Pyroblast", 6, "SPELL", text="造成10点伤害", v7_score=6.0)
```

**Verify:** `python3 scripts/test_integration.py`  
**Commit:** `test: update test fixtures from l6_score to v7_score`

---

## Batch 3: RHEA Engine Integration (1 implementer)

### Task 3.1: Wire ScoreProvider into RHEA engine

**File:** `scripts/rhea_engine.py`  
**Test:** `python3 scripts/rhea_engine.py` (built-in self-test) + `python3 scripts/test_integration.py`  
**Depends:** 1.2 (imports ScoreProvider), 2.1 (composite_evaluator now reads v7_score)

**Changes:**

**Edit A — Add import (after existing imports, ~line 27):**
```python
# ADD after "from multi_objective_evaluator import ...":
from score_provider import load_scores_into_hand  # type: ignore[import]
```

**Edit B — In search() method, load scores before population init (insert after `t_start` line, before `# Initialise population`):**
```python
# BEFORE (line 383-386):
        """Run the RHEA evolutionary search and return the best action plan."""
        t_start = time.perf_counter()

        # Initialise population
        population = self._init_population(initial_state)

# AFTER:
        """Run the RHEA evolutionary search and return the best action plan."""
        t_start = time.perf_counter()

        # Load V7 scores into hand cards so evaluators see them
        load_scores_into_hand(initial_state, source="v7")

        # Initialise population
        population = self._init_population(initial_state)
```

**Why here:** `search()` is the single public entry point. Loading scores here ensures every chromosome evaluation sees populated `v7_score` fields. The call is idempotent — `load_scores_into_hand` creates a fresh `ScoreProvider` each time, but the lazy cache means it only reads the JSON once per call.

**Design decision:** I chose to call `load_scores_into_hand` at the top of `search()` rather than in `__init__` because: (a) the engine might be reused across different GameStates, (b) the state's hand can change between calls, (c) this is the design's specified location ("constructor or search()"). The `search()` approach is cleaner.

**Verify:** `python3 scripts/rhea_engine.py`  
**Commit:** `feat(rhea): wire ScoreProvider into RHEA search pipeline`

---

## Batch 4: End-to-End Verification (1 implementer)

### Task 4.1: Run full pipeline smoke test

**File:** No file changes — verification only  
**Depends:** All previous tasks

**Verification steps:**

```bash
# 1. ScoreProvider unit tests
python3 scripts/test_score_provider.py

# 2. game_state self-test (Card dataclass unchanged for existing code)
python3 scripts/game_state.py

# 3. composite_evaluator self-test (now reads v7_score)
python3 scripts/composite_evaluator.py

# 4. multi_objective_evaluator self-test (now reads v7_score)
python3 scripts/multi_objective_evaluator.py

# 5. RHEA engine self-test (now loads V7 scores)
python3 scripts/rhea_engine.py

# 6. Full integration test suite
python3 scripts/test_integration.py
```

**Expected outcomes:**
- All 6 commands exit with code 0
- `test_score_provider.py`: All 10 unit tests pass
- `composite_evaluator.py`: Populated board scores higher than empty (same as before, just using v7_score)
- `rhea_engine.py`: Search finds lethal (same as before, but now using V7-loaded scores)
- `test_integration.py`: All integration scenarios pass

**Commit:** (no commit — verification only)

---

## Summary of All Files Changed

| File | Action | Batch | Lines Changed |
|------|--------|-------|---------------|
| `scripts/game_state.py` | Modify | 1.1 | 1 line added |
| `scripts/score_provider.py` | **New** | 1.2 | ~170 lines |
| `scripts/test_score_provider.py` | **New** | 1.2 | ~170 lines |
| `scripts/composite_evaluator.py` | Modify | 2.1 | ~12 lines changed |
| `scripts/multi_objective_evaluator.py` | Modify | 2.2 | ~3 lines changed |
| `scripts/test_integration.py` | Modify | 2.3 | ~7 lines changed |
| `scripts/rhea_engine.py` | Modify | 3.1 | ~3 lines added |

**Total: 2 new files, 5 modified files, ~370 lines of new code, ~25 lines changed**

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

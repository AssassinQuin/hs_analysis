# hs_analysis/utils/score_provider.py
"""ScoreProvider — loads card scores from V7 (or L6) scoring report JSON.

Lazy-loads on first access, caches by dbf_id. Handles the camelCase
dbfId / snake_case dbf_id naming mismatch between report and Card.

Usage:
    from hs_analysis.utils.score_provider import ScoreProvider, load_scores_into_hand

    provider = ScoreProvider("hs_cards/v7_scoring_report.json")
    score = provider.get_score(123146)   # returns 32.131

    # Or bulk-load into a GameState hand:
    load_scores_into_hand(state, source="v7")
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional

from hs_analysis.config import PROJECT_ROOT, V7_REPORT_PATH
from hs_analysis.models.card import Card

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default path from centralised config
DEFAULT_V7_PATH = str(V7_REPORT_PATH)


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
    # Deferred import to avoid circular dependency at module level
    from hs_analysis.search.game_state import GameState  # type: ignore[import]

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

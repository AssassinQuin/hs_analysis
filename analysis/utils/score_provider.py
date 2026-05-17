"""ScoreProvider — loads card scores from scoring report JSON.

Lazy-loads on first access, caches by dbf_id. Handles the camelCase
dbfId / snake_case dbf_id naming mismatch between report and Card.

Usage:
    from analysis.utils.score_provider import ScoreProvider, load_scores_into_hand

    provider = ScoreProvider()
    score = provider.get_score(123146)

    load_scores_into_hand(state)
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional

from analysis.config import PROJECT_ROOT, SCORING_REPORT_PATH
from analysis.models.card import Card

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_REPORT_PATH = str(SCORING_REPORT_PATH)


class ScoreProvider:
    """Lazy-loading, cached score lookup from a scoring report JSON.

    Parameters
    ----------
    report_path : str
        Path to the scoring report JSON.
    score_field : str
        Key to read from each card entry in the JSON.
        Default is "score".
    """

    def __init__(self, report_path: str = DEFAULT_REPORT_PATH, score_field: str = "score"):
        self._report_path = report_path
        self._score_field = score_field
        self._cache: Optional[Dict[int, float]] = None

    def get_score(self, dbf_id: int) -> float:
        """Return the score for *dbf_id*, or 0.0 if not found."""
        if self._cache is None:
            self._load()
        return self._cache.get(dbf_id, 0.0)

    def load_into_hand(self, hand: List[Card]) -> int:
        """Populate card.score for every Card in *hand*.

        Returns the number of cards that received a non-zero score.
        """
        if self._cache is None:
            self._load()
        loaded = 0
        for card in hand:
            score = self._cache.get(card.dbf_id, 0.0)
            card.score = score
            if score != 0.0:
                loaded += 1
        return loaded

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


_PROVIDERS: Dict[str, "ScoreProvider"] = {}


def _get_provider(report_path: str, score_field: str) -> "ScoreProvider":
    global _PROVIDERS
    key = f"{report_path}|{score_field}"
    if key not in _PROVIDERS:
        _PROVIDERS[key] = ScoreProvider(report_path=report_path, score_field=score_field)
    return _PROVIDERS[key]


def load_scores_into_hand(state_or_hand, report_path: Optional[str] = None):
    from analysis.search.game_state import GameState

    if isinstance(state_or_hand, GameState):
        hand = state_or_hand.hand
    elif isinstance(state_or_hand, list):
        hand = state_or_hand
    else:
        raise TypeError(f"Expected GameState or list[Card], got {type(state_or_hand).__name__}")

    path = report_path or DEFAULT_REPORT_PATH
    provider = _get_provider(path, "score")
    provider.load_into_hand(hand)

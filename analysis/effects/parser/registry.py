"""registry.py — Card metadata lookup by card_id.

Wraps CardDB / cards.collectible.json for effect system consumption.
Returns raw dict metadata (no Card model objects).

This is the ONLY file in the effects package that touches external data sources.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default card data directory (card_data/<BUILD>/enUS/cards.collectible.json)
_DEFAULT_DATA_DIR: Path = (Path(__file__).parent.parent.parent.parent
                           / "card_data" / "241958")


def _default_data_dir() -> str:
    return str(_DEFAULT_DATA_DIR)


class CardLookup:
    """Minimal card metadata lookup by card_id.

    Uses the enUS cards.collectible.json as the authoritative source.
    Falls back to cards.json if card_id not found in collectible set.
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self._data_dir = data_dir or _default_data_dir()
        self._collectible: dict[str, dict[str, Any]] | None = None
        self._all_cards: dict[str, dict[str, Any]] | None = None

    # ── Public API ────────────────────────────────────────────

    def get_metadata(self, card_id: str) -> dict[str, Any] | None:
        """Get raw card metadata dict by card_id.

        Returns card dict with keys like id, name, cost, type, text, etc.
        Returns None if card_id is unknown.
        """
        # Lazy load
        if self._collectible is None:
            self._load_collectible()

        card = self._collectible.get(card_id)
        if card is not None:
            return card

        # Fallback: try full cards.json
        if self._all_cards is None:
            self._load_all_cards()
        return self._all_cards.get(card_id) if self._all_cards else None

    def search(self, **filters: Any) -> list[dict[str, Any]]:
        """Search cards by field filters.

        Example:
            lookup.search(type="MINION", cost=2, mechanics=["BATTLECRY"])
        """
        if self._collectible is None:
            self._load_collectible()

        results: list[dict[str, Any]] = []
        for card in self._collectible.values():
            match = True
            for key, val in filters.items():
                if key == "mechanics":
                    if not val:
                        continue
                    card_mechs = set(card.get("mechanics", []))
                    required = set(val) if isinstance(val, list) else {val}
                    if not required.issubset(card_mechs):
                        match = False
                        break
                elif card.get(key) != val:
                    match = False
                    break
            if match:
                results.append(card)
        return results

    # ── Data loading ──────────────────────────────────────────

    def _load_collectible(self) -> None:
        path = Path(self._data_dir) / "enUS" / "cards.collectible.json"
        if not path.exists():
            log.warning("Collectible cards not found at %s", path)
            self._collectible = {}
            return
        try:
            cards: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
            self._collectible = {c["id"]: c for c in cards if "id" in c}
            log.info("CardLookup: loaded %d collectible cards", len(self._collectible))
        except Exception as exc:
            log.error("Failed to load %s: %s", path, exc)
            self._collectible = {}

    def _load_all_cards(self) -> None:
        path = Path(self._data_dir) / "enUS" / "cards.json"
        if not path.exists():
            self._all_cards = {}
            return
        try:
            cards: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
            self._all_cards = {c["id"]: c for c in cards if "id" in c}
            log.info("CardLookup: loaded %d total cards", len(self._all_cards))
        except Exception as exc:
            log.error("Failed to load %s: %s", path, exc)
            self._all_cards = {}


# ── Module-level singleton ────────────────────────────────────

_LOOKUP: CardLookup | None = None


def get_lookup() -> CardLookup:
    global _LOOKUP
    if _LOOKUP is None:
        _LOOKUP = CardLookup()
    return _LOOKUP

#!/usr/bin/env python3
"""Build wild-only card database by deduplicating against standard pool.

Reads ``iyingdi_all_normalized.json`` (all cards) and removes any card
whose ``dbfId`` exists in ``unified_standard.json``.  Also removes cards
that are standard-only (``standard=1, wild=0``).  The remaining wild-only
cards are written to ``unified_wild.json``.

Then runs the card cleaner on the wild cards for race/mechanic normalization.

Usage::

    python -m hs_analysis.data.build_wild_db
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Set

from ..config import DATA_DIR

logger = logging.getLogger(__name__)


def load_dbfids(path: Path) -> Set[int]:
    """Load a set of dbfIds from a JSON card array."""
    if not path.exists():
        return set()
    cards: List[Dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    ids = set()
    for c in cards:
        dbf = c.get("dbfId")
        if dbf is not None:
            ids.add(int(dbf))
    return ids


def build_wild_db(
    all_cards_path: Path | None = None,
    standard_path: Path | None = None,
    output_path: Path | None = None,
    run_cleaner: bool = True,
) -> Dict[str, Any]:
    """Build the wild-only card database.

    Args:
        all_cards_path:  Normalized all-cards file from ``fetch_wild``.
        standard_path:   Standard pool to dedup against.
        output_path:     Where to write wild-only cards.
        run_cleaner:     Whether to apply card_cleaner to wild cards.

    Returns:
        Statistics dict.
    """
    if all_cards_path is None:
        all_cards_path = DATA_DIR / "iyingdi_all_normalized.json"
    if standard_path is None:
        standard_path = DATA_DIR / "unified_standard.json"
    if output_path is None:
        output_path = DATA_DIR / "unified_wild.json"

    # Load standard dbfIds for dedup
    standard_dbfids = load_dbfids(standard_path)
    logger.info("Standard pool: %d unique dbfIds", len(standard_dbfids))

    # Load all cards
    if not all_cards_path.exists():
        raise FileNotFoundError(
            f"All-cards file not found: {all_cards_path}\n"
            "Run fetch_wild first: python -m hs_analysis.data.fetch_wild"
        )

    all_cards: List[Dict[str, Any]] = json.loads(
        all_cards_path.read_text(encoding="utf-8")
    )
    logger.info("All cards loaded: %d", len(all_cards))

    # Filter: keep only wild-eligible, non-standard cards
    wild_cards: List[Dict[str, Any]] = []
    skipped_standard = 0
    skipped_no_wild = 0
    skipped_no_dbf = 0

    for card in all_cards:
        dbf = card.get("dbfId")

        # Skip cards without dbfId
        if dbf is None:
            skipped_no_dbf += 1
            continue

        dbf_int = int(dbf)

        # Skip cards already in standard pool (dedup)
        if dbf_int in standard_dbfids:
            skipped_standard += 1
            continue

        # Skip cards that are not wild-eligible
        if not card.get("wild"):
            skipped_no_wild += 1
            continue

        # Remove standard/wild helper fields before saving
        cleaned = {k: v for k, v in card.items()
                   if k not in ("standard", "wild")}
        cleaned["format"] = "wild"
        wild_cards.append(cleaned)

    # Optionally run card cleaner on wild cards
    if run_cleaner and wild_cards:
        try:
            from .card_cleaner import clean_card
            for card in wild_cards:
                clean_card(card)
            logger.info("Applied card_cleaner to %d wild cards", len(wild_cards))
        except ImportError:
            logger.warning("card_cleaner not available, skipping cleaning")

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(wild_cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    stats = {
        "total_input": len(all_cards),
        "standard_dbfids": len(standard_dbfids),
        "skipped_standard": skipped_standard,
        "skipped_no_wild": skipped_no_wild,
        "skipped_no_dbf": skipped_no_dbf,
        "wild_only": len(wild_cards),
        "output_path": str(output_path),
    }

    logger.info(
        "Wild DB: %d cards → %s (skipped: %d standard, %d no-wild, %d no-dbf)",
        len(wild_cards), output_path,
        skipped_standard, skipped_no_wild, skipped_no_dbf,
    )

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    stats = build_wild_db()

    print(f"\n✅ Wild database built")
    print(f"   Input (all cards):     {stats['total_input']}")
    print(f"   Standard dbfIds:       {stats['standard_dbfids']}")
    print(f"   Skipped (in standard): {stats['skipped_standard']}")
    print(f"   Skipped (not wild):    {stats['skipped_no_wild']}")
    print(f"   Skipped (no dbfId):    {stats['skipped_no_dbf']}")
    print(f"   Wild-only cards:       {stats['wild_only']}")
    print(f"   Output: {stats['output_path']}")

    # Quick type breakdown
    output_path = Path(stats["output_path"])
    if output_path.exists():
        cards = json.loads(output_path.read_text(encoding="utf-8"))
        by_type: Dict[str, int] = {}
        for c in cards:
            t = c.get("type", "?")
            by_type[t] = by_type.get(t, 0) + 1
        print(f"\n   Wild cards by type:")
        for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"     {t}: {n}")

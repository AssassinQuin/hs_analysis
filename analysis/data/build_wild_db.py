#!/usr/bin/env python3
"""Build wild-only card database from HSJSON data.

Reads zhCN + enUS collectible cards from card_data/BUILD/,
removes cards in standard sets, writes remaining wild-only cards.

Usage::

    python -m hs_analysis.data.build_wild_db
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

from ..config import DATA_DIR
from ..utils import load_json

logger = logging.getLogger(__name__)

STANDARD_SETS = {
    "CATACLYSM", "TIME_TRAVEL", "THE_LOST_CITY", "EMERALD_DREAM",
    "CORE", "EVENT",
}


def _clean_text(text):
    if not text:
        return ""
    cleaned = re.sub(r"</?[^>]+>", "", text)
    cleaned = re.sub(r"[$#](\d+)", r"\1", cleaned)
    cleaned = re.sub(r"\[x\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", "", cleaned).strip()
    return cleaned


def build_wild_db(
    data_dir: Path | None = None,
    output_path: Path | None = None,
) -> Dict[str, Any]:
    """Build the wild-only card database from HSJSON data.

    Args:
        data_dir:   Directory containing zhCN/ and enUS/ subdirs.
        output_path: Where to write wild-only cards.

    Returns:
        Statistics dict.
    """
    if data_dir is None:
        data_dir = DATA_DIR
    if output_path is None:
        output_path = DATA_DIR / "unified_wild.json"

    zh_path = data_dir / "zhCN" / "cards.collectible.json"
    en_path = data_dir / "enUS" / "cards.collectible.json"

    if not zh_path.exists():
        raise FileNotFoundError(f"zhCN data not found: {zh_path}")

    zh_data: List[Dict[str, Any]] = load_json(zh_path)
    en_data: List[Dict[str, Any]] = load_json(en_path)
    en_by_id = {c["id"]: c for c in en_data}

    wild_cards: List[Dict[str, Any]] = []
    standard_count = 0

    for zh in zh_data:
        card_set = zh.get("set", "")
        if card_set in STANDARD_SETS:
            standard_count += 1
            continue

        en = en_by_id.get(zh["id"], {})
        text_raw = zh.get("text", "") or ""

        wild_cards.append({
            "dbfId": zh.get("dbfId", 0),
            "cardId": zh.get("id", ""),
            "name": zh.get("name", ""),
            "ename": en.get("name", ""),
            "cost": zh.get("cost", 0),
            "attack": zh.get("attack", 0),
            "health": zh.get("health", 0),
            "durability": zh.get("durability", 0),
            "armor": zh.get("armor", 0),
            "type": zh.get("type", ""),
            "cardClass": zh.get("cardClass", "NEUTRAL"),
            "race": zh.get("race", ""),
            "rarity": zh.get("rarity", ""),
            "text": _clean_text(text_raw),
            "mechanics": zh.get("mechanics", []),
            "overload": zh.get("overload", 0),
            "spellDamage": zh.get("spellDamage", 0),
            "set": card_set,
            "format": "wild",
        })

    wild_cards.sort(key=lambda x: (x.get("cost", 0), x["name"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(wild_cards, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    types = Counter(c["type"] for c in wild_cards)

    stats = {
        "total_collectible": len(zh_data),
        "standard_count": standard_count,
        "wild_only": len(wild_cards),
        "output_path": str(output_path),
        "types": dict(types),
    }

    logger.info(
        "Wild DB: %d wild-only cards -> %s (standard: %d)",
        len(wild_cards), output_path, standard_count,
    )

    return stats


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    stats = build_wild_db()

    print(f"\nWild database built")
    print(f"   Total collectible:    {stats['total_collectible']}")
    print(f"   Standard cards:       {stats['standard_count']}")
    print(f"   Wild-only cards:      {stats['wild_only']}")
    print(f"   Output: {stats['output_path']}")
    print(f"\n   Wild cards by type:")
    for t, n in sorted(stats["types"].items(), key=lambda x: -x[1]):
        print(f"     {t}: {n}")

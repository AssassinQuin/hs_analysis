#!/usr/bin/env python3
"""Fetch ALL Hearthstone cards from iyingdi API (standard + wild).

Unlike ``fetch_iyingdi`` (which sets ``standard=1``), this script omits
the format filter to retrieve the full 6,200+ card pool.  The result is
saved as ``hs_cards/iyingdi_all_raw.json`` for deduplication later.

Usage::

    python -m hs_analysis.data.fetch_wild
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API constants
# ---------------------------------------------------------------------------

_API_URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"

_HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.iyingdi.com",
    "Referer": "https://www.iyingdi.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
}

# Normalization maps (same as fetch_iyingdi)

RARITY_MAP: Dict[str, str] = {
    "普通": "COMMON",
    "稀有": "RARE",
    "史诗": "EPIC",
    "传说": "LEGENDARY",
    "无": "FREE",
}

_CLASS_MAP: Dict[str, str] = {
    "德鲁伊": "DRUID",
    "猎人": "HUNTER",
    "法师": "MAGE",
    "圣骑士": "PALADIN",
    "牧师": "PRIEST",
    "潜行者": "ROGUE",
    "萨满祭司": "SHAMAN",
    "术士": "WARLOCK",
    "战士": "WARRIOR",
    "恶魔猎手": "DEMONHUNTER",
    "死亡骑士": "DEATHKNIGHT",
    "中立": "NEUTRAL",
    "梦境之王": "DREAM",
}

_TYPE_MAP: Dict[str, str] = {
    "随从": "MINION",
    "法术": "SPELL",
    "武器": "WEAPON",
    "英雄牌": "HERO",
    "地标": "LOCATION",
}

# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def fetch_page(page: int, size: int = 50, *, wild: bool = False) -> Dict[str, Any]:
    """Fetch a single page from the iyingdi card search API.

    Args:
        page: Page number (1-based).
        size: Cards per page (max 50).
        wild: If True, send ``wild=1`` to filter for wild-eligible cards.
              Default False (no format filter → returns all cards).
    """
    params: Dict[str, str] = {
        "ignoreHero": "1",
        # NOTE: No "standard": "1" — fetch ALL formats
        "statistic": "total",
        "order": "-series,+mana",
        "token": "",
        "page": str(page),
        "size": str(size),
    }
    if wild:
        params["wild"] = "1"

    body = urllib.parse.urlencode(params).encode()

    req = urllib.request.Request(_API_URL, data=body, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_card(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map a raw iyingdi card to our unified schema."""
    faction_raw = raw.get("faction", "")
    # Handle multi-class: "潜行者,法师"
    classes = []
    for part in faction_raw.replace("，", ",").split(","):
        part = part.strip()
        mapped = _CLASS_MAP.get(part, part)
        if mapped:
            classes.append(mapped)
    card_class = classes[0] if classes else faction_raw

    clazz_raw = raw.get("clazz", "")
    card_type = _TYPE_MAP.get(clazz_raw, clazz_raw)

    rarity_raw = raw.get("rarity", "")
    rarity = RARITY_MAP.get(rarity_raw, rarity_raw)

    return {
        "dbfId": raw.get("gameid"),
        "name": raw.get("cname", ""),
        "ename": raw.get("ename", ""),
        "cost": raw.get("mana", 0),
        "attack": raw.get("attack", 0),
        "health": raw.get("hp", 0),
        "type": card_type,
        "cardClass": card_class,
        "rarity": rarity,
        "text": raw.get("rule", ""),
        "race": raw.get("race", ""),
        "set": raw.get("seriesAbbr", ""),
        "setName": raw.get("seriesName", ""),
        "mechanics": [],
        "source": "iyingdi",
        "standard": raw.get("standard", 0),
        "wild": raw.get("wild", 0),
    }


def fetch_all_cards(
    output_raw: Path | None = None,
    output_normalized: Path | None = None,
    page_size: int = 50,
    delay: float = 0.3,
    *,
    wild: bool = False,
) -> List[Dict[str, Any]]:
    """Fetch ALL cards from iyingdi (standard + wild).

    Args:
        output_raw:        Path to save raw API responses.
        output_normalized: Path to save normalized cards.
        page_size:         Cards per API page (max 50).
        delay:             Seconds between pages (rate limit).
        wild:              If True, send ``wild=1`` to filter for wild-eligible
                           cards.  Default False (no format filter → all cards).

    Returns:
        List of normalized card dicts.
    """
    if output_raw is None:
        output_raw = DATA_DIR / "iyingdi_all_raw.json"
    if output_normalized is None:
        output_normalized = DATA_DIR / "iyingdi_all_normalized.json"

    all_raw: List[Dict[str, Any]] = []
    all_normalized: List[Dict[str, Any]] = []
    page = 1

    while True:
        logger.info("Fetching page %d ...", page)
        try:
            data = fetch_page(page, size=page_size, wild=wild)
        except Exception as exc:
            logger.error("API error on page %d: %s", page, exc)
            break

        success = data.get("success")
        if not success:
            logger.error("API returned success=false on page %d: %s",
                         page, data.get("msg", ""))
            break

        inner = data.get("data", {})
        cards = inner.get("cards", [])
        total = inner.get("total", 0)

        if not cards:
            logger.info("No more cards at page %d — done.", page)
            break

        all_raw.extend(cards)
        all_normalized.extend(normalize_card(c) for c in cards)

        logger.info(
            "  Page %d: %d cards (cumulative: %d / %d)",
            page, len(cards), len(all_raw), total,
        )

        if len(all_raw) >= total:
            logger.info("Fetched all %d cards.", total)
            break

        page += 1
        time.sleep(delay)

    # Save raw
    output_raw.parent.mkdir(parents=True, exist_ok=True)
    output_raw.write_text(
        json.dumps(all_raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Raw data → %s (%d cards)", output_raw, len(all_raw))

    # Save normalized
    output_normalized.write_text(
        json.dumps(all_normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Normalized → %s (%d cards)", output_normalized, len(all_normalized))

    return all_normalized


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cards = fetch_all_cards()

    # Quick stats
    std_count = sum(1 for c in cards if c.get("standard"))
    wild_only = sum(1 for c in cards if c.get("wild") and not c.get("standard"))
    both = sum(1 for c in cards if c.get("standard") and c.get("wild"))

    print(f"\n✅ Fetched {len(cards)} total cards")
    print(f"   Standard + Wild (both): {both}")
    print(f"   Standard only:           {std_count - both}")
    print(f"   Wild only:               {wild_only}")

    by_type: Dict[str, int] = {}
    for c in cards:
        t = c.get("type", "?")
        by_type[t] = by_type.get(t, 0) + 1
    print(f"\n   By type:")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"     {t}: {n}")

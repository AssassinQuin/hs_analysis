# -*- coding: utf-8 -*-
"""
Build unified standard card database from HSJSON data.
Reads zhCN + enUS collectible cards from card_data/BUILD/,
merges into a single unified_standard.json with all structured fields.
"""
import json
import re
import sys
import io
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from analysis.config import DATA_DIR, UNIFIED_DB_PATH, DATA_BUILD
from analysis.utils import load_json

ZH_PATH = DATA_DIR / "zhCN" / "cards.collectible.json"
EN_PATH = DATA_DIR / "enUS" / "cards.collectible.json"
OUTPUT = str(UNIFIED_DB_PATH)

STANDARD_SETS = {
    "CATACLYSM", "TIME_TRAVEL", "THE_LOST_CITY", "EMERALD_DREAM",
    "CORE", "EVENT",
}

_SET_NAMES = {
    "CATACLYSM": "大灾变",
    "TIME_TRAVEL": "时光之穴",
    "THE_LOST_CITY": "迷失之城",
    "EMERALD_DREAM": "翡翠梦境",
    "CORE": "核心系列",
    "EVENT": "活动",
}


def _clean_text(text):
    if not text:
        return ""
    cleaned = re.sub(r"</?[^>]+>", "", text)
    cleaned = re.sub(r"[$#](\d+)", r"\1", cleaned)
    cleaned = re.sub(r"\[x\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", "", cleaned).strip()
    return cleaned


def build_card(zh_card, en_card):
    text_raw = zh_card.get("text", "") or ""
    return {
        "dbfId": zh_card.get("dbfId", 0),
        "cardId": zh_card.get("id", ""),
        "name": zh_card.get("name", ""),
        "ename": en_card.get("name", ""),
        "cost": zh_card.get("cost", 0),
        "attack": zh_card.get("attack", 0),
        "health": zh_card.get("health", 0),
        "durability": zh_card.get("durability", 0),
        "armor": zh_card.get("armor", 0),
        "type": zh_card.get("type", ""),
        "cardClass": zh_card.get("cardClass", "NEUTRAL"),
        "race": zh_card.get("race", ""),
        "races": zh_card.get("races", []),
        "rarity": zh_card.get("rarity", ""),
        "text": _clean_text(text_raw),
        "textRaw": text_raw,
        "spellSchool": zh_card.get("spellSchool", ""),
        "mechanics": zh_card.get("mechanics", []),
        "referencedTags": zh_card.get("referencedTags", []),
        "overload": zh_card.get("overload", 0),
        "spellDamage": zh_card.get("spellDamage", 0),
        "set": zh_card.get("set", ""),
        "setName": _SET_NAMES.get(zh_card.get("set", ""), ""),
    }


def main():
    zh_data = load_json(ZH_PATH)
    en_data = load_json(EN_PATH)

    en_by_id = {c["id"]: c for c in en_data}

    cards = []
    for zh in zh_data:
        card_set = zh.get("set", "")
        if card_set not in STANDARD_SETS:
            continue
        en = en_by_id.get(zh["id"], {})
        cards.append(build_card(zh, en))

    cards.sort(key=lambda x: (x.get("cost", 0), x["name"]))

    OUTPUT_PATH = Path(OUTPUT)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"Unified DB: {len(cards)} standard cards -> {OUTPUT}")

    rarities = Counter(c["rarity"] for c in cards)
    types = Counter(c["type"] for c in cards)

    print(f"\nRarities: {dict(rarities.most_common())}")
    print(f"Types: {dict(types.most_common())}")

    has_ol = sum(1 for c in cards if c.get("overload", 0))
    has_sd = sum(1 for c in cards if c.get("spellDamage", 0))
    has_ar = sum(1 for c in cards if c.get("armor", 0))
    has_dur = sum(1 for c in cards if c.get("durability", 0))
    print(f"\nStructured fields: overload={has_ol} spellDamage={has_sd} armor={has_ar} durability={has_dur}")

    all_mechs = Counter()
    for c in cards:
        for m in c.get("mechanics", []):
            all_mechs[m] += 1
    print(f"\nMechanics: {len(all_mechs)} types")
    for m, n in all_mechs.most_common():
        print(f"  {m:<25s}: {n}")


if __name__ == "__main__":
    main()

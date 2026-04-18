# -*- coding: utf-8 -*-
"""
Fetch all 1015 standard cards from iyingdi API (paginated).
Build a unified card database with gameid→card mapping.
"""
import json
import sys
import io
import time
import urllib.request
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
OUTPUT = "D:/code/game/hs_cards/iyingdi_standard_all.json"

HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.iyingdi.com",
    "Referer": "https://www.iyingdi.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
}

RARITY_MAP = {
    "普通": "COMMON", "稀有": "RARE", "史诗": "EPIC", "传说": "LEGENDARY",
}
RClassMap = {
    "德鲁伊": "DRUID", "猎人": "HUNTER", "法师": "MAGE",
    "圣骑士": "PALADIN", "牧师": "PRIEST", "潜行者": "ROGUE",
    "萨满祭司": "SHAMAN", "术士": "WARLOCK", "战士": "WARRIOR",
    "死亡骑士": "DEATHKNIGHT", "恶魔猎手": "DEMONHUNTER",
    "中立": "NEUTRAL", "梦境之王": "DREAM",
}
RTypeMap = {
    "随从": "MINION", "法术": "SPELL", "武器": "WEAPON",
    "英雄牌": "HERO", "地标": "LOCATION",
}


def fetch_page(page, size=30):
    body = urllib.parse.urlencode({
        "ignoreHero": "1", "standard": "1", "statistic": "total",
        "order": "-series,+mana", "token": "",
        "page": str(page), "size": str(size),
    })
    req = urllib.request.Request(URL, data=body.encode("utf-8"), headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))


def normalize_card(raw):
    return {
        "dbfId": raw.get("gameid"),
        "name": raw.get("cname", ""),
        "ename": raw.get("ename", ""),
        "cost": raw.get("mana", 0),
        "attack": raw.get("attack", 0),
        "health": raw.get("hp", 0),
        "type": RTypeMap.get(raw.get("clazz", ""), raw.get("clazz", "")),
        "cardClass": RClassMap.get(raw.get("faction", ""), raw.get("faction", "")),
        "rarity": RARITY_MAP.get(raw.get("rarity", ""), raw.get("rarity", "")),
        "text": raw.get("rule", ""),
        "race": raw.get("race", ""),
        "set": raw.get("seriesAbbr", ""),
        "setName": raw.get("seriesName", ""),
        "id_iyingdi": raw.get("id"),
        "mechanics": [],
        "referencedTags": [],
    }


def main():
    all_cards = []
    page = 1
    total = None

    while True:
        print(f"Fetching page {page}...")
        result = fetch_page(page)
        if not result.get("success"):
            print(f"  API error: {result.get('msg')}")
            break

        data = result.get("data", {})
        cards = data.get("cards", [])
        if total is None:
            total = data.get("total", 0)
            print(f"  Total cards reported: {total}")

        if not cards:
            print("  No more cards.")
            break

        all_cards.extend(cards)
        print(f"  Got {len(cards)} cards (running total: {len(all_cards)}/{total})")

        if len(all_cards) >= total:
            break

        page += 1
        time.sleep(0.3)

    print(f"\nTotal fetched: {len(all_cards)} cards")

    raw_output = "D:/code/game/hs_cards/iyingdi_standard_raw.json"
    with open(raw_output, "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=1)
    print(f"Raw data saved to {raw_output}")

    normalized = [normalize_card(c) for c in all_cards]

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=1)
    print(f"Saved to {OUTPUT}")

    from collections import Counter
    rarities = Counter(c["rarity"] for c in normalized)
    types = Counter(c["type"] for c in normalized)
    classes = Counter(c["cardClass"] for c in normalized)

    print(f"\nRarities: {dict(rarities.most_common())}")
    print(f"Types: {dict(types.most_common())}")
    print(f"Classes: {dict(classes.most_common())}")

    gameid_range = [c["dbfId"] for c in normalized if c["dbfId"]]
    print(f"\nDBF range: {min(gameid_range)} - {max(gameid_range)}")

    deck_missing = [92263,104725,103704,105505,106038,106050,105487,106044,105491,103619,105518,105509,106036,106047,106046,105489,105511,119919,119920,120082,120083,119815,119816,120064,120068,119705,119706,119647,119653]
    gameid_set = set(gameid_range)
    found = [d for d in deck_missing if d in gameid_set]
    still_missing = [d for d in deck_missing if d not in gameid_set]
    print(f"\nDeck missing dbfIds: {len(found)}/{len(deck_missing)} found in iyingdi")
    if still_missing:
        print(f"Still missing: {still_missing}")


if __name__ == "__main__":
    main()

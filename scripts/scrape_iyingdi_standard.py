"""
Scrape ALL standard cards from iyingdi API (paginated).
API: https://api2.iyingdi.com/hearthstone/card/search/vertical
Critical: ignoreHero=1 is required, otherwise only 30 hero cards returned.
"""
import requests
import json
import os
import time
import sys

API_URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
OUTPUT_DIR = "hs_cards"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "iyingdi_all_standard.json")
PAGE_SIZE = 50  # max per page

HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.iyingdi.com/",
    "Origin": "https://www.iyingdi.com",
}


def fetch_page(page=1, size=PAGE_SIZE):
    """Fetch one page of standard cards from iyingdi."""
    data = {
        "standard": "1",
        "ignoreHero": "1",
        "page": str(page),
        "size": str(size),
    }
    resp = requests.post(API_URL, data=data, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    result = resp.json()

    if not result.get("success"):
        raise Exception(f"API error: {result}")

    cards = result["data"]["cards"]
    return cards


def fetch_all_standard():
    """Fetch ALL standard cards with pagination (until empty page)."""
    all_cards = []
    page = 1

    while True:
        print(f"Fetching page {page}...")
        try:
            page_cards = fetch_page(page=page)
        except Exception as e:
            print(f"  Error on page {page}: {e}")
            break

        if not page_cards:
            print(f"  Empty page, stopping.")
            break

        all_cards.extend(page_cards)
        print(f"  Got {len(page_cards)} cards (cumulative: {len(all_cards)})")

        # Stop if we got fewer than PAGE_SIZE (last page)
        if len(page_cards) < PAGE_SIZE:
            print(f"  Last page (got {len(page_cards)} < {PAGE_SIZE}).")
            break

        page += 1
        time.sleep(0.3)  # be polite

    # Deduplicate by gameid (dbfId)
    seen = {}
    for card in all_cards:
        gid = card.get("gameid")
        if gid and gid not in seen:
            seen[gid] = card

    deduped = list(seen.values())
    print(f"\nTotal fetched: {len(all_cards)}, after dedup: {len(deduped)}")
    return deduped


def analyze_cards(cards):
    """Print summary statistics."""
    from collections import Counter

    # By class (faction)
    class_counts = Counter(c.get("faction", "Unknown") for c in cards)
    print("\n=== Cards by Class ===")
    for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
        print(f"  {cls}: {count}")

    # By card type (clazz)
    type_counts = Counter(c.get("clazz", "Unknown") for c in cards)
    print("\n=== Cards by Type ===")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {count}")

    # By series
    series_counts = Counter(c.get("seriesAbbr", "Unknown") for c in cards)
    print("\n=== Cards by Series ===")
    for s, count in sorted(series_counts.items(), key=lambda x: -x[1]):
        name = cards[0]  # just for reference
        print(f"  {s}: {count}")

    # By rarity
    rarity_counts = Counter(c.get("rarity", "Unknown") for c in cards)
    print("\n=== Cards by Rarity ===")
    for r, count in sorted(rarity_counts.items(), key=lambda x: -x[1]):
        print(f"  {r}: {count}")

    # By mana cost
    mana_counts = Counter(c.get("mana", -1) for c in cards)
    print("\n=== Cards by Mana Cost ===")
    for m in sorted(mana_counts.keys()):
        if m >= 0:
            print(f"  {m}-mana: {mana_counts[m]}")

    # Check for key mechanics
    mechanics_keywords = ["发现", "战吼", "亡语", "奥秘", "嘲讽", "突袭", "冲锋",
                         "潜行", "吸血", "风怒", "圣盾", "休眠", "光环",
                         "黑暗之赐", "地标", "过载", "连击", "抉择"]
    print("\n=== Key Mechanics in Card Text (rule) ===")
    for kw in mechanics_keywords:
        count = sum(1 for c in cards if kw in (c.get("rule", "") or ""))
        if count > 0:
            print(f"  {kw}: {count} cards")

    # Random effects
    random_keywords = ["随机", "Random"]
    random_count = sum(1 for c in cards if any(kw in (c.get("rule", "") or "") for kw in random_keywords))
    print(f"\n=== Cards with Random Effects: {random_count} ===")


def save_cards(cards):
    """Save all cards to JSON."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    output = {
        "total": len(cards),
        "source": "iyingdi",
        "api_url": API_URL,
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cards": cards,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(cards)} cards to {OUTPUT_FILE}")

    # Also save a compact version (key fields only)
    compact_file = os.path.join(OUTPUT_DIR, "iyingdi_standard_compact.json")
    compact = []
    for c in sorted(cards, key=lambda x: (x.get("faction", ""), x.get("mana", 0), x.get("cname", ""))):
        compact.append({
            "gameid": c.get("gameid"),
            "cname": c.get("cname"),
            "ename": c.get("ename"),
            "mana": c.get("mana"),
            "attack": c.get("attack"),
            "hp": c.get("hp"),
            "clazz": c.get("clazz"),       # card type: 随从/法术/武器 etc
            "faction": c.get("faction"),   # class: Warlock/Druid etc
            "rarity": c.get("rarity"),
            "race": c.get("race"),
            "rule": c.get("rule"),
            "description": c.get("description"),
            "seriesAbbr": c.get("seriesAbbr"),
            "seriesName": c.get("seriesName"),
            "standard": c.get("standard"),
            "img": c.get("img"),
        })

    with open(compact_file, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(compact),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cards": compact,
        }, f, ensure_ascii=False, indent=2)

    print(f"Saved compact version to {compact_file}")


def main():
    print("=" * 60)
    print("iyingdi Standard Card Scraper")
    print("=" * 60)

    cards = fetch_all_standard()
    analyze_cards(cards)
    save_cards(cards)

    print("\n" + "=" * 60)
    print(f"DONE! {len(cards)} standard cards fetched and saved.")
    print("=" * 60)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""Fetch all standard cards from iyingdi API, paginated."""
import json
import sys
import io
import time
import urllib.request
import urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
PAGE_SIZE = 30
OUTPUT = "D:/code/game/hs_cards/iyingdi_standard_fresh.json"

HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.iyingdi.com",
    "Referer": "https://www.iyingdi.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


def fetch_page(page, size=PAGE_SIZE):
    body = urllib.parse.urlencode(
        {
            "ignoreHero": "1",
            "standard": "1",
            "statistic": "total",
            "order": "-series,+mana",
            "token": "",
            "page": str(page),
            "size": str(size),
        }
    )
    req = urllib.request.Request(URL, data=body.encode("utf-8"), headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8"))


def main():
    print("Fetching page 1...")
    result = fetch_page(1)
    print(f"Response keys: {list(result.keys())}")

    if not result.get("success", False):
        print(f"API error: {result.get('msg', 'unknown')}")
        print("Trying with larger page size...")

        # Try alternative: fetch all at once
        body = "ignoreHero=1&standard=1&statistic=total&order=-series%2C%2Bmana&token=&page=1&size=2000"
        req = urllib.request.Request(URL, data=body.encode("utf-8"), headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode("utf-8"))
        print(f"Response: success={result.get('success')}, msg={result.get('msg', '')}")

        if not result.get("success"):
            print("API still failing. Dumping raw response:")
            raw = json.dumps(result, ensure_ascii=False)
            print(raw[:2000])
            return

    data = result.get("data", {})
    if isinstance(data, dict):
        print(f"Data keys: {list(data.keys())}")
        # Look for card list
        for k, v in data.items():
            if isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
                if v and isinstance(v[0], dict):
                    print(f"    Card keys: {list(v[0].keys())[:20]}")
            elif isinstance(v, (int, str)):
                print(f"  {k}: {v}")

    # Paginate if needed
    all_cards = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
                all_cards.extend(v)

    total_in_response = len(all_cards)
    print(f"\nCards in first response: {total_in_response}")

    # Try paginated fetch
    page = 2
    while total_in_response > 0 and page <= 50:
        time.sleep(0.3)
        print(f"Fetching page {page}...")
        try:
            result = fetch_page(page)
            if not result.get("success"):
                break
            data = result.get("data", {})
            page_cards = []
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
                        page_cards.extend(v)
            if not page_cards:
                break
            all_cards.extend(page_cards)
            print(f"  Got {len(page_cards)} cards (total: {len(all_cards)})")
            page += 1
        except Exception as e:
            print(f"  Error: {e}")
            break

    print(f"\nTotal cards fetched: {len(all_cards)}")

    if all_cards:
        with open(OUTPUT, "w", encoding="utf-8") as f:
            json.dump(all_cards, f, ensure_ascii=False, indent=1)
        print(f"Saved to {OUTPUT}")

        # Quick stats
        from collections import Counter

        rarities = Counter(c.get("rarity", "?") for c in all_cards)
        types = Counter(c.get("cardType", c.get("type", "?")) for c in all_cards)
        print(f"\nRarities: {dict(rarities)}")
        print(f"Types: {dict(types)}")

        # Check for dbfId field
        has_dbf = sum(1 for c in all_cards if "dbfId" in c or "dbf_id" in c)
        print(f"Cards with dbfId: {has_dbf}/{len(all_cards)}")

        # Sample card
        if all_cards:
            print(f"\nSample card keys: {list(all_cards[0].keys())}")
            print(json.dumps(all_cards[0], ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()

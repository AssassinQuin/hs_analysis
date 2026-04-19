# -*- coding: utf-8 -*-
"""
Fetch ALL standard legendary cards from HearthstoneJSON API.
This is a community-maintained API that provides complete card data.
"""

import json
import urllib.request

from hs_analysis.config import DATA_DIR, HSJSON_API_BASE

# HearthstoneJSON provides complete card data
URL = HSJSON_API_BASE + "cards.collectible.json"
OUTPUT = str(DATA_DIR / "hsjson_standard.json")


def main() -> None:
    """Fetch collectible card data from HearthstoneJSON and save to disk."""
    print(f"Fetching from: {URL}")
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        all_cards = json.loads(resp.read().decode("utf-8"))

    print(f"Total collectible cards: {len(all_cards)}")

    # Standard set IDs (from Blizzard CN API)
    STANDARD_SETS = {1980, 1957, 1952, 1946, 1935, 1905, 1897, 1941, 1637}

    # HearthstoneJSON uses set names, not IDs — check what sets are available
    sets_found = set()
    for c in all_cards:
        if "set" in c:
            sets_found.add(c["set"])

    print(f"\nSets found in data ({len(sets_found)}):")
    for s in sorted(sets_found):
        count = sum(1 for c in all_cards if c.get("set") == s)
        print(f"  {s}: {count}")

    # Check rarity field
    rarities = set()
    for c in all_cards:
        if "rarity" in c:
            rarities.add(c["rarity"])
    print(f"\nRarities: {rarities}")

    # Filter for legendary
    legendaries = [c for c in all_cards if c.get("rarity") == "LEGENDARY"]
    print(f"\nAll legendary cards: {len(legendaries)}")

    # Show legendary cards by set
    leg_sets: dict[str, int] = {}
    for c in legendaries:
        s = c.get("set", "unknown")
        if s not in leg_sets:
            leg_sets[s] = 0
        leg_sets[s] += 1
    print("\nLegendary cards by set:")
    for s, cnt in sorted(leg_sets.items(), key=lambda x: -x[1]):
        print(f"  {s}: {cnt}")

    # Show a sample legendary card with its full structure
    print("\n=== Sample legendary card structure ===")
    sample = legendaries[0]
    print(json.dumps(sample, ensure_ascii=False, indent=2)[:2000])

    # Save full data
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to: {OUTPUT}")


if __name__ == "__main__":
    main()

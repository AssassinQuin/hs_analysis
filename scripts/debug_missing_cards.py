"""Debug: compare fetch with different params to find missing cards."""
import requests
import time

API_URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.iyingdi.com/",
    "Origin": "https://www.iyingdi.com",
}

def fetch_all(params_label, extra_params=None):
    """Fetch all cards with given params, return list."""
    all_cards = []
    page = 1
    while True:
        data = {"page": str(page), "size": "50"}
        if extra_params:
            data.update(extra_params)
        resp = requests.post(API_URL, data=data, headers=HEADERS, timeout=30)
        result = resp.json()
        cards = result.get("data", {}).get("cards", [])
        if not cards:
            break
        all_cards.extend(cards)
        if len(cards) < 50:
            break
        page += 1
        time.sleep(0.2)
    return all_cards

# Test 1: standard=1, ignoreHero=1 (what we used)
print("=== Test 1: standard=1, ignoreHero=1 ===")
cards1 = fetch_all("std+ignoreHero", {"standard": "1", "ignoreHero": "1"})
print(f"  Total: {len(cards1)}")
gids1 = set(c.get("gameid") for c in cards1)
print(f"  Unique gameids: {len(gids1)}")

# Test 2: standard=1, NO ignoreHero
print("\n=== Test 2: standard=1, NO ignoreHero ===")
cards2 = fetch_all("std", {"standard": "1"})
print(f"  Total: {len(cards2)}")
gids2 = set(c.get("gameid") for c in cards2)
print(f"  Unique gameids: {len(gids2)}")

# Cards in test2 but not test1
only_in_2 = gids2 - gids1
print(f"  Only in test2 (no ignoreHero): {len(only_in_2)}")
# Print a few
map2 = {c.get("gameid"): c for c in cards2}
for gid in list(only_in_2)[:20]:
    c = map2[gid]
    print(f"    {c.get('cname')} | {c.get('faction')} | {c.get('clazz')} | {c.get('seriesAbbr')} | {c.get('mana')}mana")

# Test 3: NO standard filter, NO ignoreHero (all cards)
print("\n=== Test 3: NO filters (all cards) ===")
cards3 = fetch_all("all", {})
print(f"  Total: {len(cards3)}")
gids3 = set(c.get("gameid") for c in cards3)
print(f"  Unique gameids: {len(gids3)}")

# How many standard flags in the full set
std_flags = [c for c in cards3 if c.get("standard") == 1]
print(f"  Cards with standard=1 flag: {len(std_flags)}")

# Cards in full set with standard=1 but not in our fetch
gids_std = set(c.get("gameid") for c in std_flags)
gids_std_no_hero = set(c.get("gameid") for c in std_flags if c.get("clazz") != "英雄")
print(f"  Standard=1 unique: {len(gids_std)}")
print(f"  Standard=1 non-hero unique: {len(gids_std_no_hero)}")

missing = gids_std - gids1
print(f"  Standard=1 cards missing from test1: {len(missing)}")
map3 = {c.get("gameid"): c for c in cards3}
for gid in list(missing)[:30]:
    c = map3[gid]
    print(f"    {c.get('cname')} | {c.get('faction')} | {c.get('clazz')} | {c.get('seriesAbbr')} | standard={c.get('standard')} | wild={c.get('wild')}")

# Also check: cards in test1 but NOT flagged standard=1 in full set
non_std_in_1 = gids1 - gids_std
print(f"\n  Cards in test1 but NOT standard=1 in full set: {len(non_std_in_1)}")

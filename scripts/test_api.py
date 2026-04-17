"""
Try different API parameters to find the correct legendary cards.
Test multiple approaches to figure out why we only get 0-attack minions.
"""

import json
import urllib.request

API_URL = "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards/constructed"


def fetch_cards(page=1, page_size=50, **filters):
    body = {"page": page, "page_size": page_size}
    body.update(filters)
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Test 1: No filters - what do we get?
print("=== Test 1: No filters, page_size=10 ===")
r = fetch_cards(page=1, page_size=10)
print(f"Total: {r['data']['total']}")
for c in r["data"]["list"][:5]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

# Test 2: Use string "legendary" instead of rarity_id
print("\n=== Test 2: rarity=legendary string ===")
r2 = fetch_cards(rarity="legendary", page=1, page_size=10)
print(f"Total: {r2['data']['total']}, Got: {len(r2['data']['list'])}")
for c in r2["data"]["list"][:5]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

# Test 3: card_type_id=4 (minion) + rarity_id=5
print("\n=== Test 3: card_type_id=4 + rarity_id=5 ===")
r3 = fetch_cards(card_type_id=4, rarity_id=5, page=1, page_size=10)
print(f"Total: {r3['data']['total']}, Got: {len(r3['data']['list'])}")
for c in r3["data"]["list"][:5]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

# Test 4: card_type_id=4 (minion) without rarity filter
print("\n=== Test 4: card_type_id=4 only ===")
r4 = fetch_cards(card_type_id=4, page=1, page_size=10)
print(f"Total: {r4['data']['total']}, Got: {len(r4['data']['list'])}")
for c in r4["data"]["list"][:5]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

# Test 5: Try a specific well-known legendary - Ragnaros (id=1443)?
print("\n=== Test 5: Search specific legendary ===")
# Try searching for cards with attack > 0
# First, let's check what set IDs correspond to standard
r5 = fetch_cards(card_set_id=1637, page=1, page_size=10)  # Core set
print(f"Core set (1637) total: {r5['data']['total']}")
for c in r5["data"]["list"][:5]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

# Test 6: Core set + legendary
print("\n=== Test 6: Core set (1637) + rarity_id=5 ===")
r6 = fetch_cards(card_set_id=1637, rarity_id=5, page=1, page_size=50)
print(f"Total: {r6['data']['total']}, Got: {len(r6['data']['list'])}")
for c in r6["data"]["list"][:10]:
    print(
        f"  {c['id']} r={c['rarity_id']} {c.get('slug', '')[:40]} {c['mana_cost']}m {c['attack']}/{c['health']}"
    )

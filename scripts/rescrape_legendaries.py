"""
Re-scrape standard legendary cards with correct filtering.
Target: rarity_id=5 (legendary), standard format only.
"""

import json
import urllib.request

API_URL = "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards/constructed"


def fetch_cards(page=1, page_size=100, **filters):
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


# Fetch all standard legendaries (rarity_id=5)
print("Fetching standard legendaries (rarity_id=5)...")
result = fetch_cards(rarity_id=5, page=1, page_size=200)
print(f"Code: {result['code']}, Message: {result['message']}")
print(f"Total: {result['data']['total']}, Got: {len(result['data']['list'])}")

cards = result["data"]["list"]

# Check if we need more pages
total = result["data"]["total"]
page = 2
while len(cards) < total:
    print(f"  Fetching page {page}...")
    r = fetch_cards(rarity_id=5, page=page, page_size=200)
    cards.extend(r["data"]["list"])
    page += 1

# Deduplicate by id
seen = set()
unique = []
for c in cards:
    if c["id"] not in seen:
        seen.add(c["id"])
        unique.append(c)

print(f"\nTotal unique legendary cards: {len(unique)}")

# Check attack distribution
from collections import Counter

atk_dist = Counter(c.get("attack", "N/A") for c in unique)
print(f"Attack distribution: {dict(sorted(atk_dist.items()))}")

mana_dist = Counter(c.get("mana_cost", "N/A") for c in unique)
print(f"Mana distribution: {dict(sorted(mana_dist.items()))}")

type_dist = Counter(c.get("card_type_id", "N/A") for c in unique)
print(f"Card type distribution: {dict(sorted(type_dist.items()))}")

# Show some sample cards with non-zero attack
print("\nSample cards:")
for c in unique[:15]:
    name = c.get("name", "?")
    mana = c.get("mana_cost", "?")
    atk = c.get("attack", "?")
    hp = c.get("health", "?")
    cid = c.get("card_type_id", "?")
    rid = c.get("rarity_id", "?")
    cls = c.get("class_name", "?")
    print(
        f"  [{c['id']}] {name} | {mana}mana {atk}/{hp} type={cid} rarity={rid} class={cls}"
    )

# Save full data
output = {"total": len(unique), "all_cards": unique}
with open("hs_cards/standard_legendaries_v2.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# Also create simplified list
simple = []
for c in unique:
    simple.append(
        {
            "id": c["id"],
            "name": c.get("name", ""),
            "class": c.get("class_name", ""),
            "set": c.get("set_name", ""),
            "type_id": c.get("card_type_id", 0),
            "mana": c.get("mana_cost", 0),
            "attack": c.get("attack", 0),
            "health": c.get("health", 0),
            "text": c.get("text", ""),
            "rarity_id": c.get("rarity_id", 0),
            "keyword_ids": c.get("keyword_ids", []),
            "minion_type_id": c.get("minion_type_id", 0),
            "spell_school_id": c.get("spellSchoolId", 0),
        }
    )

with open("hs_cards/legendaries_simple_v2.json", "w", encoding="utf-8") as f:
    json.dump(simple, f, ensure_ascii=False, indent=2)

print(
    f"\nSaved {len(unique)} cards to hs_cards/standard_legendaries_v2.json and hs_cards/legendaries_simple_v2.json"
)

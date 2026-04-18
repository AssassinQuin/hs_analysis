"""Build complete standard card database using HearthstoneJSON + python-hearthstone.

Uses:
1. python-hearthstone for CardSet.is_standard to determine standard-legal sets
2. HearthstoneJSON API for zhCN card data
3. python-hearthstone cardxml for authoritative standard set detection
"""
import json
import requests
from collections import Counter
from hearthstone.enums import CardSet, ZodiacYear

# --- Determine current standard-legal sets ---
print("=== Detecting Standard Sets ===")

# Check CardSet.is_standard for each member
standard_sets = {}
for member in CardSet:
    try:
        if member.is_standard:
            standard_sets[member.name] = member.value
    except (AttributeError, TypeError):
        pass

print(f"Standard sets (via is_standard): {len(standard_sets)}")
for name, val in sorted(standard_sets.items(), key=lambda x: x[1]):
    print(f"  {name} ({val})")

# Also check the latest ZodiacYear in STANDARD_SETS
from hearthstone.utils import STANDARD_SETS
latest_year = max(STANDARD_SETS.keys(), key=lambda x: x.value)
print(f"\nLatest ZodiacYear: {latest_year.name} ({latest_year.value})")
print(f"Sets in {latest_year.name}:")
for s in STANDARD_SETS[latest_year]:
    print(f"  {s.name} ({s.value})")

# --- Fetch HearthstoneJSON data ---
print("\n=== Fetching HearthstoneJSON zhCN ===")
url = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
cards = requests.get(url, timeout=60).json()
print(f"Total collectible cards: {len(cards)}")

# Filter for standard-legal sets
standard_set_values = set(standard_sets.values())
standard_cards = [c for c in cards if c.get("set") in standard_sets]

print(f"\nStandard cards (via is_standard): {len(standard_cards)}")

# Check set distribution
std_sets = Counter(c.get("set") for c in standard_cards)
for s, cnt in sorted(std_sets.items(), key=lambda x: -x[1]):
    print(f"  {s}: {cnt}")

# --- Also try using RAPTOR year if SCARAB gives too few ---
raptor_sets = {s.name: s.value for s in STANDARD_SETS[ZodiacYear.RAPTOR]}
raptor_cards = [c for c in cards if c.get("set") in raptor_sets]
print(f"\nRAPTOR year cards: {len(raptor_cards)}")

scarab_sets = {s.name: s.value for s in STANDARD_SETS[ZodiacYear.SCARAB]}
scarab_cards = [c for c in cards if c.get("set") in scarab_sets]
print(f"SCARAB year cards: {len(scarab_cards)}")

# Check type distribution
print("\n=== Standard card types (is_standard) ===")
types = Counter(c.get("type") for c in standard_cards)
for t, cnt in sorted(types.items(), key=lambda x: -x[1]):
    print(f"  {t}: {cnt}")

# Check class distribution
print("\n=== Standard card classes ===")
classes = Counter(c.get("cardClass") for c in standard_cards)
for cl, cnt in sorted(classes.items(), key=lambda x: -x[1]):
    print(f"  {cl}: {cnt}")

# Show a few sample cards with full field list
print("\n=== Sample standard card ===")
sample = standard_cards[0]
for k, v in sample.items():
    print(f"  {k}: {repr(v)}")

# Save the dataset
output = {
    "source": "hearthstonejson_v1_latest_zhCN",
    "standard_sets": standard_sets,
    "total": len(standard_cards),
    "cards": standard_cards,
}
with open("hs_cards/hsjson_standard.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\nSaved to hs_cards/hsjson_standard.json")

# Also save a compact version
compact_fields = [
    "id", "dbfId", "name", "text", "cardClass", "cost", "rarity",
    "set", "type", "attack", "health", "mechanics", "race", "races",
    "spellSchool", "referencedTags", "playRequirements", "entourage",
]
compact = []
for c in standard_cards:
    entry = {k: c.get(k) for k in compact_fields if k in c}
    compact.append(entry)

compact_output = {
    "source": "hearthstonejson_v1_latest_zhCN",
    "standard_sets": standard_sets,
    "total": len(compact),
    "cards": compact,
}
with open("hs_cards/hsjson_standard_compact.json", "w", encoding="utf-8") as f:
    json.dump(compact_output, f, ensure_ascii=False, indent=2)
print(f"Compact saved to hs_cards/hsjson_standard_compact.json")

# Cross-reference with iyingdi
print("\n=== Cross-reference with iyingdi ===")
iyingdi_gids = set()
try:
    with open("hs_cards/iyingdi_all_standard.json", "r", encoding="utf-8") as f:
        iy_data = json.load(f)
        for c in iy_data["cards"]:
            gid = c.get("gameid")
            if gid:
                iyingdi_gids.add(gid)
except FileNotFoundError:
    pass

hsjson_dbfids = set(c.get("dbfId") for c in standard_cards)
print(f"iyingdi gameids: {len(iyingdi_gids)}")
print(f"HSJSON dbfIds: {len(hsjson_dbfids)}")

# iyingdi gameid == HSJSON dbfId?
overlap = iyingdi_gids & hsjson_dbfids
only_iy = iyingdi_gids - hsjson_dbfids
only_hs = hsjson_dbfids - iyingdi_gids
print(f"Overlap: {len(overlap)}")
print(f"Only in iyingdi: {len(only_iy)}")
print(f"Only in HSJSON: {len(only_hs)}")

# Show some cards only in HSJSON
if only_hs:
    hsjson_map = {c.get("dbfId"): c for c in standard_cards}
    print("\nSample cards only in HSJSON (first 15):")
    for dbfid in sorted(only_hs)[:15]:
        c = hsjson_map[dbfid]
        print(f"  {c.get('name')} | {c.get('cardClass')} | {c.get('set')} | {c.get('cost')}mana | {c.get('type')}")

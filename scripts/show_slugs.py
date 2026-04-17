import json

d = json.load(open("hs_cards/standard_legendaries_v2.json", "r", encoding="utf-8"))
cards = d["all_cards"]
for c in cards[:25]:
    cid = c["id"]
    r = c["rarity_id"]
    slug = c.get("slug", "N/A")
    mana = c["mana_cost"]
    atk = c["attack"]
    hp = c["health"]
    cls = c.get("class_name", "?")
    print(f"{cid:>6}  r={r}  {slug:50s}  {mana}m {atk}/{hp}  {cls}")
print(f"\n... total {len(cards)} cards")

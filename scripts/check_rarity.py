import json
from collections import Counter

d = json.load(open("hs_cards/all_standard_legendaries.json", "r", encoding="utf-8"))
cards = d["all_cards"]

# Rarity distribution
rarities = Counter(c.get("rarity_id") for c in cards)
print("Rarity distribution:", dict(rarities))

# Non-legendary
non_leg = [c for c in cards if c.get("rarity_id") != 5]
print(f"\nNon-legendary cards: {len(non_leg)}")
for c in non_leg[:5]:
    print(
        f"  id={c['id']} rarity={c['rarity_id']} mana={c['mana_cost']} atk={c['attack']} hp={c['health']}"
    )

# Legendary
leg = [c for c in cards if c.get("rarity_id") == 5]
print(f"\nLegendary cards: {len(leg)}")
for c in leg[:10]:
    print(
        f"  id={c['id']} rarity={c['rarity_id']} mana={c['mana_cost']} atk={c['attack']} hp={c['health']}"
    )

# Attack distribution for legendaries only
atk_dist = Counter(c["attack"] for c in leg)
print(f"\nLegendary attack distribution: {dict(sorted(atk_dist.items()))}")

"""Investigate missing cards - compare expected vs actual counts."""
import json
import collections

data = json.load(open("hs_cards/iyingdi_all_standard.json", "r", encoding="utf-8"))
cards = data["cards"]

print(f"Total cards: {len(cards)}")

# By series
series = collections.Counter(c.get("seriesAbbr", "?") for c in cards)
print("\n=== By seriesAbbr ===")
for k, v in sorted(series.items()):
    print(f"  {k}: {v}")

# Expected: IED(145), EWT(39), LCU(145), DOR(38), ATT(145), EOI(38), CAT(135), CS2026(289), GIFT(11)
expected = {
    "IED": 145, "EWT": 39, "LCU": 145, "DOR": 38,
    "ATT": 145, "EOI": 38, "CAT": 135, "CS2026": 289, "GIFT": 11,
}
print("\n=== Expected vs Actual ===")
total_expected = 0
for k in sorted(expected.keys()):
    exp = expected[k]
    act = series.get(k, 0)
    diff = act - exp
    total_expected += exp
    marker = "OK" if diff == 0 else f"{'+' if diff > 0 else ''}{diff}"
    print(f"  {k}: expected={exp}, actual={act}, diff={marker}")
print(f"  TOTAL: expected={total_expected}, actual={len(cards)}, diff={len(cards)-total_expected}")

# Hero cards
heroes = [c for c in cards if c.get("clazz", "") in ("英雄", "英雄牌")]
print(f"\nHero-type cards: {len(heroes)}")
for h in heroes:
    cname = h.get("cname", "?")
    faction = h.get("faction", "?")
    s = h.get("seriesAbbr", "?")
    print(f"  {cname} | {faction} | {s}")

# Check for duplicate names
name_counts = collections.Counter(c.get("cname", "?") for c in cards)
dup_names = [(n, cnt) for n, cnt in name_counts.items() if cnt > 1]
print(f"\nDuplicate card names: {len(dup_names)}")
for name, cnt in dup_names[:10]:
    matching = [c for c in cards if c.get("cname") == name]
    print(f"  {name} x{cnt}:")
    for m in matching:
        print(f"    gameid={m.get('gameid')} | {m.get('faction')} | {m.get('seriesAbbr')} | {m.get('mana')}mana")

# Check if ignoreHero=1 removes hero power cards
print("\n=== Cards without gameid ===")
no_gid = [c for c in cards if not c.get("gameid")]
print(f"Count: {len(no_gid)}")

# Faction breakdown
factions = collections.Counter(c.get("faction", "?") for c in cards)
print("\n=== By faction ===")
for k, v in sorted(factions.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

# Clazz breakdown
clazzes = collections.Counter(c.get("clazz", "?") for c in cards)
print("\n=== By clazz ===")
for k, v in sorted(clazzes.items(), key=lambda x: -x[1]):
    print(f"  {k}: {v}")

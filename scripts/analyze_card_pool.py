"""Analyze the iyingdi standard card pool for random effects, Discover, Dark Gift, Locations."""
import json
from collections import Counter

with open("hs_cards/iyingdi_standard_compact.json", "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]

lines = []
L = lines.append

L(f"# iyingdi Standard Card Pool Analysis")
L(f"Total: {len(cards)} cards")
L("")

# Class distribution
cls = Counter(c.get("faction", "?") for c in cards)
L("## By Class")
for k, v in sorted(cls.items(), key=lambda x: -x[1]):
    L(f"- {k}: {v}")
L("")

# Type distribution
typ = Counter(c.get("clazz", "?") for c in cards)
L("## By Type")
for k, v in sorted(typ.items(), key=lambda x: -x[1]):
    L(f"- {k}: {v}")
L("")

# Series distribution
ser = Counter(c.get("seriesAbbr", "?") for c in cards)
L("## By Series")
for k, v in sorted(ser.items(), key=lambda x: -x[1]):
    L(f"- {k}: {v}")
L("")

# Rarity distribution
rar = Counter(c.get("rarity", "?") for c in cards)
L("## By Rarity")
for k, v in sorted(rar.items(), key=lambda x: -x[1]):
    L(f"- {k}: {v}")
L("")

# Mana curve
mana = Counter(c.get("mana", -1) for c in cards)
L("## Mana Curve")
for m in sorted(mana.keys()):
    if m >= 0:
        bar = "#" * (mana[m] // 3)
        L(f"- {m:2d}-mana: {mana[m]:3d} {bar}")
L("")

# Random effects categorization
L("## Random Effects Categorization")
L("")
categories = {
    "discover": [],
    "dark_gift": [],
    "random_summon": [],
    "random_damage": [],
    "random_generate": [],
    "random_buff": [],
    "random_other": [],
}

for c in cards:
    rule = c.get("rule", "") or ""
    cname = c.get("cname", "?")
    faction = c.get("faction", "?")
    mana_cost = c.get("mana", 0)
    card_type = c.get("clazz", "?")
    series = c.get("seriesAbbr", "?")

    has_random = "随机" in rule
    has_discover = "发现" in rule
    has_dark_gift = "黑暗之赐" in rule

    if not (has_random or has_discover or has_dark_gift):
        continue

    entry = {
        "cname": cname,
        "faction": faction,
        "mana": mana_cost,
        "clazz": card_type,
        "series": series,
        "rule": rule[:200],
    }

    if has_dark_gift:
        categories["dark_gift"].append(entry)
    if has_discover:
        categories["discover"].append(entry)
    if has_random:
        if "召唤" in rule:
            categories["random_summon"].append(entry)
        if "伤害" in rule or "射击" in rule:
            categories["random_damage"].append(entry)
        if "获得" in rule or "置入" in rule or "添加" in rule or "衍生" in rule:
            categories["random_generate"].append(entry)
        if "属性" in rule or "增益" in rule:
            categories["random_buff"].append(entry)
        still_unmatched = not any(
            x in rule
            for x in ["召唤", "伤害", "射击", "获得", "置入", "添加", "衍生", "属性", "增益"]
        )
        if still_unmatched and not has_discover and not has_dark_gift:
            categories["random_other"].append(entry)

for cat in sorted(categories.keys()):
    items = categories[cat]
    if not items:
        continue
    L(f"### {cat} ({len(items)} cards)")
    for item in items[:15]:
        L(f'- {item["cname"]} | {item["faction"]} | {item["mana"]}mana | {item["clazz"]} | {item["series"]}')
        L(f'  Rule: {item["rule"][:150]}')
    if len(items) > 15:
        L(f"- ... and {len(items) - 15} more")
    L("")

# Multi-class cards
multi = [c for c in cards if c.get("faction", "").count(",") > 0]
L(f"## Multi-class Cards ({len(multi)})")
for c in multi:
    L(f'- {c["cname"]} | {c["faction"]} | {c.get("mana","?")}mana | {c.get("clazz","?")}')
L("")

# Location cards
L("## Location Cards")
locations = [c for c in cards if c.get("clazz", "") == "地标"]
L(f"Total: {len(locations)}")
for c in locations:
    L(f'- {c["cname"]} | {c.get("faction","?")} | {c.get("mana","?")}mana')
    L(f'  {(c.get("rule","") or "")[:200]}')
L("")

# Cards with both Discover AND random
L("## Cards with Both Discover + Random")
for c in cards:
    rule = c.get("rule", "") or ""
    if "发现" in rule and "随机" in rule:
        L(f'- {c["cname"]} | {c.get("faction","?")} | {c.get("mana","?")}mana')
        L(f'  {rule[:200]}')
L("")

# Summary stats
total_random = len(
    [
        c
        for c in cards
        if any(
            kw in (c.get("rule", "") or "")
            for kw in ["随机", "发现", "黑暗之赐"]
        )
    ]
)
L(f"## Summary")
L(f"- Total cards: {len(cards)}")
L(f"- Cards with random/Discover/Dark Gift effects: {total_random} ({total_random*100//len(cards)}%)")
L(f"- Discover cards: {len(categories['discover'])}")
L(f"- Dark Gift cards: {len(categories['dark_gift'])}")
L(f"- Random summon: {len(categories['random_summon'])}")
L(f"- Random damage: {len(categories['random_damage'])}")
L(f"- Random generate: {len(categories['random_generate'])}")
L(f"- Random buff: {len(categories['random_buff'])}")
L(f"- Random other: {len(categories['random_other'])}")
L(f"- Locations: {len(locations)}")
L(f"- Multi-class: {len(multi)}")

with open("hs_cards/card_pool_analysis.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Analysis saved to hs_cards/card_pool_analysis.md")
print(f"Total cards: {len(cards)}")
print(f"Cards with random effects: {total_random}")

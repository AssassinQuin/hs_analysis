"""
Fetch and save ALL standard legendary cards from HearthstoneJSON.
Then perform comprehensive mathematical analysis.
"""

import json
import urllib.request
from collections import Counter, defaultdict

# Fetch full card data
URL = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
print("Fetching card data...")
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=60) as resp:
    all_cards = json.loads(resp.read().decode("utf-8"))

# Standard sets based on Blizzard CN API set names
# 1980(大地的裂变)=CATACLYSM, 1957(穿越时间流)=TIME_TRAVEL, 1952(安戈洛龟途)=THE_LOST_CITY
# 1946(漫游翡翠梦境)=EMERALD_DREAM, 1935(深暗领域)=SPACE, 1905(胜地历险记)=ISLAND_VACATION
# 1897(威兹班的工坊)=WHIZBANGS_WORKSHOP, 1941(活动)=EVENT, 1637(核心)=CORE
STANDARD_SETS = {
    "CATACLYSM",
    "TIME_TRAVEL",
    "THE_LOST_CITY",
    "EMERALD_DREAM",
    "SPACE",
    "ISLAND_VACATION",
    "WHIZBANGS_WORKSHOP",
    "EVENT",
    "CORE",
}

# Filter: Standard + Legendary + Minion type (for stat analysis)
standard_legendaries_all = [
    c
    for c in all_cards
    if c.get("set") in STANDARD_SETS and c.get("rarity") == "LEGENDARY"
]
standard_leg_minions = [
    c for c in standard_legendaries_all if c.get("type") == "MINION"
]
standard_leg_spells = [c for c in standard_legendaries_all if c.get("type") == "SPELL"]
standard_leg_weapons = [
    c for c in standard_legendaries_all if c.get("type") == "WEAPON"
]
standard_leg_locations = [
    c for c in standard_legendaries_all if c.get("type") == "LOCATION"
]
standard_leg_heroes = [c for c in standard_legendaries_all if c.get("type") == "HERO"]

print(f"\n=== Standard Legendary Cards ===")
print(f"Total: {len(standard_legendaries_all)}")
print(f"  Minions: {len(standard_leg_minions)}")
print(f"  Spells: {len(standard_leg_spells)}")
print(f"  Weapons: {len(standard_leg_weapons)}")
print(f"  Locations: {len(standard_leg_locations)}")
print(f"  Heroes: {len(standard_leg_heroes)}")

# Class distribution
class_names_cn = {
    "MAGE": "法师",
    "WARRIOR": "战士",
    "WARLOCK": "术士",
    "SHAMAN": "萨满",
    "ROGUE": "潜行者",
    "PALADIN": "圣骑士",
    "PRIEST": "牧师",
    "HUNTER": "猎人",
    "DRUID": "德鲁伊",
    "DEMONHUNTER": "恶魔猎手",
    "DEATHKNIGHT": "死亡骑士",
    "NEUTRAL": "中立",
}

print(f"\n=== Class Distribution (Minions) ===")
cls_dist = Counter(c.get("cardClass", "UNKNOWN") for c in standard_leg_minions)
for cls, cnt in cls_dist.most_common():
    cn = class_names_cn.get(cls, cls)
    print(f"  {cn}({cls}): {cnt}")

# Mana distribution
print(f"\n=== Mana Curve (Minions) ===")
mana_dist = Counter(c.get("cost", 0) for c in standard_leg_minions)
for m in sorted(mana_dist.keys()):
    bar = "#" * mana_dist[m]
    print(f"  {m:2d} mana: {mana_dist[m]:3d} {bar}")

# Attack distribution
print(f"\n=== Attack Distribution (Minions) ===")
atk_dist = Counter(c.get("attack", 0) for c in standard_leg_minions)
for a in sorted(atk_dist.keys()):
    print(f"  {a:2d} atk: {atk_dist[a]:3d}")

# Health distribution
print(f"\n=== Health Distribution (Minions) ===")
hp_dist = Counter(c.get("health", 0) for c in standard_leg_minions)
for h in sorted(hp_dist.keys()):
    print(f"  {h:2d} hp: {hp_dist[h]:3d}")

# =====================
# VANILLA TEST ANALYSIS
# =====================
print(f"\n{'=' * 60}")
print(f"=== VANILLA TEST: Attack + Health vs Mana*2 + 1 ===")
print(f"{'=' * 60}")

for c in sorted(standard_leg_minions, key=lambda x: x.get("cost", 0)):
    name = c.get("name", "?")
    mana = c.get("cost", 0)
    atk = c.get("attack", 0)
    hp = c.get("health", 0)
    stats = atk + hp
    expected = mana * 2 + 1
    deficit = expected - stats  # positive = under budget, negative = over budget

    cls = class_names_cn.get(c.get("cardClass", ""), c.get("cardClass", ""))
    mechanics = ", ".join(c.get("mechanics", []))

    verdict = ""
    if deficit <= -3:
        verdict = "*** VERY OVER BUDGET ***"
    elif deficit < 0:
        verdict = "** OVER BUDGET **"
    elif deficit == 0:
        verdict = "= ON BUDGET"
    elif deficit <= 2:
        verdict = "under budget (effect value)"
    else:
        verdict = "WAY under budget (big effect)"

    print(
        f"  {mana}m {atk:2d}/{hp:2d} stats={stats:2d} exp={expected:2d} def={deficit:+3d} | {name[:12]:12s} {cls:6s} {verdict}"
    )

# =====================
# STAT BUDGET ANALYSIS
# =====================
print(f"\n{'=' * 60}")
print(f"=== STAT BUDGET BY MANA COST ===")
print(f"{'=' * 60}")

by_mana = defaultdict(list)
for c in standard_leg_minions:
    by_mana[c.get("cost", 0)].append(c)

for mana in sorted(by_mana.keys()):
    cards_at_mana = by_mana[mana]
    stats = [(c.get("attack", 0), c.get("health", 0)) for c in cards_at_mana]
    stat_sums = [a + h for a, h in stats]
    avg_stats = sum(stat_sums) / len(stat_sums)
    expected = mana * 2 + 1
    avg_atk = sum(a for a, h in stats) / len(stats)
    avg_hp = sum(h for a, h in stats) / len(stats)

    print(
        f"  {mana}mana: {len(cards_at_mana):2d} cards, avg stats={avg_stats:.1f} (expected={expected}), avg atk={avg_atk:.1f}, avg hp={avg_hp:.1f}"
    )

# =====================
# KEYWORD ANALYSIS
# =====================
print(f"\n{'=' * 60}")
print(f"=== MECHANIC/KEYWORD FREQUENCY (Minions) ===")
print(f"{'=' * 60}")

mech_counter = Counter()
for c in standard_leg_minions:
    for m in c.get("mechanics", []):
        mech_counter[m] += 1

for m, cnt in mech_counter.most_common():
    print(f"  {m}: {cnt}")

# =====================
# VALUE SCORING MODEL
# =====================
print(f"\n{'=' * 60}")
print(f"=== VALUE SCORING MODEL ===")
print(f"{'=' * 60}")

# Build a simple scoring model:
# Base score = stats - expected (vanilla test)
# Keyword bonuses: TAUNT=+1, DIVINE_SHIELD=+2, CHARGE=+2, WINDFURY=+1, STEALTH=+1
# BATTLECRY=+1 (average), DEATHRATTLE=+1 (average)
KEYWORD_VALUES = {
    "TAUNT": 1.0,
    "DIVINE_SHIELD": 2.0,
    "CHARGE": 2.0,
    "WINDFURY": 1.5,
    "STEALTH": 1.0,
    "BATTLECRY": 1.5,
    "DEATHRATTLE": 1.5,
    "COMBO": 0.5,
    "FREEZE": 0.5,
    "OVERLOAD": -1.0,
    "SPELLPOWER": 1.0,
    "INSPIRE": 1.0,
    "DISCOVER": 2.0,
    "LIFESTEAL": 1.5,
    "RUSH": 1.5,
    "RECRUIT": 2.0,
    "ECHO": 1.0,
    "MAGNETIC": 1.0,
    "POISONOUS": 1.5,
    "CANT_BE_TARGETED_BY_SPELLS": 1.5,
    "CANT_BE_TARGETED_BY_HERO_POWERS": 0.5,
}

scored_cards = []
for c in standard_leg_minions:
    mana = c.get("cost", 0)
    atk = c.get("attack", 0)
    hp = c.get("health", 0)
    stats = atk + hp
    expected = mana * 2 + 1
    stat_value = stats - expected  # deficit (negative = over budget)

    # Keyword bonus
    keyword_bonus = 0
    for m in c.get("mechanics", []):
        keyword_bonus += KEYWORD_VALUES.get(m, 0.5)  # default 0.5 per unknown mechanic

    # Total score: how much "extra" value the card provides
    total_score = -stat_value + keyword_bonus  # higher = more value

    scored_cards.append(
        {
            "card": c,
            "mana": mana,
            "atk": atk,
            "hp": hp,
            "stats": stats,
            "expected": expected,
            "stat_deficit": stat_value,
            "keyword_bonus": keyword_bonus,
            "total_score": total_score,
        }
    )

# Sort by total score descending
scored_cards.sort(key=lambda x: x["total_score"], reverse=True)

print(f"\nTop 20 VALUE cards (score = keyword_bonus - stat_deficit):")
for i, s in enumerate(scored_cards[:20]):
    c = s["card"]
    name = c.get("name", "?")
    cls = class_names_cn.get(c.get("cardClass", ""), "")
    print(
        f"  {i + 1:2d}. {s['mana']}m {s['atk']}/{s['hp']} | score={s['total_score']:+.1f} (stat_def={s['stat_deficit']}, kw={s['keyword_bonus']:.1f}) | {name} ({cls})"
    )

print(f"\nBottom 10 VALUE cards:")
for i, s in enumerate(scored_cards[-10:]):
    c = s["card"]
    name = c.get("name", "?")
    cls = class_names_cn.get(c.get("cardClass", ""), "")
    print(
        f"  {len(scored_cards) - 9 + i}. {s['mana']}m {s['atk']}/{s['hp']} | score={s['total_score']:+.1f} (stat_def={s['stat_deficit']}, kw={s['keyword_bonus']:.1f}) | {name} ({cls})"
    )

# =====================
# SAVE COMPREHENSIVE DATA
# =====================
output = {
    "metadata": {
        "source": "HearthstoneJSON v1",
        "standard_sets": list(STANDARD_SETS),
        "total_legendaries": len(standard_legendaries_all),
        "total_minions": len(standard_leg_minions),
    },
    "legendaries": standard_legendaries_all,
    "scored_minions": [
        {
            "name": s["card"].get("name", ""),
            "id": s["card"].get("id", ""),
            "class": s["card"].get("cardClass", ""),
            "set": s["card"].get("set", ""),
            "mana": s["mana"],
            "attack": s["atk"],
            "health": s["hp"],
            "mechanics": s["card"].get("mechanics", []),
            "stat_deficit": s["stat_deficit"],
            "keyword_bonus": s["keyword_bonus"],
            "total_score": s["total_score"],
        }
        for s in scored_cards
    ],
}

with open("hs_cards/standard_legendaries_analysis.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\nSaved analysis to hs_cards/standard_legendaries_analysis.json")
print(f"Total legendary minions scored: {len(scored_cards)}")

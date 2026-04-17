import json

with open("hs_cards/card_list.json", "r", encoding="utf-8") as f:
    cards = json.load(f)

print(f"Total cards: {len(cards)}")

# Attack distribution
atk_zero = [c for c in cards if c["attack"] == 0]
atk_pos = [c for c in cards if c["attack"] > 0]
print(f"Attack=0: {len(atk_zero)}")
print(f"Attack>0: {len(atk_pos)}")

if atk_pos:
    for c in atk_pos[:10]:
        print(
            f"  {c['name']} ({c['mana']}mana {c['attack']}/{c['health']}) - {c['class']} - {c['set']}"
        )

# Mana distribution
from collections import Counter

mana_dist = Counter(c["mana"] for c in cards)
print(f"\nMana distribution:")
for m in sorted(mana_dist.keys()):
    print(f"  {m} mana: {mana_dist[m]} cards")

# Health distribution
hp_dist = Counter(c["health"] for c in cards)
print(f"\nHealth distribution:")
for h in sorted(hp_dist.keys()):
    print(f"  {h} HP: {hp_dist[h]} cards")

# Class distribution
cls_dist = Counter(c["class"] for c in cards)
print(f"\nClass distribution:")
for cls, cnt in cls_dist.most_common():
    print(f"  {cls}: {cnt}")

# Set distribution
set_dist = Counter(c["set"] for c in cards)
print(f"\nSet distribution:")
for s, cnt in set_dist.most_common():
    print(f"  {s}: {cnt}")

# Keyword analysis
keywords_found = {}
for c in cards:
    text = c.get("text", "") or ""
    # Common keywords
    kws = [
        "嘲讽",
        "潜行",
        "圣盾",
        "战吼",
        "亡语",
        "发现",
        "抽牌",
        "冲锋",
        "突袭",
        "吸血",
        "法术伤害",
        "奥秘",
        "光环",
        "冻结",
        "沉默",
        "随机",
        "召唤",
        "伤害",
        "恢复",
        "Buff",
        "复制",
        "消灭",
        "移回",
        "圣疗",
        "过载",
    ]
    for kw in kws:
        if kw in text:
            keywords_found[kw] = keywords_found.get(kw, 0) + 1

print(f"\nKeyword frequency (in card text):")
for kw, cnt in sorted(keywords_found.items(), key=lambda x: -x[1]):
    print(f"  {kw}: {cnt}")

# Vanilla test calculation
print(f"\n--- Vanilla Test Analysis ---")
print(f"Formula: Stats = Attack + Health vs Expected = Mana * 2 + 1")
print(f"(Note: All {len(atk_zero)} cards have 0 attack - these are utility minions)")
for c in cards:
    stats = c["attack"] + c["health"]
    expected = c["mana"] * 2 + 1
    deficit = expected - stats
    print(
        f"  {c['name']:20s} | {c['mana']}mana | {c['attack']}/{c['health']} | stats={stats} expected={expected} deficit={deficit}"
    )

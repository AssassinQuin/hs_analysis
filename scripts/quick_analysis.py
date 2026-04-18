# -*- coding: utf-8 -*-
import json, re
from collections import Counter, defaultdict

with open("D:/code/game/hs_cards/standard_legendaries_analysis.json", "r", encoding="utf-8") as f:
    data = json.load(f)

scored = data["scored_minions"]
legendaries = data["legendaries"]

# Print top 30 by total_score
print("=== TOP 30 BY TOTAL SCORE ===")
for s in sorted(scored, key=lambda x: x["total_score"], reverse=True)[:30]:
    mechs = ", ".join(s.get("mechanics", []))
    print(f"  {s['mana']}m {s['attack']}/{s['health']} | score={s['total_score']:+.1f} | {s['name']} ({s['class']}) | {mechs}")

# Print bottom 10
print("\n=== BOTTOM 10 BY TOTAL SCORE ===")
for s in sorted(scored, key=lambda x: x["total_score"])[:10]:
    mechs = ", ".join(s.get("mechanics", []))
    print(f"  {s['mana']}m {s['attack']}/{s['health']} | score={s['total_score']:+.1f} | {s['name']} ({s['class']}) | {mechs}")

# Analyze text complexity - count unique effects mentioned
print("\n=== TEXT COMPLEXITY ANALYSIS ===")
text_lengths = []
effect_counts = []
for c in legendaries:
    text = c.get("text", "") or ""
    text_clean = re.sub(r"<[^>]+>", "", text)
    text_lengths.append(len(text_clean))
    # Count sentences/clauses as proxy for complexity
    clauses = text_clean.count(",") + text_clean.count("\n") + 1
    effect_counts.append(clauses)

print(f"  Avg text length: {sum(text_lengths)/len(text_lengths):.0f} chars")
print(f"  Max text length: {max(text_lengths)} chars")
print(f"  Avg effect clauses: {sum(effect_counts)/len(effect_counts):.1f}")
print(f"  Max effect clauses: {max(effect_counts)}")

# Mana efficiency by class (minions only)
print("\n=== AVERAGE STAT DEFICIT BY CLASS (Minions) ===")
class_names_cn = {
    "MAGE": "法师", "WARRIOR": "战士", "WARLOCK": "术士", "SHAMAN": "萨满",
    "ROGUE": "潜行者", "PALADIN": "圣骑士", "PRIEST": "牧师", "HUNTER": "猎人",
    "DRUID": "德鲁伊", "DEMONHUNTER": "恶魔猎手", "DEATHKNIGHT": "死亡骑士",
    "NEUTRAL": "中立",
}

class_deficit = defaultdict(list)
for s in scored:
    cls = s.get("class", "?")
    class_deficit[cls].append(s["stat_deficit"])

for cls in sorted(class_deficit.keys(), key=lambda c: sum(class_deficit[c])/len(class_deficit[c])):
    deficits = class_deficit[cls]
    avg = sum(deficits) / len(deficits)
    cn = class_names_cn.get(cls, cls)
    print(f"  {cn:8s}({cls:15s}): avg deficit={avg:+.1f} ({len(deficits)} cards)")

# Analyze keyword value calibration
print("\n=== KEYWORD VALUE CALIBRATION ===")
keyword_stats = defaultdict(lambda: {"count": 0, "avg_deficit": [], "avg_score": []})
for s in scored:
    for m in s.get("mechanics", []):
        keyword_stats[m]["count"] += 1
        keyword_stats[m]["avg_deficit"].append(s["stat_deficit"])
        keyword_stats[m]["avg_score"].append(s["total_score"])

for kw in sorted(keyword_stats.keys(), key=lambda k: -sum(keyword_stats[k]["avg_score"])/len(keyword_stats[k]["avg_score"])):
    stats = keyword_stats[kw]
    avg_def = sum(stats["avg_deficit"]) / len(stats["avg_deficit"])
    avg_sc = sum(stats["avg_score"]) / len(stats["avg_score"])
    print(f"  {kw:35s}: count={stats['count']:3d}, avg_deficit={avg_def:+.1f}, avg_score={avg_sc:+.1f}")

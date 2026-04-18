# -*- coding: utf-8 -*-
"""
Deep analysis of all standard legendary cards: keywords, effects, stat patterns.
Outputs comprehensive data for mathematical modeling.
"""
import json
import re
from collections import Counter, defaultdict

# Load data
with open("D:/code/game/hs_cards/standard_legendaries_analysis.json", "r", encoding="utf-8") as f:
    data = json.load(f)

legendaries = data["legendaries"]
minions = [c for c in legendaries if c.get("type") == "MINION"]
spells = [c for c in legendaries if c.get("type") == "SPELL"]

# ============================================
# 1. Complete mechanics + referenced tags
# ============================================
print("=" * 70)
print("1. ALL FORMAL MECHANICS (mechanics + referencedTags)")
print("=" * 70)

all_mechs = Counter()
for c in legendaries:
    for m in c.get("mechanics", []):
        all_mechs[m] += 1
    for rt in c.get("referencedTags", []):
        all_mechs[rt] += 1

for m, cnt in all_mechs.most_common():
    print(f"  {m:35s}: {cnt}")

# ============================================
# 2. Card text effect patterns
# ============================================
print("\n" + "=" * 70)
print("2. CARD TEXT EFFECT PATTERNS")
print("=" * 70)

patterns = {
    "direct_damage": r"\u9020\u6210\d+\u70b9\u4f24\u5bb3",           # 造成N点伤害
    "random_damage": r"\u968f\u673a.*\u4f24\u5bb3",                   # 随机.*伤害
    "draw": r"\u62bd.*\u724c",                                        # 抽牌
    "summon": r"\u53ec\u5524",                                        # 召唤
    "buff_stats": r"\u83b7\u5f97.*\u653b\u51fb\u529b|\+\d+.*\u653b\u51fb\u529b",  # buff atk
    "destroy": r"\u6d88\u706d",                                       # 消灭
    "copy": r"\u590d\u5236",                                          # 复制
    "generate": r"\u83b7\u53d6|\u83b7\u5f97\u4e00\u5f20",            # 获取/获得一张
    "mana_reduce": r"\u6cd5\u529b\u503c\u6d88\u8017.*(?:\u51cf\u5c11|\u964d\u4f4e|\u4e3a)", # mana reduce
    "aoe": r"\u6240\u6709.*(?:\u968f\u4ece|\u654c\u4eba|\u654c\u65b9)", # AoE
    "heal": r"\u6062\u590d|\u6cbb\u7597",                              # heal
    "armor": r"\u62a4\u7532",                                          # armor
    "conditional": r"\u5982\u679c.*(?:\u5219|\u5c31|\u4f1a)",         # conditional
    "turn_end": r"\u56de\u5408\u7ed3\u675f",                           # turn end
    "turn_start": r"\u56de\u5408\u5f00\u59cb",                         # turn start
    "silence": r"\u6c89\u9ed8",                                        # silence
    "freeze": r"\u51bb\u7ed3",                                         # freeze
    "poisonous": r"\u5267\u6bd2",                                      # poisonous
    "discard": r"\u4e22\u5f03",                                        # discard
    "overload": r"\u8fc7\u8f7d",                                       # overload
    "rune": r"\u6b8b\u9ab8|\u7b26\u6587",                              # corpse/rune
}

effect_counter = Counter()
for c in legendaries:
    text = c.get("text", "") or ""
    text_clean = re.sub(r"<[^>]+>", "", text)
    for pname, pat in patterns.items():
        if re.search(pat, text_clean):
            effect_counter[pname] += 1

for ename, cnt in effect_counter.most_common():
    print(f"  {ename:25s}: {cnt}")

# ============================================
# 3. Vanilla test stats by mana cost
# ============================================
print("\n" + "=" * 70)
print("3. VANILLA TEST BY MANA COST (Minions only)")
print("=" * 70)

by_mana = defaultdict(list)
for c in minions:
    by_mana[c.get("cost", 0)].append(c)

print(f"  {'Mana':>4s} | {'Count':>5s} | {'AvgStats':>8s} | {'Expected':>8s} | {'AvgAtk':>6s} | {'AvgHp':>6s} | {'AvgDeficit':>11s}")
print(f"  {'-'*4} | {'-'*5} | {'-'*8} | {'-'*8} | {'-'*6} | {'-'*6} | {'-'*11}")

for mana in sorted(by_mana.keys()):
    cards = by_mana[mana]
    if not cards:
        continue
    atks = [c.get("attack", 0) for c in cards]
    hps = [c.get("health", 0) for c in cards]
    stat_sums = [a + h for a, h in zip(atks, hps)]
    avg_stats = sum(stat_sums) / len(stat_sums)
    expected = mana * 2 + 1
    avg_atk = sum(atks) / len(atks)
    avg_hp = sum(hps) / len(hps)
    avg_deficit = avg_stats - expected
    print(f"  {mana:4d} | {len(cards):5d} | {avg_stats:8.1f} | {expected:8d} | {avg_atk:6.1f} | {avg_hp:6.1f} | {avg_deficit:+11.1f}")

# ============================================
# 4. Keyword co-occurrence
# ============================================
print("\n" + "=" * 70)
print("4. KEYWORD CO-OCCURRENCE (top pairs)")
print("=" * 70)

cooccur = Counter()
for c in minions:
    mechs = list(set(c.get("mechanics", []) + c.get("referencedTags", [])))
    for i in range(len(mechs)):
        for j in range(i+1, len(mechs)):
            pair = tuple(sorted([mechs[i], mechs[j]]))
            cooccur[pair] += 1

for pair, cnt in cooccur.most_common(15):
    print(f"  {pair[0]:25s} + {pair[1]:25s}: {cnt}")

# ============================================
# 5. Race/tribe distribution
# ============================================
print("\n" + "=" * 70)
print("5. RACE/TRIBE DISTRIBUTION (Minions)")
print("=" * 70)

race_counter = Counter()
for c in minions:
    for race in c.get("races", []):
        race_counter[race] += 1
    if not c.get("races"):
        race_counter["NO_RACE"] += 1

for race, cnt in race_counter.most_common():
    print(f"  {race:25s}: {cnt}")

# ============================================
# 6. Set distribution
# ============================================
print("\n" + "=" * 70)
print("6. SET DISTRIBUTION")
print("=" * 70)

set_counter = Counter(c.get("set", "?") for c in legendaries)
for s, cnt in set_counter.most_common():
    print(f"  {s:30s}: {cnt}")

# ============================================
# 7. Score distribution analysis
# ============================================
print("\n" + "=" * 70)
print("7. CURRENT MODEL SCORE DISTRIBUTION")
print("=" * 70)

scored = data.get("scored_minions", [])
if scored:
    scores = [s["total_score"] for s in scored]
    print(f"  Total scored: {len(scores)}")
    print(f"  Min score: {min(scores):.1f}")
    print(f"  Max score: {max(scores):.1f}")
    print(f"  Mean: {sum(scores)/len(scores):.1f}")
    sorted_scores = sorted(scores)
    mid = len(sorted_scores) // 2
    print(f"  Median: {sorted_scores[mid]:.1f}")
    
    # Distribution buckets
    buckets = Counter()
    for s in scores:
        if s < -3:
            buckets["<-3 (very under)"] += 1
        elif s < -1:
            buckets["-3 to -1"] += 1
        elif s < 0:
            buckets["-1 to 0"] += 1
        elif s < 1:
            buckets["0 to 1"] += 1
        elif s < 3:
            buckets["1 to 3"] += 1
        elif s < 5:
            buckets["3 to 5"] += 1
        else:
            buckets["5+ (very over)"] += 1
    
    print("\n  Score distribution:")
    for bucket in ["<-3 (very under)", "-3 to -1", "-1 to 0", "0 to 1", "1 to 3", "3 to 5", "5+ (very over)"]:
        if bucket in buckets:
            bar = "#" * buckets[bucket]
            print(f"    {bucket:20s}: {buckets[bucket]:3d} {bar}")

# ============================================
# 8. Spell analysis
# ============================================
print("\n" + "=" * 70)
print("8. SPELL ANALYSIS")
print("=" * 70)

for s in spells:
    mana = s.get("cost", 0)
    name = s.get("name", "?")
    cls = s.get("cardClass", "?")
    mechs = ", ".join(s.get("mechanics", []))
    text = re.sub(r"<[^>]+>", "", s.get("text", ""))
    print(f"  {mana}m | {name} ({cls}) | {mechs}")
    print(f"       {text[:80]}")

print("\nDone.")

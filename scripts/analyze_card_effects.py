"""
Comprehensive analysis of ALL 984 standard cards for variable/random/conditional effects.
Identifies cards that don't fit into our previous categories and abstracts new patterns.
"""
import json
import re
from collections import Counter, defaultdict

# Load HearthstoneJSON data
with open("hs_cards/hsjson_standard.json", "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]

print(f"Total standard cards: {len(cards)}")

# Define comprehensive effect patterns
EFFECT_PATTERNS = {
    # --- Previously defined ---
    "discover": r"发现",
    "dark_gift": r"黑暗之赐",
    "random_summon": r"随机.*召唤|召唤.*随机",
    "random_damage": r"随机.*伤害|随机.*射击|随机分配",
    "random_generate": r"随机.*获得|随机.*置入|随机.*添加|获取.*随机",
    "random_buff": r"随机.*属性|随机.*增益|随机.+/\+\d|随机.*攻击力|随机.*生命值",
    
    # --- New: Player choice effects (not random, but variable value) ---
    "choose_one": r"抉择",
    "adapt": r"适应",
    
    # --- New: Conditional effects (variable value based on game state) ---
    "conditional_mana": r"法力值.*消耗|法力值.*减少|法力值.*增加|消耗.*法力",
    "manathirst": r"法力渴求",
    "finale": r"终结",
    "conditional_if": r"如果|假如",
    "conditional_when": r"当|每当",
    "conditional_per": r"每有一个|每有一张|每点|每花费",
    
    # --- New: Cumulative effects ---
    "quest": r"任务",
    "questline": r"任务线",
    "excavate": r"发掘",
    
    # --- New: Transform/morph effects ---
    "transform": r"变形",
    "shift": r"转换|变幻",
    
    # --- New: Hand modifier effects ---
    "corrupt": r"腐蚀",
    "forge": r"锻造",
    "tradeable": r"可交易",
    
    # --- New: Board positional effects ---
    "adjacent": r"相邻",
    "aura": r"光环|所有.*获得|你的所有",
    
    # --- New: Turn timing effects ---
    "start_of_turn": r"回合开始|你的回合开始",
    "end_of_turn": r"回合结束|你的回合结束",
    "end_of_your_turn": r"你的回合结束时",
    
    # --- New: Deck/hand manipulation ---
    "dredge": r"探底",
    "draw": r"抽",
    "discard": r"弃|丢弃",
    "mill": r"疲劳",
    "shuffle": r"洗入",
    
    # --- New: Special mechanics ---
    "location": r"",  # identified by type
    "titan": r"",     # identified by mechanics
    "colossal": r"",  # identified by mechanics
    "dormant": r"休眠",
    "secret": r"奥秘",
    "lifesteal": r"吸血",
    "spellburst": r"法术迸发",
    "frenzy": r"暴怒",
    "honorable_kill": r"荣誉消灭",
    "overheal": r"过量治疗",
    "reborn": r"复生",
    "poisonous": r"剧毒",
    "venomous": r"致命",
    "inspire": r"激励",
    "invoke": r"祈求",
    "magnetic": r"磁力",
    "echo": r"回响",
    "rush": r"突袭",
    "charge": r"冲锋",
    "taunt": r"嘲讽",
    "divine_shield": r"圣盾",
    "stealth": r"潜行",
    "windfury": r"风怒",
    "deathrattle": r"亡语",
    "battlecry": r"战吼",
    "combo": r"连击",
    "outcast": r"流放",
    "tradeable_kw": r"可交易",
    "imbue": r"注能",
    "starship": r"星舰",
    "herald": r"先驱",
    "kindred": r"血亲",
    "tourist": r"游客",
    "reward": r"奖励",
    "sideboard": r"搭档|副牌组",
    
    # --- New: Multi-value effects ---
    "spell_damage": r"法术伤害|法术强度",
    "heal": r"恢复",
    "armor": r"护甲",
    "weapon": r"武器",
    "secret_gen": r"奥秘",
    "copy": r"复制",
    "steal": r"夺取|偷取|控制",
    "silence": r"沉默",
    "freeze": r"冻结",
    "immune": r"免疫",
    "cant_attack": r"无法攻击",
    "cant_target": r"无法成为目标",
}

# Categorize all cards
results = defaultdict(list)
uncategorized = []

for card in cards:
    name = card.get("name", "")
    text = card.get("text", "") or ""
    card_type = card.get("type", "")
    mechanics = card.get("mechanics", []) or []
    card_id = card.get("id", "")
    dbf_id = card.get("dbfId", "")
    cost = card.get("cost", 0)
    card_class = card.get("cardClass", "")
    card_set = card.get("set", "")
    
    # Clean text (remove HTML tags)
    clean_text = re.sub(r"<[^>]+>", "", text)
    
    matched = set()
    
    # Check type-based categories
    if card_type == "LOCATION":
        matched.add("location")
    if "COLOSSAL" in mechanics:
        matched.add("colossal")
    if "DORMANT" in mechanics:
        matched.add("dormant")
    
    # Check mechanic-based categories
    mech_map = {
        "DISCOVER": "discover",
        "BATTLECRY": "battlecry",
        "DEATHRATTLE": "deathrattle",
        "COMBO": "combo",
        "SECRET": "secret",
        "TAUNT": "taunt",
        "CHARGE": "charge",
        "RUSH": "rush",
        "DIVINE_SHIELD": "divine_shield",
        "STEALTH": "stealth",
        "WINDFURY": "windfury",
        "LIFESTEAL": "lifesteal",
        "SPELLBURST": "spellburst",
        "FRENZY": "frenzy",
        "REBORN": "reborn",
        "POISONOUS": "poisonous",
        "OVERHEAL": "overheal",
        "MAGNETIC": "magnetic",
        "ECHO": "echo",
        "TRADEABLE": "tradeable_kw",
        "OUTCAST": "outcast",
        "DREDGE": "dredge",
        "CORRUPT": "corrupt",
        "HONORABLE_KILL": "honorable_kill",
        "IMBUE": "imbue",
    }
    for mech, cat in mech_map.items():
        if mech in mechanics:
            matched.add(cat)
    
    # Check text-based patterns
    for cat, pattern in EFFECT_PATTERNS.items():
        if cat in ("location", "colossal", "dormant"):
            continue  # already handled above
        if pattern and re.search(pattern, clean_text):
            matched.add(cat)
    
    # Store matches
    card_info = {
        "id": card_id,
        "dbfId": dbf_id,
        "name": name,
        "cost": cost,
        "type": card_type,
        "class": card_class,
        "set": card_set,
        "mechanics": mechanics,
        "text": clean_text[:200],
        "matched_categories": list(matched),
    }
    
    for cat in matched:
        results[cat].append(card_info)
    
    if not matched:
        uncategorized.append(card_info)

# Generate report
lines = []
L = lines.append

L("# Standard Card Effect Analysis Report")
L(f"Total cards: {len(cards)}")
L(f"Cards with matched effects: {len(cards) - len(uncategorized)}")
L(f"Uncategorized cards: {len(uncategorized)}")
L("")

# --- Group 1: Random effects (previously defined) ---
L("## Group 1: Random Effects (Previously Defined)")
random_cats = ["discover", "dark_gift", "random_summon", "random_damage", "random_generate", "random_buff"]
for cat in random_cats:
    items = results.get(cat, [])
    L(f"### {cat}: {len(items)} cards")
    for item in items[:5]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:100]}')
    if len(items) > 5:
        L(f"  ... and {len(items) - 5} more")
    L("")

# --- Group 2: Player Choice Effects (variable but not random) ---
L("## Group 2: Player Choice Effects (NOT random, but variable value)")
L("These cards have VARIABLE value depending on player choice - NOT modeled by random EV.")
L("")
choice_cats = ["choose_one", "adapt"]
for cat in choice_cats:
    items = results.get(cat, [])
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 3: Conditional Effects (value depends on game state) ---
L("## Group 3: Conditional Effects (value depends on game state)")
L("These cards have value that CHANGES based on game conditions - need state-aware modeling.")
L("")
cond_cats = ["conditional_if", "conditional_when", "conditional_per", "manathirst", "finale", "conditional_mana"]
for cat in cond_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 4: Cumulative/Progressive Effects ---
L("## Group 4: Cumulative/Progressive Effects (build up over turns)")
L("These cards have escalating value - need time-discounted EV modeling.")
L("")
prog_cats = ["quest", "excavate"]
for cat in prog_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 5: Transform/Morph Effects ---
L("## Group 5: Transform/Morph Effects (become something else)")
L("These cards change identity - the 'target' card is unknown until it transforms.")
L("")
transform_cats = ["transform", "shift", "corrupt", "forge"]
for cat in transform_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 6: Positional/Aura Effects ---
L("## Group 6: Positional/Aura Effects (board-position dependent)")
L("These cards have value that depends on board state - need board-aware modeling.")
L("")
pos_cats = ["adjacent", "aura"]
for cat in pos_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 7: Timing Effects ---
L("## Group 7: Turn Timing Effects (trigger at specific times)")
L("")
timing_cats = ["start_of_turn", "end_of_turn", "end_of_your_turn"]
for cat in timing_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:5]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 5:
        L(f"  ... and {len(items) - 5} more")
    L("")

# --- Group 8: Special Mechanics ---
L("## Group 8: Special Mechanics (unique card types)")
L("")
special_cats = ["location", "titan", "colossal", "dormant", "secret", "starship", "imbue"]
for cat in special_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:8]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 8:
        L(f"  ... and {len(items) - 8} more")
    L("")

# --- Group 9: Keyword Mechanics ---
L("## Group 9: Keyword Mechanics (trigger-based)")
L("")
kw_cats = ["battlecry", "deathrattle", "spellburst", "frenzy", "overheal", "honorable_kill", "combo", "outcast", "inspire"]
for cat in kw_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:3]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 3:
        L(f"  ... and {len(items) - 3} more")
    L("")

# --- Group 10: Deck/Hand Manipulation ---
L("## Group 10: Deck/Hand Manipulation")
L("")
deck_cats = ["dredge", "draw", "discard", "shuffle", "tradeable_kw"]
for cat in deck_cats:
    items = results.get(cat, [])
    if not items:
        continue
    L(f"### {cat}: {len(items)} cards")
    for item in items[:3]:
        L(f'  - {item["name"]} ({item["cost"]}mana {item["class"]}) | {item["text"][:120]}')
    if len(items) > 3:
        L(f"  ... and {len(items) - 3} more")
    L("")

# --- Uncategorized cards ---
L("## Uncategorized Cards (no matched patterns)")
L(f"Total: {len(uncategorized)}")
for item in uncategorized[:20]:
    L(f'  - {item["name"]} ({item["cost"]}mana {item["type"]} {item["class"]}) | {(item["text"] or "")[:100]}')
if len(uncategorized) > 20:
    L(f"  ... and {len(uncategorized) - 20} more")
L("")

# --- Summary Statistics ---
L("## Summary Statistics")
L("")
sorted_cats = sorted(results.keys(), key=lambda k: -len(results[k]))
for cat in sorted_cats:
    L(f"- {cat}: {len(results[cat])} cards")

L("")
L("## EV Modeling Difficulty Assessment")
L("")
# Categorize by modeling difficulty
easy = ["random_damage", "random_buff", "heal", "armor"]
medium = ["discover", "random_summon", "random_generate", "dark_gift", "draw", "dredge"]
hard = ["conditional_if", "conditional_when", "conditional_per", "choose_one", "quest", "excavate"]
very_hard = ["location", "titan", "colossal", "dormant", "starship", "transform", "aura", "adjacent", "imbue"]

easy_count = sum(len(results.get(c, [])) for c in easy)
medium_count = sum(len(results.get(c, [])) for c in medium)
hard_count = sum(len(results.get(c, [])) for c in hard)
very_hard_count = sum(len(results.get(c, [])) for c in very_hard)

L(f"### Easy (direct calculation): {easy_count} card-effects")
for c in easy:
    L(f"  - {c}: {len(results.get(c, []))}")
L(f"### Medium (pool-based EV): {medium_count} card-effects")
for c in medium:
    L(f"  - {c}: {len(results.get(c, []))}")
L(f"### Hard (state-conditional): {hard_count} card-effects")
for c in hard:
    L(f"  - {c}: {len(results.get(c, []))}")
L(f"### Very Hard (complex systems): {very_hard_count} card-effects")
for c in very_hard:
    L(f"  - {c}: {len(results.get(c, []))}")

# --- NEW: Cross-analysis - cards with multiple random/variable effects ---
L("")
L("## Multi-Effect Cards (cards with 3+ variable effects)")
L("")
multi = [(name, len(cats), cats) for name, cats in [
    (item["name"], item["matched_categories"]) 
    for cat_items in results.values() 
    for item in cat_items
] if len(cats) >= 3]
# Deduplicate
seen = set()
for name, count, cats in sorted(multi, key=lambda x: -x[1]):
    if name not in seen:
        seen.add(name)
        L(f"- {name}: {count} effects → {', '.join(sorted(cats))}")

# Save
with open("hs_cards/effect_analysis_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Report saved to hs_cards/effect_analysis_report.md")
print(f"Total categories: {len(results)}")
print(f"Uncategorized: {len(uncategorized)}")

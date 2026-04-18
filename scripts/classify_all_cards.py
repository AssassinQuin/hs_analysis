"""
Comprehensive classification of ALL 984 standard cards according to the complete
sub-model framework. Identifies cards that don't fit ANY category.
"""
import json
import re
from collections import defaultdict

# Load HearthstoneJSON data
with open("hs_cards/hsjson_standard.json", "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]

print(f"Total standard cards: {len(cards)}")

# ============================================================
# COMPLETE TAXONOMY OF CARD EFFECTS
# ============================================================

# Text-based patterns
TEXT_PATTERNS = {
    # --- Random Effects (need EV modeling) ---
    "discover": r"发现",
    "dark_gift": r"黑暗之赐",
    "random_summon": r"随机.*召唤|召唤.*随机",
    "random_damage": r"随机.*伤害|随机.*射击|随机分配",
    "random_generate": r"随机.*获得|随机.*置入|随机.*添加|获取.*随机",
    "random_buff": r"随机.*属性|随机.*增益|随机.+/\+\d|随机.*攻击力|随机.*生命值",

    # --- Player Choice Effects ---
    "choose_one": r"抉择",

    # --- Conditional Effects ---
    "conditional_if": r"如果",
    "conditional_when": r"当|每当",
    "conditional_per": r"每有一个|每有一张|每点|每花费",
    "conditional_mana": r"法力值.*消耗|法力值.*减少|法力值.*增加|消耗.*法力|法力水晶",

    # --- Timing Effects ---
    "start_of_turn": r"回合开始|你的回合开始",
    "end_of_turn": r"回合结束|你的回合结束时",

    # --- Transform/Morph ---
    "transform": r"变形",

    # --- Positional/Aura ---
    "adjacent": r"相邻",
    "aura": r"光环|你的所有随从|你的所有友方|所有随从获得|所有友方",

    # --- NEW Mechanics ---
    "omen": r"兆示",
    "rewind": r"回溯",
    "fission": r"裂变",
    "lineage": r"延系",
    "imbue_text": r"灌注",
    "tradeable_text": r"可交易",
    "corrupt": r"腐蚀",
    "quest_text": r"任务",
    "secret_text": r"奥秘",
    "reward": r"奖励",

    # --- Deck/Hand Manipulation ---
    "draw": r"抽",
    "discard": r"弃|丢弃",
    "shuffle": r"洗入",

    # --- Simple Deterministic Effects ---
    "fixed_damage": r"造成.*伤害",
    "fixed_summon": r"召唤",
    "fixed_destroy": r"消灭",
    "fixed_buff": r"\+\d+/\+\d+|\+\d+攻击|获得.*攻击力|获得.*生命值",
    "fixed_heal": r"恢复.*生命|为.*恢复",
    "fixed_armor": r"护甲|获得.*护甲",
    "copy_effect": r"复制",
    "steal_effect": r"夺取|偷取|控制",
    "silence_effect": r"沉默",
    "freeze_effect": r"冻结",
    "weapon_equip": r"武器|装备",
    "spell_damage_text": r"法术伤害|法术强度",
    "overload": r"过载",
    "cant_attack": r"无法攻击",
    "immune_text": r"免疫",
    "enchant": r"使.*获得|赋予",

    # --- NEW: Previously missing patterns (from gap analysis) ---
    "set_stat": r"变为",           # 设置属性值/生命值 (生而平等, 阿玛拉的故事)
    "bounce": r"移回.*手牌",       # 弹回手牌 (眩晕)
    "resource_summon": r"残骸.*复活|复活.*残骸|复活.*为",  # 资源型召唤 (亡者大军)
    "hand_split": r"拆成|分裂",    # 手牌分裂 (裂解术)
    "conditional_target": r"未受伤|已受伤",  # 条件目标 (背刺)
}

# Mechanic-tag based categories (from the `mechanics` array)
MECH_MAP = {
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
    "OVERHEAL": "overheal",
    "HONORABLE_KILL": "honorable_kill",
    "MAGNETIC": "magnetic",
    "ECHO": "echo",
    "TRADEABLE": "tradeable_kw",
    "OUTCAST": "outcast",
    "DREDGE": "dredge",
    "CORRUPT": "corrupt",
    "REBORN": "reborn",
    "POISONOUS": "poisonous",
    "CHOOSE_ONE": "choose_one_mech",
    "TAUNT": "taunt",
    "COLLECTION": "collection",
    "INVISIBLE": "invisible",
    "IMMUNE": "immune_kw",
}

# Type-based categories
def check_type_categories(card):
    cats = set()
    if card.get("type") == "LOCATION":
        cats.add("location")
    if card.get("type") == "WEAPON":
        cats.add("weapon_type")
    if card.get("type") == "HERO":
        cats.add("hero_card")
    return cats

def check_mechanics_categories(card):
    cats = set()
    mechanics = card.get("mechanics") or []
    for mech in mechanics:
        if mech in MECH_MAP:
            cats.add(MECH_MAP[mech])
    if "COLOSSAL" in mechanics:
        cats.add("colossal")
    if "DORMANT" in mechanics:
        cats.add("dormant")
    return cats

# ============================================================
# SUB-MODEL MAPPING (A-F)
# ============================================================

SUB_MODEL_MAP = {
    "A_board_state": {
        "description": "Board State Evaluation — affects board/hand/hero state",
        "categories": {
            # Original
            "fixed_summon", "random_summon", "fixed_buff", "random_buff",
            "fixed_destroy", "fixed_damage", "taunt", "rush", "charge",
            "divine_shield", "aura", "adjacent", "colossal", "reborn",
            "fission", "lineage", "weapon_equip", "weapon_type",
            "copy_effect", "fixed_heal", "lifesteal",
            # EXPANDED: hand/board/hero state
            "vanilla_minion",      # 白板随从 = 纯场面价值
            "draw",                # 抽牌 = 手牌状态
            "enchant",             # 附魔 = 改变随从属性
            "transform",           # 变形 = 改变随从身份
            "shuffle",             # 洗牌 = 牌库状态
            "stealth",             # 潜行 = 生存概率
            "spell_damage_text",   # 法术伤害 = 输出增强
            "fixed_armor",         # 护甲 = 英雄状态
            "tradeable_text", "tradeable_kw",  # 可交易 = 手牌管理
            "set_stat",            # 设置属性值 = 直接改变场面
            "bounce",              # 弹回 = 移除场面
            "resource_summon",     # 资源型召唤 = 场面扩充
            "conditional_target",  # 条件目标 = 效果触发条件
            "poisonous",           # 剧毒 = 威胁评估
        }
    },
    "B_opponent_threat": {
        "description": "Opponent Threat Assessment — deals with enemy",
        "categories": {
            "fixed_damage", "random_damage", "fixed_destroy", "steal_effect",
            "silence_effect", "freeze_effect", "secret", "secret_text",
            "discard", "cant_attack",
            # EXPANDED: enemy interaction
            "transform",           # 变形敌方随从
            "bounce",              # 弹回敌方随从
            "set_stat",            # 设置敌方属性 (生而平等)
            "hand_split",          # 手牌分裂 (破坏对手手牌)
        }
    },
    "C_lingering_effects": {
        "description": "Lingering Effect Valuation — cross-turn effects",
        "categories": {
            "weapon_equip", "weapon_type", "location", "dormant",
            "aura", "secret", "secret_text", "end_of_turn", "start_of_turn",
            "quest_text", "reward", "overload", "immune_kw", "immune_text",
            "hero_card", "cant_attack", "windfury",
            # EXPANDED: cross-turn modifications
            "conditional_mana",    # 法力修改 = 跨回合影响
            "outcast",             # 流放 = 位置依赖的跨回合效果
            "tradeable_text", "tradeable_kw",  # 可交易 = 跨回合决策
        }
    },
    "D_trigger_probability": {
        "description": "Trigger Probability Model — probability-dependent effects",
        "categories": {
            "deathrattle", "random_summon", "random_damage", "random_generate",
            "random_buff", "dark_gift", "battlecry", "spellburst", "frenzy",
            "overheal", "honorable_kill", "omen", "rewind", "corrupt",
            "conditional_when",
            # EXPANDED: conditional probability
            "conditional_if",      # 条件效果 = 需要概率评估 P(条件满足)
            "conditional_per",     # 数量条件 = 需要状态估计
            "hand_split",          # 手牌分裂 = 随机目标选择
            "conditional_target",  # 条件目标 = 需要目标状态判断
        }
    },
    "E_meta_intelligence": {
        "description": "Meta Intelligence — opponent modeling, quest tracking",
        "categories": {
            "quest_text", "discover", "reward",
        }
    },
    "F_card_pool": {
        "description": "Card Pool & Rules — random card pools, Discover rules",
        "categories": {
            "discover", "dark_gift", "random_summon", "random_generate",
            "random_buff", "omen", "rewind", "imbue_text",
        }
    },
    "G_player_choice": {
        "description": "Player Optimal Choice — player picks best option (EV = max)",
        "categories": {
            "choose_one", "choose_one_mech",
        }
    },
}

# ============================================================
# CLASSIFY ALL CARDS
# ============================================================

results = defaultdict(list)  # category -> [card_info, ...]
card_categories = {}  # card_name -> set of categories
uncategorized = []
all_classified = []

for card in cards:
    name = card.get("name", "")
    text = card.get("text", "") or ""
    card_type = card.get("type", "")
    mechanics = card.get("mechanics", []) or []
    card_id = card.get("id", "")
    dbf_id = card.get("dbfId", 0)
    cost = card.get("cost", 0)
    card_class = card.get("cardClass", "")
    card_set = card.get("set", "")
    attack = card.get("attack")
    health = card.get("health")

    # Clean text (remove HTML tags)
    clean_text = re.sub(r"<[^>]+>", "", text)
    # Also remove embedded IDs like 122972
    clean_text = re.sub(r"\d{5,}", "", clean_text)

    matched = set()

    # 1. Type-based
    matched |= check_type_categories(card)

    # 2. Mechanics-based
    matched |= check_mechanics_categories(card)

    # 3. Text-based patterns
    for cat, pattern in TEXT_PATTERNS.items():
        if pattern and re.search(pattern, clean_text):
            matched.add(cat)

    # 4. Special: vanilla minions with attack/health but no text effects
    if not matched and card_type == "MINION" and attack is not None and health is not None:
        matched.add("vanilla_minion")

    # 5. Special: spells with no text
    if not matched and card_type == "SPELL" and not clean_text.strip():
        matched.add("basic_spell")

    card_info = {
        "name": name,
        "id": card_id,
        "cost": cost,
        "type": card_type,
        "class": card_class,
        "set": card_set,
        "attack": attack,
        "health": health,
        "mechanics": mechanics,
        "text": clean_text[:250],
        "categories": sorted(matched),
    }

    card_categories[name] = matched
    all_classified.append(card_info)

    for cat in matched:
        results[cat].append(card_info)

    if not matched:
        uncategorized.append(card_info)

# ============================================================
# SUB-MODEL COVERAGE ANALYSIS
# ============================================================

sub_model_coverage = {}
for sm_name, sm_def in SUB_MODEL_MAP.items():
    covered = set()
    for card_info in all_classified:
        if card_info["categories"] and set(card_info["categories"]) & sm_def["categories"]:
            covered.add(card_info["name"])
    sub_model_coverage[sm_name] = len(covered)

# Cards covered by at least one sub-model
covered_by_any_submodel = set()
for card_info in all_classified:
    cats = set(card_info["categories"])
    for sm_name, sm_def in SUB_MODEL_MAP.items():
        if cats & sm_def["categories"]:
            covered_by_any_submodel.add(card_info["name"])
            break

# ============================================================
# GENERATE REPORT
# ============================================================

lines = []
L = lines.append

L("# 全卡牌分类报告 (Full Card Classification Report)")
L(f"标准卡牌总数: {len(cards)}")
L(f"已分类: {len(cards) - len(uncategorized)}")
L(f"未分类: {len(uncategorized)}")
L("")

# --- Section 1: Sub-Model Coverage ---
L("## 1. 子模型覆盖分析 (Sub-Model Coverage)")
L("")
L("| 子模型 | 描述 | 覆盖卡牌数 |")
L("|--------|------|-----------|")
for sm_name, count in sorted(sub_model_coverage.items(), key=lambda x: -x[1]):
    desc = SUB_MODEL_MAP[sm_name]["description"]
    L(f"| {sm_name} | {desc} | {count} |")
L(f"| **任意子模型** | 被至少一个子模型覆盖 | **{len(covered_by_any_submodel)}** |")
L(f"| **无子模型覆盖** | 不被任何子模型覆盖 | **{len(cards) - len(covered_by_any_submodel)}** |")
L("")

# --- Section 2: Category Statistics ---
L("## 2. 分类统计 (Category Statistics)")
L("")
L("| 分类 | 卡牌数 |")
L("|------|--------|")
sorted_cats = sorted(results.keys(), key=lambda k: -len(results[k]))
for cat in sorted_cats:
    L(f"| {cat} | {len(results[cat])} |")
L("")

# --- Section 3: Previously uncategorized — now classified ---
L("## 3. 之前未分类的70张卡牌的新归属")
L("")
# These are the 70 cards from the previous analysis that were uncategorized
# Let's check which ones now have categories
previously_uncategorized_names = [
    "试验演示", "能量窃取", "眩晕", "祈雨元素", "奥术涌流", "怪异触手",
    "进击的募援官", "图腾魔像", "灵魂炸弹", "战斗邪犬", "诺格弗格市长",
    "神圣惩击", "火球术", "烈焰风暴", "地狱烈焰", "背刺", "刺杀", "奉献",
    "斩杀", "团队领袖",
]

# Find all cards that have NO complex categories (only vanilla/basic)
simple_cats = {"vanilla_minion", "basic_spell", "taunt", "rush", "divine_shield",
               "stealth", "windfury", "lifesteal", "reborn", "poisonous", "immune_kw",
               "spell_damage_text", "overload", "cant_attack", "aura"}

L("### 3a. 纯白板/简单效果卡牌 (Vanilla/Simple cards)")
L("These cards have ONLY static keywords or vanilla stats — no complex effects to model.")
L("")
simple_only = []
for card_info in all_classified:
    cats = set(card_info["categories"])
    # Check if ALL categories are "simple" (static keywords)
    non_simple = cats - simple_cats
    if cats and not non_simple and card_info["type"] == "MINION":
        simple_only.append(card_info)

L(f"Count: {len(simple_only)}")
for item in sorted(simple_only, key=lambda x: x["cost"]):
    cats_str = ", ".join(item["categories"])
    atk_hp = f"{item['attack']}/{item['health']}" if item['attack'] is not None else ""
    L(f"- {item['name']} ({item['cost']}费 {atk_hp} {item['class']}) [{cats_str}] | {item['text'][:80] if item['text'] else '(白板)'}")
L("")

# --- Section 4: Truly uncategorized ---
L("## 4. 完全未分类卡牌 (Truly Uncategorized Cards)")
L("")
L(f"Total: {len(uncategorized)}")
L("")
if uncategorized:
    for item in sorted(uncategorized, key=lambda x: (x["type"], x["cost"])):
        atk_hp = ""
        if item["attack"] is not None:
            atk_hp = f" {item['attack']}/{item['health']}"
        L(f"- {item['name']} ({item['cost']}费 {item['type']} {item['class']}{atk_hp}) | {item['text'][:150] if item['text'] else '(无文本)'}")
        L(f"  → mechanics: {item['mechanics']}")
else:
    L("无 — 所有卡牌均已分类！")
L("")

# --- Section 5: Cards NOT covered by any sub-model ---
L("## 5. 不被子模型覆盖的卡牌")
L("")
uncovered_cards = []
for card_info in all_classified:
    cats = set(card_info["categories"])
    covered = False
    for sm_name, sm_def in SUB_MODEL_MAP.items():
        if cats & sm_def["categories"]:
            covered = True
            break
    if not covered and cats:
        uncovered_cards.append(card_info)

L(f"Total: {len(uncovered_cards)}")
L("")
for item in sorted(uncovered_cards, key=lambda x: (x["type"], x["cost"])):
    cats_str = ", ".join(item["categories"])
    atk_hp = f" {item['attack']}/{item['health']}" if item["attack"] is not None else ""
    L(f"- {item['name']} ({item['cost']}费 {item['type']} {item['class']}{atk_hp}) [{cats_str}] | {item['text'][:120] if item['text'] else '(无文本)'}")
L("")

# --- Section 6: Detailed category → cards mapping ---
L("## 6. 各分类详细卡牌列表")
L("")
for cat in sorted_cats:
    items = results[cat]
    L(f"### {cat}: {len(items)} 张")
    for item in items[:5]:
        atk_hp = f" {item['attack']}/{item['health']}" if item["attack"] is not None else ""
        L(f"- {item['name']} ({item['cost']}费 {item['class']}{atk_hp}) | {item['text'][:100] if item['text'] else '(无文本)'}")
    if len(items) > 5:
        L(f"... 还有 {len(items) - 5} 张")
    L("")

# Save report
with open("hs_cards/full_classification_report.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nReport saved to hs_cards/full_classification_report.md")
print(f"Total categories found: {len(results)}")
print(f"Truly uncategorized: {len(uncategorized)}")
print(f"Not covered by any sub-model: {len(uncovered_cards)}")
print(f"\nCategory counts:")
for cat in sorted_cats:
    print(f"  {cat}: {len(results[cat])}")

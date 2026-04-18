#!/usr/bin/env python3
"""
V7 卡牌评分引擎 — 基于 enums.json 扩展 + HSReplay Rankings 权重融合

在 V2 (L1-L5) 基础上增加:
  L2+ : 扩展关键字层级 (50+ 关键字)
  L2.5: 随从种族 + 法术派系协同评分
  L3+ : 类型条件解析 ("发现一张龙牌" vs "发现一张法术牌")
  L7  : HSReplay Rankings 真实胜率校准

用法: python scripts/v7_scoring_engine.py
"""

import json
import math
import os
import re
import sys
import io
from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import curve_fit

# ── 输出编码 ──
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════════════════
# 1. 数据加载
# ═══════════════════════════════════════════════════════════════════

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_enums(path):
    """加载 hearthstone_enums.json"""
    data = load_json(path)
    races = {}
    for v in data["随从类型"]["values"]:
        races[v["id"]] = {"en": v["en"], "zh": v["zh"]}
    schools = {}
    for v in data["法术派系"]["values"]:
        schools[v["id"]] = {"en": v["en"], "zh": v["zh"]}
    keywords = {}
    for v in data["关键字"]["values"]:
        keywords[v["id"]] = {"en": v["en"], "zh": v["zh"]}
    return {"races": races, "schools": schools, "keywords": keywords}


def load_rankings(path):
    """加载 HSReplay_Card_Rankings.xlsx → {中文名: {deck_wr, played_wr, include_rate, play_count}}"""
    try:
        import openpyxl
    except ImportError:
        print("⚠️  openpyxl 未安装，跳过 L7 Rankings 校准层")
        return {}

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["总排行"]
    rows = list(ws.iter_rows(values_only=True))

    db = {}
    for r in rows[4:]:  # skip 4 header rows
        if r[0] is None or not isinstance(r[0], (int, float)):
            continue
        name_col = r[1]
        if not name_col:
            continue
        # "中文名 / English Name" → "中文名"
        name = str(name_col).split("/")[0].strip()
        deck_wr = float(r[10]) if r[10] is not None else None
        played_wr = float(r[12]) if r[12] is not None else None
        include_rate = float(r[8]) if r[8] is not None else None
        play_count = int(r[11]) if r[11] is not None else 0
        if deck_wr is not None:
            db[name] = {
                "deck_wr": deck_wr,
                "played_wr": played_wr,
                "include_rate": include_rate,
                "play_count": play_count,
            }
    wb.close()
    return db


# ═══════════════════════════════════════════════════════════════════
# 2. 扩展关键字层级 (L2+)
# ═══════════════════════════════════════════════════════════════════

KEYWORD_TIERS = {
    "power": {
        # 原有
        "BATTLECRY", "DEATHRATTLE", "DISCOVER", "DIVINE_SHIELD", "RUSH",
        "CHARGE", "WINDFURY", "TAUNT", "LIFESTEAL", "STEALTH",
        "CHOOSE_ONE", "QUEST",
        # 新增 — 高影响力机制
        "FORGE", "EXCAVATE", "QUICKDRAW", "TITAN", "ECHO",
    },
    "mechanical": {
        # 原有
        "TRIGGER_VISUAL", "AURA", "COLOSSUS", "REBORN", "IMBUE",
        "OUTCAST", "IMMUNE", "SECRET", "OVERLOAD", "COMBO",
        "SPELLPOWER", "FREEZE", "POISONOUS", "SILENCE",
        "TRADEABLE", "SIDE_QUEST", "START_OF_GAME",
        # 新增 — 中等影响力机制
        "SPELLBURST", "FRENZY", "CORRUPT", "DREDGE", "INFUSE",
        "HONORABLE_KILL", "OVERHEAL", "MANATHIRST", "OVERKILL",
        "INSPIRE", "MAGNETIC", "TWINSPELL", "MINIATURIZE", "GIGANTIFY",
        "MORPH", "COUNTER", "VENOMOUS",
    },
}

TIER_BASES = {"power": 1.5, "mechanical": 0.75, "niche": 0.5}

# 关键词中文映射
KEYWORD_CN = {
    "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "TAUNT": "嘲讽",
    "DIVINE_SHIELD": "圣盾", "CHARGE": "冲锋", "RUSH": "突袭",
    "WINDFURY": "风怒", "STEALTH": "潜行", "LIFESTEAL": "吸血",
    "POISONOUS": "剧毒", "VENOMOUS": "剧毒", "FREEZE": "冻结",
    "OVERLOAD": "过载", "SPELLPOWER": "法伤", "SILENCE": "沉默",
    "COMBO": "连击", "DISCOVER": "发现", "SECRET": "奥秘",
    "QUEST": "任务", "SIDE_QUEST": "支线任务", "CHOOSE_ONE": "抉择",
    "ECHO": "回响", "TWINSPELL": "双生", "REBORN": "复生",
    "OUTCAST": "流放", "SPELLBURST": "法术迸发", "FRENZY": "暴怒",
    "CORRUPT": "腐蚀", "TRADEABLE": "可交易", "DREDGE": "掘葬",
    "INFUSE": "充能", "HONORABLE_KILL": "荣誉消灭", "OVERHEAL": "过量治疗",
    "MANATHIRST": "法力渴求", "OVERKILL": "超杀", "INSPIRE": "激励",
    "MAGNETIC": "磁力", "FORGE": "锻造", "QUICKDRAW": "速瞄",
    "EXCAVATE": "挖掘", "COLOSSUS": "巨像", "TITAN": "泰坦",
    "IMBUE": "灌注", "IMMUNE": "免疫", "AURA": "光环",
    "TRIGGER_VISUAL": "触发", "START_OF_GAME": "开局",
    "MINIATURIZE": "迷你化", "GIGANTIFY": "巨大化", "MORPH": "变形",
    "COUNTER": "反制", "ENRAGED": "激怒", "CANT_ATTACK": "无法攻击",
}


def get_keyword_tier(kw):
    if kw in KEYWORD_TIERS["power"]:
        return "power"
    if kw in KEYWORD_TIERS["mechanical"]:
        return "mechanical"
    return "niche"


def calc_keyword_score(card, curve_popt):
    """L2: 关键词评分 (与 V2 相同逻辑，但用扩展后的 KEYWORD_TIERS)"""
    mechs = set(card.get("mechanics", []))
    mana = max(card.get("cost", 0), 0)
    if not mechs:
        return 0.0, []

    total = 0.0
    details = []
    for kw in mechs:
        tier = get_keyword_tier(kw)
        base = TIER_BASES[tier]
        val = base * (1 + 0.1 * mana)
        total += val
        cn = KEYWORD_CN.get(kw, kw)
        details.append(f"{cn}({tier[0]})={val:+.1f}")
    return total, details


# ═══════════════════════════════════════════════════════════════════
# 3. 类型协同层 (L2.5)
# ═══════════════════════════════════════════════════════════════════

# 种族 → 协同加成
RACE_BONUS = {
    "野兽": 1.2, "龙": 1.3, "恶魔": 1.2, "元素": 1.1,
    "亡灵": 1.1, "鱼人": 1.3, "机械": 1.0, "纳迦": 1.1,
    "海盗": 1.2, "图腾": 1.0, "德莱尼": 1.0, "野猪人": 1.0,
}

# 法术派系 → 协同加成
SPELL_SCHOOL_BONUS = {
    "奥术": 1.0, "邪能": 1.0, "火焰": 1.0, "冰霜": 1.0,
    "神圣": 1.0, "自然": 1.1, "暗影": 1.0,
}

# 符文类型（死亡骑士特有）
RUNE_TYPES = {"血", "冰", "邪"}


def calc_race_synergy(card, mana):
    """L2.5a: 随从种族协同评分"""
    if card.get("type") != "MINION":
        return 0.0, []
    race = card.get("race", "")
    if not race:
        return 0.0, []

    # 解析复合种族: "亡灵 野兽" → 取主种族（第一个非符文类型）
    parts = race.replace("，", " ").split()
    primary_race = None
    for p in parts:
        if p in RACE_BONUS:
            primary_race = p
            break
        # 去掉符文后缀: "亡灵 冰" → primary is 亡灵
        # 有些种族带符文后缀如 "亡灵 冰邪"
        for known_race in RACE_BONUS:
            if p.startswith(known_race):
                primary_race = known_race
                break
        if primary_race:
            break

    if not primary_race:
        return 0.0, []

    bonus = RACE_BONUS[primary_race]
    val = bonus * (1 + 0.05 * mana)
    return val, [f"种族({primary_race})={val:+.1f}"]


def calc_spell_school(card):
    """L2.5b: 法术派系评分"""
    if card.get("type") != "SPELL":
        return 0.0, []

    # 从 race 字段获取（法术卡的 race 实际存的是派系）
    race = card.get("race", "")
    if race:
        parts = race.replace("，", " ").split()
        for p in parts:
            if p in SPELL_SCHOOL_BONUS:
                bonus = SPELL_SCHOOL_BONUS[p]
                val = bonus * 0.5
                return val, [f"派系({p})={val:+.1f}"]

    # fallback: 从卡牌文本推断
    text = card.get("text", "") or ""
    for cn_name, bonus in SPELL_SCHOOL_BONUS.items():
        if cn_name in text:
            val = bonus * 0.3  # 文本推断，稍低权重
            return val, [f"派系(推断{cn_name})={val:+.1f}"]

    return 0.0, []


# ═══════════════════════════════════════════════════════════════════
# 4. 文本效果解析 (L3 + L3+)
# ═══════════════════════════════════════════════════════════════════

# V2 原有 19 个效果模式
EFFECT_PATTERNS_V2 = {
    "direct_damage":   (r"造成\s*(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 0.5),
    "random_damage":   (r"随机.*?(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 0.35),
    "draw":            (r"抽\s*(\d+)\s*张牌",                        lambda m: int(m.group(1)) * 1.2),
    "summon_stats":    (r"召唤.*?(\d+)/(\d+)",                       lambda m: (int(m.group(1)) + int(m.group(2))) * 0.3),
    "summon":          (r"召唤",                                     lambda m: 1.5),
    "destroy":         (r"消灭",                                     lambda m: 2.0),
    "aoe_damage":      (r"所有.*?(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 1.0),
    "heal":            (r"恢复\s*(\d+)\s*点",                        lambda m: int(m.group(1)) * 0.3),
    "armor":           (r"获得\s*(\d+)\s*点护甲",                    lambda m: int(m.group(1)) * 0.4),
    "buff_atk":        (r"\+\s*(\d+)\s*.*?攻击力",                   lambda m: int(m.group(1)) * 0.5),
    "generate":        (r"置入|获取|获得一张",                        lambda m: 1.5),
    "copy":            (r"复制",                                     lambda m: 1.5),
    "mana_reduce":     (r"消耗.*?减少\s*(\d+)",                      lambda m: int(m.group(1)) * 0.6),
    "dark_gift":       (r"黑暗之赐",                                 lambda m: 1.8),
    "reveal":          (r"回溯",                                     lambda m: 1.2),
    "imbue":           (r"灌注",                                     lambda m: 1.0),
    "discard":         (r"弃",                                       lambda m: -1.0),
    "condition":       (r"如果.*?(?:则|就|会)",                      lambda m: -0.3),
    "mana_thirst":     (r"延系",                                     lambda m: 0.8),
}

# V7 新增效果模式（类型条件）
RACE_NAMES = "龙|恶魔|野兽|鱼人|海盗|元素|亡灵|图腾|机械|纳迦|德莱尼"
SCHOOL_NAMES = "火焰|冰霜|奥术|自然|暗影|神圣|邪能"

EFFECT_PATTERNS_V7 = {
    "discover_race":        (r"发现.*?(?:" + RACE_NAMES + ")",       lambda m: 1.0),
    "discover_spell":       (r"发现.*?法术",                          lambda m: 0.5),
    "discover_weapon":      (r"发现.*?武器",                          lambda m: 0.3),
    "discover_minion":      (r"发现.*?随从",                          lambda m: 0.3),
    "discover_spell_school":(r"发现.*?(?:" + SCHOOL_NAMES + ")法术",  lambda m: 0.8),
    "summon_race":          (r"召唤.*?(?:" + RACE_NAMES + ")",        lambda m: 0.3),
    "buff_race":            (r"(?:" + RACE_NAMES + ").*?[+加]",       lambda m: 0.5),
    "forge_effect":         (r"锻造",                                 lambda m: 0.8),
    "excavate_effect":      (r"挖掘",                                 lambda m: 0.7),
}


def parse_text_effects(text):
    """L3 + L3+: 解析卡牌文本效果"""
    if not text:
        return 0.0, []
    total = 0.0
    details = []
    # V2 原有模式
    for ename, (pat, scorer) in EFFECT_PATTERNS_V2.items():
        m = re.search(pat, text)
        if m:
            val = scorer(m)
            total += val
            details.append(f"{ename}={val:+.1f}")
    # V7 新增模式
    for ename, (pat, scorer) in EFFECT_PATTERNS_V7.items():
        m = re.search(pat, text)
        if m:
            val = scorer(m)
            total += val
            details.append(f"L3+_{ename}={val:+.1f}")
    return total, details


# ═══════════════════════════════════════════════════════════════════
# 5. 条件期望层 (L5, 扩展)
# ═══════════════════════════════════════════════════════════════════

CONDITION_DEFS = [
    # V2 原有 29 个
    ("dark_gift",          r"黑暗之赐",                                0.6, 1.8),
    ("discover_chain",     r"发现",                                    0.8, 1.2),
    ("quest_progress",     r"任务[:：]",                               0.7, 3.0),
    ("imbue_stacking",     r"灌注",                                    0.5, 2.0),
    ("reveal_burst",       r"回溯",                                    0.6, 1.5),
    ("mana_thirst",        r"延系",                                    0.5, 1.6),
    ("trigger_on_turn",    r"每当|在你的回合|回合结束|回合开始",          0.7, 1.4),
    ("condition_if",       r"如果",                                    0.55, 1.5),
    ("synergy_use_cast",   r"使用一张|施放\d+个|打出",                  0.5, 1.3),
    ("discard_payoff",     r"弃",                                      0.3, 1.0),
    ("cost_reduction",     r"消耗.*减少|每.*减少",                      0.6, 1.4),
    ("copy_effect",        r"复制",                                    0.7, 1.3),
    ("draw_enabler",       r"抽.*牌",                                  0.8, 1.1),
    ("aoe_clear",          r"所有.*(?:伤害|消灭|随从)",                  0.5, 1.5),
    ("buff_aura",          r"获得\+\d+/\+\d+|你的.*\+\d+|获得.*攻击力",  0.6, 1.3),
    ("deathrattle_payoff", r"亡语",                                    0.7, 1.3),
    ("battlecry_strong",   r"战吼[:：]",                               0.9, 1.1),
    ("generate_value",     r"置入|获取|获得一张",                       0.7, 1.3),
    ("destroy_removal",    r"消灭",                                    0.6, 1.4),
    ("heal_sustain",       r"恢复|治疗",                               0.5, 1.1),
    ("armor_gain",         r"护甲",                                    0.5, 1.1),
    ("rush_immediate",     r"突袭",                                    0.8, 1.2),
    ("charge_lethal",      r"冲锋",                                    0.6, 1.3),
    ("taunt_stall",        r"嘲讽",                                    0.7, 1.1),
    ("freeze_control",     r"冻结",                                    0.5, 1.2),
    ("stealth_setup",      r"潜行",                                    0.5, 1.2),
    ("combo_enabler",      r"连击",                                    0.5, 1.3),
    ("secret_bluff",       r"奥秘",                                    0.5, 1.2),
    ("tradeable_cycle",    r"可交易",                                  0.8, 1.1),
    # V7 新增条件
    ("condition_race_hand",  r"手牌中有.*?(?:" + RACE_NAMES + ")",     0.4, 1.5),
    ("condition_spell_cast", r"使用一张.*?法术|施放\d+个法术",          0.6, 1.2),
    ("condition_minion_died",r"友方.*?死亡|友方.*?消灭",               0.5, 1.3),
    ("condition_overheal",   r"过量治疗",                              0.4, 1.2),
    ("condition_honorable",  r"荣誉消灭",                              0.4, 1.3),
    ("forge_chain",          r"锻造",                                  0.7, 1.4),
    ("excavate_chain",       r"挖掘",                                  0.6, 1.3),
    ("titan_ability",        r"泰坦",                                  0.8, 1.2),
]


def calc_conditional_ev(card, base_l2l3):
    """L5: 条件期望"""
    text = card.get("text", "") or ""
    mechs = " ".join(card.get("mechanics", []))
    all_text = mechs + " " + text
    cond_score = 0.0
    cond_details = []
    matched = set()

    for cname, pat, prob, mult in CONDITION_DEFS:
        if cname in matched:
            continue
        if re.search(pat, all_text):
            ev = prob * base_l2l3 * (mult - 1.0)
            cond_score += ev
            cond_details.append(f"{cname}(P={prob:.1f},M={mult:.1f})={ev:+.1f}")
            matched.add(cname)

    return cond_score, cond_details


# ═══════════════════════════════════════════════════════════════════
# 6. Vanilla 曲线 + 类型基线 (与 V2 相同)
# ═══════════════════════════════════════════════════════════════════

def power_law(mana, a, b, c):
    return a * np.power(mana, b) + c


CLASS_MULTIPLIER = {
    "NEUTRAL": 0.85, "DEMONHUNTER": 0.95, "HUNTER": 0.95,
    "WARRIOR": 0.98, "PALADIN": 1.00, "ROGUE": 1.00, "MAGE": 1.00,
    "DEATHKNIGHT": 1.02, "PRIEST": 1.02, "WARLOCK": 1.02,
    "DRUID": 1.05, "SHAMAN": 1.05,
}


def fit_per_type_baselines(cards, curve_popt):
    """对非随从卡类型拟合基线"""
    type_values = defaultdict(list)
    for card in cards:
        ctype = card.get("type", "")
        if ctype not in ("SPELL", "WEAPON", "LOCATION", "HERO"):
            continue
        mana = max(card.get("cost", 0), 0)
        l2, _ = calc_keyword_score(card, curve_popt)
        l3, _ = parse_text_effects(card.get("text", ""))
        total = l2 + l3
        if total > 0:
            type_values[ctype].append((mana, total))

    baselines = {}
    for ctype, vals in type_values.items():
        if len(vals) < 5:
            mean_v = np.mean([v for _, v in vals])
            baselines[ctype] = {"params": None, "mean": mean_v}
            continue
        mana_arr = np.array([m for m, _ in vals])
        val_arr = np.array([v for _, v in vals])
        try:
            popt, _ = curve_fit(power_law, mana_arr, val_arr,
                                p0=[3.0, 0.7, 0], maxfev=5000,
                                bounds=([0.1, 0.1, -10], [10, 2, 20]))
            baselines[ctype] = {"params": popt, "mean": float(np.mean(val_arr))}
        except Exception:
            baselines[ctype] = {"params": None, "mean": float(np.mean(val_arr))}
    return baselines


def get_type_expected(mana, baseline):
    if baseline["params"] is not None:
        return float(power_law(mana, *baseline["params"]))
    return baseline["mean"]


# ═══════════════════════════════════════════════════════════════════
# 7. L7 Rankings 校准层
# ═══════════════════════════════════════════════════════════════════

def calc_rankings_calibration(card, model_score, rankings_db, model_min, model_max):
    """L7: 用 HSReplay 真实胜率校准模型分数"""
    card_name = card.get("name", "")
    if card_name not in rankings_db:
        return model_score, "纯模型"

    data = rankings_db[card_name]
    deck_wr = data["deck_wr"]
    played_wr = data.get("played_wr") or deck_wr
    play_count = data["play_count"]

    # 标准化模型分数到 [0, 1]
    model_range = model_max - model_min
    if model_range < 0.001:
        return model_score, "纯模型(范围≈0)"
    norm_model = max(0, min(1, (model_score - model_min) / model_range))

    # 标准化胜率到 [0, 1] (典型范围 40-65%)
    norm_deck_wr = max(0, min(1, (deck_wr - 40.0) / 25.0))
    norm_played_wr = max(0, min(1, (played_wr - 40.0) / 25.0))

    # 置信度: 出场次数越多越可信
    confidence = min(1.0, math.log10(1 + play_count) / math.log10(1 + 1000000))

    # 融合
    alpha = 0.5   # 模型权重
    beta = 0.3    # 含卡组胜率
    gamma = 0.2   # 打出时胜率

    effective_alpha = alpha + (1 - alpha) * (1 - confidence)
    data_blend = (beta * norm_deck_wr + gamma * norm_played_wr) / (beta + gamma)

    blended = effective_alpha * norm_model + (1 - effective_alpha) * data_blend
    v7_score = blended * model_range + model_min

    label = (f"融合(模型{effective_alpha:.0%}+数据{1-effective_alpha:.0%}, "
             f"deck_wr={deck_wr:.1f}%, played_wr={played_wr:.1f}%, N={play_count:,})")
    return v7_score, label


# ═══════════════════════════════════════════════════════════════════
# 8. 类型评分器 (V7 版本)
# ═══════════════════════════════════════════════════════════════════

def score_minion(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    actual = card.get("attack", 0) + card.get("health", 0)
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass", "NEUTRAL"), 1.0)
    expected = power_law(mana, *curve_popt) * cls_mult
    l1 = actual - expected

    l2, d2 = calc_keyword_score(card, curve_popt)
    l2_5_race, d2_5r = calc_race_synergy(card, mana)
    l2_5_spell, d2_5s = calc_spell_school(card)
    l3, d3 = parse_text_effects(card.get("text", ""))

    base_l2l3 = l2 + l2_5_race + l2_5_spell + l3
    l5, d5 = calc_conditional_ev(card, base_l2l3)

    total = l1 + l2 + l2_5_race + l2_5_spell + l3 + l5
    details = {
        "L1": l1, "L2": l2, "L2_5_race": l2_5_race, "L2_5_spell": l2_5_spell,
        "L3": l3, "L5": l5, "total_raw": total,
        "breakdown": d2 + d2_5r + d2_5s + d3 + d5,
    }
    return total, details


def score_spell(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass", "NEUTRAL"), 1.0)
    l2, d2 = calc_keyword_score(card, curve_popt)
    l2_5_spell, d2_5s = calc_spell_school(card)
    l3, d3 = parse_text_effects(card.get("text", ""))

    bl = type_baselines.get("SPELL", {"params": None, "mean": 5.0})
    expected = get_type_expected(mana, bl) * cls_mult
    l1 = (l2 + l2_5_spell + l3) - expected

    base_l2l3 = l2 + l2_5_spell + l3
    l5, d5 = calc_conditional_ev(card, base_l2l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L2_5_spell": l2_5_spell, "L3": l3, "L5": l5,
        "total_raw": total,
        "breakdown": d2 + d2_5s + d3 + d5,
    }
    return total, details


def score_weapon(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    atk = card.get("attack", 0)
    dur = card.get("health", 0)
    weapon_stats = atk * dur
    expected_stats = power_law(mana, *curve_popt) * 0.7
    l1_raw = weapon_stats - expected_stats

    l2, d2 = calc_keyword_score(card, curve_popt)
    l3, d3 = parse_text_effects(card.get("text", ""))

    bl = type_baselines.get("WEAPON", {"params": None, "mean": 3.0})
    expected_effects = get_type_expected(mana, bl)
    l1 = l1_raw + (l2 + l3) - expected_effects

    l5, d5 = calc_conditional_ev(card, l2 + l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L3": l3, "L5": l5, "total_raw": total,
        "breakdown": d2 + d3 + d5,
    }
    return total, details


def score_location(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    charges = max(card.get("health", 0), 1)

    l2, d2 = calc_keyword_score(card, curve_popt)
    l3_per_use, _ = parse_text_effects(card.get("text", ""))
    total_effect = l3_per_use * charges

    bl = type_baselines.get("LOCATION", {"params": None, "mean": 4.0})
    expected = get_type_expected(mana, bl)
    l1 = total_effect + l2 - expected

    l5, d5 = calc_conditional_ev(card, l2 + total_effect)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L3": l3_per_use, "L3_total": total_effect,
        "charges": charges, "L5": l5, "total_raw": total,
        "breakdown": d2 + d5,
    }
    return total, details


def score_hero(card, curve_popt, type_baselines):
    l2, d2 = calc_keyword_score(card, curve_popt)
    l3, d3 = parse_text_effects(card.get("text", ""))
    armor_budget = 5.0

    bl = type_baselines.get("HERO", {"params": None, "mean": 7.0})
    expected = get_type_expected(card.get("cost", 5), bl)
    l1 = l2 + l3 + armor_budget - expected

    l5, d5 = calc_conditional_ev(card, l2 + l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L3": l3, "L5": l5, "total_raw": total,
        "breakdown": d2 + d3 + d5,
    }
    return total, details


SCORERS = {
    "MINION": score_minion, "SPELL": score_spell,
    "WEAPON": score_weapon, "LOCATION": score_location, "HERO": score_hero,
}


# ═══════════════════════════════════════════════════════════════════
# 9. 主流程
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("  V7 卡牌评分引擎 — enums 扩展 + Rankings 校准")
    print("=" * 70)

    # ── 1. 加载数据 ──
    enums_path = os.path.join(BASE_DIR, "hearthstone_enums.json")
    rankings_path = os.path.join(BASE_DIR, "HSReplay_Card_Rankings.xlsx")
    cards_path = os.path.join(BASE_DIR, "hs_cards", "unified_standard.json")
    curve_path = os.path.join(BASE_DIR, "hs_cards", "v2_curve_params.json")

    enums = load_enums(enums_path)
    print(f"\n📋 Enums 加载: {len(enums['keywords'])} 关键字, "
          f"{len(enums['races'])} 种族, {len(enums['schools'])} 法术派系")

    rankings_db = load_rankings(rankings_path)
    print(f"📊 Rankings 加载: {len(rankings_db)} 张卡有真实数据")

    # 检查关键字覆盖度
    enum_kws = set(enums["keywords"].keys())
    covered_kws = set()
    for kw in enum_kws:
        tier = get_keyword_tier(kw)
        covered_kws.add(kw)
    print(f"🔑 关键字覆盖: {len(covered_kws)}/{len(enum_kws)} "
          f"({100*len(covered_kws)/len(enum_kws):.0f}%)")

    cards = load_json(cards_path)
    curve_data = load_json(curve_path)
    curve_popt = (curve_data["parameters"]["a"],
                  curve_data["parameters"]["b"],
                  curve_data["parameters"]["c"])
    print(f"🃏 卡牌数据: {len(cards)} 张")
    print(f"📈 曲线参数: a={curve_popt[0]:.4f}, b={curve_popt[1]:.4f}, c={curve_popt[2]:.4f}")

    # ── 2. 拟合类型基线 ──
    type_baselines = fit_per_type_baselines(cards, curve_popt)
    print(f"📏 类型基线: {list(type_baselines.keys())}")

    # ── 3. 评分所有卡牌 ──
    print(f"\n{'─'*70}")
    print("  评分中...")
    scored = []
    skipped = 0
    for card in cards:
        ctype = card.get("type", "")
        scorer = SCORERS.get(ctype)
        if not scorer:
            skipped += 1
            continue
        try:
            raw_score, details = scorer(card, curve_popt, type_baselines)
            scored.append({
                "card": card,
                "raw_score": raw_score,
                "details": details,
            })
        except Exception as e:
            skipped += 1

    print(f"  ✅ 评分完成: {len(scored)} 张, 跳过: {skipped} 张")

    # ── 4. L7 Rankings 校准 ──
    raw_scores = [s["raw_score"] for s in scored]
    model_min, model_max = min(raw_scores), max(raw_scores)
    print(f"  模型分数范围: [{model_min:.2f}, {model_max:.2f}]")

    calibrated = 0
    for s in scored:
        v7_score, l7_label = calc_rankings_calibration(
            s["card"], s["raw_score"], rankings_db, model_min, model_max
        )
        s["v7_score"] = v7_score
        s["l7_label"] = l7_label
        if "融合" in l7_label:
            calibrated += 1
    print(f"  🎯 L7 校准: {calibrated}/{len(scored)} 张卡使用 Rankings 数据")

    # ── 5. 排序输出 ──
    scored.sort(key=lambda x: x["v7_score"], reverse=True)

    # Top 30
    print(f"\n{'═'*70}")
    print("  TOP 30 卡牌 (V7 评分)")
    print(f"{'═'*70}")
    print(f"{'#':>3}  {'分数':>7}  {'费用':>2}  {'类型':<6}  {'职业':<5}  {'名称':<20}  {'L7标记'}")
    print(f"{'─'*70}")
    for i, s in enumerate(scored[:30], 1):
        c = s["card"]
        l7_short = "📊" if "融合" in s["l7_label"] else "🧮"
        print(f"{i:>3}  {s['v7_score']:>+7.2f}  {c.get('cost', 0):>2}  "
              f"{c.get('type', '?'):<6}  {c.get('cardClass', '?')[:4]:<5}  "
              f"{c.get('name', '?')[:18]:<20}  {l7_short}")

    # Bottom 10
    print(f"\n{'═'*70}")
    print("  BOTTOM 10 卡牌")
    print(f"{'═'*70}")
    for i, s in enumerate(scored[-10:], len(scored) - 9):
        c = s["card"]
        print(f"{i:>3}  {s['v7_score']:>+7.2f}  {c.get('cost', 0):>2}  "
              f"{c.get('type', '?'):<6}  {c.get('name', '?')[:18]}")

    # ── 6. 统计 ──
    print(f"\n{'═'*70}")
    print("  统计摘要")
    print(f"{'═'*70}")

    # 分数分布
    buckets = {"<-5": 0, "-5~0": 0, "0~5": 0, "5~10": 0, "10~20": 0, ">20": 0}
    for s in scored:
        sc = s["v7_score"]
        if sc < -5:
            buckets["<-5"] += 1
        elif sc < 0:
            buckets["-5~0"] += 1
        elif sc < 5:
            buckets["0~5"] += 1
        elif sc < 10:
            buckets["5~10"] += 1
        elif sc < 20:
            buckets["10~20"] += 1
        else:
            buckets[">20"] += 1
    print("\n  分数分布:")
    for k, v in buckets.items():
        bar = "█" * (v // 3)
        print(f"    {k:>6}: {v:>4}  {bar}")

    # 类型统计
    type_stats = defaultdict(list)
    for s in scored:
        type_stats[s["card"].get("type", "?")].append(s["v7_score"])
    print("\n  类型统计:")
    for t in ["MINION", "SPELL", "WEAPON", "LOCATION", "HERO"]:
        vals = type_stats.get(t, [])
        if vals:
            print(f"    {t:<10}: mean={np.mean(vals):>+.2f}, "
                  f"min={min(vals):>+.2f}, max={max(vals):>+.2f}, n={len(vals)}")

    # 种族统计
    race_stats = defaultdict(list)
    for s in scored:
        c = s["card"]
        if c.get("type") != "MINION":
            continue
        race = c.get("race", "")
        if race:
            # 取主种族
            parts = race.replace("，", " ").split()
            for p in parts:
                if p in RACE_BONUS:
                    race_stats[p].append(s["v7_score"])
                    break
    if race_stats:
        print("\n  种族统计 (平均V7分数):")
        for race, vals in sorted(race_stats.items(), key=lambda x: -np.mean(x[1])):
            print(f"    {race:<6}: {np.mean(vals):>+.2f} (n={len(vals)})")

    # L7 校准影响分析
    print("\n  L7 校准影响:")
    rank_changes = []
    for i, s in enumerate(scored):
        # 找 V2 排名
        raw_rank = sorted(range(len(scored)),
                          key=lambda x: scored[x]["raw_score"], reverse=True).index(i) + 1
        v7_rank = i + 1
        change = raw_rank - v7_rank
        rank_changes.append((change, s["card"].get("name", "?"), raw_rank, v7_rank))

    rank_changes.sort()
    print("    上升最多 TOP 5:")
    for change, name, raw_r, v7_r in rank_changes[-5:]:
        if change != 0:
            print(f"      {name[:18]:<18}: #{raw_r:>4} → #{v7_r:>4} ({change:+d})")
    print("    下降最多 TOP 5:")
    for change, name, raw_r, v7_r in rank_changes[:5]:
        if change != 0:
            print(f"      {name[:18]:<18}: #{raw_r:>4} → #{v7_r:>4} ({change:+d})")

    # ── 7. 保存报告 ──
    report = []
    for s in scored:
        c = s["card"]
        entry = {
            "name": c.get("name"),
            "ename": c.get("ename", ""),
            "dbfId": c.get("dbfId"),
            "cost": c.get("cost"),
            "type": c.get("type"),
            "cardClass": c.get("cardClass"),
            "rarity": c.get("rarity"),
            "race": c.get("race", ""),
            "set": c.get("set", ""),
            "v2_raw_score": round(s["raw_score"], 3),
            "v7_score": round(s["v7_score"], 3),
            "l7_label": s["l7_label"],
            "details": s["details"],
        }
        report.append(entry)

    report_path = os.path.join(BASE_DIR, "hs_cards", "v7_scoring_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已保存: {report_path}")
    print(f"   共 {len(report)} 张卡")
    print("=" * 70)


if __name__ == "__main__":
    main()

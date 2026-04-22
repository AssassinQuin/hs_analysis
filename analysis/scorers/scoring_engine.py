#!/usr/bin/env python3
"""卡牌评分引擎 — 多层评分 + HSReplay Rankings 校准

评分层级:
  L1  : 白板曲线基线 (stats vs expected)
  L2  : 关键词层级评分 (50+ 关键字)
  L2.5: 随从种族 + 法术派系协同评分
  L3  : 文本效果解析
  L5  : 条件期望层
  L7  : HSReplay Rankings 真实胜率校准

用法: python -m hs_analysis.scorers.scoring_engine
"""

import json
import math
import re
from collections import defaultdict

import numpy as np
from scipy.optimize import curve_fit

from analysis.scorers.constants import (
    KEYWORD_TIERS, TIER_BASES, KEYWORD_CN,
    EFFECT_PATTERNS,
    CONDITION_DEFS, CLASS_MULTIPLIER,
    RACE_BONUS, SPELL_SCHOOL_BONUS, RUNE_TYPES,
    RACE_NAMES, SCHOOL_NAMES,
)

from analysis.scorers.vanilla_curve import power_law

from analysis.config import (
    DATA_DIR, ENUMS_PATH, RANKINGS_PATH, CURVE_PARAMS_PATH,
    SCORING_REPORT_PATH, UNIFIED_DB_PATH,
)


# ═══════════════════════════════════════════════════════════════════
# 1. 数据加载
# ═══════════════════════════════════════════════════════════════════

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_enums(path):
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
    try:
        import openpyxl
    except ImportError:
        print("⚠️  openpyxl 未安装，跳过 L7 Rankings 校准层")
        return {}

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["总排行"]
    rows = list(ws.iter_rows(values_only=True))

    db = {}
    for r in rows[4:]:
        if r[0] is None or not isinstance(r[0], (int, float)):
            continue
        name_col = r[1]
        if not name_col:
            continue
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
# 2. 关键字层级 (L2)
# ═══════════════════════════════════════════════════════════════════

def get_keyword_tier(kw):
    if kw in KEYWORD_TIERS["power"]:
        return "power"
    if kw in KEYWORD_TIERS["mechanical"]:
        return "mechanical"
    return "niche"


def calc_keyword_score(card, curve_popt):
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


def calc_structured_bonuses(card):
    bonuses = 0.0
    details = []

    overload_val = card.get("overload", 0)
    if overload_val:
        bonuses -= overload_val * 0.3
        details.append(f"过载({overload_val})={-overload_val * 0.3:+.1f}")

    sd_val = card.get("spellDamage", 0)
    if sd_val:
        bonuses += sd_val * 0.4
        details.append(f"法强({sd_val})={sd_val * 0.4:+.1f}")

    armor_val = card.get("armor", 0)
    if armor_val:
        bonuses += armor_val * 0.3
        details.append(f"护甲({armor_val})={armor_val * 0.3:+.1f}")

    return bonuses, details


# ═══════════════════════════════════════════════════════════════════
# 3. 类型协同层 (L2.5)
# ═══════════════════════════════════════════════════════════════════

def calc_race_synergy(card, mana):
    if card.get("type") != "MINION":
        return 0.0, []
    race = card.get("race", "")
    if not race:
        return 0.0, []

    parts = race.replace("，", " ").split()
    primary_race = None
    for p in parts:
        if p in RACE_BONUS:
            primary_race = p
            break
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
    if card.get("type") != "SPELL":
        return 0.0, []

    race = card.get("race", "")
    if race:
        parts = race.replace("，", " ").split()
        for p in parts:
            if p in SPELL_SCHOOL_BONUS:
                bonus = SPELL_SCHOOL_BONUS[p]
                val = bonus * 0.5
                return val, [f"派系({p})={val:+.1f}"]

    text = card.get("text", "") or ""
    for cn_name, bonus in SPELL_SCHOOL_BONUS.items():
        if cn_name in text:
            val = bonus * 0.3
            return val, [f"派系(推断{cn_name})={val:+.1f}"]

    return 0.0, []


# ═══════════════════════════════════════════════════════════════════
# 4. 文本效果解析 (L3)
# ═══════════════════════════════════════════════════════════════════

_RE_HTML = re.compile(r"</?[^>]+>")
_RE_VAR = re.compile(r"[$#](\d+)")
_RE_BRACKET = re.compile(r"\[x\]", re.IGNORECASE)
_RE_FULLWIDTH_PAREN = re.compile(r"（(\d+)）")
_RE_MULTI_SPACE = re.compile(r"\s+")


def _clean_card_text(text):
    cleaned = _RE_HTML.sub("", text)
    cleaned = _RE_VAR.sub(r"\1", cleaned)
    cleaned = _RE_BRACKET.sub("", cleaned)
    cleaned = _RE_MULTI_SPACE.sub(" ", cleaned).strip()
    return cleaned


def parse_text_effects(text):
    if not text:
        return 0.0, []
    cleaned = _clean_card_text(text)
    total = 0.0
    details = []
    for ename, (pat, scorer) in EFFECT_PATTERNS.items():
        m = re.search(pat, cleaned)
        if m:
            val = scorer(m)
            total += val
            details.append(f"{ename}={val:+.1f}")
    return total, details


# ═══════════════════════════════════════════════════════════════════
# 5. 条件期望层 (L5)
# ═══════════════════════════════════════════════════════════════════

def calc_conditional_ev(card, base_l2l3):
    text = card.get("text", "") or ""
    mechs = set(card.get("mechanics", []))
    cond_score = 0.0
    cond_details = []
    matched = set()

    for entry in CONDITION_DEFS:
        cname, mech_tag, pat, prob, mult = entry
        if cname in matched:
            continue
        triggered = False
        if mech_tag is not None:
            triggered = mech_tag in mechs
        elif pat is not None:
            triggered = bool(re.search(pat, text))
        if triggered:
            ev = prob * base_l2l3 * (mult - 1.0)
            cond_score += ev
            cond_details.append(f"{cname}(P={prob:.1f},M={mult:.1f})={ev:+.1f}")
            matched.add(cname)

    return cond_score, cond_details


# ═══════════════════════════════════════════════════════════════════
# 6. Vanilla 曲线 + 类型基线
# ═══════════════════════════════════════════════════════════════════

def fit_per_type_baselines(cards, curve_popt):
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
# 7. Rankings 校准层 (L7)
# ═══════════════════════════════════════════════════════════════════

def calc_rankings_calibration(card, model_score, rankings_db, model_min, model_max):
    card_name = card.get("name", "")
    if card_name not in rankings_db:
        return model_score, "纯模型"

    data = rankings_db[card_name]
    deck_wr = data["deck_wr"]
    played_wr = data.get("played_wr") or deck_wr
    play_count = data["play_count"]

    model_range = model_max - model_min
    if model_range < 0.001:
        return model_score, "纯模型(范围≈0)"
    norm_model = max(0, min(1, (model_score - model_min) / model_range))

    norm_deck_wr = max(0, min(1, (deck_wr - 40.0) / 25.0))
    norm_played_wr = max(0, min(1, (played_wr - 40.0) / 25.0))

    confidence = min(1.0, math.log10(1 + play_count) / math.log10(1 + 1000000))

    alpha = 0.5
    beta = 0.3
    gamma = 0.2

    effective_alpha = alpha + (1 - alpha) * (1 - confidence)
    data_blend = (beta * norm_deck_wr + gamma * norm_played_wr) / (beta + gamma)

    blended = effective_alpha * norm_model + (1 - effective_alpha) * data_blend
    calibrated_score = blended * model_range + model_min

    label = (f"融合(模型{effective_alpha:.0%}+数据{1-effective_alpha:.0%}, "
             f"deck_wr={deck_wr:.1f}%, played_wr={played_wr:.1f}%, N={play_count:,})")
    return calibrated_score, label


# ═══════════════════════════════════════════════════════════════════
# 8. 类型评分器
# ═══════════════════════════════════════════════════════════════════

def score_minion(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    actual = card.get("attack", 0) + card.get("health", 0)
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass", "NEUTRAL"), 1.0)
    expected = power_law(mana, *curve_popt) * cls_mult
    l1 = actual - expected

    l2, d2 = calc_keyword_score(card, curve_popt)
    l_struct, d_struct = calc_structured_bonuses(card)
    l2_5_race, d2_5r = calc_race_synergy(card, mana)
    l2_5_spell, d2_5s = calc_spell_school(card)
    l3, d3 = parse_text_effects(card.get("text", ""))

    base_l2l3 = l2 + l_struct + l2_5_race + l2_5_spell + l3
    l5, d5 = calc_conditional_ev(card, base_l2l3)

    total = l1 + l2 + l_struct + l2_5_race + l2_5_spell + l3 + l5
    details = {
        "L1": l1, "L2": l2, "L_struct": l_struct, "L2_5_race": l2_5_race,
        "L2_5_spell": l2_5_spell, "L3": l3, "L5": l5, "total_raw": total,
        "breakdown": d2 + d_struct + d2_5r + d2_5s + d3 + d5,
    }
    return total, details


def score_spell(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass", "NEUTRAL"), 1.0)
    l2, d2 = calc_keyword_score(card, curve_popt)
    l_struct, d_struct = calc_structured_bonuses(card)
    l2_5_spell, d2_5s = calc_spell_school(card)
    l3, d3 = parse_text_effects(card.get("text", ""))

    bl = type_baselines.get("SPELL", {"params": None, "mean": 5.0})
    expected = get_type_expected(mana, bl) * cls_mult
    l1 = (l2 + l_struct + l2_5_spell + l3) - expected

    base_l2l3 = l2 + l_struct + l2_5_spell + l3
    l5, d5 = calc_conditional_ev(card, base_l2l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L_struct": l_struct, "L2_5_spell": l2_5_spell,
        "L3": l3, "L5": l5, "total_raw": total,
        "breakdown": d2 + d_struct + d2_5s + d3 + d5,
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
    l_struct, d_struct = calc_structured_bonuses(card)
    l3, d3 = parse_text_effects(card.get("text", ""))

    bl = type_baselines.get("WEAPON", {"params": None, "mean": 3.0})
    expected_effects = get_type_expected(mana, bl)
    l1 = l1_raw + (l2 + l_struct + l3) - expected_effects

    l5, d5 = calc_conditional_ev(card, l2 + l_struct + l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L_struct": l_struct, "L3": l3, "L5": l5,
        "total_raw": total,
        "breakdown": d2 + d_struct + d3 + d5,
    }
    return total, details


def score_location(card, curve_popt, type_baselines):
    mana = max(card.get("cost", 0), 0)
    charges = max(card.get("health", 0), 1)

    l2, d2 = calc_keyword_score(card, curve_popt)
    l_struct, d_struct = calc_structured_bonuses(card)
    l3_per_use, _ = parse_text_effects(card.get("text", ""))
    total_effect = l3_per_use * charges

    bl = type_baselines.get("LOCATION", {"params": None, "mean": 4.0})
    expected = get_type_expected(mana, bl)
    l1 = total_effect + l2 + l_struct - expected

    l5, d5 = calc_conditional_ev(card, l2 + l_struct + total_effect)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L_struct": l_struct, "L3": l3_per_use,
        "L3_total": total_effect, "charges": charges, "L5": l5,
        "total_raw": total,
        "breakdown": d2 + d_struct + d5,
    }
    return total, details


def score_hero(card, curve_popt, type_baselines):
    l2, d2 = calc_keyword_score(card, curve_popt)
    l_struct, d_struct = calc_structured_bonuses(card)
    l3, d3 = parse_text_effects(card.get("text", ""))
    armor_budget = 5.0

    bl = type_baselines.get("HERO", {"params": None, "mean": 7.0})
    expected = get_type_expected(card.get("cost", 5), bl)
    l1 = l2 + l_struct + l3 + armor_budget - expected

    l5, d5 = calc_conditional_ev(card, l2 + l_struct + l3)

    total = l1 + l5
    details = {
        "L1": l1, "L2": l2, "L_struct": l_struct, "L3": l3, "L5": l5,
        "total_raw": total,
        "breakdown": d2 + d_struct + d3 + d5,
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
    print("  卡牌评分引擎 — 多层评分 + Rankings 校准")
    print("=" * 70)

    enums_path = str(ENUMS_PATH)
    rankings_path = str(RANKINGS_PATH)
    cards_path = str(UNIFIED_DB_PATH)
    curve_path = str(CURVE_PARAMS_PATH)

    enums = load_enums(enums_path)
    print(f"\n📋 Enums 加载: {len(enums['keywords'])} 关键字, "
          f"{len(enums['races'])} 种族, {len(enums['schools'])} 法术派系")

    rankings_db = load_rankings(rankings_path)
    print(f"📊 Rankings 加载: {len(rankings_db)} 张卡有真实数据")

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

    type_baselines = fit_per_type_baselines(cards, curve_popt)
    print(f"📏 类型基线: {list(type_baselines.keys())}")

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
        except Exception:
            skipped += 1

    print(f"  ✅ 评分完成: {len(scored)} 张, 跳过: {skipped} 张")

    raw_scores = [s["raw_score"] for s in scored]
    model_min, model_max = min(raw_scores), max(raw_scores)
    print(f"  模型分数范围: [{model_min:.2f}, {model_max:.2f}]")

    calibrated = 0
    for s in scored:
        final_score, l7_label = calc_rankings_calibration(
            s["card"], s["raw_score"], rankings_db, model_min, model_max
        )
        s["score"] = final_score
        s["l7_label"] = l7_label
        if "融合" in l7_label:
            calibrated += 1
    print(f"  🎯 L7 校准: {calibrated}/{len(scored)} 张卡使用 Rankings 数据")

    scored.sort(key=lambda x: x["score"], reverse=True)

    print(f"\n{'═'*70}")
    print("  TOP 30 卡牌")
    print(f"{'═'*70}")
    print(f"{'#':>3}  {'分数':>7}  {'费用':>2}  {'类型':<6}  {'职业':<5}  {'名称':<20}  {'L7标记'}")
    print(f"{'─'*70}")
    for i, s in enumerate(scored[:30], 1):
        c = s["card"]
        l7_short = "📊" if "融合" in s["l7_label"] else "🧮"
        print(f"{i:>3}  {s['score']:>+7.2f}  {c.get('cost', 0):>2}  "
              f"{c.get('type', '?'):<6}  {c.get('cardClass', '?')[:4]:<5}  "
              f"{c.get('name', '?')[:18]:<20}  {l7_short}")

    print(f"\n{'═'*70}")
    print("  BOTTOM 10 卡牌")
    print(f"{'═'*70}")
    for i, s in enumerate(scored[-10:], len(scored) - 9):
        c = s["card"]
        print(f"{i:>3}  {s['score']:>+7.2f}  {c.get('cost', 0):>2}  "
              f"{c.get('type', '?'):<6}  {c.get('name', '?')[:18]}")

    print(f"\n{'═'*70}")
    print("  统计摘要")
    print(f"{'═'*70}")

    buckets = {"<-5": 0, "-5~0": 0, "0~5": 0, "5~10": 0, "10~20": 0, ">20": 0}
    for s in scored:
        sc = s["score"]
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

    type_stats = defaultdict(list)
    for s in scored:
        type_stats[s["card"].get("type", "?")].append(s["score"])
    print("\n  类型统计:")
    for t in ["MINION", "SPELL", "WEAPON", "LOCATION", "HERO"]:
        vals = type_stats.get(t, [])
        if vals:
            print(f"    {t:<10}: mean={np.mean(vals):>+.2f}, "
                  f"min={min(vals):>+.2f}, max={max(vals):>+.2f}, n={len(vals)}")

    race_stats = defaultdict(list)
    for s in scored:
        c = s["card"]
        if c.get("type") != "MINION":
            continue
        race = c.get("race", "")
        if race:
            parts = race.replace("，", " ").split()
            for p in parts:
                if p in RACE_BONUS:
                    race_stats[p].append(s["score"])
                    break
    if race_stats:
        print("\n  种族统计 (平均分数):")
        for race, vals in sorted(race_stats.items(), key=lambda x: -np.mean(x[1])):
            print(f"    {race:<6}: {np.mean(vals):>+.2f} (n={len(vals)})")

    print("\n  L7 校准影响:")
    rank_changes = []
    for i, s in enumerate(scored):
        raw_rank = sorted(range(len(scored)),
                          key=lambda x: scored[x]["raw_score"], reverse=True).index(i) + 1
        final_rank = i + 1
        change = raw_rank - final_rank
        rank_changes.append((change, s["card"].get("name", "?"), raw_rank, final_rank))

    rank_changes.sort()
    print("    上升最多 TOP 5:")
    for change, name, raw_r, final_r in rank_changes[-5:]:
        if change != 0:
            print(f"      {name[:18]:<18}: #{raw_r:>4} → #{final_r:>4} ({change:+d})")
    print("    下降最多 TOP 5:")
    for change, name, raw_r, final_r in rank_changes[:5]:
        if change != 0:
            print(f"      {name[:18]:<18}: #{raw_r:>4} → #{final_r:>4} ({change:+d})")

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
            "raw_score": round(s["raw_score"], 3),
            "score": round(s["score"], 3),
            "l7_label": s["l7_label"],
            "details": s["details"],
        }
        report.append(entry)

    report_path = str(SCORING_REPORT_PATH)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n💾 报告已保存: {report_path}")
    print(f"   共 {len(report)} 张卡")
    print("=" * 70)


if __name__ == "__main__":
    main()

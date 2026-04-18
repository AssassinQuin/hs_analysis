# -*- coding: utf-8 -*-
"""
V2 Scoring Engine — Full Rarity Extension
Uses unified_standard.json (1015 cards) instead of legends-only.

Pipeline:
  1. Fit vanilla curve on ALL minions (630)
  2. Keyword scoring by rarity tier
  3. Text effect parser (19 effect types)
  4. Type adapter (Spell/Weapon/Location/Hero)
  5. Composite score + report
"""
import json
import re
import sys
import io
from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import curve_fit

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATA_PATH = "D:/code/game/hs_cards/unified_standard.json"
OUTPUT_CURVE = "D:/code/game/hs_cards/v2_curve_params.json"
OUTPUT_KEYWORDS = "D:/code/game/hs_cards/v2_keyword_params.json"
OUTPUT_REPORT = "D:/code/game/hs_cards/v2_scoring_report.json"


# ──────────────────────────────────────────────
# L1: Vanilla Curve
# ──────────────────────────────────────────────
def power_law(mana, a, b, c):
    return a * np.power(mana, b) + c


def linear_model(mana):
    return 2 * mana + 1


def fit_vanilla_curve(cards):
    minions = [c for c in cards if c.get("type") == "MINION" and 0 < c.get("cost", 99) < 99]
    has_no_text = lambda c: not c.get("text", "").strip() or len(c.get("mechanics", [])) == 0
    by_mana = defaultdict(list)
    for c in minions:
        stat_sum = c.get("attack", 0) + c.get("health", 0)
        by_mana[c["cost"]].append(stat_sum)

    mana_arr = np.array(sorted(by_mana.keys()), dtype=float)
    avg_arr = np.array([np.mean(by_mana[int(m)]) for m in mana_arr])
    count_arr = np.array([len(by_mana[int(m)]) for m in mana_arr])
    weight_arr = np.sqrt(count_arr)

    popt, pcov = curve_fit(
        power_law, mana_arr, avg_arr, p0=[3.0, 0.7, 0],
        sigma=1.0 / weight_arr, absolute_sigma=True,
        bounds=([0.1, 0.3, -5], [10, 1.5, 10]), maxfev=10000
    )
    perr = np.sqrt(np.diag(pcov))
    a, b, c = popt

    pred_v2 = power_law(mana_arr, *popt)
    pred_v1 = linear_model(mana_arr)
    res_v2 = avg_arr - pred_v2
    res_v1 = avg_arr - pred_v1

    print(f"\n{'=' * 70}")
    print(f"L1 VANILLA CURVE FIT ({len(minions)} minions, {len(mana_arr)} mana buckets)")
    print(f"{'=' * 70}")
    print(f"  Formula: {a:.3f} * mana^{b:.3f} + ({c:.3f})")
    print(f"  Mana range: {int(mana_arr[0])}-{int(mana_arr[-1])}")
    print(f"  MAE: {np.mean(np.abs(res_v2)):.2f} (V1 was {np.mean(np.abs(res_v1)):.2f})")
    print(f"  RMSE: {np.sqrt(np.mean(res_v2**2)):.2f} (V1 was {np.sqrt(np.mean(res_v1**2)):.2f})")

    print(f"\n  {'Mana':>4} | {'N':>4} | {'Actual':>7} | {'V1':>5} | {'V2':>5} | {'V2Res':>6}")
    for i, m in enumerate(mana_arr):
        print(f"  {int(m):4d} | {count_arr[i]:4d} | {avg_arr[i]:7.1f} | {pred_v1[i]:5.1f} | {pred_v2[i]:5.1f} | {res_v2[i]:+6.1f}")

    params = {
        "model": "power_law", "formula": "a * mana^b + c",
        "parameters": {"a": round(float(a), 6), "b": round(float(b), 6), "c": round(float(c), 6)},
        "fit_quality": {"mae": round(float(np.mean(np.abs(res_v2))), 4), "rmse": round(float(np.sqrt(np.mean(res_v2**2))), 4)},
        "data_source": {"minion_count": len(minions), "mana_buckets": len(mana_arr)},
    }
    with open(OUTPUT_CURVE, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)

    return popt


# ──────────────────────────────────────────────
# L2: Keyword Scoring
# ──────────────────────────────────────────────
KEYWORD_TIERS = {
    "power": {
        "BATTLECRY", "DEATHRATTLE", "DISCOVER", "DIVINE_SHIELD", "RUSH",
        "CHARGE", "WINDFURY", "TAUNT", "LIFESTEAL", "STEALTH",
        "CHOOSE_ONE", "QUEST",
    },
    "mechanical": {
        "TRIGGER_VISUAL", "AURA", "COLOSSUS", "REBORN", "IMBUE",
        "OUTCAST", "IMMUNE", "SECRET", "OVERLOAD", "COMBO",
        "SPELLPOWER", "FREEZE", "POISONOUS", "SILENCE",
        "TRADEABLE", "SIDE_QUEST", "START_OF_GAME",
    },
}

KEYWORD_CN = {
    "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "DISCOVER": "发现",
    "DIVINE_SHIELD": "圣盾", "RUSH": "突袭", "CHARGE": "冲锋",
    "WINDFURY": "风怒", "TAUNT": "嘲讽", "LIFESTEAL": "吸血",
    "STEALTH": "潜行", "CHOOSE_ONE": "抉择", "QUEST": "任务",
    "TRIGGER_VISUAL": "触发", "AURA": "光环", "COLOSSAL": "巨型",
    "REBORN": "复生", "IMBUE": "灌注", "OUTCAST": "流放",
    "IMMUNE": "免疫", "SECRET": "奥秘", "OVERLOAD": "过载",
    "COMBO": "连击", "SPELLPOWER": "法强", "FREEZE": "冻结",
    "POISONOUS": "剧毒", "SILENCE": "沉默", "TRADEABLE": "可交易",
    "SIDE_QUEST": "支线任务", "START_OF_GAME": "开局触发",
}

TIER_BASES = {"power": 1.5, "mechanical": 0.75, "niche": 0.5}


def calc_keyword_score(card, curve_popt):
    mechs = set(card.get("mechanics", []))
    if not mechs:
        return 0.0, []
    mana = max(card.get("cost", 0), 0)
    total = 0.0
    applied = []
    for kw in mechs:
        tier = "niche"
        for t, kws in KEYWORD_TIERS.items():
            if kw in kws:
                tier = t
                break
        base = TIER_BASES[tier]
        val = base * (1 + 0.1 * mana)
        total += val
        cn = KEYWORD_CN.get(kw, kw)
        applied.append(f"{cn}({tier[0].upper()}={val:.1f})")
    return total, applied


# ──────────────────────────────────────────────
# L3: Text Effect Parser
# ──────────────────────────────────────────────
EFFECT_PATTERNS = {
    "direct_damage": (r"造成\s*(\d+)\s*点伤害", lambda m: int(m.group(1)) * 0.5),
    "random_damage": (r"随机.*?(\d+)\s*点伤害", lambda m: int(m.group(1)) * 0.35),
    "draw": (r"抽\s*(\d+)\s*张牌", lambda m: int(m.group(1)) * 1.2),
    "summon_stats": (r"召唤.*?(\d+)/(\d+)", lambda m: (int(m.group(1)) + int(m.group(2))) * 0.3),
    "summon": (r"召唤", lambda m: 1.5),
    "destroy": (r"消灭", lambda m: 2.0),
    "aoe_damage": (r"所有.*?(\d+)\s*点伤害", lambda m: int(m.group(1)) * 1.0),
    "heal": (r"恢复\s*(\d+)\s*点", lambda m: int(m.group(1)) * 0.3),
    "armor": (r"获得\s*(\d+)\s*点护甲", lambda m: int(m.group(1)) * 0.4),
    "buff_atk": (r"\+\s*(\d+)\s*.*?攻击力", lambda m: int(m.group(1)) * 0.5),
    "generate": (r"置入|获取|获得一张", lambda m: 1.5),
    "copy": (r"复制", lambda m: 1.5),
    "mana_reduce": (r"消耗.*?减少\s*(\d+)", lambda m: int(m.group(1)) * 0.6),
    "dark_gift": (r"黑暗之赐", lambda m: 1.8),
    "reveal": (r"回溯", lambda m: 1.2),
    "imbue": (r"灌注", lambda m: 1.0),
    "discard": (r"弃", lambda m: -1.0),
    "condition": (r"如果.*?(?:则|就|会)", lambda m: -0.3),
    "mana_thirst": (r"延系", lambda m: 0.8),
}

CLASS_MULTIPLIER = {
    "NEUTRAL": 0.85, "DEMONHUNTER": 0.95, "HUNTER": 0.95,
    "WARRIOR": 0.98, "PALADIN": 1.00, "ROGUE": 1.00, "MAGE": 1.00,
    "DEATHKNIGHT": 1.02, "PRIEST": 1.02, "WARLOCK": 1.02,
    "DRUID": 1.05, "SHAMAN": 1.05,
}


def parse_text_effects(text):
    total = 0.0
    effects = []
    for ename, (pat, scorer) in EFFECT_PATTERNS.items():
        m = re.search(pat, text)
        if m:
            val = scorer(m)
            total += val
            effects.append(f"{ename}={val:+.1f}")
    return total, effects


# ──────────────────────────────────────────────
# L4: Type Adapter
# ──────────────────────────────────────────────
def score_minion(card, curve_popt):
    mana = max(card.get("cost", 0), 0)
    actual = card.get("attack", 0) + card.get("health", 0)
    expected = power_law(mana, *curve_popt) * CLASS_MULTIPLIER.get(card.get("cardClass"), 1.0)
    l1 = actual - expected
    l2, kw_applied = calc_keyword_score(card, curve_popt)
    text = card.get("text", "")
    l3, eff_applied = parse_text_effects(text)
    return l1 + l2 + l3, l1, l2, l3, kw_applied, eff_applied


def score_spell(card, curve_popt):
    mana = max(card.get("cost", 0), 0)
    text = card.get("text", "")
    l3, eff_applied = parse_text_effects(text)
    l2, kw_applied = calc_keyword_score(card, curve_popt)
    expected_budget = power_law(mana, *curve_popt) * 0.5 * CLASS_MULTIPLIER.get(card.get("cardClass"), 1.0)
    return l2 + l3 - expected_budget, 0, l2, l3, kw_applied, eff_applied


def score_weapon(card, curve_popt):
    mana = max(card.get("cost", 0), 0)
    atk = card.get("attack", 0)
    dur = card.get("health", 1)
    weapon_stats = atk * dur
    expected = power_law(mana, *curve_popt) * 0.7
    l1 = weapon_stats - expected
    l2, kw_applied = calc_keyword_score(card, curve_popt)
    text = card.get("text", "")
    l3, eff_applied = parse_text_effects(text)
    return l1 + l2 + l3, l1, l2, l3, kw_applied, eff_applied


def score_location(card, curve_popt):
    mana = max(card.get("cost", 0), 0)
    text = card.get("text", "")
    l3, eff_applied = parse_text_effects(text)
    l2, kw_applied = calc_keyword_score(card, curve_popt)
    expected = power_law(mana, *curve_popt) * 0.4
    charges = card.get("health", 3)
    return l2 + l3 * charges * 0.5 - expected, 0, l2, l3, kw_applied, eff_applied


def score_hero(card, curve_popt):
    text = card.get("text", "")
    l3, eff_applied = parse_text_effects(text)
    l2, kw_applied = calc_keyword_score(card, curve_popt)
    armor = 5.0
    return l2 + l3 + armor, 0, l2, l3, kw_applied, eff_applied


SCORERS = {
    "MINION": score_minion, "SPELL": score_spell,
    "WEAPON": score_weapon, "LOCATION": score_location, "HERO": score_hero,
}


# ──────────────────────────────────────────────
# Main Pipeline
# ──────────────────────────────────────────────
def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        cards = json.load(f)

    print(f"Loaded {len(cards)} cards from unified DB")

    # L1: Fit curve
    curve_popt = fit_vanilla_curve(cards)

    # Score all cards
    scored = []
    type_counts = Counter()
    for card in cards:
        ctype = card.get("type", "")
        scorer = SCORERS.get(ctype)
        if not scorer:
            continue
        try:
            total, l1, l2, l3, kw, eff = scorer(card, curve_popt)
        except Exception:
            continue
        scored.append({
            "name": card["name"],
            "cost": card.get("cost", 0),
            "type": ctype,
            "class": card.get("cardClass", ""),
            "rarity": card.get("rarity", ""),
            "attack": card.get("attack", 0),
            "health": card.get("health", 0),
            "score": round(total, 2),
            "L1": round(float(l1), 2),
            "L2": round(float(l2), 2),
            "L3": round(float(l3), 2),
            "keywords": kw,
            "effects": eff,
            "mechanics": card.get("mechanics", []),
        })
        type_counts[ctype] += 1

    print(f"\n{'=' * 70}")
    print(f"SCORING RESULTS ({len(scored)} cards scored)")
    print(f"{'=' * 70}")
    for t, n in type_counts.most_common():
        print(f"  {t}: {n}")

    scored.sort(key=lambda x: -x["score"])
    scores = [s["score"] for s in scored]

    print(f"\n  Score stats: min={min(scores):.1f}, max={max(scores):.1f}, mean={np.mean(scores):.1f}, median={np.median(scores):.1f}")

    # Distribution
    buckets = {"<-5": 0, "-5~-2": 0, "-2~0": 0, "0~2": 0, "2~5": 0, "5~10": 0, ">10": 0}
    for s in scores:
        if s < -5: buckets["<-5"] += 1
        elif s < -2: buckets["-5~-2"] += 1
        elif s < 0: buckets["-2~0"] += 1
        elif s < 2: buckets["0~2"] += 1
        elif s < 5: buckets["2~5"] += 1
        elif s < 10: buckets["5~10"] += 1
        else: buckets[">10"] += 1

    print(f"\n  Distribution:")
    for b, n in buckets.items():
        bar = "#" * n
        print(f"    {b:>8s}: {n:4d} {bar}")

    # Top 20 / Bottom 10
    print(f"\n  === TOP 20 ===")
    print(f"  {'Score':>6} | {'Cost':>4} | {'Type':>7} | {'Class':>6} | {'Rarity':>10} | Name | Details")
    for s in scored[:20]:
        detail = ",".join(s["keywords"][:2] + s["effects"][:2])
        print(f"  {s['score']:6.1f} | {s['cost']:4d} | {s['type']:>7s} | {s['class']:>6s} | {s['rarity']:>10s} | {s['name']} | {detail}")

    print(f"\n  === BOTTOM 10 ===")
    for s in scored[-10:]:
        detail = ",".join(s["keywords"][:2] + s["effects"][:2])
        print(f"  {s['score']:6.1f} | {s['cost']:4d} | {s['type']:>7s} | {s['class']:>6s} | {s['rarity']:>10s} | {s['name']} | {detail}")

    # Per-rarity stats
    print(f"\n  === PER-RARITY ===")
    for rar in ["COMMON", "RARE", "EPIC", "LEGENDARY"]:
        rs = [s["score"] for s in scored if s["rarity"] == rar]
        if rs:
            print(f"    {rar:<12s}: n={len(rs):3d}, mean={np.mean(rs):5.1f}, median={np.median(rs):5.1f}, top={max(rs):5.1f}")

    # Validation checks
    print(f"\n{'=' * 70}")
    print("VALIDATION")
    print(f"{'=' * 70}")
    vanilla = [s for s in scored if s["type"] == "MINION" and not s["mechanics"] and not s["effects"]]
    if vanilla:
        v_scores = [s["score"] for s in vanilla]
        print(f"  Vanilla minions ({len(vanilla)}): mean={np.mean(v_scores):.2f}, should be ~0")

    skewness = float(np.mean((np.array(scores) - np.mean(scores))**3) / np.std(scores)**3)
    print(f"  Distribution skewness: {skewness:.2f} (target < 1.0)")

    # Save
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=1)
    print(f"\n  Report saved: {OUTPUT_REPORT}")

    # Keyword stats
    kw_counter = Counter()
    for s in scored:
        for k in s["keywords"]:
            kw_counter[k] += 1
    print(f"\n  Keyword usage: {len(kw_counter)} distinct applied")

    kw_params = {
        "tiers": {t: list(kws) for t, kws in KEYWORD_TIERS.items()},
        "bases": TIER_BASES,
        "formula": "base * (1 + 0.1 * mana)",
        "class_multiplier": CLASS_MULTIPLIER,
    }
    with open(OUTPUT_KEYWORDS, "w", encoding="utf-8") as f:
        json.dump(kw_params, f, indent=2, ensure_ascii=False)
    print(f"  Keyword params saved: {OUTPUT_KEYWORDS}")


if __name__ == "__main__":
    main()

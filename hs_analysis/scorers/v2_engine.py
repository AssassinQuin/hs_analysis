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

Refactored from scripts/v2_scoring_engine.py:
  - Constants imported from hs_analysis.scorers.constants
  - Vanilla curve imported from hs_analysis.scorers.vanilla_curve
  - Paths from hs_analysis.config
"""
import json
import re
from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import curve_fit

from hs_analysis.config import (
    UNIFIED_DB_PATH,
    V2_CURVE_PARAMS_PATH,
    V2_KEYWORD_PARAMS_PATH,
    V2_REPORT_PATH,
)
from hs_analysis.scorers.constants import (
    KEYWORD_TIERS_V2 as KEYWORD_TIERS,
    KEYWORD_CN_V2 as KEYWORD_CN,
    TIER_BASES,
    EFFECT_PATTERNS_V2 as EFFECT_PATTERNS,
    CLASS_MULTIPLIER,
    CONDITION_DEFS_V2 as CONDITION_DEFS,
)
from hs_analysis.scorers.vanilla_curve import power_law, linear_model, fit_vanilla_curve

DATA_PATH = str(UNIFIED_DB_PATH)
OUTPUT_CURVE = str(V2_CURVE_PARAMS_PATH)
OUTPUT_KEYWORDS = str(V2_KEYWORD_PARAMS_PATH)
OUTPUT_REPORT = str(V2_REPORT_PATH)


# ──────────────────────────────────────────────
# L2: Keyword Scoring
# ──────────────────────────────────────────────
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
# L5: Conditional Expectation Layer
# ──────────────────────────────────────────────
# Many cards are weak standalone but powerful with conditions met.
# This layer estimates P(condition met) × bonus_when_met.

def calc_conditional_ev(card, base_l2l3):
    text = card.get("text", "")
    mechs = set(card.get("mechanics", []))
    all_text = " ".join(mechs) + " " + text

    cond_score = 0.0
    cond_details = []
    matched = set()

    for cname, pat, prob, mult in CONDITION_DEFS:
        if re.search(pat, all_text) and cname not in matched:
            matched.add(cname)
            ev = prob * base_l2l3 * (mult - 1.0)
            cond_score += ev
            cond_details.append(f"{cname}={ev:+.1f}(P{prob:.0%}×M{mult:.1f})")

    return cond_score, cond_details


# ──────────────────────────────────────────────
# L4: Type Adapters — data-driven baselines per type
# ──────────────────────────────────────────────
def _fit_per_type_baselines(cards, curve_popt):
    """
    For each card type, compute expected effect budget by fitting
    actual L2+L3 totals to a per-type power-law curve.
    This gives every type a proper L1 baseline from data.
    """
    baselines = {}
    type_groups = defaultdict(list)

    for card in cards:
        ctype = card.get("type", "")
        if ctype not in ("SPELL", "WEAPON", "LOCATION", "HERO"):
            continue
        mana = max(card.get("cost", 0), 0)
        if mana == 0:
            continue
        text = card.get("text", "")
        l2, _ = calc_keyword_score(card, curve_popt)
        l3, _ = parse_text_effects(text)
        total_value = l2 + l3
        type_groups[ctype].append((mana, total_value))

    for ctype, entries in type_groups.items():
        if len(entries) < 5:
            continue
        manas = np.array([e[0] for e in entries], dtype=float)
        values = np.array([e[1] for e in entries], dtype=float)
        try:
            popt, _ = curve_fit(
                power_law, manas, values, p0=[1.0, 0.7, 0],
                bounds=([0, 0.1, -5], [20, 2, 10]), maxfev=10000
            )
            baselines[ctype] = {
                "params": popt.tolist(),
                "formula": "a * mana^b + c",
                "sample": len(entries),
                "mean_value": float(np.mean(values)),
            }
            print(f"  {ctype} baseline: {popt[0]:.2f} * m^{popt[1]:.2f} + ({popt[2]:.2f}), n={len(entries)}, mean={np.mean(values):.1f}")
        except Exception:
            baselines[ctype] = {"params": None, "mean_value": float(np.mean(values))}
            print(f"  {ctype} baseline: flat={np.mean(values):.1f} (fit failed), n={len(entries)}")

    return baselines


def score_minion(card, curve_popt, baselines):
    mana = max(card.get("cost", 0), 0)
    actual = card.get("attack", 0) + card.get("health", 0)
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass"), 1.0)
    expected = power_law(mana, *curve_popt) * cls_mult
    l1 = actual - expected
    l2, kw = calc_keyword_score(card, curve_popt)
    l3, eff = parse_text_effects(card.get("text", ""))
    base_l2l3 = l2 + l3
    l5, cond = calc_conditional_ev(card, base_l2l3)
    return l1 + base_l2l3 + l5, l1, l2, l3, kw, eff, l5, cond


def _get_type_expected(ctype, mana, baselines):
    bl = baselines.get(ctype)
    if not bl:
        return 0
    params = bl.get("params")
    if params:
        return power_law(mana, *params)
    return bl.get("mean_value", 0)


def score_spell(card, curve_popt, baselines):
    mana = max(card.get("cost", 0), 0)
    l2, kw = calc_keyword_score(card, curve_popt)
    l3, eff = parse_text_effects(card.get("text", ""))
    cls_mult = CLASS_MULTIPLIER.get(card.get("cardClass"), 1.0)
    expected = _get_type_expected("SPELL", mana, baselines) * cls_mult
    l1 = (l2 + l3) - expected
    base_l2l3 = l2 + l3
    l5, cond = calc_conditional_ev(card, base_l2l3)
    return l1 + l5, l1, l2, l3, kw, eff, l5, cond


def score_weapon(card, curve_popt, baselines):
    mana = max(card.get("cost", 0), 0)
    atk = card.get("attack", 0)
    dur = max(card.get("health", 1), 1)
    weapon_stats = atk * dur
    expected_stats = power_law(mana, *curve_popt) * 0.7
    l1_raw = weapon_stats - expected_stats
    l2, kw = calc_keyword_score(card, curve_popt)
    l3, eff = parse_text_effects(card.get("text", ""))
    expected_effects = _get_type_expected("WEAPON", mana, baselines)
    l1 = l1_raw + (l2 + l3) - expected_effects
    base_l2l3 = l2 + l3
    l5, cond = calc_conditional_ev(card, base_l2l3)
    return l1 + l5, l1_raw, l2, l3, kw, eff, l5, cond


def score_location(card, curve_popt, baselines):
    mana = max(card.get("cost", 0), 0)
    charges = max(card.get("health", 3), 1)
    l2, kw = calc_keyword_score(card, curve_popt)
    l3_per_use, eff = parse_text_effects(card.get("text", ""))
    total_effect = l3_per_use * charges
    expected = _get_type_expected("LOCATION", mana, baselines)
    l1 = total_effect + l2 - expected
    base_l2l3 = l2 + total_effect
    l5, cond = calc_conditional_ev(card, base_l2l3)
    return l1 + l5, 0, l2, total_effect, kw, eff, l5, cond


def score_hero(card, curve_popt, baselines):
    mana = max(card.get("cost", 0), 0)
    l2, kw = calc_keyword_score(card, curve_popt)
    l3, eff = parse_text_effects(card.get("text", ""))
    hero_power_budget = 5.0
    armor_budget = hero_power_budget
    expected = _get_type_expected("HERO", mana, baselines)
    if expected == 0:
        expected = 7.0
    l1 = l2 + l3 + armor_budget - expected
    base_l2l3 = l2 + l3
    l5, cond = calc_conditional_ev(card, base_l2l3)
    return l1 + l5, 0, l2, l3, kw, eff, l5, cond


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

    curve_popt = fit_vanilla_curve(cards)

    print(f"\n{'=' * 70}")
    print("PER-TYPE EFFECT BASELINES")
    print(f"{'=' * 70}")
    baselines = _fit_per_type_baselines(cards, curve_popt)

    scored = []
    type_counts = Counter()
    for card in cards:
        ctype = card.get("type", "")
        scorer = SCORERS.get(ctype)
        if not scorer:
            continue
        try:
            total, l1, l2, l3, kw, eff, l5, cond = scorer(card, curve_popt, baselines)
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
            "L5": round(float(l5), 2),
            "conditions": cond,
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

    # L5 conditional expectation stats
    print(f"\n  === L5 CONDITIONAL EXPECTATION ===")
    cond_cards = [s for s in scored if s["conditions"]]
    l5_scores = [s["L5"] for s in scored]
    l5_pos = [s for s in scored if s["L5"] > 0]
    print(f"    Cards with conditions: {len(cond_cards)} / {len(scored)} ({100 * len(cond_cards) / len(scored):.1f}%)")
    print(f"    L5 stats: mean={np.mean(l5_scores):.2f}, max={max(l5_scores):.2f}, total_positive={len(l5_pos)}")
    if cond_cards:
        top_cond = sorted(cond_cards, key=lambda x: -x["L5"])[:15]
        print(f"\n    Top 15 conditional boost:")
        print(f"    {'L5':>6} | {'Score':>6} | {'Cost':>4} | {'Type':>7} | Name | Conditions")
        for s in top_cond:
            cond_str = "; ".join(s["conditions"][:3])
            print(f"    {s['L5']:6.1f} | {s['score']:6.1f} | {s['cost']:4d} | {s['type']:>7s} | {s['name']} | {cond_str}")

    # Validation checks
    print(f"\n{'=' * 70}")
    print("VALIDATION")
    print(f"{'=' * 70}")
    vanilla = [s for s in scored if s["type"] == "MINION" and not s["mechanics"] and not s["effects"]]
    if vanilla:
        v_scores = [s["score"] for s in vanilla]
        print(f"  Vanilla minions ({len(vanilla)}): mean={np.mean(v_scores):.2f}, should be ~0")

    for ctype in ["MINION", "SPELL", "WEAPON", "LOCATION", "HERO"]:
        ts = [s["score"] for s in scored if s["type"] == ctype]
        if ts:
            print(f"  {ctype:<10s}: n={len(ts):3d}, mean={np.mean(ts):5.1f}, range=[{min(ts):.1f}, {max(ts):.1f}]")

    skewness = float(np.mean((np.array(scores) - np.mean(scores))**3) / np.std(scores)**3)
    print(f"  Distribution skewness: {skewness:.2f} (target < 1.0)")

    # Save
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        json.dump({"cards": scored, "baselines": {k: {kk: vv for kk, vv in v.items() if kk != "params"} for k, v in baselines.items()}}, f, ensure_ascii=False, indent=1)
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

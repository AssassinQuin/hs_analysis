#!/usr/bin/env python3
"""Pool Quality Generator — Computes pool quality metrics for V8 contextual scoring.

Reads unified_standard.json + v7_scoring_report.json + hsreplay_cache.db.
Outputs card_data/pool_quality_report.json and card_data/card_turn_data.json.

Usage: python scripts/pool_quality_generator.py
"""

import json, math, os, sqlite3, sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_PATH = os.path.join(BASE_DIR, "card_data", "240397", "unified_standard.json")
V7_PATH = os.path.join(BASE_DIR, "card_data", "240397", "scoring_report.json")
DB_PATH = os.path.join(BASE_DIR, "card_data", "240397", "hsreplay_cache.db")
POOL_OUT = os.path.join(BASE_DIR, "card_data", "240397", "pool_quality_report.json")
TURN_OUT = os.path.join(BASE_DIR, "card_data", "240397", "card_turn_data.json")

# Race pools to compute (English names matching card_cleaner output)
RACE_POOLS = ["DRAGON", "DEMON", "BEAST", "MURLOC", "PIRATE", "ELEMENTAL", "UNDEAD", "TOTEM", "MECHANICAL", "NAGA", "DRAENEI"]
# Spell school pools (English names matching card_cleaner output)
SCHOOL_POOLS = ["FIRE", "FROST", "ARCANE", "NATURE", "SHADOW", "HOLY", "FEL"]
# Type pools
TYPE_POOLS = ["MINION", "SPELL", "WEAPON"]


def load_cards():
    with open(CARDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_scores():
    """Returns {dbfId: score}"""
    with open(V7_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {entry["dbfId"]: entry.get("score", 0.0) for entry in data if "dbfId" in entry}


def compute_pool_metrics(cards_in_pool, v7_map):
    """Compute avg_v7, top_10_pct_v7, pool_size, quality_std for a list of cards."""
    scores = []
    for c in cards_in_pool:
        s = v7_map.get(c["dbfId"], 0.0)
        if s > 0:
            scores.append(s)
    if not scores:
        return {"avg_v7": 0.0, "top_10_pct_v7": 0.0, "pool_size": len(cards_in_pool), "quality_std": 0.0}
    n = len(scores)
    avg = sum(scores) / n
    std = math.sqrt(sum((s - avg) ** 2 for s in scores) / n) if n > 1 else 0.0
    top_n = max(1, math.ceil(n * 0.1))
    sorted_scores = sorted(scores, reverse=True)
    top_10 = sum(sorted_scores[:top_n]) / top_n
    return {"avg_v7": round(avg, 3), "top_10_pct_v7": round(top_10, 3), "pool_size": len(cards_in_pool), "quality_std": round(std, 3)}


def build_pools(cards):
    """Build pool_name -> list of cards mappings."""
    pools = defaultdict(list)
    for c in cards:
        # Race pools
        race = c.get("race", "") or ""
        for r in RACE_POOLS:
            if r in race:
                pools[f"race_{r}"].append(c)
        # School pools (stored in 'race' field for spells)
        for s in SCHOOL_POOLS:
            if s in race:
                pools[f"school_{s}"].append(c)
        # Type pools
        t = c.get("type", "")
        if t in TYPE_POOLS:
            pools[f"type_{t}"].append(c)
    return pools


def generate_pool_report():
    cards = load_cards()
    v7_map = load_scores()
    pools = build_pools(cards)
    report = {}
    for pool_name, pool_cards in pools.items():
        report[pool_name] = compute_pool_metrics(pool_cards, v7_map)
    return report


def load_turn_data():
    """Load avg_turns from hsreplay_cache.db."""
    turn_data = {}
    if not os.path.isfile(DB_PATH):
        return turn_data
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT dbfId, avg_turns FROM card_stats WHERE avg_turns IS NOT NULL AND avg_turns > 0")
        for row in c.fetchall():
            turn_data[str(row[0])] = {"optimal_turn": round(row[1], 1), "confidence": 0.8}
        conn.close()
    except Exception:
        pass
    return turn_data


def main():
    report = generate_pool_report()
    with open(POOL_OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"Pool quality report: {len(report)} pools -> {POOL_OUT}")

    turn_data = load_turn_data()
    with open(TURN_OUT, "w", encoding="utf-8") as f:
        json.dump(turn_data, f, ensure_ascii=False, indent=2)
    print(f"Card turn data: {len(turn_data)} cards -> {TURN_OUT}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
L6 Real-World Scoring Layer — Blends V2 theoretical scores with HSReplay data.

Computes:
  - Card Power Index (CPI): normalized blend of winrate / deck_winrate / play_rate
  - Tempo Bonus: actual turn winrate vs same-cost average
  - Meta Factor: archetype presence bonus
  - Adjusted Score: weighted blend of V2 theoretical and real-world data

Data sources:
  - hs_cards/v2_scoring_report.json  — V2 theoretical scores (1013 cards)
  - hs_cards/unified_standard.json   — card definitions (1015 cards)
  - hs_cards/hsreplay_cache.db       — HSReplay cached stats (card_stats + meta_decks)
"""
import json
import sys
import os
import math
from collections import defaultdict

import numpy as np

# ── Paths ──────────────────────────────────────────
from hs_analysis.config import PROJECT_ROOT, DATA_DIR, UNIFIED_DB_PATH, V2_REPORT_PATH

UNIFIED_PATH = str(UNIFIED_DB_PATH)
V2_REPORT_PATH_L6 = str(V2_REPORT_PATH)
L6_REPORT_PATH = str(DATA_DIR / "l6_scoring_report.json")

# Import from fetch_hsreplay with fallback
try:
    from hs_analysis.data.fetch_hsreplay import init_db, get_all_cached_stats, get_meta_decks
except ImportError:
    sys.path.insert(0, os.path.join(str(PROJECT_ROOT), "scripts"))
    from fetch_hsreplay import init_db, get_all_cached_stats, get_meta_decks


# ══════════════════════════════════════════════════════════════════════
# Core Scoring Functions
# ══════════════════════════════════════════════════════════════════════

def calc_cpi(dbf_id, all_stats):
    """Card Power Index — normalized blend of real-world performance metrics.

    CPI = 0.5 * norm(winrate) + 0.3 * norm(deck_winrate) + 0.2 * norm(play_rate)

    Min-max normalization across all cards in the standard pool.
    Returns float in [0, 1].
    """
    # Collect all values for normalization
    winrates = []
    deck_winrates = []
    play_rates = []

    for stats in all_stats.values():
        if stats.get("winrate") is not None:
            winrates.append(stats["winrate"])
        if stats.get("deck_winrate") is not None:
            deck_winrates.append(stats["deck_winrate"])
        if stats.get("play_rate") is not None:
            play_rates.append(stats["play_rate"])

    if not all_stats or not winrates:
        return 0.5  # neutral default when no data

    wr_min, wr_max = min(winrates), max(winrates)
    dwr_min, dwr_max = min(deck_winrates) if deck_winrates else (0, 1), max(deck_winrates) if deck_winrates else (1, 1)
    pr_min, pr_max = min(play_rates) if play_rates else (0, 1), max(play_rates) if play_rates else (1, 1)

    def norm(val, vmin, vmax):
        if vmax == vmin:
            return 0.5
        return (val - vmin) / (vmax - vmin)

    stats = all_stats.get(dbf_id)
    if stats is None:
        return 0.5

    wr = stats.get("winrate")
    dwr = stats.get("deck_winrate")
    pr = stats.get("play_rate")

    # If the specific card lacks data, return neutral
    if wr is None:
        return 0.5

    cpi = 0.0
    cpi += 0.5 * norm(wr, wr_min, wr_max)
    cpi += 0.3 * norm(dwr if dwr is not None else wr, dwr_min, dwr_max)
    cpi += 0.2 * norm(pr if pr is not None else (pr_min + pr_max) / 2, pr_min, pr_max)

    return max(0.0, min(1.0, cpi))


def calc_tempo_bonus(dbf_id, card_data, all_stats):
    """Tempo Bonus — compare card's actual winrate vs same-cost average.

    Compares the card's winrate (at its typical play turn) against the
    average winrate of cards played at similar costs.

    tempo_bonus = clamp(winrate - avg_winrate_at_same_cost, -0.5, 0.5)
    """
    stats = all_stats.get(dbf_id)
    if stats is None or stats.get("winrate") is None:
        return 0.0

    card_winrate = stats["winrate"]
    card_cost = card_data.get("cost", 0)

    # Collect winrates of cards at the same cost
    same_cost_winrates = []
    for did, s in all_stats.items():
        if s.get("winrate") is None:
            continue
        # Use avg_turns to determine which "turn" the card is typically played
        # Cards at similar cost tend to be played at similar turns
        avg_turn = s.get("avg_turns")
        card_avg_turn = stats.get("avg_turns")

        if avg_turn is not None and card_avg_turn is not None:
            # Compare cards played within ±1 turn of each other
            if abs(avg_turn - card_avg_turn) <= 1.0:
                same_cost_winrates.append(s["winrate"])
        else:
            # Fallback: compare by cost (±1 mana)
            # Need to look up cost for this dbf_id
            pass

    if not same_cost_winrates:
        # Fallback: no tempo data, neutral bonus
        return 0.0

    avg_wr = np.mean(same_cost_winrates)
    bonus = card_winrate - avg_wr

    return max(-0.5, min(0.5, bonus))


def calc_meta_factor(dbf_id, meta_decks):
    """Meta Factor — bonus for cards appearing in meta deck signatures.

    meta_factor = 1.0 + 0.1 * log10(deck_count + 1)
    Range: [1.0, ~1.3]
    """
    deck_count = 0
    for deck in meta_decks:
        cards = deck.get("cards", [])
        if dbf_id in cards:
            deck_count += 1

    meta_factor = 1.0 + 0.1 * math.log10(deck_count + 1)
    return meta_factor


def adjusted_score(v2_score, dbf_id, all_stats, theta=0.3, v2_max_score=None):
    """Compute L6 adjusted score blending V2 theoretical with real-world data.

    result = v2_score * (1 - theta) + CPI * theta * v2_max_score

    If no HSReplay data for card, theta=0 (pure V2 score).
    """
    stats = all_stats.get(dbf_id)

    # If no data for this card, return pure V2
    if stats is None or stats.get("winrate") is None:
        return v2_score

    if v2_max_score is None or v2_max_score == 0:
        return v2_score

    cpi = calc_cpi(dbf_id, all_stats)
    result = v2_score * (1 - theta) + cpi * theta * v2_max_score

    return result


# ══════════════════════════════════════════════════════════════════════
# Report Generation
# ══════════════════════════════════════════════════════════════════════

def generate_l6_report():
    """Compute L6 adjusted scores for all 1015 cards and generate comparison report.

    Loads V2 report, unified cards, and HSReplay cache.
    Computes L6 scores, compares V2 vs L6 ranking.
    Flags cards with rank change > 20.
    Saves report to hs_cards/l6_scoring_report.json.

    Returns:
        dict with report data
    """
    # ── Load data ───────────────────────────────────
    with open(UNIFIED_PATH, "r", encoding="utf-8") as f:
        cards = json.load(f)
    with open(V2_REPORT_PATH_L6, "r", encoding="utf-8") as f:
        v2_report = json.load(f)

    conn = init_db()
    all_stats = get_all_cached_stats(conn)
    meta_decks = get_meta_decks(conn)
    conn.close()

    # Build lookup: name → card data (with dbfId)
    cards_by_name = {c["name"]: c for c in cards}
    cards_by_dbf = {c["dbfId"]: c for c in cards}

    # Build V2 lookup: name → V2 score
    v2_by_name = {c["name"]: c for c in v2_report.get("cards", [])}

    # Compute V2 max score
    v2_scores_all = [c["score"] for c in v2_report.get("cards", []) if "score" in c]
    v2_max_score = max(v2_scores_all) if v2_scores_all else 1.0

    # ── Compute L6 for all cards ────────────────────
    l6_cards = []
    for v2_card in v2_report.get("cards", []):
        name = v2_card["name"]
        v2_score = v2_card.get("score", 0)

        # Find dbfId from unified card data
        unified = cards_by_name.get(name)
        dbf_id = unified.get("dbfId") if unified else None

        if dbf_id is None:
            # Can't compute L6 without dbfId — keep V2 score
            l6_cards.append({
                **v2_card,
                "L6": v2_score,
                "CPI": None,
                "tempo_bonus": 0.0,
                "meta_factor": 1.0,
                "has_real_data": False,
            })
            continue

        # Compute components
        cpi = calc_cpi(dbf_id, all_stats)
        tempo = calc_tempo_bonus(dbf_id, unified, all_stats)
        meta = calc_meta_factor(dbf_id, meta_decks)
        l6 = adjusted_score(v2_score, dbf_id, all_stats, theta=0.3,
                            v2_max_score=v2_max_score)

        # Apply tempo bonus and meta factor as multipliers
        l6_adjusted = l6 * meta + tempo * v2_max_score * 0.05

        l6_cards.append({
            **v2_card,
            "dbfId": dbf_id,
            "L6": round(l6_adjusted, 2),
            "CPI": round(cpi, 4),
            "tempo_bonus": round(tempo, 4),
            "meta_factor": round(meta, 4),
            "has_real_data": True,
        })

    # ── Ranking comparison ──────────────────────────
    # V2 ranking (by V2 score, descending)
    v2_ranked = sorted(l6_cards, key=lambda c: c.get("score", 0), reverse=True)
    v2_rank_map = {c["name"]: i + 1 for i, c in enumerate(v2_ranked)}

    # L6 ranking (by L6 score, descending)
    l6_ranked = sorted(l6_cards, key=lambda c: c.get("L6", 0), reverse=True)
    l6_rank_map = {c["name"]: i + 1 for i, c in enumerate(l6_ranked)}

    # Flag cards with rank change > 20
    big_movers = []
    for c in l6_cards:
        v2r = v2_rank_map.get(c["name"], 999)
        l6r = l6_rank_map.get(c["name"], 999)
        c["v2_rank"] = v2r
        c["l6_rank"] = l6r
        c["rank_change"] = v2r - l6r  # positive = L6 improved rank
        if abs(c["rank_change"]) > 20:
            big_movers.append({
                "name": c["name"],
                "v2_rank": v2r,
                "l6_rank": l6r,
                "rank_change": c["rank_change"],
                "v2_score": c.get("score", 0),
                "L6": c.get("L6", 0),
                "CPI": c.get("CPI"),
            })

    # ── Build report ────────────────────────────────
    report = {
        "metadata": {
            "description": "L6 Real-World Scoring Report — V2 + HSReplay blended",
            "card_count": len(l6_cards),
            "cards_with_data": sum(1 for c in l6_cards if c.get("has_real_data")),
            "v2_max_score": v2_max_score,
            "theta": 0.3,
        },
        "big_movers": big_movers,
        "cards": l6_ranked,  # sorted by L6 score
    }

    # Save
    with open(L6_REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    return report


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("L6 REAL-WORLD SCORING — V2 + HSReplay Blend")
    print("=" * 70)

    # Load data for display
    with open(UNIFIED_PATH, "r", encoding="utf-8") as f:
        cards = json.load(f)
    with open(V2_REPORT_PATH_L6, "r", encoding="utf-8") as f:
        v2_report = json.load(f)

    conn = init_db()
    all_stats = get_all_cached_stats(conn)
    meta_decks = get_meta_decks(conn)
    conn.close()

    print(f"\n  Cards in unified DB: {len(cards)}")
    print(f"  Cards in V2 report: {len(v2_report.get('cards', []))}")
    print(f"  Cards with HSReplay data: {len(all_stats)}")
    print(f"  Meta deck archetypes: {len(meta_decks)}")

    # Generate full report
    print(f"\n{'─' * 70}")
    print("Computing L6 scores...")
    report = generate_l6_report()

    meta = report["metadata"]
    print(f"\n  Cards scored: {meta['card_count']}")
    print(f"  Cards with real-world data: {meta['cards_with_data']}")
    print(f"  V2 max score: {meta['v2_max_score']:.2f}")
    print(f"  Blending theta: {meta['theta']}")

    # ── Top 20 V2 vs L6 comparison ─────────────────
    print(f"\n{'═' * 70}")
    print("TOP 20: V2 RANK vs L6 RANK")
    print(f"{'═' * 70}")
    print(f"  {'#':>3} | {'V2 Rank':>7} | {'L6 Rank':>7} | {'Δ':>5} | {'Name':<30} | {'V2':>7} | {'L6':>7} | {'CPI':>6}")
    print(f"  {'─' * 3}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 5}─┼─{'─' * 30}─┼─{'─' * 7}─┼─{'─' * 7}─┼─{'─' * 6}")

    top20 = report["cards"][:20]
    for i, c in enumerate(top20):
        v2r = c.get("v2_rank", "?")
        l6r = i + 1
        delta = c.get("rank_change", 0)
        delta_str = f"{delta:+d}" if isinstance(delta, int) else f"{delta:+.0f}"
        v2s = c.get("score", 0)
        l6s = c.get("L6", 0)
        cpi = c.get("CPI", 0)
        cpi_str = f"{cpi:.3f}" if cpi is not None else "N/A"
        name = c["name"][:30]

        print(f"  {i+1:3d} | {v2r:>7d} | {l6r:>7d} | {delta_str:>5} | {name:<30} | {v2s:>7.2f} | {l6s:>7.2f} | {cpi_str:>6}")

    # ── Big movers ──────────────────────────────────
    movers = report["big_movers"]
    if movers:
        risers = sorted([m for m in movers if m["rank_change"] > 0],
                        key=lambda m: m["rank_change"], reverse=True)
        fallers = sorted([m for m in movers if m["rank_change"] < 0],
                         key=lambda m: m["rank_change"])

        print(f"\n{'═' * 70}")
        print(f"BIG MOVERS (|Δrank| > 20): {len(movers)} cards")
        print(f"{'═' * 70}")

        if risers:
            print(f"\n  ↑ RISERS (L6 ranks higher than V2):")
            for m in risers[:10]:
                print(f"    {m['name']}: V2#{m['v2_rank']} → L6#{m['l6_rank']} "
                      f"(+{m['rank_change']}) V2={m['v2_score']:.1f} L6={m['L6']:.1f}")

        if fallers:
            print(f"\n  ↓ FALLERS (L6 ranks lower than V2):")
            for m in fallers[:10]:
                print(f"    {m['name']}: V2#{m['v2_rank']} → L6#{m['l6_rank']} "
                      f"({m['rank_change']}) V2={m['v2_score']:.1f} L6={m['L6']:.1f}")

    print(f"\n{'─' * 70}")
    print(f"Report saved to: {L6_REPORT_PATH}")
    print("Done.")


if __name__ == "__main__":
    main()

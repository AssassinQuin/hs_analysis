#!/usr/bin/env python3
"""Rewind Delta Generator — Computes score delta between rewind and original cards.

Reads standard cards from CardDB + scoring_report.json.
Outputs card_data/rewind_delta_report.json.

Usage: python scripts/rewind_delta_generator.py
"""

import json, os, re, sys
from difflib import SequenceMatcher

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V7_PATH = os.path.join(BASE_DIR, "card_data", "240397", "scoring_report.json")
OUT_PATH = os.path.join(BASE_DIR, "card_data", "240397", "rewind_delta_report.json")


def load_cards():
    """Load standard cards from CardDB."""
    from analysis.card.data.card_data import get_db
    db = get_db()
    return db.get_collectible_cards(fmt="standard")


def load_scores():
    """Returns {dbfId: score}"""
    with open(V7_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {entry["dbfId"]: entry.get("score", 0.0) for entry in data if "dbfId" in entry}


def strip_html(text):
    """Remove HTML tags from card text."""
    return re.sub(r'<[^>]+>', '', text or '')


def find_rewind_cards(cards):
    """Find all cards with 回溯 in text."""
    return [c for c in cards if '回溯' in (c.get('text', '') or '')]


def find_original(rewind_card, all_cards, v7_map):
    """Find the best-matching original card for a rewind card.
    
    Strategy:
    1. Find cards with similar name (SequenceMatcher ratio > 0.5) but NOT rewind cards
    2. Same type preferred
    3. Similar cost preferred
    4. Return best match or None
    """
    rw_name = rewind_card.get("name", "")
    rw_type = rewind_card.get("type", "")
    rw_cost = rewind_card.get("cost", 0)
    rw_text = strip_html(rewind_card.get("text", ""))
    # Remove 回溯 and related text for matching
    rw_text_clean = re.sub(r'回溯[。.]?\s*', '', rw_text)
    
    rewind_ids = {c["dbfId"] for c in all_cards if '回溯' in (c.get('text', '') or '')}
    
    best_match = None
    best_score = 0.0
    
    for c in all_cards:
        if c["dbfId"] in rewind_ids:
            continue  # Skip other rewind cards
        if c["dbfId"] == rewind_card["dbfId"]:
            continue
        
        # Name similarity
        name_ratio = SequenceMatcher(None, rw_name, c.get("name", "")).ratio()
        
        # Text similarity (stripped)
        c_text = strip_html(c.get("text", ""))
        text_ratio = SequenceMatcher(None, rw_text_clean, c_text).ratio()
        
        # Type match bonus
        type_bonus = 0.2 if c.get("type") == rw_type else 0.0
        
        # Cost similarity bonus
        cost_diff = abs(c.get("cost", 0) - rw_cost)
        cost_bonus = max(0, 0.1 - cost_diff * 0.02)
        
        combined = name_ratio * 0.4 + text_ratio * 0.4 + type_bonus + cost_bonus
        
        if combined > best_score and combined > 0.3:
            best_score = combined
            best_match = c
    
    return best_match


def generate_report():
    cards = load_cards()
    v7_map = load_scores()
    rewind_cards = find_rewind_cards(cards)
    
    report = {}
    for rw in rewind_cards:
        dbf_id = str(rw["dbfId"])
        rw_v7 = v7_map.get(rw["dbfId"], 0.0)
        
        original = find_original(rw, cards, v7_map)
        
        if original:
            orig_v7 = v7_map.get(original["dbfId"], 0.0)
            delta = round(rw_v7 - orig_v7, 3)
            entry = {
                "name": rw["name"],
                "original_dbfId": original["dbfId"],
                "original_name": original.get("name", ""),
                "original_v7": orig_v7,
                "rewind_v7": rw_v7,
                "delta": delta,
                "paired": True,
            }
        else:
            entry = {
                "name": rw["name"],
                "original_dbfId": None,
                "original_name": None,
                "original_v7": 0.0,
                "rewind_v7": rw_v7,
                "delta": 0.0,
                "paired": False,
            }
        report[dbf_id] = entry
    
    return report


def main():
    report = generate_report()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    paired = sum(1 for v in report.values() if v["paired"])
    unpaired = sum(1 for v in report.values() if not v["paired"])
    print(f"Rewind delta report: {len(report)} cards ({paired} paired, {unpaired} unpaired) -> {OUT_PATH}")


if __name__ == "__main__":
    main()

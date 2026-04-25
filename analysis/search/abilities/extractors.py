#!/usr/bin/env python3
"""extractors.py — Pure string extractors for card text parsing.

All functions use string.find() / split() / isdigit() only.
Zero regex. Zero Chinese text. English only.
"""
from __future__ import annotations

from typing import Tuple, Optional

from analysis.search.abilities.tokens import RACE_NAMES


def clean_text(text: str) -> str:
    result = text
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        result = result.replace(tag, "")
    result = result.replace("[x]", "")
    result = result.replace("\n", " ")
    while "  " in result:
        result = result.replace("  ", " ")
    return result.strip()


def extract_number_after(text: str, keyword: str) -> int:
    idx = text.find(keyword)
    if idx < 0:
        return 0
    after = text[idx + len(keyword):].strip()
    for part in after.split():
        cleaned = part.strip(".,;:!?)")
        if cleaned.isdigit():
            return int(cleaned)
    return 0


def extract_number_before(text: str, keyword: str) -> int:
    idx = text.find(keyword)
    if idx <= 0:
        return 0
    before = text[:idx].strip()
    parts = before.split()
    for p in reversed(parts):
        cleaned = p.strip(".,;:!?(+")
        if cleaned.isdigit():
            return int(cleaned)
    return 0


def extract_stats_after(text: str, keyword: str) -> Tuple[int, int]:
    idx = text.find(keyword)
    if idx < 0:
        return 0, 0
    after = text[idx + len(keyword):]
    for i, ch in enumerate(after):
        if ch.isdigit():
            rest = after[i:]
            slash_pos = rest.find("/")
            if 0 < slash_pos < 6:
                atk_str = rest[:slash_pos]
                hp_part = rest[slash_pos + 1:]
                hp_str = ""
                for c in hp_part:
                    if c.isdigit():
                        hp_str += c
                    else:
                        break
                try:
                    return int(atk_str), int(hp_str) if hp_str else 0
                except ValueError:
                    pass
    return 0, 0


def extract_plus_stats(text: str) -> Tuple[int, int]:
    tl = text.lower()
    atk = 0
    hp = 0
    parts = tl.replace("+", " +").replace("/", " / ").split()
    i = 0
    while i < len(parts):
        p = parts[i]
        if p.startswith("+") and p[1:].isdigit():
            val = int(p[1:])
            if i + 2 < len(parts) and parts[i + 1] == "/" and parts[i + 2].startswith("+") and parts[i + 2][1:].isdigit():
                atk = val
                hp = int(parts[i + 2][1:])
                break
            if "attack" in " ".join(parts[i:i + 3]):
                atk += val
            elif "health" in " ".join(parts[i:i + 3]):
                hp += val
            else:
                atk += val
        i += 1
    return atk, hp


def extract_target_kind(text: str) -> str:
    tl = text.lower()
    from analysis.search.abilities.tokens import TARGET_PHRASES
    for phrase, kind in TARGET_PHRASES.items():
        if phrase in tl:
            return kind.value
    if "enemy" in tl:
        return "ENEMY"
    if "friendly" in tl:
        return "FRIENDLY_MINION"
    if "hero" in tl:
        return "FRIENDLY_HERO"
    return "ENEMY"


def extract_race_name(text: str) -> Optional[str]:
    tl = text.lower()
    for name, standard in RACE_NAMES.items():
        if name in tl:
            return standard
    return None


def extract_keyword_after_give(text: str) -> str:
    tl = text.lower()
    give_keywords = [
        "taunt", "rush", "divine shield", "stealth", "windfury",
        "lifesteal", "poisonous", "charge", "reborn", "elusive",
        "frozen", "immune",
    ]
    for kw in give_keywords:
        if kw in tl:
            return kw.upper().replace(" ", "_")
    return ""


def extract_card_type_from_condition(text: str) -> str:
    tl = text.lower()
    if "fire spell" in tl or "fire" in tl:
        return "FIRE"
    if "frost spell" in tl or "frost" in tl:
        return "FROST"
    if "nature spell" in tl or "nature" in tl:
        return "NATURE"
    if "holy spell" in tl or "holy" in tl:
        return "HOLY"
    if "shadow spell" in tl or "shadow" in tl:
        return "SHADOW"
    if "spell" in tl:
        return "SPELL"
    if "weapon" in tl:
        return "WEAPON"
    if "minion" in tl:
        return "MINION"
    return ""


def extract_paren_number(text: str, before: str) -> int:
    idx = text.find(before)
    if idx < 0:
        return 0
    after = text[idx + len(before):]
    paren_start = after.find("(")
    if paren_start < 0:
        paren_start = after.find("[")
    if paren_start >= 0:
        num_start = paren_start + 1
        num_str = ""
        for c in after[num_start:]:
            if c.isdigit():
                num_str += c
            else:
                break
        if num_str:
            return int(num_str)
    return 0

#!/usr/bin/env python3
"""Card data cleaner — normalize race, extract mechanics, parse spell schools.

DEPRECATED for new code: Use ``hs_analysis.data.hsdb.HSCardDB`` instead,
which provides authoritative card data from CardDefs.xml with proper enums.
The regex-based cleaning in this module is kept for backward compatibility
with legacy JSON data files.

For new code::

    from analysis.data.hsdb import get_db
    db = get_db()
    card = db.get_card("EX1_001")  # mechanics, race, school all pre-extracted
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ENUMS_PATH: Path = PROJECT_ROOT / "hearthstone_enums.json"

# --------------------------------------------------------------------------- #
#  SECTION 2 — Race / School / Rune normalization
# --------------------------------------------------------------------------- #

# 13 canonical minion races  (zh → enum id)
RACE_ZH_MAP: Dict[str, str] = {
    "野兽": "BEAST",
    "恶魔": "DEMON",
    "德莱尼": "DRAENEI",
    "龙": "DRAGON",
    "元素": "ELEMENTAL",
    "机械": "MECHANICAL",
    "鱼人": "MURLOC",
    "纳迦": "NAGA",
    "海盗": "PIRATE",
    "野猪人": "QUILBOAR",
    "图腾": "TOTEM",
    "亡灵": "UNDEAD",
    "全部": "ALL",
}

# 7 spell schools  (zh → enum id)
SCHOOL_ZH_MAP: Dict[str, str] = {
    "奥术": "ARCANE",
    "邪能": "FEL",
    "火焰": "FIRE",
    "冰霜": "FROST",
    "神圣": "HOLY",
    "自然": "NATURE",
    "暗影": "SHADOW",
}

# Death Knight rune abbreviations (single-char tokens found in race field)
RUNE_ZH_MAP: Dict[str, str] = {
    "血": "BLOOD",
    "冰": "FROST_RUNE",
    "邪": "UNHOLY",
}

# Non-race tokens to silently discard when normalizing
_DISCARD_TOKENS: set = {
    "奇闻", "地标", "武器", "英雄", "英雄牌",
}


def normalize_race(
    race_str: str,
    card_type: str,
) -> Tuple[str, str]:
    """Return ``(cleaned_race, spell_school)`` from a dirty race string.

    * **race_str** — the raw ``race`` value, e.g. ``"亡灵 野兽 冰冰"``.
    * **card_type** — ``MINION``, ``SPELL``, ``WEAPON``, etc.

    Returns:
        ``(race, school)`` where *race* is a canonical enum id (or ``""``)
        and *school* is a spell school enum id (or ``""``).
    """
    if not race_str:
        return ("", "")

    # Unify separators: commas (Chinese & English) → space
    text = race_str.replace("，", " ").replace(",", " ").strip()
    tokens = text.split()

    races: list[str] = []
    schools: list[str] = []

    for tok in tokens:
        # 1. Exact race match
        if tok in RACE_ZH_MAP:
            races.append(RACE_ZH_MAP[tok])
            continue

        # 2. Exact school match (may appear as multi-char: 冰霜, 火焰, etc.)
        if tok in SCHOOL_ZH_MAP:
            schools.append(SCHOOL_ZH_MAP[tok])
            continue

        # 3. Rune tokens — multi-char combinations like 冰冰, 血血, 邪邪
        if _parse_rune_token(tok) is not None:
            # Runes are relevant for SPELL / HERO cards (DK spells show runes)
            # For MINION, silently ignore rune tokens
            pass
            continue

        # 4. Mixed race+rune like "亡灵 冰邪" — the 亡灵 part was already
        #    captured as a race; the remaining rune tokens are handled above.

        # 5. Discard tokens
        if tok in _DISCARD_TOKENS:
            continue

        # 6. Unknown token — log and skip
        logger.debug("normalize_race: unknown token '%s' in '%s'", tok, race_str)

    # For SPELL / LOCATION / HERO cards, school takes priority over race
    # For MINION cards, race is primary
    cleaned_race = " ".join(races) if races else ""
    cleaned_school = " ".join(schools) if schools else ""

    return (cleaned_race, cleaned_school)


def _parse_rune_token(tok: str) -> Optional[str]:
    """Try to parse a rune token like ``冰冰``, ``血邪``, ``邪邪邪``.

    Returns a descriptive string like ``"2xFROST_RUNE+BLOOD"`` or *None*.
    Only used for logging; the actual rune info is not stored in the card
    model at this point.
    """
    if not tok or len(tok) > 5:
        return None
    parts: list[str] = []
    for ch in tok:
        if ch in RUNE_ZH_MAP:
            parts.append(RUNE_ZH_MAP[ch])
        else:
            return None  # not a pure rune token
    if not parts:
        return None
    from collections import Counter
    counts = Counter(parts)
    return "+".join(f"{cnt}x{rune}" for rune, cnt in sorted(counts.items()))


# --------------------------------------------------------------------------- #
#  SECTION 3 — Mechanic extraction (56 keywords from enums)
# --------------------------------------------------------------------------- #

# NOTE: Some keywords (IMBUE, TRIGGER_VISUAL, START_OF_GAME, etc.) are
# **tag-based** — they appear in the ``mechanics`` field from HSJSON but
# do NOT have a unique Chinese keyword in card text.  We preserve those
# from the existing mechanics list rather than trying to regex-match them.

# Keywords that should be preserved from existing mechanics (not regex-able)
_PRESERVE_FROM_EXISTING: set = {
    "IMBUE",
    "TRIGGER_VISUAL",
    "START_OF_GAME",
    "END_OF_TURN_TRIGGER",
    "START_OF_COMBAT",
    "START_OF_GAME_KEYWORD",
    "COLLECTIONMANAGER_FILTER_MANA_EVEN",
    "COLLECTIONMANAGER_FILTER_MANA_ODD",
    "JADE_GOLEM",
    "GIGANTIFY",
    "MINIATURIZE",
    "AURA",
}

# Each entry: (keyword_id, compiled_regex, priority)
# Higher priority = checked first (longer / more specific patterns first).
# Many patterns need negative lookbehind/lookahead to avoid false positives.
KEYWORD_PATTERNS: List[Tuple[str, "re.Pattern[str]", int]] = []

# Helper to register a pattern
def _kw(kw_id: str, pattern: str, priority: int = 0) -> None:
    KEYWORD_PATTERNS.append((kw_id, re.compile(pattern), priority))


# ---- Sorted by priority (high → low).  Same-priority entries are order-independent. ----

# Multi-char exact matches (high priority to avoid substring conflicts)
_kw("SIDE_QUEST", r"支线任务", priority=100)
_kw("START_OF_GAME_KEYWORD", r"游戏开始时|对战开始时", priority=100)
_kw("START_OF_COMBAT", r"战斗开始", priority=100)
_kw("END_OF_TURN_TRIGGER", r"回合结束(?:时|触发)?", priority=95)
_kw("MANATHIRST", r"法力(?:值)?渴[求望]", priority=90)
_kw("SPELLPOWER", r"法术伤害?\s*(?:\+\d+)?", priority=90)
_kw("HONORABLE_KILL", r"荣誉消灭", priority=90)
_kw("CANT_ATTACK", r"无法攻击", priority=90)
_kw("OVERHEAL", r"过量治疗", priority=85)

_kw("BATTLECRY", r"战吼", priority=80)
_kw("DEATHRATTLE", r"亡语", priority=80)
_kw("DIVINE_SHIELD", r"圣盾", priority=80)
_kw("CHOOSE_ONE", r"抉择", priority=80)
_kw("DISCOVER", r"发现", priority=80)
_kw("TAUNT", r"嘲[讽晕]", priority=80)
_kw("LIFESTEAL", r"吸血", priority=80)
_kw("FREEZE", r"冻结", priority=80)
_kw("OVERLOAD", r"过载\s*(?:\(?(\d+)\)?)?", priority=80)
_kw("POISONOUS", r"剧毒", priority=80)         # POISONOUS & VENOMOUS share zh
_kw("SILENCE", r"沉默", priority=80)
_kw("COMBO", r"连击", priority=80)
_kw("SECRET", r"奥秘", priority=80)
_kw("QUEST", r"(?:^|[^支])任务", priority=75)   # avoid matching 支线任务
_kw("STEALTH", r"潜行", priority=80)
_kw("WINDFURY", r"风怒", priority=80)
_kw("CHARGE", r"冲锋", priority=80)
_kw("RUSH", r"突袭", priority=80)

_kw("REBORN", r"复生", priority=70)
_kw("ECHO", r"回响", priority=70)
_kw("TWINSPELL", r"双生法术", priority=70)
_kw("OUTCAST", r"流放", priority=70)
_kw("SPELLBURST", r"法术迸发", priority=70)
_kw("FRENZY", r"暴怒", priority=70)
_kw("CORRUPT", r"腐蚀", priority=70)
_kw("TRADEABLE", r"(?:可|能)交易", priority=70)
_kw("DREDGE", r"掘葬", priority=70)
_kw("INFUSE", r"充能", priority=70)
_kw("EXCAVATE", r"挖掘", priority=70)
_kw("COLOSSAL", r"巨像", priority=70)
_kw("TITAN", r"泰坦", priority=70)
_kw("ENRAGED", r"激怒", priority=70)
_kw("COUNTER", r"反制", priority=70)
_kw("MORPH", r"变形", priority=70)
_kw("IMMUNE", r"免疫", priority=70)
_kw("AVENGE", r"复仇", priority=70)
_kw("MAGNETIC", r"磁力", priority=70)
_kw("FORGE", r"锻造", priority=70)
_kw("QUICKDRAW", r"速瞄", priority=70)
_kw("INSPIRE", r"激励", priority=70)
_kw("OVERKILL", r"超杀", priority=70)
_kw("VENOMOUS", r"剧毒", priority=65)           # same zh as POISONOUS

# Sort: highest priority first → longest pattern first → alphabetical
KEYWORD_PATTERNS.sort(key=lambda t: (-t[2], -len(t[1].pattern), t[0]))


def extract_mechanics(
    card_text: str,
    existing_mechanics: Optional[List[str]] = None,
    card_type: str = "",
) -> List[str]:
    """Extract keyword mechanic IDs from card text + existing mechanics.

    1. Apply 56 regex patterns against *card_text*.
    2. Merge with *existing_mechanics* (keeping tag-based keywords).
    3. De-duplicate and sort.
    """
    found: set[str] = set()

    # Regex scan
    text = card_text or ""
    for kw_id, pat, _prio in KEYWORD_PATTERNS:
        if pat.search(text):
            found.add(kw_id)

    # Merge with existing tag-based mechanics
    if existing_mechanics:
        for m in existing_mechanics:
            if m in _PRESERVE_FROM_EXISTING:
                found.add(m)
            elif m not in found:
                # Keep any existing mechanic that wasn't regex-found
                # (may be from HSJSON source with English tags)
                found.add(m)

    # Resolve synonyms: POISONOUS and VENOMOUS are treated as POISONOUS
    if "VENOMOUS" in found and "POISONOUS" in found:
        found.discard("VENOMOUS")

    return sorted(found)


# --------------------------------------------------------------------------- #
#  SECTION 4 — Card cleaning pipeline
# --------------------------------------------------------------------------- #

def clean_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Clean a single card dict in-place and return it.

    Normalizes:
    * ``race`` → canonical race enum(s), space-separated
    * ``spellSchool`` → extracted spell school (new field)
    * ``mechanics`` → re-extracted from text using 56 keywords
    * ``cost``, ``attack``, ``health`` → guaranteed int
    * ``type`` → trimmed, upper
    """
    card_type = (card.get("type") or "").strip().upper()

    # 1. Race + School normalization
    raw_race = card.get("race", "")
    cleaned_race, cleaned_school = normalize_race(raw_race, card_type)
    card["race"] = cleaned_race
    if cleaned_school:
        card["spellSchool"] = cleaned_school
    # Remove spellSchool if empty and key existed
    elif "spellSchool" in card:
        del card["spellSchool"]

    # 2. Mechanic re-extraction
    old_mechanics = card.get("mechanics", [])
    card["mechanics"] = extract_mechanics(
        card.get("text", ""),
        old_mechanics,
        card_type,
    )

    # 3. Ensure numeric fields are int
    for field in ("cost", "attack", "health"):
        val = card.get(field, 0)
        if val is None:
            val = 0
        try:
            card[field] = int(val)
        except (ValueError, TypeError):
            card[field] = 0

    # 4. Normalize type
    card["type"] = card_type

    return card


def clean_card_pool(
    input_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    backup: bool = True,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Clean all cards in a JSON file.

    Args:
        input_path:  Path to JSON card array.  Defaults to ``unified_standard.json``.
        output_path: Where to write cleaned data.  Defaults to *input_path* (in-place).
        backup:      If True, copy the original to ``<name>.bak`` before overwriting.

    Returns:
        ``(cards, stats)`` where *stats* has cleaning statistics.
    """
    if input_path is None:
        input_path = DATA_DIR / "unified_standard.json"
    if output_path is None:
        output_path = input_path

    logger.info("Loading cards from %s", input_path)
    cards: List[Dict[str, Any]] = json.loads(input_path.read_text(encoding="utf-8"))
    total = len(cards)

    # Stats counters
    stats: Dict[str, Any] = {
        "total": total,
        "race_changed": 0,
        "school_added": 0,
        "mechanics_changed": 0,
        "type_fixed": 0,
    }

    for card in cards:
        old_race = card.get("race", "")
        old_mechanics = sorted(card.get("mechanics", []))
        old_type = card.get("type", "")

        clean_card(card)

        if card.get("race", "") != old_race:
            stats["race_changed"] += 1
        if "spellSchool" in card:
            stats["school_added"] += 1
        if sorted(card.get("mechanics", [])) != old_mechanics:
            stats["mechanics_changed"] += 1
        if card.get("type", "") != old_type:
            stats["type_fixed"] += 1

    # Backup
    if backup and output_path.exists():
        bak = output_path.with_suffix(output_path.suffix + ".bak")
        shutil.copy2(output_path, bak)
        logger.info("Backup → %s", bak)

    # Write
    output_path.write_text(
        json.dumps(cards, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Cleaned %d cards → %s", total, output_path)

    return cards, stats


# --------------------------------------------------------------------------- #
#  SECTION 5 — CLI
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cards, stats = clean_card_pool()

    print(f"\n✅ Cleaned {stats['total']} cards")
    print(f"   Race changed:        {stats['race_changed']}")
    print(f"   Spell school added:  {stats['school_added']}")
    print(f"   Mechanics changed:   {stats['mechanics_changed']}")
    print(f"   Type fixed:          {stats['type_fixed']}")

    # Quick smoke test
    by_mech: Dict[str, int] = {}
    for c in cards:
        for m in c.get("mechanics", []):
            by_mech[m] = by_mech.get(m, 0) + 1

    print(f"\n   Unique mechanics: {len(by_mech)}")
    for m, cnt in sorted(by_mech.items(), key=lambda x: -x[1])[:10]:
        print(f"     {m}: {cnt}")

    by_race: Dict[str, int] = {}
    for c in cards:
        if c.get("race"):
            by_race[c["race"]] = by_race.get(c["race"], 0) + 1
    print(f"\n   Unique races: {len(by_race)}")
    for r, cnt in sorted(by_race.items(), key=lambda x: -x[1]):
        print(f"     {r}: {cnt}")

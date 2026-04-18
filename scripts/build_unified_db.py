# -*- coding: utf-8 -*-
"""
Build unified card database from iyingdi raw data.
Fix class/type mapping, extract mechanics from rule text.
Then re-analyze all 16 decks with complete data.
"""
import json
import re
import sys
import io
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

RAW_PATH = "D:/code/game/hs_cards/iyingdi_standard_raw.json"
HSJSON_PATH = "D:/code/game/hs_cards/hsjson_standard.json"
LEGEND_PATH = "D:/code/game/hs_cards/standard_legendaries_analysis.json"
OUTPUT = "D:/code/game/hs_cards/unified_standard.json"

TYPE_MAP = {
    "随从": "MINION", "法术": "SPELL", "武器": "WEAPON",
    "英雄牌": "HERO", "地标": "LOCATION", "装备": "WEAPON",
}
CLASS_MAP = {
    "Druid": "DRUID", "Hunter": "HUNTER", "Mage": "MAGE",
    "Paladin": "PALADIN", "Priest": "PRIEST", "Rogue": "ROGUE",
    "Shaman": "SHAMAN", "Warlock": "WARLOCK", "Warrior": "WARRIOR",
    "Deathknight": "DEATHKNIGHT", "Demonhunter": "DEMONHUNTER",
    "Neutral": "NEUTRAL",
}
RARITY_MAP = {
    "普通": "COMMON", "稀有": "RARE", "史诗": "EPIC", "传说": "LEGENDARY",
}

KEYWORD_PATTERNS = {
    "BATTLECRY": r"战吼",
    "DEATHRATTLE": r"亡语",
    "DISCOVER": r"发现",
    "DIVINE_SHIELD": r"圣盾",
    "RUSH": r"突袭",
    "CHARGE": r"冲锋",
    "WINDFURY": r"风怒",
    "TAUNT": r"嘲讽",
    "LIFESTEAL": r"吸血",
    "STEALTH": r"潜行",
    "SPELLPOWER": r"法术伤害",
    "SECRET": r"奥秘",
    "FREEZE": r"冻结",
    "POISONOUS": r"剧毒",
    "SILENCE": r"沉默",
    "OVERLOAD": r"过载",
    "COMBO": r"连击",
    "AURA": r"光环",
    "CHOOSE_ONE": r"抉择",
    "REBORN": r"复生",
    "ELUSIVE": r"魔免|无法成为法术",
    "IMMUNE": r"免疫",
    "OUTCAST": r"流放",
    "TRADEABLE": r"可交易",
    "QUEST": r"任务[:：]",
    "COLOSSAL": r"巨型",
    "TRIGGER_VISUAL": r"回溯|触发|每当|在你的回合",
    "IMBUE": r"灌注",
    "SIDE_QUEST": r"支线任务",
    "START_OF_GAME": r"对战开始",
}


def extract_mechanics(rule_text):
    mechs = []
    for mech, pat in KEYWORD_PATTERNS.items():
        if re.search(pat, rule_text):
            mechs.append(mech)
    return mechs


def normalize_class(faction):
    if not faction:
        return "NEUTRAL"
    multi = []
    for cls in faction.split(","):
        mapped = CLASS_MAP.get(cls.strip(), cls.strip().upper())
        multi.append(mapped)
    if len(multi) == 1:
        return multi[0]
    return multi[0]


def normalize_card(raw):
    rule = raw.get("rule", "")
    clazz_raw = raw.get("clazz", "")
    ctype = TYPE_MAP.get(clazz_raw, clazz_raw)
    faction = raw.get("faction", "")
    card_class = normalize_class(faction)
    mechs = extract_mechanics(rule)

    return {
        "dbfId": raw.get("gameid"),
        "name": raw.get("cname", ""),
        "ename": raw.get("ename", ""),
        "cost": raw.get("mana", 0),
        "attack": raw.get("attack", 0),
        "health": raw.get("hp", 0),
        "type": ctype,
        "cardClass": card_class,
        "rarity": RARITY_MAP.get(raw.get("rarity", ""), raw.get("rarity", "")),
        "text": rule,
        "race": raw.get("race", ""),
        "set": raw.get("seriesAbbr", ""),
        "setName": raw.get("seriesName", ""),
        "mechanics": mechs,
        "source": "iyingdi",
    }


def main():
    with open(RAW_PATH, "r", encoding="utf-8") as f:
        raw_cards = json.load(f)

    with open(HSJSON_PATH, "r", encoding="utf-8") as f:
        hsjson = json.load(f)

    with open(LEGEND_PATH, "r", encoding="utf-8") as f:
        legend_data = json.load(f)
    legend_names = {c["name"] for c in legend_data["legendaries"]}

    cards_iyd = [normalize_card(c) for c in raw_cards]

    # HSJSON cards as secondary
    cards_hsj = hsjson["cards"]

    name_to_iyd = {c["name"]: c for c in cards_iyd}
    name_to_hsj = {c["name"]: c for c in cards_hsj}

    # Build unified: prefer iyingdi (has 985), supplement with hsjson extras
    unified = {}
    for c in cards_iyd:
        unified[c["name"]] = c

    # Add HSJSON-only cards (by name)
    for c in cards_hsj:
        if c["name"] not in unified:
            unified[c["name"]] = {
                "dbfId": c.get("dbfId"),
                "name": c.get("name", ""),
                "ename": "",
                "cost": c.get("cost", 0),
                "attack": c.get("attack", 0),
                "health": c.get("health", 0),
                "type": c.get("type", ""),
                "cardClass": c.get("cardClass", ""),
                "rarity": c.get("rarity", ""),
                "text": re.sub(r"<[^>]+>", "", c.get("text", "") or ""),
                "race": "",
                "set": c.get("set", ""),
                "setName": "",
                "mechanics": c.get("mechanics", []),
                "source": "hsjson",
            }

    unified_list = sorted(unified.values(), key=lambda x: (x.get("cost", 0), x["name"]))

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(unified_list, f, ensure_ascii=False, indent=1)
    print(f"Unified DB: {len(unified_list)} cards saved to {OUTPUT}")

    # Stats
    rarities = Counter(c["rarity"] for c in unified_list)
    types = Counter(c["type"] for c in unified_list)
    sources = Counter(c["source"] for c in unified_list)

    print(f"\nRarities: {dict(rarities.most_common())}")
    print(f"Types: {dict(types.most_common())}")
    print(f"Sources: {dict(sources.most_common())}")

    # Check legend coverage
    legend_in_unified = sum(1 for c in unified_list if c["name"] in legend_names)
    print(f"\nLegend names from V1: {len(legend_names)}")
    print(f"Of those in unified DB: {legend_in_unified}")

    # All mechanics found
    all_mechs = Counter()
    for c in unified_list:
        for m in c.get("mechanics", []):
            all_mechs[m] += 1
    print(f"\nMechanics extracted: {len(all_mechs)} types")
    for m, n in all_mechs.most_common():
        print(f"  {m:<25s}: {n}")

    # Per-rarity card count
    print(f"\n=== 按稀有度卡牌数 ===")
    for r in ["COMMON", "RARE", "EPIC", "LEGENDARY"]:
        cnt = rarities.get(r, 0)
        print(f"  {r:<12s}: {cnt}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
from __future__ import annotations

CLASS_CN = {
    "WARRIOR": "战士", "SHAMAN": "萨满", "ROGUE": "盗贼",
    "PALADIN": "圣骑士", "HUNTER": "猎人", "WARLOCK": "术士",
    "MAGE": "法师", "PRIEST": "牧师", "DRUID": "德鲁伊",
    "DEMONHUNTER": "恶魔猎手", "DEATHKNIGHT": "死亡骑士",
}

_HERO_CARD_CLASS = {
    "HERO_01": "WARRIOR", "HERO_01a": "WARRIOR", "HERO_01b": "WARRIOR",
    "HERO_01bn": "WARRIOR", "HERO_01n": "WARRIOR", "HERO_01w": "WARRIOR",
    "HERO_01bp": "WARRIOR", "HERO_01dbp": "WARRIOR",
    "HERO_02": "SHAMAN",
    "HERO_03": "ROGUE", "HERO_03a": "ROGUE", "HERO_03az": "ROGUE",
    "HERO_03b": "ROGUE", "HERO_03e": "ROGUE",
    "HERO_03bp": "ROGUE", "HERO_03dbp": "ROGUE", "HERO_03ebp": "ROGUE",
    "HERO_04": "PALADIN",
    "HERO_05": "HUNTER", "HERO_05a": "HUNTER", "HERO_05b": "HUNTER",
    "HERO_05bp": "HUNTER",
    "HERO_06": "WARLOCK", "HERO_06a": "WARLOCK", "HERO_06bi": "WARLOCK",
    "HERO_06bp": "WARLOCK", "HERO_06ebp": "WARLOCK",
    "HERO_07": "MAGE",
    "HERO_08": "PRIEST",
    "HERO_09": "DRUID", "HERO_09a": "DRUID",
    "HERO_10": "DEMONHUNTER", "HERO_10a": "DEMONHUNTER",
    "HERO_10ak_Kailene": "DEMONHUNTER", "HERO_10akhp": "DEMONHUNTER",
    "HERO_10ak": "DEMONHUNTER",
    "HERO_11": "DEATHKNIGHT", "HERO_11a": "DEATHKNIGHT",
    "HERO_11aw": "DEATHKNIGHT", "HERO_11awhp": "DEATHKNIGHT",
}

_HERO_DBF_CLASS = {
    7: "WARRIOR", 813: "WARLOCK", 930: "SHAMAN", 1066: "ROGUE",
    1418: "HUNTER", 1655: "DRUID", 1709: "MAGE", 1801: "PRIEST",
    4193: "PALADIN", 56550: "DEMONHUNTER", 84306: "DEATHKNIGHT",
}


def hero_card_to_class(card_id: str) -> str:
    if not card_id:
        return "UNKNOWN"
    if card_id in _HERO_CARD_CLASS:
        return _HERO_CARD_CLASS[card_id]
    for prefix in sorted(_HERO_CARD_CLASS.keys(), key=len, reverse=True):
        if card_id.startswith(prefix):
            return _HERO_CARD_CLASS[prefix]
    return "UNKNOWN"


def hero_dbf_to_class(dbf_id: int) -> str:
    return _HERO_DBF_CLASS.get(dbf_id, "UNKNOWN")


def class_to_cn(cls: str) -> str:
    return CLASS_CN.get(cls, cls)

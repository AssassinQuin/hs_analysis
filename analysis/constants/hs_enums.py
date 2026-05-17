# -*- coding: utf-8 -*-
"""Hearthstone Power.log 枚举常量与映射表

统一管理所有 GameTag / Zone / CardType / Step 数值常量，
以及 tag 名→Entity属性 的映射关系，供 packet_replayer / global_tracker 共用。

数据来源: hearthstone.enums (官方 Python 包)
当 hearthstone 包可用时，所有数值常量从库枚举派生，确保单一数据源；
否则回退到手动定义的数值（向后兼容）。
"""

# ═══════════════════════════════════════════════════════════════
# Derive constants from hearthstone.enums when available
# ═══════════════════════════════════════════════════════════════

try:
    from hearthstone.enums import GameTag as _GT, Zone as _Zone, CardType as _CT, Step as _Step

    # GameTag numeric values — derived from library
    TAG_RESOURCES = _GT.RESOURCES.value
    TAG_RESOURCES_USED = _GT.RESOURCES_USED.value
    TAG_MAXRESOURCES = _GT.MAXRESOURCES.value
    TAG_TURN = _GT.TURN.value
    TAG_STEP = _GT.STEP.value
    TAG_ZONE = _GT.ZONE.value
    TAG_CARDTYPE = _GT.CARDTYPE.value
    TAG_COST = _GT.COST.value
    TAG_ATK = _GT.ATK.value
    TAG_HEALTH = _GT.HEALTH.value
    TAG_ARMOR = _GT.ARMOR.value
    TAG_ZONE_POSITION = _GT.ZONE_POSITION.value
    TAG_CONTROLLER = _GT.CONTROLLER.value
    TAG_EXHAUSTED = _GT.EXHAUSTED.value
    TAG_TAUNT = _GT.TAUNT.value
    TAG_DIVINE_SHIELD = _GT.DIVINE_SHIELD.value
    TAG_CHARGE = _GT.CHARGE.value
    TAG_RUSH = _GT.RUSH.value
    TAG_WINDFURY = _GT.WINDFURY.value
    TAG_STEALTH = _GT.STEALTH.value
    TAG_POISONOUS = _GT.POISONOUS.value
    TAG_LIFESTEAL = _GT.LIFESTEAL.value
    TAG_FROZEN = _GT.FROZEN.value
    TAG_REBORN = _GT.REBORN.value
    TAG_OVERLOAD_LOCKED = _GT.OVERLOAD_LOCKED.value
    TAG_TEMP_RESOURCES = _GT.TEMP_RESOURCES.value
    TAG_OVERLOAD_OWED = _GT.OVERLOAD_OWED.value
    TAG_IMMUNE = _GT.IMMUNE.value
    # HERO_POWER_USED and SPELL_POWER are not in the library — manual fallback
    TAG_HERO_POWER_USED = 426
    TAG_SPELL_POWER = 215

    # Zone values — derived from library
    ZONE_INVALID = _Zone.INVALID.value
    ZONE_PLAY = _Zone.PLAY.value
    ZONE_DECK = _Zone.DECK.value
    ZONE_HAND = _Zone.HAND.value
    ZONE_GRAVEYARD = _Zone.GRAVEYARD.value
    ZONE_SETASIDE = _Zone.SETASIDE.value
    ZONE_SECRET = _Zone.SECRET.value
    ZONE_REMOVEDFROMGAME = _Zone.REMOVEDFROMGAME.value

    # CardType values — derived from library
    CT_INVALID = _CT.INVALID.value
    CT_GAME = _CT.GAME.value
    CT_PLAYER = _CT.PLAYER.value
    CT_HERO = _CT.HERO.value
    CT_MINION = _CT.MINION.value
    CT_SPELL = _CT.SPELL.value
    CT_ENCHANTMENT = _CT.ENCHANTMENT.value
    CT_WEAPON = _CT.WEAPON.value
    CT_ITEM = _CT.ITEM.value
    CT_HERO_POWER = _CT.HERO_POWER.value
    CT_LOCATION = _CT.LOCATION.value

    # Step values — derived from library
    STEP_INVALID = _Step.INVALID.value
    STEP_MAIN_READY = _Step.MAIN_READY.value
    STEP_MAIN_START = _Step.MAIN_START.value
    STEP_MAIN_ACTION = _Step.MAIN_ACTION.value
    STEP_MAIN_END = _Step.MAIN_END.value

except ImportError:
    # Manual fallback if hearthstone package not installed

    # GameTag numeric values
    TAG_RESOURCES = 26
    TAG_RESOURCES_USED = 25
    TAG_MAXRESOURCES = 37
    TAG_TURN = 20
    TAG_STEP = 19
    TAG_ZONE = 49
    TAG_CARDTYPE = 202
    TAG_COST = 54
    TAG_ATK = 47
    TAG_HEALTH = 71
    TAG_ARMOR = 292
    TAG_ZONE_POSITION = 341
    TAG_CONTROLLER = 3
    TAG_EXHAUSTED = 424
    TAG_TAUNT = 238
    TAG_DIVINE_SHIELD = 191
    TAG_CHARGE = 188
    TAG_RUSH = 187
    TAG_WINDFURY = 189
    TAG_STEALTH = 225
    TAG_POISONOUS = 237
    TAG_LIFESTEAL = 2145
    TAG_FROZEN = 260
    TAG_REBORN = 2185
    TAG_OVERLOAD_LOCKED = 393
    TAG_TEMP_RESOURCES = 295
    TAG_OVERLOAD_OWED = 394
    TAG_IMMUNE = 477
    TAG_HERO_POWER_USED = 426
    TAG_SPELL_POWER = 215

    # Zone values
    ZONE_INVALID = 0
    ZONE_PLAY = 1
    ZONE_DECK = 2
    ZONE_HAND = 3
    ZONE_GRAVEYARD = 4
    ZONE_SETASIDE = 6
    ZONE_SECRET = 7
    ZONE_REMOVEDFROMGAME = 8

    # CardType values
    CT_INVALID = 0
    CT_GAME = 1
    CT_PLAYER = 2
    CT_HERO = 3
    CT_MINION = 4
    CT_SPELL = 5
    CT_ENCHANTMENT = 6
    CT_WEAPON = 7
    CT_ITEM = 8
    CT_HERO_POWER = 10
    CT_LOCATION = 39

    # Step values
    STEP_INVALID = 0
    STEP_MAIN_READY = 9
    STEP_MAIN_START = 10
    STEP_MAIN_ACTION = 11
    STEP_MAIN_END = 12

# ═══════════════════════════════════════════════════════════════
# String → Enum 映射表
# ═══════════════════════════════════════════════════════════════

ZONE_NAME_MAP = {
    'PLAY': ZONE_PLAY,
    'DECK': ZONE_DECK,
    'HAND': ZONE_HAND,
    'GRAVEYARD': ZONE_GRAVEYARD,
    'SECRET': ZONE_SECRET,
    'SETASIDE': ZONE_SETASIDE,
}

CARDTYPE_NAME_MAP = {
    'GAME': CT_GAME,
    'PLAYER': CT_PLAYER,
    'HERO': CT_HERO,
    'MINION': CT_MINION,
    'SPELL': CT_SPELL,
    'ENCHANTMENT': CT_ENCHANTMENT,
    'WEAPON': CT_WEAPON,
    'HERO_POWER': CT_HERO_POWER,
    'LOCATION': CT_LOCATION,
}

# ═══════════════════════════════════════════════════════════════
# CardType → 中文名称
# ═══════════════════════════════════════════════════════════════

CARDTYPE_CN = {
    CT_MINION: "随从",
    CT_SPELL: "法术",
    CT_WEAPON: "武器",
    CT_HERO: "英雄牌",
    CT_LOCATION: "地点",
    CT_HERO_POWER: "英雄技能",
}

# ═══════════════════════════════════════════════════════════════
# CardType → 英文标识（用于 GameState 构建）
# ═══════════════════════════════════════════════════════════════

CARDTYPE_EN = {
    CT_MINION: "MINION",
    CT_SPELL: "SPELL",
    CT_WEAPON: "WEAPON",
    CT_HERO: "HERO",
    CT_ENCHANTMENT: "ENCHANTMENT",
    CT_LOCATION: "LOCATION",
    CT_HERO_POWER: "HERO_POWER",
}

# ═══════════════════════════════════════════════════════════════
# Entity keyword boolean attributes → 中文标签
# ═══════════════════════════════════════════════════════════════

KEYWORD_BOOL_FIELDS = [
    ('taunt', 'TAUNT'),
    ('divine_shield', 'DIVINE_SHIELD'),
    ('charge', 'CHARGE'),
    ('rush', 'RUSH'),
    ('windfury', 'WINDFURY'),
    ('stealth', 'STEALTH'),
    ('poisonous', 'POISONOUS'),
    ('frozen', 'FROZEN'),
    ('reborn', 'REBORN'),
]

KEYWORD_CN_MAP = {
    'taunt': "嘲讽",
    'divine_shield': "圣盾",
    'charge': "冲锋",
    'rush': "突袭",
    'windfury': "风怒",
    'stealth': "潜行",
    'poisonous': "剧毒",
    'frozen': "冻结",
    'reborn': "亡语",
}

# ═══════════════════════════════════════════════════════════════
# TAG_CHANGE handler mapping
# tag_name → (field_label, handler_factory)
# ═══════════════════════════════════════════════════════════════

TAG_CHANGE_HANDLER_KEYS = {
    'RESOURCES', 'RESOURCES_USED', 'MAXRESOURCES',
    'ZONE', 'ZONE_POSITION', 'CONTROLLER', 'CARDTYPE', 'COST',
    'ATK', 'HEALTH', 'ARMOR', 'EXHAUSTED',
    'TAUNT', 'DIVINE_SHIELD', 'CHARGE', 'RUSH', 'WINDFURY',
    'STEALTH', 'POISONOUS', 'LIFESTEAL', 'FROZEN', 'REBORN',
    'IMMUNE', 'SPELL_POWER',
    'FIRST_PLAYER', 'OVERLOAD_OWED',
}

# ═══════════════════════════════════════════════════════════════
# FULL_ENTITY tag → Entity attribute mapping
# ═══════════════════════════════════════════════════════════════

ENTITY_TAG_TO_ATTR = {
    'CONTROLLER': 'controller',
    'ZONE': 'zone',
    'ZONE_POSITION': 'zone_position',
    'CARDTYPE': 'card_type',
    'COST': 'cost',
    'ATK': 'atk',
    'HEALTH': 'health',
    'ARMOR': 'armor',
    'EXHAUSTED': 'exhausted',
    'TAUNT': 'taunt',
    'DIVINE_SHIELD': 'divine_shield',
    'CHARGE': 'charge',
    'RUSH': 'rush',
    'WINDFURY': 'windfury',
    'STEALTH': 'stealth',
    'POISONOUS': 'poisonous',
    'LIFESTEAL': 'lifesteal',
    'FROZEN': 'frozen',
    'REBORN': 'reborn',
    'IMMUNE': 'immune',
    'SPELL_POWER': 'spell_power',
}

# ═══════════════════════════════════════════════════════════════
# Boolean-valued tag set (for type coercion)
# ═══════════════════════════════════════════════════════════════

BOOL_TAG_NAMES = {
    'EXHAUSTED', 'TAUNT', 'DIVINE_SHIELD', 'CHARGE', 'RUSH',
    'WINDFURY', 'STEALTH', 'POISONOUS', 'LIFESTEAL', 'FROZEN',
    'REBORN', 'IMMUNE',
}

# ═══════════════════════════════════════════════════════════════
# Condition holding rules (conditional effect evidence mapping)
# ═══════════════════════════════════════════════════════════════

CONDITIONAL_HOLDING_RULES = {
    "HOLDING_DRAGON": {"race": "DRAGON"},
    "HOLDING_BEAST": {"race": "BEAST"},
    "HOLDING_DEMON": {"race": "DEMON"},
    "HOLDING_MURLOC": {"race": "MURLOC"},
    "HOLDING_ELEMENTAL": {"race": "ELEMENTAL"},
    "HOLDING_MECH": {"race": "MECHANICAL"},
    "HOLDING_PIRATE": {"race": "PIRATE"},
    "HOLDING_SPELL_SCHOOL:FIRE": {"spellSchool": "FIRE"},
    "HOLDING_SPELL_SCHOOL:FROST": {"spellSchool": "FROST"},
    "HOLDING_SPELL_SCHOOL:HOLY": {"spellSchool": "HOLY"},
    "HOLDING_SPELL_SCHOOL:SHADOW": {"spellSchool": "SHADOW"},
    "HOLDING_SPELL_SCHOOL:ARCANE": {"spellSchool": "ARCANE"},
    "HOLDING_SPELL_SCHOOL:NATURE": {"spellSchool": "NATURE"},
    "HOLDING_SPELL_SCHOOL:FEL": {"spellSchool": "FEL"},
}

# ═══════════════════════════════════════════════════════════════
# Race Chinese → English mapping (canonical)
# ═══════════════════════════════════════════════════════════════

RACE_ZH_MAP = {
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

# ═══════════════════════════════════════════════════════════════
# English race normalization (lowercase → uppercase)
# ═══════════════════════════════════════════════════════════════

RACE_EN_NORMALIZE = {
    "dragon": "DRAGON",
    "demon": "DEMON",
    "beast": "BEAST",
    "murloc": "MURLOC",
    "pirate": "PIRATE",
    "elemental": "ELEMENTAL",
    "undead": "UNDEAD",
    "totem": "TOTEM",
    "mechanical": "MECHANICAL",
    "mech": "MECHANICAL",
    "naga": "NAGA",
    "draenei": "DRAENEI",
    "quillboar": "QUILBOAR",
}

# ═══════════════════════════════════════════════════════════════
# Spell School Chinese → English mapping (canonical)
# ═══════════════════════════════════════════════════════════════

SCHOOL_ZH_MAP = {
    "奥术": "ARCANE",
    "邪能": "FEL",
    "火焰": "FIRE",
    "冰霜": "FROST",
    "神圣": "HOLY",
    "自然": "NATURE",
    "暗影": "SHADOW",
}

# ═══════════════════════════════════════════════════════════════
# Coin card IDs (canonical)
# ═══════════════════════════════════════════════════════════════

COIN_CARD_IDS = frozenset({"GAME_005", "TB_BlingBrawl_Coin", "NEW1_008t"})

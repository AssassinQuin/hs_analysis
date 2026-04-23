# -*- coding: utf-8 -*-
"""Hearthstone Power.log 枚举常量与映射表

统一管理所有 GameTag / Zone / CardType / Step 数值常量，
以及 tag 名→Entity属性 的映射关系，供 game_replayer / global_tracker 共用。

数据来源: hearthstone.enums (官方 Python 包)
"""

# ═══════════════════════════════════════════════════════════════
# GameTag numeric values
# ═══════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════
# Zone values
# ═══════════════════════════════════════════════════════════════

ZONE_INVALID = 0
ZONE_PLAY = 1
ZONE_DECK = 2
ZONE_HAND = 3
ZONE_GRAVEYARD = 4
ZONE_SETASIDE = 6
ZONE_SECRET = 7
ZONE_REMOVEDFROMGAME = 8

# ═══════════════════════════════════════════════════════════════
# CardType values
# ═══════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════
# Step values
# ═══════════════════════════════════════════════════════════════

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

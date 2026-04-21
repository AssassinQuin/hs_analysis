# -*- coding: utf-8 -*-
import re


# ═══════════════════════════════════════════════════════════════════
# L2: 关键词层级 (Keyword Tiers)
# ═══════════════════════════════════════════════════════════════════

KEYWORD_TIERS = {
    "power": {
        "BATTLECRY", "DEATHRATTLE", "DISCOVER", "DIVINE_SHIELD", "RUSH",
        "CHARGE", "WINDFURY", "TAUNT", "LIFESTEAL", "STEALTH",
        "CHOOSE_ONE", "QUEST",
        "FORGE", "EXCAVATE", "QUICKDRAW", "TITAN", "ECHO",
    },
    "mechanical": {
        "TRIGGER_VISUAL", "AURA", "COLOSSUS", "REBORN", "IMBUE",
        "OUTCAST", "IMMUNE", "SECRET", "OVERLOAD", "COMBO",
        "SPELLPOWER", "FREEZE", "POISONOUS", "SILENCE",
        "TRADEABLE", "SIDE_QUEST", "START_OF_GAME",
        "SPELLBURST", "FRENZY", "CORRUPT", "DREDGE", "INFUSE",
        "HONORABLE_KILL", "OVERHEAL", "MANATHIRST", "OVERKILL",
        "INSPIRE", "MAGNETIC", "TWINSPELL", "MINIATURIZE", "GIGANTIFY",
        "MORPH", "COUNTER", "VENOMOUS",
    },
}

KEYWORD_CN = {
    "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "TAUNT": "嘲讽",
    "DIVINE_SHIELD": "圣盾", "CHARGE": "冲锋", "RUSH": "突袭",
    "WINDFURY": "风怒", "STEALTH": "潜行", "LIFESTEAL": "吸血",
    "POISONOUS": "剧毒", "VENOMOUS": "剧毒", "FREEZE": "冻结",
    "OVERLOAD": "过载", "SPELLPOWER": "法伤", "SILENCE": "沉默",
    "COMBO": "连击", "DISCOVER": "发现", "SECRET": "奥秘",
    "QUEST": "任务", "SIDE_QUEST": "支线任务", "CHOOSE_ONE": "抉择",
    "ECHO": "回响", "TWINSPELL": "双生", "REBORN": "复生",
    "OUTCAST": "流放", "SPELLBURST": "法术迸发", "FRENZY": "暴怒",
    "CORRUPT": "腐蚀", "TRADEABLE": "可交易", "DREDGE": "掘葬",
    "INFUSE": "充能", "HONORABLE_KILL": "荣誉消灭", "OVERHEAL": "过量治疗",
    "MANATHIRST": "法力渴求", "OVERKILL": "超杀", "INSPIRE": "激励",
    "MAGNETIC": "磁力", "FORGE": "锻造", "QUICKDRAW": "速瞄",
    "EXCAVATE": "挖掘", "COLOSSUS": "巨型", "TITAN": "泰坦",
    "IMBUE": "灌注", "IMMUNE": "免疫", "AURA": "光环",
    "TRIGGER_VISUAL": "触发", "START_OF_GAME": "开局",
    "MINIATURIZE": "迷你化", "GIGANTIFY": "巨大化", "MORPH": "变形",
    "COUNTER": "反制", "ENRAGED": "激怒", "CANT_ATTACK": "无法攻击",
}

TIER_BASES = {"power": 1.5, "mechanical": 0.75, "niche": 0.5}


# ═══════════════════════════════════════════════════════════════════
# L3: 文本效果模式 (Text Effect Patterns)
# ═══════════════════════════════════════════════════════════════════

RACE_NAMES = "龙|恶魔|野兽|鱼人|海盗|元素|亡灵|图腾|机械|纳迦|德莱尼"
SCHOOL_NAMES = "火焰|冰霜|奥术|自然|暗影|神圣|邪能"

EFFECT_PATTERNS = {
    "direct_damage":   (r"造成\s*(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 0.5),
    "random_damage":   (r"随机.*?(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 0.35),
    "draw":            (r"抽\s*(\d+)\s*张牌",                        lambda m: int(m.group(1)) * 1.2),
    "summon_stats":    (r"召唤.*?(\d+)/(\d+)",                       lambda m: (int(m.group(1)) + int(m.group(2))) * 0.3),
    "summon":          (r"召唤",                                     lambda m: 1.5),
    "destroy":         (r"消灭",                                     lambda m: 2.0),
    "aoe_damage":      (r"所有.*?(\d+)\s*点伤害",                    lambda m: int(m.group(1)) * 1.0),
    "heal":            (r"恢复\s*(\d+)\s*点",                        lambda m: int(m.group(1)) * 0.3),
    "armor":           (r"获得\s*(\d+)\s*点护甲",                    lambda m: int(m.group(1)) * 0.4),
    "buff_atk":        (r"\+\s*(\d+)\s*.*?攻击力",                   lambda m: int(m.group(1)) * 0.5),
    "generate":        (r"置入|获取|获得一张",                        lambda m: 1.5),
    "copy":            (r"复制",                                     lambda m: 1.5),
    "mana_reduce":     (r"消耗.*?减少\s*(\d+)",                      lambda m: int(m.group(1)) * 0.6),
    "dark_gift":       (r"黑暗之赐",                                 lambda m: 1.8),
    "reveal":          (r"回溯",                                     lambda m: 1.2),
    "imbue":           (r"灌注",                                     lambda m: 1.0),
    "discard":         (r"弃",                                       lambda m: -1.0),
    "condition":       (r"如果.*?(?:则|就|会)",                      lambda m: -0.3),
    "mana_thirst":     (r"延系",                                     lambda m: 0.8),
    "discover_race":        (r"发现.*?(?:" + RACE_NAMES + ")",       lambda m: 1.0),
    "discover_spell":       (r"发现.*?法术",                          lambda m: 0.5),
    "discover_weapon":      (r"发现.*?武器",                          lambda m: 0.3),
    "discover_minion":      (r"发现.*?随从",                          lambda m: 0.3),
    "discover_spell_school":(r"发现.*?(?:" + SCHOOL_NAMES + ")法术",  lambda m: 0.8),
    "summon_race":          (r"召唤.*?(?:" + RACE_NAMES + ")",        lambda m: 0.3),
    "buff_race":            (r"(?:" + RACE_NAMES + ").*?[+加]",       lambda m: 0.5),
    "forge_effect":         (r"锻造",                                 lambda m: 0.8),
    "excavate_effect":      (r"挖掘",                                 lambda m: 0.7),
}


# ═══════════════════════════════════════════════════════════════════
# L5: 条件期望定义 (Conditional EV)
# ═══════════════════════════════════════════════════════════════════

CONDITION_DEFS = [
    ("dark_gift",          r"黑暗之赐",                                0.6, 1.8),
    ("discover_chain",     r"发现",                                    0.8, 1.2),
    ("quest_progress",     r"任务[:：]",                               0.7, 3.0),
    ("imbue_stacking",     r"灌注",                                    0.5, 2.0),
    ("reveal_burst",       r"回溯",                                    0.6, 1.5),
    ("mana_thirst",        r"延系",                                    0.5, 1.6),
    ("trigger_on_turn",    r"每当|在你的回合|回合结束|回合开始",          0.7, 1.4),
    ("condition_if",       r"如果",                                    0.55, 1.5),
    ("synergy_use_cast",   r"使用一张|施放\d+个|打出",                  0.5, 1.3),
    ("discard_payoff",     r"弃",                                      0.3, 1.0),
    ("cost_reduction",     r"消耗.*减少|每.*减少",                      0.6, 1.4),
    ("copy_effect",        r"复制",                                    0.7, 1.3),
    ("draw_enabler",       r"抽.*牌",                                  0.8, 1.1),
    ("aoe_clear",          r"所有.*(?:伤害|消灭|随从)",                  0.5, 1.5),
    ("buff_aura",          r"获得\+\d+/\+\d+|你的.*\+\d+|获得.*攻击力",  0.6, 1.3),
    ("deathrattle_payoff", r"亡语",                                    0.7, 1.3),
    ("battlecry_strong",   r"战吼[:：]",                               0.9, 1.1),
    ("generate_value",     r"置入|获取|获得一张",                       0.7, 1.3),
    ("destroy_removal",    r"消灭",                                    0.6, 1.4),
    ("heal_sustain",       r"恢复|治疗",                               0.5, 1.1),
    ("armor_gain",         r"护甲",                                    0.5, 1.1),
    ("rush_immediate",     r"突袭",                                    0.8, 1.2),
    ("charge_lethal",      r"冲锋",                                    0.6, 1.3),
    ("taunt_stall",        r"嘲讽",                                    0.7, 1.1),
    ("freeze_control",     r"冻结",                                    0.5, 1.2),
    ("stealth_setup",      r"潜行",                                    0.5, 1.2),
    ("combo_enabler",      r"连击",                                    0.5, 1.3),
    ("secret_bluff",       r"奥秘",                                    0.5, 1.2),
    ("tradeable_cycle",    r"可交易",                                  0.8, 1.1),
    ("condition_race_hand",  r"手牌中有.*?(?:" + RACE_NAMES + ")",     0.4, 1.5),
    ("condition_spell_cast", r"使用一张.*?法术|施放\d+个法术",          0.6, 1.2),
    ("condition_minion_died",r"友方.*?死亡|友方.*?消灭",               0.5, 1.3),
    ("condition_overheal",   r"过量治疗",                              0.4, 1.2),
    ("condition_honorable",  r"荣誉消灭",                              0.4, 1.3),
    ("forge_chain",          r"锻造",                                  0.7, 1.4),
    ("excavate_chain",       r"挖掘",                                  0.6, 1.3),
    ("titan_ability",        r"泰坦",                                  0.8, 1.2),
]


# ═══════════════════════════════════════════════════════════════════
# 职业系数
# ═══════════════════════════════════════════════════════════════════

CLASS_MULTIPLIER = {
    "NEUTRAL": 0.85, "DEMONHUNTER": 0.95, "HUNTER": 0.95,
    "WARRIOR": 0.98, "PALADIN": 1.00, "ROGUE": 1.00, "MAGE": 1.00,
    "DEATHKNIGHT": 1.02, "PRIEST": 1.02, "WARLOCK": 1.02,
    "DRUID": 1.05, "SHAMAN": 1.05,
}


# ═══════════════════════════════════════════════════════════════════
# L2.5: 种族与法术派系协同
# ═══════════════════════════════════════════════════════════════════

RACE_BONUS = {
    "野兽": 1.2, "龙": 1.3, "恶魔": 1.2, "元素": 1.1,
    "亡灵": 1.1, "鱼人": 1.3, "机械": 1.0, "纳迦": 1.1,
    "海盗": 1.2, "图腾": 1.0, "德莱尼": 1.0, "野猪人": 1.0,
}

SPELL_SCHOOL_BONUS = {
    "奥术": 1.0, "邪能": 1.0, "火焰": 1.0, "冰霜": 1.0,
    "神圣": 1.0, "自然": 1.1, "暗影": 1.0,
}

RUNE_TYPES = {"血", "冰", "邪"}

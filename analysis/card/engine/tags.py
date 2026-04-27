"""定义 GameTag 枚举和机制映射表，作为卡牌属性的唯一真相源。
参考 SabberStone (C#) 的 Tag-Driven 模型，所有实体属性统一为 Dict[GameTag, int]。
"""

from __future__ import annotations

from enum import IntEnum
from typing import Dict, Iterable, List


# ═══════════════════════════════════════════════════════════════
# GameTag 枚举
# ═══════════════════════════════════════════════════════════════

class GameTag(IntEnum):
    """卡牌属性标签枚举。

    数值采用官方 Hearthstone GameTag ID（与 hs_enums.py 一致），
    新增本项目自定义的 tag 从 10000 开始。
    """

    # --- 基础属性 ---
    COST = 54
    ATK = 47
    HEALTH = 71
    ARMOR = 292
    DURABILITY = 720

    # --- 关键字（布尔型，0/1）---
    TAUNT = 238
    CHARGE = 188
    RUSH = 187
    DIVINE_SHIELD = 191
    WINDFURY = 189
    MEGA_WINDFURY = 10001
    STEALTH = 225
    POISONOUS = 237
    LIFESTEAL = 2145
    REBORN = 2185
    IMMUNE = 477
    FROZEN = 260
    ELUSIVE = 10002          # 魔爆：不能成为法术或英雄技能目标
    CANT_ATTACK = 10003      # 不能攻击（如看门人）
    WARD = 10004             # 护盾（可被攻击次数+1）

    # --- 机制触发器（布尔型）---
    BATTLECRY = 10010
    DEATHRATTLE = 10011
    INSPIRE = 10012
    COMBO = 10013
    SECRET = 10014
    OVERLOAD = 10015
    SPELL_BURST = 10016      # 法术迸发
    FRENZY = 10017           # 暴怒
    OUTCAST = 10018          # 流放
    CORRUPT = 10019          # 堕落
    INVOKE = 10020           # 祈求
    MAGNETIC = 10021         # 磁力
    QUEST = 10022            # 任务
    DORMANT = 10023          # 休眠

    # --- 数值型属性 ---
    SPELL_POWER = 215
    OVERLOAD_OWED = 394

    # --- 状态标记 ---
    EXHAUSTED = 424          # 已行动完毕
    ENRAGED = 10030          # 激怒状态

    # --- 其他 ---
    COLLECTIBLE = 10040
    ELITE = 10041            # 传说标记
    FORGETFUL = 10042        # 忘记（可能攻击错误目标）


# ═══════════════════════════════════════════════════════════════
# HearthstoneJSON mechanics → GameTag 映射
# ═══════════════════════════════════════════════════════════════

MECHANIC_TO_TAG: Dict[str, GameTag] = {
    # 关键字
    "TAUNT": GameTag.TAUNT,
    "CHARGE": GameTag.CHARGE,
    "RUSH": GameTag.RUSH,
    "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
    "WINDFURY": GameTag.WINDFURY,
    "STEALTH": GameTag.STEALTH,
    "POISONOUS": GameTag.POISONOUS,
    "LIFESTEAL": GameTag.LIFESTEAL,
    "REBORN": GameTag.REBORN,
    "IMMUNE": GameTag.IMMUNE,
    "FROZEN": GameTag.FROZEN,
    "ELUSIVE": GameTag.ELUSIVE,        #_spellShatter / can't be targeted

    # 机制触发器
    "BATTLECRY": GameTag.BATTLECRY,
    "DEATHRATTLE": GameTag.DEATHRATTLE,
    "INSPIRE": GameTag.INSPIRE,
    "COMBO": GameTag.COMBO,
    "SECRET": GameTag.SECRET,
    "OVERLOAD": GameTag.OVERLOAD,
    "SPELLBURST": GameTag.SPELL_BURST,
    "FRENZY": GameTag.FRENZY,
    "OUTCAST": GameTag.OUTCAST,
    "CORRUPT": GameTag.CORRUPT,
    "INVOKE": GameTag.INVOKE,
    "MAGNETIC": GameTag.MAGNETIC,
    "QUEST": GameTag.QUEST,
    "DORMANT": GameTag.DORMANT,
    "FORGETFUL": GameTag.FORGETFUL,
}

# 反向映射：GameTag → mechanics 字符串（用于序列化/调试）
TAG_TO_MECHANIC: Dict[GameTag, str] = {v: k for k, v in MECHANIC_TO_TAG.items()}

# 布尔型 GameTag 集合（值为 0 或 1）
BOOL_TAGS: frozenset[GameTag] = frozenset({
    GameTag.TAUNT, GameTag.CHARGE, GameTag.RUSH,
    GameTag.DIVINE_SHIELD, GameTag.WINDFURY, GameTag.MEGA_WINDFURY,
    GameTag.STEALTH, GameTag.POISONOUS, GameTag.LIFESTEAL,
    GameTag.REBORN, GameTag.IMMUNE, GameTag.FROZEN,
    GameTag.ELUSIVE, GameTag.CANT_ATTACK, GameTag.WARD,
    GameTag.BATTLECRY, GameTag.DEATHRATTLE, GameTag.INSPIRE,
    GameTag.COMBO, GameTag.SECRET, GameTag.OVERLOAD,
    GameTag.SPELL_BURST, GameTag.FRENZY, GameTag.OUTCAST,
    GameTag.CORRUPT, GameTag.INVOKE, GameTag.MAGNETIC,
    GameTag.QUEST, GameTag.DORMANT, GameTag.ENRAGED,
    GameTag.EXHAUSTED, GameTag.COLLECTIBLE, GameTag.ELITE,
})


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def mechanics_to_tags(mechanics: Iterable[str]) -> Dict[GameTag, int]:
    """将 HearthstoneJSON mechanics 列表转换为 tags 字典。

    Args:
        mechanics: 机制字符串列表，如 ["TAUNT", "RUSH", "BATTLECRY"]

    Returns:
        tags 字典，如 {GameTag.TAUNT: 1, GameTag.RUSH: 1, GameTag.BATTLECRY: 1}
    """
    tags: Dict[GameTag, int] = {}
    for m in mechanics:
        tag = MECHANIC_TO_TAG.get(m)
        if tag is not None:
            tags[tag] = 1
    return tags


def has_tag(tags: Dict[GameTag, int], tag: GameTag) -> bool:
    """检查 tags 字典中某标签是否激活（值 > 0）。"""
    return tags.get(tag, 0) > 0


def get_tag(tags: Dict[GameTag, int], tag: GameTag, default: int = 0) -> int:
    """获取 tags 字典中的标签值。"""
    return tags.get(tag, default)


def set_tag(tags: Dict[GameTag, int], tag: GameTag, value: int = 1) -> None:
    """设置 tags 字典中的标签值。"""
    tags[tag] = value


def remove_tag(tags: Dict[GameTag, int], tag: GameTag) -> None:
    """移除 tags 字典中的标签（设为 0 或删除）。"""
    tags.pop(tag, None)


def silence_tags(tags: Dict[GameTag, int]) -> Dict[GameTag, int]:
    """沉默效果：清除所有关键字和机制标签，仅保留基础属性。

    Args:
        tags: 原 tags 字典

    Returns:
        清除关键字后的新 tags 字典
    """
    # 保留的基础属性
    keep = {GameTag.COST, GameTag.ATK, GameTag.HEALTH,
            GameTag.ARMOR, GameTag.DURABILITY, GameTag.SPELL_POWER}
    return {k: v for k, v in tags.items() if k in keep}


def tags_to_display(tags: Dict[GameTag, int]) -> List[str]:
    """将 tags 字典转换为可读标签列表（用于调试和显示）。"""
    result = []
    for tag, value in sorted(tags.items(), key=lambda x: x[0].value):
        if value > 0:
            name = TAG_TO_MECHANIC.get(tag, tag.name)
            if value == 1:
                result.append(name)
            else:
                result.append(f"{name}={value}")
    return result

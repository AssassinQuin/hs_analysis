#!/usr/bin/env python3
"""generator.py — 从 CardDB 数据自动生成 card_abilities.json 骨架。

> **本文件功能**: 从 CardDB 数据自动生成 card_abilities.json 骨架。解析 mechanics 字段推断基本能力
> （BATTLECRY/DEATHRATTLE/DISCOVER 等），生成 MetaStone 风格的 JSON 定义。

生成逻辑:
  1. 纯关键字随从 → 空 abilities（由 Tag 系统处理）
  2. 有 BATTLECRY + 简单效果 → 半自动推断 Spell 类
  3. 有 DEATHRATTLE → 同理解析
  4. 法术牌 → 解析 text 推断 Spell 类
  5. 复杂效果 → TODO 标记 + text_raw 保留原文

用法::

    python -m analysis.card.abilities.generator                  # 生成到默认路径
    python -m analysis.card.abilities.generator --output /path   # 指定输出路径
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

# ── 默认输出路径 ──────────────────────────────────────────────
_DEFAULT_OUTPUT = PROJECT_ROOT / "analysis" / "card" / "data" / "card_abilities.json"

# ── 需要生成 abilities 的 mechanics 关键字 ────────────────────
_TRIGGER_MECHANICS = {
    "BATTLECRY",
    "DEATHRATTLE",
    "DISCOVER",
    "COMBO",
    "SPELLBURST",
    "INSPIRE",
    "OVERLOAD",
    "SECRET",
    "QUEST",
    "OUTCAST",
    "FRENZY",
    "FINALE",
}

# ── 纯关键字 mechanics（由 Tag 系统处理，不需要 abilities） ──
_TAG_ONLY_MECHANICS = {
    "TAUNT",
    "RUSH",
    "CHARGE",
    "DIVINE_SHIELD",
    "WINDFURY",
    "STEALTH",
    "POISONOUS",
    "LIFESTEAL",
    "REBORN",
    "SPELL_DAMAGE",
    "IMMUNE",
    "MEGA_WINDFURY",
    "ELUSIVE",
    "CANT_BE_TARGETED_BY_SPELLS",
    "CANT_BE_TARGETED_BY_HERO_POWERS",
    "FREEZE",
    "INFERNAL",
}

# ── 中文文本匹配模式 ──────────────────────────────────────────

# "造成{n}点伤害"
_RE_DAMAGE = re.compile(r"造成(\d+)点伤害")
# "恢复{n}点生命值" 或 "恢复#{n}点生命值" (法力值引用)
_RE_HEAL = re.compile(r"恢复(\d+)点生命值")
# "召唤{n}个" 或 "召唤" + 卡牌名
_RE_SUMMON = re.compile(r"召唤(\d+)个(.+?)(?:。|$)")
_RE_SUMMON_SIMPLE = re.compile(r"召唤(.+?)(?:。|$)")
# "抽{n}张牌"
_RE_DRAW = re.compile(r"抽(\d+)张牌")
# "获得{n}点护甲"
_RE_ARMOR = re.compile(r"获得(\d+)点护甲")
# "发现"
_RE_DISCOVER = re.compile(r"发现")
# "+{n}/+{n}" 或 "+{n}攻击力" 等
_RE_BUFF = re.compile(r"\+(\d+)/\+(\d+)")
_RE_BUFF_ATK = re.compile(r"\+(\d+)攻击力")
_RE_BUFF_HP = re.compile(r"\+(\d+)生命值")
# "摧毁" 随从
_RE_DESTROY = re.compile(r"摧毁")
# "沉默"
_RE_SILENCE = re.compile(r"沉默")
# "冻结"
_RE_FREEZE = re.compile(r"冻结(.+?)(?:。|$)")
# "变形"
_RE_TRANSFORM = re.compile(r"变形为(.+?)(?:。|$)")
# "复制"
_RE_COPY = re.compile(r"复制")
# "获得控制权"
_RE_TAKE_CONTROL = re.compile(r"获得控制权")
# "洗入"
_RE_SHUFFLE = re.compile(r"洗入(.+?)(?:。|$)")
# "装备"
_RE_EQUIP_WEAPON = re.compile(r"装备(.+?)(?:。|$)")
# "获得法力值"
_RE_MANA = re.compile(r"获得(\d+)个法力水晶")
# "弃牌"
_RE_DISCARD = re.compile(r"弃(\d+)张牌")
# "返回手牌"
_RE_RETURN = re.compile(r"返回手牌")


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _extract_number(text: str) -> Optional[int]:
    """从文本中提取第一个数字。

    参数:
        text: 包含数字的文本
    返回:
        找到的第一个整数，未找到返回 None
    """
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _is_tag_only(mechanics: List[str]) -> bool:
    """判断卡牌是否仅包含纯关键字 mechanics（不需要 abilities）。

    参数:
        mechanics: 卡牌的 mechanics 列表
    返回:
        如果所有 mechanics 都是纯关键字，返回 True
    """
    for m in mechanics:
        if m not in _TAG_ONLY_MECHANICS:
            return False
    return True


def _has_trigger_mechanic(mechanics: List[str]) -> bool:
    """判断卡牌是否有触发类 mechanic（需要生成 abilities）。

    参数:
        mechanics: 卡牌的 mechanics 列表
    返回:
        如果有触发类 mechanic，返回 True
    """
    return any(m in _TRIGGER_MECHANICS for m in mechanics)


def _make_todo(text: str) -> dict:
    """创建 TODO 标记条目。

    参数:
        text: 原始卡牌描述文本
    返回:
        包含 TODO 标记和原始文本的字典
    """
    return {"class": "TODO", "text_raw": text}


def _parse_simple_battlecry(text: str) -> List[dict]:
    """解析简单战吼文本，推断 Spell 类。

    参数:
        text: 卡牌描述文本
    返回:
        推断出的 Spell action 列表
    """
    actions: List[dict] = []
    remaining = text

    # 发现
    if _RE_DISCOVER.search(remaining):
        actions.append({"class": "DiscoverSpell"})
        return actions  # 发现通常独占效果

    # 造成伤害
    m = _RE_DAMAGE.search(remaining)
    if m:
        value = int(m.group(1))
        # 判断目标类型
        target = _infer_damage_target(remaining)
        actions.append({"class": "DamageSpell", "value": value, "target": target})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 治疗效果
    m = _RE_HEAL.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "HealSpell", "value": value, "target": "FRIENDLY_HERO"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 抽牌
    m = _RE_DRAW.search(remaining)
    if m:
        count = int(m.group(1))
        actions.append({"class": "DrawSpell", "count": count})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 获得护甲
    m = _RE_ARMOR.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ArmorSpell", "value": value})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 增益效果
    m = _RE_BUFF.search(remaining)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack": atk, "health": hp, "target": "SELF"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 召唤
    m = _RE_SUMMON.search(remaining)
    if m:
        count = int(m.group(1))
        card_name = m.group(2).strip()
        actions.append({"class": "SummonSpell", "_count": count, "_card_name": card_name})
        remaining = remaining[:m.start()] + remaining[m.end():]
    else:
        m = _RE_SUMMON_SIMPLE.search(remaining)
        if m:
            card_name = m.group(1).strip()
            actions.append({"class": "SummonSpell", "_card_name": card_name})
            remaining = remaining[:m.start()] + remaining[m.end():]

    # 摧毁
    if _RE_DESTROY.search(remaining):
        actions.append({"class": "DestroySpell", "target": "TARGET"})

    # 沉默
    if _RE_SILENCE.search(remaining):
        actions.append({"class": "SilenceSpell", "target": "TARGET"})

    # 冻结
    m = _RE_FREEZE.search(remaining)
    if m:
        actions.append({"class": "FreezeSpell", "target": "TARGET"})

    # 变形
    m = _RE_TRANSFORM.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "TransformSpell", "_card_name": card_name})

    # 复制
    if _RE_COPY.search(remaining):
        actions.append({"class": "CopySpell", "target": "TARGET"})

    # 获得控制权
    if _RE_TAKE_CONTROL.search(remaining):
        actions.append({"class": "TakeControlSpell", "target": "TARGET"})

    # 洗入牌库
    m = _RE_SHUFFLE.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "ShuffleSpell", "_card_name": card_name})

    # 装备武器
    m = _RE_EQUIP_WEAPON.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "WeaponEquipSpell", "_card_name": card_name})

    # 获得法力水晶
    m = _RE_MANA.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ManaSpell", "value": value})

    # 弃牌
    m = _RE_DISCARD.search(remaining)
    if m:
        count = int(m.group(1))
        actions.append({"class": "DiscardSpell", "count": count})

    # 返回手牌
    if _RE_RETURN.search(remaining):
        actions.append({"class": "ReturnSpell", "target": "TARGET"})

    # 如果没有推断出任何 action，标记 TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_simple_deathrattle(text: str) -> List[dict]:
    """解析简单亡语文本，推断 Spell 类。

    参数:
        text: 卡牌描述文本
    返回:
        推断出的 Spell action 列表
    """
    actions: List[dict] = []

    # 召唤（亡语最常见）
    m = _RE_SUMMON.search(text)
    if m:
        count = int(m.group(1))
        card_name = m.group(2).strip()
        actions.append({"class": "SummonSpell", "_count": count, "_card_name": card_name})
        return actions

    m = _RE_SUMMON_SIMPLE.search(text)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "SummonSpell", "_card_name": card_name})
        return actions

    # 造成伤害（亡语随机目标）
    m = _RE_DAMAGE.search(text)
    if m:
        value = int(m.group(1))
        actions.append({"class": "DamageSpell", "value": value, "target": "RANDOM_ENEMY_CHARACTER"})

    # 抽牌
    m = _RE_DRAW.search(text)
    if m:
        count = int(m.group(1))
        actions.append({"class": "DrawSpell", "count": count})

    # 如果没有推断出任何 action，标记 TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_spell_text(text: str) -> List[dict]:
    """解析法术牌文本，推断 Spell 类。

    参数:
        text: 法术牌描述文本
    返回:
        推断出的 Spell action 列表
    """
    actions: List[dict] = []
    remaining = text

    # 造成伤害
    m = _RE_DAMAGE.search(remaining)
    if m:
        value = int(m.group(1))
        target = _infer_damage_target(remaining)
        actions.append({"class": "DamageSpell", "value": value, "target": target})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 治疗效果
    m = _RE_HEAL.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "HealSpell", "value": value, "target": "FRIENDLY_HERO"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 抽牌
    m = _RE_DRAW.search(remaining)
    if m:
        count = int(m.group(1))
        actions.append({"class": "DrawSpell", "count": count})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 获得护甲
    m = _RE_ARMOR.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ArmorSpell", "value": value})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 增益效果
    m = _RE_BUFF.search(remaining)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack": atk, "health": hp, "target": "TARGET"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 召唤
    m = _RE_SUMMON.search(remaining)
    if m:
        count = int(m.group(1))
        card_name = m.group(2).strip()
        actions.append({"class": "SummonSpell", "_count": count, "_card_name": card_name})
        remaining = remaining[:m.start()] + remaining[m.end():]
    else:
        m = _RE_SUMMON_SIMPLE.search(remaining)
        if m:
            card_name = m.group(1).strip()
            actions.append({"class": "SummonSpell", "_card_name": card_name})
            remaining = remaining[:m.start()] + remaining[m.end():]

    # 发现
    if _RE_DISCOVER.search(remaining):
        actions.append({"class": "DiscoverSpell"})
        remaining = _RE_DISCOVER.sub("", remaining)

    # 摧毁
    if _RE_DESTROY.search(remaining):
        actions.append({"class": "DestroySpell", "target": "TARGET"})

    # 沉默
    if _RE_SILENCE.search(remaining):
        actions.append({"class": "SilenceSpell", "target": "TARGET"})

    # 冻结
    m = _RE_FREEZE.search(remaining)
    if m:
        actions.append({"class": "FreezeSpell", "target": "TARGET"})

    # 变形
    m = _RE_TRANSFORM.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "TransformSpell", "_card_name": card_name})

    # 复制
    if _RE_COPY.search(remaining):
        actions.append({"class": "CopySpell", "target": "TARGET"})

    # 获得控制权
    if _RE_TAKE_CONTROL.search(remaining):
        actions.append({"class": "TakeControlSpell", "target": "TARGET"})

    # 获得法力水晶
    m = _RE_MANA.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ManaSpell", "value": value})

    # 弃牌
    m = _RE_DISCARD.search(remaining)
    if m:
        count = int(m.group(1))
        actions.append({"class": "DiscardSpell", "count": count})

    # 返回手牌
    if _RE_RETURN.search(remaining):
        actions.append({"class": "ReturnSpell", "target": "TARGET"})

    # 如果没有推断出任何 action，标记 TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _infer_damage_target(text: str) -> str:
    """从文本推断伤害目标类型。

    参数:
        text: 卡牌描述文本
    返回:
        目标选择器字符串
    """
    text_lower = text.lower()
    if "所有" in text and ("敌人" in text or "敌方" in text):
        return "ALL_ENEMY_CHARACTERS"
    if "所有" in text and ("随从" in text):
        return "ALL_MINIONS"
    if "随机" in text and ("敌人" in text or "敌方" in text):
        return "RANDOM_ENEMY_CHARACTER"
    if "随机" in text:
        return "RANDOM_ENEMY_MINION"
    if "敌人" in text or "敌方" in text:
        return "ENEMY_MINION"
    # 默认：需要目标选择
    return "TARGET"


def _validate_spell_class(class_name: str) -> bool:
    """验证 Spell 类名是否在注册表中合法。

    参数:
        class_name: 要验证的类名
    返回:
        如果类名合法返回 True
    """
    if class_name == "TODO":
        return True
    # 延迟导入避免循环依赖
    try:
        from analysis.card.abilities.spells import SPELL_REGISTRY
        return class_name in SPELL_REGISTRY
    except ImportError:
        return True  # 无法验证时放行


# ═══════════════════════════════════════════════════════════════
# 主生成逻辑
# ═══════════════════════════════════════════════════════════════

def generate_abilities_json(output_path: Optional[str] = None) -> dict:
    """从 CardDB 数据自动生成 card_abilities.json 骨架。

    解析 mechanics 字段推断基本能力（BATTLECRY/DEATHRATTLE/DISCOVER 等），
    生成 MetaStone 风格的 JSON 定义。

    参数:
        output_path: 输出文件路径。为 None 时不写入文件，仅返回 dict。
    返回:
        生成的完整 dict 数据结构
    """
    from analysis.card.data.card_data import get_db

    db = get_db()
    cards = db.get_collectible_cards(fmt="standard")

    result: Dict[str, Any] = {"version": 1, "cards": {}}

    stats = {
        "total": 0,
        "tag_only": 0,
        "inferred": 0,
        "todo": 0,
        "spell": 0,
    }

    for card in cards:
        card_id = card.get("cardId", card.get("id", ""))
        name = card.get("name", "")
        card_type = card.get("type", "")
        mechanics = card.get("mechanics", [])
        text = card.get("text", "")

        if not card_id or not name:
            continue

        stats["total"] += 1

        # ── 法术牌 ──
        if card_type == "SPELL":
            if not text:
                continue
            actions = _parse_spell_text(text)
            result["cards"][card_id] = {
                "name": name,
                "abilities": [{"actions": actions}],
            }
            if any(a.get("class") == "TODO" for a in actions):
                stats["todo"] += 1
            else:
                stats["inferred"] += 1
                stats["spell"] += 1
            continue

        # ── 武器牌 ──
        if card_type == "WEAPON":
            # 武器一般没有需要 abilities 系统处理的文本
            continue

        # ── 随从牌 ──
        if card_type != "MINION":
            continue

        # 纯关键字随从 → 空 abilities（由 Tag 系统处理）
        if not mechanics or _is_tag_only(mechanics):
            stats["tag_only"] += 1
            continue

        # 没有 text 的触发 mechanic 卡牌
        if not text and _has_trigger_mechanic(mechanics):
            result["cards"][card_id] = {
                "name": name,
                "abilities": [{"trigger": mechanics[0], "actions": [_make_todo("")]}],
            }
            stats["todo"] += 1
            continue

        # 有触发 mechanic + 文本的随从
        abilities = []
        for mechanic in mechanics:
            if mechanic not in _TRIGGER_MECHANICS:
                continue

            if mechanic == "BATTLECRY":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "BATTLECRY", "actions": actions})
            elif mechanic == "DEATHRATTLE":
                actions = _parse_simple_deathrattle(text)
                abilities.append({"trigger": "DEATHRATTLE", "actions": actions})
            elif mechanic == "DISCOVER":
                abilities.append({"trigger": "DISCOVER", "actions": [{"class": "DiscoverSpell"}]})
            elif mechanic == "COMBO":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "COMBO", "actions": actions})
            elif mechanic == "SPELLBURST":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "SPELLBURST", "actions": actions})
            elif mechanic == "INSPIRE":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "INSPIRE", "actions": actions})
            elif mechanic == "FRENZY":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "FRENZY", "actions": actions})
            elif mechanic == "FINALE":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "FINALE", "actions": actions})
            else:
                # 其他触发器标记 TODO
                abilities.append({
                    "trigger": mechanic,
                    "actions": [_make_todo(text)],
                })

        if abilities:
            result["cards"][card_id] = {
                "name": name,
                "abilities": abilities,
            }
            # 判断是否有 TODO
            has_todo = any(
                a.get("class") == "TODO"
                for ab in abilities
                for a in ab.get("actions", [])
            )
            if has_todo:
                stats["todo"] += 1
            else:
                stats["inferred"] += 1

    # ── 写入文件 ──
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("已写入 %s", out)

    # ── 统计信息 ──
    log.info(
        "生成完成: 总计 %d 张卡, 纯关键字 %d, 推断成功 %d, TODO %d, 法术 %d",
        stats["total"],
        stats["tag_only"],
        stats["inferred"],
        stats["todo"],
        stats["spell"],
    )

    return result


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="从 CardDB 生成 card_abilities.json 骨架")
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help=f"输出文件路径（默认: {_DEFAULT_OUTPUT}）",
    )
    args = parser.parse_args()

    output = args.output or str(_DEFAULT_OUTPUT)
    generate_abilities_json(output_path=output)

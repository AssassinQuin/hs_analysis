#!/usr/bin/env python3
"""generator.py — 已弃用，请使用 generator_v2.py。

> ⚠️ DEPRECATED (Phase 3): 旧版 v1 生成器，输出 card_abilities.json。
> 新版 generator_v2.py 输出 card_abilities_v2.json (递归 SpellDesc)。

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
    "BATTLECRY", "DEATHRATTLE", "DISCOVER", "COMBO",
    "SPELLBURST", "INSPIRE", "OVERLOAD", "SECRET",
    "QUEST", "OUTCAST", "FRENZY", "FINALE",
}

# ── Mechanic → handler 注册表 ─────────────────────────────────
# handler(text) -> List[dict] | None  (None=skip this mechanic)
# most trigger types share _parse_simple_battlecry
_MECHANIC_HANDLERS: Dict[str, Any] = {
    "BATTLECRY":    ("BATTLECRY", _parse_simple_battlecry),
    "DEATHRATTLE":  ("DEATHRATTLE", _parse_simple_deathrattle),
    "COMBO":        ("COMBO", _parse_simple_battlecry),
    "SPELLBURST":   ("SPELLBURST", _parse_simple_battlecry),
    "INSPIRE":      ("INSPIRE", _parse_simple_battlecry),
    "FRENZY":       ("FRENZY", _parse_simple_battlecry),
    "FINALE":       ("FINALE", _parse_simple_battlecry),
    "OUTCAST":      ("OUTCAST", _parse_simple_battlecry),
    "DISCOVER":     ("DISCOVER", lambda t: [{"class": "DiscoverSpell"}]),
    "OVERLOAD":     None,   # cost modifier, not an effect
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

# ── 文本清理工具 ─────────────────────────────────────────────
_RE_HTML = re.compile(r"</?[a-zA-Z]+>")
_RE_X_PREFIX = re.compile(r"\[x\]")


def _clean(text: str) -> str:
    """移除 HTML 标签、[x] 前缀、多余空白后返回纯文本。"""
    t = _RE_HTML.sub("", text)
    t = _RE_X_PREFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


# ── 英文文本匹配模式 ──────────────────────────────────────────

# "Deal [$#]N damage" — $ for spellpower-scalable, # for fixed
_RE_DAMAGE = re.compile(r"[Dd]eal\s*[\$#]?\s*(\d+)\s+damage")
# "Restore [$#]N Health"
_RE_HEAL = re.compile(r"[Rr]estore\s*[\$#]?\s*(\d+)\s+[Hh]ealth")
# "Draw N card(s)" or "Draw a card"
_RE_DRAW = re.compile(r"[Dd]raw\s+(\d+|a|an)\s*(?:cards?|copies?)?")
# "Gain [$#]N Armor"
_RE_ARMOR = re.compile(r"[Gg]ain\s*[\$#]?\s*(\d+)\s+[Aa]rmor")
# "Summon a N/N minion" or "Summon two 2/2 Treants" — simple suffix match
_RE_SUMMON = re.compile(r"[Ss]ummon\s+(\d+|a|an|two|three)?\s*(.+?)?(?:\.|$)")
_RE_SUMMON_SIMPLE = re.compile(r"[Ss]ummon\s+(?:a|an)?\s*(.+?)(?:\.|$)")
# "Discover"
_RE_DISCOVER = re.compile(r"[Dd]iscover")
# "+N/+N"
_RE_BUFF = re.compile(r"\+(\d+)/\+(\d+)")
# "Destroy"
_RE_DESTROY = re.compile(r"[Dd]estroy")
# "Silence"
_RE_SILENCE = re.compile(r"[Ss]ilence")
# "Freeze"
_RE_FREEZE = re.compile(r"[Ff]reeze")
# "Transform"
_RE_TRANSFORM = re.compile(r"[Tt]ransform\s(?:into\s)?(.+?)(?:\.|$)")
# "Copy"
_RE_COPY = re.compile(r"[Cc]opy")
# "Take control"
_RE_TAKE_CONTROL = re.compile(r"[Tt]ake\s+control")
# "Shuffle into"
_RE_SHUFFLE = re.compile(r"[Ss]huffle\s+(.+?)\s+into")
# "Equip a weapon"
_RE_EQUIP_WEAPON = re.compile(r"[Ee]quip")
# "Gain N Mana Crystal"
_RE_MANA = re.compile(r"[Gg]ain\s*(?:\w+\s+)*?(\d+)\s+Mana")
# "Discard N" or "Discard a"
_RE_DISCARD = re.compile(r"[Dd]iscard\s+(\d+|a|an)")
# "Return to hand"
_RE_RETURN = re.compile(r"[Rr]eturn\s+(?:to\s+\w+\s+)?hand")


# ═══════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════

def _en_int(sval: str) -> int:
    """将英文字符串转整数：数字字符串直接解析，"a"/"an" = 1，否则 0。"""
    if sval.isdigit():
        return int(sval)
    if sval.lower() in ("a", "an"):
        return 1
    return 0


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
    """Parse simple battlecry text, infer Spell classes.

    Uses English text from card DB with English regex patterns.
    """
    actions: List[dict] = []
    remaining = _clean(text)

    # Discover (usually exclusive)
    if _RE_DISCOVER.search(remaining):
        actions.append({"class": "DiscoverSpell"})
        return actions

    # Deal damage
    m = _RE_DAMAGE.search(remaining)
    if m:
        value = int(m.group(1))
        target = _infer_damage_target(remaining)
        actions.append({"class": "DamageSpell", "value": value, "target": target})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Heal
    m = _RE_HEAL.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "HealSpell", "value": value, "target": "FRIENDLY_HERO"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Draw
    m = _RE_DRAW.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DrawSpell", "count": count})
            remaining = remaining[:m.start()] + remaining[m.end():]

    # Gain Armor
    m = _RE_ARMOR.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ArmorSpell", "value": value})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Buff +N/+N
    m = _RE_BUFF.search(remaining)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack": atk, "health": hp, "target": "SELF"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Destroy
    if _RE_DESTROY.search(remaining):
        actions.append({"class": "DestroySpell", "target": "TARGET"})

    # Silence
    if _RE_SILENCE.search(remaining):
        actions.append({"class": "SilenceSpell", "target": "TARGET"})

    # Freeze
    if _RE_FREEZE.search(remaining):
        actions.append({"class": "FreezeSpell", "target": "TARGET"})

    # Transform
    m = _RE_TRANSFORM.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "TransformSpell", "_card_name": card_name})

    # Copy
    if _RE_COPY.search(remaining):
        actions.append({"class": "CopySpell", "target": "TARGET"})

    # Take control
    if _RE_TAKE_CONTROL.search(remaining):
        actions.append({"class": "TakeControlSpell", "target": "TARGET"})

    # Summon
    if _RE_SUMMON.search(remaining):
        actions.append({"class": "SummonSpell"})

    # Shuffle into deck
    m = _RE_SHUFFLE.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "ShuffleSpell", "_card_name": card_name})

    # Equip weapon
    if _RE_EQUIP_WEAPON.search(remaining):
        actions.append({"class": "WeaponEquipSpell"})

    # Gain Mana Crystal
    m = _RE_MANA.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ManaSpell", "value": value})

    # Discard
    m = _RE_DISCARD.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DiscardSpell", "count": count})

    # Return to hand
    if _RE_RETURN.search(remaining):
        actions.append({"class": "ReturnSpell", "target": "TARGET"})

    # Fallback: no action inferred → TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_simple_deathrattle(text: str) -> List[dict]:
    """Parse simple deathrattle text, infer Spell classes.

    Uses English text with English regex patterns.
    """
    actions: List[dict] = []
    text = _clean(text)

    # Deal damage (deathrattle defaults to random enemy target)
    m = _RE_DAMAGE.search(text)
    if m:
        value = int(m.group(1))
        actions.append({"class": "DamageSpell", "value": value, "target": "RANDOM_ENEMY_CHARACTER"})

    # Draw
    m = _RE_DRAW.search(text)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DrawSpell", "count": count})

    # Summon (common deathrattle)
    if _RE_SUMMON.search(text):
        actions.append({"class": "SummonSpell"})

    # +N/+N buff
    m = _RE_BUFF.search(text)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack": atk, "health": hp, "target": "SELF"})

    # Fallback: no action inferred → TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_spell_text(text: str) -> List[dict]:
    """Parse spell card text, infer Spell classes.

    Uses English text with English regex patterns.
    """
    actions: List[dict] = []
    remaining = _clean(text)

    # Deal damage
    m = _RE_DAMAGE.search(remaining)
    if m:
        value = int(m.group(1))
        target = _infer_damage_target(remaining)
        actions.append({"class": "DamageSpell", "value": value, "target": target})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Heal
    m = _RE_HEAL.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "HealSpell", "value": value, "target": "FRIENDLY_HERO"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Draw
    m = _RE_DRAW.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DrawSpell", "count": count})
            remaining = remaining[:m.start()] + remaining[m.end():]

    # Gain Armor
    m = _RE_ARMOR.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ArmorSpell", "value": value})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Buff +N/+N
    m = _RE_BUFF.search(remaining)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack": atk, "health": hp, "target": "TARGET"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    # Discover
    if _RE_DISCOVER.search(remaining):
        actions.append({"class": "DiscoverSpell"})
        remaining = _RE_DISCOVER.sub("", remaining)

    # Destroy
    if _RE_DESTROY.search(remaining):
        actions.append({"class": "DestroySpell", "target": "TARGET"})

    # Silence
    if _RE_SILENCE.search(remaining):
        actions.append({"class": "SilenceSpell", "target": "TARGET"})

    # Freeze
    if _RE_FREEZE.search(remaining):
        actions.append({"class": "FreezeSpell", "target": "TARGET"})

    # Transform
    m = _RE_TRANSFORM.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "TransformSpell", "_card_name": card_name})

    # Copy
    if _RE_COPY.search(remaining):
        actions.append({"class": "CopySpell", "target": "TARGET"})

    # Take control
    if _RE_TAKE_CONTROL.search(remaining):
        actions.append({"class": "TakeControlSpell", "target": "TARGET"})

    # Summon
    if _RE_SUMMON.search(remaining):
        actions.append({"class": "SummonSpell"})

    # Gain Mana Crystal
    m = _RE_MANA.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ManaSpell", "value": value})

    # Discard
    m = _RE_DISCARD.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DiscardSpell", "count": count})

    # Return to hand
    if _RE_RETURN.search(remaining):
        actions.append({"class": "ReturnSpell", "target": "TARGET"})

    # Shuffle into deck
    m = _RE_SHUFFLE.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "ShuffleSpell", "_card_name": card_name})

    # Equip weapon
    if _RE_EQUIP_WEAPON.search(remaining):
        actions.append({"class": "WeaponEquipSpell"})

    # Fallback: no action inferred → TODO
    if not actions:
        actions.append(_make_todo(text))

    return actions


def _infer_damage_target(text: str) -> str:
    """从英文文本推断伤害目标类型。

    Returns target selector string for Spell JSON.
    """
    t = text.lower()
    if "all enemy" in t or "all enemies" in t:
        return "ALL_ENEMY_CHARACTERS"
    if "all minion" in t or "all other minion" in t:
        return "ALL_MINIONS"
    if "random enemy" in t or "random" in t and "enemy" in t:
        return "RANDOM_ENEMY_CHARACTER"
    if "random" in t:
        return "RANDOM_ENEMY_MINION"
    if "enemy minion" in t or "enemy" in t:
        return "ENEMY_MINION"
    # Default: requires target selection
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
        text = card.get("englishText", "") or card.get("text", "")

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
            elif mechanic == "OUTCAST":
                actions = _parse_simple_battlecry(text)
                abilities.append({"trigger": "OUTCAST", "actions": actions})
            elif mechanic == "OVERLOAD":
                # OVERLOAD is a cost modifier, not an effect — skip
                continue
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

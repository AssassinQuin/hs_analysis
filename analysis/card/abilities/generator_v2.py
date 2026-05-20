#!/usr/bin/env python3
"""generator_v2.py — 从 CardDB 生成 card_abilities_v2.json (递归 SpellDesc 格式)。

v2 格式 (每张卡一个条目):
  {"card_id": {
    "ON_PLAY": {"class": "DamageSpell", "value": {...}, "target": "TARGET"},
    "COMBO":   {"class": "MetaSpell", "spells": [...]},
    "DEATHRATTLE": {"class": "SummonSpell", ...},
    "AURA":    {"class": "AuraBuffSpell", ...},
    "TRIGGERS": [{"event": "TURN_END", "spell": {...}}],
  }}

v1 到 v2 核心变更:
  - "actions" 列表 → 单 SpellDesc (多效果用 MetaSpell 包装)
  - "value": N → 支持值提供器 (Damage/Heal 用 spell_damage 提供器)
  - "abilities" 包装 → 直接按 trigger 类型键名
  - 无 "name" 字段 (由 CardDB 持有)
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from analysis.config import PROJECT_ROOT

log = logging.getLogger(__name__)

_DEFAULT_OUTPUT = PROJECT_ROOT / "analysis" / "card" / "data" / "card_abilities_v2.json"

# ── Mechanics 分类 ───────────────────────────────────────────
_TRIGGER_MECHANICS = {
    "BATTLECRY", "DEATHRATTLE", "DISCOVER", "COMBO",
    "SPELLBURST", "INSPIRE", "OVERLOAD", "SECRET",
    "QUEST", "OUTCAST", "FRENZY", "FINALE",
}

_TRIGGER_TO_KEY: Dict[str, str] = {
    "BATTLECRY":    "ON_PLAY",
    "COMBO":        "COMBO",
    "OUTCAST":      "OUTCAST",
    "DEATHRATTLE":  "DEATHRATTLE",
    "DISCOVER":     None,   # → ON_PLAY
    "SPELLBURST":   "SPELLBURST",
    "INSPIRE":      "INSPIRE",
    "FRENZY":       "FRENZY",
    "FINALE":       "FINALE",
    "QUEST":        None,   # TODO
    "SECRET":       None,   # TODO
    "OVERLOAD":     None,   # cost modifier
}

_TAG_ONLY_MECHANICS = {
    "TAUNT", "RUSH", "CHARGE", "DIVINE_SHIELD", "WINDFURY",
    "STEALTH", "POISONOUS", "LIFESTEAL", "REBORN",
    "SPELL_DAMAGE", "IMMUNE", "MEGA_WINDFURY", "ELUSIVE",
    "CANT_BE_TARGETED_BY_SPELLS", "CANT_BE_TARGETED_BY_HERO_POWERS",
    "FREEZE", "INFERNAL",
}

# ── 文本清理 ─────────────────────────────────────────────────
_RE_HTML = re.compile(r"</?[a-zA-Z]+>")
_RE_X_PREFIX = re.compile(r"\[x\]")

def _clean(text: str) -> str:
    t = _RE_HTML.sub("", text)
    t = _RE_X_PREFIX.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


# ── Regex patterns ───────────────────────────────────────────
_RE_DAMAGE  = re.compile(r"[Dd]eal\s*[\$#]?\s*(\d+)\s+damage")
_RE_HEAL    = re.compile(r"[Rr]estore\s*[\$#]?\s*(\d+)\s+[Hh]ealth")
_RE_DRAW    = re.compile(r"[Dd]raw\s+(\d+|a|an)\s*(?:cards?|copies?)?")
_RE_ARMOR   = re.compile(r"[Gg]ain\s*[\$#]?\s*(\d+)\s+[Aa]rmor")
_RE_SUMMON  = re.compile(r"[Ss]ummon\s+(?:a|an|two|three)?\s*(.+?)?(?:\.|$)")
_RE_DISCOVER = re.compile(r"[Dd]iscover")
_RE_BUFF    = re.compile(r"\+(\d+)/\+(\d+)")
_RE_DESTROY  = re.compile(r"[Dd]estroy")
_RE_SILENCE  = re.compile(r"[Ss]ilence")
_RE_FREEZE   = re.compile(r"[Ff]reeze")
_RE_TRANSFORM = re.compile(r"[Tt]ransform\s(?:into\s)?(.+?)(?:\.|$)")
_RE_COPY     = re.compile(r"[Cc]opy")
_RE_TAKE_CONTROL = re.compile(r"[Tt]ake\s+control")
_RE_SHUFFLE  = re.compile(r"[Ss]huffle\s+(.+?)\s+into")
_RE_EQUIP_WEAPON = re.compile(r"[Ee]quip")
_RE_MANA     = re.compile(r"[Gg]ain\s*(?:\w+\s+)*?(\d+)\s+Mana")
_RE_DISCARD  = re.compile(r"[Dd]iscard\s+(\d+|a|an)")
_RE_RETURN   = re.compile(r"[Rr]eturn\s+(?:to\s+\w+\s+)?hand")
# Aura detection: cards that give ongoing buffs to other minions
_RE_AURA = re.compile(
    r"(?:your\s+other\s+minions|your\s+minions|adjacent\s+minions|"
    r"your\s+(?:\w+\s+)*minions|all\s+other\s+\w+)\s+have\s+",
    re.IGNORECASE,
)
# Trigger detection: at the start/end of your turn, after you play, etc.
_RE_TRIGGER = re.compile(
    r"(?:at\s+(?:the\s+)?(?:start|end)\s+of\s+(?:your|each)\s+turn"
    r"|after\s+(?:your\s+hero\s+)?attacks"
    r"|whenever\s+(?:you\s+)?(?:play|cast|summon))",
    re.IGNORECASE,
)


def _en_int(sval: str) -> int:
    """英文字符串 → int."""
    if sval.isdigit():
        return int(sval)
    if sval.lower() in ("a", "an"):
        return 1
    return 0


# ═══════════════════════════════════════════════════════════════
# v2 输出构建
# ═══════════════════════════════════════════════════════════════

def _make_damage_value(base: int) -> dict:
    """Damage/Heal 的值包装为 spell_damage 提供器。"""
    return {"provider": "spell_damage", "base": base}


def _action_to_spell_desc(action: dict) -> dict:
    """将 v1 风格 action dict 转为 v2 SpellDesc dict。

    v1: {"class": "DamageSpell", "value": 6, "target": "TARGET"}
    v2: {"class": "DamageSpell", "value": {"provider": "spell_damage", "base": 6}, "target": "TARGET"}
    """
    result: dict = {"class": action["class"]}

    # 复制已知字段
    for field in ("target", "count", "attack", "health",
                  "attack_bonus", "health_bonus",
                  "card_id", "keyword", "pool", "filter"):
        if field in action:
            result[field] = action[field]

    # value: 对 Damage/Heal 用值提供器
    if "value" in action:
        cls_name = action["class"]
        if cls_name in ("DamageSpell", "HealSpell"):
            result["value"] = _make_damage_value(action["value"])
        else:
            result["value"] = action["value"]

    # 自定义参数兜底
    known = {"class", "target", "value", "count", "attack", "health",
             "attack_bonus", "health_bonus", "card_id", "keyword", "pool",
             "filter", "_card_name", "text_raw"}
    for k, v in action.items():
        if k not in known:
            result[k] = v

    return result


def _actions_to_spell_desc(actions: List[dict]) -> dict:
    """v1 actions 列表 → 单个 v2 SpellDesc dict。

    单 action → 直接转换
    多 action → MetaSpell 包装
    空 list   → TODO
    """
    if not actions:
        return {"class": "TODO", "text_raw": ""}
    if len(actions) == 1:
        return _action_to_spell_desc(actions[0])
    # 多效果 → MetaSpell
    return {
        "class": "MetaSpell",
        "spells": [_action_to_spell_desc(a) for a in actions],
    }


_buff_ranges: Dict[str, Dict[str, int]] = {}


def _register_buff(card_id: str, atk: int, hp: int) -> None:
    _buff_ranges[card_id] = {"atk": atk, "hp": hp}


# ═══════════════════════════════════════════════════════════════
# 解析逻辑 (复用 generator.py 的模式)
# ═══════════════════════════════════════════════════════════════

def _infer_damage_target(text: str) -> str:
    t = text.lower()
    if "all enemy" in t or "all enemies" in t:
        return "ALL_ENEMY_CHARACTERS"
    if "all minion" in t or "all other minion" in t:
        return "ALL_MINIONS"
    if "random enemy" in t and "minion" in t:
        return "RANDOM_ENEMY_MINION"
    if "random enemy" in t:
        return "RANDOM_ENEMY_CHARACTER"
    if "random" in t:
        return "RANDOM_ENEMY_MINION"
    if "enemy minion" in t or "enemy" in t:
        return "ENEMY_MINION"
    if "all friendly" in t or "your" in t:
        return "ALL_FRIENDLY_CHARACTERS"
    return "TARGET"


def _make_todo(text: str) -> dict:
    return {"class": "TODO", "text_raw": text}


def _parse_battlecry(text: str) -> List[dict]:
    """从英文文本中推断 BATTLECRY/COMBO 等效果列表 (v1 actions)。"""
    actions: List[dict] = []
    remaining = _clean(text)

    if _RE_DISCOVER.search(remaining):
        actions.append({"class": "DiscoverSpell"})
        return actions

    m = _RE_DAMAGE.search(remaining)
    if m:
        value = int(m.group(1))
        target = _infer_damage_target(remaining)
        actions.append({"class": "DamageSpell", "value": value, "target": target})
        remaining = remaining[:m.start()] + remaining[m.end():]

    m = _RE_HEAL.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "HealSpell", "value": value, "target": "FRIENDLY_HERO"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    m = _RE_DRAW.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DrawSpell", "value": count})
            remaining = remaining[:m.start()] + remaining[m.end():]

    m = _RE_ARMOR.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ArmorSpell", "value": value})
        remaining = remaining[:m.start()] + remaining[m.end():]

    m = _RE_BUFF.search(remaining)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack_bonus": atk, "health_bonus": hp, "target": "SELF"})
        remaining = remaining[:m.start()] + remaining[m.end():]

    if _RE_DESTROY.search(remaining):
        actions.append({"class": "DestroySpell", "target": "TARGET"})

    if _RE_SILENCE.search(remaining):
        actions.append({"class": "SilenceSpell", "target": "TARGET"})

    if _RE_FREEZE.search(remaining):
        actions.append({"class": "FreezeSpell", "target": "TARGET"})

    m = _RE_TRANSFORM.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "TransformSpell", "text_raw": card_name})

    if _RE_COPY.search(remaining):
        actions.append({"class": "CopySpell", "target": "TARGET"})

    if _RE_TAKE_CONTROL.search(remaining):
        actions.append({"class": "TakeControlSpell", "target": "TARGET"})

    if _RE_SUMMON.search(remaining):
        actions.append({"class": "SummonSpell"})

    m = _RE_SHUFFLE.search(remaining)
    if m:
        card_name = m.group(1).strip()
        actions.append({"class": "ShuffleSpell", "text_raw": card_name})

    if _RE_EQUIP_WEAPON.search(remaining):
        actions.append({"class": "WeaponEquipSpell"})

    m = _RE_MANA.search(remaining)
    if m:
        value = int(m.group(1))
        actions.append({"class": "ManaSpell", "value": value})

    m = _RE_DISCARD.search(remaining)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DiscardSpell", "value": count})

    if _RE_RETURN.search(remaining):
        actions.append({"class": "ReturnSpell", "target": "TARGET"})

    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_deathrattle(text: str) -> List[dict]:
    """从英文文本中推断 DEATHRATTLE 效果列表 (v1 actions)。"""
    actions: List[dict] = []
    text = _clean(text)

    m = _RE_DAMAGE.search(text)
    if m:
        value = int(m.group(1))
        actions.append({"class": "DamageSpell", "value": value, "target": "RANDOM_ENEMY_CHARACTER"})

    m = _RE_DRAW.search(text)
    if m:
        count = _en_int(m.group(1))
        if count:
            actions.append({"class": "DrawSpell", "value": count})

    if _RE_SUMMON.search(text):
        actions.append({"class": "SummonSpell"})

    m = _RE_BUFF.search(text)
    if m:
        atk, hp = int(m.group(1)), int(m.group(2))
        actions.append({"class": "BuffSpell", "attack_bonus": atk, "health_bonus": hp, "target": "SELF"})

    if not actions:
        actions.append(_make_todo(text))

    return actions


def _parse_spell(text: str) -> List[dict]:
    """从法术文本推断效果列表 (同 _parse_battlecry)。"""
    return _parse_battlecry(text)


# ═══════════════════════════════════════════════════════════════
# Aura 检测
# ═══════════════════════════════════════════════════════════════

def _is_aura_card(text: str, card_id: str, card_type: str, mechanics: List[str]) -> bool:
    """检测是否为光环效果卡 (持续给其他随从+攻/+血等)。"""
    if card_type != "MINION":
        return False
    # 只检测 BATTLECRY 以外的持续效果
    if "BATTLECRY" in mechanics:
        return False
    if "DEATHRATTLE" in mechanics:
        return False

    text = _clean(text)
    return bool(_RE_AURA.search(text))


def _parse_aura(text: str) -> Optional[dict]:
    """解析光环效果 → AuraBuffSpell 描述。"""
    text = _clean(text)
    m = _RE_BUFF.search(text)
    if not m:
        return None
    atk, hp = int(m.group(1)), int(m.group(2))

    target = "OTHER_FRIENDLY_MINIONS"
    if "adjacent" in text.lower():
        target = "ADJACENT_MINIONS"
    elif "your minions" in text.lower() and "other" not in text.lower():
        target = "FRIENDLY_MINIONS"

    return {
        "class": "AuraBuffSpell",
        "attack_bonus": atk,
        "health_bonus": hp,
        "target": target,
    }


def _detect_trigger_event(text: str) -> Optional[str]:
    """检测文本中是否包含触发器事件。
    
    返回事件名 (如 "TURN_END", "AFTER_ATTACK") 或 None。
    """
    t = text.lower()
    if "at the start of your turn" in t or "at the start of each turn" in t:
        return "TURN_START"
    if "at the end of your turn" in t or "at the end of each turn" in t:
        return "TURN_END"
    if "after your hero attacks" in t or "whenever your hero attacks" in t:
        return "AFTER_ATTACK"
    if "after you play" in t or "whenever you play" in t:
        return "AFTER_PLAY_CARD"
    if "after you cast" in t or "whenever you cast" in t:
        return "AFTER_CAST_SPELL"
    return None


# ═══════════════════════════════════════════════════════════════
# v2 转换入口
# ═══════════════════════════════════════════════════════════════

def generate_card_ability_v2(entry: dict) -> dict:
    """将 v1 格式 entry 转为 v2 SpellDesc JSON。

    v1: {"name": "Fireball", "abilities": [{"actions": [...]}]}
    v2: {"ON_PLAY": {"class": "DamageSpell", ...}}
    """
    abilities = entry.get("abilities", [])
    if not abilities:
        # 空 → 从 text 重新解析
        text = entry.get("text", entry.get("englishText", ""))
        if text:
            actions = _parse_spell(text)
            return {
                "ON_PLAY": _actions_to_spell_desc(actions),
            }
        return {}

    # v1 abilities = [{"trigger": "BATTLECRY", "actions": [...]}, ...]
    result: dict = {}
    for ab in abilities:
        trigger = ab.get("trigger", "")
        actions = ab.get("actions", [])

        if trigger == "BATTLECRY":
            result["ON_PLAY"] = _actions_to_spell_desc(actions)
        elif trigger in ("COMBO", "OUTCAST", "DEATHRATTLE"):
            result[trigger] = _actions_to_spell_desc(actions)
        elif trigger in ("SPELLBURST", "INSPIRE", "FRENZY", "FINALE"):
            # 这些作为 TRIGGERS
            triggers = result.setdefault("TRIGGERS", [])
            triggers.append({
                "event": trigger,
                "spell": _actions_to_spell_desc(actions),
            })
        elif trigger == "DISCOVER":
            existing = result.get("ON_PLAY")
            desc = {"class": "DiscoverSpell"}
            if existing:
                # 合并到 MetaSpell
                if existing.get("class") == "MetaSpell":
                    existing["spells"].append(desc)
                else:
                    result["ON_PLAY"] = {"class": "MetaSpell", "spells": [existing, desc]}
            else:
                result["ON_PLAY"] = desc
        else:
            # 未知 trigger → 仍然输出
            result[trigger] = _actions_to_spell_desc(actions)

    return result


# ═══════════════════════════════════════════════════════════════
# 主生成逻辑
# ═══════════════════════════════════════════════════════════════

def generate_abilities_json_v2(output_path: Optional[str] = None) -> Dict[str, Any]:
    """从 CardDB 生成 v2 card_abilities.json。

    返回: {"card_id": {"ON_PLAY": ..., "DEATHRATTLE": ..., ...}, ...}
    """
    from analysis.card.data.card_data import get_db

    db = get_db()
    cards = db.get_collectible_cards(fmt="wild")

    result: Dict[str, Any] = {}
    stats = {
        "total": 0, "tag_only": 0, "inferred": 0, "todo": 0,
        "spell": 0, "aura": 0,
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
            actions = _parse_spell(text)
            v2_entry = {"ON_PLAY": _actions_to_spell_desc(actions)}
            result[card_id] = v2_entry
            if any(a.get("class") == "TODO" for a in actions):
                stats["todo"] += 1
            else:
                stats["inferred"] += 1
                stats["spell"] += 1
            continue

        # ── 武器牌 ──
        if card_type == "WEAPON":
            continue

        # ── 随从牌 ──
        if card_type != "MINION":
            continue

        # 纯关键字
        if not mechanics or all(m in _TAG_ONLY_MECHANICS for m in mechanics):
            stats["tag_only"] += 1
            continue

        # Aura 检测
        if _is_aura_card(text, card_id, card_type, mechanics):
            aura = _parse_aura(text)
            if aura:
                result[card_id] = {"AURA": aura}
                stats["aura"] += 1
                stats["inferred"] += 1
                continue
            else:
                result[card_id] = {"AURA": _make_todo(text)}
                stats["todo"] += 1
                continue

        # 触发效果
        ability_entry: dict = {}
        has_todo_flag = False
        for mechanic in mechanics:
            if mechanic not in _TRIGGER_MECHANICS:
                continue
            if mechanic == "OVERLOAD":
                continue

            if mechanic in ("BATTLECRY", "COMBO", "OUTCAST"):
                handler = _parse_battlecry
            elif mechanic == "DEATHRATTLE":
                handler = _parse_deathrattle
            else:
                handler = _parse_battlecry

            actions = handler(text)
            key = _TRIGGER_TO_KEY.get(mechanic, mechanic)
            if key in ("SPELLBURST", "INSPIRE", "FRENZY", "FINALE"):
                # 注册为触发器
                triggers = ability_entry.setdefault("TRIGGERS", [])
                triggers.append({
                    "event": mechanic,
                    "spell": _actions_to_spell_desc(actions),
                })
            elif key:
                ability_entry[key] = _actions_to_spell_desc(actions)

            if any(a.get("class") == "TODO" for a in actions):
                has_todo_flag = True

        # 文本触发器 (TURN_START/TURN_END/AFTER_ATTACK 等)
        trigger_event = _detect_trigger_event(text) if text else None
        if trigger_event:
            actions = _parse_battlecry(text)
            triggers = ability_entry.setdefault("TRIGGERS", [])
            triggers.append({
                "event": trigger_event,
                "spell": _actions_to_spell_desc(actions),
            })
            # 如果只有 on-play 对应的 trigger，可能也需要 ON_PLAY
            # (这里按需, 暂不自动加)

        if ability_entry:
            result[card_id] = ability_entry
            if has_todo_flag:
                stats["todo"] += 1
            else:
                stats["inferred"] += 1

    # ── 写文件 ──
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("v2 JSON 已写入 %s", out)

    log.info(
        "v2 生成完成: 总计 %d 张, 纯关键字 %d, 推断成功 %d, "
        "TODO %d, 法术 %d, 光环 %d",
        stats["total"], stats["tag_only"], stats["inferred"],
        stats["todo"], stats["spell"], stats["aura"],
    )

    return result


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    import argparse
    parser = argparse.ArgumentParser(description="生成 v2 card_abilities.json")
    parser.add_argument("--output", "-o", type=str, default=None)
    args = parser.parse_args()
    output = args.output or str(_DEFAULT_OUTPUT)
    generate_abilities_json_v2(output_path=output)

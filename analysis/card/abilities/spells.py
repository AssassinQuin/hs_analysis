#!/usr/bin/env python3
"""spells.py — MetaStone 风格的 Spell 效果系统。

核心架构:
  Spell ABC       — 效果基类，所有可执行效果的抽象接口
  SPELL_REGISTRY  — 类名 → Spell 类的注册表，支持反射加载
  MetaSpell       — 组合模式，顺序执行多个子 Spell
  ConditionalSpell — 条件分支 Spell

Spell 实例从 card_abilities.json 的 {"class": "DamageSpell", ...} 加载，
运行时通过 SPELL_REGISTRY 查找并实例化。
"""
from __future__ import annotations

import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState, Minion

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

SPELL_REGISTRY: Dict[str, type["Spell"]] = {}


def register_spell(cls: type["Spell"]) -> type["Spell"]:
    """装饰器: 将 Spell 子类注册到 SPELL_REGISTRY。

    用法:
        @register_spell
        class DamageSpell(Spell):
            ...
    """
    name = cls.__name__
    SPELL_REGISTRY[name] = cls
    return cls


# ═══════════════════════════════════════════════════════════════
# Spell 基类
# ═══════════════════════════════════════════════════════════════

class Spell(ABC):
    """效果基类 — 所有可执行卡牌效果的抽象基类。

    子类必须实现 execute() 方法。
    使用 @register_spell 装饰器自动注册到 SPELL_REGISTRY。
    """

    @abstractmethod
    def execute(self, state: "GameState", source: Any = None,
                target: Any = None, **kwargs) -> Optional["GameState"]:
        """执行效果。

        参数:
            state: 游戏状态
            source: 效果来源（通常是卡牌或随从）
            target: 效果目标（可能是 None）
        返回:
            变更后的 GameState（不可变模式）或 None
        """
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "Spell":
        """从 JSON dict 构造 Spell 实例（反射工厂）。

        根据 data["class"] 字段查找 SPELL_REGISTRY，
        然后调用对应类的 from_dict() 方法。
        """
        class_name = data.get("class", "")
        spell_cls = SPELL_REGISTRY.get(class_name)
        if spell_cls is None:
            log.warning("Spell 注册表中未找到类名 %r，跳过", class_name)
            return NoOpSpell()
        return spell_cls.from_dict(data)


# ═══════════════════════════════════════════════════════════════
# 目标选择器
# ═══════════════════════════════════════════════════════════════

def resolve_target(
    target_spec: str,
    state: "GameState",
    source: Any = None,
    action_target: Any = None,
) -> List[Any]:
    """将目标选择器字符串解析为实体列表。

    参数:
        target_spec: 目标选择器字符串（如 "RANDOM_ENEMY_CHARACTER"）
        state: 游戏状态
        source: 效果来源
        action_target: 玩家选择的法术/战吼目标
    """
    # 友方
    board = list(state.board) if state.board else []
    opp_board = list(state.opponent.board) if hasattr(state, "opponent") and state.opponent.board else []

    spec = target_spec.upper() if target_spec else ""

    if spec == "SELF":
        return [source] if source else []
    elif spec == "TARGET":
        return [action_target] if action_target else []
    elif spec == "FRIENDLY_HERO":
        return [state.hero] if hasattr(state, "hero") else []
    elif spec == "FRIENDLY_MINION":
        return board
    elif spec == "FRIENDLY_MINIONS":
        return board
    elif spec == "ENEMY_HERO":
        return [state.opponent.hero] if hasattr(state, "opponent") and hasattr(state.opponent, "hero") else []
    elif spec == "ENEMY_MINION":
        return opp_board  # 通常法术指定单个，这里返回全部由 Spell 选取
    elif spec == "ENEMY_MINIONS":
        return opp_board
    elif spec == "ALL_MINIONS":
        return board + opp_board
    elif spec == "ALL_ENEMY_CHARACTERS":
        heroes = [state.opponent.hero] if hasattr(state, "opponent") and hasattr(state.opponent, "hero") else []
        return opp_board + heroes
    elif spec == "ALL_FRIENDLY_CHARACTERS":
        heroes = [state.hero] if hasattr(state, "hero") else []
        return board + heroes
    elif spec == "ANY":
        # 任意角色 — 如果有 action_target 用它，否则全部
        if action_target:
            return [action_target]
        return board + opp_board
    elif spec == "RANDOM_ENEMY_CHARACTER":
        heroes = [state.opponent.hero] if hasattr(state, "opponent") and hasattr(state.opponent, "hero") else []
        pool = opp_board + heroes
        return [random.choice(pool)] if pool else []
    elif spec == "RANDOM_ENEMY_MINION":
        return [random.choice(opp_board)] if opp_board else []
    elif spec == "RANDOM_FRIENDLY_MINION":
        return [random.choice(board)] if board else []
    else:
        log.warning("未知目标选择器 %r，返回空列表", target_spec)
        return []


def resolve_value(
    value: Any,
    state: "GameState" = None,
    source: Any = None,
) -> int:
    """解析值表达式为整数。

    支持字面量 int 和 value_expr 字典格式。
    """
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        from analysis.card.abilities.value_expr import resolve as ve_resolve
        return ve_resolve(value, state, source)
    return int(value) if value else 0


# ═══════════════════════════════════════════════════════════════
# 具体 Spell 实现
# ═══════════════════════════════════════════════════════════════

@register_spell
class NoOpSpell(Spell):
    """空操作 Spell — 用于未知类名的 fallback。"""

    def execute(self, state, source=None, target=None, **kwargs):
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "NoOpSpell":
        return cls()


@register_spell
class DamageSpell(Spell):
    """造成伤害。"""

    def __init__(self, value: Any = 0, target: str = "TARGET"):
        self._value = value
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import damage
        val = resolve_value(self._value, state, source)
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = damage(state, val, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "DamageSpell":
        return cls(value=data.get("value", 0), target=data.get("target", "TARGET"))


@register_spell
class HealSpell(Spell):
    """治疗。"""

    def __init__(self, value: Any = 0, target: str = "TARGET"):
        self._value = value
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import heal
        val = resolve_value(self._value, state, source)
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = heal(state, val, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "HealSpell":
        return cls(value=data.get("value", 0), target=data.get("target", "TARGET"))


@register_spell
class SummonSpell(Spell):
    """召唤随从。"""

    def __init__(self, card_id: str = "", position: int = -1):
        self._card_id = card_id
        self._position = position

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import summon_minion_by_id
        return summon_minion_by_id(state, self._card_id, position=self._position)

    @classmethod
    def from_dict(cls, data: dict) -> "SummonSpell":
        return cls(card_id=data.get("card_id", ""), position=data.get("position", -1))


@register_spell
class BuffSpell(Spell):
    """增益随从属性（+attack/+health）。"""

    def __init__(self, attack: Any = 0, health: Any = 0, target: str = "TARGET"):
        self._attack = attack
        self._health = health
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import buff_minion
        atk = resolve_value(self._attack, state, source)
        hp = resolve_value(self._health, state, source)
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = buff_minion(state, t, atk, hp)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "BuffSpell":
        return cls(
            attack=data.get("attack", 0),
            health=data.get("health", 0),
            target=data.get("target", "TARGET"),
        )


@register_spell
class DrawSpell(Spell):
    """抽牌。"""

    def __init__(self, count: Any = 1):
        self._count = count

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import draw_cards
        n = resolve_value(self._count, state, source)
        return draw_cards(state, n)

    @classmethod
    def from_dict(cls, data: dict) -> "DrawSpell":
        return cls(count=data.get("count", 1))


@register_spell
class DestroySpell(Spell):
    """摧毁随从。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import destroy_minion
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = destroy_minion(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "DestroySpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class SilenceSpell(Spell):
    """沉默随从。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import silence_minion
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = silence_minion(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "SilenceSpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class FreezeSpell(Spell):
    """冻结。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import freeze_entity
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = freeze_entity(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "FreezeSpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class ReturnSpell(Spell):
    """将随从返回手牌。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import return_to_hand
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = return_to_hand(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "ReturnSpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class TakeControlSpell(Spell):
    """获得随从控制权。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import take_control
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = take_control(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "TakeControlSpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class DiscoverSpell(Spell):
    """发现机制。"""

    def __init__(self, pool: str = "", count: int = 3):
        self._pool = pool
        self._count = count

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import discover
        return discover(state, pool=self._pool, count=self._count)

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoverSpell":
        return cls(pool=data.get("pool", ""), count=data.get("count", 3))


@register_spell
class DiscardSpell(Spell):
    """随机弃牌。"""

    def __init__(self, count: Any = 1):
        self._count = count

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import discard_cards
        n = resolve_value(self._count, state, source)
        return discard_cards(state, n)

    @classmethod
    def from_dict(cls, data: dict) -> "DiscardSpell":
        return cls(count=data.get("count", 1))


@register_spell
class ShuffleSpell(Spell):
    """洗入牌库。"""

    def __init__(self, card_id: str = ""):
        self._card_id = card_id

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import shuffle_into_deck
        return shuffle_into_deck(state, self._card_id)

    @classmethod
    def from_dict(cls, data: dict) -> "ShuffleSpell":
        return cls(card_id=data.get("card_id", ""))


@register_spell
class TransformSpell(Spell):
    """变形随从。"""

    def __init__(self, card_id: str = "", target: str = "TARGET"):
        self._card_id = card_id
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import transform_minion
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = transform_minion(state, t, self._card_id)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "TransformSpell":
        return cls(card_id=data.get("card_id", ""), target=data.get("target", "TARGET"))


@register_spell
class CopySpell(Spell):
    """复制随从。"""

    def __init__(self, target: str = "TARGET"):
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import copy_minion
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = copy_minion(state, t)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "CopySpell":
        return cls(target=data.get("target", "TARGET"))


@register_spell
class ArmorSpell(Spell):
    """获得护甲。"""

    def __init__(self, value: Any = 0):
        self._value = value

    def execute(self, state, source=None, target=None, **kwargs):
        val = resolve_value(self._value, state, source)
        state.hero.armor += val
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "ArmorSpell":
        return cls(value=data.get("value", 0))


@register_spell
class ManaSpell(Spell):
    """获得法力。"""

    def __init__(self, value: Any = 0):
        self._value = value

    def execute(self, state, source=None, target=None, **kwargs):
        val = resolve_value(self._value, state, source)
        if hasattr(state, "mana"):
            state.mana.available += val
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "ManaSpell":
        return cls(value=data.get("value", 0))


@register_spell
class GiveSpell(Spell):
    """给予关键词/标签。"""

    def __init__(self, keyword: str = "", target: str = "TARGET"):
        self._keyword = keyword
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.tags import GameTag, set_tag
        tag_map = {
            "TAUNT": GameTag.TAUNT, "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
            "STEALTH": GameTag.STEALTH, "WINDFURY": GameTag.WINDFURY,
            "CHARGE": GameTag.CHARGE, "RUSH": GameTag.RUSH,
            "LIFESTEAL": GameTag.LIFESTEAL, "POISONOUS": GameTag.POISONOUS,
            "REBORN": GameTag.REBORN, "IMMUNE": GameTag.IMMUNE,
        }
        tag = tag_map.get(self._keyword.upper())
        if tag:
            targets = resolve_target(self._target, state, source, target)
            for t in targets:
                set_tag(t, tag, 1)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "GiveSpell":
        return cls(keyword=data.get("keyword", ""), target=data.get("target", "TARGET"))


@register_spell
class WeaponEquipSpell(Spell):
    """装备武器。"""

    def __init__(self, card_id: str = ""):
        self._card_id = card_id

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import equip_weapon
        return equip_weapon(state, self._card_id)

    @classmethod
    def from_dict(cls, data: dict) -> "WeaponEquipSpell":
        return cls(card_id=data.get("card_id", ""))


@register_spell
class EnchantSpell(Spell):
    """附魔 — 给随从添加临时或永久的属性修改。"""

    def __init__(self, attack: Any = 0, health: Any = 0,
                 duration: int = 0, target: str = "TARGET"):
        self._attack = attack
        self._health = health
        self._duration = duration
        self._target = target

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.engine.executor import buff_minion
        atk = resolve_value(self._attack, state, source)
        hp = resolve_value(self._health, state, source)
        targets = resolve_target(self._target, state, source, target)
        for t in targets:
            state = buff_minion(state, t, atk, hp)
            if self._duration > 0 and hasattr(t, "enchantments"):
                # 记录附魔用于回合结束时移除
                t.enchantments.append({
                    "attack": atk, "health": hp,
                    "duration": self._duration, "turns_left": self._duration,
                })
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "EnchantSpell":
        return cls(
            attack=data.get("attack", 0),
            health=data.get("health", 0),
            duration=data.get("duration", 0),
            target=data.get("target", "TARGET"),
        )


# ═══════════════════════════════════════════════════════════════
# 组合 Spell
# ═══════════════════════════════════════════════════════════════

@register_spell
class MetaSpell(Spell):
    """组合模式 — 顺序执行多个子 Spell。

    JSON 格式:
        {"class": "MetaSpell", "spells": [
            {"class": "DrawSpell", "count": 2},
            {"class": "BuffSpell", "attack": 1, "target": "FRIENDLY_MINIONS"}
        ]}
    """

    def __init__(self, spells: List[Spell] = None):
        self._spells = spells or []

    def execute(self, state, source=None, target=None, **kwargs):
        for spell in self._spells:
            state = spell.execute(state, source, target, **kwargs)
            if state is None:
                break
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "MetaSpell":
        spells = [Spell.from_dict(s) for s in data.get("spells", [])]
        return cls(spells=spells)


@register_spell
class ConditionalSpell(Spell):
    """条件分支 Spell。

    JSON 格式:
        {"class": "ConditionalSpell",
         "condition": {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}},
         "then_spell": {"class": "DamageSpell", "value": 3, "target": "RANDOM_ENEMY_MINION"},
         "else_spell": null}
    """

    def __init__(self, condition: dict = None,
                 then_spell: Spell = None, else_spell: Spell = None):
        self._condition = condition or {}
        self._then_spell = then_spell
        self._else_spell = else_spell

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.abilities.value_expr import resolve_condition
        if resolve_condition(self._condition, state, source):
            if self._then_spell:
                return self._then_spell.execute(state, source, target, **kwargs)
        else:
            if self._else_spell:
                return self._else_spell.execute(state, source, target, **kwargs)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "ConditionalSpell":
        then_data = data.get("then_spell")
        else_data = data.get("else_spell")
        return cls(
            condition=data.get("condition"),
            then_spell=Spell.from_dict(then_data) if then_data else None,
            else_spell=Spell.from_dict(else_data) if else_data else None,
        )


@register_spell
class EitherOrSpell(Spell):
    """二选一 Spell — 类似 ConditionalSpell 但更语义化。"""

    def __init__(self, condition: dict = None,
                 spell1: Spell = None, spell2: Spell = None):
        self._condition = condition or {}
        self._spell1 = spell1
        self._spell2 = spell2

    def execute(self, state, source=None, target=None, **kwargs):
        from analysis.card.abilities.value_expr import resolve_condition
        if resolve_condition(self._condition, state, source):
            return self._spell1.execute(state, source, target, **kwargs) if self._spell1 else state
        return self._spell2.execute(state, source, target, **kwargs) if self._spell2 else state

    @classmethod
    def from_dict(cls, data: dict) -> "EitherOrSpell":
        s1 = data.get("spell1")
        s2 = data.get("spell2")
        return cls(
            condition=data.get("condition"),
            spell1=Spell.from_dict(s1) if s1 else None,
            spell2=Spell.from_dict(s2) if s2 else None,
        )


@register_spell
class RepeatSpell(Spell):
    """重复执行子 Spell N 次。"""

    def __init__(self, spell: Spell = None, count: Any = 1):
        self._spell = spell
        self._count = count

    def execute(self, state, source=None, target=None, **kwargs):
        n = resolve_value(self._count, state, source)
        for _ in range(n):
            if self._spell:
                state = self._spell.execute(state, source, target, **kwargs)
        return state

    @classmethod
    def from_dict(cls, data: dict) -> "RepeatSpell":
        spell_data = data.get("spell")
        return cls(
            spell=Spell.from_dict(spell_data) if spell_data else None,
            count=data.get("count", 1),
        )

"""value/providers.py — 值提供器系统。

SpellDesc 中 value 字段可以是 int（字面量）或 dict（ValueProvider 描述）。
系统根据 provider 字段派发到具体实现，支持链式调用。

JSON 格式:
  {"provider": "spell_damage", "base": 6}
  {"provider": "board_count", "target": "ENEMY_MINIONS"}
  {"provider": "attribute", "entity": "SELF", "attr": "attack"}
  {"provider": "last_spell_cost"}
  {"provider": "hand_count"}
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ValueProvider 基类
# ═══════════════════════════════════════════════════════════════

class ValueProvider(ABC):
    """值提供器基类。"""

    @abstractmethod
    def resolve(self, desc: Dict, state: GameState, source: Any = None) -> int:
        ...


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

VALUE_REGISTRY: Dict[str, ValueProvider] = {}


def register_provider(name: str) -> Callable:
    """装饰器: 注册 ValueProvider。"""
    def wrapper(cls):
        VALUE_REGISTRY[name] = cls()
        return cls
    return wrapper


# ═══════════════════════════════════════════════════════════════
# 入口: resolve_value
# ═══════════════════════════════════════════════════════════════

def resolve_value(
    value: Any,
    state: GameState = None,
    source: Any = None,
) -> int:
    """解析值为整数。

    参数:
        value: int → 直接返回
               dict → 根据 provider 字段派发
               str  → 尝试转 int
    返回:
        解析后的 int
    """
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        provider_name = value.get("provider", "")
        handler = VALUE_REGISTRY.get(provider_name)
        if handler is None:
            log.warning("未知值提供器 %r，返回 0", provider_name)
            return 0
        return handler.resolve(value, state, source)
    try:
        return int(value) if value is not None else 0
    except (ValueError, TypeError):
        return 0


# ═══════════════════════════════════════════════════════════════
# 具体实现
# ═══════════════════════════════════════════════════════════════

@register_provider("spell_damage")
class SpellDamageProvider(ValueProvider):
    """法术伤害值：base + 施法者 spell_power。"""
    def resolve(self, desc, state, source=None):
        base = desc.get("base", 0)
        bonus = 0
        if source is not None:
            bonus = getattr(source, 'spell_power', 0)
        # 也检查场上其他友方随从的法强
        if state:
            for m in state.board:
                bonus += getattr(m, 'spell_power', 0)
        return base + bonus


@register_provider("board_count")
class BoardCountProvider(ValueProvider):
    """场上特定实体数量。"""
    def resolve(self, desc, state, source=None):
        from analysis.card.target.selector import resolve_target
        targets = resolve_target(
            desc.get("target", "ALL_MINIONS"),
            state, source,
        )
        return len(targets)


@register_provider("attribute")
class AttributeProvider(ValueProvider):
    """获取实体属性值。"""
    def resolve(self, desc, state, source=None):
        from analysis.card.target.selector import resolve_target
        entity = desc.get("entity", "SELF")
        attr = desc.get("attr", "attack")
        targets = resolve_target(entity, state, source)
        if not targets:
            return 0
        return getattr(targets[0], attr, 0)


@register_provider("health")
class HealthProvider(ValueProvider):
    """目标当前血量。"""
    def resolve(self, desc, state, source=None):
        from analysis.card.target.selector import resolve_target
        targets = resolve_target(
            desc.get("target", "TARGET"),
            state, source,
        )
        if not targets:
            return 0
        t = targets[0]
        return getattr(t, 'hp', None) or getattr(t, 'health', 0)


@register_provider("missing_health")
class MissingHealthProvider(ValueProvider):
    """目标缺失的血量（max - current）。"""
    def resolve(self, desc, state, source=None):
        from analysis.card.target.selector import resolve_target
        targets = resolve_target(
            desc.get("target", "TARGET"),
            state, source,
        )
        if not targets:
            return 0
        t = targets[0]
        cur = getattr(t, 'hp', None) or getattr(t, 'health', 0)
        max_v = getattr(t, 'max_hp', None) or getattr(t, 'max_health', 0)
        return max(0, max_v - cur)


@register_provider("hand_count")
class HandCountProvider(ValueProvider):
    """手牌数量。"""
    def resolve(self, desc, state, source=None):
        return len(state.hand) if state else 0


@register_provider("deck_count")
class DeckCountProvider(ValueProvider):
    """牌库剩余数量。"""
    def resolve(self, desc, state, source=None):
        remaining = getattr(state, 'deck_remaining', 0)
        deck_list = getattr(state, 'deck_list', None)
        if deck_list is not None:
            return len(deck_list)
        return remaining


@register_provider("last_spell_cost")
class LastSpellCostProvider(ValueProvider):
    """上次施法的费用（用于 Sif 等）。"""
    def resolve(self, desc, state, source=None):
        last = getattr(state, 'last_played_card', None)
        if last is None:
            return 0
        return getattr(last, 'cost', 0)


@register_provider("board_full_count")
class BoardFullCountProvider(ValueProvider):
    """场上还有多少空位。"""
    def resolve(self, desc, state, source=None):
        return max(0, 7 - len(state.board)) if state else 7


@register_provider("corpse_count")
class CorpseCountProvider(ValueProvider):
    """友方残骸数量（DK 资源）。"""
    def resolve(self, desc, state, source=None):
        return getattr(state, 'corpses', 0)


@register_provider("hero_atk")
class HeroAttackProvider(ValueProvider):
    """英雄攻击力（含武器）。"""
    def resolve(self, desc, state, source=None):
        atk = getattr(state.hero, 'attack', 0) if state else 0
        weapon = getattr(state.hero, 'weapon', None) if state else None
        if weapon:
            atk += getattr(weapon, 'attack', 0)
        return atk


@register_provider("damage_taken")
class DamageTakenProvider(ValueProvider):
    """本回合 source 受到的伤害。"""
    def resolve(self, desc, state, source=None):
        return getattr(source, '_damage_taken_this_turn', 0) if source else 0


@register_provider("friendly_deaths")
class FriendlyDeathCountProvider(ValueProvider):
    """本局友方死亡数。"""
    def resolve(self, desc, state, source=None):
        graveyard = getattr(state, 'graveyard', [])
        if graveyard:
            return len(graveyard)
        return 0


# ── 变量递增提供器（escalation / handbuff 等） ──

@register_provider("variable")
class VariableProvider(ValueProvider):
    """变量值提供器 —— escalation/handbuff 类卡牌的值（如每回合递增）。

    计算方式: base + max(0, turn_number - turn_drawn)
    - turn_number 来自 GameState
    - turn_drawn 来自 source 卡牌（由 _draw_card 在抽牌时设置）
    """
    def resolve(self, desc, state, source=None):
        base = desc.get("base", 0)
        if source is None or state is None:
            return base
        drawn_turn = getattr(source, 'turn_drawn', state.turn_number)
        escalation = state.turn_number - drawn_turn
        return base + max(0, escalation)


# ── 常量提供器 ──

@register_provider("constant")
class ConstantProvider(ValueProvider):
    """返回固定值，相当于 int 的 dict 版本。"""
    def resolve(self, desc, state, source=None):
        return desc.get("value", desc.get("base", 0))

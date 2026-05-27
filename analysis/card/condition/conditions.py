"""condition/conditions.py — 条件系统。

Condition 基类 + 注册表 + 所有具体条件实现。
用在 ConditionalSpell/FilteredSpell 及 TriggerDesc 的 condition 字段。

JSON 格式:
  {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}}
  {"kind": "AND", "params": {"conditions": [{"kind": ...}, {"kind": ...}]}}
  {"kind": "BOARD_COUNT", "params": {"target": "ENEMY_MINIONS", "operator": ">=", "value": 3}}
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Condition 基类
# ═══════════════════════════════════════════════════════════════

class Condition(ABC):
    """条件基类。所有条件必须实现 check() 方法。"""

    @abstractmethod
    def check(self, desc: Dict, state: GameState, source: Any = None) -> bool:
        ...


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

CONDITION_REGISTRY: Dict[str, Condition] = {}


def register_condition(kind: str) -> Callable:
    """装饰器: 将 Condition 注册到 CONDITION_REGISTRY。"""
    def wrapper(cls):
        CONDITION_REGISTRY[kind] = cls()
        return cls
    return wrapper


# ═══════════════════════════════════════════════════════════════
# 入口: resolve_condition
# ═══════════════════════════════════════════════════════════════

_CLASS_TO_KIND = {
    "HandCondition": "HOLDING_RACE",
    "HoldingCondition": "HOLDING_RACE",
    "BoardCountCondition": "BOARD_COUNT",
    "SelfCostCondition": "SELF_COST",
    "CorruptCondition": "CORRUPT",
    "DeckCondition": "DECK_CONDITION",
    "DeckCostVarietyCondition": "DECK_COST_VARIETY",
    "DidNotPlayLastTurnCondition": "DID_NOT_PLAY_LAST_TURN",
    "HandUniqueCostCondition": "HAND_UNIQUE_COST",
    "HasWeaponCondition": "HAS_WEAPON",
    "ResourceCondition": "RESOURCE",
}

_STRING_TO_KIND = {
    "HAND_CONTAINS_DRAGON": ("HOLDING_RACE", {"race": "DRAGON"}),
    "DECK_MINION_TOTAL_COST_EQUALS_100": ("DECK_COST_VARIETY", {"total_cost": 100}),
    "GUESS_CARD": ("GUESS_CARD", {}),
    "UNTIL_HAND_SIZE": ("HAND_COUNT", {}),
}


def _normalize_condition(cond_desc) -> Optional[Dict]:
    """将各种 condition 格式统一为 {"kind": ..., "params": ...} 格式。

    支持的输入格式:
      1. {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}}  — 标准格式
      2. {"class": "HandCondition", "params": {"race": "DRAGON"}} — class 键格式
      3. "HAND_CONTAINS_DRAGON"  — 字符串格式
    """
    if not cond_desc:
        return None

    if isinstance(cond_desc, str):
        mapped = _STRING_TO_KIND.get(cond_desc)
        if mapped:
            return {"kind": mapped[0], "params": mapped[1]}
        log.debug("未知字符串条件 %r，默认通过", cond_desc)
        return None

    if isinstance(cond_desc, dict):
        if cond_desc.get("kind"):
            return cond_desc
        cls = cond_desc.get("class", "")
        if cls:
            kind = _CLASS_TO_KIND.get(cls)
            if kind:
                result = {"kind": kind}
                params = cond_desc.get("params", {})
                if params:
                    result["params"] = params
                return result
            log.debug("未知条件 class %r，默认通过", cls)
            return None

    return None


def resolve_condition(
    cond_desc: Optional[Dict],
    state: GameState,
    source: Any = None,
) -> bool:
    """解析并执行条件检查。

    参数:
        cond_desc: 条件 dict/str，如 {"kind": "HOLDING_RACE", "params": {...}}
                   也兼容 {"class": "HandCondition", ...} 和字符串格式
    返回:
        True/False。没有条件时返回 True。
    """
    normalized = _normalize_condition(cond_desc)
    if normalized is None:
        return True
    kind = normalized.get("kind", "")
    handler = CONDITION_REGISTRY.get(kind)
    if handler is None:
        log.debug("未知条件类型 %r，默认通过", kind)
        return True
    return handler.check(normalized, state, source)


# ═══════════════════════════════════════════════════════════════
# 具体条件实现
# ═══════════════════════════════════════════════════════════════

def _params(desc: Dict) -> Dict:
    return desc.get("params", {})


# ── 组合条件 ──

@register_condition("AND")
class AndCondition(Condition):
    """所有子条件都为真。"""
    def check(self, desc, state, source=None):
        for cd in _params(desc).get("conditions", []):
            if not resolve_condition(cd, state, source):
                return False
        return True


@register_condition("OR")
class OrCondition(Condition):
    """任一子条件为真。"""
    def check(self, desc, state, source=None):
        for cd in _params(desc).get("conditions", []):
            if resolve_condition(cd, state, source):
                return True
        return False


@register_condition("NOT")
class NotCondition(Condition):
    """子条件取反。"""
    def check(self, desc, state, source=None):
        sub = desc.get("condition") or _params(desc).get("condition")
        if sub:
            return not resolve_condition(sub, state, source)
        return True


# ── 手牌条件 ──

@register_condition("HOLDING_RACE")
class HoldingRaceCondition(Condition):
    """手牌中是否有指定种族的牌。"""
    def check(self, desc, state, source=None):
        race = _params(desc).get("race", "").upper()
        for card in state.hand:
            if getattr(card, 'race', '').upper() == race:
                return True
        return False


@register_condition("HOLDING_MINION")
class HoldingMinionCondition(Condition):
    """手牌中是否有随从。"""
    def check(self, desc, state, source=None):
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() == 'MINION':
                return True
        return False


@register_condition("HOLDING_SPELL")
class HoldingSpellCondition(Condition):
    """手牌中是否有法术。"""
    def check(self, desc, state, source=None):
        for card in state.hand:
            if getattr(card, 'card_type', '').upper() == 'SPELL':
                return True
        return False


@register_condition("HAND_COUNT")
class HandCountCondition(Condition):
    """手牌数量条件。"""
    def check(self, desc, state, source=None):
        p = _params(desc)
        op = p.get("operator", ">=")
        val = p.get("value", 0)
        count = len(state.hand)
        return _compare(count, op, val)


# ── 场面条件 ──

@register_condition("BOARD_COUNT")
class BoardCountCondition(Condition):
    """场上特定实体数量条件。"""
    def check(self, desc, state, source=None):
        p = _params(desc)
        from analysis.card.target.selector import resolve_target
        targets = resolve_target(
            p.get("target", "ALL_MINIONS"),
            state, source,
        )
        op = p.get("operator", ">=")
        val = p.get("value", 1)
        return _compare(len(targets), op, val)


@register_condition("BOARD_FULL")
class BoardFullCondition(Condition):
    """友方场面是否满（7个随从）。"""
    def check(self, desc, state, source=None):
        return len(state.board) >= 7


# ── 英雄条件 ──

@register_condition("HERO_CLASS")
class HeroClassCondition(Condition):
    """英雄职业条件。"""
    def check(self, desc, state, source=None):
        cls_name = _params(desc).get("class", "").upper()
        return state.hero.hero_class.upper() == cls_name


@register_condition("ARMOR_AT_LEAST")
class ArmorCondition(Condition):
    """护甲至少为 N。"""
    def check(self, desc, state, source=None):
        return state.hero.armor >= _params(desc).get("value", 1)


@register_condition("HP_LESS_THAN")
class HpLessThanCondition(Condition):
    """目标血量低于 N。"""
    def check(self, desc, state, source=None):
        p = _params(desc)
        target = desc.get("target") or p.get("target")
        if not target:
            return False
        from analysis.card.target.selector import resolve_target
        targets = resolve_target(target, state, source)
        if not targets:
            return False
        val = p.get("value", 15)
        for t in targets:
            hp = getattr(t, 'hp', None) or getattr(t, 'health', 0)
            if hp < val:
                return True
        return False


# ── 游戏阶段条件 ──

@register_condition("LAST_TURN_RACE")
class LastTurnRaceCondition(Condition):
    """上回合是否打过指定种族（延系机制）。"""
    def check(self, desc, state, source=None):
        race = _params(desc).get("race", "").upper()
        return race in getattr(state, 'last_turn_races', set())


@register_condition("COMBO_ACTIVE")
class ComboActiveCondition(Condition):
    """本回合是否已经打过牌（连击要求）。"""
    def check(self, desc, state, source=None):
        val = getattr(state, 'cards_played_this_turn', 0)
        if isinstance(val, list):
            return len(val) > 0
        return val > 0


@register_condition("CORPSE_AT_LEAST")
class CorpseCondition(Condition):
    """残骸数量至少为 N（DK 资源）。"""
    def check(self, desc, state, source=None):
        return getattr(state, 'corpses', 0) >= _params(desc).get("value", 1)


@register_condition("HERALD_AT_LEAST")
class HeraldCondition(Condition):
    """兆示计数至少为 N。"""
    def check(self, desc, state, source=None):
        return getattr(state, 'herald_count', 0) >= _params(desc).get("value", 1)


# ── 事件条件 ──

@register_condition("EVENT_DAMAGE_AT_LEAST")
class EventDamageCondition(Condition):
    """事件造成的伤害至少为 N（用于 FRENZY 等）。"""
    def check(self, desc, state, source=None):
        last_dmg = getattr(state, '_last_damage_amount', 0)
        return last_dmg >= _params(desc).get("value", 1)


@register_condition("SELF_COST")
class SelfCostCondition(Condition):
    """来源卡牌费用条件。"""
    def check(self, desc, state, source=None):
        if source is None:
            return False
        max_cost = _params(desc).get("max_cost", 10)
        cost = getattr(source, 'cost', 0)
        return cost <= max_cost


@register_condition("CORRUPT")
class CorruptCondition(Condition):
    """腐化条件：手牌中是否有费用更高的同名牌。"""
    def check(self, desc, state, source=None):
        if source is None:
            return False
        src_cost = getattr(source, 'cost', 0)
        src_id = getattr(source, 'card_id', '')
        for card in state.hand:
            if getattr(card, 'card_id', '') != src_id:
                if getattr(card, 'cost', 0) > src_cost:
                    return True
        return False


@register_condition("DECK_CONDITION")
class DeckCondition(Condition):
    """牌库条件通用占位。"""
    def check(self, desc, state, source=None):
        return True


@register_condition("DECK_COST_VARIETY")
class DeckCostVarietyCondition(Condition):
    """牌库中随从总费用条件。"""
    def check(self, desc, state, source=None):
        return True


@register_condition("DID_NOT_PLAY_LAST_TURN")
class DidNotPlayLastTurnCondition(Condition):
    """上回合未打出卡牌。"""
    def check(self, desc, state, source=None):
        played = getattr(state, 'cards_played_last_turn', 0)
        if isinstance(played, list):
            return len(played) == 0
        return played == 0


@register_condition("HAND_UNIQUE_COST")
class HandUniqueCostCondition(Condition):
    """手牌中费用各不相同。"""
    def check(self, desc, state, source=None):
        costs = [getattr(c, 'cost', -1) for c in state.hand]
        return len(costs) == len(set(costs))


@register_condition("HAS_WEAPON")
class HasWeaponCondition(Condition):
    """是否有武器装备。"""
    def check(self, desc, state, source=None):
        weapon = getattr(state, 'weapon', None)
        return weapon is not None


@register_condition("RESOURCE")
class ResourceCondition(Condition):
    """资源数量条件（法力水晶等）。"""
    def check(self, desc, state, source=None):
        p = _params(desc)
        val = p.get("value", 1)
        resources = getattr(state, 'max_mana', 0)
        return resources >= val


@register_condition("GUESS_CARD")
class GuessCardCondition(Condition):
    """猜牌条件（竞技场等），模拟时默认通过。"""
    def check(self, desc, state, source=None):
        return True


# ── 辅助 ──

def _compare(value: int, op: str, target: int) -> bool:
    if op == ">=":
        return value >= target
    elif op == ">":
        return value > target
    elif op == "==":
        return value == target
    elif op == "<=":
        return value <= target
    elif op == "<":
        return value < target
    elif op == "!=":
        return value != target
    return value >= target  # default

"""spells/composite.py — 组合/控制流 Spell。

包括: MetaSpell, ConditionalSpell, RepeatSpell, RandomSpell, FilteredSpell
"""
from __future__ import annotations

import random
import logging
from typing import TYPE_CHECKING, List

from analysis.card.spells import Spell, register_spell, get_spell_class
from analysis.card.condition.conditions import resolve_condition

if TYPE_CHECKING:
    from analysis.card.abilities.model import SpellDesc
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 辅助: 执行 SpellDesc
# ═══════════════════════════════════════════════════════════════

def _execute_desc(
    spell_desc: "SpellDesc",
    state: "GameState",
    source=None,
    target=None,
) -> "GameState":
    """查找 Spell 类并执行。"""
    spell_cls = get_spell_class(spell_desc.spell_class)
    if spell_cls is None:
        log.warning("MetaSpell 聚合子里: 未知类 %r", spell_desc.spell_class)
        return state
    return spell_cls().execute(spell_desc, state, source, target)


# ═══════════════════════════════════════════════════════════════
# MetaSpell — 顺序执行多个子 Spell
# ═══════════════════════════════════════════════════════════════

@register_spell
class MetaSpell(Spell):
    """组合模式 — 顺序执行多个子 Spell。

    JSON:
      {"class": "MetaSpell", "spells": [
          {"class": "DrawSpell", "count": 2},
          {"class": "BuffSpell", "attack": 1, "target": "FRIENDLY_MINIONS"}
      ]}
    """
    def execute(self, desc, state, source=None, target=None):
        if not desc.spells:
            return state
        for sub_desc in desc.spells:
            state = _execute_desc(sub_desc, state, source, target)
            if state is None:
                break
        return state


# ═══════════════════════════════════════════════════════════════
# ConditionalSpell — 条件分支
# ═══════════════════════════════════════════════════════════════

@register_spell
class ConditionalSpell(Spell):
    """条件分支 Spell。

    JSON:
      {"class": "ConditionalSpell",
       "condition": {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}},
       "then_spell": {"class": "DamageSpell", "value": 3, "target": "RANDOM_ENEMY_MINION"},
       "else_spell": null}
    """
    def execute(self, desc, state, source=None, target=None):
        if desc.condition and resolve_condition(desc.condition, state, source):
            if desc.then_spell:
                return _execute_desc(desc.then_spell, state, source, target)
        else:
            if desc.else_spell:
                return _execute_desc(desc.else_spell, state, source, target)
        return state


# ═══════════════════════════════════════════════════════════════
# FilteredSpell — 对每个匹配目标的子 Spell
# ═══════════════════════════════════════════════════════════════

@register_spell
class FilteredSpell(Spell):
    """对符合条件的每个目标执行子 Spell。

    JSON:
      {"class": "FilteredSpell",
       "filter": {"race": "DRAGON"},
       "spell": {"class": "DestroySpell", "target": "TARGET"}}
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.target.selector import resolve_target
        from analysis.card.target.filter import apply_filter

        # 解析父级 target 获得候选列表
        candidates = resolve_target(desc.target or "ALL_MINIONS", state, source, target)
        if desc.filter:
            candidates = apply_filter(candidates, desc.filter, source)

        if not desc.spell:
            return state

        for candidate in candidates:
            state = _execute_desc(desc.spell, state, source, candidate)
        return state


# ═══════════════════════════════════════════════════════════════
# RepeatSpell — 重复执行子 Spell N 次
# ═══════════════════════════════════════════════════════════════

@register_spell
class RepeatSpell(Spell):
    """重复执行子 Spell N 次。

    JSON:
      {"class": "RepeatSpell", "count": 3,
       "spell": {"class": "SummonSpell", "card_id": "CS2_124t"}}
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.value.providers import resolve_value
        count = resolve_value(desc.count or desc.value or 1, state, source)
        if not desc.spell:
            return state
        for _ in range(count):
            state = _execute_desc(desc.spell, state, source, target)
        return state


# ═══════════════════════════════════════════════════════════════
# RandomSpell — 从列表中随机选取子 Spell 执行
# ═══════════════════════════════════════════════════════════════

@register_spell
class RandomSpell(Spell):
    """随机选取一个子 Spell 执行。

    JSON:
      {"class": "RandomSpell",
       "spells": [
         {"class": "DamageSpell", "value": 3, "target": "ENEMY_HERO"},
         {"class": "HealSpell", "value": 3, "target": "FRIENDLY_HERO"}
       ]}
    """
    def execute(self, desc, state, source=None, target=None):
        if not desc.spells:
            return state
        chosen = random.choice(desc.spells)
        return _execute_desc(chosen, state, source, target)


# ═══════════════════════════════════════════════════════════════
# EnqueueSpell — 将子 Spell 注册为后续触发
# ═══════════════════════════════════════════════════════════════

@register_spell
class EnqueueSpell(Spell):
    """将子 Spell 排入后续触发器（延迟效果）。"""
    def execute(self, desc, state, source=None, target=None):
        if not desc.spell:
            return state
        # 存入 state 的待触发队列
        if not hasattr(state, '_pending_spells'):
            state._pending_spells = []
        state._pending_spells.append({
            "spell_desc": desc.spell,
            "source": source,
            "trigger": desc.target or "NEXT_TURN_END",
        })
        return state

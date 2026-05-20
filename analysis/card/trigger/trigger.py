"""trigger/trigger.py — 触发器注册表系统。

管理卡牌上的 all 触发器（SPELLBURST, FRENZY, TURN_END, 亡语等）。
每张卡在入场时注册触发器，在对应事件发生时由游戏引擎派发。

事件列表:
  AFTER_PLAY_MINION    — 打出随从后
  AFTER_PLAY_SPELL     — 打出法术后
  AFTER_ATTACK         — 攻击后
  TURN_START           — 回合开始
  TURN_END             — 回合结束
  DAMAGE_DEALT         — 造成伤害后
  MINION_DIES          — 随从死亡时
  HEAL_DEALT           — 治疗后
  SPELL_CAST           — 施放法术后（用于 SPELLBURST）
  CARD_DRAWN           — 抽牌后
  SUMMONED             — 召唤后
  FRENZY_TRIGGERED     — 狂怒触发
  OUTCAST_TRIGGERED    — 流放触发
  HERO_ATTACK          — 英雄攻击时
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from analysis.card.abilities.model import SpellDesc, TriggerDesc, CardAbility
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TriggerRecord — 已注册的触发器实例
# ═══════════════════════════════════════════════════════════════

class TriggerRecord:
    """一张卡牌注册的一个触发器实例。"""

    def __init__(
        self,
        event: str,
        spell_desc: "SpellDesc",
        source: Any,
        condition: Optional[Dict] = None,
        once: bool = False,
        owner_id: str = "",
    ):
        self.event = event
        self.spell_desc = spell_desc
        self.source = source
        self.condition = condition
        self.once = once
        self.owner_id = owner_id
        self.triggered: bool = False

    def can_trigger(self) -> bool:
        if self.once and self.triggered:
            return False
        return True

    def mark_triggered(self):
        self.triggered = True

    def __repr__(self) -> str:
        return (f"TriggerRecord(event={self.event}, "
                f"spell={self.spell_desc.spell_class}, "
                f"once={self.once}, triggered={self.triggered})")


# ═══════════════════════════════════════════════════════════════
# TriggerRegistry — 全局触发器管理器
# ═══════════════════════════════════════════════════════════════

class TriggerRegistry:
    """全局触发器注册表。

    管理所有已注册的触发器，按事件类型索引。
    GameState 持有此注册表的引用。
    """

    def __init__(self):
        # event → List[TriggerRecord]
        self._triggers: Dict[str, List[TriggerRecord]] = {}

    # ── 注册 ──

    def register(
        self,
        event: str,
        spell_desc: "SpellDesc",
        source: Any = None,
        condition: Optional[Dict] = None,
        once: bool = False,
        owner_id: str = "",
    ) -> TriggerRecord:
        """注册一个触发器。"""
        record = TriggerRecord(event, spell_desc, source, condition, once, owner_id)
        self._triggers.setdefault(event, []).append(record)
        return record

    def register_trigger_desc(
        self,
        td: "TriggerDesc",
        source: Any = None,
        owner_id: str = "",
    ) -> Optional[TriggerRecord]:
        """从 TriggerDesc 注册。"""
        return self.register(
            event=td.event,
            spell_desc=td.spell,
            source=source,
            condition=td.condition,
            once=td.once,
            owner_id=owner_id,
        )

    def register_card_ability(
        self,
        ability: "CardAbility",
        source: Any = None,
        owner_id: str = "",
    ) -> List[TriggerRecord]:
        """从 CardAbility 注册所有触发器。"""
        records = []
        # 亡语 → AFTER_DEATH 事件
        if ability.deathrattle:
            r = self.register("AFTER_DEATH", ability.deathrattle, source, owner_id=owner_id)
            records.append(r)
        # 显式触发器列表
        for td in ability.triggers:
            r = self.register_trigger_desc(td, source, owner_id)
            if r:
                records.append(r)
        return records

    # ── 触发 ──

    def fire(
        self,
        event: str,
        state: "GameState",
        source: Any = None,
        event_target: Any = None,
    ) -> "GameState":
        """触发指定事件的所有注册触发器。"""
        records = self._triggers.get(event, [])
        if not records:
            return state

        from analysis.card.condition.conditions import resolve_condition
        from analysis.card.spells import Spell, get_spell_class

        for record in list(records):
            if not record.can_trigger():
                continue
            # 条件检查
            if record.condition:
                if not resolve_condition(record.condition, state, record.source):
                    continue
            # 执行
            spell_cls = get_spell_class(record.spell_desc.spell_class)
            if spell_cls is None:
                continue
            try:
                state = spell_cls().execute(
                    record.spell_desc, state,
                    source=record.source,
                    target=event_target,
                )
            except Exception as e:
                log.warning("触发器 %s 执行失败: %s", record, e)
            if record.once:
                record.mark_triggered()
        return state

    # ── 清理 ──

    def remove_by_owner(self, owner_id: str):
        """移除指定主人的所有触发器（随从死亡时调用）。"""
        for event in list(self._triggers.keys()):
            self._triggers[event] = [
                r for r in self._triggers[event]
                if r.owner_id != owner_id
            ]
            if not self._triggers[event]:
                del self._triggers[event]

    def remove_all(self):
        """清除所有触发器。"""
        self._triggers.clear()

    def copy(self) -> "TriggerRegistry":
        """深拷贝注册表（搜索树分支用）。"""
        new = TriggerRegistry()
        for event, records in self._triggers.items():
            new._triggers[event] = [
                TriggerRecord(
                    event=r.event,
                    spell_desc=r.spell_desc,
                    source=r.source,
                    condition=r.condition,
                    once=r.once,
                    owner_id=r.owner_id,
                )
                for r in records
            ]
            for r, nr in zip(self._triggers[event], new._triggers[event]):
                nr.triggered = r.triggered
        return new

    @property
    def all_events(self) -> List[str]:
        return list(self._triggers.keys())

    def count(self, event: Optional[str] = None) -> int:
        if event:
            return len(self._triggers.get(event, []))
        return sum(len(v) for v in self._triggers.values())

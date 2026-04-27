#!/usr/bin/env python3
"""power.py — 卡牌能力容器 (CardPower)。

> **本文件功能**: 定义 CardPower dataclass，统一管理一张卡的所有能力定义。
> 参考 RosettaStone/SabberStone 的 Power 类设计。

CardPower 将 card_abilities.json 中的能力按触发类型分组，
提供类型安全的访问接口，替代当前分散的 abilities 列表。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from analysis.card.abilities.spells import Spell

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TriggerDef — 触发器定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class TriggerDef:
    """触发器定义 — 事件驱动的持续效果。

    属性:
        trigger_type: 触发事件类型（如 TURN_START, ON_DAMAGE）
        condition: 触发条件（可选）
        actions: 触发后执行的 Spell 列表
    """
    trigger_type: str = ""
    condition: Optional[dict] = None
    actions: List["Spell"] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# AuraDef — 光环定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class AuraDef:
    """光环定义 — 持续性区域效果。

    属性:
        target: 光环影响的目标范围
        attack: 攻击力加成
        health: 生命值加成
        condition: 生效条件
    """
    target: str = ""
    attack: int = 0
    health: int = 0
    condition: Optional[dict] = None


# ═══════════════════════════════════════════════════════════════
# EnchantDef — 附魔定义
# ═══════════════════════════════════════════════════════════════

@dataclass
class EnchantDef:
    """附魔定义 — 永久或临时的属性修改。

    属性:
        attack: 攻击力修改
        health: 生命值修改
        duration: 持续回合数（0 = 永久）
        target: 作用目标
    """
    attack: int = 0
    health: int = 0
    duration: int = 0
    target: str = "SELF"


# ═══════════════════════════════════════════════════════════════
# CardPower — 卡牌能力容器
# ═══════════════════════════════════════════════════════════════

@dataclass
class CardPower:
    """卡牌能力容器 — 一张卡的所有效果定义。

    参考 RosettaStone 的 Power 类，将卡牌能力按触发类型分组管理。
    每种触发类型对应一组 Spell 实例，执行时顺序调用。

    属性:
        card_id: 卡牌 ID（如 "EX1_066"）
        battlecry: 战吼效果列表
        deathrattle: 亡语效果列表
        combo: 连击效果列表
        spellburst: 法术迸发效果列表
        outcast: 流放效果列表
        frenzy: 暴怒效果列表
        inspire: 激励效果列表
        on_play: 打出时效果（法术牌主效果）
        triggers: 事件触发器列表（光环/被动）
        aura: 光环定义
        enchant: 附魔定义
    """
    card_id: str = ""
    battlecry: List["Spell"] = field(default_factory=list)
    deathrattle: List["Spell"] = field(default_factory=list)
    combo: List["Spell"] = field(default_factory=list)
    spellburst: List["Spell"] = field(default_factory=list)
    outcast: List["Spell"] = field(default_factory=list)
    frenzy: List["Spell"] = field(default_factory=list)
    inspire: List["Spell"] = field(default_factory=list)
    on_play: List["Spell"] = field(default_factory=list)
    triggers: List[TriggerDef] = field(default_factory=list)
    aura: Optional[AuraDef] = None
    enchant: Optional[EnchantDef] = None

    # ── 便捷属性 ──────────────────────────────────────────────

    @property
    def has_battlecry(self) -> bool:
        """是否有战吼效果"""
        return len(self.battlecry) > 0

    @property
    def has_deathrattle(self) -> bool:
        """是否有亡语效果"""
        return len(self.deathrattle) > 0

    @property
    def has_combo(self) -> bool:
        """是否有连击效果"""
        return len(self.combo) > 0

    @property
    def has_spellburst(self) -> bool:
        """是否有法术迸发效果"""
        return len(self.spellburst) > 0

    @property
    def has_outcast(self) -> bool:
        """是否有流放效果"""
        return len(self.outcast) > 0

    @property
    def has_frenzy(self) -> bool:
        """是否有暴怒效果"""
        return len(self.frenzy) > 0

    @property
    def has_inspire(self) -> bool:
        """是否有激励效果"""
        return len(self.inspire) > 0

    @property
    def has_on_play(self) -> bool:
        """是否有打出效果（法术主效果）"""
        return len(self.on_play) > 0

    @property
    def has_triggers(self) -> bool:
        """是否有事件触发器"""
        return len(self.triggers) > 0

    @property
    def has_aura(self) -> bool:
        """是否有光环效果"""
        return self.aura is not None

    @property
    def has_enchant(self) -> bool:
        """是否有附魔效果"""
        return self.enchant is not None

    @property
    def is_empty(self) -> bool:
        """是否没有任何能力定义"""
        return (
            not self.battlecry
            and not self.deathrattle
            and not self.combo
            and not self.spellburst
            and not self.outcast
            and not self.frenzy
            and not self.inspire
            and not self.on_play
            and not self.triggers
            and self.aura is None
            and self.enchant is None
        )

    # ── 工厂方法 ──────────────────────────────────────────────

    @classmethod
    def from_abilities_json(cls, card_id: str, abilities_data: list) -> "CardPower":
        """从 card_abilities.json 的 abilities 数组构建 CardPower。

        将各 ability 的 trigger 分组到对应字段，
        actions 通过 Spell.from_dict() 解析为 Spell 实例。

        参数:
            card_id: 卡牌 ID
            abilities_data: JSON 中的 abilities 数组
        """
        from analysis.card.abilities.spells import Spell

        power = cls(card_id=card_id)

        for ability in abilities_data:
            trigger = ability.get("trigger", "")
            actions_data = ability.get("actions", [])
            spells = [Spell.from_dict(a) for a in actions_data]

            if trigger == "BATTLECRY":
                power.battlecry.extend(spells)
            elif trigger == "DEATHRATTLE":
                power.deathrattle.extend(spells)
            elif trigger == "COMBO":
                power.combo.extend(spells)
            elif trigger == "SPELLBURST":
                power.spellburst.extend(spells)
            elif trigger == "OUTCAST":
                power.outcast.extend(spells)
            elif trigger == "FRENZY":
                power.frenzy.extend(spells)
            elif trigger == "INSPIRE":
                power.inspire.extend(spells)
            elif trigger in ("ON_PLAY", "CAST_SPELL"):
                power.on_play.extend(spells)
            elif trigger == "AURA":
                # 光环效果 — 从 actions 解析 AuraDef
                if spells:
                    power.aura = AuraDef(target="FRIENDLY_MINIONS")
            elif trigger in ("TURN_START", "TURN_END", "ON_ATTACK",
                             "ON_DAMAGE", "ON_SPELL_CAST", "ON_DEATH",
                             "WHENEVER", "AFTER"):
                # 事件触发器
                td = TriggerDef(
                    trigger_type=trigger,
                    condition=ability.get("condition"),
                    actions=spells,
                )
                power.triggers.append(td)
            else:
                # 未知触发器 — 归入 on_play
                log.debug("CardPower: 未知触发器 %r for %s, 归入 on_play",
                          trigger, card_id)
                power.on_play.extend(spells)

        return power

    def __repr__(self) -> str:
        parts = [f"CardPower({self.card_id}"]
        if self.battlecry:
            parts.append(f" battlecry={len(self.battlecry)}")
        if self.deathrattle:
            parts.append(f" deathrattle={len(self.deathrattle)}")
        if self.on_play:
            parts.append(f" on_play={len(self.on_play)}")
        if self.triggers:
            parts.append(f" triggers={len(self.triggers)}")
        if self.aura:
            parts.append(" aura")
        parts.append(")")
        return "".join(parts)

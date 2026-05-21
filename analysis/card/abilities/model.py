"""model.py — v2 CardAbility 递归数据模型。

核心:
  SpellDesc     — 递归嵌套的法术描述（MetaSpell → 子 Spells）
  CardAbility   — 单张卡的完整效果对象，含触发器列表
  TriggerDesc   — 触发器描述（ON_EVENT → SpellDesc）

JSON ↔ SpellDesc 严格一对一映射，无隐式转换。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# SpellDesc — 递归法术描述
# ═══════════════════════════════════════════════════════════════

@dataclass
class SpellDesc:
    """递归法术描述，JSON 的 Python 映射。

    spell_class   — 法术类型名（"DamageSpell", "MetaSpell", …）
    target        — 目标选择器名（"TARGET", "ALL_ENEMY_CHARACTERS", …）
    value         — 字面量 int | ValueProvider dict | None
    spells        — MetaSpell 子法术列表
    then_spell    — ConditionalSpell 的 then 分支
    else_spell    — ConditionalSpell 的 else 分支
    spell         — RepeatSpell/FilteredSpell 的被包装 Spell
    attack_bonus  — BuffSpell 攻击力加成
    health_bonus  — BuffSpell 生命值加成
    card_id       — SummonSpell / EquipWeapon 等用
    condition     — ConditionalSpell 的条件描述 dict
    filter        — 目标过滤器描述 dict
    count         — DrawSpell / RepeatSpell 等用
    keyword       — GiveSpell 关键词
    pool          — DiscoverSpell 发现池
    duration      — EnchantSpell 持续时间
    random_count  — RandomSpell 随机选取数
    on_trigger    — AuraBuffSpell 的触发器描述

    所有字段均为 Optional 以简化构造，校验在 loader 层。
    """
    spell_class: str
    target: Optional[str] = None
    value: Optional[Any] = None
    spells: Optional[List[SpellDesc]] = None
    then_spell: Optional[SpellDesc] = None
    else_spell: Optional[SpellDesc] = None
    spell: Optional[SpellDesc] = None
    attack_bonus: Optional[int] = None
    health_bonus: Optional[int] = None
    card_id: Optional[str] = None
    condition: Optional[Dict] = None
    filter: Optional[Dict] = None
    count: Optional[int] = None
    keyword: Optional[str] = None
    pool: Optional[str] = None
    duration: Optional[int] = None
    random_count: Optional[int] = None
    on_trigger: Optional[TriggerDesc] = None

    # 额外自定义参数兜底
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def __getattr__(self, name: str) -> Any:
        """fallback: 未显式声明的字段从 extra_params 获取。"""
        if name.startswith('_'):
            raise AttributeError(name)
        return self.extra_params.get(name)

    @classmethod
    def from_json(cls, data: Dict) -> SpellDesc:
        """从 JSON dict 递归构造 SpellDesc。"""
        if not isinstance(data, dict):
            raise TypeError(f"SpellDesc.from_json 需要 dict，收到 {type(data).__name__}")

        sc = data.get("class", data.get("spell_class", ""))
        if not sc:
            # 容错: 遇到 {"name": "...", "spell": {"class": "..."}} 格式的包装条目
            #（常见于 ChooseOneSpell 的 choices 数组或 generator 生成的旧格式数据）
            if "spell" in data and isinstance(data["spell"], dict):
                return cls.from_json(data["spell"])
            raise ValueError(f"SpellDesc 缺少 class 字段: {data}")

        # 标准字段
        known = {"class", "spell_class", "target", "value", "spells",
                 "then_spell", "else_spell", "spell", "attack_bonus",
                 "health_bonus", "card_id", "condition", "filter",
                 "count", "keyword", "pool", "duration", "random_count",
                 "on_trigger"}
        extra = {k: v for k, v in data.items() if k not in known}

        return cls(
            spell_class=sc,
            target=data.get("target"),
            value=data.get("value"),
            spells=[cls.from_json(s) for s in data["spells"]] if "spells" in data else None,
            then_spell=cls.from_json(data["then_spell"]) if "then_spell" in data else None,
            else_spell=cls.from_json(data["else_spell"]) if "else_spell" in data else None,
            spell=cls.from_json(data["spell"]) if "spell" in data else None,
            attack_bonus=data.get("attack_bonus") or data.get("attack"),
            health_bonus=data.get("health_bonus") or data.get("health"),
            card_id=data.get("card_id"),
            condition=data.get("condition"),
            filter=data.get("filter"),
            count=data.get("count"),
            keyword=data.get("keyword"),
            pool=data.get("pool"),
            duration=data.get("duration"),
            random_count=data.get("random_count"),
            on_trigger=TriggerDesc.from_json(data["on_trigger"]) if "on_trigger" in data else None,
            extra_params=extra,
        )

    def to_json(self) -> Dict:
        """递归转换为 JSON dict（用于序列化/验证）。"""
        d: Dict = {"class": self.spell_class}
        if self.target is not None:
            d["target"] = self.target
        if self.value is not None:
            d["value"] = self.value
        if self.spells is not None:
            d["spells"] = [s.to_json() for s in self.spells]
        if self.then_spell is not None:
            d["then_spell"] = self.then_spell.to_json()
        if self.else_spell is not None:
            d["else_spell"] = self.else_spell.to_json()
        if self.spell is not None:
            d["spell"] = self.spell.to_json()
        if self.attack_bonus is not None:
            d["attack_bonus"] = self.attack_bonus
        if self.health_bonus is not None:
            d["health_bonus"] = self.health_bonus
        if self.card_id is not None:
            d["card_id"] = self.card_id
        if self.condition is not None:
            d["condition"] = self.condition
        if self.filter is not None:
            d["filter"] = self.filter
        if self.count is not None:
            d["count"] = self.count
        if self.keyword is not None:
            d["keyword"] = self.keyword
        if self.pool is not None:
            d["pool"] = self.pool
        if self.duration is not None:
            d["duration"] = self.duration
        if self.random_count is not None:
            d["random_count"] = self.random_count
        if self.on_trigger is not None:
            d["on_trigger"] = self.on_trigger.to_json()
        d.update(self.extra_params)
        return d


# ═══════════════════════════════════════════════════════════════
# TriggerDesc — 触发器描述
# ═══════════════════════════════════════════════════════════════

@dataclass
class TriggerDesc:
    """触发器描述。

    event      — 事件名（"AFTER_PLAY_MINION", "TURN_END", "DAMAGE_DEALT", …）
    condition  — 触发条件 dict（可选）
    spell      — 触发时执行的 SpellDesc
    once       — 是否一次性（已触发后不再触发）
    """
    event: str
    spell: SpellDesc
    condition: Optional[Dict] = None
    once: bool = False

    @classmethod
    def from_json(cls, data: Dict) -> TriggerDesc:
        return cls(
            event=data["event"],
            spell=SpellDesc.from_json(data["spell"]),
            condition=data.get("condition"),
            once=data.get("once", False),
        )

    def to_json(self) -> Dict:
        d: Dict = {"event": self.event, "spell": self.spell.to_json()}
        if self.condition:
            d["condition"] = self.condition
        if self.once:
            d["once"] = True
        return d


# ═══════════════════════════════════════════════════════════════
# CardAbility — 单张卡的完整效果
# ═══════════════════════════════════════════════════════════════

@dataclass
class CardAbility:
    """一张卡的完整效果对象。

    on_play      — 打出时执行（法术效果/战吼）
    deathrattle  — 亡语
    aura         — 光环效果
    triggers     — 其他触发器（SPELLBURST, FRENZY, INSPIRE, 自定义事件等）
    combo        — 连击效果
    outcast      — 流放效果

    所有字段均为 Optional，无效果则为 None。
    """
    on_play: Optional[SpellDesc] = None
    deathrattle: Optional[SpellDesc] = None
    aura: Optional[SpellDesc] = None
    triggers: List[TriggerDesc] = field(default_factory=list)
    combo: Optional[SpellDesc] = None
    outcast: Optional[SpellDesc] = None

    @classmethod
    def empty(cls) -> CardAbility:
        """空效果对象。"""
        return cls()

    @property
    def has_any(self) -> bool:
        """是否有任何效果（用于快速判断是否需要进入 SpellExecutor）。"""
        return bool(self.on_play or self.deathrattle or self.aura
                    or self.triggers or self.combo or self.outcast)

    def to_json(self) -> Dict:
        """序列化为 JSON dict。"""
        d: Dict = {}
        if self.on_play:
            d["ON_PLAY"] = self.on_play.to_json()
        if self.deathrattle:
            d["DEATHRATTLE"] = self.deathrattle.to_json()
        if self.aura:
            d["AURA"] = self.aura.to_json()
        if self.combo:
            d["COMBO"] = self.combo.to_json()
        if self.outcast:
            d["OUTCAST"] = self.outcast.to_json()
        if self.triggers:
            d["TRIGGERS"] = [t.to_json() for t in self.triggers]
        return d

    @classmethod
    def from_json(cls, data: Dict) -> CardAbility:
        """从 JSON dict 解析 CardAbility。

        顶层 key 映射:
          ON_PLAY / BATTLECRY → on_play
          DEATHRATTLE         → deathrattle
          AURA                → aura
          COMBO               → combo
          OUTCAST             → outcast
          TRIGGERS            → triggers[]
        """
        on_play_data = data.get("ON_PLAY") or data.get("BATTLECRY")
        return cls(
            on_play=SpellDesc.from_json(on_play_data) if on_play_data else None,
            deathrattle=SpellDesc.from_json(data["DEATHRATTLE"]) if "DEATHRATTLE" in data else None,
            aura=SpellDesc.from_json(data["AURA"]) if "AURA" in data else None,
            combo=SpellDesc.from_json(data["COMBO"]) if "COMBO" in data else None,
            outcast=SpellDesc.from_json(data["OUTCAST"]) if "OUTCAST" in data else None,
            triggers=[TriggerDesc.from_json(t) for t in data.get("TRIGGERS", [])],
        )

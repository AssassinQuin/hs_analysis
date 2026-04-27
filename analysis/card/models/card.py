# -*- coding: utf-8 -*-
"""Card — 炉石卡牌统一数据模型

项目中有两种卡牌表示：
1. hsdb.py 的 Dict（轻量级，纯数据索引） — 用于快速池查询、DB操作
2. 本文件 Card dataclass（面向对象，带行为方法） — 用于评分引擎、搜索树

通过 from_hsdb_dict() 工厂方法从 HSCardDB 数据源构建。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional


@dataclass
class Card:
    """炉石卡牌统一数据模型

    字段覆盖所有卡牌类型（随从、法术、武器、英雄、地点）。
    部分字段仅对特定类型有意义（如 health 仅对随从有效）。
    """
    card_id: str = ""
    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    original_cost: int = 0
    card_type: str = ""
    attack: int = 0
    health: int = 0
    score: float = 0.0
    text: str = ""
    rarity: str = ""
    card_class: str = ""
    race: str = ""
    mechanics: list = None
    set_name: str = ""
    ename: str = ""
    english_text: str = ""
    overload: int = 0
    spell_damage: int = 0
    armor: int = 0
    durability: int = 0
    spell_school: str = ""
    roles: frozenset = field(default_factory=frozenset)

    def __post_init__(self):
        if self.mechanics is None:
            self.mechanics = []
        if not self.roles:
            try:
                from analysis.card.data.card_roles import classify_card_roles
                self.roles = frozenset(classify_card_roles(self))
            except Exception:
                self.roles = frozenset()
        # 延迟加载字段初始化
        self._power = None

    def copy(self) -> "Card":
        """创建 Card 的浅拷贝，保留 _power 等非 dataclass 字段。"""
        new_card = replace(self)
        # 保留延迟加载的 _power 属性
        power = getattr(self, '_power', None)
        if power is not None:
            new_card._power = power
        return new_card
        self._abilities = None
        self._power = None

    @property
    def abilities(self):
        """旧版能力列表（向后兼容）。优先使用 power 属性。"""
        if self._abilities is None:
            try:
                from analysis.card.abilities.loader import load_abilities
                loaded = load_abilities(self.card_id)
                if loaded:
                    self._abilities = loaded
                else:
                    self._abilities = []
            except Exception:
                self._abilities = []
        return self._abilities

    @abilities.setter
    def abilities(self, value):
        self._abilities = value

    @property
    def power(self):
        """卡牌能力容器 — 按触发类型分组管理的 Spell 列表。

        延迟加载: 首次访问时从 card_abilities.json 读取并构建 CardPower。
        """
        if self._power is None:
            try:
                from analysis.card.abilities.loader import load_card_power
                from analysis.card.abilities.power import CardPower
                data = load_card_power(self.card_id)
                if data and data.get("abilities"):
                    self._power = CardPower.from_abilities_json(
                        self.card_id, data["abilities"]
                    )
                else:
                    self._power = CardPower(card_id=self.card_id)
            except Exception:
                from analysis.card.abilities.power import CardPower
                self._power = CardPower(card_id=self.card_id)
        return self._power

    @power.setter
    def power(self, value):
        self._power = value

    @property
    def mechanics_set(self) -> set:
        return set(self.mechanics or [])

    def has_mechanic(self, keyword: str) -> bool:
        return keyword in (self.mechanics or [])

    @property
    def has_battlecry(self) -> bool:
        """是否有战吼能力（从 mechanics 或 power 判断）"""
        if "BATTLECRY" in (self.mechanics or []):
            return True
        return self.power.has_battlecry

    @property
    def has_deathrattle(self) -> bool:
        """是否有亡语能力"""
        if "DEATHRATTLE" in (self.mechanics or []):
            return True
        return self.power.has_deathrattle

    @property
    def has_combo(self) -> bool:
        """是否有连击能力"""
        if "COMBO" in (self.mechanics or []):
            return True
        return self.power.has_combo

    @property
    def has_spellburst(self) -> bool:
        """是否有法术迸发"""
        return self.power.has_spellburst

    @property
    def has_outcast(self) -> bool:
        """是否有流放"""
        if "OUTCAST" in (self.mechanics or []):
            return True
        return self.power.has_outcast

    @property
    def has_frenzy(self) -> bool:
        """是否有暴怒"""
        return self.power.has_frenzy

    def get_effects(self):
        from analysis.card.data.card_effects import get_effects
        return get_effects(self)

    def compute_mechanics(self) -> list:
        # card_cleaner removed in Phase 0 — return existing mechanics
        return self.mechanics or []

    def effective_overload(self) -> int:
        if self.overload > 0:
            return self.overload
        import re
        m = re.search(r"Overload\s*\(\s*(\d+)\s*\)", self.english_text or self.text or "")
        return int(m.group(1)) if m else 0

    def effective_armor(self) -> int:
        if self.armor > 0:
            return self.armor
        import re
        m = re.search(r"Gain\s+(\d+)\s+Armor", self.english_text or self.text or "")
        return int(m.group(1)) if m else 0

    def effective_spell_damage(self) -> int:
        return self.spell_damage

    def total_damage(self) -> int:
        eff = self.get_effects()
        return eff.damage + eff.random_damage

    @property
    def is_minion(self) -> bool:
        return (self.card_type or "").upper() == "MINION"

    @property
    def is_spell(self) -> bool:
        return (self.card_type or "").upper() == "SPELL"

    @property
    def is_weapon(self) -> bool:
        return (self.card_type or "").upper() == "WEAPON"

    @property
    def is_hero(self) -> bool:
        return (self.card_type or "").upper() == "HERO"

    @property
    def is_location(self) -> bool:
        return (self.card_type or "").upper() == "LOCATION"

    @property
    def identity_key(self) -> str:
        if self.card_id:
            return self.card_id
        if self.dbf_id:
            return str(self.dbf_id)
        return self.name or ""

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.ename:
            return self.ename
        if self.card_id:
            return self.card_id
        return str(self.dbf_id) if self.dbf_id else "???"

    @classmethod
    def from_hsdb_dict(cls, data: dict) -> "Card":
        return cls(
            card_id=data.get("cardId", ""),
            dbf_id=data.get("dbfId", 0),
            name=data.get("name", ""),
            cost=data.get("cost", 0),
            original_cost=data.get("cost", 0),
            card_type=data.get("type", ""),
            attack=data.get("attack", 0),
            health=data.get("health", 0),
            text=data.get("text", ""),
            rarity=data.get("rarity", ""),
            card_class=data.get("cardClass", ""),
            race=data.get("race", ""),
            mechanics=data.get("mechanics", []),
            set_name=data.get("set", ""),
            ename=data.get("englishName", ""),
            english_text=data.get("englishText", ""),
            overload=data.get("overload", 0),
            spell_damage=data.get("spellDamage", 0),
            armor=data.get("armor", 0),
            durability=data.get("durability", 0),
            spell_school=data.get("spellSchool", ""),
        )

    def to_dict(self) -> dict:
        return {
            "dbf_id": self.dbf_id,
            "name": self.name,
            "cost": self.cost,
            "original_cost": self.original_cost,
            "card_type": self.card_type,
            "attack": self.attack,
            "health": self.health,
            "score": self.score,
            "text": self.text,
            "rarity": self.rarity,
            "card_class": self.card_class,
            "race": self.race,
            "mechanics": self.mechanics,
            "set_name": self.set_name,
        }

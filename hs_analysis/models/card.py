# -*- coding: utf-8 -*-
"""统一卡牌数据模型 — Card dataclass + factory methods.

Provides a standardized Card dataclass used across all modules.
Factory methods convert from different data source formats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Card:
    """统一卡牌数据模型.

    Fields match the original Card from game_state.py for backward compatibility.
    Additional factory methods support conversion from different data sources.
    """

    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    original_cost: int = 0
    card_type: str = ""  # MINION, SPELL, WEAPON, HERO
    attack: int = 0
    health: int = 0
    v2_score: float = 0.0
    l6_score: float = 0.0
    v7_score: float = 0.0
    text: str = ""

    # ── Additional fields from unified data sources ──
    rarity: str = ""
    card_class: str = ""
    race: str = ""
    mechanics: list = None  # type: list[str]
    set_name: str = ""
    ename: str = ""

    def __post_init__(self):
        if self.mechanics is None:
            self.mechanics = []

    @classmethod
    def from_hsjson(cls, data: dict) -> "Card":
        """从 HearthstoneJSON 格式构建 Card.

        Field mapping: dbfId -> dbf_id, type -> card_type, cardClass -> card_class
        """
        return cls(
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
            ename=data.get("ename", ""),
        )

    @classmethod
    def from_unified(cls, data: dict) -> "Card":
        """从 unified_standard.json 格式构建 Card."""
        return cls(
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
            ename=data.get("ename", ""),
        )

    @classmethod
    def from_iyingdi(cls, data: dict) -> "Card":
        """从 iyingdi 数据格式构建 Card.

        Field mapping: gameid -> dbf_id
        """
        return cls(
            dbf_id=data.get("gameid", data.get("dbf_id", 0)),
            name=data.get("name", ""),
            cost=data.get("cost", 0),
            original_cost=data.get("cost", 0),
            card_type=data.get("type", ""),
            attack=data.get("attack", 0),
            health=data.get("health", 0),
            text=data.get("text", ""),
            rarity=data.get("rarity", ""),
            card_class=data.get("cardClass", ""),
        )

    def to_dict(self) -> dict:
        """转换为字典格式 (用于 JSON 序列化)."""
        return {
            "dbf_id": self.dbf_id,
            "name": self.name,
            "cost": self.cost,
            "original_cost": self.original_cost,
            "card_type": self.card_type,
            "attack": self.attack,
            "health": self.health,
            "v2_score": self.v2_score,
            "l6_score": self.l6_score,
            "v7_score": self.v7_score,
            "text": self.text,
            "rarity": self.rarity,
            "card_class": self.card_class,
            "race": self.race,
            "mechanics": self.mechanics,
            "set_name": self.set_name,
        }

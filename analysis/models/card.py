# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Card:
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

    def __post_init__(self):
        if self.mechanics is None:
            self.mechanics = []

    @classmethod
    def from_cardxml(cls, card_xml) -> "Card":
        from hearthstone.enums import CardType, CardClass, Race, Rarity

        card_type = card_xml.type.name if card_xml.type else ""
        card_class = card_xml.card_class.name if card_xml.card_class else "NEUTRAL"
        rarity = card_xml.rarity.name if card_xml.rarity else ""
        races = " ".join(r.name for r in (card_xml.races or []) if r) if card_xml.races else ""
        if not races and card_xml.race:
            races = card_xml.race.name

        mechanics = []
        _MECH_MAP = {
            "taunt": "TAUNT", "charge": "CHARGE", "divine_shield": "DIVINE_SHIELD",
            "battlecry": "BATTLECRY", "deathrattle": "DEATHRATTLE",
            "windfury": "WINDFURY", "lifesteal": "LIFESTEAL",
            "poisonous": "POISONOUS", "rush": "RUSH", "reborn": "REBORN",
            "discover": "DISCOVER", "secret": "SECRET", "quest": "QUEST",
            "sidequest": "SIDE_QUEST", "outcast": "OUTCAST",
            "spellburst": "SPELLBURST", "combo": "COMBO",
            "choose_one": "CHOOSE_ONE", "overkill": "OVERKILL",
            "inspire": "INSPIRE", "corrupt": "CORRUPT",
            "echo": "ECHO", "twinspell": "TWINSPELL",
            "tradeable": "TRADEABLE", "dredge": "DREDGE",
            "colossal": "COLOSSAL", "titan": "TITAN",
            "forge": "FORGE", "overheal": "OVERHEAL",
            "miniaturize": "MINIATURIZE", "frenzy": "FRENZY",
            "magnetic": "MAGNETIC", "immune": "IMMUNE",
        }
        for prop, name in _MECH_MAP.items():
            if getattr(card_xml, prop, False):
                mechanics.append(name)
        from hearthstone.enums import GameTag
        _TAG_MECHS = {
            GameTag.OVERLOAD: "OVERLOAD", GameTag.SPELLPOWER: "SPELLPOWER",
            GameTag.FREEZE: "FREEZE", GameTag.SILENCE: "SILENCE",
            GameTag.TRIGGER_VISUAL: "TRIGGER_VISUAL",
            GameTag.IMBUE: "IMBUE", GameTag.EXCAVATE: "EXCAVATE",
            GameTag.AURA: "AURA",
        }
        for tag, name in _TAG_MECHS.items():
            if card_xml.tags.get(tag, 0) > 0 and name not in mechanics:
                mechanics.append(name)
        mechanics.sort()

        return cls(
            dbf_id=card_xml.dbf_id,
            name=card_xml.name or "",
            cost=card_xml.cost or 0,
            original_cost=card_xml.cost or 0,
            card_type=card_type,
            attack=card_xml.atk or 0,
            health=card_xml.health or 0,
            text=card_xml.description or "",
            rarity=rarity,
            card_class=card_class,
            race=races,
            mechanics=mechanics,
            set_name=card_xml.card_set.name if card_xml.card_set else "",
            ename=card_xml.english_name or "",
        )

    @classmethod
    def from_hsdb_dict(cls, data: dict) -> "Card":
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
            ename=data.get("englishName", ""),
        )

    @classmethod
    def from_hsjson(cls, data: dict) -> "Card":
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

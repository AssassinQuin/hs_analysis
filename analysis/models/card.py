# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class MinionData:
    """Minion-specific static data."""
    attack: int = 0
    health: int = 0


@dataclass(frozen=True)
class SpellData:
    """Spell-specific static data."""
    spell_damage: int = 0
    spell_school: str = ""


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
    overload: int = 0
    spell_damage: int = 0
    armor: int = 0
    durability: int = 0
    spell_school: str = ""
    minion_data: Optional[MinionData] = None
    spell_data: Optional[SpellData] = None

    def __post_init__(self):
        if self.mechanics is None:
            self.mechanics = []
        # Populate component data objects from direct fields when not explicitly provided
        if self.minion_data is None and (self.attack > 0 or self.health > 0):
            self.minion_data = MinionData(attack=self.attack, health=self.health)
        elif self.minion_data is not None:
            # Sync direct fields from explicitly-provided minion_data
            self.attack = self.minion_data.attack
            self.health = self.minion_data.health
        if self.spell_data is None and (self.spell_damage > 0 or self.spell_school):
            self.spell_data = SpellData(spell_damage=self.spell_damage, spell_school=self.spell_school)
        elif self.spell_data is not None:
            # Sync direct fields from explicitly-provided spell_data
            self.spell_damage = self.spell_data.spell_damage
            self.spell_school = self.spell_data.spell_school

    # ── Mechanics helpers ──────────────────────────────────────────

    @property
    def mechanics_set(self) -> set:
        return set(self.mechanics or [])

    def has_mechanic(self, keyword: str) -> bool:
        return keyword in (self.mechanics or [])

    # ── Effect parsing ─────────────────────────────────────────────

    def get_effects(self):
        """Return structured CardEffects for this card."""
        from analysis.data.card_effects import get_effects
        return get_effects(self)

    def compute_mechanics(self) -> list:
        """Re-extract mechanics from text + existing tags via card_cleaner."""
        from analysis.data.card_cleaner import extract_mechanics
        self.mechanics = extract_mechanics(
            self.text, self.mechanics, self.card_type,
        )
        return self.mechanics

    # ── Structured field accessors (with text fallback) ────────────

    def effective_overload(self) -> int:
        """Overload value: structured field first, text regex fallback."""
        if self.overload > 0:
            return self.overload
        import re
        m = re.search(r"过载[：:]\s*[（(]\s*(\d+)\s*[）)]", self.text or "")
        return int(m.group(1)) if m else 0

    def effective_armor(self) -> int:
        """Armor value: structured field first, text regex fallback."""
        if self.armor > 0:
            return self.armor
        import re
        m = re.search(r"获得\s*(\d+)\s*点护甲", self.text or "")
        return int(m.group(1)) if m else 0

    def effective_spell_damage(self) -> int:
        return self.spell_damage

    def total_damage(self) -> int:
        """Quick accessor: direct + random damage."""
        eff = self.get_effects()
        return eff.damage + eff.random_damage

    # ── Type predicates ────────────────────────────────────────────

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

    # ── Construction from external formats ─────────────────────────

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

        overload_val = card_xml.tags.get(GameTag.OVERLOAD, 0) if hasattr(card_xml, "tags") else 0
        spellpower_val = card_xml.tags.get(GameTag.SPELLPOWER, 0) if hasattr(card_xml, "tags") else 0

        atk_val = card_xml.atk or 0
        health_val = card_xml.health or 0

        minion_data = MinionData(attack=atk_val, health=health_val) if atk_val > 0 or health_val > 0 or card_type in ("MINION", "WEAPON") else None
        spell_data = SpellData(spell_damage=spellpower_val) if spellpower_val > 0 or card_type == "SPELL" else None

        return cls(
            dbf_id=card_xml.dbf_id,
            name=card_xml.name or "",
            cost=card_xml.cost or 0,
            original_cost=card_xml.cost or 0,
            card_type=card_type,
            attack=atk_val,
            health=health_val,
            text=card_xml.description or "",
            rarity=rarity,
            card_class=card_class,
            race=races,
            mechanics=mechanics,
            set_name=card_xml.card_set.name if card_xml.card_set else "",
            ename=card_xml.english_name or "",
            overload=overload_val,
            spell_damage=spellpower_val,
            armor=card_xml.armor or 0,
            durability=card_xml.durability or 0,
            minion_data=minion_data,
            spell_data=spell_data,
        )

    @classmethod
    def from_hsdb_dict(cls, data: dict) -> "Card":
        atk_val = data.get("attack", 0)
        health_val = data.get("health", 0)
        card_type = data.get("type", "")
        spell_damage_val = data.get("spellDamage", 0)
        spell_school_val = data.get("spellSchool", "")

        minion_data = MinionData(attack=atk_val, health=health_val) if atk_val > 0 or health_val > 0 or card_type in ("MINION", "WEAPON") else None
        spell_data = SpellData(spell_damage=spell_damage_val, spell_school=spell_school_val) if spell_damage_val > 0 or card_type == "SPELL" else None

        return cls(
            dbf_id=data.get("dbfId", 0),
            name=data.get("name", ""),
            cost=data.get("cost", 0),
            original_cost=data.get("cost", 0),
            card_type=card_type,
            attack=atk_val,
            health=health_val,
            text=data.get("text", ""),
            rarity=data.get("rarity", ""),
            card_class=data.get("cardClass", ""),
            race=data.get("race", ""),
            mechanics=data.get("mechanics", []),
            set_name=data.get("set", ""),
            ename=data.get("englishName", ""),
            overload=data.get("overload", 0),
            spell_damage=spell_damage_val,
            armor=data.get("armor", 0),
            durability=data.get("durability", 0),
            spell_school=spell_school_val,
            minion_data=minion_data,
            spell_data=spell_data,
        )

    @classmethod
    def from_hsjson(cls, data: dict) -> "Card":
        atk_val = data.get("attack", 0)
        health_val = data.get("health", 0)
        card_type = data.get("type", "")
        spell_damage_val = data.get("spellDamage", 0)
        spell_school_val = data.get("spellSchool", "")

        minion_data = MinionData(attack=atk_val, health=health_val) if atk_val > 0 or health_val > 0 or card_type in ("MINION", "WEAPON") else None
        spell_data = SpellData(spell_damage=spell_damage_val, spell_school=spell_school_val) if spell_damage_val > 0 or card_type == "SPELL" else None

        return cls(
            dbf_id=data.get("dbfId", 0),
            name=data.get("name", ""),
            cost=data.get("cost", 0),
            original_cost=data.get("cost", 0),
            card_type=card_type,
            attack=atk_val,
            health=health_val,
            text=data.get("text", ""),
            rarity=data.get("rarity", ""),
            card_class=data.get("cardClass", ""),
            race=data.get("race", ""),
            mechanics=data.get("mechanics", []),
            set_name=data.get("set", ""),
            ename=data.get("ename", ""),
            overload=data.get("overload", 0),
            spell_damage=spell_damage_val,
            armor=data.get("armor", 0),
            durability=data.get("durability", 0),
            spell_school=spell_school_val,
            minion_data=minion_data,
            spell_data=spell_data,
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

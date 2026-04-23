# -*- coding: utf-8 -*-
"""entity.py — Unified entity identity and zone management for Hearthstone AI.

Provides the foundational types for the game engine refactoring:
- EntityId: unique, hashable identity for every game object
- Zone: IntEnum matching Hearthstone zone constants
- CardInstance: mutable simulation wrapper around immutable Card data,
  tracking zone placement, enchantments, and effective stats
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional

from analysis.models.card import Card
from analysis.search.enchantment import Enchantment

__all__ = ["EntityId", "Zone", "CardInstance", "next_entity_id"]


# ===================================================================
# EntityId — unique identity token
# ===================================================================

_next_id: int = 0


@dataclass(frozen=True, slots=True)
class EntityId:
    """Unique, hashable identity for a game entity."""
    value: int

    def __str__(self) -> str:
        return f"E{self.value}"


def next_entity_id() -> EntityId:
    """Return the next unique EntityId from a module-level counter."""
    global _next_id
    _next_id += 1
    return EntityId(_next_id)


# ===================================================================
# Zone enum
# ===================================================================

class Zone(IntEnum):
    """Hearthstone zone constants (matches hs_enums.py)."""
    INVALID = 0
    PLAY = 1
    DECK = 2
    HAND = 3
    GRAVEYARD = 4
    SETASIDE = 6
    SECRET = 7
    REMOVED = 8


# ===================================================================
# CardInstance — mutable simulation wrapper
# ===================================================================

@dataclass(slots=True)
class CardInstance:
    """A mutable card instance during simulation.

    Wraps an immutable Card reference with zone, controller, enchantment,
    and effective-stat tracking.  Properties fall back to the base Card
    values when no override is set.
    """
    entity_id: EntityId
    card: Card
    zone: Zone = Zone.INVALID
    controller: int = 0
    enchantments: List[Enchantment] = field(default_factory=list)
    current_cost: Optional[int] = None
    current_attack: Optional[int] = None
    current_health: Optional[int] = None
    max_health: Optional[int] = None
    attacks_this_turn: int = 0
    turn_played: int = 0

    # -- Effective stat properties -----------------------------------------

    @property
    def effective_cost(self) -> int:
        """Mana cost, falling back to the card's base cost."""
        return self.current_cost if self.current_cost is not None else self.card.cost

    @property
    def effective_attack(self) -> int:
        """Current attack, falling back to the card's base attack."""
        return self.current_attack if self.current_attack is not None else self.card.attack

    @property
    def effective_health(self) -> int:
        """Current health, falling back to the card's base health."""
        return self.current_health if self.current_health is not None else self.card.health

    @property
    def effective_max_health(self) -> int:
        """Maximum health, falling back to the card's base health."""
        return self.max_health if self.max_health is not None else self.card.health

    # -- Card delegate properties ------------------------------------------

    @property
    def name(self) -> str:
        return self.card.name

    @property
    def dbf_id(self) -> int:
        return self.card.dbf_id

    # -- Copy (shallow, for simulation branching) -------------------------

    def copy(self) -> CardInstance:
        """Return a shallow copy suitable for simulation branching.

        The *card* reference is shared (immutable).  Enchantments list is
        shallow-copied so the branch can diverge.
        """
        return CardInstance(
            entity_id=self.entity_id,
            card=self.card,
            zone=self.zone,
            controller=self.controller,
            enchantments=list(self.enchantments),
            current_cost=self.current_cost,
            current_attack=self.current_attack,
            current_health=self.current_health,
            max_health=self.max_health,
            attacks_this_turn=self.attacks_this_turn,
            turn_played=self.turn_played,
        )

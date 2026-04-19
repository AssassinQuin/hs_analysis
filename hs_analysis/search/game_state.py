"""GameState data structure for Hearthstone AI decision engine.

Represents the full game state and supports copy() for search tree branching.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Weapon:
    """Equipped weapon."""

    attack: int = 0
    health: int = 0  # durability
    name: str = ""


@dataclass
class Minion:
    """A minion on the board."""

    dbf_id: int = 0
    name: str = ""
    attack: int = 0
    health: int = 0
    max_health: int = 0
    cost: int = 0
    can_attack: bool = False
    has_divine_shield: bool = False
    has_taunt: bool = False
    has_stealth: bool = False
    has_windfury: bool = False
    has_rush: bool = False
    has_charge: bool = False
    has_poisonous: bool = False
    enchantments: list = field(default_factory=list)
    owner: str = "friendly"  # or "enemy"


@dataclass
class HeroState:
    """Hero + weapon state."""

    hp: int = 30
    armor: int = 0
    hero_class: str = ""
    weapon: Optional[Weapon] = None
    hero_power_used: bool = False


@dataclass
class ManaState:
    """Mana availability."""

    available: int = 0
    overloaded: int = 0
    max_mana: int = 0
    overload_next: int = 0


@dataclass
class OpponentState:
    """Opponent's visible / inferred state."""

    hero: HeroState = field(default_factory=HeroState)
    board: List[Minion] = field(default_factory=list)
    hand_count: int = 0
    secrets: list = field(default_factory=list)
    deck_remaining: int = 15
    locked_deck_id: Optional[int] = None  # Bayesian lock
    deck_confidence: float = 0.0


@dataclass
class GameState:
    """Full game state for AI decision-making.

    Supports deep-copy for search-tree branching.
    """

    hero: HeroState = field(default_factory=HeroState)
    mana: ManaState = field(default_factory=ManaState)
    board: List[Minion] = field(default_factory=list)
    hand: list = field(default_factory=list)  # List of Card
    deck_list: Optional[List] = None  # remaining cards in player's deck (for draw probability)
    deck_remaining: int = 15
    opponent: OpponentState = field(default_factory=OpponentState)
    turn_number: int = 1
    cards_played_this_turn: list = field(default_factory=list)
    fatigue_damage: int = 0

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def copy(self) -> "GameState":
        """Deep copy for search-tree branching."""
        return copy.deepcopy(self)

    def is_lethal(self) -> bool:
        """True if opponent hero HP + armor <= 0."""
        opp = self.opponent.hero
        return (opp.hp + opp.armor) <= 0

    def board_full(self) -> bool:
        """True if the friendly board already has 7 minions."""
        return len(self.board) >= 7

    def has_taunt_on_board(self) -> bool:
        """True if any friendly minion has taunt."""
        return any(m.has_taunt for m in self.board)

    def get_total_attack(self) -> int:
        """Sum of friendly minion attacks + weapon attack (if equipped)."""
        total = sum(m.attack for m in self.board)
        if self.hero.weapon is not None:
            total += self.hero.weapon.attack
        return total

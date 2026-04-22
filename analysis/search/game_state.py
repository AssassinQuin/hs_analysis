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
    has_lifesteal: bool = False  # lifesteal: heal hero for damage dealt
    has_reborn: bool = False  # reborn: resummon as 1/1 on death
    has_immune: bool = False  # immune: prevents all damage
    cant_attack: bool = False  # cannot attack (e.g. Watcher)
    is_dormant: bool = False  # dormant: can't attack until awaken
    dormant_turns_remaining: int = 0  # turns until dormant minion awakens
    spell_power: int = 0  # spell damage +N
    has_attacked_once: bool = False  # windfury first-attack tracking
    frozen_until_next_turn: bool = False  # freeze effect
    enchantments: list = field(default_factory=list)
    owner: str = "friendly"  # or "enemy"


@dataclass
class HeroState:
    """Hero + weapon state."""

    hp: int = 30
    max_hp: int = 30
    armor: int = 0
    hero_class: str = ""
    weapon: Optional[Weapon] = None
    hero_power_used: bool = False
    imbue_level: int = 0
    is_immune: bool = False
    hero_power_cost: int = 2
    hero_power_damage: int = 0
    is_hero_card: bool = False


@dataclass
class ManaModifier:
    modifier_type: str
    value: int
    scope: str
    used: bool = False


@dataclass
class ManaState:
    """Mana availability."""

    available: int = 0
    overloaded: int = 0
    max_mana: int = 0
    overload_next: int = 0
    max_mana_cap: int = 10
    modifiers: List[ManaModifier] = field(default_factory=list)

    def effective_cost(self, card) -> int:
        from analysis.models.card import Card

        base = card.cost if isinstance(card, Card) else int(card)
        card_type = (
            getattr(card, "card_type", "").upper() if isinstance(card, Card) else ""
        )
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card_type == "SPELL":
                base = max(0, base - mod.value)
            elif mod.scope == "next_minion" and card_type == "MINION":
                base = max(0, base - mod.value)
            elif mod.scope == "this_turn":
                base = max(0, base - mod.value)
        return base

    def consume_modifiers(self, card) -> None:
        from analysis.models.card import Card

        card_type = (
            getattr(card, "card_type", "").upper() if isinstance(card, Card) else ""
        )
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card_type == "SPELL":
                mod.used = True
                return
            if mod.scope == "next_minion" and card_type == "MINION":
                mod.used = True
                return
            if mod.scope == "this_turn":
                mod.used = True
                return

    def add_modifier(self, modifier_type: str, value: int, scope: str) -> None:
        self.modifiers.append(
            ManaModifier(
                modifier_type=modifier_type,
                value=value,
                scope=scope,
            )
        )


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
    locations: list = field(default_factory=list)  # List[Location]
    hand: list = field(default_factory=list)  # List of Card
    deck_list: Optional[List] = (
        None  # remaining cards in player's deck (for draw probability)
    )
    deck_remaining: int = 15
    opponent: OpponentState = field(default_factory=OpponentState)
    turn_number: int = 1
    cards_played_this_turn: list = field(default_factory=list)
    fatigue_damage: int = 0
    herald_count: int = 0  # Herald mechanic counter
    last_turn_races: set = field(default_factory=set)  # Kindred: races played last turn
    last_turn_schools: set = field(
        default_factory=set
    )  # Kindred: spell schools played last turn
    active_quests: list = field(default_factory=list)  # Active quest tracking
    corpses: int = 0  # DK Corpse resource
    kindred_double_next: bool = False  # Kindred: next 延系 triggers twice
    last_played_card: dict | None = (
        None  # Last card played (for rune/conditional checks)
    )
    _defer_deaths: bool = (
        False  # Phase death delay: defer death resolution to phase end
    )
    _pending_dead_friendly: list = field(
        default_factory=list
    )  # Deferred dead friendly minions
    _pending_dead_enemy: list = field(
        default_factory=list
    )  # Deferred dead enemy minions

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

    def flush_deaths(self) -> "GameState":
        """Process all pending deaths (outermost phase death delay).

        Called at END_TURN or when the phase completes. Applies reborn,
        deathrattles, corpse gain, and removes dead minions.
        """
        try:
            from analysis.search.deathrattle import resolve_deaths

            self = resolve_deaths(self)
        except Exception:
            pass

        # Reborn for friendly minions
        for m in list(self.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1
                m.has_attacked_once = False
                m.can_attack = False
                m.has_divine_shield = False
                m.has_stealth = False
                m.has_taunt = False

        # Reborn for enemy minions
        for m in list(self.opponent.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1

        self.board = [m for m in self.board if m.health > 0]
        self.opponent.board = [m for m in self.opponent.board if m.health > 0]

        # Corpse gain
        try:
            from analysis.search.corpse import gain_corpses, has_double_corpse_gen

            amount = 2 if has_double_corpse_gen(self) else 1
            self = gain_corpses(self, amount)
        except Exception:
            pass

        # Aura recompute
        try:
            from analysis.search.aura_engine import recompute_auras

            self = recompute_auras(self)
        except Exception:
            pass

        self._defer_deaths = False
        return self

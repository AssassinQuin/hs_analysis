"""GameState data structure for Hearthstone AI decision engine.

Represents the full game state and supports copy() for search tree branching.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from analysis.search.keywords import KeywordSet

if TYPE_CHECKING:
    from analysis.search.mechanics_state import MechanicsState
    from analysis.search.zone_manager import ZoneManager

log = logging.getLogger(__name__)


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
    has_magnetic: bool = False  # magnetic: attaches to friendly mech
    has_invoke: bool = False  # invoke galakrond mechanic
    has_corrupt: bool = False  # corrupt: upgrades when higher-cost card played
    has_spellburst: bool = False  # spellburst: triggers when spell is cast
    is_outcast: bool = False  # outcast: bonus when played from leftmost/rightmost
    race: str = ""  # minion race/type (beast, demon, mech, dragon, etc.)
    spell_school: str = ""  # spell school for spell-related interactions
    spell_power: int = 0  # spell damage +N
    has_attacked_once: bool = False  # windfury first-attack tracking
    frozen_until_next_turn: bool = False  # freeze effect
    has_ward: bool = False
    has_mega_windfury: bool = False
    card_id: str = ""
    keywords: KeywordSet = field(default_factory=KeywordSet)
    turn_played: int = 0
    enchantments: list = field(default_factory=list)
    owner: str = "friendly"  # or "enemy"
    card_ref: object = None  # Optional reference to source Card

    @classmethod
    def from_card(cls, card, owner: str = "friendly", turn_played: int = 0) -> "Minion":
        """Create a board-ready Minion from a static Card definition."""
        mechanics = set(getattr(card, "mechanics", []) or [])
        return cls(
            dbf_id=getattr(card, "dbf_id", 0),
            name=getattr(card, "name", ""),
            attack=getattr(card, "attack", 0),
            health=getattr(card, "health", 0),
            max_health=getattr(card, "health", 0),
            cost=getattr(card, "cost", 0),
            race=getattr(card, "race", ""),
            spell_school=getattr(card, "spell_school", ""),
            card_id=getattr(card, "card_id", "") if hasattr(card, "card_id") else "",
            can_attack="CHARGE" in mechanics,
            has_charge="CHARGE" in mechanics,
            has_rush="RUSH" in mechanics,
            has_taunt="TAUNT" in mechanics,
            has_divine_shield="DIVINE_SHIELD" in mechanics,
            has_windfury="WINDFURY" in mechanics,
            has_stealth="STEALTH" in mechanics,
            has_poisonous="POISONOUS" in mechanics,
            has_lifesteal="LIFESTEAL" in mechanics,
            has_reborn="REBORN" in mechanics,
            has_immune="IMMUNE" in mechanics,
            cant_attack="CANT_ATTACK" in mechanics,
            owner=owner,
            turn_played=turn_played,
            card_ref=card,
        )

    @property
    def is_friendly(self) -> bool:
        return self.owner == "friendly"

    @property
    def is_enemy(self) -> bool:
        return self.owner == "enemy"

    @property
    def can_attack_now(self) -> bool:
        if not self.can_attack or self.cant_attack or self.is_dormant:
            return False
        if self.frozen_until_next_turn:
            return False
        if self.has_windfury:
            return not self.has_attacked_once or self.attack > 0
        return not self.has_attacked_once

    @property
    def is_taunted(self) -> bool:
        return self.has_taunt

    @property
    def total_stats(self) -> int:
        return self.attack + self.health


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
    opp_known_cards: list = field(default_factory=list)  # List of known opponent cards (KnownCard dicts)
    opp_generated_count: int = 0  # Number of generated cards opponent has played
    opp_secrets_triggered: list = field(default_factory=list)  # Opponent secrets that have triggered


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
    _mechanics: Optional[object] = (
        None  # MechanicsState (lazy init, Phase 2 integration)
    )
    _zones: Optional[object] = (
        None  # tuple[ZoneManager, ZoneManager] (lazy init, Phase 3 integration)
    )

    # ------------------------------------------------------------------
    # ZoneManager access (Phase 3 integration)
    # ------------------------------------------------------------------

    @property
    def zones(self):
        """Tuple of (friendly ZoneManager, enemy ZoneManager).

        Lazily initialised from the legacy list fields on first access.
        """
        if self._zones is None:
            from analysis.search.zone_manager import ZoneManager
            friendly = ZoneManager(
                hand=list(self.hand),
                board=list(self.board) + list(self.locations),
                deck=list(self.deck_list) if self.deck_list else [],
                secrets=[],
            )
            enemy = ZoneManager(
                board=list(self.opponent.board),
                secrets=list(self.opponent.secrets),
            )
            self._zones = (friendly, enemy)
        return self._zones

    @zones.setter
    def zones(self, value):
        self._zones = value

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def copy(self) -> "GameState":
        """Fast copy — shallow-copy immutable fields, copy mutable containers."""
        opp_hero = dataclasses.replace(self.opponent.hero)
        if self.opponent.hero.weapon is not None:
            opp_hero.weapon = dataclasses.replace(self.opponent.hero.weapon)

        opp = dataclasses.replace(
            self.opponent,
            hero=opp_hero,
            board=[dataclasses.replace(m) for m in self.opponent.board],
            secrets=list(self.opponent.secrets),
            opp_known_cards=list(self.opponent.opp_known_cards),
            opp_secrets_triggered=list(self.opponent.opp_secrets_triggered),
        )

        hero = dataclasses.replace(self.hero)
        if self.hero.weapon is not None:
            hero.weapon = dataclasses.replace(self.hero.weapon)

        mana = dataclasses.replace(
            self.mana,
            modifiers=[
                dataclasses.replace(mod) for mod in self.mana.modifiers
            ],
        )

        gs = GameState(
            hero=hero,
            mana=mana,
            board=[dataclasses.replace(m) for m in self.board],
            locations=[dataclasses.replace(loc) for loc in self.locations],
            hand=list(self.hand),
            deck_list=list(self.deck_list) if self.deck_list is not None else None,
            deck_remaining=self.deck_remaining,
            opponent=opp,
            turn_number=self.turn_number,
            cards_played_this_turn=list(self.cards_played_this_turn),
            fatigue_damage=self.fatigue_damage,
            herald_count=self.herald_count,
            last_turn_races=set(self.last_turn_races),
            last_turn_schools=set(self.last_turn_schools),
            active_quests=list(self.active_quests),
            corpses=self.corpses,
            kindred_double_next=self.kindred_double_next,
            last_played_card=self.last_played_card,
            _defer_deaths=self._defer_deaths,
            _pending_dead_friendly=list(self._pending_dead_friendly),
            _pending_dead_enemy=list(self._pending_dead_enemy),
        )
        # Copy mechanics state if populated
        if self._mechanics is not None:
            gs._mechanics = self._mechanics.copy()
        # Copy zone managers if populated
        if self._zones is not None:
            gs._zones = (self._zones[0].copy(), self._zones[1].copy())
        return gs

    def is_lethal(self) -> bool:
        """True if opponent hero HP + armor <= 0."""
        opp = self.opponent.hero
        return (opp.hp + opp.armor) <= 0

    def board_full(self) -> bool:
        """True if the friendly board already has 7 minions."""
        return len(self.board) >= 7

    def location_full(self) -> bool:
        """True if friendly locations already at max (2)."""
        return len(self.locations) >= 2

    # -- MechanicsState access (Phase 2 integration) -----------------------

    @property
    def mechanics(self):
        """Lazy-initialized MechanicsState for mechanic-specific state."""
        if self._mechanics is None:
            from analysis.search.mechanics_state import MechanicsState
            self._mechanics = MechanicsState()
        return self._mechanics

    @mechanics.setter
    def mechanics(self, value):
        self._mechanics = value

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
            log.warning("flush_deaths: resolve_deaths failed", exc_info=True)

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
            log.warning("flush_deaths: corpse gain failed", exc_info=True)

        # Aura recompute
        try:
            from analysis.search.aura_engine import recompute_auras

            self = recompute_auras(self)
        except Exception:
            log.warning("flush_deaths: aura recompute failed", exc_info=True)

        self._defer_deaths = False
        return self

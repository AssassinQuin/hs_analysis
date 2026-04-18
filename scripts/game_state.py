"""GameState data structure for Hearthstone AI decision engine.

Represents the full game state and supports copy() for search tree branching.
Runnable independently: python3 scripts/game_state.py
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
class Card:
    """A card in hand."""

    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    original_cost: int = 0
    card_type: str = ""  # MINION, SPELL, WEAPON, HERO
    attack: int = 0
    health: int = 0
    v2_score: float = 0.0
    l6_score: float = 0.0
    v7_score: float = 0.0   # V7 scoring report score
    text: str = ""


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
    hand: List[Card] = field(default_factory=list)
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


# ======================================================================
# __main__ demo / smoke-test
# ======================================================================

if __name__ == "__main__":
    # -- Build a sample state -------------------------------------------------
    gs = GameState(
        hero=HeroState(
            hp=25,
            armor=2,
            hero_class="WARRIOR",
            weapon=Weapon(attack=3, health=2, name="Arcanite Reaper"),
        ),
        mana=ManaState(available=6, max_mana=8),
        board=[
            Minion(
                dbf_id=1001,
                name="Fire Fly",
                attack=1,
                health=2,
                max_health=2,
                cost=1,
                can_attack=True,
                owner="friendly",
            ),
            Minion(
                dbf_id=1002,
                name="Tar Creeper",
                attack=1,
                health=5,
                max_health=5,
                cost=3,
                has_taunt=True,
                owner="friendly",
            ),
            Minion(
                dbf_id=1003,
                name="Southsea Deckhand",
                attack=2,
                health=1,
                max_health=1,
                cost=1,
                can_attack=True,
                has_charge=True,
                owner="friendly",
            ),
        ],
        hand=[
            Card(dbf_id=2001, name="Frostbolt", cost=2, card_type="SPELL"),
            Card(dbf_id=2002, name="Fireball", cost=4, card_type="SPELL"),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=12, armor=0),
            board=[
                Minion(
                    dbf_id=3001,
                    name="Voidwalker",
                    attack=1,
                    health=3,
                    max_health=3,
                    has_taunt=True,
                    owner="enemy",
                ),
            ],
            hand_count=5,
        ),
        turn_number=7,
    )

    # -- Tests ----------------------------------------------------------------
    errors: list[str] = []

    # 1. copy() isolation
    gs_copy = gs.copy()
    gs_copy.board[0].attack = 99
    gs_copy.hero.hp = 1
    if gs.board[0].attack == 99:
        errors.append("FAIL: copy() is not isolated — modifying copy affected original (board)")
    if gs.hero.hp == 1:
        errors.append("FAIL: copy() is not isolated — modifying copy affected original (hero)")

    # 2. is_lethal
    if gs.is_lethal():
        errors.append(f"FAIL: is_lethal() should be False (opp hp={gs.opponent.hero.hp})")
    gs.opponent.hero.hp = -2
    if not gs.is_lethal():
        errors.append("FAIL: is_lethal() should be True when opp hp <= 0")
    gs.opponent.hero.hp = 0
    gs.opponent.hero.armor = 1
    if gs.is_lethal():
        errors.append("FAIL: is_lethal() should be False when hp+armor > 0")
    gs.opponent.hero.hp = -1
    gs.opponent.hero.armor = 1
    if not gs.is_lethal():
        errors.append("FAIL: is_lethal() should be True when hp+armor <= 0")
    gs.opponent.hero.hp = 12
    gs.opponent.hero.armor = 0

    # 3. board_full
    if gs.board_full():
        errors.append(f"FAIL: board_full() should be False (board size={len(gs.board)})")
    # fill to 7
    for i in range(4):
        gs.board.append(Minion(dbf_id=9000 + i, name=f"filler_{i}"))
    if not gs.board_full():
        errors.append(f"FAIL: board_full() should be True (board size={len(gs.board)})")
    # trim back
    del gs.board[3:]

    # 4. has_taunt_on_board
    if not gs.has_taunt_on_board():
        errors.append("FAIL: has_taunt_on_board() should be True (Tar Creeper has taunt)")

    # 5. get_total_attack  (1+1+2 minions + 3 weapon = 7)
    total = gs.get_total_attack()
    expected = 1 + 1 + 2 + 3  # minion attacks + weapon
    if total != expected:
        errors.append(f"FAIL: get_total_attack() = {total}, expected {expected}")

    # -- Report ---------------------------------------------------------------
    if errors:
        print("❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("✅ All tests passed.")
        print(f"   Board size : {len(gs.board)}")
        print(f"   Total attack: {gs.get_total_attack()}")
        print(f"   Board full : {gs.board_full()}")
        print(f"   Is lethal  : {gs.is_lethal()}")

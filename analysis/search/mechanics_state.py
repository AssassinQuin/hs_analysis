#!/usr/bin/env python3
"""mechanics_state.py — Composition root for mechanic-specific state.

Replaces ~15 scattered fields on GameState with a single container.
Cheap copy() because most sub-states are None or immutable.

This module intentionally does NOT import game_state to avoid circular deps.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from analysis.watcher.global_tracker import GlobalGameState

__all__ = [
    "CorpseState",
    "KindredState",
    "QuestProgress",
    "ImbueState",
    "MechanicsState",
]


# ═══════════════════════════════════════════════════════════════════
# Sub-states — one per mechanic system
# ═══════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class CorpseState:
    """DK Corpse resource tracking."""
    gained: int = 0
    spent: int = 0

    @property
    def available(self) -> int:
        return self.gained - self.spent

    def gain(self, amount: int) -> None:
        self.gained += amount

    def spend(self, amount: int) -> bool:
        """Try to spend corpses. Returns True if successful."""
        if self.available >= amount:
            self.spent += amount
            return True
        return False


@dataclass(slots=True)
class KindredState:
    """延系 (Kindred) mechanic state."""
    last_turn_races: frozenset = frozenset()
    last_turn_schools: frozenset = frozenset()
    current_turn_races: set = field(default_factory=set)
    current_turn_schools: set = field(default_factory=set)
    double_next: bool = False  # 蛮鱼挑战者 doubles next kindred trigger

    def record_play(self, race: str = "", spell_school: str = "") -> None:
        """Record a card play for kindred tracking this turn."""
        if race:
            for r in race.upper().split():
                self.current_turn_races.add(r)
        if spell_school:
            for s in spell_school.upper().split():
                self.current_turn_schools.add(s)

    def rotate_turn(self) -> None:
        """Move current turn data to last turn (called at turn end)."""
        self.last_turn_races = frozenset(self.current_turn_races)
        self.last_turn_schools = frozenset(self.current_turn_schools)
        self.current_turn_races = set()
        self.current_turn_schools = set()

    def copy(self) -> KindredState:
        return KindredState(
            last_turn_races=self.last_turn_races,  # frozen, shared
            last_turn_schools=self.last_turn_schools,  # frozen, shared
            current_turn_races=set(self.current_turn_races),
            current_turn_schools=set(self.current_turn_schools),
            double_next=self.double_next,
        )


@dataclass(slots=True)
class QuestProgress:
    """Tracks a single active quest/questline."""
    quest_name: str = ""
    quest_dbf_id: int = 0
    quest_type: str = ""  # "play_cards", "cast_spells", "summon_minions", etc.
    progress: int = 0
    threshold: int = 3
    reward_name: str = ""
    reward_dbf_id: int = 0
    is_side_quest: bool = False
    completed: bool = False
    quest_constraint: str = ""  # "UNDEAD", "BEAST", "HOLY", "SHADOW", etc.

    def copy(self) -> QuestProgress:
        return dataclasses.replace(self)


@dataclass(slots=True)
class ImbueState:
    """Imbue hero power upgrade tracking."""
    level: int = 0
    hero_class: str = ""  # set when first imbue card is played

    def copy(self) -> ImbueState:
        return dataclasses.replace(self)


# ═══════════════════════════════════════════════════════════════════
# MechanicsState — composition root
# ═══════════════════════════════════════════════════════════════════


@dataclass
class MechanicsState:
    """Composition root for all mechanic-specific state.

    Replaces these scattered fields on GameState:
        corpses: int
        herald_count: int
        active_quests: list
        last_turn_races: set
        last_turn_schools: set
        kindred_double_next: bool
        fatigue_damage: int

    And one field from HeroState:
        imbue_level: int
    """
    corpses: Optional[CorpseState] = None  # DK only
    kindred: Optional[KindredState] = None  # 延系
    quests: list = field(default_factory=list)  # list of QuestProgress
    imbue: Optional[ImbueState] = None  # 灌注
    herald_count: int = 0  # 兆示 counter
    fatigue: int = 0  # fatigue damage counter
    rune_cost: frozenset = frozenset()  # DK rune requirement

    # -- Factory: build from watcher's GlobalGameState ---------------------

    @classmethod
    def from_global_state(cls, ggs: 'GlobalGameState') -> 'MechanicsState':
        """Build MechanicsState from watcher's GlobalGameState."""
        corpses = None
        if ggs.player_corpses > 0:
            corpses = CorpseState(gained=ggs.player_corpses, spent=0)

        kindred = None
        if ggs.last_turn_races_player or ggs.last_turn_schools_player:
            kindred = KindredState(
                last_turn_races=frozenset(ggs.last_turn_races_player),
                last_turn_schools=frozenset(ggs.last_turn_schools_player),
            )

        quests = []
        for qd in ggs.player_quests:
            if isinstance(qd, dict):
                quests.append(QuestProgress(
                    quest_name=qd.get('name', ''),
                    quest_dbf_id=qd.get('dbf_id', 0),
                    progress=qd.get('progress', 0),
                    threshold=qd.get('threshold', 3),
                    completed=qd.get('completed', False),
                ))

        fatigue = ggs.player_stats.fatigue_damage if hasattr(ggs, 'player_stats') else 0

        return cls(
            corpses=corpses,
            kindred=kindred,
            quests=quests,
            herald_count=ggs.player_herald_count,
            fatigue=fatigue,
        )

    # -- Convenience accessors for backward compat -------------------------

    @property
    def corpse_count(self) -> int:
        """Available corpses (backward compat for state.corpses)."""
        return self.corpses.available if self.corpses else 0

    @property
    def kindred_double_next(self) -> bool:
        return self.kindred.double_next if self.kindred else False

    @kindred_double_next.setter
    def kindred_double_next(self, value: bool) -> None:
        if self.kindred is None:
            self.kindred = KindredState()
        self.kindred.double_next = value

    # -- Copy (cheap — most fields are None or immutable) ------------------

    def copy(self) -> MechanicsState:
        return MechanicsState(
            corpses=dataclasses.replace(self.corpses) if self.corpses else None,
            kindred=self.kindred.copy() if self.kindred else None,
            quests=[q.copy() for q in self.quests],
            imbue=self.imbue.copy() if self.imbue else None,
            herald_count=self.herald_count,
            fatigue=self.fatigue,
            rune_cost=self.rune_cost,  # frozenset, shared
        )

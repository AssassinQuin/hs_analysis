#!/usr/bin/env python3
"""mechanic.py — Mechanic Protocol for the game engine.

Defines the interface that all mechanic modules must implement.
Mechanics are event-driven: the engine dispatches game events to
all registered mechanics, which can modify state and legal actions.

This module does NOT import game_state to avoid circular deps.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card

__all__ = ["Mechanic"]


@runtime_checkable
class Mechanic(Protocol):
    """Interface for mechanic modules.

    Each mechanic handles one game system (corpses, quests, kindred, etc.).
    All methods return the (possibly modified) GameState.  Default no-op
    implementations allow mechanics to only override the events they care about.
    """

    @property
    def name(self) -> str:
        """Human-readable name for logging."""
        ...

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Called when any card is played."""
        return state

    def on_minion_died(self, state: "GameState", minion: "Minion", **ctx) -> "GameState":
        """Called when a minion dies (health <= 0)."""
        return state

    def on_turn_start(self, state: "GameState", player: int, **ctx) -> "GameState":
        """Called at the start of a turn."""
        return state

    def on_turn_end(self, state: "GameState", player: int, **ctx) -> "GameState":
        """Called at the end of a turn."""
        return state

    def on_attack(self, state: "GameState", attacker: "Minion", target, **ctx) -> "GameState":
        """Called after an attack is resolved."""
        return state

    def on_spell_cast(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Called after a spell is cast."""
        return state

    def modify_legal_actions(self, state: "GameState", actions: list) -> list:
        """Add or filter mechanic-specific legal actions.

        Return the modified actions list.  Default: pass through unchanged.
        """
        return actions

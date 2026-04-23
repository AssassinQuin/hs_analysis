#!/usr/bin/env python3
"""mechanic_dispatcher.py — Central dispatcher for game mechanic events.

Owns all registered Mechanic instances and dispatches game events to them
in order.  This replaces direct calls to individual mechanic modules
scattered throughout the engine.

Usage:
    dispatcher = MechanicDispatcher()
    dispatcher.register(CorpseMechanic())
    dispatcher.register(KindredMechanic())
    ...

    state = dispatcher.on_card_played(state, card)
    actions = dispatcher.modify_legal_actions(state, actions)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.search.mechanic import Mechanic
    from analysis.models.card import Card

logger = logging.getLogger(__name__)

__all__ = ["MechanicDispatcher"]


class MechanicDispatcher:
    """Owns registered Mechanics and dispatches game events to all of them.

    Mechanics are called in registration order.  Each handler receives the
    state returned by the previous handler (pipeline pattern).

    Exception handling: individual mechanic failures are caught and logged
    so one broken mechanic doesn't crash the entire dispatch chain.
    """

    def __init__(self) -> None:
        self._mechanics: List[Mechanic] = []

    def register(self, mechanic: "Mechanic") -> None:
        """Register a mechanic instance."""
        self._mechanics.append(mechanic)

    @property
    def mechanics(self) -> List["Mechanic"]:
        """Read-only access to registered mechanics."""
        return list(self._mechanics)

    # -- Event dispatchers --------------------------------------------------

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Dispatch card-played event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_card_played(state, card, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_card_played failed: %s", m.name, exc)
        return state

    def on_minion_died(self, state: "GameState", minion: "Minion", **ctx) -> "GameState":
        """Dispatch minion-death event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_minion_died(state, minion, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_minion_died failed: %s", m.name, exc)
        return state

    def on_turn_start(self, state: "GameState", player: int = 0, **ctx) -> "GameState":
        """Dispatch turn-start event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_turn_start(state, player, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_turn_start failed: %s", m.name, exc)
        return state

    def on_turn_end(self, state: "GameState", player: int = 0, **ctx) -> "GameState":
        """Dispatch turn-end event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_turn_end(state, player, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_turn_end failed: %s", m.name, exc)
        return state

    def on_attack(self, state: "GameState", attacker: "Minion", target=None, **ctx) -> "GameState":
        """Dispatch attack event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_attack(state, attacker, target, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_attack failed: %s", m.name, exc)
        return state

    def on_spell_cast(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Dispatch spell-cast event to all mechanics."""
        for m in self._mechanics:
            try:
                state = m.on_spell_cast(state, card, **ctx)
            except Exception as exc:
                logger.warning("Mechanic %s on_spell_cast failed: %s", m.name, exc)
        return state

    def modify_legal_actions(self, state: "GameState", actions: list) -> list:
        """Let all mechanics add/filter legal actions."""
        for m in self._mechanics:
            try:
                actions = m.modify_legal_actions(state, actions)
            except Exception as exc:
                logger.warning("Mechanic %s modify_legal_actions failed: %s", m.name, exc)
        return actions

    # -- Factory for default setup ------------------------------------------

    @classmethod
    def create_default(cls) -> "MechanicDispatcher":
        """Create a dispatcher with all standard mechanics registered.

        This is the single point where the mechanic roster is configured.
        """
        from analysis.search.mechanics.corpse_mechanic import CorpseMechanic
        from analysis.search.mechanics.kindred_mechanic import KindredMechanic
        from analysis.search.mechanics.quest_mechanic import QuestMechanic
        from analysis.search.mechanics.herald_mechanic import HeraldMechanic
        from analysis.search.mechanics.imbue_mechanic import ImbueMechanic

        dispatcher = cls()
        dispatcher.register(CorpseMechanic())
        dispatcher.register(KindredMechanic())
        dispatcher.register(QuestMechanic())
        dispatcher.register(HeraldMechanic())
        dispatcher.register(ImbueMechanic())
        return dispatcher

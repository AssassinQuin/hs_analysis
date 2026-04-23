"""imbue_mechanic.py — Mechanic adapter for the Imbue hero power upgrade system.

Wraps analysis.search.imbue to implement the Mechanic protocol.
Delegates all logic to the existing standalone imbue functions.

NOTE: This adapter does NOT read/write state.mechanics (that field does
not exist yet). It works directly with the existing state fields
(hero.imbue_level, etc.) via the standalone imbue module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card


class ImbueMechanic:
    """Mechanic adapter for the Imbue hero power upgrade system.

    When a card with the IMBUE mechanic is played, increments the
    hero's imbue_level to strengthen the hero power.
    """

    # -- Mechanic protocol ---------------------------------------------------

    @property
    def name(self) -> str:
        return "Imbue"

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Apply imbue effect: increment hero imbue_level if card has IMBUE."""
        from analysis.search.imbue import apply_imbue

        return apply_imbue(state, card)

    # Default no-op methods
    def on_minion_died(self, state: "GameState", minion: "Minion", **ctx) -> "GameState":
        return state

    def on_turn_start(self, state: "GameState", player: int, **ctx) -> "GameState":
        return state

    def on_turn_end(self, state: "GameState", player: int, **ctx) -> "GameState":
        return state

    def on_attack(self, state: "GameState", attacker: "Minion", target, **ctx) -> "GameState":
        return state

    def on_spell_cast(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        return state

    def modify_legal_actions(self, state: "GameState", actions: list) -> list:
        return actions

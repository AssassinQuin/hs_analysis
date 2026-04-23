"""herald_mechanic.py — Mechanic adapter for the Herald (兆示) system.

Wraps analysis.search.herald to implement the Mechanic protocol.
Delegates all logic to the existing standalone herald functions.

NOTE: This adapter does NOT read/write state.mechanics (that field does
not exist yet). It works directly with the existing state fields
(herald_count, board, etc.) via the standalone herald module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card


class HeraldMechanic:
    """Mechanic adapter for the Herald (兆示) summon system.

    When a card with the Herald mechanic is played, increments the
    herald counter and summons a class-specific soldier minion.
    """

    # -- Mechanic protocol ---------------------------------------------------

    @property
    def name(self) -> str:
        return "Herald"

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Apply herald effect: increment counter and summon soldier."""
        from analysis.search.herald import apply_herald

        return apply_herald(state, card)

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

"""kindred_mechanic.py — Mechanic adapter for the Kindred (延系) system.

Wraps analysis.search.kindred to implement the Mechanic protocol.
Delegates all logic to the existing standalone kindred functions.

NOTE: This adapter does NOT read/write state.mechanics (that field does
not exist yet). It works directly with the existing state fields
(last_turn_races, last_turn_schools, kindred_double_next, etc.)
via the standalone kindred module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card


class KindredMechanic:
    """Mechanic adapter for the Kindred (延系) bonus-trigger system.

    Checks kindred condition on card play and applies the bonus effect
    when the played card shares a race/spellSchool with last turn's plays.
    """

    # -- Mechanic protocol ---------------------------------------------------

    @property
    def name(self) -> str:
        return "Kindred"

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Apply kindred effect if the card has it and the condition is met."""
        from analysis.search.kindred import apply_kindred

        return apply_kindred(state, card)

    def on_turn_end(self, state: "GameState", player: int, **ctx) -> "GameState":
        """Placeholder for kindred turn rotation.

        Currently kindred rotation (updating last_turn_races / last_turn_schools)
        is handled elsewhere in the engine. This hook will be used once
        MechanicsState is fully integrated.
        """
        return state

    # Default no-op methods
    def on_minion_died(self, state: "GameState", minion: "Minion", **ctx) -> "GameState":
        return state

    def on_turn_start(self, state: "GameState", player: int, **ctx) -> "GameState":
        return state

    def on_attack(self, state: "GameState", attacker: "Minion", target, **ctx) -> "GameState":
        return state

    def on_spell_cast(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        return state

    def modify_legal_actions(self, state: "GameState", actions: list) -> list:
        return actions

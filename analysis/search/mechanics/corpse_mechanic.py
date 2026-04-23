"""corpse_mechanic.py — Mechanic adapter for the Corpse (残骸) resource system.

Wraps analysis.search.corpse to implement the Mechanic protocol.
Delegates all logic to the existing standalone corpse functions.

NOTE: This adapter does NOT read/write state.mechanics (that field does
not exist yet). It works directly with the existing state fields
(corpses, board, etc.) via the standalone corpse module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card


class CorpseMechanic:
    """Mechanic adapter for the Death Knight Corpse resource system.

    Gains corpses when friendly minions die, and resolves corpse-spending
    effects when DK cards are played.
    """

    # -- Mechanic protocol ---------------------------------------------------

    @property
    def name(self) -> str:
        return "Corpse"

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Resolve corpse effects when a DK card is played."""
        from analysis.search.corpse import resolve_corpse_effects

        # resolve_corpse_effects expects a dict with a "text" key
        if isinstance(card, dict):
            card_dict = card
        else:
            card_dict = {
                "text": getattr(card, "text", ""),
                "name": getattr(card, "name", ""),
            }
        return resolve_corpse_effects(state, card_dict)

    def on_minion_died(self, state: "GameState", minion: "Minion", **ctx) -> "GameState":
        """Gain corpses when a friendly minion dies."""
        from analysis.search.corpse import gain_corpses, has_double_corpse_gen

        if getattr(minion, "owner", "") == "friendly":
            amount = 2 if has_double_corpse_gen(state) else 1
            return gain_corpses(state, amount)
        return state

    # Default no-op methods (inherited from protocol semantics)
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

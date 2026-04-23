"""quest_mechanic.py — Mechanic adapter for the Quest progress system.

Wraps analysis.search.quest to implement the Mechanic protocol.
Delegates all logic to the existing standalone quest functions.

NOTE: This adapter does NOT read/write state.mechanics (that field does
not exist yet). It works directly with the existing state fields
(active_quests, hand, etc.) via the standalone quest module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion
    from analysis.models.card import Card


class QuestMechanic:
    """Mechanic adapter for quest progress tracking.

    Advances quest progress whenever a card is played, and marks
    quests as completed when their threshold is reached.
    """

    # -- Mechanic protocol ---------------------------------------------------

    @property
    def name(self) -> str:
        return "Quest"

    def on_card_played(self, state: "GameState", card: "Card", **ctx) -> "GameState":
        """Track quest progress when a card is played."""
        from analysis.search.quest import track_quest_progress

        return track_quest_progress(state, "PLAY", card)

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

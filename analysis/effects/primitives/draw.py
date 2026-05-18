"""draw.py — Draw, discard, shuffle primitives."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def apply_draw(state: GameState, count: int = 1, **kwargs: Any) -> None:
    """Draw *count* cards from the deck."""
    for _ in range(count):
        if state.deck_list and len(state.deck_list) > 0:
            drawn = state.deck_list.pop(0)
            state.hand.append(drawn)
            state.cards_drawn_this_turn += 1
        else:
            _apply_fatigue(state)


def apply_discard(state: GameState, count: int = 1, **kwargs: Any) -> None:
    """Discard *count* cards from hand."""
    for _ in range(count):
        if state.hand:
            state.hand.pop(0)


def _apply_fatigue(state: GameState) -> None:
    """Apply fatigue damage when deck is empty."""
    state.fatigue_damage += 1
    state.hero.health -= state.fatigue_damage
    if state.hero.health < 0:
        state.hero.health = 0

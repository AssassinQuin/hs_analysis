"""summon.py — Summon minion primitives."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def apply_summon(state: GameState, attack: int = 0, health: int = 0,
                 count: int = 1, card_id: str = "",
                 **kwargs: Any) -> None:
    """Summon *count* minions with given stats."""
    from analysis.card.engine.state import Minion

    for _ in range(count):
        minion = Minion(
            attack=attack,
            health=health,
            max_health=health,
            cost=0,
            card_id=card_id or "generated",
            owner="friendly",
        )
        if len(state.board) < 7:
            state.board.append(minion)
        else:
            log.debug("Board full, cannot summon")
            break


def apply_summon_from_deck(state: GameState, count: int = 1,
                           **kwargs: Any) -> None:
    """Summon *count* minions from the deck."""
    if not state.deck_list:
        return
    from analysis.card.engine.state import Minion

    summoned = 0
    for card in list(state.deck_list):
        if summoned >= count:
            break
        if card.is_minion and len(state.board) < 7:
            minion = Minion(
                dbf_id=card.dbf_id,
                name=card.name,
                attack=card.attack,
                health=card.health,
                max_health=card.health,
                cost=card.cost,
                card_id=card.card_id,
                owner="friendly",
            )
            state.board.append(minion)
            state.deck_list.remove(card)
            summoned += 1

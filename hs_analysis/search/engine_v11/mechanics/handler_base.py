"""MechanicHandler ABC — interface for all mechanic handlers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from hs_analysis.search.game_state import GameState
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import Action


@dataclass
class ActionContext:
    state: GameState
    action: Action
    card: Optional[Card] = None
    source_minion: Optional[Any] = None
    target_minion: Optional[Any] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def keywords(self) -> Set[str]:
        if self.card is None:
            return set()
        return set(self.card.mechanics or [])


class MechanicHandler(ABC):

    @abstractmethod
    def trigger_point(self) -> str:
        ...

    @abstractmethod
    def apply(self, state: GameState, context: ActionContext) -> GameState:
        ...

    def priority(self) -> int:
        return 100

    def enabled(self) -> bool:
        return True

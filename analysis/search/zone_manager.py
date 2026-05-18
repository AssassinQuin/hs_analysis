# -*- coding: utf-8 -*-
"""zone_manager.py — Zone-based card instance management for Hearthstone AI.

Each player's cards are tracked across six zones (hand, deck, board,
graveyard, secrets, setaside).  ZoneManager provides movement, query,
and convenience methods used by the simulation engine.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING, Union

from analysis.search.entity import Zone, CardInstance, EntityId, next_entity_id

if TYPE_CHECKING:
    from analysis.models.card import Card
    from analysis.search.game_state import Minion


@dataclass
class ZoneManager:
    """Manages card instances across all zones for one player.

    Each zone is a plain list of ``CardInstance`` objects ordered by
    position (for board) or draw order (for deck).  Movement between
    zones updates the ``zone`` field on the entity and transfers it
    between the corresponding lists.
    """

    hand: list = field(default_factory=list)        # List[CardInstance] — cards in hand
    deck: list = field(default_factory=list)         # List[CardInstance] — cards in deck
    board: list = field(default_factory=list)        # List[CardInstance] — minions/locations on board
    graveyard: list = field(default_factory=list)    # List[CardInstance] — dead minions
    secrets: list = field(default_factory=list)      # List[CardInstance] — active secrets
    setaside: list = field(default_factory=list)     # List[CardInstance] — set aside (evolved, dormant base)

    # ------------------------------------------------------------------
    # Zone list mapping
    # ------------------------------------------------------------------

    def _zone_list(self, zone: Zone) -> list:
        """Return the list corresponding to *zone*.

        Supported zones: HAND, DECK, PLAY, GRAVEYARD, SECRET, SETASIDE.
        """
        if zone == Zone.HAND:
            return self.hand
        if zone == Zone.DECK:
            return self.deck
        if zone == Zone.PLAY:
            return self.board
        if zone == Zone.GRAVEYARD:
            return self.graveyard
        if zone == Zone.SECRET:
            return self.secrets
        if zone == Zone.SETASIDE:
            return self.setaside
        raise ValueError(f"Unsupported zone: {zone!r}")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _remove_by_id(self, entity_id: EntityId) -> Optional[CardInstance]:
        """Scan all zone lists, remove the entity with *entity_id*, and return it.

        Returns ``None`` if the entity is not found in any zone.
        """
        for zone_list in (self.hand, self.deck, self.board,
                          self.graveyard, self.secrets, self.setaside):
            for i, ci in enumerate(zone_list):
                if ci.entity_id == entity_id:
                    return zone_list.pop(i)
        return None

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def move(self, entity: CardInstance, to_zone: Zone, position: int = -1) -> CardInstance:
        """Move *entity* to *to_zone* at the given *position*.

        Removes the entity from its current zone (matched by entity_id),
        updates its ``zone`` field, and inserts it into the target zone
        list.  Returns the moved entity.
        """
        self._remove_by_id(entity.entity_id)
        entity.zone = to_zone
        target = self._zone_list(to_zone)
        if position == -1 or position >= len(target):
            target.append(entity)
        else:
            target.insert(position, entity)
        return entity

    # ------------------------------------------------------------------
    # Copy (for simulation branching)
    # ------------------------------------------------------------------

    def copy(self) -> ZoneManager:
        """Deep-copy the ZoneManager for RHEA simulation branching.

        Each zone list is recreated with shallow copies of its
        ``CardInstance`` objects (via ``CardInstance.copy()``).
        The immutable ``Card`` references are shared.
        """
        return ZoneManager(
            hand=[ci.copy() for ci in self.hand],
            deck=[ci.copy() for ci in self.deck],
            board=[ci.copy() for ci in self.board],
            graveyard=[ci.copy() for ci in self.graveyard],
            secrets=[ci.copy() for ci in self.secrets],
            setaside=[ci.copy() for ci in self.setaside],
        )

    # ------------------------------------------------------------------
    # Convenience queries
    # ------------------------------------------------------------------

    def dead_minions(self) -> list:
        """Return graveyard entries whose card type is MINION."""
        return [ci for ci in self.graveyard
                if (ci.card.card_type or "").upper() == "MINION"]

    def board_minions(self) -> list:
        """Return board entries whose card type is MINION."""
        return [ci for ci in self.board
                if (ci.card.card_type or "").upper() == "MINION"]

    def board_locations(self) -> list:
        """Return board entries whose card type is LOCATION."""
        return [ci for ci in self.board
                if (ci.card.card_type or "").upper() == "LOCATION"]

    def has_taunt(self) -> bool:
        """Return ``True`` if any board minion has the TAUNT keyword."""
        return any(ci.card.has_mechanic("TAUNT") for ci in self.board_minions())

    def board_full(self) -> bool:
        """Return ``True`` if the board has 7 or more entities (minions + locations share 7 slots)."""
        return len(self.board) >= 7

    def hand_full(self) -> bool:
        """Return ``True`` if the hand has 10 or more cards."""
        return len(self.hand) >= 10

    # ------------------------------------------------------------------
    # High-level add / summon / draw / destroy
    # ------------------------------------------------------------------

    def add_to_hand(self, card_or_instance: Union[Card, CardInstance]) -> CardInstance:
        """Add a card or existing instance to the hand.

        If a ``Card`` is passed, a new ``CardInstance`` is created.
        Returns the resulting ``CardInstance``.
        """
        from analysis.models.card import Card
        if isinstance(card_or_instance, Card):
            ci = CardInstance(entity_id=next_entity_id(), card=card_or_instance, zone=Zone.HAND)
        else:
            ci = card_or_instance
            ci.zone = Zone.HAND
        self.hand.append(ci)
        return ci

    def add_to_deck(self, card_or_instance: Union[Card, CardInstance], position: int = -1) -> CardInstance:
        """Add a card or existing instance to the deck.

        If a ``Card`` is passed, a new ``CardInstance`` is created.
        Returns the resulting ``CardInstance``.
        """
        from analysis.models.card import Card
        if isinstance(card_or_instance, Card):
            ci = CardInstance(entity_id=next_entity_id(), card=card_or_instance, zone=Zone.DECK)
        else:
            ci = card_or_instance
            ci.zone = Zone.DECK
        if position == -1 or position >= len(self.deck):
            self.deck.append(ci)
        else:
            self.deck.insert(position, ci)
        return ci

    def summon_to_board(self, card_or_instance: Union[Card, CardInstance], position: int = -1) -> Optional[CardInstance]:
        """Summon a card or instance to the board.

        Returns ``None`` (without modifying state) if the board is full.
        Otherwise returns the placed ``CardInstance``.
        """
        if self.board_full():
            return None
        from analysis.models.card import Card
        if isinstance(card_or_instance, Card):
            ci = CardInstance(entity_id=next_entity_id(), card=card_or_instance, zone=Zone.PLAY)
        else:
            ci = card_or_instance
            ci.zone = Zone.PLAY
        if position == -1 or position >= len(self.board):
            self.board.append(ci)
        else:
            self.board.insert(position, ci)
        return ci

    def draw(self) -> Optional[CardInstance]:
        """Pop the front card from the deck.

        Sets the entity's zone to ``HAND`` and returns it.  Returns
        ``None`` if the deck is empty.  The caller is responsible for
        handling the hand-full case.
        """
        if not self.deck:
            return None
        ci = self.deck.pop(0)
        ci.zone = Zone.HAND
        return ci

    def destroy_minion(self, entity_id: EntityId) -> Optional[CardInstance]:
        """Remove a minion from the board by *entity_id* and place it in the graveyard.

        Returns the destroyed ``CardInstance``, or ``None`` if not found on the board.
        """
        ci = self._remove_by_id(entity_id)
        if ci is None:
            return None
        ci.zone = Zone.GRAVEYARD
        self.graveyard.append(ci)
        return ci

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def deck_size(self) -> int:
        """Number of cards remaining in the deck."""
        return len(self.deck)

    @property
    def hand_size(self) -> int:
        """Number of cards in hand."""
        return len(self.hand)

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ZoneManager(hand={len(self.hand)}, deck={len(self.deck)}, "
            f"board={len(self.board)}, graveyard={len(self.graveyard)}, "
            f"secrets={len(self.secrets)})"
        )

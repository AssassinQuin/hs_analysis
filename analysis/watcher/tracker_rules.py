"""tracker_rules.py — TrackerRule Protocol for pluggable tracking rules.

Defines the interface that all tracking rule modules must implement.
Rules are event-driven: GlobalTracker dispatches game events to all
registered rules, which can update GlobalGameState.

Design mirrors the existing Mechanic(Protocol) pattern in
analysis/search/mechanic.py.

Usage::

    class ShuffleTrackerRule:
        name = "shuffle"

        def on_zone_change(self, ctx: TrackingContext) -> None:
            if ctx.new_zone == ZONE_DECK and ctx.card_id:
                ...

    # In GlobalTracker.__init__:
    self._rule_dispatcher = TrackerRuleDispatcher()
    self._rule_dispatcher.register(ShuffleTrackerRule())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List, Protocol, runtime_checkable

if TYPE_CHECKING:
    from analysis.watcher.global_tracker import GlobalGameState

logger = logging.getLogger(__name__)

__all__ = ["TrackingContext", "TrackerRule", "TrackerRuleDispatcher"]


# ═══════════════════════════════════════════════════════════════════
# Event context — bundles event parameters for dispatch
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class TrackingContext:
    """Immutable context passed to TrackerRule handlers.

    Provides all the information a rule needs to decide whether
    and how to update GlobalGameState.
    """
    entity_id: int
    controller: int
    old_zone: int
    new_zone: int
    card_id: str
    card_type: int
    is_opp: bool
    state: GlobalGameState  # mutable reference — rules modify in-place


# ═══════════════════════════════════════════════════════════════════
# TrackerRule Protocol
# ═══════════════════════════════════════════════════════════════════

@runtime_checkable
class TrackerRule(Protocol):
    """Interface for pluggable tracking rules.

    Each rule handles one tracking concern (shuffle detection,
    corrupt tracking, secret management, etc.).

    Rules modify GlobalGameState in-place. Default no-op
    implementations allow rules to only override the events they
    care about.
    """

    @property
    def name(self) -> str:
        """Human-readable name for logging."""
        ...

    def on_zone_change(self, ctx: TrackingContext) -> None:
        """Called when an entity's ZONE tag changes.

        This is the primary event for most tracking rules.
        Rules can inspect ctx.old_zone / ctx.new_zone to decide
        whether to act.
        """
        ...

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        """Called when a hidden entity is revealed (SHOW_ENTITY log entry).

        Used for corrupt detection and opponent hand intelligence.
        """
        ...

    def on_turn_change(self, new_turn: int,
                       state: "GlobalGameState") -> None:
        """Called when the turn counter advances."""
        ...


# ═══════════════════════════════════════════════════════════════════
# Dispatcher — manages registered rules and dispatches events
# ═══════════════════════════════════════════════════════════════════

class TrackerRuleDispatcher:
    """Manages TrackerRule instances and dispatches events to them.

    Rules are called in registration order. Exceptions in individual
    rules are caught and logged to prevent one rule from breaking
    the tracking pipeline.
    """

    def __init__(self) -> None:
        self._rules: List[TrackerRule] = []

    def register(self, rule: TrackerRule) -> None:
        """Register a TrackerRule. It will receive all future events."""
        self._rules.append(rule)

    def dispatch_zone_change(self, ctx: TrackingContext) -> None:
        """Dispatch a zone change event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_zone_change(ctx)
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_zone_change: %s",
                    rule.name, exc,
                )

    def dispatch_show_entity(self, entity_id: int, card_id: str,
                             controller: int, zone: int,
                             card_type: int,
                             state: "GlobalGameState",
                             is_opp: bool) -> None:
        """Dispatch a show_entity event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_show_entity(
                    entity_id, card_id, controller, zone,
                    card_type, state, is_opp,
                )
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_show_entity: %s",
                    rule.name, exc,
                )

    def dispatch_turn_change(self, new_turn: int,
                             state: "GlobalGameState") -> None:
        """Dispatch a turn change event to all registered rules."""
        for rule in self._rules:
            try:
                rule.on_turn_change(new_turn, state)
            except Exception as exc:
                logger.warning(
                    "TrackerRule %s failed in on_turn_change: %s",
                    rule.name, exc,
                )


# ═══════════════════════════════════════════════════════════════════
# Built-in rule implementations
# ═══════════════════════════════════════════════════════════════════

class ShuffleTrackerRule:
    """Tracks cards shuffled into either player's deck.
    
    Distinguishes between:
    - Known cards (card_id present): specific card shuffled (e.g., 爆牌鱼 effect)
    - Unknown cards (card_id absent): random/unknown card shuffled
    
    Known shuffled cards are tracked as known information for deck inference.
    When played later, they are marked as GENERATED (not from original deck).
    """

    name = "shuffle"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_DECK
        self._ZONE_DECK = ZONE_DECK

    def on_zone_change(self, ctx: TrackingContext) -> None:
        if ctx.new_zone != self._ZONE_DECK:
            return
            
        if ctx.is_opp:
            # Always track in the legacy list for backward compat
            if ctx.card_id:
                ctx.state.opp_shuffled_into_deck.append(ctx.card_id)
                # Mark as known card (we know what was shuffled)
                ctx.state.opp_shuffled_known_cards[ctx.card_id] = True
            else:
                # Unknown card shuffled (no card_id visible)
                ctx.state.opp_shuffled_known_cards[f"unknown_{ctx.entity_id}"] = False
            
            # Track source if entity has birth info
            ctx.state.opp_shuffled_card_sources[ctx.entity_id] = ctx.card_id or ""
        else:
            if ctx.card_id:
                ctx.state.player_shuffled_into_deck.append(ctx.card_id)


class CorruptTrackerRule:
    """Tracks Corrupt upgrades in the opponent's hand.

    Detects when a card in the opponent's hand changes its card_id
    via SHOW_ENTITY (the Corrupt mechanic transforms a card while
    it remains in hand).
    """

    name = "corrupt"

    def __init__(self) -> None:
        from analysis.constants.hs_enums import ZONE_HAND
        self._ZONE_HAND = ZONE_HAND

    def on_show_entity(self, entity_id: int, card_id: str,
                       controller: int, zone: int,
                       card_type: int, state: "GlobalGameState",
                       is_opp: bool) -> None:
        if not is_opp:
            return
        if entity_id in state.opp_hand_card_ids:
            old_card_id = state.opp_hand_card_ids[entity_id][0]
            if old_card_id and old_card_id != card_id and zone == self._ZONE_HAND:
                state.opp_corrupted_cards.append(old_card_id)
                state.opp_corrupted_upgrades[old_card_id] = card_id

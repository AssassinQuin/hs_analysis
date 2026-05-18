"""validator.py — Legal action validation using ParsedCard.

This is the "Rules Layer" — it answers:
  - Is this Action legal in the current GameState?
  - What are all legal Actions right now?

Key difference from the old rules.py: validation is driven by the
ParsedCard's typed effects rather than by hard-coded checks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from analysis.effects.types import (
    Action, ActionKind, ParsedCard, TargetKind,
)

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def is_action_legal(state: GameState, action: Action,
                    parsed_card: ParsedCard | None = None) -> bool:
    """Check if an action is legal in the current game state.

    Args:
        state: Current GameState.
        action: The proposed Action.
        parsed_card: ParsedCard for the card being played (optional).

    Returns:
        True if legal, False otherwise.
    """
    kind = action.action_type

    if kind == ActionKind.END_TURN:
        return True

    if kind in (ActionKind.PLAY, ActionKind.PLAY_WITH_TARGET,
                ActionKind.HERO_REPLACE):
        return _can_play_card(state, action, parsed_card)

    if kind == ActionKind.ATTACK:
        return _can_attack(state, action)

    if kind == ActionKind.HERO_POWER:
        return _can_use_hero_power(state)

    if kind == ActionKind.ACTIVATE_LOCATION:
        return _can_activate_location(state, action)

    if kind == ActionKind.DISCOVER_PICK:
        # Always valid — discovery choices are always shown
        return True

    return False


def enumerate_legal_actions(state: GameState,
                            parsed_card: ParsedCard | None = None
                            ) -> list[Action]:
    """Return all legal actions in the current state.

    This is a thin replacement for the old rules.enumerate_legal().
    """
    actions: list[Action] = []

    # — Play cards from hand —
    for i, card in enumerate(state.hand):
        parsed = parsed_card if card.card_id else None
        if _can_play_card_from_hand(state, i, card, parsed):
            if _card_needs_target(card, parsed):
                actions.append(Action(
                    action_type=ActionKind.PLAY_WITH_TARGET,
                    card_index=i,
                    card_id=card.card_id,
                ))
            else:
                actions.append(Action(
                    action_type=ActionKind.PLAY,
                    card_index=i,
                    card_id=card.card_id,
                ))

    # — Attack with board —
    for i, minion in enumerate(state.board):
        if minion.can_attack and minion.attack > 0:
            for j, enemy in enumerate(state.opponent.board):
                actions.append(Action(
                    action_type=ActionKind.ATTACK,
                    source_index=i,
                    target_index=j,
                ))
            # Hero attack
            actions.append(Action(
                action_type=ActionKind.ATTACK,
                source_index=i,
            ))

    # — Hero power —
    mana = _available_mana(state)
    if state.mana and mana >= 2:  # hero power costs 2 by default
        actions.append(Action(action_type=ActionKind.HERO_POWER))

    # — Location activation —
    for i, loc in enumerate(state.locations):
        if mana >= 1:
            actions.append(Action(
                action_type=ActionKind.ACTIVATE_LOCATION,
                source_index=i,
            ))

    # — End turn —
    actions.append(Action(action_type=ActionKind.END_TURN))

    return actions


# ════════════════════════════════════════════════════════════════
# Internal validation helpers
# ════════════════════════════════════════════════════════════════

def _can_play_card(state: GameState, action: Action,
                   parsed_card: ParsedCard | None) -> bool:
    """Check if a card can be played."""
    idx = action.card_index
    if idx < 0 or idx >= len(state.hand):
        return False
    card = state.hand[idx]
    return _can_play_card_from_hand(state, idx, card, parsed_card)


def _can_play_card_from_hand(state: GameState, idx: int,
                              card: Any,
                              parsed_card: ParsedCard | None) -> bool:
    """Check if a card can be played from hand."""
    # Mana check
    if card.cost > _available_mana(state):
        return False

    # Minion: need board space
    if getattr(card, 'is_minion', False):
        if len(state.board) >= 7:
            return False

    # Weapon: can't equip if already have one (in basic rules)
    # (actual Hearthstone allows replacing weapons)

    return True


def _card_needs_target(card: Any,
                       parsed_card: ParsedCard | None) -> bool:
    """Check if playing a card requires target selection."""
    if parsed_card is None:
        return False
    for ab in parsed_card.abilities:
        for eff in ab.effects:
            if eff.target.kind == TargetKind.SELECTED:
                return True
    return False


def _can_attack(state: GameState, action: Action) -> bool:
    """Check if an attack action is legal."""
    if action.source_index < 0:
        return False
    if action.source_index >= len(state.board):
        return False
    minion = state.board[action.source_index]
    if not minion.can_attack:
        return False
    if minion.attack <= 0:
        return False

    # Check for taunt
    has_taunt = any(m.has_taunt for m in state.opponent.board)
    if has_taunt:
        # Must attack a taunt minion (if target_index is valid and is taunt)
        if action.target_index >= 0:
            if action.target_index < len(state.opponent.board):
                return state.opponent.board[action.target_index].has_taunt
        # Attacking hero when taunts exist → not allowed
        return False

    return True


def _can_use_hero_power(state: GameState) -> bool:
    """Check if hero power can be used."""
    if _available_mana(state) < 2:
        return False
    return True


def _can_activate_location(state: GameState, action: Action) -> bool:
    if _available_mana(state) < 1:
        return False
    if action.source_index < 0:
        return False
    if action.source_index >= len(state.locations):
        return False
    return True


def _available_mana(state: GameState) -> int:
    mana = state.mana
    if mana is None:
        return 0
    return mana.available - (mana.overloaded or 0)

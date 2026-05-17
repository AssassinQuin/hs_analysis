#!/usr/bin/env python3
"""deathrattle.py — Deathrattle queue for Hearthstone AI.

Handles minion death resolution: collects dead minions, queues deathrattle
effects in board-position order, executes effects, and cascades up to a
configurable limit.

Uses the unified abilities executor (zero regex, English text only).
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from analysis.search.game_state import GameState, Minion

logger = logging.getLogger(__name__)


def resolve_deaths(state: GameState, max_cascade: int = 5) -> GameState:
    """Resolve all dead minions on both boards with deathrattle effects.

    Process:
    1. Collect all minions with health <= 0 from both boards
    2. Queue deathrattle effects in board-position order (left to right)
    3. Execute each deathrattle effect
    4. Re-check for new deaths (cascade), up to max_cascade times
    5. Remove all dead minions from boards
    """
    s = state

    for cascade in range(max_cascade):
        dead_queue = _collect_dead(s)

        if not dead_queue:
            break

        for minion, board_type, position in dead_queue:
            s = _execute_deathrattle(s, minion, board_type, position)

        s.board = [m for m in s.board if m.health > 0]
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s


def _collect_dead(state: GameState) -> List[Tuple[Minion, str, int]]:
    """Collect all dead minions (health <= 0) from both boards."""
    dead = []

    for i, m in enumerate(state.board):
        if m.health <= 0:
            dead.append((m, 'friendly', i))

    for i, m in enumerate(state.opponent.board):
        if m.health <= 0:
            dead.append((m, 'enemy', i))

    dead.sort(key=lambda x: (0 if x[1] == 'friendly' else 1, x[2]))
    return dead


def _execute_deathrattle(
    state: GameState,
    minion: Minion,
    board_type: str,
    position: int,
) -> GameState:
    """Execute deathrattle effects for a single dying minion.

    Sources checked in order:
    1. Enchantment-based deathrattles (trigger_type="deathrattle")
    2. Unified abilities executor (from mechanics tags + English text)
    """
    s = state

    # Source 1: Enchantment-based deathrattles
    for ench in list(getattr(minion, 'enchantments', [])):
        if ench.trigger_type == "deathrattle" and ench.trigger_effect:
            try:
                s = _apply_deathrattle_effect(s, ench.trigger_effect, board_type, position)
            except Exception as exc:
                logger.warning("Deathrattle enchantment failed: %s — %s", ench.trigger_effect, exc)

    # Source 2: Unified abilities executor
    s = _execute_abilities_deathrattle(s, minion, board_type, position)

    return s


def _execute_abilities_deathrattle(
    state: GameState,
    minion: Minion,
    board_type: str,
    position: int,
) -> GameState:
    """Execute deathrattle via unified abilities system (zero regex)."""
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.definition import AbilityTrigger
    from analysis.search.abilities.executor import execute_effects

    abilities = getattr(minion, 'abilities', [])
    if not abilities:
        card_ref = getattr(minion, 'card_ref', None)
        if card_ref is not None:
            abilities = getattr(card_ref, 'abilities', [])
        if not abilities:
            abilities = AbilityParser.parse(minion)

    for ability in abilities:
        if ability.trigger != AbilityTrigger.DEATHRATTLE:
            continue
        if not ability.is_active(state, minion):
            continue
        try:
            state = ability.execute(state, minion)
        except Exception as exc:
            logger.debug("Abilities deathrattle failed: %s — %s", ability, exc)

    return state


def _apply_deathrattle_effect(
    state: GameState,
    effect: str,
    board_type: str,
    position: int,
) -> GameState:
    """Apply a single deathrattle effect string from enchantments.

    Delegates to the unified effects dispatcher.
    """
    from analysis.search.effects import dispatch, parse_effect

    spec = parse_effect(effect)
    if spec is not None:
        return dispatch(state, spec, board_type=board_type, position=position)

    logger.debug("Unparseable deathrattle effect: %s", effect)
    return state

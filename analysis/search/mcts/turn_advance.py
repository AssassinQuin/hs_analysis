#!/usr/bin/env python3
"""turn_advance.py — Cross-turn state advancement for MCTS.

Simulates the full cycle: our END_TURN → opponent turn → our next turn start.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


def advance_full_turn(state: GameState, *, greedy_opponent: bool = True) -> GameState:
    """Advance state from our END_TURN to the start of our next turn.

    Cycle:
    1. Our end-of-turn cleanup (overload, fatigue, dormant, freeze, immune, locations)
       — already done by _apply_end_turn before this function is called.
    2. Opponent's turn: mana refresh, draw, minions can attack, opponent plays greedy.
    3. Opponent's end-of-turn cleanup.
    4. Our next turn: mana refresh, draw, minions can attack.

    Args:
        state: GameState after our END_TURN has been applied (cleanup done).
        greedy_opponent: If True, simulate opponent playing minions greedily.

    Returns:
        New GameState at the start of our next turn.
    """
    s = state.copy()

    # === Step 1: Our end-of-turn cleanup is already done by _apply_end_turn ===

    # === Step 2: Opponent's turn start ===
    s.turn_number += 1

    # Opponent mana refresh — heuristic: opponent mana ≈ min(10, turn//2 + 1)
    # We don't track opponent mana directly; estimate based on turn number.
    # Each player gains one mana per their turn.
    opp_estimated_max = min(10, max(1, s.turn_number // 2 + 1))

    # Opponent draw
    if s.opponent.deck_remaining > 0:
        s.opponent.deck_remaining -= 1

    # Opponent minions can attack
    for m in s.opponent.board:
        if not m.has_rush:
            m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    # === Step 2b: Opponent plays (greedy) ===
    if greedy_opponent:
        s = _greedy_opponent_play(s)

    # === Step 3: Opponent's end-of-turn cleanup ===
    # Clear our minions' freeze/immune (applied at opponent's end-of-turn)
    for m in s.board:
        m.frozen_until_next_turn = False
        m.has_immune = False
    s.hero.is_immune = False

    # === Step 4: Our next turn start ===
    s.turn_number += 1

    # Our mana refresh
    next_max = min(s.mana.max_mana_cap, s.mana.max_mana + 1)
    s.mana.max_mana = next_max
    s.mana.overloaded = s.mana.overload_next
    s.mana.overload_next = 0
    s.mana.available = max(0, next_max - s.mana.overloaded)
    s.mana.modifiers = []

    # Our draw — decrement deck count without adding specific cards to hand.
    # MCTS doesn't know which specific cards we'll draw; the static evaluator
    # estimates hand quality based on hand size.
    if s.deck_remaining > 0:
        s.deck_remaining -= 1
    else:
        s.fatigue_damage += 1
        s.hero.hp -= s.fatigue_damage

    # Our minions can attack
    for m in s.board:
        m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    # Clear turn-level tracking
    s.cards_played_this_turn = []

    return s


def _greedy_opponent_play(state: GameState) -> GameState:
    """Simulate opponent attacking greedily.

    Simple heuristic:
    1. Trade favorably (our minion dies, theirs survives)
    2. Attack taunts if any are present
    3. Go face if no taunts and no favorable trades
    """
    s = state

    # Opponent attacks with each minion
    opp_board = s.opponent.board
    our_board = s.board

    for opp_minion in opp_board:
        if not opp_minion.can_attack or opp_minion.has_attacked_once:
            continue

        traded = False

        # Try favorable trade: kill our minion, theirs survives
        for our_minion in our_board:
            if our_minion.health <= 0:
                continue
            if our_minion.health <= opp_minion.attack and opp_minion.health > our_minion.attack:
                # Favorable trade: kill our minion, theirs survives
                our_minion.health -= opp_minion.attack
                opp_minion.health -= our_minion.attack
                opp_minion.has_attacked_once = True
                traded = True
                break

        if traded:
            continue

        # Check for taunts on our board
        taunts = [m for m in our_board if m.health > 0 and m.has_taunt]

        if taunts:
            # Must attack taunt
            target = taunts[0]
            target.health -= opp_minion.attack
            opp_minion.health -= target.attack
            opp_minion.has_attacked_once = True
        elif len(our_board) == 0 or all(m.health <= 0 for m in our_board):
            # No minions — go face
            s.hero.hp -= opp_minion.attack
            opp_minion.has_attacked_once = True
        else:
            # No favorable trade and no taunts — go face
            s.hero.hp -= opp_minion.attack
            opp_minion.has_attacked_once = True

    # Remove dead minions from both boards
    s.board = [m for m in s.board if m.health > 0]
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s

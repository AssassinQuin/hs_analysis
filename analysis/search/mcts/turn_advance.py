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


def _draw_from_deck(state: GameState) -> object | None:
    """Draw a random card from deck_list, or return None if empty."""
    deck = getattr(state, 'deck_list', None)
    if deck and len(deck) > 0:
        import random
        idx = random.randint(0, len(deck) - 1)
        card = deck.pop(idx)
        return card
    return None


def advance_full_turn(state: GameState, *, greedy_opponent: bool = True) -> GameState:
    """Advance state from our END_TURN to the start of our next turn.

    Cycle:
    1. Our end-of-turn cleanup — already done by _apply_end_turn.
    2. Opponent's turn: mana refresh, draw, minions attack, opponent greedy.
    3. Opponent's end-of-turn cleanup.
    4. Our next turn: mana refresh, draw, minions can attack, greedy play.

    Args:
        state: GameState after our END_TURN has been applied (cleanup done).
        greedy_opponent: If True, simulate opponent attacking greedily.

    Returns:
        New GameState at the end of our next turn (after greedy play).
    """
    s = state.copy()

    # === Step 2: Opponent's turn start ===
    s.turn_number += 1

    opp_estimated_max = min(10, max(1, s.turn_number // 2 + 1))

    if s.opponent.deck_remaining > 0:
        s.opponent.deck_remaining -= 1
        s.opponent.hand_count += 1

    for m in s.opponent.board:
        if not m.has_rush:
            m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    if greedy_opponent:
        s = _greedy_opponent_play(s)

    # === Step 3: Opponent's end-of-turn cleanup ===
    for m in s.board:
        m.frozen_until_next_turn = False
        m.has_immune = False
    s.hero.is_immune = False

    # === Step 4: Our next turn start ===
    s.turn_number += 1

    next_max = min(s.mana.max_mana_cap, s.mana.max_mana + 1)
    s.mana.max_mana = next_max
    s.mana.overloaded = s.mana.overload_next
    s.mana.overload_next = 0
    s.mana.available = max(0, next_max - s.mana.overloaded)
    s.mana.modifiers = []

    if s.deck_remaining > 0:
        drawn = _draw_from_deck(s)
        if drawn is not None:
            s.hand.append(drawn)
        s.deck_remaining -= 1
    else:
        s.fatigue_damage += 1
        s.hero.hp -= s.fatigue_damage

    for m in s.board:
        m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    s.cards_played_this_turn = []

    _apply_turn_start_triggers(s)

    # === Step 4b: Our greedy play — spend mana efficiently ===
    s = _greedy_self_play(s)

    # Greedy attacks with our minions
    s = _greedy_self_attacks(s)

    return s


def _greedy_self_play(state: GameState) -> GameState:
    """Play cards greedily to maximise mana usage.

    Strategy: play the most expensive affordable card first, repeat.
    This simulates reasonable turn play in cross-turn rollouts.
    """
    from analysis.search.rhea.actions import ActionType
    from analysis.search.rhea.simulation import apply_action
    from analysis.search.rhea.enumeration import enumerate_legal_actions

    s = state
    max_plays = 7

    for _ in range(max_plays):
        if s.mana.available <= 0:
            break

        actions = enumerate_legal_actions(s)
        playable = [
            a for a in actions
            if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET)
        ]
        if not playable:
            break

        def _play_value(a):
            idx = a.card_index
            if 0 <= idx < len(s.hand):
                card = s.hand[idx]
                cost = getattr(card, 'cost', 0) or 0
                atk = getattr(card, 'attack', 0) or 0
                hp = getattr(card, 'health', 0) or 0
                eff_cost = s.mana.effective_cost(card)
                if eff_cost > s.mana.available:
                    return -100
                return atk + hp
            return 0

        best = max(playable, key=_play_value)
        bv = _play_value(best)
        if bv < 0:
            break

        s = apply_action(s, best)

    return s


def _greedy_self_attacks(state: GameState) -> GameState:
    """Attack greedily with our minions in cross-turn rollout."""
    from analysis.search.rhea.actions import ActionType
    from analysis.search.rhea.simulation import apply_action
    from analysis.search.rhea.enumeration import enumerate_legal_actions

    s = state

    for _ in range(7):
        actions = enumerate_legal_actions(s)
        attacks = [
            a for a in actions
            if a.action_type == ActionType.ATTACK
        ]
        if not attacks:
            break

        face_attacks = [a for a in attacks if a.target_index == 0]
        if face_attacks:
            s = apply_action(s, face_attacks[0])
        else:
            s = apply_action(s, attacks[0])

    return s


def _apply_turn_start_triggers(state: GameState) -> None:
    """Apply turn-start effects from card text on board minions.

    Handles patterns like:
    - "在你的回合开始时获得+1/+1"
    - "At the start of your turn, gain +1/+1"
    """
    import re
    _TURN_START_BUFF_CN = re.compile(r'回合开始时获得\s*\+(\d+)/\+(\d+)')
    _TURN_START_BUFF_EN = re.compile(
        r'start of your turn.*?gain\s*\+(\d+)/\+(\d+)', re.IGNORECASE
    )
    for m in state.board:
        text = ''
        card_ref = getattr(m, 'card_ref', None)
        if card_ref is not None:
            text = getattr(card_ref, 'text', '') or ''
        if not text:
            text = getattr(m, 'text', '') or ''
        if not text:
            continue
        match = _TURN_START_BUFF_CN.search(text) or _TURN_START_BUFF_EN.search(text)
        if match:
            atk_bonus = int(match.group(1))
            hp_bonus = int(match.group(2))
            m.attack += atk_bonus
            m.health += hp_bonus
            m.max_health += hp_bonus


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

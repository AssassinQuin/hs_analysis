#!/usr/bin/env python3
"""perspective_swap.py — Swap player/opponent perspective for opponent simulation.

The core idea: to simulate the opponent's turn using the existing action
enumeration and apply_action system, we temporarily swap the GameState
so that the opponent becomes "us" and vice versa. After simulation,
we swap back.

This reuses ALL existing mechanics:
- enumerate_legal_actions() works on the swapped state
- apply_action() works on the swapped state
- Effect chains, deathrattles, triggers, auras all work correctly
- No need to duplicate opponent-specific logic

Usage:
    from analysis.search.perspective_swap import swap_perspective, swap_back

    # Swap to opponent perspective
    opp_state, saved = swap_perspective(state)

    # Simulate opponent turn using normal action system
    actions = enumerate_legal_actions(opp_state)
    for action in actions:
        opp_state = apply_action(opp_state, action)

    # Swap back to our perspective
    result_state = swap_back(opp_state, saved)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState, OpponentState

log = logging.getLogger(__name__)


def swap_perspective(state: 'GameState') -> Tuple['GameState', dict]:
    """Swap player ↔ opponent perspective in GameState.

    Returns (swapped_state, saved_context) where saved_context contains
    fields that need special handling when swapping back.

    After this call:
    - swapped_state.hero = original opponent's hero
    - swapped_state.board = original opponent's board
    - swapped_state.hand = original opponent's hand (inferred)
    - swapped_state.opponent = original player's state
    """
    from analysis.card.engine.state import GameState, OpponentState, ManaState, ManaModifier

    s = state.copy()

    # Save context that needs special handling when swapping back
    saved = {
        'our_playstyle': s.our_playstyle,
        'opp_playstyle': s.opp_playstyle,
        'turn_number': s.turn_number,
        'corpses': s.corpses,
        'herald_count': s.herald_count,
        'active_quests': list(s.active_quests),
        'last_turn_races': set(s.last_turn_races),
        'last_turn_schools': set(s.last_turn_schools),
        'kindred_double_next': s.kindred_double_next,
        'fatigue_damage': s.fatigue_damage,
        'cards_played_this_turn': list(s.cards_played_this_turn),
        'last_played_card': s.last_played_card,
        # Save our mana state for restoration
        'mana_state': s.mana.copy(),
        # Save our deck list for restoration
        'deck_list': list(s.deck_list) if s.deck_list else None,
        # Save our locations
        'our_locations': list(s.locations) if s.locations else [],
        # Save our secrets
        'our_secrets': list(s.secrets) if hasattr(s, 'secrets') else [],
    }

    # Build opponent's mana state from opponent context
    # Opponent mana is estimated based on turn number
    opp_mana_max = min(10, s.turn_number // 2 + 1)
    opp_mana = ManaState(
        available=opp_mana_max,  # Opponent gets full mana on their turn
        overloaded=0,
        max_mana=opp_mana_max,
        overload_next=0,
    )

    # Apply opponent cost modifiers
    for mod in s.opponent.opp_cost_modifiers:
        mod_type, value, scope = mod
        opp_mana.modifiers.append(ManaModifier(
            modifier_type=mod_type,
            value=value,
            scope=scope,
        ))

    # Create opponent's hand from opponent.hand (Bayesian-sampled)
    opp_hand = list(s.opponent.hand)

    # Build the swapped GameState
    swapped = GameState(
        hero=s.opponent.hero.copy(),
        mana=opp_mana,
        board=[m.copy() for m in s.opponent.board],
        locations=[],  # Opponent locations not fully tracked
        hand=opp_hand,
        deck_list=None,
        deck_remaining=s.opponent.deck_remaining,
        opponent=OpponentState(
            hero=s.hero.copy(),
            board=[m.copy() for m in s.board],
            hand=list(s.hand),
            hand_count=len(s.hand),
            secrets=list(s.secrets) if hasattr(s, 'secrets') else [],
            deck_remaining=s.deck_remaining,
        ),
        turn_number=s.turn_number,
        our_playstyle=s.opp_playstyle,
        opp_playstyle=s.our_playstyle,
        cards_played_this_turn=[],
        fatigue_damage=0,  # Reset for opponent perspective
        herald_count=s.opponent.opp_herald_count,
        active_quests=list(s.opponent.opp_quests),
        corpses=s.opponent.opp_corpses,
        last_turn_races=set(),
        last_turn_schools=set(),
        kindred_double_next=False,
    )

    # Fix minion ownership in swapped board
    for m in swapped.board:
        m.owner = "friendly"
        m.can_attack = True  # Opponent's minions can attack on their turn
        m.has_attacked_once = False

    for m in swapped.opponent.board:
        m.owner = "enemy"

    return swapped, saved


def swap_back(swapped_state: 'GameState', saved: dict) -> 'GameState':
    """Swap back from opponent perspective to our perspective.

    Takes the simulated opponent state and converts it back to our perspective,
    preserving the results of the opponent's actions (board state, HP, etc.).
    """
    from analysis.card.engine.state import GameState, OpponentState, ManaState

    s = swapped_state

    # Build our new state from the swapped perspective
    # Our hero is now the "opponent" in the swapped state
    our_new_hero = s.opponent.hero.copy()
    our_new_board = [m.copy() for m in s.opponent.board]
    for m in our_new_board:
        m.owner = "friendly"

    # Opponent's new state is the "hero" side in the swapped state
    opp_new_hero = s.hero.copy()
    opp_new_board = [m.copy() for m in s.board]
    for m in opp_new_board:
        m.owner = "enemy"

    # Opponent's new hand: whatever they have left after playing cards
    opp_hand_after = list(s.hand)

    # Restore our mana state (will be recalculated on our next turn anyway)
    saved_mana = saved.get('mana_state')
    if saved_mana is not None:
        our_mana = saved_mana.copy()
    else:
        our_mana = ManaState(
            available=0,  # Will be recalculated on our next turn
            max_mana=saved.get('mana_max', 0),
        )

    result = GameState(
        hero=our_new_hero,
        mana=our_mana,
        board=our_new_board,
        locations=saved.get('our_locations', []),
        hand=list(s.opponent.hand),  # Our hand is unchanged
        deck_list=saved.get('deck_list'),
        deck_remaining=s.opponent.deck_remaining,
        opponent=OpponentState(
            hero=opp_new_hero,
            board=opp_new_board,
            hand=opp_hand_after,
            hand_count=len(opp_hand_after),
            secrets=list(s.opponent.secrets),
            deck_remaining=s.deck_remaining,
            opp_corpses=s.corpses,
            opp_herald_count=s.herald_count,
            opp_quests=list(s.active_quests),
            opp_cost_modifiers=[],  # Opponent cost mods consumed on their turn
        ),
        turn_number=saved['turn_number'],
        our_playstyle=saved['our_playstyle'],
        opp_playstyle=saved['opp_playstyle'],
        cards_played_this_turn=[],
        fatigue_damage=saved['fatigue_damage'],
        herald_count=saved['herald_count'],
        active_quests=saved['active_quests'],
        corpses=saved['corpses'],
        last_turn_races=saved['last_turn_races'],
        last_turn_schools=saved['last_turn_schools'],
        kindred_double_next=saved['kindred_double_next'],
        last_played_card=saved['last_played_card'],
    )

    return result

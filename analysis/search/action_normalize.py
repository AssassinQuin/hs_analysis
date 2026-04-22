"""action_normalize.py — Action normalization for canonical chromosome ordering.

Provides utilities to sort commutative actions into a canonical order,
enabling duplicate detection and diversity maintenance in the RHEA engine.

Key idea: two ATTACK actions with different sources and non-conflicting
targets are commutative (order doesn't matter). We sort such groups
by action_hash to get a stable, canonical representation.
"""

from __future__ import annotations

from typing import List, Tuple

from analysis.search.rhea_engine import Action
from analysis.search.game_state import GameState


# ===================================================================
# action_hash
# ===================================================================

def action_hash(action: Action) -> tuple:
    """Return a hashable tuple for canonical ordering of actions.

    Returns (action_type, source_key, target_key) where:
      - PLAY:   source_key = card_index,  target_key = -1
      - ATTACK: source_key = source_index, target_key = target_index
      - others: source_key = action_type,  target_key = -1
    """
    if action.action_type == "PLAY":
        return (action.action_type, action.card_index, -1)
    elif action.action_type == "ATTACK":
        return (action.action_type, action.source_index, action.target_index)
    else:
        return (action.action_type, action.action_type, -1)


# ===================================================================
# are_commutative
# ===================================================================

def are_commutative(a1: Action, a2: Action, state: GameState) -> bool:
    """Return True if two actions are commutative (order-independent).

    Two actions are commutative if:
      - Both are ATTACK actions
      - They have different source minions
      - They don't share a non-face target
    """
    if a1.action_type != "ATTACK" or a2.action_type != "ATTACK":
        return False
    if a1.source_index == a2.source_index:
        return False  # same source = not commutative
    # Different sources attacking different targets (or same face target)
    # Commutative if both go face (target_index=0) or target different minions
    if a1.target_index == a2.target_index and a1.target_index != 0:
        return False  # same non-face target = not commutative
    return True


# ===================================================================
# normalize_chromosome
# ===================================================================

def normalize_chromosome(chromosome: list, state: GameState) -> list:
    """Sort commutative action groups into canonical order.

    Finds maximal runs of consecutive commutative actions and sorts each
    group by action_hash. Non-commutative actions maintain their position.

    Preserves semantics: the normalized chromosome produces the same final
    state when applied (for valid commutative groups).
    """
    if not chromosome:
        return chromosome
    result = list(chromosome)
    # Find groups of consecutive commutative actions
    i = 0
    while i < len(result) - 1:
        if are_commutative(result[i], result[i + 1], state):
            # Find the end of this commutative group
            j = i + 1
            while j < len(result) and are_commutative(result[i], result[j], state):
                j += 1
            # Sort the group by action_hash
            group = result[i:j]
            group.sort(key=action_hash)
            result[i:j] = group
            i = j
        else:
            i += 1
    return result


# ===================================================================
# is_canonical
# ===================================================================

def is_canonical(chromosome: list, state: GameState) -> bool:
    """Return True if the chromosome is already in canonical form."""
    return chromosome == normalize_chromosome(chromosome, state)

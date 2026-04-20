"""rewind.py — Rewind mechanic card detection and branch evaluation.

V10 Phase 3: Detects rewind (回溯) cards and provides a helper for
evaluating two branches during RHEA fitness evaluation.

Note: Full integration with the RHEA chromosome evaluator would require
changes to _evaluate_chromosome. This module provides the building blocks.
"""

from __future__ import annotations

from typing import Tuple


# ===================================================================
# is_rewind_card
# ===================================================================

def is_rewind_card(card) -> bool:
    """Return True if the card has the Rewind (回溯) mechanic.

    Detection logic:
    1. 'REWIND' in mechanics
    2. '回溯' in card text
    3. 'TRIGGER_VISUAL' in mechanics AND '回溯' in text (combo pattern)
    """
    mechanics = getattr(card, 'mechanics', None) or []
    text = getattr(card, 'text', '') or ''

    # Direct mechanic check
    if 'REWIND' in mechanics:
        return True

    # Chinese text check
    if '回溯' in text:
        return True

    return False


# ===================================================================
# REWIND_SCORING_BONUS
# ===================================================================

# Flat bonus for rewind cards in fitness evaluation.
# Having a second chance is valuable even without branch simulation.
REWIND_SCORING_BONUS: float = 0.5


# ===================================================================
# evaluate_with_rewind
# ===================================================================

def evaluate_with_rewind(state, card, apply_func, fitness_func) -> Tuple:
    """Evaluate a rewind card by trying two branches and picking the better one.

    This is a helper for the RHEA fitness evaluation, NOT for apply_action.

    Args:
        state: Current GameState (will be copied for each branch)
        card: The rewind card to evaluate
        apply_func: Callable(state, card) -> state that applies the card
        fitness_func: Callable(state) -> float that evaluates fitness

    Returns:
        Tuple of (best_state, best_fitness) from the two branches.
    """
    # Branch A
    snapshot_a = state.copy()
    result_a = apply_func(snapshot_a, card)
    fitness_a = fitness_func(result_a)

    # Branch B (fresh copy from original state)
    snapshot_b = state.copy()
    result_b = apply_func(snapshot_b, card)
    fitness_b = fitness_func(result_b)

    # Return the better branch (tie goes to branch A for stability)
    if fitness_b > fitness_a:
        return result_b, fitness_b
    return result_a, fitness_a

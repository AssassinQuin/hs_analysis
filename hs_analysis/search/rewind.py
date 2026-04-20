"""rewind.py — Rewind mechanic card detection and branch evaluation.

V10 Phase 3: Detects rewind (回溯) cards and provides a helper for
evaluating two branches during RHEA fitness evaluation.

Rewind mechanic: when a card with 回溯 is played, the player gets to
discover (choose from 3 options) a second copy of the effect. Branch A
plays the card normally; Branch B applies the effect twice (simulating
picking the same effect from the discover).
"""

from __future__ import annotations

from typing import Tuple


def is_rewind_card(card) -> bool:
    mechanics = getattr(card, 'mechanics', None) or []
    text = getattr(card, 'text', '') or ''

    if 'REWIND' in mechanics:
        return True

    if '回溯' in text:
        return True

    return False


REWIND_SCORING_BONUS: float = 0.5


def evaluate_with_rewind(state, card, apply_func, fitness_func) -> Tuple:
    """Evaluate a rewind card by trying two branches and picking the better one.

    Branch A: apply the card normally (no rewind bonus).
    Branch B: apply the card TWICE (simulating rewind discover picking same effect).

    Args:
        state: Current GameState (will be copied for each branch)
        card: The rewind card to evaluate
        apply_func: Callable(state, card) -> state that applies the card
        fitness_func: Callable(state) -> float that evaluates fitness

    Returns:
        Tuple of (best_state, best_fitness) from the two branches.
    """
    # Branch A: normal play (no rewind)
    snapshot_a = state.copy()
    result_a = apply_func(snapshot_a, card)
    fitness_a = fitness_func(result_a)

    # Branch B: rewind — apply card effect twice (simulating discover same card)
    snapshot_b = state.copy()
    result_b = apply_func(snapshot_b, card)
    result_b = apply_func(result_b, card)
    fitness_b = fitness_func(result_b)

    if fitness_b > fitness_a:
        return result_b, fitness_b
    return result_a, fitness_a

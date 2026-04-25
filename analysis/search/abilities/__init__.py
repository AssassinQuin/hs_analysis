#!/usr/bin/env python3
"""abilities — Unified card ability system and search engine primitives.

Parses card effects from mechanics tags + English text tokens (zero regex).
Provides a single execution entry point (AbilityExecutor) for all effects.

Also contains action types, enumeration, and simulation logic for turn planning.
Import directly from sub-modules to avoid circular imports:
  from analysis.search.abilities.actions import Action, ActionType
  from analysis.search.abilities.enumeration import enumerate_legal_actions
  from analysis.search.abilities.simulation import apply_action
"""

# Eager imports — safe (no heavy dependencies, no circular import risk)
from analysis.search.abilities.actions import (
    Action, ActionType, action_key, action_in_list,
)


# NOTE: Do NOT import simulation/enumeration here — they have heavy
# dependencies that create circular imports when loaded eagerly.
# Use lazy wrappers for functions that consumers import at package level:

def enumerate_legal_actions(*args, **kwargs):
    """Lazy re-export to avoid circular import via quest.py."""
    from analysis.search.abilities.enumeration import enumerate_legal_actions as _fn
    return _fn(*args, **kwargs)


def apply_action(*args, **kwargs):
    """Lazy re-export."""
    from analysis.search.abilities.simulation import apply_action as _fn
    return _fn(*args, **kwargs)


def apply_draw(*args, **kwargs):
    """Lazy re-export."""
    from analysis.search.abilities.simulation import apply_draw as _fn
    return _fn(*args, **kwargs)


def next_turn_lethal_check(*args, **kwargs):
    """Lazy re-export."""
    from analysis.search.abilities.simulation import next_turn_lethal_check as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "Action", "ActionType", "action_key", "action_in_list",
    "enumerate_legal_actions", "apply_action", "apply_draw",
    "next_turn_lethal_check",
]

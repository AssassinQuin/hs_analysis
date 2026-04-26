#!/usr/bin/env python3
"""Backward-compatibility shim — all types now live in analysis.abilities.definition.

Import directly from the new locations:
  from analysis.abilities.definition import Action, ActionType
  from analysis.engine.rules import enumerate_legal_actions
  from analysis.engine.simulation import apply_action
"""

# Eager imports from new location
from analysis.abilities.definition import (
    Action, ActionType, action_key, action_in_list,
)


# NOTE: Do NOT import simulation/enumeration here — they have heavy
# dependencies that create circular imports when loaded eagerly.
# Use lazy wrappers for functions that consumers import at package level:

def enumerate_legal_actions(*args, **kwargs):
    """Lazy re-export to avoid circular import via quest.py."""
    from analysis.engine.rules import enumerate_legal_actions as _fn
    return _fn(*args, **kwargs)


def apply_action(*args, **kwargs):
    """Lazy re-export."""
    from analysis.engine.simulation import apply_action as _fn
    return _fn(*args, **kwargs)


def apply_draw(*args, **kwargs):
    """Lazy re-export."""
    from analysis.engine.simulation import apply_draw as _fn
    return _fn(*args, **kwargs)


def next_turn_lethal_check(*args, **kwargs):
    """Lazy re-export."""
    from analysis.engine.simulation import next_turn_lethal_check as _fn
    return _fn(*args, **kwargs)


def load_abilities(*args, **kwargs):
    """Lazy re-export for JSON ability loader."""
    from analysis.abilities.loader import load_abilities as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "Action", "ActionType", "action_key", "action_in_list",
    "enumerate_legal_actions", "apply_action", "apply_draw",
    "next_turn_lethal_check", "load_abilities",
]

# -*- coding: utf-8 -*-
"""rhea — Rolling Horizon Evolutionary Algorithm for Hearthstone turn planning.

This package contains the decomposed RHEA engine. All public symbols are
re-exported here for backward compatibility with ``analysis.search.rhea_engine``.
"""

from analysis.search.rhea.actions import Action, ActionType, action_key, action_in_list
from analysis.search.rhea.enumeration import enumerate_legal_actions
from analysis.search.rhea.simulation import (
    apply_action,
    apply_draw,
    next_turn_lethal_check,
    _try_mechanic,
)
from analysis.search.rhea.result import SearchResult
from analysis.search.rhea.engine import RHEAEngine

__all__ = [
    "Action",
    "ActionType",
    "action_key",
    "action_in_list",
    "enumerate_legal_actions",
    "apply_action",
    "apply_draw",
    "next_turn_lethal_check",
    "SearchResult",
    "RHEAEngine",
]

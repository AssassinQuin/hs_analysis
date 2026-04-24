#!/usr/bin/env python3
"""rhea_engine.py — Backward-compatibility shim.

All exports have been moved to the ``analysis.search.rhea`` package.
This file re-exports everything so that existing imports like::

    from analysis.search.rhea_engine import RHEAEngine, Action

continue to work without any changes.
"""

# Re-export all public API from the rhea package
from analysis.search.rhea import (  # noqa: F401
    Action,
    ActionType,
    action_key as _action_key,
    action_in_list as _action_in_list,
    enumerate_legal_actions,
    apply_action,
    apply_draw,
    next_turn_lethal_check,
    SearchResult,
    RHEAEngine,
)

# Re-export optional dependencies that tests access as module attributes
from analysis.search.rhea.engine import (  # noqa: F401
    check_lethal,
    RiskAssessor,
    RiskReport,
    OpponentSimulator,
)

#!/usr/bin/env python3
"""spell_simulator.py — v1 effects engine removed.

The v1 effects engine (analysis.effects) has been replaced by
analysis.card.engine (v2). This module is kept as a migration stub.
"""

import logging

log = logging.getLogger(__name__)

try:
    from analysis.card.engine.simulation import apply_action, apply_draw
    from analysis.card.engine.target import orchestrate
    from analysis.card.abilities.executor import SpellExecutor
except ImportError:
    log.warning("v2 card engine not available")

__all__ = [
    "EffectApplier",
    "resolve_effects",
]


class EffectApplier:
    """Stub — replaced by card.abilities.executor.SpellExecutor in v2."""

    @staticmethod
    def apply(effects, state, source=None, target=None):
        raise NotImplementedError(
            "EffectApplier (v1 effects engine) has been removed. "
            "Use analysis.card.abilities.executor.SpellExecutor instead."
        )


def resolve_effects(state, card, target_index=-1):
    """Stub — replaced by card.engine.target.orchestrate in v2."""
    from analysis.card.engine.target import orchestrate
    return orchestrate(state, card, [], {})

#!/usr/bin/env python3
"""engine_adapter.py — Thin adapter so DecisionLoop can use RHEA or MCTS interchangeably.

Usage:
    from analysis.search.engine_adapter import create_engine

    engine_factory = create_engine("rhea", params)
    engine = engine_factory()
    result = engine.search(state)
    # result always has: best_chromosome, best_fitness, confidence,
    #                     population_diversity, generations_run, timings, alternatives
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from analysis.search.rhea.actions import Action


# ── Unified result wrapper ──────────────────────────────────────────

class UnifiedSearchResult:
    """Normalised search result that DecisionLoop / DecisionPresenter can consume.

    Wraps either an RHEA ``SearchResult`` or an MCTS ``SearchResult`` and
    exposes a uniform attribute interface.
    """

    __slots__ = (
        "_raw",
        "best_chromosome",
        "best_fitness",
        "alternatives",
        "confidence",
        "population_diversity",
        "generations_run",
        "timings",
    )

    def __init__(self, raw: Any):
        self._raw = raw

        # --- fields present in both engine results ---
        self.alternatives: List[Tuple[List[Action], float]] = getattr(raw, "alternatives", [])

        # --- RHEA-native path (used as-is) ---
        if hasattr(raw, "best_chromosome"):
            self.best_chromosome: List[Action] = raw.best_chromosome
            self.best_fitness: float = raw.best_fitness
            self.confidence: float = getattr(raw, "confidence", 0.0)
            self.population_diversity: float = getattr(raw, "population_diversity", 0.0)
            self.generations_run: int = getattr(raw, "generations_run", 0)
            self.timings: dict = getattr(raw, "timings", {})
        # --- MCTS path (map field names) ---
        else:
            self.best_chromosome: List[Action] = raw.best_sequence
            self.best_fitness: float = raw.fitness
            mcts_stats = getattr(raw, "mcts_stats", None)
            self.confidence: float = 0.0
            self.population_diversity: float = 0.0
            self.generations_run: int = getattr(mcts_stats, "iterations", 0) if mcts_stats else 0
            self.timings: dict = (
                {"mcts": getattr(mcts_stats, "time_used_ms", 0.0)} if mcts_stats else {}
            )


# ── Engine factories ────────────────────────────────────────────────

def _rhea_factory(params: Dict[str, Any]) -> Callable[[], Any]:
    """Return a callable that creates an ``RHEAEngine`` per invocation."""
    from analysis.search.rhea.engine import RHEAEngine

    def factory() -> Any:
        return RHEAEngine(
            pop_size=params.get("pop_size", 30),
            max_gens=params.get("max_gens", 80),
            time_limit=params.get("time_limit", 75.0),
            max_chromosome_length=params.get("max_chromosome_length", 8),
            cross_turn=params.get("cross_turn", True),
        )

    return factory


def _mcts_factory(params: Dict[str, Any]) -> Callable[[], Any]:
    """Return a callable that creates an ``MCTSEngine`` per invocation."""
    from analysis.search.mcts.engine import MCTSEngine
    from analysis.search.mcts.config import MCTSConfig

    config = MCTSConfig(
        time_budget_ms=params.get("time_budget_ms", 8000.0),
        num_worlds=params.get("num_worlds", 7),
    )
    # Override any additional MCTSConfig fields present in params
    for key in ("uct_constant", "time_decay_gamma", "max_actions_per_turn"):
        if key in params:
            setattr(config, key, params[key])

    def factory() -> Any:
        return MCTSEngine(config=config)

    return factory


_ENGINES = {
    "rhea": _rhea_factory,
    "mcts": _mcts_factory,
}


def create_engine(name: str, params: Dict[str, Any] | None = None) -> Callable[[], Any]:
    """Return a zero-arg factory that produces the chosen engine.

    Args:
        name: ``"rhea"`` or ``"mcts"``.
        params: Engine-specific parameters forwarded to the constructor.

    Returns:
        A callable ``() -> engine`` whose ``search(state)`` returns a result
        that can be wrapped with :class:`UnifiedSearchResult`.
    """
    factory_fn = _ENGINES.get(name)
    if factory_fn is None:
        raise ValueError(f"Unknown engine '{name}'. Choose from: {list(_ENGINES)}")
    return factory_fn(params or {})

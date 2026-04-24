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


# ── Action probability / win-rate data ──────────────────────────────

class ActionProb:
    """Per-action probability and win-rate for display."""

    __slots__ = ("action", "visit_count", "probability", "win_rate", "q_value")

    def __init__(
        self,
        action: Action,
        visit_count: int = 0,
        probability: float = 0.0,
        win_rate: float = 0.0,
        q_value: float = 0.0,
    ):
        self.action = action
        self.visit_count = visit_count
        self.probability = probability
        self.win_rate = win_rate
        self.q_value = q_value


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
        "action_probs",
        "mcts_stats",
        "mcts_detailed_log",
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
            self.action_probs: List[ActionProb] = []
            self.mcts_stats = None
            self.mcts_detailed_log = None
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
            # Extract per-action stats from MCTS
            raw_action_stats = getattr(raw, "action_stats", [])
            self.action_probs: List[ActionProb] = [
                ActionProb(
                    action=ast.action,
                    visit_count=ast.visit_count,
                    probability=ast.visit_probability,
                    win_rate=ast.win_rate,
                    q_value=ast.q_value,
                )
                for ast in raw_action_stats
            ]
            self.mcts_stats = mcts_stats
            self.mcts_detailed_log = getattr(raw, "detailed_log", None)


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

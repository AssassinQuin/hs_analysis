#!/usr/bin/env python3
"""engine_adapter.py — Thin adapter so DecisionLoop can use MCTS engine.

NOTE: RHEA support has been disabled. Only MCTS mode is active.
      RHEA modules will be removed in a future cleanup.
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

    Wraps an MCTS ``SearchResult`` and exposes a uniform attribute interface.
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
        # [DISABLED] RHEA support commented out — only MCTS path is active.
        # if hasattr(raw, "best_chromosome"):
        #     self.best_chromosome: List[Action] = raw.best_chromosome
        #     ... (removed for clarity, see git history)

        # --- MCTS path (now the only path) ---
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

# [DISABLED] RHEA factory — will be removed in future cleanup
# def _rhea_factory(params: Dict[str, Any]) -> Callable[[], Any]:
#     from analysis.search.rhea.engine import RHEAEngine
#     def factory() -> Any:
#         return RHEAEngine(...)
#     return factory


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
    # "rhea": _rhea_factory,  # [DISABLED]
    "mcts": _mcts_factory,
}


def create_engine(name: str, params: Dict[str, Any] | None = None) -> Callable[[], Any]:
    """Return a zero-arg factory that produces the chosen engine.

    Args:
        name: ``"mcts"`` (RHEA is disabled).
        params: Engine-specific parameters forwarded to the constructor.

    Returns:
        A callable ``() -> engine`` whose ``search(state)`` returns a result
        that can be wrapped with :class:`UnifiedSearchResult`.
    """
    # Silently redirect "rhea" to "mcts"
    if name == "rhea":
        name = "mcts"
    factory_fn = _ENGINES.get(name)
    if factory_fn is None:
        raise ValueError(f"Unknown engine '{name}'. Only 'mcts' is supported.")
    return factory_fn(params or {})

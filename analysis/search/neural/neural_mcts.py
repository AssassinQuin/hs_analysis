#!/usr/bin/env python3
"""neural_mcts.py — Neural-guided MCTS bridge layer.

Provides :class:`NeuralMCTS` which transparently injects neural network
priors into the MCTS search loop.  When no models are loaded it delegates
to the standard :class:`MCTSEngine` with zero overhead.

Also exports helper functions for computing neural priors and blending
them with UCB exploration.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.engine.state import GameState

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Neural MCTS engine
# ---------------------------------------------------------------------------

class NeuralMCTS:
    """Neural-guided MCTS engine.

    Behavior modes:
    - **Models loaded**: use policy prior for selection + value net for
      leaf evaluation (neural-guided search).
    - **No models**: delegate to regular :class:`MCTSEngine` with zero
      overhead — the search is indistinguishable from plain MCTS.

    This is a thin wrapper that injects neural priors into the existing
    MCTS loop.  The actual neural search implementation will be filled in
    when real models are available.
    """

    def __init__(
        self,
        policy_net: Optional[Any] = None,
        value_net: Optional[Any] = None,
    ) -> None:
        """Initialise NeuralMCTS.

        Args:
            policy_net: A :class:`PolicyNet` instance, or ``None`` to use
                the registry (which defaults to ``RandomPolicyNet``).
            value_net: A :class:`ValueNet` instance, or ``None`` to use
                the registry (which defaults to ``HeuristicValueNet``).
        """
        self._policy = policy_net
        self._value = value_net
        self._mcts_engine: Optional[Any] = None

    # -- Public API ---------------------------------------------------------

    def search(
        self,
        state: Any,
        time_budget_ms: float = 8000,
        **kwargs: Any,
    ) -> Any:
        """Search for the best action sequence.

        Args:
            state: Current :class:`GameState`.
            time_budget_ms: Time budget in milliseconds.
            **kwargs: Forwarded to :meth:`MCTSEngine.search` (e.g.
                ``bayesian_model``, ``opp_playstyle``).

        Returns:
            A :class:`SearchResult` (same format as regular MCTS).
        """
        if not self._has_models():
            return self._regular_mcts(state, time_budget_ms, **kwargs)

        # Models available — neural-guided search
        return self._neural_search(state, time_budget_ms, **kwargs)

    # -- Internal helpers ---------------------------------------------------

    def _has_models(self) -> bool:
        """Check if both policy and value nets are loaded and usable."""
        if self._policy is None or self._value is None:
            return False
        # Fallback models always report is_loaded == False
        return getattr(self._policy, "is_loaded", False) and getattr(
            self._value, "is_loaded", False
        )

    def _regular_mcts(
        self,
        state: Any,
        time_budget_ms: float,
        **kwargs: Any,
    ) -> Any:
        """Delegate to standard :class:`MCTSEngine`.

        Uses lazy import to avoid circular dependencies.
        """
        if self._mcts_engine is None:
            from analysis.search.mcts.engine import MCTSEngine
            self._mcts_engine = MCTSEngine()

        return self._mcts_engine.search(state, time_budget_ms=time_budget_ms, **kwargs)

    def _neural_search(
        self,
        state: Any,
        time_budget_ms: float,
        **kwargs: Any,
    ) -> Any:
        """Neural-guided search (future implementation).

        For now, falls back to regular MCTS with a log message.
        This will be implemented when concrete models are available.
        """
        log.info(
            "Neural search requested but not yet implemented — "
            "falling back to regular MCTS"
        )
        return self._regular_mcts(state, time_budget_ms, **kwargs)

    # -- Factory ------------------------------------------------------------

    @staticmethod
    def from_registry() -> NeuralMCTS:
        """Create a :class:`NeuralMCTS` from the :class:`ModelRegistry` singleton.

        Returns:
            A new ``NeuralMCTS`` instance wired to whatever models are
            currently registered (or ``None`` if using fallbacks).
        """
        from analysis.search.neural.interfaces import ModelRegistry

        reg = ModelRegistry.get()
        return NeuralMCTS(
            policy_net=reg._policy_net,
            value_net=reg._value_net,
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def compute_mcts_prior(
    state: Any,
    policy_net: Any,
) -> dict:
    """Compute action priors from a policy network.

    Enumerates legal actions from *state*, encodes the state and action
    features, then calls *policy_net.predict* to get a probability
    distribution.  Returns a mapping from ``action_key(action)`` to
    probability.

    Args:
        state: Current :class:`GameState`.
        policy_net: A :class:`PolicyNet` instance.

    Returns:
        ``dict[tuple, float]`` mapping action keys to prior probabilities.
        Only legal actions are included; probabilities sum to ~1.0.
    """
    from analysis.abilities.definition import action_key
    from analysis.engine.rules import enumerate_legal_actions

    legal = enumerate_legal_actions(state)
    if not legal:
        return {}

    # Build action mask and features (placeholder encoding)
    action_mask: list[float] = [1.0] * len(legal)
    action_features: list[list[float]] = [
        [0.0] * 13 for _ in legal
    ]

    # State vector placeholder — real encoder will be used later
    state_vector: list[float] = [0.0] * 294

    probs = policy_net.predict(state_vector, action_mask, action_features)

    prior: dict = {}
    for action, prob in zip(legal, probs):
        prior[action_key(action)] = prob

    return prior


def compute_state_value(
    state: Any,
    value_net: Any,
) -> float:
    """Get a value estimate for *state* from a value network.

    Args:
        state: Current :class:`GameState`.
        value_net: A :class:`ValueNet` instance.

    Returns:
        A float in [-1, 1] where 1.0 = certain win, -1.0 = certain loss.
    """
    # State vector placeholder — real encoder will be used later
    state_vector: list[float] = [0.0] * 294
    return value_net.predict(state_vector)


def blend_ucb(
    q_value: float,
    prior: float,
    visit_count: int,
    c_puct: float = 1.5,
) -> float:
    """Compute the PUCT-blended UCB score for neural-guided selection.

    Formula::

        UCB = Q + c_puct * prior * sqrt(parent_visits) / (1 + visit_count)

    This replaces the standard UCB1 exploration term with a
    prior-weighted version, allowing the policy network to guide
    initial exploration toward promising actions.

    Args:
        q_value: Exploitation term — average reward from this node.
        prior: Prior probability from the policy network for this action.
        visit_count: Number of times this node has been visited.
        c_puct: Exploration constant (higher = more exploration).
            Typical values: 1.0–2.0.  Default: 1.5.

    Returns:
        A float score; higher is better for selection.
    """
    if visit_count <= 0:
        # Unvisited node — rely entirely on prior with a safety floor
        return q_value + c_puct * prior * 10.0

    exploration = c_puct * prior * math.sqrt(visit_count) / (1 + visit_count)
    return q_value + exploration

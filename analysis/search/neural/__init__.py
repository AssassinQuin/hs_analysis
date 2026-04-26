#!/usr/bin/env python3
"""analysis.search.neural — Neural network interfaces for Hearthstone AI.

This package provides abstract interfaces for neural networks and a bridge
layer that connects them to the MCTS search engine.  When no models are
loaded, the system transparently falls back to regular MCTS with zero
overhead.

Public API:
    NeuralMCTS      — neural-guided MCTS search (falls back to regular MCTS)
    ModelRegistry   — singleton for managing model instances
    PolicyNet       — abstract policy network interface
    ValueNet        — abstract value network interface
    RandomPolicyNet — fallback uniform random policy
    HeuristicValueNet — fallback heuristic board evaluation
    compute_mcts_prior  — compute action priors from policy net
    compute_state_value — get value estimate from value net
    blend_ucb           — PUCT formula for neural-guided selection
"""

from analysis.search.neural.interfaces import (
    PolicyNet,
    ValueNet,
    RandomPolicyNet,
    HeuristicValueNet,
    ModelRegistry,
)
from analysis.search.neural.neural_mcts import (
    NeuralMCTS,
    compute_mcts_prior,
    compute_state_value,
    blend_ucb,
)

__all__ = [
    # Interfaces
    "PolicyNet",
    "ValueNet",
    # Fallbacks
    "RandomPolicyNet",
    "HeuristicValueNet",
    # Registry
    "ModelRegistry",
    # Bridge
    "NeuralMCTS",
    # Helpers
    "compute_mcts_prior",
    "compute_state_value",
    "blend_ucb",
]

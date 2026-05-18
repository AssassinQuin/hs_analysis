#!/usr/bin/env python3
"""config.py — MCTS search engine configuration and enums."""

from __future__ import annotations

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional


class NodeType(Enum):
    """MCTS tree node type.

    DECISION — player choice node (select one action from legal set)
    CHANCE   — stochastic outcome node (discover, random effect, draw)
    """
    DECISION = auto()
    CHANCE = auto()


class SimulationMode(Enum):
    """Leaf evaluation strategy."""
    EVAL_CUTOFF = "eval_cutoff"   # use evaluate_delta directly (fastest)
    HYBRID = "hybrid"             # short rollout (1-2 steps) + eval cutoff
    RANDOM = "random"             # full random rollout (baseline)


class ExpansionOrder(Enum):
    """Order in which untried actions are selected for expansion."""
    RANDOM = "random"
    HEURISTIC = "heuristic"
    BALANCED = "balanced"


@dataclass
class MCTSConfig:
    """Complete parameter configuration for the MCTS search engine."""

    # === UCT parameters ===
    uct_constant: float = 0.5               # UCB1 exploration constant c
    # range: 0.25-1.0  (aggro low / control high)

    # === Determinization parameters ===
    num_worlds: int = 7                      # DUCT world count
    # range: 5-11
    sampling_method: str = "bayesian"        # "uniform" / "bayesian"

    # === Progressive Widening parameters ===
    pw_constant: float = 1.0                 # PW coefficient C
    pw_alpha: float = 0.5                    # PW exponent alpha
    # k = floor(C * n^alpha)

    # === Simulation / evaluation parameters ===
    simulation_mode: SimulationMode = SimulationMode.EVAL_CUTOFF
    rollout_depth: int = 1                   # hybrid mode rollout depth (turns)
    eval_normalization_scale: float = 15.0   # tanh(raw/scale) normalization factor

    # === Chance node sampling ===
    discover_samples: int = 3                # number of discover outcome samples
    rng_samples: int = 5                     # number of random-effect outcome samples

    # === Time budget ===
    time_budget_ms: float = 8000.0           # total time budget (ms)
    time_decay_gamma: float = 0.6            # exponential decay factor per action
    min_step_budget_ms: float = 300.0        # minimum per-action budget (ms)
    max_actions_per_turn: int = 10           # max actions in one turn sequence

    # === Expansion strategy ===
    expansion_order: ExpansionOrder = ExpansionOrder.HEURISTIC

    # === Transposition table ===
    transposition_max_size: int = 100_000
    enable_transposition: bool = True

    # === Action pruning ===
    enable_tree_pruning: bool = True
    enable_sim_pruning: bool = True
    enable_obliged_actions: bool = True

    # === Search depth ===
    max_tree_depth: int = 15                 # max tree depth (action count)

    # === Opponent modelling ===
    opponent_greedy_prob: float = 0.8        # probability opponent picks greedy action
    opponent_max_depth: int = 1              # how deep to simulate opponent turns

    # === Cross-turn simulation ===
    max_turns_ahead: int = 3              # max full turns to search ahead in tree
    cross_turn_rollout_depth: int = 2     # greedy rollout turns beyond tree depth
    cross_turn_budget_ratio: float = 0.30  # fraction of budget for beyond-current-turn
    cross_turn_node_budget: int = 3000     # max nodes for cross-turn portion of tree
    opponent_tree_actions: int = 3         # max opponent actions to consider per turn

    # === Debug ===
    debug_mode: bool = False
    log_interval: int = 100                  # log every N iterations


@dataclass
class MCTSStats:
    """Statistics from a completed MCTS search."""
    iterations: int = 0
    nodes_created: int = 0
    evaluations_done: int = 0
    time_used_ms: float = 0.0
    world_count: int = 0
    transposition_hits: int = 0
    actions_explored: int = 0
    pruning_rate: float = 0.0
    chance_node_samples: int = 0


_PLAYSTYLE_UCT = {
    "aggro": -0.15,
    "control": 0.15,
    "combo": 0.10,
    "midrange": 0.0,
    "unknown": 0.0,
}


def get_phase_overrides(turn_number: int, opp_playstyle: str = "unknown") -> dict:
    """Return parameter overrides based on game phase + opponent playstyle.

    uct_constant is tuned per-phase then adjusted by opponent playstyle:
      - aggro: lower exploration (we need exploitation to survive)
      - control: higher exploration (search deeper for win condition)
      - combo: moderate-high exploration
      - midrange: neutral
    """
    from analysis.models.phase import detect_phase, Phase
    phase = detect_phase(turn_number)
    style_delta = _PLAYSTYLE_UCT.get(opp_playstyle, 0.0)

    if phase == Phase.EARLY:
        base = {
            "uct_constant": 0.4,
            "num_worlds": 5,
            "time_budget_ms": 15000,
            "max_turns_ahead": 3,
        }
    elif phase == Phase.MID:
        base = {
            "uct_constant": 0.5,
            "num_worlds": 7,
            "time_budget_ms": 15000,
            "max_turns_ahead": 3,
        }
    else:  # LATE
        base = {
            "uct_constant": 0.7,
            "num_worlds": 9,
            "time_budget_ms": 15000,
            "max_turns_ahead": 3,
        }

    base["uct_constant"] = round(max(0.2, min(1.2, base["uct_constant"] + style_delta)), 2)
    return base

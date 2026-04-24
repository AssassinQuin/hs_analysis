#!/usr/bin/env python3
"""simulation.py — Leaf evaluation strategies for MCTS.

Three modes:
- EVAL_CUTOFF: evaluate_delta directly (fastest, recommended for Python)
- HYBRID: short rollout (1-2 steps) + eval cutoff
- RANDOM: full random rollout (baseline comparison)
"""

from __future__ import annotations

import math
import random
import logging
from typing import Optional, TYPE_CHECKING

from analysis.search.mcts.config import MCTSConfig, SimulationMode

if TYPE_CHECKING:
    from analysis.search.game_state import GameState
    from analysis.search.mcts.node import MCTSNode

log = logging.getLogger(__name__)


def evaluate_leaf(
    leaf_state: 'GameState',
    root_state: 'GameState',
    config: MCTSConfig,
) -> float:
    """Evaluate a leaf node and return reward in [-1, 1].

    Terminal states return ±1.0 directly.
    Non-terminal states use evaluate_delta normalised via tanh.
    """
    # Terminal check
    terminal = _get_terminal_reward(leaf_state)
    if terminal is not None:
        return terminal

    if config.simulation_mode == SimulationMode.EVAL_CUTOFF:
        return _eval_cutoff(leaf_state, root_state, config)
    elif config.simulation_mode == SimulationMode.HYBRID:
        return _eval_hybrid(leaf_state, root_state, config)
    else:
        return _eval_random_rollout(leaf_state, config)


def normalize_score(raw_score: float, scale: float = 15.0) -> float:
    """Normalise evaluate_delta output to [-1, 1] via tanh."""
    return math.tanh(raw_score / scale)


def _get_terminal_reward(state: 'GameState') -> Optional[float]:
    """Check for terminal state and return reward. None = not terminal."""
    my_hp = state.hero.hp
    opp_hp = state.opponent.hero.hp

    if opp_hp <= 0:
        return 1.0   # opponent dead → we win
    if my_hp <= 0:
        return -1.0  # we dead → opponent wins
    return None


def _eval_cutoff(
    leaf_state: 'GameState',
    root_state: 'GameState',
    config: MCTSConfig,
) -> float:
    """Evaluation cutoff: directly evaluate the leaf state."""
    from analysis.evaluators.composite import evaluate_delta
    raw = evaluate_delta(root_state, leaf_state)
    return normalize_score(raw, config.eval_normalization_scale)


def _eval_hybrid(
    leaf_state: 'GameState',
    root_state: 'GameState',
    config: MCTSConfig,
) -> float:
    """Hybrid: short random rollout (1-2 steps) + eval cutoff."""
    from analysis.search.rhea.enumeration import enumerate_legal_actions
    from analysis.search.rhea.simulation import apply_action

    current = leaf_state
    for _ in range(config.rollout_depth):
        actions = enumerate_legal_actions(current)
        if not actions:
            break

        # Filter to reasonable actions for rollout
        filtered = _filter_rollout_actions(actions, current)
        if not filtered:
            filtered = actions

        action = random.choice(filtered)
        current = apply_action(current, action)

        # Check terminal
        terminal = _get_terminal_reward(current)
        if terminal is not None:
            return terminal

    return _eval_cutoff(current, root_state, config)


def _eval_random_rollout(
    state: 'GameState',
    config: MCTSConfig,
    max_depth: int = 3,
) -> float:
    """Full random rollout (baseline)."""
    from analysis.search.rhea.enumeration import enumerate_legal_actions
    from analysis.search.rhea.simulation import apply_action

    current = state
    for _ in range(max_depth):
        terminal = _get_terminal_reward(current)
        if terminal is not None:
            return terminal

        actions = enumerate_legal_actions(current)
        if not actions:
            break

        action = random.choice(actions)
        current = apply_action(current, action)

    terminal = _get_terminal_reward(current)
    if terminal is not None:
        return terminal

    from analysis.evaluators.composite import evaluate
    raw = evaluate(current)
    return normalize_score(raw, config.eval_normalization_scale)


def _filter_rollout_actions(actions: list, state: 'GameState') -> list:
    """Quick filter for rollout: remove obviously bad actions."""
    from analysis.search.rhea.actions import ActionType

    filtered = []
    for action in actions:
        if action.action_type == ActionType.PLAY_WITH_TARGET:
            # Skip self-damage spells targeting own hero
            if action.target_index == 0:
                continue
        filtered.append(action)
    return filtered

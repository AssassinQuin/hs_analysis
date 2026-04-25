#!/usr/bin/env python3
"""simulation.py — Leaf evaluation for MCTS via random rollout.

Every non-terminal leaf is evaluated by random playout:
  1. Pick a legal action (weighted: card plays > attacks > hero power > end turn)
  2. Apply it
  3. Repeat until terminal or max_depth reached
  4. Return reward in [-1, 1]

Terminal states (hero or opponent dead) return ±1.0 directly.
"""

from __future__ import annotations

import math
import random
import logging
from typing import Optional, TYPE_CHECKING

from analysis.search.mcts.config import MCTSConfig

if TYPE_CHECKING:
    from analysis.search.game_state import GameState
    from analysis.search.mcts.node import MCTSNode

log = logging.getLogger(__name__)

# Rollout action weights — higher = more likely to be picked during simulation.
# Card plays and location activations are strong tempo actions; END_TURN is
# a last resort when nothing else is affordable or useful.
_ROLLOUT_WEIGHTS = {
    "PLAY": 5,
    "PLAY_WITH_TARGET": 5,
    "ACTIVATE_LOCATION": 4,
    "ATTACK": 3,
    "HERO_POWER": 2,
    "DISCOVER_PICK": 4,
    "CHOOSE_ONE": 4,
    "HERO_REPLACE": 1,
    "TRANSFORM": 2,
    "END_TURN": 1,
}


def evaluate_leaf(
    leaf_state: 'GameState',
    root_state: 'GameState',
    config: MCTSConfig,
    turn_depth: int = 0,
) -> float:
    """Evaluate a leaf node by random rollout.  Returns reward in [-1, 1].

    Terminal states return +/-1.0 directly.
    Non-terminal states are evaluated by random playout up to max_depth,
    then normalised via tanh(evaluate / scale).
    """
    terminal = _get_terminal_reward(leaf_state)
    if terminal is not None:
        return terminal

    return _eval_random_rollout(leaf_state, config, max_depth=config.rollout_depth)


def normalize_score(raw_score: float, scale: float = 15.0) -> float:
    """Normalise evaluate_delta output to [-1, 1] via tanh."""
    return math.tanh(raw_score / scale)


def _get_terminal_reward(state: 'GameState') -> Optional[float]:
    """Check for terminal state and return reward. None = not terminal."""
    if state.opponent.hero.hp <= 0:
        return 1.0
    if state.hero.hp <= 0:
        return -1.0
    return None


def _weighted_choice(actions: list) -> 'Action':
    """Pick a random action weighted by type priority.

    Card plays and location activations get 4-5x weight vs END_TURN (1x).
    This prevents rollouts from prematurely ending turns.
    """
    if len(actions) == 1:
        return actions[0]

    weights = [_ROLLOUT_WEIGHTS.get(a.action_type.name, 1) for a in actions]

    # Fast path: if there are non-END_TURN actions, exclude END_TURN entirely
    # unless it's the only option. This forces the rollout to actually play cards.
    non_end = [(a, w) for a, w in zip(actions, weights) if a.action_type.name != "END_TURN"]
    if non_end:
        actions, weights = zip(*non_end)
        actions, weights = list(actions), list(weights)

    total = sum(weights)
    if total <= 0:
        return random.choice(actions)

    r = random.random() * total
    cumulative = 0
    for action, w in zip(actions, weights):
        cumulative += w
        if r <= cumulative:
            return action
    return actions[-1]


def _eval_random_rollout(
    state: 'GameState',
    config: MCTSConfig,
    max_depth: int = 10,
) -> float:
    """Rollout: play out the current turn until mana exhausted or no useful actions.

    Skips END_TURN — the rollout simulates spending all available resources,
    then evaluates the resulting board state. This matches the Hearthstone
    principle: play all affordable cards unless saving for a better turn.
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.enumeration import enumerate_legal_actions
    from analysis.search.abilities.simulation import apply_action

    current = state
    for _ in range(max_depth):
        terminal = _get_terminal_reward(current)
        if terminal is not None:
            return terminal

        actions = enumerate_legal_actions(current)
        if not actions:
            break

        # Filter out END_TURN — we want to play out the full turn
        useful = [a for a in actions if a.action_type != ActionType.END_TURN]
        if not useful:
            break  # only END_TURN left = turn naturally exhausted

        action = _weighted_choice(useful)
        current = apply_action(current, action)

    terminal = _get_terminal_reward(current)
    if terminal is not None:
        return terminal

    from analysis.evaluators.composite import evaluate
    raw = evaluate(current)
    return normalize_score(raw, config.eval_normalization_scale)

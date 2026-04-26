#!/usr/bin/env python3
"""interfaces.py — Abstract neural network interfaces for Hearthstone AI.

Provides:
- PolicyNet: abstract policy network (state → action probabilities)
- ValueNet: abstract value network (state → win probability)
- RandomPolicyNet: fallback uniform random policy
- HeuristicValueNet: fallback heuristic board evaluation
- ModelRegistry: singleton for managing model instances

No numpy/torch/sklearn dependencies — pure Python with lists and math.
"""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract interfaces
# ---------------------------------------------------------------------------

class PolicyNet(ABC):
    """Abstract policy network interface.

    Takes encoded state + action space and returns an action probability
    distribution.  Concrete implementations will be provided later
    (PyTorch, ONNX, etc.).
    """

    @abstractmethod
    def predict(
        self,
        state_vector: list[float],
        action_mask: list[float],
        action_features: list[list[float]],
    ) -> list[float]:
        """Return action probabilities for each *legal* action slot.

        Args:
            state_vector: Encoded game state (294 dims from StateEncoder).
            action_mask: Binary mask — 1.0 for legal actions, 0.0 otherwise.
                Length equals the total action candidate count; only entries
                with mask == 1.0 receive non-zero probability.
            action_features: Per-action feature vectors.  Length must match
                *action_mask*.  Each inner list is a fixed-size feature
                representation of the corresponding action.

        Returns:
            A list of probabilities (one per legal action, i.e. one per
            ``action_mask[i] == 1.0``).  Sum should be approximately 1.0.
        """

    @abstractmethod
    def load(self, path: str) -> None:
        """Load model weights from *path*.

        Raises:
            FileNotFoundError: If *path* does not exist.
            RuntimeError: If the file is not a valid model checkpoint.
        """

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Whether model weights have been loaded successfully."""


class ValueNet(ABC):
    """Abstract value network interface.

    Takes an encoded state and returns a scalar win-probability estimate.
    """

    @abstractmethod
    def predict(self, state_vector: list[float]) -> float:
        """Return estimated win probability.

        Args:
            state_vector: Encoded game state (294 dims from StateEncoder).

        Returns:
            A float in [-1, 1] where 1.0 means certain win and -1.0 means
            certain loss.
        """

    @abstractmethod
    def load(self, path: str) -> None:
        """Load model weights from *path*.

        Raises:
            FileNotFoundError: If *path* does not exist.
            RuntimeError: If the file is not a valid model checkpoint.
        """

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """Whether model weights have been loaded successfully."""


# ---------------------------------------------------------------------------
# Fallback implementations
# ---------------------------------------------------------------------------

class RandomPolicyNet(PolicyNet):
    """Fallback: uniform random policy when no model is loaded.

    Returns equal probability for every legal action (based on
    *action_mask*).  This is the zero-information baseline.
    """

    def predict(
        self,
        state_vector: list[float],
        action_mask: list[float],
        action_features: list[list[float]],
    ) -> list[float]:
        """Return uniform probabilities over legal actions.

        The returned list contains exactly one entry per ``action_mask[i]``
        that equals 1.0.  Each entry is ``1 / num_legal``.
        """
        legal_count = sum(1 for m in action_mask if m > 0.5)
        if legal_count == 0:
            return []
        prob = 1.0 / legal_count
        return [prob] * legal_count

    def load(self, path: str) -> None:
        """No-op — random policy has no weights to load."""
        log.debug("RandomPolicyNet.load(%s) is a no-op", path)

    @property
    def is_loaded(self) -> bool:
        return False


class HeuristicValueNet(ValueNet):
    """Fallback: heuristic board evaluation when no model is loaded.

    Uses a simple hand-crafted heuristic based on board state features
    extracted from the raw state vector.  The state vector is expected to
    contain (among other things) friendly/enemy hero HP, total friendly
    board stats, and total enemy board stats.
    """

    # Expected indices in the 294-dim state vector.
    # These are conventions established by StateEncoder; the heuristic
    # will degrade gracefully if indices are out of range by clamping.
    _FRIENDLY_HERO_HP_IDX: int = 0
    _ENEMY_HERO_HP_IDX: int = 1
    _FRIENDLY_TOTAL_ATTACK_IDX: int = 2
    _FRIENDLY_TOTAL_HEALTH_IDX: int = 3
    _ENEMY_TOTAL_ATTACK_IDX: int = 4
    _ENEMY_TOTAL_HEALTH_IDX: int = 5

    def predict(self, state_vector: list[float]) -> float:
        """Return a heuristic win probability in [-1, 1].

        The heuristic combines:
        1. HP differential (friendly - enemy), scaled by 30.
        2. Board stats differential (friendly total stats - enemy total stats).

        The result is clamped to [-1, 1].
        """
        n = len(state_vector)

        def _safe(idx: int) -> float:
            return state_vector[idx] if 0 <= idx < n else 0.0

        friendly_hp = _safe(self._FRIENDLY_HERO_HP_IDX)
        enemy_hp = _safe(self._ENEMY_HERO_HP_IDX)
        friendly_atk = _safe(self._FRIENDLY_TOTAL_ATTACK_IDX)
        friendly_hp_board = _safe(self._FRIENDLY_TOTAL_HEALTH_IDX)
        enemy_atk = _safe(self._ENEMY_TOTAL_ATTACK_IDX)
        enemy_hp_board = _safe(self._ENEMY_TOTAL_HEALTH_IDX)

        # HP differential scaled to roughly [-1, 1]
        hp_diff = (friendly_hp - enemy_hp) / 30.0

        # Board stats differential — a difference of ~20 stats maps to ~1.0
        friendly_stats = friendly_atk + friendly_hp_board
        enemy_stats = enemy_atk + enemy_hp_board
        board_diff = (friendly_stats - enemy_stats) / 20.0

        # Weighted combination
        value = 0.6 * hp_diff + 0.4 * board_diff

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, value))

    def load(self, path: str) -> None:
        """No-op — heuristic value has no weights to load."""
        log.debug("HeuristicValueNet.load(%s) is a no-op", path)

    @property
    def is_loaded(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# Model registry (singleton)
# ---------------------------------------------------------------------------

class ModelRegistry:
    """Singleton registry for managing neural model instances.

    Provides global access to policy and value networks with fallback
    defaults when no models are registered.  Thread-safe within a single
    interpreter (GIL protects simple attribute access).

    Usage::

        reg = ModelRegistry.get()
        reg.load_policy("models/policy_v1.pt")
        policy = reg.policy  # Returns loaded model or RandomPolicyNet
    """

    _instance: Optional[ModelRegistry] = None

    def __init__(self) -> None:
        self._policy_net: Optional[PolicyNet] = None
        self._value_net: Optional[ValueNet] = None

    # -- Singleton ----------------------------------------------------------

    @classmethod
    def get(cls) -> ModelRegistry:
        """Return the global ModelRegistry singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -- Accessors ----------------------------------------------------------

    @property
    def policy(self) -> PolicyNet:
        """Return the registered policy net, or ``RandomPolicyNet`` fallback."""
        return self._policy_net if self._policy_net is not None else RandomPolicyNet()

    @property
    def value(self) -> ValueNet:
        """Return the registered value net, or ``HeuristicValueNet`` fallback."""
        return self._value_net if self._value_net is not None else HeuristicValueNet()

    # -- Registration -------------------------------------------------------

    def register_policy(self, net: PolicyNet) -> None:
        """Register a policy network instance.

        Args:
            net: A concrete :class:`PolicyNet` implementation.
        """
        self._policy_net = net
        log.info("PolicyNet registered: %s", type(net).__name__)

    def register_value(self, net: ValueNet) -> None:
        """Register a value network instance.

        Args:
            net: A concrete :class:`ValueNet` implementation.
        """
        self._value_net = net
        log.info("ValueNet registered: %s", type(net).__name__)

    # -- Load helpers -------------------------------------------------------

    def load_policy(self, path: str) -> None:
        """Load a policy network from *path*.

        If the load fails (file not found, corrupt checkpoint, etc.), the
        registry keeps whatever model was previously registered (or none).
        A warning is logged on failure.

        Args:
            path: Filesystem path to a model checkpoint.
        """
        try:
            net = RandomPolicyNet()  # placeholder; real impl will create proper class
            net.load(path)
            self.register_policy(net)
        except Exception:
            log.warning(
                "Failed to load policy model from %s — keeping current model",
                path,
                exc_info=True,
            )

    def load_value(self, path: str) -> None:
        """Load a value network from *path*.

        If the load fails, the registry keeps whatever model was previously
        registered (or none).

        Args:
            path: Filesystem path to a model checkpoint.
        """
        try:
            net = HeuristicValueNet()  # placeholder; real impl will create proper class
            net.load(path)
            self.register_value(net)
        except Exception:
            log.warning(
                "Failed to load value model from %s — keeping current model",
                path,
                exc_info=True,
            )

    # -- Queries ------------------------------------------------------------

    def has_models(self) -> bool:
        """Return ``True`` if *both* policy and value nets are loaded.

        Returns ``False`` if either (or both) are still using the fallback.
        """
        return (
            self._policy_net is not None
            and self._policy_net.is_loaded
            and self._value_net is not None
            and self._value_net.is_loaded
        )

    # -- Reset --------------------------------------------------------------

    def reset(self) -> None:
        """Clear all registered models, reverting to fallback defaults."""
        self._policy_net = None
        self._value_net = None
        log.info("ModelRegistry reset — using fallback defaults")

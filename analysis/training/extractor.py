"""extractor.py — TrainingDataExtractor: extract ML training samples from game replays.

Transforms sequences of GameState snapshots and Actions into TrainingSample
objects with encoded feature vectors and reward signals.  No neural network
models are required — only heuristic reward computation.

Typical usage::

    extractor = TrainingDataExtractor()
    samples = extractor.extract_from_replay(game_states, actions, "win")
    extractor.to_jsonl(samples, "training_data/game_123.jsonl")
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from analysis.training.encoder import ActionEncoder, StateEncoder

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────


@dataclass
class TrainingSample:
    """Single training sample for supervised / RL training.

    Attributes:
        state_vector: Encoded GameState as a fixed-length float vector.
        action_vector: Encoded Action as a fixed-length float vector.
        reward: Outcome signal (typically in [-1, 1]).
        meta: Arbitrary metadata (game_id, turn, card_id, etc.).
    """

    state_vector: List[float]
    action_vector: List[float]
    reward: float
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "state_vector": self.state_vector,
            "action_vector": self.action_vector,
            "reward": self.reward,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingSample":
        """Deserialise from a plain dict."""
        return cls(
            state_vector=data["state_vector"],
            action_vector=data["action_vector"],
            reward=data["reward"],
            meta=data.get("meta", {}),
        )


# ──────────────────────────────────────────────────────────────
# TrainingDataExtractor
# ──────────────────────────────────────────────────────────────


class TrainingDataExtractor:
    """Extract training samples from parsed Power.log games.

    Uses :class:`StateEncoder` and :class:`ActionEncoder` to produce
    feature vectors, and computes reward signals via a heuristic board
    evaluation function.
    """

    def __init__(self) -> None:
        """Initialise with default encoders."""
        self.state_encoder = StateEncoder()
        self.action_encoder = ActionEncoder()

    # ──────────────────────────────────────────────────────────
    # Main extraction
    # ──────────────────────────────────────────────────────────

    def extract_from_replay(
        self,
        game_states: List[Any],
        actions: List[Any],
        outcome: str,
    ) -> List[TrainingSample]:
        """Extract samples from a single game replay.

        Args:
            game_states: List of GameState snapshots (one per turn or action).
                Each element is expected to have the same fields as GameState.
            actions: List of ``(turn_number, Action)`` tuples or Action objects
                with a ``step_order`` / ``meta`` attribute for turn mapping.
            outcome: ``"win"`` or ``"loss"`` (case-insensitive).

        Returns:
            A list of :class:`TrainingSample` instances.
        """
        if not game_states or not actions:
            return []

        outcome_val = 1.0 if outcome.lower() == "win" else -1.0
        samples: List[TrainingSample] = []

        # Build turn-indexed lookup: turn_number → GameState
        state_by_turn: Dict[int, Any] = {}
        for state in game_states:
            turn = getattr(state, "turn_number", 0)
            state_by_turn[turn] = state

        # Sort states by turn for sequential pairing
        sorted_turns = sorted(state_by_turn.keys())

        for action_entry in actions:
            # Support both (turn, action) tuples and bare action objects
            if isinstance(action_entry, tuple) and len(action_entry) == 2:
                turn_number, action = action_entry
            else:
                action = action_entry
                turn_number = getattr(action, "step_order", 0)

            # Find the state for this turn
            state = state_by_turn.get(turn_number)
            if state is None:
                # Fallback: use the nearest available state
                state = self._nearest_state(state_by_turn, turn_number, sorted_turns)

            if state is None:
                continue

            # Find next state for delta computation
            next_state = self._next_state(state_by_turn, turn_number, sorted_turns)

            # Encode
            try:
                state_vec = self.state_encoder.encode(state)
            except Exception as e:
                log.warning("Failed to encode state at turn %d: %s", turn_number, e)
                continue

            try:
                action_vec = self.action_encoder.encode(action)
            except Exception as e:
                log.warning("Failed to encode action at turn %d: %s", turn_number, e)
                continue

            # Compute reward
            if next_state is not None:
                reward = self.extract_action_reward(state, action, next_state, outcome_val)
            else:
                # Last action: use outcome only with slight decay
                total_turns = max(sorted_turns[-1], 1) if sorted_turns else 1
                discount = 0.9 ** (total_turns - turn_number)
                reward = 0.3 * outcome_val * discount

            # Build metadata
            meta = {
                "turn": turn_number,
                "action_type": getattr(
                    getattr(action, "action_type", None), "name",
                    str(getattr(action, "action_type", "UNKNOWN"))
                ),
                "outcome": outcome.lower(),
            }
            # Extract card_id if available
            card_index = getattr(action, "card_index", -1)
            if card_index >= 0 and hasattr(state, "hand"):
                hand = state.hand if state.hand else []
                if card_index < len(hand):
                    card = hand[card_index]
                    meta["card_id"] = getattr(card, "card_id", "")
                    meta["card_name"] = getattr(card, "name", "")

            samples.append(TrainingSample(
                state_vector=state_vec,
                action_vector=action_vec,
                reward=reward,
                meta=meta,
            ))

        return samples

    # ──────────────────────────────────────────────────────────
    # Reward computation
    # ──────────────────────────────────────────────────────────

    def extract_action_reward(
        self,
        state_before: Any,
        action: Any,
        state_after: Any,
        final_outcome: float,
    ) -> float:
        """Compute reward for a single action.

        Uses immediate delta + discounted final outcome::

            reward = 0.7 * immediate_delta + 0.3 * final_outcome * discount

        where ``immediate_delta = board_value(after) - board_value(before)``.

        Args:
            state_before: GameState before the action.
            action: The Action taken (used for turn-based discount).
            state_after: GameState after the action.
            final_outcome: +1.0 for win, -1.0 for loss.

        Returns:
            A float reward value.
        """
        # Immediate board delta (normalised to ~[-1, 1])
        bv_before = self._board_value(state_before)
        bv_after = self._board_value(state_after)
        immediate_delta = bv_after - bv_before

        # Clamp immediate delta
        immediate_delta = max(-1.0, min(1.0, immediate_delta * 0.1))

        # Discount based on turn number
        turn = getattr(state_before, "turn_number", 1)
        discount = 0.95 ** max(turn - 1, 0)

        reward = 0.7 * immediate_delta + 0.3 * final_outcome * discount
        return max(-1.0, min(1.0, reward))

    def _board_value(self, state: Any) -> float:
        """Heuristic board state value for reward computation.

        Considers:
            - Hero HP + armor advantage
            - Total friendly board stats (attack + health)
            - Total enemy board stats (penalty)
            - Board control (number of minions)
            - Hand size advantage

        Returns:
            A float representing board value (higher is better for the player).
        """
        value = 0.0

        # Hero advantage
        hero = getattr(state, "hero", None)
        opponent = getattr(state, "opponent", None)
        if hero is not None:
            value += (getattr(hero, "hp", 0) + getattr(hero, "armor", 0)) * 0.5
        if opponent is not None:
            opp_hero = getattr(opponent, "hero", None)
            if opp_hero is not None:
                value -= (getattr(opp_hero, "hp", 0) + getattr(opp_hero, "armor", 0)) * 0.3

        # Friendly board stats
        board = getattr(state, "board", []) or []
        for minion in board:
            value += getattr(minion, "attack", 0) * 0.3
            value += getattr(minion, "health", 0) * 0.2
            if getattr(minion, "has_taunt", False):
                value += 0.5
            if getattr(minion, "has_divine_shield", False):
                value += 0.3

        # Enemy board stats (penalty)
        if opponent is not None:
            enemy_board = getattr(opponent, "board", []) or []
            for minion in enemy_board:
                value -= getattr(minion, "attack", 0) * 0.3
                value -= getattr(minion, "health", 0) * 0.2
                if getattr(minion, "has_taunt", False):
                    value -= 0.5

        # Hand size advantage
        hand = getattr(state, "hand", []) or []
        value += len(hand) * 0.2
        if opponent is not None:
            opp_hand = getattr(opponent, "hand_count", 0) or 0
            value -= opp_hand * 0.1

        return value

    # ──────────────────────────────────────────────────────────
    # State lookup helpers
    # ──────────────────────────────────────────────────────────

    @staticmethod
    def _nearest_state(
        state_by_turn: Dict[int, Any],
        turn: int,
        sorted_turns: List[int],
    ) -> Optional[Any]:
        """Find the closest available state to the given turn."""
        if not sorted_turns:
            return None
        # Binary search for nearest turn
        lo, hi = 0, len(sorted_turns) - 1
        best_idx = 0
        best_diff = abs(sorted_turns[0] - turn)
        for i in range(len(sorted_turns)):
            diff = abs(sorted_turns[i] - turn)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        return state_by_turn.get(sorted_turns[best_idx])

    @staticmethod
    def _next_state(
        state_by_turn: Dict[int, Any],
        turn: int,
        sorted_turns: List[int],
    ) -> Optional[Any]:
        """Find the state for the turn immediately after *turn*."""
        for t in sorted_turns:
            if t > turn:
                return state_by_turn.get(t)
        return None

    # ──────────────────────────────────────────────────────────
    # Serialisation
    # ──────────────────────────────────────────────────────────

    def to_jsonl(self, samples: List[TrainingSample], output_path: str) -> None:
        """Write samples to a JSONL file for training.

        Each line is a JSON object with keys:
        ``state_vector``, ``action_vector``, ``reward``, ``meta``.

        Args:
            samples: List of TrainingSample instances.
            output_path: File path for the output JSONL file.
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for sample in samples:
                f.write(json.dumps(sample.to_dict(), ensure_ascii=False) + "\n")

        log.info("Wrote %d samples to %s", len(samples), output_path)

    @staticmethod
    def from_jsonl(path: str) -> List[TrainingSample]:
        """Load samples from a JSONL file.

        Args:
            path: File path to a JSONL file produced by :meth:`to_jsonl`.

        Returns:
            A list of :class:`TrainingSample` instances.
        """
        samples: List[TrainingSample] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    samples.append(TrainingSample.from_dict(data))
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning("Skipping malformed line %d in %s: %s", line_num, path, e)

        log.info("Loaded %d samples from %s", len(samples), path)
        return samples

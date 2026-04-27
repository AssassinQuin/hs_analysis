"""encoder.py — StateEncoder and ActionEncoder for converting game data to feature vectors.

StateEncoder: GameState → 294-dim float vector
ActionEncoder: Action → 13-dim float vector

All features are normalised to approximately [0, 1] range using divisors
that reflect typical Hearthstone maximums.  Empty slots are encoded as
all-zeros.
"""

from __future__ import annotations

from typing import Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState, Minion
    from analysis.card.abilities.definition import Action

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────


def _safe_get(obj: Any, attr: str, default: Any = 0) -> Any:
    """Safely get an attribute, returning *default* on AttributeError."""
    return getattr(obj, attr, default)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, val))


def _normalise(val: float, divisor: float) -> float:
    """Normalise *val* by *divisor*, clamped to [0, 1]."""
    if divisor <= 0:
        return 0.0
    return _clamp(val / divisor)


# ──────────────────────────────────────────────────────────────
# StateEncoder
# ──────────────────────────────────────────────────────────────

# Dimension constants
_MINION_FEATURES = 15
_CARD_FEATURES = 7
_MAX_BOARD_SLOTS = 7
_MAX_HAND_SLOTS = 10
_HERO_FEATURES = 8
_GLOBAL_FEATURES = 6

# Derived dimensions
FRIENDLY_BOARD_DIMS = _MAX_BOARD_SLOTS * _MINION_FEATURES  # 105
ENEMY_BOARD_DIMS = _MAX_BOARD_SLOTS * _MINION_FEATURES    # 105
HAND_DIMS = _MAX_HAND_SLOTS * _CARD_FEATURES               # 70
STATE_DIMS = (
    _HERO_FEATURES
    + FRIENDLY_BOARD_DIMS
    + ENEMY_BOARD_DIMS
    + HAND_DIMS
    + _GLOBAL_FEATURES
)  # 294


class StateEncoder:
    """Encode a :class:`GameState` into a fixed-length 294-dim feature vector.

    Vector layout:
        - Hero features:    8 dims  (offset 0)
        - Friendly board: 105 dims  (offset 8)
        - Enemy board:    105 dims  (offset 113)
        - Hand:            70 dims  (offset 218)
        - Global:           6 dims  (offset 288)
        - Total:         294 dims
    """

    def __init__(self) -> None:
        """Initialise the encoder (no configuration needed)."""
        pass

    def encode(self, state: Any) -> List[float]:
        """Encode a GameState into a 294-dimensional feature vector.

        Args:
            state: A GameState instance (duck-typed; missing fields default to 0).

        Returns:
            A list of 294 floats.
        """
        vec: List[float] = []

        # ── Hero features (8 dims) ──
        vec.extend(self._encode_hero(state))

        # ── Friendly board (7 × 15 = 105 dims) ──
        friendly_board = _safe_get(state, "board", [])
        vec.extend(self._encode_board(friendly_board))

        # ── Enemy board (7 × 15 = 105 dims) ──
        opponent = _safe_get(state, "opponent", None)
        enemy_board = _safe_get(opponent, "board", []) if opponent else []
        vec.extend(self._encode_board(enemy_board))

        # ── Hand (10 × 7 = 70 dims) ──
        hand = _safe_get(state, "hand", [])
        vec.extend(self._encode_hand(hand))

        # ── Global features (6 dims) ──
        vec.extend(self._encode_global(state))

        assert len(vec) == STATE_DIMS, f"Expected {STATE_DIMS}, got {len(vec)}"
        return vec

    def _encode_hero(self, state: Any) -> List[float]:
        """Encode hero state into 8 features.

        Features (normalised):
            0. hp / 30
            1. armor / 30
            2. weapon_attack / 10
            3. weapon_durability / 10
            4. mana_available / 10
            5. mana_overloaded / 10
            6. hero_power_used (0/1)
            7. imbue_level / 10
        """
        hero = _safe_get(state, "hero", None)
        if hero is None:
            return [0.0] * _HERO_FEATURES

        weapon = _safe_get(hero, "weapon", None)
        weapon_attack = _safe_get(weapon, "attack", 0) if weapon else 0
        weapon_durability = _safe_get(weapon, "health", 0) if weapon else 0

        mana = _safe_get(state, "mana", None)
        mana_available = _safe_get(mana, "available", 0) if mana else 0
        mana_overloaded = _safe_get(mana, "overloaded", 0) if mana else 0

        return [
            _normalise(_safe_get(hero, "hp", 0), 30.0),
            _normalise(_safe_get(hero, "armor", 0), 30.0),
            _normalise(weapon_attack, 10.0),
            _normalise(weapon_durability, 10.0),
            _normalise(mana_available, 10.0),
            _normalise(mana_overloaded, 10.0),
            float(bool(_safe_get(hero, "hero_power_used", False))),
            _normalise(_safe_get(hero, "imbue_level", 0), 10.0),
        ]

    def _encode_board(self, board: list) -> List[float]:
        """Encode a list of minions into 105 features (7 slots × 15 per minion).

        Minions beyond slot 7 are silently dropped.  Empty slots are
        encoded as all-zeros.
        """
        vec: List[float] = []
        for i in range(_MAX_BOARD_SLOTS):
            if i < len(board):
                vec.extend(self._encode_minion(board[i]))
            else:
                vec.extend(self._empty_minion())
        return vec

    def _encode_minion(self, minion: Any) -> List[float]:
        """Encode a single Minion into 15 normalised features.

        Features:
            0. attack / 10
            1. health / 10
            2. cost / 10
            3. can_attack (0/1)
            4. has_taunt (0/1)
            5. has_divine_shield (0/1)
            6. has_stealth (0/1)
            7. has_rush (0/1)
            8. has_windfury (0/1)
            9. has_reborn (0/1)
           10. has_poisonous (0/1)
           11. has_lifesteal (0/1)
           12. is_dormant (0/1)
           13. frozen (0/1)
           14. spell_power / 5
        """
        return [
            _normalise(_safe_get(minion, "attack", 0), 10.0),
            _normalise(_safe_get(minion, "health", 0), 10.0),
            _normalise(_safe_get(minion, "cost", 0), 10.0),
            float(bool(_safe_get(minion, "can_attack", False))),
            float(bool(_safe_get(minion, "has_taunt", False))),
            float(bool(_safe_get(minion, "has_divine_shield", False))),
            float(bool(_safe_get(minion, "has_stealth", False))),
            float(bool(_safe_get(minion, "has_rush", False))),
            float(bool(_safe_get(minion, "has_windfury", False))),
            float(bool(_safe_get(minion, "has_reborn", False))),
            float(bool(_safe_get(minion, "has_poisonous", False))),
            float(bool(_safe_get(minion, "has_lifesteal", False))),
            float(bool(_safe_get(minion, "is_dormant", False))),
            float(bool(_safe_get(minion, "frozen_until_next_turn", False))),
            _normalise(_safe_get(minion, "spell_power", 0), 5.0),
        ]

    def _empty_minion(self) -> List[float]:
        """Return a 15-dim zero vector (empty board slot)."""
        return [0.0] * _MINION_FEATURES

    def _encode_hand(self, hand: list) -> List[float]:
        """Encode the hand (up to 10 cards) into 70 features (10 × 7 per card).

        Cards beyond slot 10 are silently dropped.
        """
        vec: List[float] = []
        for i in range(_MAX_HAND_SLOTS):
            if i < len(hand):
                vec.extend(self._encode_card(hand[i]))
            else:
                vec.extend(self._empty_card())
        return vec

    def _encode_card(self, card: Any) -> List[float]:
        """Encode a single Card into 7 normalised features.

        Features:
            0. cost / 10
            1. is_minion (0/1)
            2. is_spell (0/1)
            3. is_weapon (0/1)
            4. attack / 10
            5. health / 10
            6. has_battlecry (0/1)
        """
        card_type = str(_safe_get(card, "card_type", "") or "").upper()
        mechanics = _safe_get(card, "mechanics", []) or []
        return [
            _normalise(_safe_get(card, "cost", 0), 10.0),
            float(card_type == "MINION"),
            float(card_type == "SPELL"),
            float(card_type == "WEAPON"),
            _normalise(_safe_get(card, "attack", 0), 10.0),
            _normalise(_safe_get(card, "health", 0), 10.0),
            float("BATTLECRY" in mechanics),
        ]

    def _empty_card(self) -> List[float]:
        """Return a 7-dim zero vector (empty hand slot)."""
        return [0.0] * _CARD_FEATURES

    def _encode_global(self, state: Any) -> List[float]:
        """Encode global game features into 6 dimensions.

        Features:
            0. deck_remaining / 30
            1. opponent_hand_count / 10
            2. opponent_secret_count / 5
            3. turn_number / 30
            4. fatigue_damage / 10
            5. corpses / 10
        """
        opponent = _safe_get(state, "opponent", None)
        return [
            _normalise(_safe_get(state, "deck_remaining", 0), 30.0),
            _normalise(
                _safe_get(opponent, "hand_count", 0) if opponent else 0, 10.0
            ),
            _normalise(
                len(_safe_get(opponent, "secrets", []) or []) if opponent else 0,
                5.0,
            ),
            _normalise(_safe_get(state, "turn_number", 0), 30.0),
            _normalise(_safe_get(state, "fatigue_damage", 0), 10.0),
            _normalise(_safe_get(state, "corpses", 0), 10.0),
        ]


# ──────────────────────────────────────────────────────────────
# ActionEncoder
# ──────────────────────────────────────────────────────────────

#: All valid action type names (order defines one-hot index).
ACTION_TYPES: List[str] = [
    "PLAY",
    "PLAY_WITH_TARGET",
    "ATTACK",
    "HERO_POWER",
    "ACTIVATE_LOCATION",
    "HERO_REPLACE",
    "DISCOVER_PICK",
    "CHOOSE_ONE",
    "TRANSFORM",
    "END_TURN",
]

_NUM_ACTION_TYPES = len(ACTION_TYPES)  # 10
ACTION_DIMS = _NUM_ACTION_TYPES + 3    # 10 one-hot + card_idx + src_idx + tgt_idx = 13


class ActionEncoder:
    """Encode an :class:`Action` into a fixed-length 13-dim feature vector.

    Vector layout:
        - action_type one-hot: 10 dims  (offset 0)
        - card_index / 10:     1 dim   (offset 10)
        - source_index / 8:    1 dim   (offset 11)
        - target_index / 8:    1 dim   (offset 12)
        - Total:              13 dims
    """

    def __init__(self) -> None:
        """Initialise the encoder (no configuration needed)."""
        pass

    def encode(self, action: Any) -> List[float]:
        """Encode a single Action into a 13-dimensional feature vector.

        Args:
            action: An Action instance.  If ``action.action_type`` is an enum,
                    its ``.name`` is used; otherwise the string value is used.

        Returns:
            A list of 13 floats.
        """
        vec: List[float] = []

        # ── Action type one-hot (10 dims) ──
        action_type = _safe_get(action, "action_type", None)
        type_name = getattr(action_type, "name", str(action_type)) if action_type is not None else "END_TURN"
        one_hot = [0.0] * _NUM_ACTION_TYPES
        for i, name in enumerate(ACTION_TYPES):
            if name == type_name:
                one_hot[i] = 1.0
                break
        vec.extend(one_hot)

        # ── Normalised indices (3 dims) ──
        card_index = _safe_get(action, "card_index", -1)
        source_index = _safe_get(action, "source_index", -1)
        target_index = _safe_get(action, "target_index", -1)

        # Normalise: treat -1 as 0 (no target)
        vec.append(_normalise(max(card_index, 0), 10.0))
        vec.append(_normalise(max(source_index, 0), 8.0))
        vec.append(_normalise(max(target_index, 0), 8.0))

        assert len(vec) == ACTION_DIMS, f"Expected {ACTION_DIMS}, got {len(vec)}"
        return vec

    def encode_batch(self, actions: list) -> List[List[float]]:
        """Encode a list of actions into a list of 13-dim vectors.

        Args:
            actions: A list of Action instances.

        Returns:
            A list of lists, each inner list having 13 floats.
        """
        return [self.encode(a) for a in actions]

"""ability_tags.py — Feature encoding for card ability tags.

Encodes ability tag strings (e.g. "DAMAGE:ALL_ENEMY:3") into fixed-length
52-dimensional vectors using hash-based one-hot encoding for categorical
dimensions and binned encoding for numeric values.

Dimension layout (52 total):
    - EffectKind one-hot:  24 dims (one per EffectKind)
    - TargetKind one-hot:  14 dims (one per TargetKind)
    - Numeric bins:        11 dims (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10+)
    - Reserved/padding:     3 dims (for future use)
"""

from __future__ import annotations

import hashlib
from typing import List, Optional

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

#: Dimensionality of each ability tag vector.
ABILITY_TAG_DIM = 52

#: All TargetKind enum member names (order defines one-hot index).
TARGET_KINDS: List[str] = [
    "SINGLE_MINION",
    "RANDOM",
    "FRIENDLY_HERO",
    "FRIENDLY_MINION",
    "RANDOM_ENEMY",
    "ALL_MINIONS",
    "ENEMY",
    "ALL_ENEMY",
    "ALL_FRIENDLY",
    "DAMAGED",
    "UNDAMAGED",
    "SELF",
    "ALL",
    "NONE",
]

#: All EffectKind enum member names (order defines one-hot index).
EFFECT_KINDS: List[str] = [
    "DAMAGE",
    "SUMMON",
    "DRAW",
    "GAIN",
    "GIVE",
    "DESTROY",
    "COPY",
    "HEAL",
    "SHUFFLE",
    "REDUCE_COST",
    "TRANSFORM",
    "RETURN",
    "TAKE_CONTROL",
    "DISCARD",
    "SWAP",
    "WEAPON_EQUIP",
    "DISCOVER",
    "FREEZE",
    "SILENCE",
    "CAST_SPELL",
    "ENCHANT",
    "BUFF",
    "ARMOR",
    "RANDOM_DAMAGE",
    "AOE_DAMAGE",
    "MANA",
    "HERALD_SUMMON",
    "IMBUE_UPGRADE",
    "COMBO_DISCOUNT",
    "OUTCAST_DRAW",
    "OUTCAST_BUFF",
    "OUTCAST_COST",
    "COLOSSAL_SUMMON",
    "KINDRED_BUFF",
    "CORRUPT_UPGRADE",
    "CORPSE_EFFECT",
    "NONE",
]

# Numeric value bins: 0..9 and "10+"
_NUM_BINS = 11
# Dimension offsets within the 52-dim vector
_EFFECT_OFFSET = 0
_EFFECT_DIMS = len(EFFECT_KINDS)  # 38
_TARGET_OFFSET = _EFFECT_OFFSET + _EFFECT_DIMS  # 38
_TARGET_DIMS = len(TARGET_KINDS)  # 14
_NUM_OFFSET = _TARGET_OFFSET + _TARGET_DIMS  # 52 — exceeds 52

# Recompute: EFFECT_KINDS has 38 entries, TARGET_KINDS has 14 → 52 total.
# No room for numeric bins within 52 if we keep all enums.
# Adjust: reduce EFFECT_KINDS to the 24 most common to fit 24+14+11+3=52.
# We keep only the primary 24 EffectKind entries:
_PRIMARY_EFFECT_KINDS: List[str] = [
    "DAMAGE", "SUMMON", "DRAW", "GAIN", "GIVE", "DESTROY", "COPY", "HEAL",
    "SHUFFLE", "REDUCE_COST", "TRANSFORM", "RETURN", "TAKE_CONTROL", "DISCARD",
    "SWAP", "WEAPON_EQUIP", "DISCOVER", "FREEZE", "SILENCE", "CAST_SPELL",
    "ENCHANT", "BUFF", "ARMOR", "NONE",
]
_PRIMARY_EFFECT_DIMS = len(_PRIMARY_EFFECT_KINDS)  # 24
_PRIMARY_EFFECT_OFFSET = 0
_TARGET_OFFSET_V2 = _PRIMARY_EFFECT_OFFSET + _PRIMARY_EFFECT_DIMS  # 24
_TARGET_DIMS_V2 = len(TARGET_KINDS)  # 14
_NUM_OFFSET_V2 = _TARGET_OFFSET_V2 + _TARGET_DIMS_V2  # 38
_RESERVED_OFFSET = _NUM_OFFSET_V2 + _NUM_BINS  # 49
_RESERVED_DIMS = ABILITY_TAG_DIM - _RESERVED_OFFSET  # 3


def _hash_mod(value: str, n: int) -> int:
    """Deterministic hash-based modulo for string → integer binning."""
    if not value:
        return 0
    h = hashlib.md5(value.encode("utf-8")).hexdigest()
    return int(h, 16) % n


def _bin_numeric(value: int) -> int:
    """Map a numeric value to one of 11 bins (0..9, 10+)."""
    if value < 0:
        return 0
    if value >= 10:
        return 10
    return value


def encode_ability_tag(tag_string: str) -> List[float]:
    """Encode an ability tag string into a 52-dimensional feature vector.

    Tag format: ``"EFFECT_KIND:TARGET_KIND:numeric_value"``
    Example: ``"DAMAGE:ALL_ENEMY:3"``

    The vector layout:
        - dims 0–23:  EffectKind one-hot (24 dims)
        - dims 24–37: TargetKind one-hot (14 dims)
        - dims 38–48: Numeric value bin one-hot (11 bins: 0–9, 10+)
        - dims 49–51: Reserved / padding (3 dims)

    Args:
        tag_string: Ability tag in ``"EFFECT:TARGET:VALUE"`` format.

    Returns:
        A list of 52 floats in [0.0, 1.0].
    """
    vec = [0.0] * ABILITY_TAG_DIM

    if not tag_string:
        return vec

    parts = tag_string.strip().split(":")
    effect_str = parts[0] if len(parts) > 0 else ""
    target_str = parts[1] if len(parts) > 1 else ""
    num_str = parts[2] if len(parts) > 2 else ""

    # --- EffectKind one-hot ---
    effect_idx = _effect_kind_index(effect_str)
    vec[_PRIMARY_EFFECT_OFFSET + effect_idx] = 1.0

    # --- TargetKind one-hot ---
    target_idx = _target_kind_index(target_str)
    vec[_TARGET_OFFSET_V2 + target_idx] = 1.0

    # --- Numeric value bin ---
    try:
        num_val = int(num_str)
    except (ValueError, TypeError):
        # Use hash-based fallback for non-numeric strings
        num_val = _hash_mod(num_str, 11) if num_str else 0
    bin_idx = _bin_numeric(num_val)
    vec[_NUM_OFFSET_V2 + bin_idx] = 1.0

    # --- Reserved dims remain 0.0 ---
    return vec


def _effect_kind_index(effect_str: str) -> int:
    """Get the one-hot index for an EffectKind name.

    Falls back to hash-based index if the name is not recognized.
    """
    upper = effect_str.upper()
    for i, name in enumerate(_PRIMARY_EFFECT_KINDS):
        if name == upper:
            return i
    # Hash-based fallback for unknown effects
    return _hash_mod(effect_str, _PRIMARY_EFFECT_DIMS)


def _target_kind_index(target_str: str) -> int:
    """Get the one-hot index for a TargetKind name.

    Falls back to hash-based index if the name is not recognized.
    """
    upper = target_str.upper()
    for i, name in enumerate(TARGET_KINDS):
        if name == upper:
            return i
    # Hash-based fallback for unknown targets
    return _hash_mod(target_str, _TARGET_DIMS_V2)


def pool_ability_tags(tags: List[str], max_tags: int = 4) -> List[float]:
    """Mean-pool multiple ability tag vectors into a single vector.

    Encodes each tag individually and averages the resulting vectors.
    If fewer than *max_tags* are provided, the remaining are treated as
    zero vectors (effectively down-weighting non-empty tags).

    Args:
        tags: List of ability tag strings.
        max_tags: Maximum number of tags to pool (default 4).

    Returns:
        A list of ``ABILITY_TAG_DIM`` floats.
    """
    if not tags:
        return [0.0] * ABILITY_TAG_DIM

    # Truncate or pad to max_tags
    padded = list(tags[:max_tags])
    while len(padded) < max_tags:
        padded.append("")

    # Encode and mean-pool
    encoded = [encode_ability_tag(t) for t in padded]
    dim = ABILITY_TAG_DIM
    return [
        sum(encoded[i][j] for i in range(len(encoded))) / len(encoded)
        for j in range(dim)
    ]


def effect_to_tag(effect: dict) -> Optional[str]:
    """Convert a JSON effect dict to a tag string.

    Accepts dicts with keys like:
        - ``"effect_kind"`` / ``"type"``: the EffectKind name
        - ``"target_kind"`` / ``"target"``: the TargetKind name
        - ``"value"`` / ``"amount"``: numeric value (int)

    Args:
        effect: A dictionary describing the effect.

    Returns:
        A tag string like ``"DAMAGE:ALL_ENEMY:3"``, or ``None`` if the
        dict is empty or missing required fields.
    """
    if not effect:
        return None

    # Extract effect kind
    ek = effect.get("effect_kind") or effect.get("type", "")
    if not ek:
        return None

    # Extract target kind
    tk = effect.get("target_kind") or effect.get("target", "NONE")

    # Extract numeric value
    val = effect.get("value") or effect.get("amount", 0)
    try:
        val = int(val)
    except (ValueError, TypeError):
        val = 0

    return f"{ek}:{tk}:{val}"

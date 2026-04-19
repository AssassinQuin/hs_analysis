"""V10 mechanic base value formulas.

Provides computed base values for special mechanics
that cannot be derived from raw stats alone.
"""

from __future__ import annotations
import math
from typing import Any


def _imbue(params: dict[str, Any]) -> float:
    """Imbue: summon k 1/1s. Value = sum(base_hp * 0.8^(k-1)).
    params: base_hp (float, default 1.0), k (int, default 1)
    """
    base_hp = params.get("base_hp", 1.0)
    k = params.get("k", 1)
    return sum(base_hp * (0.8 ** (i - 1)) for i in range(1, k + 1))


def _herald(params: dict[str, Any]) -> float:
    """Herald: value scales with count of soldiers.
    params: soldier_value (float, default 1.0), count (int, default 0)
    """
    soldier_value = params.get("soldier_value", 1.0)
    count = params.get("count", 0)
    return soldier_value * (1 + 0.5 * math.floor(count / 2))


def _shatter(params: dict[str, Any]) -> float:
    """Shatter: double half-damage with bonus.
    params: half (float, default 0.0)
    """
    half = params.get("half", 0.0)
    return (half * 2) * 1.3


def _kindred(params: dict[str, Any]) -> float:
    """Kindred: base * match probability.
    params: base (float, default 0.0), match_prob (float, default 0.0)
    """
    base = params.get("base", 0.0)
    match_prob = params.get("match_prob", 0.0)
    return base * match_prob


def _rewind(params: dict[str, Any]) -> float:
    """Rewind: take max of two options.
    params: a (float, default 0.0), b (float, default 0.0)
    """
    a = params.get("a", 0.0)
    b = params.get("b", 0.0)
    return max(a, b)


def _dark_gift(params: dict[str, Any]) -> float:
    """Dark Gift: average of gift values.
    params: gift_values (list[float], default [])
    """
    gift_values = params.get("gift_values", [])
    if not gift_values:
        return 0.0
    return sum(gift_values) / len(gift_values)


def _colossal(params: dict[str, Any]) -> float:
    """Colossal: body + appendages, penalized by board space.
    params: body (float, default 0.0), append (float, default 0.0),
            n (int, default 0), space_penalty (float, default 1.0)
    """
    body = params.get("body", 0.0)
    append = params.get("append", 0.0)
    n = params.get("n", 0)
    space_penalty = params.get("space_penalty", 1.0)
    return (body + n * append) * space_penalty


def _dormant(params: dict[str, Any]) -> float:
    """Dormant: awakened value * survival probability.
    params: awakened (float, default 0.0), survival_prob (float, default 1.0)
    """
    awakened = params.get("awakened", 0.0)
    survival_prob = params.get("survival_prob", 1.0)
    return awakened * survival_prob


def _quest(params: dict[str, Any]) -> float:
    """Quest: reward * completion probability.
    params: reward (float, default 0.0), completion_prob (float, default 0.0)
    """
    reward = params.get("reward", 0.0)
    completion_prob = params.get("completion_prob", 0.0)
    return reward * completion_prob


MECHANIC_FORMULAS: dict[str, callable] = {
    "imbue": _imbue,
    "herald": _herald,
    "shatter": _shatter,
    "kindred": _kindred,
    "rewind": _rewind,
    "dark_gift": _dark_gift,
    "colossal": _colossal,
    "dormant": _dormant,
    "quest": _quest,
}


def get_mechanic_base_value(mechanic: str, params: dict[str, Any] | None = None) -> float:
    """Compute base value for a special mechanic.

    Args:
        mechanic: Name of the mechanic (e.g., 'imbue', 'herald').
        params: Keyword parameters for the formula.

    Returns:
        Computed base value, or 0.0 if mechanic is unknown.
    """
    if params is None:
        params = {}
    formula = MECHANIC_FORMULAS.get(mechanic)
    if formula is None:
        return 0.0
    try:
        return float(formula(params))
    except Exception:
        return 0.0

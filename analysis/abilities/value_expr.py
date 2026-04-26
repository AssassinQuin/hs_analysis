"""Declarative value expression system for Hearthstone ability definitions.

Replaces the runtime LazyValue class with a JSON-serializable expression language.
Every expression is either an int literal or a dict with a single operator key.

Operators:
  Literal:    6
  Attribute:  {"$attr": "source.attack"}
  Count:      {"$count": "friendly_minions"}
  Add:        {"$add": [a, b]}
  Multiply:   {"$mul": [a, b]}
  Subtract:   {"$sub": [a, b]}
  Max:        {"$max": [a, b]}
  Min:        {"$min": [a, b]}
  Condition:  {"$if": {"condition": {...}, "then": a, "else": b}}
  Reference:  {"$ref": "fireball_damage"}

Backward compatibility: use to_lazy_value(expr) / from_lazy_value(lv) to convert.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

log = logging.getLogger(__name__)

# ── Global values registry for $ref lookups ──────────────────────────
VALUES_REGISTRY: Dict[str, int] = {}

# ── Count field mapping ──────────────────────────────────────────────
_COUNT_FIELDS = {
    "friendly_minions": lambda st: len(st.board) if st and hasattr(st, "board") else 0,
    "enemy_minions": lambda st: len(st.opponent.board) if st and hasattr(st, "opponent") and hasattr(st.opponent, "board") else 0,
    "hand": lambda st: len(st.hand) if st and hasattr(st, "hand") else 0,
    "secrets": lambda st: len(st.secrets) if st and hasattr(st, "secrets") and st.secrets else 0,
    "damaged_friendly": lambda st: (
        sum(1 for m in st.board if hasattr(m, "health") and hasattr(m, "max_health") and m.health < m.max_health)
        if st and hasattr(st, "board") else 0
    ),
    "deck": lambda st: getattr(st, "deck_remaining", 0) if st else 0,
}


# ── resolve ──────────────────────────────────────────────────────────

def resolve(
    expr: Union[int, dict, list],
    state: Any = None,
    source: Any = None,
    target: Any = None,
) -> int:
    """Resolve a JSON value expression to an integer.

    Args:
        expr: JSON-compatible expression (int, dict, or nested structure).
        state: Game state object (board, hand, hero, etc.).
        source: Source entity (card/minion triggering the effect).
        target: Target entity of the effect.
    """
    if isinstance(expr, int):
        return expr

    if isinstance(expr, float):
        return int(expr)

    if not isinstance(expr, dict):
        log.warning("value_expr: unsupported expression type %r, returning 0", type(expr))
        return 0

    if len(expr) != 1:
        log.warning("value_expr: dict must have exactly one key, got %d keys, returning 0", len(expr))
        return 0

    op, val = next(iter(expr.items()))

    if op == "$attr":
        return _resolve_attr(val, state, source, target)

    if op == "$count":
        return _resolve_count(val, state)

    if op == "$add":
        a, b = val
        return _resolve_binary(a, b, lambda x, y: x + y, state, source, target)

    if op == "$mul":
        a, b = val
        return _resolve_binary(a, b, lambda x, y: x * y, state, source, target)

    if op == "$sub":
        a, b = val
        return _resolve_binary(a, b, lambda x, y: x - y, state, source, target)

    if op == "$max":
        a, b = val
        return _resolve_binary(a, b, lambda x, y: max(x, y), state, source, target)

    if op == "$min":
        a, b = val
        return _resolve_binary(a, b, lambda x, y: min(x, y), state, source, target)

    if op == "$if":
        return _resolve_if(val, state, source, target)

    if op == "$ref":
        if val not in VALUES_REGISTRY:
            log.warning("value_expr: $ref '%s' not found in VALUES_REGISTRY", val)
            return 0
        return VALUES_REGISTRY[val]

    log.warning("value_expr: unknown operator %r, returning 0", op)
    return 0


def _resolve_binary(
    a: Any,
    b: Any,
    fn,
    state: Any = None,
    source: Any = None,
    target: Any = None,
) -> int:
    return fn(resolve(a, state, source, target), resolve(b, state, source, target))


def _resolve_attr(path: str, state: Any, source: Any, target: Any) -> int:
    """Resolve a dot-path attribute like 'source.attack' or 'hero.armor'."""
    parts = path.split(".", 1)
    root, attr = parts[0], parts[1] if len(parts) > 1 else None

    if root == "source":
        obj = source
    elif root == "target":
        obj = target
    else:
        # Treat as state attribute (e.g., "hero.armor" → state.hero.armor)
        obj = getattr(state, root, None) if state else None

    if obj is None:
        log.warning("value_expr: $attr '%s' — root %r is None, returning 0", path, root)
        return 0

    if attr:
        val = getattr(obj, attr, None)
    else:
        val = obj

    try:
        return int(val or 0)
    except (TypeError, ValueError):
        return 0


def _resolve_count(field: str, state: Any) -> int:
    """Resolve a $count field name to an integer count."""
    fn = _COUNT_FIELDS.get(field)
    if fn is None:
        # Fallback: try as a direct state attribute that's a collection
        collection = getattr(state, field, []) if state else []
        log.warning("value_expr: $count '%s' not recognized, falling back to len", field)
        return len(collection) if collection else 0
    return fn(state)


def _resolve_if(if_dict: dict, state: Any, source: Any, target: Any) -> int:
    """Resolve a conditional expression."""
    cond = if_dict.get("condition", {})
    then_expr = if_dict.get("then", 0)
    else_expr = if_dict.get("else", 0)

    if resolve_condition(cond, state, source):
        return resolve(then_expr, state, source, target)
    return resolve(else_expr, state, source, target)


# ── resolve_condition ────────────────────────────────────────────────

def resolve_condition(cond_dict: dict, state: Any = None, source: Any = None) -> bool:
    """Evaluate a condition dict to a boolean.

    Supported kinds:
        HOLDING_RACE, HAS_KEYWORD, HEALTH_THRESHOLD, BOARD_STATE,
        HAND_POSITION, RACE_MATCH
    """
    kind = cond_dict.get("kind", "")
    params = cond_dict.get("params", {})

    if kind == "HOLDING_RACE":
        race = params.get("race", "")
        if not state or not hasattr(state, "hand"):
            return False
        return any(getattr(c, "race", None) == race for c in state.hand) if race else False

    if kind == "HAS_KEYWORD":
        keyword = params.get("keyword", "")
        if not source:
            return False
        return bool(getattr(source, keyword, False))

    if kind == "HEALTH_THRESHOLD":
        threshold = params.get("threshold", 0)
        if not state or not hasattr(state, "hero"):
            return False
        return getattr(state.hero, "health", 0) >= threshold

    if kind == "BOARD_STATE":
        min_minions = params.get("min_minions", 0)
        if not state or not hasattr(state, "board"):
            return False
        return len(state.board) >= min_minions

    if kind == "HAND_POSITION":
        position = params.get("position", 0)
        if not state or not hasattr(state, "hand") or not source:
            return False
        try:
            idx = state.hand.index(source)
            return idx == position
        except (ValueError, AttributeError):
            return False

    if kind == "RACE_MATCH":
        race = params.get("race", "")
        if not source:
            return False
        return getattr(source, "race", None) == race

    # Unknown condition kind — default to True
    log.warning("value_expr: unknown condition kind %r, defaulting to True", kind)
    return True


# ── Serialization helpers ────────────────────────────────────────────

def serialize(expr: Union[int, dict]) -> Union[int, dict]:
    """Serialize an expression for JSON output (identity + validation)."""
    if isinstance(expr, int):
        return expr
    if isinstance(expr, dict) and len(expr) == 1:
        op = next(iter(expr))
        if not op.startswith("$"):
            raise ValueError(f"Invalid expression operator: {op!r} (must start with $)")
        return expr
    raise ValueError(f"Invalid expression: {expr!r}")


def deserialize(data: Union[int, dict]) -> Union[int, dict]:
    """Deserialize JSON data back to an expression (identity + validation)."""
    return serialize(data)


# ── LazyValue conversion ─────────────────────────────────────────────

def from_lazy_value(lv: Any) -> Union[int, dict]:
    """Convert a LazyValue to a JSON expression."""
    from analysis.abilities.definition import LazyValue

    if not isinstance(lv, LazyValue):
        raise TypeError(f"Expected LazyValue, got {type(lv).__name__}")

    # Literal only
    if lv._literal is not None and lv._op is None:
        return lv._literal

    # Build the base expression
    if lv._literal is not None:
        base: Union[int, dict] = lv._literal
    elif lv._source_attr:
        base = {"$attr": f"source.{lv._source_attr}"}
    elif lv._count_field:
        base = {"$count": lv._count_field}
    else:
        base = 0

    # Wrap with arithmetic
    if lv._op and lv._operand is not None:
        op_map = {"+": "$add", "-": "$sub", "*": "$mul", "//": "$mul"}
        op_key = op_map.get(lv._op)
        if op_key is None:
            log.warning("value_expr: unhandled LazyValue op %r", lv._op)
            return base
        operand_expr = (
            from_lazy_value(lv._operand)
            if isinstance(lv._operand, LazyValue)
            else lv._operand
        )
        return {op_key: [base, operand_expr]}

    return base


def to_lazy_value(expr: Union[int, dict]) -> Any:
    """Convert a JSON expression back to a LazyValue for backward compatibility."""
    from analysis.abilities.definition import LazyValue as LV

    if isinstance(expr, int):
        return LV(expr)

    if not isinstance(expr, dict):
        return LV()

    if "$attr" in expr:
        path = expr["$attr"]
        parts = path.split(".", 1)
        if len(parts) == 2 and parts[0] == "source":
            return LV.attr(parts[1])
        # For non-source attrs, wrap in literal 0 (can't fully represent)
        log.warning("value_expr: to_lazy_value only supports source.* attrs, got %s", path)
        return LV()

    if "$count" in expr:
        return LV.count(expr["$count"])

    if "$ref" in expr:
        val = VALUES_REGISTRY.get(expr["$ref"], 0)
        return LV(val)

    if "$add" in expr:
        a, b = expr["$add"]
        return to_lazy_value(a) + to_lazy_value(b)

    if "$mul" in expr:
        a, b = expr["$mul"]
        return to_lazy_value(a) * to_lazy_value(b)

    if "$sub" in expr:
        a, b = expr["$sub"]
        return to_lazy_value(a) + (-resolve(b))  # Approximate: a - b

    # Fallback
    return LV()

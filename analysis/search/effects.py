#!/usr/bin/env python3
"""effects.py — Unified effect dispatch for Hearthstone AI.

Replaces the 3× duplicated string-parsing effect dispatch in:
  - deathrattle.py  (_apply_deathrattle_effect)
  - trigger_system.py (_execute_effect)
  - location.py (_resolve_location_effect)

Architecture:
  - EffectKind enum: canonical effect types
  - EffectSpec: structured, parsed effect descriptor
  - Global registry: @register(EffectKind.DAMAGE) decorator
  - dispatch() / dispatch_batch(): single point of execution
  - parse_effect(): converts legacy "action:target:value" strings → EffectSpec
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion

logger = logging.getLogger(__name__)

__all__ = [
    "EffectKind",
    "EffectSpec",
    "register",
    "dispatch",
    "dispatch_batch",
    "parse_effect",
]


# ═══════════════════════════════════════════════════════════════════
# EffectKind — canonical effect type enum
# ═══════════════════════════════════════════════════════════════════


class EffectKind(Enum):
    """Canonical types of effects in the game engine."""
    DAMAGE = auto()
    HEAL = auto()
    SUMMON = auto()
    DRAW = auto()
    BUFF = auto()
    ARMOR = auto()
    DESTROY = auto()
    RANDOM_DAMAGE = auto()
    AOE_DAMAGE = auto()
    DISCARD = auto()
    MANA = auto()
    COPY = auto()
    TRANSFORM = auto()
    ENCHANT = auto()


# ═══════════════════════════════════════════════════════════════════
# EffectSpec — structured effect descriptor
# ═══════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class EffectSpec:
    """A parsed, structured effect — replaces raw colon-delimited strings.

    Example mappings from legacy strings:
        "damage:random_enemy:3"  → EffectSpec(RANDOM_DAMAGE, value=3, target_filter="random_enemy")
        "summon:2:3"             → EffectSpec(SUMMON, value=2, value2=3)
        "draw:2"                 → EffectSpec(DRAW, value=2)
        "buff:friendly:1:2"     → EffectSpec(BUFF, value=1, value2=2, target_filter="friendly")
        "armor:5"               → EffectSpec(ARMOR, value=5)
        "heal:hero:3"           → EffectSpec(HEAL, value=3, target_filter="hero")
    """
    kind: EffectKind
    value: int = 0
    value2: int = 0
    target_filter: str = ""  # 'self', 'enemy', 'random_enemy', 'all_enemy', 'hero', 'friendly', etc.
    card_id: int = 0  # for summon/copy/transform with specific cards


# ═══════════════════════════════════════════════════════════════════
# Registry — global handler dispatch
# ═══════════════════════════════════════════════════════════════════

EffectHandler = Callable[..., Any]
_REGISTRY: Dict[EffectKind, EffectHandler] = {}


def register(kind: EffectKind):
    """Decorator to register a handler function for an EffectKind."""
    def decorator(fn: EffectHandler) -> EffectHandler:
        _REGISTRY[kind] = fn
        return fn
    return decorator


def dispatch(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Execute a single EffectSpec against game state.

    Returns the (possibly modified) state.  Unknown kinds are no-ops.
    """
    handler = _REGISTRY.get(spec.kind)
    if handler is None:
        logger.debug("No handler registered for effect kind: %s", spec.kind)
        return state
    try:
        return handler(state, spec, source, **ctx)
    except Exception as exc:
        logger.warning("Effect dispatch failed for %s: %s", spec, exc)
        return state


def dispatch_batch(state: "GameState", specs: List[EffectSpec], source: Any = None, **ctx) -> "GameState":
    """Execute a sequence of EffectSpecs in order."""
    for spec in specs:
        state = dispatch(state, spec, source, **ctx)
    return state


# ═══════════════════════════════════════════════════════════════════
# Legacy string parser  →  EffectSpec
# ═══════════════════════════════════════════════════════════════════
# Format: "action:target:value[:value2]"
#   e.g. "damage:random_enemy:3", "summon:2:3", "draw:2", etc.

def parse_effect(text: str) -> Optional[EffectSpec]:
    """Parse a legacy colon-delimited effect string into an EffectSpec.

    Returns None for unparseable / empty strings.
    """
    text = text.strip()
    if not text:
        return None

    parts = text.split(":")
    if not parts:
        return None

    action = parts[0].lower()

    if action == "damage" and len(parts) >= 3:
        target = parts[1].lower()
        try:
            amount = int(parts[2])
        except ValueError:
            return None
        if target == "random_enemy":
            return EffectSpec(kind=EffectKind.RANDOM_DAMAGE, value=amount, target_filter="random_enemy")
        elif target == "all_enemy" or target == "all_enemies":
            return EffectSpec(kind=EffectKind.AOE_DAMAGE, value=amount, target_filter="all_enemy")
        elif target == "enemy_hero":
            return EffectSpec(kind=EffectKind.DAMAGE, value=amount, target_filter="enemy_hero")
        elif target == "enemy":
            return EffectSpec(kind=EffectKind.DAMAGE, value=amount, target_filter="enemy")
        else:
            return EffectSpec(kind=EffectKind.DAMAGE, value=amount, target_filter=target)

    elif action == "summon" and len(parts) >= 3:
        try:
            atk = int(parts[1])
            hp = int(parts[2])
        except ValueError:
            return None
        return EffectSpec(kind=EffectKind.SUMMON, value=atk, value2=hp)

    elif action == "draw" and len(parts) >= 2:
        try:
            count = int(parts[1])
        except ValueError:
            return None
        return EffectSpec(kind=EffectKind.DRAW, value=count)

    elif action == "buff" and len(parts) >= 4:
        target = parts[1].lower()
        try:
            atk_delta = int(parts[2])
            hp_delta = int(parts[3])
        except ValueError:
            return None
        return EffectSpec(kind=EffectKind.BUFF, value=atk_delta, value2=hp_delta, target_filter=target)

    elif action == "armor" and len(parts) >= 2:
        try:
            amount = int(parts[1])
        except ValueError:
            return None
        return EffectSpec(kind=EffectKind.ARMOR, value=amount)

    elif action == "heal" and len(parts) >= 3:
        target = parts[1].lower()
        try:
            amount = int(parts[2])
        except ValueError:
            return None
        return EffectSpec(kind=EffectKind.HEAL, value=amount, target_filter=target)

    elif action == "destroy" and len(parts) >= 2:
        target = parts[1].lower()
        return EffectSpec(kind=EffectKind.DESTROY, target_filter=target)

    # Unknown action
    logger.debug("Unknown effect action: %s (raw: %s)", action, text)
    return None


def parse_effects(texts: List[str]) -> List[EffectSpec]:
    """Parse multiple effect strings, skipping None results."""
    results = []
    for t in texts:
        spec = parse_effect(t)
        if spec is not None:
            results.append(spec)
    return results


# ═══════════════════════════════════════════════════════════════════
# Effect handlers — one per EffectKind
# ═══════════════════════════════════════════════════════════════════


@register(EffectKind.RANDOM_DAMAGE)
def _handle_random_damage(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Deal *value* damage to a random enemy minion."""
    import random as _random

    if not state.opponent.board:
        return state

    target = _random.choice(state.opponent.board)
    if target.has_divine_shield:
        target.has_divine_shield = False
    else:
        target.health -= spec.value
    return state


@register(EffectKind.DAMAGE)
def _handle_damage(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Deal *value* damage to a target determined by target_filter."""
    tf = spec.target_filter

    if tf == "enemy_hero":
        state.opponent.hero.hp -= spec.value
    elif tf == "enemy":
        # Single enemy minion (first or targeted) — currently delegate to random
        if state.opponent.board:
            import random as _random
            target = _random.choice(state.opponent.board)
            if target.has_divine_shield:
                target.has_divine_shield = False
            else:
                target.health -= spec.value
    elif tf == "self_hero":
        state.hero.hp -= spec.value
    else:
        # Generic damage — try enemy hero as fallback
        state.opponent.hero.hp -= spec.value
    return state


@register(EffectKind.AOE_DAMAGE)
def _handle_aoe_damage(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Deal *value* damage to all enemy minions."""
    for m in state.opponent.board:
        if m.has_divine_shield:
            m.has_divine_shield = False
        else:
            m.health -= spec.value
    return state


@register(EffectKind.SUMMON)
def _handle_summon(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Summon a token with attack=value, health=value2."""
    from analysis.search.game_state import Minion

    board_type = ctx.get("board_type", "friendly")
    position = ctx.get("position", -1)

    if board_type == "friendly":
        alive_count = sum(1 for m in state.board if m.health > 0)
        if alive_count >= 7:
            return state
        token = Minion(
            name=f"Token({spec.value}/{spec.value2})",
            attack=spec.value,
            health=spec.value2,
            max_health=spec.value2,
            owner="friendly",
        )
        if 0 <= position < len(state.board):
            state.board.insert(position, token)
        else:
            state.board.append(token)
    return state


@register(EffectKind.DRAW)
def _handle_draw(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Draw *value* cards from deck."""
    from analysis.search.rhea_engine import apply_draw
    return apply_draw(state, spec.value)


@register(EffectKind.BUFF)
def _handle_buff(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Give +value/+value2 buff to minions determined by target_filter."""
    tf = spec.target_filter
    if tf in ("friendly", ""):
        for m in state.board:
            m.attack = max(0, m.attack + spec.value)
            m.health = max(0, m.health + spec.value2)
            m.max_health = max(1, m.max_health + spec.value2)
    return state


@register(EffectKind.ARMOR)
def _handle_armor(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Gain *value* armor."""
    state.hero.armor += spec.value
    return state


@register(EffectKind.HEAL)
def _handle_heal(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Heal *value* HP to target determined by target_filter."""
    tf = spec.target_filter
    if tf == "hero":
        state.hero.hp = min(30, state.hero.hp + spec.value)
    elif tf == "friendly" and state.board:
        target = state.board[0]
        target.health = min(target.max_health, target.health + spec.value)
    return state


@register(EffectKind.DESTROY)
def _handle_destroy(state: "GameState", spec: EffectSpec, source: Any = None, **ctx) -> "GameState":
    """Destroy a target minion."""
    tf = spec.target_filter
    if tf in ("enemy", "random_enemy") and state.opponent.board:
        import random as _random
        target = _random.choice(state.opponent.board)
        target.health = 0
    elif tf == "friendly" and state.board:
        target = state.board[0]
        target.health = 0
    return state

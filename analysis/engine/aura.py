"""engine/aura.py — Aura (continuous buff) engine.

Maintains a registry of aura definitions and recomputes aura effects on game state.
Extensible via register_aura() instead of hardcoded-only registry.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set

from analysis.engine.enchantment import Enchantment, apply_enchantment, remove_enchantment
from analysis.engine.state import GameState, Minion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Aura definition schema
# ---------------------------------------------------------------------------

AuraDef = dict  # {target_filter, attack_delta, health_delta, max_health_delta, cost_delta}

# ---------------------------------------------------------------------------
# Aura registry — hardcoded classic auras + extensible via register_aura()
# ---------------------------------------------------------------------------

AURA_REGISTRY: Dict[str, AuraDef] = {
    # Raid Leader — 掠夺者
    "Raid Leader": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
    },
    "掠夺者": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
    },
    # Stormwind Champion — 暴风城勇士
    "Stormwind Champion": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
        "health_delta": 1,
        "max_health_delta": 1,
    },
    "暴风城勇士": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
        "health_delta": 1,
        "max_health_delta": 1,
    },
    # Flametongue Totem — 火舌图腾
    "Flametongue Totem": {
        "target_filter": "adjacent",
        "attack_delta": 2,
    },
    "火舌图腾": {
        "target_filter": "adjacent",
        "attack_delta": 2,
    },
    # Murloc Warleader — 鱼人领军
    "Murloc Warleader": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 2,
    },
    "鱼人领军": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 2,
    },
    # Grimscale Oracle — 暗鳞先知
    "Grimscale Oracle": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 1,
    },
    "暗鳞先知": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 1,
    },
}

# ---------------------------------------------------------------------------
# Race / type detection — uses Minion.race field when available, falls back
# to name heuristics for legacy data.
# ---------------------------------------------------------------------------

_MURLOC_NAMES: frozenset = frozenset({
    "Murloc Warleader", "Grimscale Oracle", "Murloc Tidecaller",
    "Murloc Tidehunter", "Old Murk-Eye", "Bluegill Warrior",
    "Murloc Scout", "Murloc Tinyfin",
    "鱼人领军", "暗鳞先知", "鱼人招潮者", "鱼人猎潮者",
    "老瞎眼", "蓝鳃战士", "鱼人侦察兵", "鱼人宝宝",
})

_PIRATE_NAMES: frozenset = frozenset({
    "Southsea Captain", "Southsea Deckhand", "Bloodsail Raider",
    "Patches the Pirate", "Sky Captain", "Captain Hook",
    "南海船长", "南海水手", "血帆袭击者", "海盗帕奇斯",
    "天空船长",
})

_RACE_KEYWORD_MAP = {
    "MURLOC": _MURLOC_NAMES,
    "PIRATE": _PIRATE_NAMES,
}


def _is_murloc(minion: Minion) -> bool:
    """Check if minion is a murloc using race field or name heuristic."""
    race = getattr(minion, "race", "").upper()
    if race == "MURLOC":
        return True
    return minion.name in _MURLOC_NAMES


def _is_pirate(minion: Minion) -> bool:
    """Check if minion is a pirate using race field or name heuristic."""
    race = getattr(minion, "race", "").upper()
    if race == "PIRATE":
        return True
    return minion.name in _PIRATE_NAMES


# ---------------------------------------------------------------------------
# Dirty flag for lazy recomputation (kept for API compatibility; no-op)
# ---------------------------------------------------------------------------

_aura_dirty = True


def invalidate_auras(state: GameState) -> None:
    """Mark aura state as dirty — next apply_auras call will recompute.

    Note: apply_auras always recomputes now; this is kept for API compat.
    """
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_aura(card_id: str, aura_def: AuraDef) -> None:
    """Register an aura definition for a card.

    Args:
        card_id: Card name (EN or CN) or card_id string.
        aura_def: Aura definition dict with at least 'target_filter'.
    """
    if not isinstance(aura_def, dict) or "target_filter" not in aura_def:
        raise ValueError(f"aura_def must contain 'target_filter': {aura_def}")
    AURA_REGISTRY[card_id] = aura_def
    logger.debug("Registered aura for %s: %s", card_id, aura_def)


def apply_auras(state: GameState, max_iterations: int = 10) -> GameState:
    """Recompute all active aura buffs on the game state.

    Removes all aura enchantments then re-applies based on current board.
    Mutates state in place and returns it.

    A single remove-then-apply pass is sufficient because aura effects
    don't chain (the target_filter selects final board positions, not
    intermediate stat values).
    """
    _remove_all_auras(state)
    _apply_all_auras(state)
    return state


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def _get_targets(
    source: Minion,
    source_idx: int,
    board: List[Minion],
    target_filter: str,
) -> List[tuple]:
    """Return (index, minion) pairs that match the filter."""
    if target_filter == "other_friendly":
        return [(i, m) for i, m in enumerate(board) if i != source_idx]
    elif target_filter == "adjacent":
        targets = []
        if source_idx - 1 >= 0 and source_idx - 1 < len(board):
            targets.append((source_idx - 1, board[source_idx - 1]))
        if source_idx + 1 < len(board):
            targets.append((source_idx + 1, board[source_idx + 1]))
        return targets
    elif target_filter == "other_friendly_murloc":
        return [
            (i, m) for i, m in enumerate(board)
            if i != source_idx and _is_murloc(m)
        ]
    elif target_filter == "other_friendly_pirate":
        return [
            (i, m) for i, m in enumerate(board)
            if i != source_idx and _is_pirate(m)
        ]
    return []


def _get_hand_targets(
    state: GameState,
    target_filter: str,
    side: str = "friend",
) -> List[tuple]:
    """Return (index, card) pairs from the appropriate hand for cost auras."""
    if target_filter == "friendly_hand":
        return [(i, c) for i, c in enumerate(state.hand) if hasattr(c, "cost")]
    elif target_filter == "opponent_hand":
        return [(i, c) for i, c in enumerate(state.opponent.hand) if hasattr(c, "cost")]
    return []


# ---------------------------------------------------------------------------
# Internal: remove / apply aura enchantments
# ---------------------------------------------------------------------------

def _remove_all_auras(state: GameState) -> None:
    """Remove every aura enchantment from every minion on both boards + hand."""
    for minion in state.board:
        _remove_auras_from_entity(state, minion)
    for minion in state.opponent.board:
        _remove_auras_from_entity(state, minion)
    for card in state.hand:
        if hasattr(card, "enchantments"):
            _remove_auras_from_entity(state, card)
    for card in state.opponent.hand:
        if hasattr(card, "enchantments"):
            _remove_auras_from_entity(state, card)


def _remove_auras_from_entity(state, entity) -> None:
    """Remove aura enchantments from a single entity."""
    aura_ids = [
        e.enchantment_id for e in getattr(entity, "enchantments", [])
        if e.enchantment_id.startswith("aura_")
    ]
    for aid in aura_ids:
        remove_enchantment(state, entity, aid)


def _apply_all_auras(state: GameState) -> bool:
    """Apply auras from all aura sources on both boards. Return True if any applied."""
    any_applied = False

    # Friendly board
    for idx, minion in enumerate(state.board):
        if minion.name in AURA_REGISTRY or getattr(minion, "card_id", "") in AURA_REGISTRY:
            aura_def = AURA_REGISTRY.get(minion.name) or AURA_REGISTRY.get(minion.card_id)
            any_applied |= _apply_aura_to_targets(state, minion, idx, aura_def, side="friend")

    # Opponent board
    for idx, minion in enumerate(state.opponent.board):
        if minion.name in AURA_REGISTRY or getattr(minion, "card_id", "") in AURA_REGISTRY:
            aura_def = AURA_REGISTRY.get(minion.name) or AURA_REGISTRY.get(minion.card_id)
            any_applied |= _apply_aura_to_targets(state, minion, idx, aura_def, side="opp")

    return any_applied


def _apply_aura_to_targets(
    state: GameState,
    source: Minion,
    source_idx: int,
    aura_def: AuraDef,
    side: str = "friend",
) -> bool:
    """Apply a single aura to its targets. Return True if any applied."""
    any_applied = False
    board = state.board if side == "friend" else state.opponent.board

    if aura_def.get("cost_delta", 0) != 0 and aura_def.get("target_filter") in ("friendly_hand", "opponent_hand"):
        targets = _get_hand_targets(state, aura_def["target_filter"], side=side)
        for t_idx, target in targets:
            ench = _make_aura_enchantment(source, source_idx, t_idx, aura_def, side)
            apply_enchantment(target, ench)
            any_applied = True
    else:
        targets = _get_targets(source, source_idx, board, aura_def["target_filter"])
        for t_idx, target in targets:
            ench = _make_aura_enchantment(source, source_idx, t_idx, aura_def, side)
            apply_enchantment(target, ench)
            any_applied = True

    return any_applied


def _make_aura_enchantment(
    source: Minion,
    source_idx: int,
    target_idx: int,
    aura_def: AuraDef,
    side: str = "friend",
) -> Enchantment:
    """Create an Enchantment representing an aura buff."""
    return Enchantment(
        enchantment_id=f"aura_{side}_{source_idx}_{target_idx}",
        name=f"Aura:{source.name}",
        source_dbf_id=source.dbf_id,
        attack_delta=aura_def.get("attack_delta", 0),
        health_delta=aura_def.get("health_delta", 0),
        max_health_delta=aura_def.get("max_health_delta", 0),
        cost_delta=aura_def.get("cost_delta", 0),
    )


# ── Backward-compatible alias ──
recompute_auras = apply_auras

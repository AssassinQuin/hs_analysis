"""
Aura Engine — continuous board-wide buff recomputation.

Handles aura effects from minions like Raid Leader, Stormwind Champion,
Flametongue Totem, Murloc Warleader, etc.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from analysis.search.enchantment import Enchantment, apply_enchantment, remove_enchantment
from analysis.search.game_state import GameState, Minion


# ---------------------------------------------------------------------------
# Aura definitions
# ---------------------------------------------------------------------------

AuraDef = dict  # {target_filter, attack_delta, health_delta, max_health_delta}

AURA_REGISTRY: Dict[str, AuraDef] = {
    # Raid Leader — 雷德·黑手 is actually WRONG; Raid Leader CN = 掠夺者
    # Use both EN and common CN names
    "Raid Leader": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
    },
    "掠夺者": {
        "target_filter": "other_friendly",
        "attack_delta": 1,
    },
    # Stormwind Champion
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
    # Flametongue Totem
    "Flametongue Totem": {
        "target_filter": "adjacent",
        "attack_delta": 2,
    },
    "火舌图腾": {
        "target_filter": "adjacent",
        "attack_delta": 2,
    },
    # Murloc Warleader
    "Murloc Warleader": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 2,
    },
    "鱼人领军": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 2,
    },
    # Grimscale Oracle
    "Grimscale Oracle": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 1,
    },
    "暗鳞先知": {
        "target_filter": "other_friendly_murloc",
        "attack_delta": 1,
    },
    # Southsea Captain
    "Southsea Captain": {
        "target_filter": "other_friendly_pirate",
        "attack_delta": 1,
        "health_delta": 1,
        "max_health_delta": 1,
    },
    "南海船长": {
        "target_filter": "other_friendly_pirate",
        "attack_delta": 1,
        "health_delta": 1,
        "max_health_delta": 1,
    },
}

# ---------------------------------------------------------------------------
# Murloc / Pirate name heuristics
# ---------------------------------------------------------------------------

_MURLOC_NAMES = frozenset({
    "Murloc Warleader", "Grimscale Oracle", "Murloc Tidecaller",
    "Murloc Tidehunter", "Old Murk-Eye", "Bluegill Warrior",
    "Murloc Scout", "Murloc Tinyfin",
    "鱼人领军", "暗鳞先知", "鱼人招潮者", "鱼人猎潮者",
    "老瞎眼", "蓝鳃战士", "鱼人侦察兵", "鱼人宝宝",
})

_PIRATE_NAMES = frozenset({
    "Southsea Captain", "Southsea Deckhand", "Bloodsail Raider",
    "Patches the Pirate", "Sky Captain", "Captain Hook",
    "南海船长", "南海水手", "血帆袭击者", "海盗帕奇斯",
    "天空船长",
})

# Race keywords that might appear in card text
_MURLOC_KEYWORDS = ("Murloc", "鱼人")
_PIRATE_KEYWORDS = ("Pirate", "海盗")


def _is_murloc(minion: Minion) -> bool:
    """Heuristic: is this minion a murloc?"""
    if minion.name in _MURLOC_NAMES:
        return True
    return False


def _is_pirate(minion: Minion) -> bool:
    """Heuristic: is this minion a pirate?"""
    if minion.name in _PIRATE_NAMES:
        return True
    return False


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
    if target_filter == "other_friendly":  # actually means other on same board
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
            (i, m)
            for i, m in enumerate(board)
            if i != source_idx and _is_murloc(m)
        ]
    elif target_filter == "other_friendly_pirate":
        return [
            (i, m)
            for i, m in enumerate(board)
            if i != source_idx and _is_pirate(m)
        ]
    return []


# ---------------------------------------------------------------------------
# Core: recompute_auras
# ---------------------------------------------------------------------------

def recompute_auras(state: GameState, max_iterations: int = 10) -> GameState:
    """
    Remove all aura enchantments then re-apply based on current board.

    Mutates state in place (for search performance) and returns it.
    """
    for _ in range(max_iterations):
        # Phase 1: remove all aura enchantments
        _remove_all_auras(state)

        # Phase 2: reapply based on current board
        applied = _apply_all_auras(state)

        # If no auras were applied (or board didn't change), stop iterating
        if not applied:
            break

    return state


def _remove_all_auras(state: GameState) -> None:
    """Remove every aura enchantment from every minion on both boards."""
    for minion in state.board:
        _remove_auras_from_minion(minion)
    for minion in state.opponent.board:
        _remove_auras_from_minion(minion)


def _remove_auras_from_minion(minion: Minion) -> None:
    """Remove aura enchantments from a single minion."""
    # Collect aura enchantment IDs first (avoid mutating during iteration)
    aura_ids = [
        e.enchantment_id for e in minion.enchantments if e.enchantment_id.startswith("aura_")
    ]
    for aid in aura_ids:
        remove_enchantment(minion, aid)


def _apply_all_auras(state: GameState) -> bool:
    """Apply auras from all aura sources on both boards. Return True if any applied."""
    any_applied = False

    # Friendly board
    for idx, minion in enumerate(state.board):
        if minion.name in AURA_REGISTRY:
            aura_def = AURA_REGISTRY[minion.name]
            targets = _get_targets(minion, idx, state.board, aura_def["target_filter"])
            for t_idx, target in targets:
                ench = _make_aura_enchantment(minion, idx, t_idx, aura_def)
                apply_enchantment(target, ench)
                any_applied = True

    # Opponent board
    for idx, minion in enumerate(state.opponent.board):
        if minion.name in AURA_REGISTRY:
            aura_def = AURA_REGISTRY[minion.name]
            targets = _get_targets(minion, idx, state.opponent.board, aura_def["target_filter"])
            for t_idx, target in targets:
                ench = _make_aura_enchantment(minion, idx, t_idx, aura_def, side="opp")
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
    )

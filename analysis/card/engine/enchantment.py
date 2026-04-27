"""engine/enchantment.py — Enchantment system with trigger registry.

Merged from search/enchantment.py and search/trigger_registry.py.
Provides Enchantment dataclass, EnchantmentRegistry, and trigger definitions.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analysis.card.engine.state import GameState, Minion

logger = logging.getLogger(__name__)


# ===================================================================
# Enchantment dataclass
# ===================================================================

@dataclass
class Enchantment:
    """A persistent buff/debuff attached to a minion or entity.

    Stat deltas are additive: minion effective attack = base + Σ(attack_delta).
    Keywords_added/removed modify the minion's keyword set.
    Trigger bindings link this enchantment to the TriggerDispatcher event system.
    Duration: -1 = permanent, >0 = turns remaining (decremented each turn end).
    """
    enchantment_id: str = ""
    name: str = ""
    source_dbf_id: int = 0
    source_id: str = ""                    # Card ID that created this
    attack_delta: int = 0
    health_delta: int = 0
    max_health_delta: int = 0
    cost_delta: int = 0
    keywords_added: List[str] = field(default_factory=list)
    keywords_removed: List[str] = field(default_factory=list)
    trigger_type: str = ""
    trigger_effect: str = ""
    trigger_bindings: List[str] = field(default_factory=list)  # event type bindings
    duration: int = -1                     # -1 = permanent, >0 = turns remaining


# ===================================================================
# EnchantmentRegistry — manages active enchantments
# ===================================================================

class EnchantmentRegistry:
    """Central registry for managing active enchantments across the game.

    Tracks enchantments by target entity and provides batch operations
    for attaching, removing, and ticking enchantments.
    """

    def __init__(self) -> None:
        # target_id -> list of Enchantment
        self._enchantments: Dict[str, List[Enchantment]] = {}

    def get_enchantments(self, target_id: str) -> List[Enchantment]:
        """Return all enchantments on a target."""
        return list(self._enchantments.get(target_id, []))

    def find_by_id(self, enchantment_id: str) -> Optional[tuple]:
        """Find an enchantment by its ID. Returns (target_id, Enchantment) or None."""
        for target_id, ench_list in self._enchantments.items():
            for ench in ench_list:
                if ench.enchantment_id == enchantment_id:
                    return (target_id, ench)
        return None

    def register(self, target_id: str, enchantment: Enchantment) -> None:
        """Track an enchantment in the registry."""
        self._enchantments.setdefault(target_id, []).append(enchantment)

    def unregister(self, target_id: str, enchantment_id: str) -> Optional[Enchantment]:
        """Remove an enchantment from tracking. Returns the removed enchantment or None."""
        ench_list = self._enchantments.get(target_id, [])
        for i, ench in enumerate(ench_list):
            if ench.enchantment_id == enchantment_id:
                return ench_list.pop(i)
        return None

    def clear_target(self, target_id: str) -> List[Enchantment]:
        """Remove all enchantments for a target. Returns removed list."""
        return self._enchantments.pop(target_id, [])

    def clear_all(self) -> None:
        """Remove all tracked enchantments."""
        self._enchantments.clear()

    def all_enchantments(self) -> List[tuple]:
        """Iterate over all (target_id, Enchantment) pairs."""
        result = []
        for target_id, ench_list in self._enchantments.items():
            for ench in ench_list:
                result.append((target_id, ench))
        return result


# ===================================================================
# Trigger registry — ported from search/trigger_registry.py
# ===================================================================

TRIGGER_REGISTRY: Dict[str, List[Enchantment]] = {
    # ── Knife Juggler / 飞刀杂耍者 ──
    "飞刀杂耍者": [
        Enchantment(
            enchantment_id="trigger_knife_juggler",
            trigger_type="on_play",
            trigger_effect="damage:random_enemy:1",
        ),
    ],
    "Knife Juggler": [
        Enchantment(
            enchantment_id="trigger_knife_juggler",
            trigger_type="on_play",
            trigger_effect="damage:random_enemy:1",
        ),
    ],
    # ── Bloodsail Cultist / 海魔驱逐者 ──
    "Bloodsail Cultist": [
        Enchantment(
            enchantment_id="trigger_bloodsail_cultist",
            trigger_type="on_play_pirate",
            trigger_effect="buff:other_PIRATE:1:1",
        ),
    ],
}


def get_triggers_for_minion(name: str) -> List[Enchantment]:
    """Get trigger enchantments for a minion by name.

    Returns deep copies to avoid shared mutation.
    """
    triggers = TRIGGER_REGISTRY.get(name, [])
    if triggers:
        return [Enchantment(
            enchantment_id=t.enchantment_id,
            name=t.name,
            source_dbf_id=t.source_dbf_id,
            source_id=t.source_id,
            trigger_type=t.trigger_type,
            trigger_effect=t.trigger_effect,
            trigger_bindings=list(t.trigger_bindings),
            attack_delta=t.attack_delta,
            health_delta=t.health_delta,
            duration=t.duration,
        ) for t in triggers]
    return []


# ===================================================================
# Stat computation helpers
# ===================================================================

def compute_effective_attack(minion: Any) -> int:
    """Compute effective attack = base_attack + Σ(attack_delta)."""
    base = getattr(minion, "attack", 0)
    delta = sum(e.attack_delta for e in getattr(minion, "enchantments", []))
    return max(0, base + delta)


def compute_effective_health(minion: Any) -> int:
    """Compute effective current health = base_health + Σ(health_delta)."""
    base = getattr(minion, "health", 0)
    delta = sum(e.health_delta for e in getattr(minion, "enchantments", []))
    return max(0, base + delta)


def compute_effective_max_health(minion: Any) -> int:
    """Compute effective max health = base_max_health + Σ(max_health_delta)."""
    base = getattr(minion, "max_health", 0)
    delta = sum(e.max_health_delta for e in getattr(minion, "enchantments", []))
    return max(1, base + delta)


def get_effective_keywords(minion: Any) -> set:
    """Compute effective keyword set after enchantment modifications."""
    keywords = set()
    flag_map = {
        "has_taunt": "TAUNT",
        "has_divine_shield": "DIVINE_SHIELD",
        "has_stealth": "STEALTH",
        "has_windfury": "WINDFURY",
        "has_rush": "RUSH",
        "has_charge": "CHARGE",
        "has_poisonous": "POISONOUS",
    }
    for flag, kw in flag_map.items():
        if getattr(minion, flag, False):
            keywords.add(kw)
    for e in getattr(minion, "enchantments", []):
        for kw in e.keywords_added:
            keywords.add(kw)
        for kw in e.keywords_removed:
            keywords.discard(kw)
    return keywords


# ===================================================================
# Enchantment management — GameState-aware operations
# ===================================================================

def attach_enchantment(
    state: GameState,
    target: Any,
    enchantment: Enchantment,
    registry: Optional[EnchantmentRegistry] = None,
) -> GameState:
    """Attach an enchantment to a target entity.

    Applies stat deltas immediately and optionally tracks in registry.

    Args:
        state: Game state (returned unchanged for chaining).
        target: Minion or card to enchant.
        enchantment: Enchantment to attach.
        registry: Optional EnchantmentRegistry for tracking.

    Returns:
        GameState (unchanged — mutation is in-place on target).
    """
    if not hasattr(target, "enchantments"):
        target.enchantments = []
    target.enchantments.append(enchantment)

    # Apply deltas directly to base stats
    if enchantment.attack_delta != 0:
        target.attack = max(0, target.attack + enchantment.attack_delta)
    if enchantment.health_delta != 0:
        target.health = max(0, target.health + enchantment.health_delta)
    if enchantment.max_health_delta != 0:
        target.max_health = max(1, target.max_health + enchantment.max_health_delta)
    if enchantment.cost_delta != 0 and hasattr(target, "cost"):
        target.cost = max(0, target.cost + enchantment.cost_delta)

    # Track in registry if provided
    if registry is not None:
        target_id = getattr(target, "enchantment_id", "") or getattr(target, "name", "") or id(target)
        registry.register(str(target_id), enchantment)

    return state


def remove_enchantment(
    state: GameState,
    target: Any,
    enchantment_id: str,
    registry: Optional[EnchantmentRegistry] = None,
) -> GameState:
    """Remove an enchantment by ID and reverse its stat deltas.

    Args:
        state: Game state (returned unchanged for chaining).
        target: Minion or card to remove enchantment from.
        enchantment_id: ID of the enchantment to remove.
        registry: Optional EnchantmentRegistry for tracking.

    Returns:
        GameState (unchanged — mutation is in-place on target).
    """
    if not hasattr(target, "enchantments"):
        return state

    for i, e in enumerate(target.enchantments):
        if e.enchantment_id == enchantment_id:
            # Reverse deltas
            if e.attack_delta != 0:
                target.attack = max(0, target.attack - e.attack_delta)
            if e.health_delta != 0:
                target.health = max(0, target.health - e.health_delta)
            if e.max_health_delta != 0:
                target.max_health = max(1, target.max_health - e.max_health_delta)
            if e.cost_delta != 0 and hasattr(target, "cost"):
                target.cost = max(0, target.cost - e.cost_delta)
            target.enchantments.pop(i)

            # Untrack from registry
            if registry is not None:
                target_id = getattr(target, "enchantment_id", "") or getattr(target, "name", "") or id(target)
                registry.unregister(str(target_id), enchantment_id)
            return state

    return state


def tick_enchantments(state: GameState) -> GameState:
    """Tick duration-based enchantments on all minions on both boards.

    Decrements duration on all enchantments. Removes expired ones
    (duration reaches 0). Permanent enchantments (duration=-1) are skipped.

    Returns:
        GameState with expired enchantments removed.
    """
    for minion in state.board:
        _tick_entity_enchantments(minion)
    for minion in state.opponent.board:
        _tick_entity_enchantments(minion)
    return state


def _tick_entity_enchantments(entity: Any) -> int:
    """Decrement duration and remove expired enchantments on a single entity.

    Returns number of enchantments removed.
    """
    if not hasattr(entity, "enchantments"):
        return 0
    removed = 0
    to_remove = []
    for e in entity.enchantments:
        if e.duration > 0:
            e.duration -= 1
            if e.duration <= 0:
                to_remove.append(e.enchantment_id)
    for eid in to_remove:
        # Reverse deltas on removal
        for e in entity.enchantments:
            if e.enchantment_id == eid:
                if e.attack_delta != 0:
                    entity.attack = max(0, entity.attack - e.attack_delta)
                if e.health_delta != 0:
                    entity.health = max(0, entity.health - e.health_delta)
                if e.max_health_delta != 0:
                    entity.max_health = max(1, entity.max_health - e.max_health_delta)
                if e.cost_delta != 0 and hasattr(entity, "cost"):
                    entity.cost = max(0, entity.cost - e.cost_delta)
                break
        entity.enchantments = [e for e in entity.enchantments if e.enchantment_id != eid]
        removed += 1
    return removed


# ===================================================================
# Legacy compatibility — minion-level apply/remove (in-place, no state)
# ===================================================================

def apply_enchantment(minion: Any, enchantment: Enchantment) -> None:
    """Attach an enchantment to a minion (legacy API, mutates in-place)."""
    if not hasattr(minion, "enchantments"):
        minion.enchantments = []
    minion.enchantments.append(enchantment)
    if enchantment.attack_delta != 0:
        minion.attack = max(0, minion.attack + enchantment.attack_delta)
    if enchantment.health_delta != 0:
        minion.health = max(0, minion.health + enchantment.health_delta)
    if enchantment.max_health_delta != 0:
        minion.max_health = max(1, minion.max_health + enchantment.max_health_delta)
    if enchantment.cost_delta != 0 and hasattr(minion, "cost"):
        minion.cost = max(0, minion.cost + enchantment.cost_delta)


def remove_enchantment_legacy(minion: Any, enchantment_id: str) -> None:
    """Remove an enchantment by ID (legacy API, mutates in-place)."""
    if not hasattr(minion, "enchantments"):
        return
    for i, e in enumerate(minion.enchantments):
        if e.enchantment_id == enchantment_id:
            if e.attack_delta != 0:
                minion.attack = max(0, minion.attack - e.attack_delta)
            if e.health_delta != 0:
                minion.health = max(0, minion.health - e.health_delta)
            if e.max_health_delta != 0:
                minion.max_health = max(1, minion.max_health - e.max_health_delta)
            if e.cost_delta != 0 and hasattr(minion, "cost"):
                minion.cost = max(0, minion.cost - e.cost_delta)
            minion.enchantments.pop(i)
            return

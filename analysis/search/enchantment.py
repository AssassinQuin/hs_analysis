#!/usr/bin/env python3
"""enchantment.py — Enchantment data model for Hearthstone AI.

Represents persistent buffs/debuffs attached to minions, with stat deltas,
keyword modifications, trigger bindings, and duration tracking.

Usage:
    python3 -m hs_analysis.search.enchantment          # run built-in self-test
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ===================================================================
# Enchantment dataclass
# ===================================================================

@dataclass
class Enchantment:
    """A persistent buff/debuff attached to a minion or entity.

    Stat deltas are additive: minion effective attack = base + Σ(attack_delta).
    Keywords_added/removed modify the minion's keyword set.
    Trigger_type links this enchantment to the TriggerDispatcher event system.
    Duration: -1 = permanent, >0 = turns remaining (decremented each turn end).
    """

    enchantment_id: str = ""               # Unique identifier (e.g. "aura_raid_leader_0")
    name: str = ""                         # Display name
    source_dbf_id: int = 0                 # Card DBF ID that created this
    attack_delta: int = 0                  # +attack modifier
    health_delta: int = 0                  # +health modifier (current HP)
    max_health_delta: int = 0              # +max_health modifier
    cost_delta: int = 0                    # +cost modifier (for hand cards)
    keywords_added: List[str] = field(default_factory=list)
    keywords_removed: List[str] = field(default_factory=list)
    trigger_type: str = ""                 # "deathrattle", "end_of_turn", "start_of_turn",
                                           # "on_attack", "aura", "on_damage", "on_spell_cast"
    trigger_effect: str = ""               # Effect description for dispatch
    duration: int = -1                     # -1 = permanent, >0 = turns remaining


# ===================================================================
# Stat computation helpers
# ===================================================================

def compute_effective_attack(minion) -> int:
    """Compute effective attack = base_attack + Σ(attack_delta from enchantments).

    Args:
        minion: Minion instance with .attack (base) and .enchantments list.

    Returns:
        Effective attack value (minimum 0).
    """
    base = getattr(minion, 'attack', 0)
    delta = sum(e.attack_delta for e in getattr(minion, 'enchantments', []))
    return max(0, base + delta)


def compute_effective_health(minion) -> int:
    """Compute effective current health = base_health + Σ(health_delta from enchantments).

    Args:
        minion: Minion instance with .health (base) and .enchantments list.

    Returns:
        Effective health value (minimum 0).
    """
    base = getattr(minion, 'health', 0)
    delta = sum(e.health_delta for e in getattr(minion, 'enchantments', []))
    return max(0, base + delta)


def compute_effective_max_health(minion) -> int:
    """Compute effective max health = base_max_health + Σ(max_health_delta from enchantments).

    Args:
        minion: Minion instance with .max_health and .enchantments list.

    Returns:
        Effective max health value (minimum 1).
    """
    base = getattr(minion, 'max_health', 0)
    delta = sum(e.max_health_delta for e in getattr(minion, 'enchantments', []))
    return max(1, base + delta)


def get_effective_keywords(minion) -> set:
    """Compute the effective keyword set after enchantment modifications.

    Returns a set of keyword strings like {'TAUNT', 'DIVINE_SHIELD'}.
    """
    # Base keywords from minion flags
    keywords = set()
    flag_map = {
        'has_taunt': 'TAUNT',
        'has_divine_shield': 'DIVINE_SHIELD',
        'has_stealth': 'STEALTH',
        'has_windfury': 'WINDFURY',
        'has_rush': 'RUSH',
        'has_charge': 'CHARGE',
        'has_poisonous': 'POISONOUS',
    }
    for flag, kw in flag_map.items():
        if getattr(minion, flag, False):
            keywords.add(kw)

    # Apply enchantment keyword modifications
    for e in getattr(minion, 'enchantments', []):
        for kw in e.keywords_added:
            keywords.add(kw)
        for kw in e.keywords_removed:
            keywords.discard(kw)

    return keywords


# ===================================================================
# Enchantment management
# ===================================================================

def apply_enchantment(minion, enchantment: Enchantment) -> None:
    """Attach an enchantment to a minion and apply its stat deltas.

    Modifies minion in place:
    - Adds enchantment to minion.enchantments list
    - Applies attack/health/max_health deltas immediately
    """
    if not hasattr(minion, 'enchantments'):
        minion.enchantments = []
    minion.enchantments.append(enchantment)

    # Apply deltas directly to base stats
    if enchantment.attack_delta != 0:
        minion.attack = max(0, minion.attack + enchantment.attack_delta)
    if enchantment.health_delta != 0:
        minion.health = max(0, minion.health + enchantment.health_delta)
    if enchantment.max_health_delta != 0:
        minion.max_health = max(1, minion.max_health + enchantment.max_health_delta)


def remove_enchantment(minion, enchantment_id: str) -> None:
    """Remove an enchantment by ID and reverse its stat deltas.

    Searches minion.enchantments for matching enchantment_id.
    If found, reverses deltas and removes from list.
    """
    if not hasattr(minion, 'enchantments'):
        return
    for i, e in enumerate(minion.enchantments):
        if e.enchantment_id == enchantment_id:
            # Reverse deltas
            if e.attack_delta != 0:
                minion.attack = max(0, minion.attack - e.attack_delta)
            if e.health_delta != 0:
                minion.health = max(0, minion.health - e.health_delta)
            if e.max_health_delta != 0:
                minion.max_health = max(1, minion.max_health - e.max_health_delta)
            minion.enchantments.pop(i)
            return


def tick_enchantments(minion) -> int:
    """Decrement duration on all enchantments and remove expired ones.

    Called at end of turn. Permanent enchantments (duration=-1) are skipped.

    Returns:
        Number of enchantments removed.
    """
    if not hasattr(minion, 'enchantments'):
        return 0
    removed = 0
    to_remove = []
    for e in minion.enchantments:
        if e.duration > 0:
            e.duration -= 1
            if e.duration <= 0:
                to_remove.append(e.enchantment_id)
    for eid in to_remove:
        remove_enchantment(minion, eid)
        removed += 1
    return removed


# ===================================================================
# Self-test
# ===================================================================

if __name__ == "__main__":
    from analysis.search.game_state import Minion

    m = Minion(attack=3, health=3, max_health=3)
    print(f"Base: {m.attack}/{m.health}")

    # Apply +2/+2 buff
    buff = Enchantment(
        enchantment_id="test_buff",
        name="Test Buff",
        attack_delta=2,
        health_delta=2,
        max_health_delta=2,
        duration=2,
    )
    apply_enchantment(m, buff)
    print(f"After buff: {m.attack}/{m.health} (max_hp={m.max_health})")
    assert m.attack == 5
    assert m.health == 5
    assert m.max_health == 5

    # Tick once → duration goes 2→1, still present
    removed = tick_enchantments(m)
    assert removed == 0
    assert len(m.enchantments) == 1

    # Tick again → duration goes 1→0, removed
    removed = tick_enchantments(m)
    assert removed == 1
    assert m.attack == 3
    assert m.health == 3
    print(f"After expiry: {m.attack}/{m.health}")

    # Permanent enchantment (duration=-1)
    perm = Enchantment(enchantment_id="perm", attack_delta=1, duration=-1)
    apply_enchantment(m, perm)
    tick_enchantments(m)  # should NOT remove permanent
    assert len(m.enchantments) == 1
    remove_enchantment(m, "perm")
    assert len(m.enchantments) == 0
    assert m.attack == 3
    print("All self-tests passed!")

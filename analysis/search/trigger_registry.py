#!/usr/bin/env python3
"""trigger_registry.py — Trigger enchantment definitions for named minions.

Maps minion names to their Enchantment definitions with trigger_type and
trigger_effect strings. Used by state_bridge to auto-attach triggers when
building Minion objects from Power.log data.

These are NOT static auras (handled by aura_engine.py) — they fire in
response to game events like playing a card, dealing damage, etc.
"""
from __future__ import annotations

from typing import Dict, List

from analysis.search.enchantment import Enchantment


# ═══════════════════════════════════════════════════════════════
# Trigger definitions: card_name → list of Enchantment templates
# ═══════════════════════════════════════════════════════════════

# Each entry maps to a list of Enchantment objects that should be
# auto-attached when a minion with this name enters the board.
#
# trigger_effect format: "effect_type:targets:params"
# - buff:other_DRAGON:2:0  → buff other dragons +2 attack, +0 health
# - damage:random_enemy:1  → deal 1 damage to random enemy
# - draw:self:1            → draw 1 card

TRIGGER_REGISTRY: Dict[str, List[Enchantment]] = {
    # NOTE: 龙群先锋 / Naralex, Dragon Pioneer 是费用修正光环，
    # 不是触发效果。它在 state_bridge._apply_board_cost_modifiers() 中处理。

    # ── 飞刀杂耍者 / Knife Juggler ──
    # "After you play a minion, deal 1 damage to a random enemy."
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

    # ── 海魔驱逐者 / Bloodsail Cultist ──
    # "After you play a Pirate, give your other Pirates +1/+1."
    "Bloodsail Cultist": [
        Enchantment(
            enchantment_id="trigger_bloodsail_cultist",
            trigger_type="on_play_pirate",
            trigger_effect="buff:other_PIRATE:1:1",
        ),
    ],

    # ── 暗影收割者 / Shadowgale ──
    # "After you play a spell, deal 1 damage to all enemy minions."
    # Note: simplified — actual effect may vary by card

    # ── 灵魂狱卒 / Spirit Jailer ──
    # "After a friendly minion dies, gain +1 Attack."
    # (deathrattle trigger variant)

    # ── Impatient Shopkeep ──
    # "After you play a card, gain +1 Attack."
    # (on_play trigger — buffs self)
}


def get_triggers_for_minion(name: str) -> List[Enchantment]:
    """Get trigger enchantments for a minion by name.

    Args:
        name: Minion name (EN or CN)

    Returns:
        List of Enchantment objects to attach, or empty list.
    """
    triggers = TRIGGER_REGISTRY.get(name, [])
    if triggers:
        # Return deep copies to avoid shared mutation
        return [Enchantment(
            enchantment_id=t.enchantment_id,
            trigger_type=t.trigger_type,
            trigger_effect=t.trigger_effect,
            attack_delta=t.attack_delta,
            health_delta=t.health_delta,
            duration=t.duration,
        ) for t in triggers]
    return []

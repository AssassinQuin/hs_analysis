#!/usr/bin/env python3
"""effect_parser.py — Card text → effect tuple parser.

Extracted from spell_simulator.EffectParser for reuse by the abilities system.
Parses card effects using structured CardEffects data or regex text fallback.

Returns List[Tuple[str, object]] — (effect_type, params) tuples.
Used by spell_simulator.resolve_effects() and battlecry_dispatcher.
"""
from __future__ import annotations

from typing import List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.models.card import Card


class EffectParser:
    """Parse card effects from a Card object or text fallback.

    Returns a list of (effect_type, params) tuples.

    Effect types produced:
        aoe_damage      → int
        random_damage   → int
        direct_damage   → int
        summon_stats    → (atk, hp) tuple
        summon          → True
        draw            → int
        destroy         → True
        heal            → int
        armor           → int
        buff_atk        → int
        hand_buff       → (atk, hp) tuple
        discard         → int
        cost_reduce     → int
    """

    @staticmethod
    def parse(card_text: str, card: Card = None) -> List[Tuple[str, object]]:
        """Parse card effects from a Card object or text fallback.

        If a Card object is provided, uses structured fields via get_effects().
        Falls back to text-only parsing if no Card is given.
        """
        if card is not None:
            return EffectParser._from_card(card)
        if not card_text:
            return []
        return EffectParser._from_text_fallback(card_text)

    @staticmethod
    def _from_card(card: Card) -> List[Tuple[str, object]]:
        from analysis.data.card_effects import get_effects

        eff = get_effects(card)
        effects: List[Tuple[str, object]] = []

        if eff.aoe_damage > 0:
            effects.append(('aoe_damage', eff.aoe_damage))
        if eff.random_damage > 0:
            effects.append(('random_damage', eff.random_damage))
        elif eff.damage > 0:
            effects.append(('direct_damage', eff.damage))

        if eff.summon_attack > 0 and eff.summon_health > 0:
            effects.append(('summon_stats', (eff.summon_attack, eff.summon_health)))
        elif eff.has_summon:
            effects.append(('summon', True))

        if eff.draw > 0:
            effects.append(('draw', eff.draw))
        if eff.has_destroy:
            effects.append(('destroy', True))
        if eff.heal > 0:
            effects.append(('heal', eff.heal))
        if eff.armor > 0:
            effects.append(('armor', eff.armor))
        if eff.buff_attack > 0:
            if eff.buff_health > 0:
                effects.append(('hand_buff', (eff.buff_attack, eff.buff_health)))
            else:
                effects.append(('buff_atk', eff.buff_attack))
        if eff.discard > 0:
            effects.append(('discard', eff.discard))
        if eff.cost_reduce > 0:
            effects.append(('cost_reduce', eff.cost_reduce))

        return effects

    @staticmethod
    def _from_text_fallback(card_text: str) -> List[Tuple[str, object]]:
        """Minimal text fallback when no Card object is available."""
        from analysis.data.card_effects import (
            _AOE_CN, _AOE_EN, _RANDOM_DMG_CN, _RANDOM_DMG_EN,
            _DAMAGE_CN, _DAMAGE_EN, _DRAW_CN, _DRAW_EN,
            _SUMMON_STATS_CN, _SUMMON_STATS_EN, _HEAL_CN, _HEAL_EN,
            _ARMOR_CN, _ARMOR_EN, _BUFF_ATK_CN, _BUFF_ATK_EN,
            _HAND_BUFF_CN, _DISCARD_CN, _DISCARD_EN,
            _COST_REDUCE_CN, _COST_REDUCE_EN,
        )

        effects: List[Tuple[str, object]] = []
        matched_ranges: List[Tuple[int, int]] = []

        def _check(pattern, effect_name, extractor):
            m = pattern.search(card_text)
            if m:
                s = m.span()
                for rs in matched_ranges:
                    if s[0] < rs[1] and s[1] > rs[0]:
                        return
                effects.append((effect_name, extractor(m)))
                matched_ranges.append(s)

        _check(_AOE_CN, 'aoe_damage', lambda m: int(m.group(1)))
        _check(_AOE_EN, 'aoe_damage', lambda m: int(m.group(1)))
        _check(_RANDOM_DMG_CN, 'random_damage', lambda m: int(m.group(1)))
        _check(_RANDOM_DMG_EN, 'random_damage', lambda m: int(m.group(1)))
        _check(_DAMAGE_CN, 'direct_damage', lambda m: int(m.group(1)))
        _check(_DAMAGE_EN, 'direct_damage', lambda m: int(m.group(1)))
        _check(_SUMMON_STATS_CN, 'summon_stats', lambda m: (int(m.group(1)), int(m.group(2))))
        _check(_SUMMON_STATS_EN, 'summon_stats', lambda m: (int(m.group(1)), int(m.group(2))))
        has_summon_stats = any(t == 'summon_stats' for t, _ in effects)
        if not has_summon_stats:
            if "召唤" in card_text:
                effects.append(('summon', True))
            elif "Summon" in card_text:
                effects.append(('summon', True))
        _check(_DRAW_CN, 'draw', lambda m: int(m.group(1)))
        _check(_DRAW_EN, 'draw', lambda m: int(m.group(1)))
        if "消灭" in card_text or "Destroy" in card_text:
            effects.append(('destroy', True))
        _check(_HEAL_CN, 'heal', lambda m: int(m.group(1)))
        _check(_HEAL_EN, 'heal', lambda m: int(m.group(1)))
        _check(_ARMOR_CN, 'armor', lambda m: int(m.group(1)))
        _check(_ARMOR_EN, 'armor', lambda m: int(m.group(1)))
        _check(_BUFF_ATK_CN, 'buff_atk', lambda m: int(m.group(1)))
        _check(_BUFF_ATK_EN, 'buff_atk', lambda m: int(m.group(1)))
        _check(_HAND_BUFF_CN, 'hand_buff', lambda m: (int(m.group(1)), int(m.group(2))))
        _check(_DISCARD_CN, 'discard', lambda m: int(m.group(1)))
        _check(_DISCARD_EN, 'discard', lambda m: int(m.group(1)))
        _check(_COST_REDUCE_CN, 'cost_reduce', lambda m: int(m.group(1)))
        _check(_COST_REDUCE_EN, 'cost_reduce', lambda m: int(m.group(1)))

        return effects

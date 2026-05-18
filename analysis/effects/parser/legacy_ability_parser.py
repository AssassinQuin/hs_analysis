#!/usr/bin/env python3
"""legacy_ability_parser.py — Converts new-format parsed effects to CardAbility objects.

The AbilityParser class bridges the new effects.parser system with consumers
that still expect the old ``CardAbility`` / ``EffectSpec`` model from
``analysis.card.abilities.definition``.
"""

from __future__ import annotations

from typing import List

from analysis.card.abilities.definition import (
    CardAbility, AbilityTrigger, EffectKind, EffectSpec,
    ConditionSpec, TargetSpec, TargetKind,
)
from analysis.effects.parser import parse as new_parse


# ── Trigger mapping: mechanics tag → AbilityTrigger ──
TRIGGER_MECHANICS = {
    "BATTLECRY": AbilityTrigger.BATTLECRY,
    "DEATHRATTLE": AbilityTrigger.DEATHRATTLE,
    "INSPIRE": AbilityTrigger.INSPIRE,
    "SECRET": AbilityTrigger.SECRET,
    "COMBO": AbilityTrigger.COMBO,
    "SPELLBURST": AbilityTrigger.SPELLBURST,
    "FRENZY": AbilityTrigger.ON_DAMAGE,
    "OUTCAST": AbilityTrigger.OUTCAST,
    "HONORABLE_KILL": AbilityTrigger.AFTER,
}


class AbilityParser:
    """Parse card abilities from a card object.

    Delegates to analysis.effects.parser internally.
    Returns List[CardAbility] (legacy format).
    """

    @classmethod
    def parse(cls, card) -> List[CardAbility]:
        mechanics = set(getattr(card, 'mechanics', []) or [])
        card_id = getattr(card, 'card_id', '') or ''
        text_en = getattr(card, 'english_text', '') or getattr(card, 'text', '') or ''

        parsed = new_parse(card_id, text_en)
        if parsed is None:
            return []

        abilities: List[CardAbility] = []

        text_raw = parsed.text_raw or text_en
        for ab in parsed.abilities:
            trigger = _map_trigger(ab.trigger)
            effects: List[EffectSpec] = []
            for eff in ab.effects:
                old_eff = _map_effect(eff)
                if old_eff is not None:
                    effects.append(old_eff)
            abilities.append(CardAbility(
                trigger=trigger,
                effects=effects,
                text_raw=text_raw,
            ))

        # Also scan mechanics tags for triggers the parser may have missed
        for mech, trigger in TRIGGER_MECHANICS.items():
            if mech in mechanics:
                if not any(a.trigger == trigger for a in abilities):
                    abilities.append(CardAbility(
                        trigger=trigger,
                        effects=[],
                        text_raw=text_en,
                    ))

        return abilities


def _map_trigger(new_trigger) -> AbilityTrigger:
    """Map new effects.types.Trigger to old AbilityTrigger."""
    from analysis.effects.types import Trigger
    mapping = {
        Trigger.BATTLECRY: AbilityTrigger.BATTLECRY,
        Trigger.DEATHRATTLE: AbilityTrigger.DEATHRATTLE,
        Trigger.SECRET: AbilityTrigger.SECRET,
        Trigger.INSPIRE: AbilityTrigger.INSPIRE,
        Trigger.CHOOSE_ONE: AbilityTrigger.CHOOSE_ONE,
        Trigger.COMBO: AbilityTrigger.COMBO,
        Trigger.OUTCAST: AbilityTrigger.OUTCAST,
        Trigger.SPELLBURST: AbilityTrigger.SPELLBURST,
        Trigger.INFUSE: AbilityTrigger.INFUSE,
        Trigger.CORRUPT: AbilityTrigger.CORRUPT,
        Trigger.QUEST: AbilityTrigger.QUEST,
        Trigger.TURN_START: AbilityTrigger.TURN_START,
        Trigger.TURN_END: AbilityTrigger.TURN_END,
        Trigger.ON_ATTACK: AbilityTrigger.ON_ATTACK,
        Trigger.ON_DAMAGE: AbilityTrigger.ON_DAMAGE,
        Trigger.ON_SPELL_CAST: AbilityTrigger.ON_SPELL_CAST,
        Trigger.AURA: AbilityTrigger.AURA,
        Trigger.ACTIVATE: AbilityTrigger.ACTIVATE,
    }
    return mapping.get(new_trigger, AbilityTrigger.BATTLECRY)


def _map_effect(new_effect) -> EffectSpec | None:
    """Map new Effect to old EffectSpec."""
    from analysis.effects.types import EffectKind as NewKind
    kind = new_effect.kind
    p = new_effect.params

    kind_map = {
        NewKind.DAMAGE: EffectKind.DAMAGE,
        NewKind.AOE_DAMAGE: EffectKind.AOE_DAMAGE,
        NewKind.RANDOM_DAMAGE: EffectKind.RANDOM_DAMAGE,
        NewKind.SUMMON: EffectKind.SUMMON,
        NewKind.DRAW: EffectKind.DRAW,
        NewKind.BUFF: EffectKind.BUFF,
        NewKind.DEBUFF: EffectKind.BUFF,
        NewKind.HAND_BUFF: EffectKind.GIVE,
        NewKind.DESTROY: EffectKind.DESTROY,
        NewKind.HEAL: EffectKind.HEAL,
        NewKind.DISCOVER: EffectKind.DISCOVER,
        NewKind.FREEZE: EffectKind.FREEZE,
        NewKind.SILENCE: EffectKind.SILENCE,
        NewKind.TRANSFORM: EffectKind.TRANSFORM,
        NewKind.ARMOR: EffectKind.ARMOR,
        NewKind.WEAPON_EQUIP: EffectKind.WEAPON_EQUIP,
        NewKind.REDUCE_COST: EffectKind.REDUCE_COST,
        NewKind.DISCARD: EffectKind.DISCARD,
        NewKind.GAIN_MANA: EffectKind.MANA,
        NewKind.CORPSE_GAIN: EffectKind.CORPSE_EFFECT,
        NewKind.CORPSE_SPEND: EffectKind.CORPSE_EFFECT,
        NewKind.COPY_CARD: EffectKind.COPY,
        NewKind.RETURN_TO_HAND: EffectKind.RETURN,
        NewKind.TAKE_CONTROL: EffectKind.TAKE_CONTROL,
        NewKind.ENCHANT: EffectKind.ENCHANT,
        NewKind.HERALD_SUMMON: EffectKind.HERALD_SUMMON,
        NewKind.IMBUE_UPGRADE: EffectKind.IMBUE_UPGRADE,
        NewKind.KINDRED_BUFF: EffectKind.KINDRED_BUFF,
        NewKind.COLOSSAL_SUMMON: EffectKind.COLOSSAL_SUMMON,
        NewKind.CORRUPT_UPGRADE: EffectKind.CORRUPT_UPGRADE,
    }
    old_kind = kind_map.get(kind)
    if old_kind is None:
        return None

    # New system uses 'amount', 'count', 'attack', 'health' as param names
    return EffectSpec(
        kind=old_kind,
        value=p.get("amount", 0) or p.get("count", 0) or p.get("attack", 0),
        value2=p.get("health", 0),
        subtype=p.get("subtype", ""),
    )

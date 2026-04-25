#!/usr/bin/env python3
"""parser.py — Unified ability parser from mechanics tags + English text.

Zero regex. Uses mechanics tags for direct trigger mapping and
string.find()/split() for effect/condition/target extraction.
"""
from __future__ import annotations

from typing import List, Tuple, Optional

from analysis.search.abilities.definition import (
    CardAbility, AbilityTrigger, EffectKind, EffectSpec,
    ConditionKind, ConditionSpec, TargetSpec, TargetKind,
)
from analysis.search.abilities.tokens import (
    MECHANICS_TRIGGER_MAP, STATIC_KEYWORD_MECHANICS,
    TEXT_TRIGGER_MAP, CONDITION_PHRASES,
)
from analysis.search.abilities.extractors import (
    clean_text, extract_number_after, extract_number_before,
    extract_stats_after, extract_plus_stats, extract_target_kind,
    extract_race_name, extract_keyword_after_give,
    extract_card_type_from_condition, extract_paren_number,
)


class AbilityParser:
    @classmethod
    def parse(cls, card) -> List[CardAbility]:
        mechanics = set(getattr(card, 'mechanics', []) or [])
        text_en = getattr(card, 'english_text', '') or getattr(card, 'text', '') or ''
        card_type = (getattr(card, 'card_type', '') or getattr(card, 'type', '') or '').upper()
        text_clean = clean_text(text_en)
        abilities: List[CardAbility] = []

        dynamic_mechanics = mechanics - STATIC_KEYWORD_MECHANICS

        for mech, trigger in MECHANICS_TRIGGER_MAP.items():
            if mech in dynamic_mechanics:
                effects, condition = cls._parse_effects_for_trigger(text_clean, trigger, card)
                if effects or trigger in (AbilityTrigger.BATTLECRY, AbilityTrigger.DEATHRATTLE):
                    abilities.append(CardAbility(
                        trigger=trigger,
                        condition=condition,
                        effects=effects,
                        text_raw=text_clean,
                    ))

        if "deathrattle" in text_clean.lower() and not any(a.trigger == AbilityTrigger.DEATHRATTLE for a in abilities):
            effects = cls._parse_deathrattle(text_clean)
            if effects:
                abilities.append(CardAbility(
                    trigger=AbilityTrigger.DEATHRATTLE,
                    effects=effects,
                    text_raw=text_clean,
                ))

        if card_type == "LOCATION":
            effects = cls._parse_activate(text_clean)
            abilities.append(CardAbility(
                trigger=AbilityTrigger.ACTIVATE,
                effects=effects,
                text_raw=text_clean,
            ))

        for phrase, trigger in TEXT_TRIGGER_MAP.items():
            if phrase in text_clean.lower():
                if not any(a.trigger == trigger for a in abilities):
                    effects, condition = cls._parse_effects_for_trigger(text_clean, trigger, card)
                    abilities.append(CardAbility(
                        trigger=trigger,
                        condition=condition,
                        effects=effects,
                        text_raw=text_clean,
                    ))

        return abilities

    @classmethod
    def _parse_effects_for_trigger(
        cls, text: str, trigger: AbilityTrigger, card
    ) -> Tuple[List[EffectSpec], Optional[ConditionSpec]]:
        condition = cls._parse_condition(text, card)
        effects = cls._parse_action_verbs(text)
        return effects, condition

    @classmethod
    def _parse_action_verbs(cls, text: str) -> List[EffectSpec]:
        effects: List[EffectSpec] = []
        tl = text.lower()

        if "summon" in tl:
            atk, hp = extract_stats_after(tl, "summon")
            target_str = extract_target_kind(tl)
            effects.append(EffectSpec(
                kind=EffectKind.SUMMON, value=atk, value2=hp,
                target=TargetSpec(kind=TargetKind(target_str)) if target_str else None,
            ))

        if "deal" in tl and "damage" in tl:
            amount = extract_number_after(tl, "deal")
            target_str = extract_target_kind(tl)
            is_aoe = "all" in tl or "each" in tl or "every" in tl or "randomly split" in tl
            if "randomly split" in tl:
                effects.append(EffectSpec(
                    kind=EffectKind.DAMAGE, value=amount,
                    target=TargetSpec(kind=TargetKind.ALL_ENEMY),
                ))
            else:
                effects.append(EffectSpec(
                    kind=EffectKind.DAMAGE, value=amount,
                    target=TargetSpec(kind=TargetKind(target_str)) if target_str else None,
                ))

        if "equip" in tl:
            atk, hp = extract_stats_after(tl, "equip")
            if atk > 0 or hp > 0:
                effects.append(EffectSpec(
                    kind=EffectKind.WEAPON_EQUIP, value=atk, value2=hp,
                ))

        if "give" in tl:
            atk, hp = extract_plus_stats(tl)
            if atk > 0 or hp > 0:
                effects.append(EffectSpec(kind=EffectKind.GIVE, value=atk, value2=hp))
            kw = extract_keyword_after_give(tl)
            if kw:
                effects.append(EffectSpec(kind=EffectKind.GIVE, keyword=kw))

        if "draw" in tl:
            count = extract_number_after(tl, "draw")
            effects.append(EffectSpec(kind=EffectKind.DRAW, value=max(count, 1)))

        if "gain" in tl:
            if "armor" in tl:
                amt = extract_number_before(tl, "armor")
                effects.append(EffectSpec(kind=EffectKind.GAIN, value=amt, subtype="armor"))
            if "health" in tl and "armor" not in tl:
                amt = extract_number_before(tl, "health")
                effects.append(EffectSpec(kind=EffectKind.GAIN, value=amt, subtype="health"))

        if "destroy" in tl:
            effects.append(EffectSpec(kind=EffectKind.DESTROY))

        if "discover" in tl:
            effects.append(EffectSpec(kind=EffectKind.DISCOVER))

        if "freeze" in tl:
            effects.append(EffectSpec(kind=EffectKind.FREEZE))

        if "silence" in tl:
            effects.append(EffectSpec(kind=EffectKind.SILENCE))

        if "transform" in tl:
            effects.append(EffectSpec(kind=EffectKind.TRANSFORM))

        if "heal" in tl or "restore" in tl:
            amt = 0
            if "restore" in tl:
                amt = extract_number_after(tl, "restore")
            elif "heal" in tl:
                amt = extract_number_after(tl, "heal")
            effects.append(EffectSpec(kind=EffectKind.HEAL, value=amt))

        return effects

    @classmethod
    def _parse_deathrattle(cls, text: str) -> List[EffectSpec]:
        return cls._parse_action_verbs(text)

    @classmethod
    def _parse_activate(cls, text: str) -> List[EffectSpec]:
        return cls._parse_action_verbs(text)

    @classmethod
    def _parse_condition(cls, text: str, card) -> Optional[ConditionSpec]:
        tl = text.lower()

        for phrase in ("you're holding a ", "you are holding a "):
            idx = tl.find(phrase)
            if idx >= 0:
                after = tl[idx + len(phrase):].strip()
                race = extract_race_name(after)
                if race:
                    return ConditionSpec(ConditionKind.HOLDING_RACE, {"race": race})

        if "for each" in tl:
            return ConditionSpec(ConditionKind.FOR_EACH, {})

        if "this turn" in tl:
            return ConditionSpec(ConditionKind.THIS_TURN, {})

        if "if you've played" in tl or "if you have played" in tl:
            card_type = extract_card_type_from_condition(tl)
            return ConditionSpec(ConditionKind.PLAYED_THIS_TURN, {"card_type": card_type})

        return None

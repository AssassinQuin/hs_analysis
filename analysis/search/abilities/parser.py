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
    KEYWORD_TEXT_MAP, KEYWORD_EFFECT_MAP,
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
                # Always generate ability for known triggers, even if no effects parsed.
                # Some triggers (AURA, QUEST, SECRET, TRIGGER_VISUAL) are valid with
                # empty effects — the text describes behavior too complex for verb parsing.
                # BATTLECRY/DEATHRATTLE only count if they have effects.
                if effects:
                    abilities.append(CardAbility(
                        trigger=trigger,
                        condition=condition,
                        effects=effects,
                        text_raw=text_clean,
                    ))
                elif trigger in (AbilityTrigger.BATTLECRY, AbilityTrigger.DEATHRATTLE):
                    abilities.append(CardAbility(
                        trigger=trigger,
                        condition=condition,
                        effects=effects,
                        text_raw=text_clean,
                    ))
                elif trigger in (AbilityTrigger.AURA, AbilityTrigger.QUEST,
                                 AbilityTrigger.SECRET, AbilityTrigger.TRIGGER_VISUAL,
                                 AbilityTrigger.COMBO, AbilityTrigger.OUTCAST):
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

        # ── Keyword detection (herald, imbue, kindred, etc.) ──
        abilities.extend(cls._parse_keywords(text_clean, card, abilities))

        # ── Structured effects from card_effects (reliable CN+EN coverage) ──
        # When verb parsing produced no effects, fall back to structured data
        # from card_effects.get_effects() which uses regex on both CN and EN text.
        abilities = cls._supplement_with_structured(card, abilities)

        return abilities

    # ──────────────────────────────────────────────────────────
    # Keyword detection (herald, imbue, kindred, etc.)
    # ──────────────────────────────────────────────────────────

    @classmethod
    def _parse_keywords(
        cls, text: str, card, existing: list
    ) -> List[CardAbility]:
        """Detect keyword abilities from card text.

        Keywords like Herald, Imbue, Kindred may not appear in mechanics
        array, so we detect them from english_text. Returns a list of
        CardAbility with the appropriate trigger and effect specs.
        """
        tl = text.lower()
        mechanics = set(getattr(card, 'mechanics', []) or [])
        results: List[CardAbility] = []
        existing_triggers = {a.trigger for a in existing}

        # ── Herald (兆示) ──
        if (AbilityTrigger.HERALD not in existing_triggers
                and ('herald' in tl or 'HERALD' in mechanics)):
            results.append(CardAbility(
                trigger=AbilityTrigger.HERALD,
                effects=[EffectSpec(kind=EffectKind.HERALD_SUMMON)],
                text_raw=text,
            ))

        # ── Imbue (灌注) ──
        if (AbilityTrigger.IMBUE not in existing_triggers
                and ('imbue' in tl or 'IMBUE' in mechanics)):
            results.append(CardAbility(
                trigger=AbilityTrigger.IMBUE,
                effects=[EffectSpec(kind=EffectKind.IMBUE_UPGRADE)],
                text_raw=text,
            ))

        # ── Colossal (巨型) ──
        if (AbilityTrigger.COLOSSAL not in existing_triggers
                and 'COLOSSAL' in mechanics):
            from analysis.search.colossal import parse_colossal_value
            n = parse_colossal_value(card)
            results.append(CardAbility(
                trigger=AbilityTrigger.COLOSSAL,
                effects=[EffectSpec(kind=EffectKind.COLOSSAL_SUMMON, value=n)],
                text_raw=text,
            ))

        # ── Kindred (延系) ──
        if (AbilityTrigger.KINDRED not in existing_triggers
                and 'kindred' in tl):
            results.append(CardAbility(
                trigger=AbilityTrigger.KINDRED,
                effects=[EffectSpec(kind=EffectKind.KINDRED_BUFF)],
                text_raw=text,
            ))

        # ── Combo discount (连击减费) ──
        if 'combo card costs' in tl or 'your next combo' in tl:
            discount = extract_number_after(tl, 'costs')
            if discount <= 0:
                discount = extract_number_after(tl, 'less')
            if discount <= 0:
                discount = 2  # default for Foxy Fraud
            results.append(CardAbility(
                trigger=AbilityTrigger.BATTLECRY,
                effects=[EffectSpec(kind=EffectKind.COMBO_DISCOUNT, value=discount)],
                text_raw=text,
            ))

        # ── Corpse effects (残骸) ──
        if 'spend' in tl and 'corpse' in tl:
            results.append(CardAbility(
                trigger=AbilityTrigger.CORPSE_SPEND,
                effects=[EffectSpec(kind=EffectKind.CORPSE_EFFECT)],
                text_raw=text,
            ))

        return results

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

        # AURA pattern: "have +N/N" or "have +N Attack"
        if " have +" in tl:
            atk, hp = extract_plus_stats(tl)
            if atk > 0 or hp > 0:
                effects.append(EffectSpec(kind=EffectKind.GIVE, value=atk, value2=hp))

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

    # ──────────────────────────────────────────────────────────
    # Structured data supplement (from card_effects)
    # ──────────────────────────────────────────────────────────

    @classmethod
    def _supplement_with_structured(
        cls, card, abilities: List[CardAbility]
    ) -> List[CardAbility]:
        """Supplement verb-parsed abilities with structured card_effects data.

        When verb parsing (english text verbs) produced no DAMAGE/DRAW/SUMMON/etc.
        effects, fall back to ``card_effects.get_effects()`` which parses both
        CN and EN text via regex.  This ensures complete coverage for all cards.

        The structured data is attached as a new BATTLECRY-like ability with
        trigger PLAY_EFFECT (a virtual trigger for spell/minion card effects
        that fire on play, separate from BATTLECRY keyword).
        """
        from analysis.data.card_effects import get_effects
        from analysis.search.abilities.definition import TargetSpec, TargetKind

        # Only works for Card objects (has mechanics/cost/text fields)
        if not hasattr(card, 'mechanics'):
            return abilities

        # Skip Location — handled by _resolve_location_effect directly
        card_type = (getattr(card, 'card_type', '') or '').upper()
        if card_type == "LOCATION":
            return abilities

        eff = get_effects(card)
        effects: List[EffectSpec] = []

        # Check if we already have these effects from verb parsing
        existing_kinds = set()
        for a in abilities:
            for e in a.effects:
                existing_kinds.add(e.kind)

        # Direct damage (skip if verb parsing already found DAMAGE)
        if eff.damage > 0 and EffectKind.DAMAGE not in existing_kinds:
            effects.append(EffectSpec(
                kind=EffectKind.DAMAGE, value=eff.damage,
            ))

        # Random damage
        if eff.random_damage > 0 and EffectKind.DAMAGE not in existing_kinds:
            effects.append(EffectSpec(
                kind=EffectKind.DAMAGE, value=eff.random_damage,
                target=TargetSpec(kind=TargetKind.RANDOM_ENEMY),
            ))

        # AOE damage
        if eff.aoe_damage > 0:
            effects.append(EffectSpec(
                kind=EffectKind.DAMAGE, value=eff.aoe_damage,
                target=TargetSpec(kind=TargetKind.ALL_ENEMY),
            ))

        # Heal
        if eff.heal > 0 and EffectKind.HEAL not in existing_kinds:
            effects.append(EffectSpec(
                kind=EffectKind.HEAL, value=eff.heal,
            ))

        # Draw
        if eff.draw > 0 and EffectKind.DRAW not in existing_kinds:
            effects.append(EffectSpec(kind=EffectKind.DRAW, value=eff.draw))

        # Summon
        if eff.summon_attack > 0 and eff.summon_health > 0:
            if EffectKind.SUMMON not in existing_kinds:
                effects.append(EffectSpec(
                    kind=EffectKind.SUMMON,
                    value=eff.summon_attack, value2=eff.summon_health,
                ))

        # Armor
        if eff.armor > 0 and EffectKind.GAIN not in existing_kinds:
            effects.append(EffectSpec(
                kind=EffectKind.GAIN, value=eff.armor, subtype="armor",
            ))

        # Buff attack
        if eff.buff_attack > 0 and EffectKind.GIVE not in existing_kinds:
            effects.append(EffectSpec(
                kind=EffectKind.GIVE,
                value=eff.buff_attack, value2=eff.buff_health,
            ))

        # Destroy
        if eff.has_destroy and EffectKind.DESTROY not in existing_kinds:
            effects.append(EffectSpec(kind=EffectKind.DESTROY))

        # Discard
        if eff.discard > 0 and EffectKind.DISCARD not in existing_kinds:
            effects.append(EffectSpec(kind=EffectKind.DISCARD, value=eff.discard))

        # Cost reduce
        if eff.cost_reduce > 0 and EffectKind.REDUCE_COST not in existing_kinds:
            effects.append(EffectSpec(kind=EffectKind.REDUCE_COST, value=eff.cost_reduce))

        # Silence
        if eff.has_silence and EffectKind.SILENCE not in existing_kinds:
            effects.append(EffectSpec(kind=EffectKind.SILENCE))

        if not effects:
            return abilities

        # Attach as PLAY_EFFECT trigger — a virtual trigger for
        # "effects that happen when you play this card" (spell effects,
        # minion battlecries without BATTLECRY tag, etc.)
        card_type = (getattr(card, 'card_type', '') or '').upper()
        if card_type == "SPELL":
            trigger = AbilityTrigger.ACTIVATE  # spell effects fire on play
        else:
            trigger = AbilityTrigger.BATTLECRY  # minion effects fire on play

        # Don't duplicate if we already have a BATTLECRY with effects
        if trigger == AbilityTrigger.BATTLECRY:
            has_bc_with_effects = any(
                a.trigger == AbilityTrigger.BATTLECRY and a.effects for a in abilities
            )
            if has_bc_with_effects:
                # Append to existing BATTLECRY ability instead of creating new
                for a in abilities:
                    if a.trigger == AbilityTrigger.BATTLECRY and a.effects:
                        # Add only effects not already present
                        existing_vals = {(e.kind, e.value) for e in a.effects}
                        for e in effects:
                            if (e.kind, e.value) not in existing_vals:
                                a.effects.append(e)
                        break
                return abilities

        abilities.append(CardAbility(
            trigger=trigger,
            effects=effects,
            text_raw=getattr(card, 'english_text', '') or '',
        ))
        return abilities

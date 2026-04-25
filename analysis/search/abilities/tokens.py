#!/usr/bin/env python3
"""tokens.py — Mapping tables for mechanics tags, action verbs, conditions.

All mappings derived from real data analysis of 7898 collectible cards.
Uses English text and mechanics tags exclusively — zero regex.
"""
from __future__ import annotations

from analysis.search.abilities.definition import (
    AbilityTrigger,
    EffectKind,
    ConditionKind,
    TargetKind,
)

# ──────────────────────────────────────────────────────────────
# Mechanics tag → AbilityTrigger (direct 1:1 mapping, zero parsing)
# ──────────────────────────────────────────────────────────────

MECHANICS_TRIGGER_MAP = {
    "BATTLECRY":      AbilityTrigger.BATTLECRY,
    "DEATHRATTLE":    AbilityTrigger.DEATHRATTLE,
    "SECRET":         AbilityTrigger.SECRET,
    "INSPIRE":        AbilityTrigger.INSPIRE,
    "CHOOSE_ONE":     AbilityTrigger.CHOOSE_ONE,
    "COMBO":          AbilityTrigger.COMBO,
    "OUTCAST":        AbilityTrigger.OUTCAST,
    "SPELLBURST":     AbilityTrigger.ON_SPELL_CAST,
    "INFUSE":         AbilityTrigger.INFUSE,
    "CORRUPT":        AbilityTrigger.CORRUPT,
    "QUEST":          AbilityTrigger.QUEST,
    "AURA":           AbilityTrigger.AURA,
    "TRIGGER_VISUAL": AbilityTrigger.TRIGGER_VISUAL,
}

# Static keyword mechanics — no ability parsing needed, just attach to entity
STATIC_KEYWORD_MECHANICS = frozenset({
    "TAUNT", "RUSH", "LIFESTEAL", "DIVINE_SHIELD", "STEALTH",
    "CHARGE", "WINDFURY", "POISONOUS", "REBORN", "ELUSIVE",
    "FREEZE", "SPELLPOWER", "OVERLOAD", "TRADEABLE",
    "IMMUNE", "CANT_BE_TARGETED_BY_SPELLS", "CANT_BE_TARGETED_BY_HEROPOWERS",
})

# ──────────────────────────────────────────────────────────────
# Action verbs → EffectKind (sorted by frequency in real data)
# ──────────────────────────────────────────────────────────────

ACTION_VERB_MAP = {
    "summon":     EffectKind.SUMMON,
    "deal":       EffectKind.DAMAGE,
    "give":       EffectKind.GIVE,
    "draw":       EffectKind.DRAW,
    "gain":       EffectKind.GAIN,
    "destroy":    EffectKind.DESTROY,
    "copy":       EffectKind.COPY,
    "cast":       EffectKind.CAST_SPELL,
    "restore":    EffectKind.HEAL,
    "shuffle":    EffectKind.SHUFFLE,
    "reduce":     EffectKind.REDUCE_COST,
    "transform":  EffectKind.TRANSFORM,
    "return":     EffectKind.RETURN,
    "control":    EffectKind.TAKE_CONTROL,
    "discard":    EffectKind.DISCARD,
    "swap":       EffectKind.SWAP,
    "equip":      EffectKind.WEAPON_EQUIP,
    "discover":   EffectKind.DISCOVER,
    "freeze":     EffectKind.FREEZE,
    "silence":    EffectKind.SILENCE,
    "enchant":    EffectKind.ENCHANT,
}

# ──────────────────────────────────────────────────────────────
# Condition keywords → ConditionKind
# ──────────────────────────────────────────────────────────────

CONDITION_PHRASES = {
    "you're holding a":  ConditionKind.HOLDING_RACE,
    "you are holding a": ConditionKind.HOLDING_RACE,
    "for each":          ConditionKind.FOR_EACH,
    "this turn":         ConditionKind.THIS_TURN,
    "if you've played":  ConditionKind.PLAYED_THIS_TURN,
    "if you have played": ConditionKind.PLAYED_THIS_TURN,
}

# ──────────────────────────────────────────────────────────────
# Target phrases → TargetKind
# ──────────────────────────────────────────────────────────────

TARGET_PHRASES = {
    "all enemies":        TargetKind.ALL_ENEMY,
    "all enemy":          TargetKind.ALL_ENEMY,
    "all friendly":       TargetKind.ALL_FRIENDLY,
    "all minions":        TargetKind.ALL_MINIONS,
    "all other":          TargetKind.ALL,
    "a random enemy":     TargetKind.RANDOM_ENEMY,
    "random enemy":       TargetKind.RANDOM_ENEMY,
    "a random friendly":  TargetKind.FRIENDLY_MINION,
    "a random":           TargetKind.RANDOM,
    "a friendly minion":  TargetKind.FRIENDLY_MINION,
    "a friendly":         TargetKind.FRIENDLY_MINION,
    "an enemy minion":    TargetKind.ENEMY,
    "an enemy":           TargetKind.ENEMY,
    "a minion":           TargetKind.SINGLE_MINION,
    "your hero":          TargetKind.FRIENDLY_HERO,
    "enemy hero":         TargetKind.ALL_ENEMY,
    "damaged":            TargetKind.DAMAGED,
    "undamaged":          TargetKind.UNDAMAGED,
}

# ──────────────────────────────────────────────────────────────
# Race name normalization (English text → standard race)
# ──────────────────────────────────────────────────────────────

RACE_NAMES = {
    "dragon": "DRAGON",
    "demon": "DEMON",
    "beast": "BEAST",
    "murloc": "MURLOC",
    "pirate": "PIRATE",
    "elemental": "ELEMENTAL",
    "undead": "UNDEAD",
    "totem": "TOTEM",
    "mechanical": "MECHANICAL",
    "mech": "MECHANICAL",
    "naga": "NAGA",
    "draenei": "DRAENEI",
}

# ──────────────────────────────────────────────────────────────
# Trigger timing keywords in text → AbilityTrigger
# ──────────────────────────────────────────────────────────────

TEXT_TRIGGER_MAP = {
    "at the start of your turn": AbilityTrigger.TURN_START,
    "at the start of each turn":  AbilityTrigger.TURN_START,
    "at the end of your turn":    AbilityTrigger.TURN_END,
    "at the end of each turn":    AbilityTrigger.TURN_END,
    "whenever":                   AbilityTrigger.WHENEVER,
    "after you":                  AbilityTrigger.AFTER,
    "after a":                    AbilityTrigger.AFTER,
    "after an":                   AbilityTrigger.AFTER,
    "costs less":                 AbilityTrigger.PASSIVE_COST,
    "cost less":                  AbilityTrigger.PASSIVE_COST,
}

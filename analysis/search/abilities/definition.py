#!/usr/bin/env python3
"""definition.py — Core data types for the unified card ability system.

All enums and data classes are derived from real data analysis of 7898
collectible cards in cards.collectible.json (enUS).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


# ──────────────────────────────────────────────────────────────
# Trigger — when does this ability fire?
# ──────────────────────────────────────────────────────────────

class AbilityTrigger(Enum):
    BATTLECRY = "BATTLECRY"
    DEATHRATTLE = "DEATHRATTLE"
    SECRET = "SECRET"
    INSPIRE = "INSPIRE"
    CHOOSE_ONE = "CHOOSE_ONE"
    COMBO = "COMBO"
    OUTCAST = "OUTCAST"
    SPELLBURST = "SPELLBURST"
    INFUSE = "INFUSE"
    CORRUPT = "CORRUPT"
    QUEST = "QUEST"
    TURN_START = "TURN_START"
    TURN_END = "TURN_END"
    WHENEVER = "WHENEVER"
    AFTER = "AFTER"
    ON_ATTACK = "ON_ATTACK"
    ON_DAMAGE = "ON_DAMAGE"
    ON_SPELL_CAST = "ON_SPELL_CAST"
    ON_DEATH = "ON_DEATH"
    AURA = "AURA"
    PASSIVE_COST = "PASSIVE_COST"
    ACTIVATE = "ACTIVATE"
    TRIGGER_VISUAL = "TRIGGER_VISUAL"


# ──────────────────────────────────────────────────────────────
# Effect — what does this ability do?
# ──────────────────────────────────────────────────────────────

class EffectKind(Enum):
    DAMAGE = "DAMAGE"
    SUMMON = "SUMMON"
    DRAW = "DRAW"
    GAIN = "GAIN"
    GIVE = "GIVE"
    DESTROY = "DESTROY"
    COPY = "COPY"
    HEAL = "HEAL"
    SHUFFLE = "SHUFFLE"
    REDUCE_COST = "REDUCE_COST"
    TRANSFORM = "TRANSFORM"
    RETURN = "RETURN"
    TAKE_CONTROL = "TAKE_CONTROL"
    DISCARD = "DISCARD"
    SWAP = "SWAP"
    WEAPON_EQUIP = "WEAPON_EQUIP"
    DISCOVER = "DISCOVER"
    FREEZE = "FREEZE"
    SILENCE = "SILENCE"
    CAST_SPELL = "CAST_SPELL"
    ENCHANT = "ENCHANT"


# ──────────────────────────────────────────────────────────────
# Condition — when is this ability active?
# ──────────────────────────────────────────────────────────────

class ConditionKind(Enum):
    HOLDING_RACE = "HOLDING_RACE"
    THIS_TURN = "THIS_TURN"
    FOR_EACH = "FOR_EACH"
    HAS_KEYWORD = "HAS_KEYWORD"
    PLAYED_THIS_TURN = "PLAYED_THIS_TURN"
    COST_COMPARISON = "COST_COMPARISON"
    HEALTH_THRESHOLD = "HEALTH_THRESHOLD"
    BOARD_STATE = "BOARD_STATE"


# ──────────────────────────────────────────────────────────────
# Target — who/what does this ability affect?
# ──────────────────────────────────────────────────────────────

class TargetKind(Enum):
    SINGLE_MINION = "SINGLE_MINION"
    RANDOM = "RANDOM"
    FRIENDLY_HERO = "FRIENDLY_HERO"
    FRIENDLY_MINION = "FRIENDLY_MINION"
    RANDOM_ENEMY = "RANDOM_ENEMY"
    ALL_MINIONS = "ALL_MINIONS"
    ENEMY = "ENEMY"
    ALL_ENEMY = "ALL_ENEMY"
    ALL_FRIENDLY = "ALL_FRIENDLY"
    DAMAGED = "DAMAGED"
    UNDAMAGED = "UNDAMAGED"
    SELF = "SELF"
    ALL = "ALL"


# ──────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────

@dataclass
class ConditionSpec:
    kind: ConditionKind
    params: dict = field(default_factory=dict)

    def check(self, state, source) -> bool:
        from analysis.search.abilities.executor import check_condition
        return check_condition(self, state, source)


@dataclass
class TargetSpec:
    kind: TargetKind
    count: int = 1
    side: str = ""
    filters: list = field(default_factory=list)


@dataclass
class EffectSpec:
    kind: EffectKind
    value: int = 0
    value2: int = 0
    subtype: str = ""
    keyword: str = ""
    target: Optional[TargetSpec] = None
    text_raw: str = ""


@dataclass
class CardAbility:
    trigger: AbilityTrigger
    condition: Optional[ConditionSpec] = None
    effects: List[EffectSpec] = field(default_factory=list)
    text_raw: str = ""

    def is_active(self, state, source) -> bool:
        if self.condition is None:
            return True
        return self.condition.check(state, source)

    def execute(self, state, source, target=None):
        from analysis.search.abilities.executor import execute_effects
        return execute_effects(state, source, self.effects, target)

    def __repr__(self):
        parts = [f"Ability({self.trigger.value}"]
        if self.condition:
            parts.append(f" if {self.condition.kind.value}")
        if self.effects:
            eff_strs = [e.kind.value for e in self.effects]
            parts.append(f" -> {','.join(eff_strs)}")
        parts.append(")")
        return "".join(parts)

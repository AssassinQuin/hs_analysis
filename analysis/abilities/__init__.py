"""analysis/abilities/ — Top-level ability system."""
from analysis.card.abilities.definition import (
    AbilityTrigger, EffectKind, ConditionKind, TargetKind,
    EffectSpec, CardAbility, ConditionSpec, TargetSpec,
    LazyValue, EntitySelector,
    ActionType, Action,  # merged from actions.py
)
from analysis.card.abilities.value_expr import resolve, to_lazy_value, from_lazy_value
from analysis.card.abilities.loader import load_abilities, load_all_abilities

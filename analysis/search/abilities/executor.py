#!/usr/bin/env python3
"""executor.py — Unified ability execution engine.

Single entry point for all ability triggers. Replaces scattered if/elif
chains across battlecry_dispatcher, deathrattle, location, turn_advance, etc.
"""
from __future__ import annotations

import logging
from typing import List, Optional, TYPE_CHECKING

from analysis.search.abilities.definition import (
    CardAbility, AbilityTrigger, EffectSpec, EffectKind,
    ConditionSpec, ConditionKind, TargetSpec, TargetKind,
)

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


class AbilityExecutor:
    @staticmethod
    def trigger(
        state: 'GameState',
        event: AbilityTrigger,
        source=None,
        target=None,
    ) -> 'GameState':
        entities = _collect_entities(state, source)
        for entity in entities:
            abilities = getattr(entity, 'abilities', [])
            if not abilities:
                card_ref = getattr(entity, 'card_ref', None)
                if card_ref is not None:
                    abilities = getattr(card_ref, 'abilities', [])
            for ability in abilities:
                if ability.trigger != event:
                    continue
                if not ability.is_active(state, entity):
                    continue
                try:
                    state = ability.execute(state, entity, target)
                except Exception as exc:
                    log.debug("Ability execution failed: %s — %s", ability, exc)
        return state


def check_condition(spec: ConditionSpec, state: 'GameState', source) -> bool:
    if spec.kind == ConditionKind.HOLDING_RACE:
        race = spec.params.get("race", "")
        hand = getattr(state, 'hand', [])
        source_idx = None
        for i, h in enumerate(hand):
            if h is source:
                source_idx = i
                break
        for i, h in enumerate(hand):
            if i == source_idx:
                continue
            h_race = getattr(h, 'race', '').upper()
            h_races = getattr(h, 'races', None)
            if h_race == race:
                return True
            if h_races and race in [r.upper() for r in h_races]:
                return True
        return False

    if spec.kind == ConditionKind.THIS_TURN:
        return True

    if spec.kind == ConditionKind.FOR_EACH:
        return True

    if spec.kind == ConditionKind.PLAYED_THIS_TURN:
        card_type = spec.params.get("card_type", "")
        played = getattr(state, 'cards_played_this_turn', [])
        for p in played:
            p_type = getattr(p, 'card_type', '').upper()
            p_school = getattr(p, 'spell_school', '').upper()
            if card_type == p_type or card_type == p_school:
                return True
        return False

    return True


def execute_effects(
    state: 'GameState',
    source,
    effects: List[EffectSpec],
    target=None,
) -> 'GameState':
    s = state
    for effect in effects:
        s = _execute_single(s, source, effect, target)
    return s


def _execute_single(
    state: 'GameState',
    source,
    effect: EffectSpec,
    target=None,
) -> 'GameState':
    kind = effect.kind

    if kind == EffectKind.WEAPON_EQUIP:
        from analysis.search.game_state import Weapon
        state.hero.weapon = Weapon(
            attack=effect.value, health=effect.value2,
            name=getattr(source, 'name', 'Weapon'),
        )
        return state

    if kind == EffectKind.DAMAGE:
        amount = effect.value
        if amount <= 0:
            return state
        tgt = _resolve_target(state, effect.target, target)
        if tgt == "enemy_hero":
            state.opponent.hero.hp -= amount
        elif tgt == "friendly_hero":
            state.hero.hp -= amount
        elif isinstance(tgt, int) and tgt >= 0:
            board = state.opponent.board if _is_enemy_target(effect.target) else state.board
            if tgt < len(board):
                board[tgt].health -= amount
        elif tgt == "all_enemy":
            for m in list(state.opponent.board):
                m.health -= amount
            if amount >= state.opponent.hero.hp:
                state.opponent.hero.hp = 0
        return state

    if kind == EffectKind.SUMMON:
        from analysis.search.game_state import Minion
        atk = effect.value
        hp = effect.value2
        if atk > 0 or hp > 0:
            m = Minion(attack=atk, health=hp, name="Token", can_attack=False)
            if len(state.board) < 7:
                state.board.append(m)
        return state

    if kind == EffectKind.DRAW:
        count = max(effect.value, 1)
        for _ in range(count):
            if state.deck_remaining > 0:
                state.deck_remaining -= 1
        return state

    if kind == EffectKind.GAIN:
        subtype = effect.subtype
        amount = effect.value
        if subtype == "armor":
            state.hero.armor += amount
        elif subtype == "health":
            state.hero.hp += amount
        return state

    if kind == EffectKind.HEAL:
        amount = effect.value
        if amount > 0:
            state.hero.hp = min(state.hero.hp + amount, 30)
        return state

    if kind == EffectKind.GIVE:
        atk = effect.value
        hp = effect.value2
        if atk > 0 or hp > 0:
            if isinstance(target, int) and 0 <= target < len(state.board):
                state.board[target].attack += atk
                state.board[target].health += hp
        return state

    if kind == EffectKind.DISCOVER:
        return state

    if kind == EffectKind.DESTROY:
        return state

    if kind == EffectKind.FREEZE:
        return state

    if kind == EffectKind.SILENCE:
        return state

    return state


def _resolve_target(state, target_spec: Optional[TargetSpec], fallback_target=None):
    if target_spec is None:
        return fallback_target
    kind = target_spec.kind
    if kind == TargetKind.ALL_ENEMY:
        return "all_enemy"
    if kind == TargetKind.ALL_MINIONS:
        return "all_minions"
    if kind == TargetKind.FRIENDLY_HERO:
        return "friendly_hero"
    if kind == TargetKind.RANDOM_ENEMY:
        opp_board = state.opponent.board
        if opp_board:
            import random
            return random.randint(0, len(opp_board) - 1)
        return "enemy_hero"
    if kind in (TargetKind.SINGLE_MINION, TargetKind.ENEMY):
        if fallback_target is not None:
            return fallback_target
        opp_board = state.opponent.board
        if opp_board:
            import random
            return random.randint(0, len(opp_board) - 1)
        return "enemy_hero"
    if kind == TargetKind.FRIENDLY_MINION:
        if fallback_target is not None:
            return fallback_target
        return 0
    return fallback_target


def _is_enemy_target(target_spec: Optional[TargetSpec]) -> bool:
    if target_spec is None:
        return True
    return target_spec.kind in (
        TargetKind.ENEMY, TargetKind.RANDOM_ENEMY, TargetKind.ALL_ENEMY,
    )


def _collect_entities(state: 'GameState', source=None):
    entities = list(state.board)
    if source is not None and source not in entities:
        entities.append(source)
    return entities

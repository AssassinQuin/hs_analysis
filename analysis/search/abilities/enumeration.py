#!/usr/bin/env python3
"""enumeration.py — Legal action enumeration for the search engine."""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from analysis.search.abilities.actions import Action, ActionType

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion

_spell_target_resolver = None


def _get_spell_target_resolver():
    global _spell_target_resolver
    if _spell_target_resolver is None:
        from analysis.search.engine.mechanics.spell_target_resolver import (
            SpellTargetResolver,
        )
        _spell_target_resolver = SpellTargetResolver()
    return _spell_target_resolver


def enumerate_legal_actions(state: GameState) -> List[Action]:
    """Enumerate all legal actions for the current player turn."""
    actions: List[Action] = []

    _enumerate_play_actions(state, actions)
    _enumerate_attack_actions(state, actions)
    _enumerate_hero_power(state, actions)
    _enumerate_location_actions(state, actions)
    actions.append(Action(action_type=ActionType.END_TURN))

    _stamp_card_names(actions, state)
    return actions


# ── PLAY actions ──


def _enumerate_play_actions(state: GameState, actions: List[Action]):
    """Generate all legal PLAY / PLAY_WITH_TARGET actions from hand."""
    for idx, card in enumerate(state.hand):
        tags = _probe_tags_for_card(state, card)
        eff_cost = state.mana.effective_cost(card)
        from analysis.search.abilities.simulation import _apply_text_cost_reduction
        eff_cost = _apply_text_cost_reduction(card, state.hand, idx, eff_cost)
        if eff_cost > state.mana.available:
            continue

        ctype = card.card_type.upper()
        if ctype == "MINION":
            _enum_play_minion(state, idx, card, tags, actions)
        elif ctype == "HERO":
            actions.append(
                Action(
                    action_type=ActionType.HERO_REPLACE,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif ctype == "SPELL":
            _enum_play_spell(state, idx, card, tags, actions)
        elif ctype == "WEAPON":
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif ctype == "LOCATION":
            if not state.location_full():
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )


def _enum_play_minion(state, idx, card, tags, actions):
    """Enumerate minion play actions (with optional target for battlecry)."""
    if state.board_full():
        return
    try:
        targets = _get_spell_target_resolver().resolve_targets(state, card)
    except (ImportError, AttributeError, TypeError):
        targets = []
    if targets:
        for tgt in targets:
            for pos in range(len(state.board) + 1):
                actions.append(
                    Action(
                        action_type=ActionType.PLAY_WITH_TARGET,
                        card_index=idx,
                        target_index=tgt,
                        position=pos,
                        meta_tags=frozenset(tags),
                    )
                )
    else:
        for pos in range(len(state.board) + 1):
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    position=pos,
                    meta_tags=frozenset(tags),
                )
            )


def _enum_play_spell(state, idx, card, tags, actions):
    """Enumerate spell play actions with target resolution."""
    try:
        targets = _get_spell_target_resolver().resolve_targets(state, card)
        if targets:
            for tgt in targets:
                actions.append(
                    Action(
                        action_type=ActionType.PLAY_WITH_TARGET,
                        card_index=idx,
                        target_index=tgt,
                        meta_tags=frozenset(tags),
                    )
                )
        else:
            # targets=[] — three cases:
            # 1. AOE (auto-targets all): can play without selecting target
            # 2. No-target spell (draw, armor, buff-self): can play
            # 3. Targeted spell with no valid targets: CANNOT play
            text = getattr(card, "text", "") or ""

            # Case 1: AOE — detect "所有/全部/all" + damage patterns
            is_aoe = (
                "所有" in text or "全部" in text
                or "all enemie" in text.lower()
                or "all minion" in text.lower()
            )
            if is_aoe:
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )
                return

            # Case 2 vs 3: use card_effects to check if card has damage
            from analysis.data.card_effects import get_effects
            eff = get_effects(card)
            has_damage = eff.damage > 0 or eff.random_damage > 0 or eff.aoe_damage > 0

            from analysis.search.engine.mechanics.spell_target_resolver import SpellTargetResolver
            has_target_keyword = SpellTargetResolver.has_targeting_keyword(text)
            if not (has_damage and has_target_keyword):
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )
    except (ImportError, AttributeError, TypeError):
        actions.append(
            Action(
                action_type=ActionType.PLAY,
                card_index=idx,
                meta_tags=frozenset(tags),
            )
        )


# ── ATTACK actions ──


def _enumerate_attack_actions(state: GameState, actions: List[Action]):
    """Generate all legal ATTACK actions (minion + hero weapon)."""
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    # Minion attacks
    for src_idx, minion in enumerate(state.board):
        can_act = minion.can_attack or (
            minion.has_windfury and minion.has_attacked_once
        )
        if not can_act or minion.frozen_until_next_turn or minion.is_dormant or minion.cant_attack:
            continue

        if enemy_taunts:
            for tgt_idx, _ in enumerate(enemy_taunts):
                real_idx = _find_enemy_minion_index(state, enemy_taunts[tgt_idx])
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=real_idx + 1,
                    )
                )
        else:
            if not minion.has_rush:
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=0,
                    )
                )
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=tgt_idx + 1,
                    )
                )

    # Hero weapon attacks
    if state.hero.weapon is not None and state.hero.weapon.attack > 0:
        if enemy_taunts:
            for t in enemy_taunts:
                real_idx = _find_enemy_minion_index(state, t)
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,
                        target_index=real_idx + 1,
                    )
                )
        else:
            actions.append(
                Action(action_type=ActionType.ATTACK, source_index=-1, target_index=0)
            )
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,
                        target_index=tgt_idx + 1,
                    )
                )


# ── HERO_POWER actions ──


def _enumerate_hero_power(state: GameState, actions: List[Action]):
    """Generate HERO_POWER action if available and affordable."""
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        actions.append(Action(action_type=ActionType.HERO_POWER))


# ── LOCATION actions ──


def _enumerate_location_actions(state: GameState, actions: List[Action]):
    """Generate ACTIVATE_LOCATION actions for ready locations."""
    for loc_idx, loc in enumerate(state.locations):
        if loc.durability <= 0 or loc.cooldown_current != 0:
            continue
        loc_text = getattr(loc, 'text', '') or ''
        loc_targets = []
        if loc_text:
            try:
                resolver = _get_spell_target_resolver()
                class _LocCard:
                    def __init__(self, text):
                        self.text = text
                        self.card_type = "LOCATION"
                loc_targets = resolver.resolve_targets(state, _LocCard(loc_text))
            except (ImportError, AttributeError, TypeError):
                loc_targets = []
        if loc_targets:
            for tgt in loc_targets:
                actions.append(
                    Action(
                        action_type=ActionType.ACTIVATE_LOCATION,
                        source_index=loc_idx,
                        target_index=tgt,
                    )
                )
        else:
            actions.append(
                Action(
                    action_type=ActionType.ACTIVATE_LOCATION,
                    source_index=loc_idx,
                )
            )


# ── Helpers ──


def _stamp_card_names(actions: List[Action], state: GameState):
    """Stamp each PLAY action with card name for action_key uniqueness."""
    for a in actions:
        if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            if 0 <= a.card_index < len(state.hand):
                a._card_name = state.hand[a.card_index].name or ''


def _find_enemy_minion_index(state: GameState, minion: Minion) -> int:
    for i, m in enumerate(state.opponent.board):
        if m is minion:
            return i
    return 0


def _probe_tags_for_card(state: GameState, card) -> set[str]:
    tags: set[str] = set()
    enemy_has_secret = bool(getattr(state.opponent, "secrets", None))
    card_type = (getattr(card, "card_type", "") or "").upper()
    cost = int(getattr(card, "cost", 0) or 0)
    attack = int(getattr(card, "attack", 0) or 0)
    health = int(getattr(card, "health", 0) or 0)

    if enemy_has_secret:
        if card_type == "SPELL" and cost <= 2:
            tags.add("PROBE_SECRET")
        if card_type == "MINION" and (attack + health) <= 4:
            tags.add("PROBE_SECRET")

    if cost >= 6:
        tags.add("RESOURCE_HOLD")
    return tags

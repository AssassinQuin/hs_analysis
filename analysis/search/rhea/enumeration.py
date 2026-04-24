#!/usr/bin/env python3
"""enumeration.py — Legal action enumeration for the RHEA search engine."""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from analysis.search.rhea.actions import Action, ActionType

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
    actions: List[Action] = []

    for idx, card in enumerate(state.hand):
        tags = _probe_tags_for_card(state, card)
        eff_cost = state.mana.effective_cost(card)
        if eff_cost > state.mana.available:
            continue
        if card.card_type.upper() == "MINION":
            if not state.board_full():
                for pos in range(len(state.board) + 1):
                    actions.append(
                        Action(
                            action_type=ActionType.PLAY,
                            card_index=idx,
                            position=pos,
                            meta_tags=frozenset(tags),
                        )
                    )
        elif card.card_type.upper() == "HERO":
            actions.append(
                Action(
                    action_type=ActionType.HERO_REPLACE,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif card.card_type.upper() == "SPELL":
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
                    # No targets returned — check if this is a no-target spell
                    # (AOE, draw, armor) or a targeted spell with no valid targets
                    text = getattr(card, "text", "") or ""
                    from analysis.data.card_effects import _DAMAGE_CN, _DAMAGE_EN
                    has_damage = bool(_DAMAGE_EN.search(text) or _DAMAGE_CN.search(text))
                    has_target_keyword = any(
                        kw in text for kw in
                        ("受伤", "damaged", "敌方随从", "enemy minion",
                         "友方随从", "friendly minion", "一个?随从")
                    )
                    # If spell has damage text and mentions target conditions,
                    # empty targets means no valid target → cannot play.
                    # Otherwise it's a no-target spell (draw, armor, AOE etc.)
                    if not (has_damage and has_target_keyword):
                        actions.append(
                            Action(
                                action_type=ActionType.PLAY,
                                card_index=idx,
                                meta_tags=frozenset(tags),
                            )
                        )
            except Exception:
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )
        elif card.card_type.upper() == "WEAPON":
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif card.card_type.upper() == "LOCATION":
            if not state.location_full():
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        position=0,
                        meta_tags=frozenset(tags),
                    )
                )

    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    for src_idx, minion in enumerate(state.board):
        can_act = minion.can_attack or (
            minion.has_windfury and minion.has_attacked_once
        )
        if not can_act:
            continue
        if minion.frozen_until_next_turn:
            continue
        if minion.is_dormant:
            continue
        if minion.cant_attack:
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
            can_attack_hero = not minion.has_rush
            if can_attack_hero:
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
                Action(
                    action_type=ActionType.ATTACK,
                    source_index=-1,
                    target_index=0,
                )
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

    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        actions.append(Action(action_type=ActionType.HERO_POWER))

    for loc_idx, loc in enumerate(state.locations):
        if loc.durability > 0 and loc.cooldown_current == 0:
            actions.append(
                Action(
                    action_type=ActionType.ACTIVATE_LOCATION,
                    source_index=loc_idx,
                )
            )

    actions.append(Action(action_type=ActionType.END_TURN))

    return actions


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

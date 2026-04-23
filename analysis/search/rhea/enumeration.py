#!/usr/bin/env python3
"""enumeration.py — Legal action enumeration for the RHEA search engine."""

from __future__ import annotations

from typing import List, TYPE_CHECKING

from analysis.search.rhea.actions import Action

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
    """Return all legal actions for the given state."""
    actions: List[Action] = []

    # --- PLAY actions ---
    for idx, card in enumerate(state.hand):
        eff_cost = state.mana.effective_cost(card)
        if eff_cost > state.mana.available:
            continue
        if card.card_type.upper() == "MINION":
            if not state.board_full():
                for pos in range(len(state.board) + 1):
                    actions.append(
                        Action(
                            action_type="PLAY",
                            card_index=idx,
                            position=pos,
                        )
                    )
        elif card.card_type.upper() == "HERO":
            actions.append(
                Action(
                    action_type="HERO_REPLACE",
                    card_index=idx,
                )
            )
        elif card.card_type.upper() == "SPELL":
            try:
                targets = _get_spell_target_resolver().resolve_targets(state, card)
                if targets:
                    for tgt in targets:
                        actions.append(
                            Action(
                                action_type="PLAY_WITH_TARGET",
                                card_index=idx,
                                target_index=tgt,
                            )
                        )
                else:
                    actions.append(
                        Action(
                            action_type="PLAY",
                            card_index=idx,
                        )
                    )
            except Exception:
                actions.append(
                    Action(
                        action_type="PLAY",
                        card_index=idx,
                    )
                )
        elif card.card_type.upper() == "WEAPON":
            actions.append(
                Action(
                    action_type="PLAY",
                    card_index=idx,
                )
            )
        elif card.card_type.upper() == "LOCATION":
            if not state.location_full():
                actions.append(
                    Action(
                        action_type="PLAY",
                        card_index=idx,
                        position=0,
                    )
                )

    # --- ATTACK actions ---
    # Check if enemy has taunt minions
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    for src_idx, minion in enumerate(state.board):
        # Can attack if: can_attack flag is set, OR has windfury and has attacked once
        can_act = minion.can_attack or (
            minion.has_windfury and minion.has_attacked_once
        )
        if not can_act:
            continue
        # Frozen minions cannot attack
        if minion.frozen_until_next_turn:
            continue
        # Dormant minions cannot attack
        if minion.is_dormant:
            continue
        # Minions with cant_attack cannot attack
        if minion.cant_attack:
            continue

        if enemy_taunts:
            # Must attack taunt minions — taunt blocks ALL face attacks,
            # including charge minions (charge bypasses summoning sickness, NOT taunt)
            for tgt_idx, _ in enumerate(enemy_taunts):
                # Find the actual index in opponent.board
                real_idx = _find_enemy_minion_index(state, enemy_taunts[tgt_idx])
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=real_idx + 1,  # 1-indexed (0 = hero)
                    )
                )
        else:
            # No taunts: can attack enemy hero or any enemy minion
            # Enemy hero
            can_attack_hero = not minion.has_rush  # Rush can only attack minions
            if can_attack_hero:
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=0,
                    )
                )
            # Enemy minions (skip stealthed)
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=tgt_idx + 1,  # 1-indexed
                    )
                )

    # --- Hero weapon ATTACK ---
    if state.hero.weapon is not None and state.hero.weapon.attack > 0:
        # Hero immune check: immune hero can still attack but doesn't take damage
        if enemy_taunts:
            for t in enemy_taunts:
                real_idx = _find_enemy_minion_index(state, t)
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=-1,
                        target_index=real_idx + 1,
                    )
                )
        else:
            actions.append(
                Action(
                    action_type="ATTACK",
                    source_index=-1,
                    target_index=0,
                )
            )
            # Weapon attack enemy minions (skip stealthed)
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=-1,
                        target_index=tgt_idx + 1,
                    )
                )

    # --- HERO_POWER action ---
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        actions.append(Action(action_type="HERO_POWER"))

    # --- ACTIVATE_LOCATION actions ---
    for loc_idx, loc in enumerate(state.locations):
        if loc.durability > 0 and loc.cooldown_current == 0:
            actions.append(
                Action(
                    action_type="ACTIVATE_LOCATION",
                    source_index=loc_idx,
                )
            )

    # --- END_TURN (always legal) ---
    actions.append(Action(action_type="END_TURN"))

    return actions


def _find_enemy_minion_index(state: GameState, minion: Minion) -> int:
    """Find the index of a minion object in the opponent's board."""
    for i, m in enumerate(state.opponent.board):
        if m is minion:
            return i
    return 0

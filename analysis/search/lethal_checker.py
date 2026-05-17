#!/usr/bin/env python3
"""lethal_checker.py — Exhaustive lethal detection within a time budget.

Provides:
  - max_damage_bound(state): upper-bound estimate of total damage available
  - check_lethal(state, time_budget_ms): DFS search for a lethal action sequence

Design principles:
  - Missing lethal is catastrophic → must be exhaustive within the time budget.
  - If the time budget is exceeded, returns None (fallback to RHEA).
"""

from __future__ import annotations

import time
from typing import List, Optional

from analysis.data.card_effects import get_card_damage, _DAMAGE_CN, _DAMAGE_EN
from analysis.search.game_state import GameState, Minion
from analysis.search.abilities import (
    Action,
    ActionType,
    apply_action,
    enumerate_legal_actions,
)


# ===================================================================
# max_damage_bound
# ===================================================================


def max_damage_bound(state: GameState) -> int:
    """Return an upper-bound estimate of total damage the current player can deal.

    Sums:
      - Board minion attack (only those that can attack face; rush-only excluded)
      - Windfury bonus for eligible minions
      - Hand spell damage (regex-parsed from card text)
      - Weapon damage (if equipped)
      - Hero power damage (rough class-based estimate)
    """
    total = 0

    # Board damage — minions that can attack face (rush-only minions can't go face)
    for m in state.board:
        if m.can_attack or m.has_charge:
            total += m.attack
            if m.has_windfury:
                total += m.attack  # windfury = double attack

    # Hand spell damage
    for card in state.hand:
        dmg = get_card_damage(card)
        if dmg > 0 and card.cost <= state.mana.available:
            spell_power_bonus = sum(m.spell_power for m in state.board)
            total += dmg + spell_power_bonus

    # Weapon
    if state.hero.weapon is not None:
        total += state.hero.weapon.attack

    # Hero power (rough estimate)
    hero_class = state.hero.hero_class.upper() if state.hero.hero_class else ""
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        if state.hero.hero_power_damage > 0:
            total += state.hero.hero_power_damage
        elif hero_class == "MAGE":
            total += 1
        elif hero_class == "HUNTER":
            total += 2

    return total


# ===================================================================
# _enumerate_damage_actions
# ===================================================================


def _enumerate_damage_actions(state: GameState) -> list:
    """Return only the subset of legal actions that deal damage."""
    actions: list = []
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    # ATTACK actions
    for src_idx, m in enumerate(state.board):
        if not (m.can_attack or m.has_charge):
            continue

        if enemy_taunts:
            # ALL attackers (including charge) must target taunt minions first.
            # Charge bypasses summoning sickness, NOT taunt.
            for t in enemy_taunts:
                real_idx = state.opponent.board.index(t)
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=real_idx + 1,
                    )
                )
        else:
            # No taunts: rush minions can't go face
            if not m.has_rush:
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=0,
                    )
                )
            # All attackers can target enemy minions
            for tgt_idx in range(len(state.opponent.board)):
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=tgt_idx + 1,
                    )
                )

    # Hero weapon ATTACK (source_index=-1 convention for hero)
    if state.hero.weapon is not None and state.hero.weapon.attack > 0:
        if enemy_taunts:
            # Must attack through taunts
            for t in enemy_taunts:
                real_idx = state.opponent.board.index(t)
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,  # hero
                        target_index=real_idx + 1,
                    )
                )
        else:
            # Can go face
            actions.append(
                Action(
                    action_type=ActionType.ATTACK,
                    source_index=-1,
                    target_index=0,
                )
            )
            # Can attack enemy minions
            for tgt_idx in range(len(state.opponent.board)):
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,
                        target_index=tgt_idx + 1,
                    )
                )

    # PLAY damage spells
    for idx, card in enumerate(state.hand):
        if card.cost > state.mana.available:
            continue
        if getattr(card, "card_type", "").upper() == "SPELL":
            text = getattr(card, "text", "") or ""
            _is_dmg = bool(
                _DAMAGE_CN.search(text) or _DAMAGE_EN.search(text)
            )
            mechanics = getattr(card, "mechanics", None)
            if mechanics and not _is_dmg:
                _is_dmg = any(k in mechanics for k in ("AFFECTED_BY_SPELL_POWER",))
            if _is_dmg:
                actions.append(Action(action_type=ActionType.PLAY, card_index=idx))
                actions.append(
                    Action(
                        action_type=ActionType.PLAY_WITH_TARGET,
                        card_index=idx,
                        target_index=0,
                    )
                )
                for tgt_idx in range(len(state.opponent.board)):
                    actions.append(
                        Action(
                            action_type=ActionType.PLAY_WITH_TARGET,
                            card_index=idx,
                            target_index=tgt_idx + 1,
                        )
                    )

    # Hero power damage
    hero_class = state.hero.hero_class.upper() if state.hero.hero_class else ""
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        if hero_class in ("MAGE", "HUNTER") or state.hero.hero_power_damage > 0:
            actions.append(Action(action_type=ActionType.HERO_POWER, target_index=0))

    return actions


# ===================================================================
# _dfs_lethal
# ===================================================================


def _dfs_lethal(
    state: GameState,
    actions: list,
    remaining_health: int,
    depth: int,
    deadline: float,
) -> Optional[List[Action]]:
    """Recursive DFS for lethal. Returns action sequence or None."""
    if remaining_health <= 0:
        return []
    if depth > 20:  # max depth safety
        return None
    if time.perf_counter() > deadline:
        return None

    # Prune: remaining max damage < remaining enemy health
    rem_dmg = max_damage_bound(state)
    if rem_dmg < remaining_health:
        return None

    # Get current legal actions for legality checking
    legal = enumerate_legal_actions(state)

    for action in actions:
        # Check if this action is still legal
        legal_check = False
        for la in legal:
            if (
                la.action_type == action.action_type
                and la.card_index == action.card_index
                and la.source_index == action.source_index
                and la.target_index == action.target_index
            ):
                legal_check = True
                break
        if not legal_check:
            continue

        new_state = apply_action(state, action)
        new_health = new_state.opponent.hero.hp + new_state.opponent.hero.armor

        new_actions = _enumerate_damage_actions(new_state)
        result = _dfs_lethal(new_state, new_actions, new_health, depth + 1, deadline)
        if result is not None:
            return [action] + result

    return None


# ===================================================================
# check_lethal  (main entry point)
# ===================================================================


def check_lethal(
    state: GameState, time_budget_ms: float = 5.0
) -> Optional[List[Action]]:
    """Search for a lethal action sequence within *time_budget_ms*.

    Returns a list of Actions that kill the opponent, or None if lethal
    is not found (either impossible or timed out).
    """
    enemy_health = state.opponent.hero.hp + state.opponent.hero.armor
    if enemy_health <= 0:
        return []  # already dead

    bound = max_damage_bound(state)
    if bound < enemy_health:
        return None  # can't possibly kill

    deadline = time.perf_counter() + (time_budget_ms / 1000.0)
    actions = _enumerate_damage_actions(state)

    if not actions:
        return None

    result = _dfs_lethal(state, actions, enemy_health, 0, deadline)
    if result is not None:
        return result
    return None

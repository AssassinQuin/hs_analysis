#!/usr/bin/env python3
# [从 analysis/search/deathrattle.py 迁移而来]
# 原文件仍保留，后续 Phase 统一 import 路径后删除原文件。
"""deathrattle.py — Deathrattle queue for Hearthstone AI.

Handles minion death resolution: collects dead minions, queues deathrattle
effects in board-position order, executes effects, and cascades up to a
configurable limit.

Uses the unified abilities executor (zero regex, English text only).
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from analysis.engine.state import GameState, Minion

logger = logging.getLogger(__name__)


def resolve_deaths(state: GameState, max_cascade: int = 5) -> GameState:
    """Resolve all dead minions on both boards with deathrattle effects.

    Process:
    1. Collect all minions with health <= 0 from both boards
    2. Queue deathrattle effects in board-position order (left to right)
    3. Execute each deathrattle effect
    4. Re-check for new deaths (cascade), up to max_cascade times
    5. Remove all dead minions from boards
    """
    s = state

    for cascade in range(max_cascade):
        dead_queue = _collect_dead(s)

        if not dead_queue:
            break

        for minion, board_type, position in dead_queue:
            s = _execute_deathrattle(s, minion, board_type, position)

        s.board = [m for m in s.board if m.health > 0]
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s


def _collect_dead(state: GameState) -> List[Tuple[Minion, str, int]]:
    """Collect all dead minions (health <= 0) from both boards."""
    dead = []

    for i, m in enumerate(state.board):
        if m.health <= 0:
            dead.append((m, 'friendly', i))

    for i, m in enumerate(state.opponent.board):
        if m.health <= 0:
            dead.append((m, 'enemy', i))

    dead.sort(key=lambda x: (0 if x[1] == 'friendly' else 1, x[2]))
    return dead


def _execute_deathrattle(
    state: GameState,
    minion: Minion,
    board_type: str,
    position: int,
) -> GameState:
    """Execute deathrattle effects for a single dying minion.

    Sources checked in order:
    1. Enchantment-based deathrattles (trigger_type="deathrattle")
    2. Unified abilities executor (from mechanics tags + English text)
    """
    s = state

    # Source 1: Enchantment-based deathrattles
    for ench in list(getattr(minion, 'enchantments', [])):
        if ench.trigger_type == "deathrattle" and ench.trigger_effect:
            try:
                s = _apply_deathrattle_effect(s, ench.trigger_effect, board_type, position)
            except Exception as exc:
                logger.warning("Deathrattle enchantment failed: %s — %s", ench.trigger_effect, exc)

    # Source 2: Unified abilities executor
    s = _execute_abilities_deathrattle(s, minion, board_type, position)

    return s


def _execute_abilities_deathrattle(
    state: GameState,
    minion: Minion,
    board_type: str,
    position: int,
) -> GameState:
    """Execute deathrattle via unified abilities system (zero regex)."""
    from analysis.abilities.definition import AbilityTrigger
    from analysis.abilities.loader import load_abilities

    abilities = getattr(minion, 'abilities', [])
    if not abilities:
        card_ref = getattr(minion, 'card_ref', None)
        if card_ref is not None:
            abilities = getattr(card_ref, 'abilities', [])
        if not abilities:
            card_id = getattr(minion, 'card_id', '') or (getattr(card_ref, 'card_id', '') if card_ref else '')
            if card_id:
                abilities = load_abilities(card_id)
            if not abilities:
                abilities = []

    for ability in abilities:
        if ability.trigger != AbilityTrigger.DEATHRATTLE:
            continue
        if not ability.is_active(state, minion):
            continue
        try:
            state = ability.execute(state, minion)
        except Exception as exc:
            logger.debug("Abilities deathrattle failed: %s — %s", ability, exc)

    return state


def _apply_deathrattle_effect(
    state: GameState,
    effect: str,
    board_type: str,
    position: int,
) -> GameState:
    """Apply a single deathrattle effect string from enchantments.

    Supported patterns:
    - summon:A:H          — summon a token with attack=A, health=H
    - damage:all_enemy:N  — deal N damage to all enemy minions
    - damage:random_enemy:N — deal N damage to a random enemy minion
    - draw:N              — draw N cards
    - buff:friendly:A:H   — buff surviving friendly minions +A/+H
    - armor:N             — gain N armor
    """
    s = state
    parts = effect.split(':')

    if parts[0] == 'summon' and len(parts) >= 3:
        try:
            atk_val = int(parts[1])
            hp_val = int(parts[2])
        except (ValueError, IndexError):
            logger.warning("Invalid summon effect: %s", effect)
            return s

        token = Minion(attack=atk_val, health=hp_val, max_health=hp_val,
                       name=f"DR Token {atk_val}/{hp_val}")

        if board_type == 'friendly':
            board = s.board
        else:
            board = s.opponent.board

        # Insert at position if valid, otherwise append
        if 0 <= position <= len(board):
            board.insert(position, token)
        else:
            board.append(token)

        logger.debug("Deathrattle summon: %d/%d at pos %d (%s)",
                     atk_val, hp_val, position, board_type)

    elif parts[0] == 'damage' and len(parts) >= 3:
        try:
            dmg = int(parts[-1])
        except (ValueError, IndexError):
            logger.warning("Invalid damage effect: %s", effect)
            return s

        target = parts[1]

        if target == 'all_enemy':
            if board_type == 'friendly':
                enemy_board = s.opponent.board
            else:
                enemy_board = s.board

            for m in enemy_board:
                if getattr(m, 'has_divine_shield', False):
                    m.has_divine_shield = False
                else:
                    m.health -= dmg

            logger.debug("Deathrattle AoE damage %d to %d enemies",
                         dmg, len(enemy_board))

        elif target == 'random_enemy':
            if board_type == 'friendly':
                enemy_board = s.opponent.board
            else:
                enemy_board = s.board

            alive = [m for m in enemy_board if m.health > 0]
            if alive:
                from analysis.engine.deterministic import DeterministicRNG
                rng = DeterministicRNG.from_state(s)
                target_minion = rng.choice(alive)
                if getattr(target_minion, 'has_divine_shield', False):
                    target_minion.has_divine_shield = False
                else:
                    target_minion.health -= dmg

            logger.debug("Deathrattle random damage %d", dmg)

    elif parts[0] == 'draw' and len(parts) >= 2:
        try:
            n = int(parts[1])
        except (ValueError, IndexError):
            logger.warning("Invalid draw effect: %s", effect)
            return s

        deck_remaining = getattr(s, 'deck_remaining', 0) or 0
        s.deck_remaining = max(0, deck_remaining - n)
        logger.debug("Deathrattle draw %d", n)

    elif parts[0] == 'buff' and len(parts) >= 4:
        try:
            buff_atk = int(parts[2])
            buff_hp = int(parts[3])
        except (ValueError, IndexError):
            logger.warning("Invalid buff effect: %s", effect)
            return s

        if board_type == 'friendly':
            friendly_board = s.board
        else:
            friendly_board = s.opponent.board

        for m in friendly_board:
            if m.health > 0:  # only buff surviving minions
                m.attack += buff_atk
                m.health += buff_hp
                m.max_health += buff_hp

        logger.debug("Deathrattle buff +%d/+%d to %d minions",
                     buff_atk, buff_hp, len(friendly_board))

    elif parts[0] == 'armor' and len(parts) >= 2:
        try:
            n = int(parts[1])
        except (ValueError, IndexError):
            logger.warning("Invalid armor effect: %s", effect)
            return s

        if board_type == 'friendly':
            hero = s.hero
        else:
            hero = getattr(s.opponent, 'hero', None)

        if hero is not None:
            hero.armor = getattr(hero, 'armor', 0) + n

        logger.debug("Deathrattle armor %d", n)

    else:
        logger.debug("Unparseable deathrattle effect: %s", effect)

    return s

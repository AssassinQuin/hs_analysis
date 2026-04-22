#!/usr/bin/env python3
"""trigger_system.py — Trigger dispatcher for Hearthstone AI.

Central event bus that dispatches game events (play, death, attack, etc.)
to registered listeners based on enchantment trigger_types on minions.

All methods return a (possibly modified) GameState copy and never crash —
each dispatch is wrapped in try/except for graceful degradation.

Usage:
    python3 -m hs_analysis.search.trigger_system          # run built-in self-test
"""

from __future__ import annotations

import copy
import logging
from typing import List, Optional

from analysis.search.game_state import GameState, Minion

logger = logging.getLogger(__name__)


# ===================================================================
# TriggerDispatcher
# ===================================================================

class TriggerDispatcher:
    """Dispatches game events to enchantment-based triggers on minions.

    Each event method scans both boards for minions with enchantments
    whose trigger_type matches the event. For each match, the enchantment's
    trigger_effect string is dispatched to the appropriate handler.

    All methods receive and return a GameState (may be the same or a copy).
    """

    # ---------------------------------------------------------------
    # Public event dispatchers
    # ---------------------------------------------------------------

    def on_minion_played(self, state: GameState, minion: Minion, card) -> GameState:
        """Fire after a minion is played onto the board.

        Triggers: on_play enchantments on OTHER minions (e.g. "Whenever you play a beast...").
        """
        s = state
        for m in s.board:
            if m is minion:
                continue  # skip the just-played minion itself
            s = self._dispatch_triggers(s, m, "on_play")
        # Also scan enemy board for opponent triggers (future: secrets, etc.)
        for m in s.opponent.board:
            s = self._dispatch_triggers(s, m, "on_play")
        return s

    def on_minion_dies(self, state: GameState, minion: Minion, position: int) -> GameState:
        """Fire after a minion dies (health <= 0).

        Triggers: deathrattle enchantments on the dying minion, plus
        on_death triggers on other minions.
        """
        s = state
        # First: fire the dying minion's own deathrattle triggers
        s = self._dispatch_triggers(s, minion, "deathrattle")
        # Then: fire on_death triggers on surviving minions
        for m in s.board:
            if m is not minion:
                s = self._dispatch_triggers(s, m, "on_death")
        for m in s.opponent.board:
            if m is not minion:
                s = self._dispatch_triggers(s, m, "on_death")
        return s

    def on_turn_end(self, state: GameState) -> GameState:
        """Fire at end of turn.

        Triggers: end_of_turn enchantments on all friendly minions.
        Also ticks all enchantment durations.
        """
        from analysis.search.enchantment import tick_enchantments
        s = state
        for m in s.board:
            s = self._dispatch_triggers(s, m, "end_of_turn")
            tick_enchantments(m)
        for m in s.opponent.board:
            tick_enchantments(m)
        return s

    def on_turn_start(self, state: GameState) -> GameState:
        """Fire at start of turn.

        Triggers: start_of_turn enchantments on all friendly minions.
        """
        s = state
        for m in s.board:
            s = self._dispatch_triggers(s, m, "start_of_turn")
        return s

    def on_attack(self, state: GameState, attacker: Minion, target) -> GameState:
        """Fire after an attack is resolved.

        Triggers: on_attack enchantments on the attacker and on_damage on the target.
        """
        s = state
        s = self._dispatch_triggers(s, attacker, "on_attack")
        if target is not None:
            s = self._dispatch_triggers(s, target, "on_damage")
        return s

    def on_spell_cast(self, state: GameState, card) -> GameState:
        """Fire after a spell is cast.

        Triggers: on_spell_cast enchantments on all friendly minions.
        """
        s = state
        for m in s.board:
            s = self._dispatch_triggers(s, m, "on_spell_cast")
        return s

    def on_damage_dealt(self, state: GameState, target, amount: int) -> GameState:
        """Fire after damage is dealt to any target.

        Triggers: on_damage enchantments on the damaged entity.
        """
        s = state
        if isinstance(target, Minion):
            s = self._dispatch_triggers(s, target, "on_damage")
        return s

    def on_heal(self, state: GameState, target, amount: int) -> GameState:
        """Fire after healing.

        Triggers: on_heal enchantments on the healed entity.
        """
        s = state
        if isinstance(target, Minion):
            s = self._dispatch_triggers(s, target, "on_heal")
        return s

    # ---------------------------------------------------------------
    # Internal: trigger dispatch engine
    # ---------------------------------------------------------------

    def _dispatch_triggers(self, state: GameState, minion: Minion,
                           trigger_type: str) -> GameState:
        """Scan minion's enchantments for matching trigger_type and dispatch effects.

        For each matching enchantment, call _execute_effect with the trigger_effect string.
        Returns the (possibly modified) state.
        """
        s = state
        if not hasattr(minion, 'enchantments') or not minion.enchantments:
            return s

        for ench in list(minion.enchantments):  # copy list to allow mutation
            if ench.trigger_type == trigger_type and ench.trigger_effect:
                try:
                    s = self._execute_effect(s, ench.trigger_effect, minion)
                except Exception as exc:
                    # Graceful degradation: log and continue
                    logger.warning(
                        "Trigger dispatch failed for %s/%s: %s",
                        getattr(minion, 'name', '?'), ench.trigger_effect, exc,
                    )
        return s

    def _execute_effect(self, state: GameState, effect: str,
                        source: Minion) -> GameState:
        """Execute a trigger effect string on the game state.

        Effect strings are parsed to determine the action:
        - "damage:random_enemy:N" → deal N damage to random enemy
        - "damage:enemy_hero:N" → deal N damage to enemy hero
        - "summon:N:N" → summon N/N token
        - "draw:N" → draw N cards
        - "buff:friendly:N:N" → give all friendly minions +N/+N
        - "heal:hero:N" → heal hero N HP
        - "armor:N" → gain N armor
        - Unknown effects are logged and ignored (graceful degradation).
        """
        import re

        s = state
        parts = effect.split(":")

        if not parts:
            return s

        action = parts[0]

        if action == "damage" and len(parts) >= 3:
            target_type = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                return s

            if target_type == "random_enemy" and s.opponent.board:
                import random
                target = random.choice(s.opponent.board)
                if target.has_divine_shield:
                    target.has_divine_shield = False
                else:
                    target.health -= amount
            elif target_type == "enemy_hero":
                s.opponent.hero.hp -= amount
            elif target_type == "all_enemy" and s.opponent.board:
                for m in s.opponent.board:
                    if m.has_divine_shield:
                        m.has_divine_shield = False
                    else:
                        m.health -= amount

        elif action == "summon" and len(parts) >= 3:
            try:
                atk = int(parts[1])
                hp = int(parts[2])
            except ValueError:
                return s
            if len(s.board) < 7:
                token = Minion(
                    name=f"Token({atk}/{hp})",
                    attack=atk,
                    health=hp,
                    max_health=hp,
                    can_attack=False,
                    owner="friendly",
                )
                s.board.append(token)

        elif action == "draw" and len(parts) >= 2:
            try:
                count = int(parts[1])
            except ValueError:
                return s
            from analysis.search.rhea_engine import apply_draw
            s = apply_draw(s, count)

        elif action == "buff" and len(parts) >= 4:
            try:
                atk_delta = int(parts[2])
                hp_delta = int(parts[3])
            except ValueError:
                return s
            target_type = parts[1]
            if target_type == "friendly":
                for m in s.board:
                    m.attack = max(0, m.attack + atk_delta)
                    m.health = max(0, m.health + hp_delta)
                    m.max_health = max(1, m.max_health + hp_delta)

        elif action == "heal" and len(parts) >= 3:
            target_type = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                return s
            if target_type == "hero":
                s.hero.hp = min(30, s.hero.hp + amount)

        elif action == "armor" and len(parts) >= 2:
            try:
                amount = int(parts[1])
            except ValueError:
                return s
            s.hero.armor += amount

        else:
            logger.debug("Unknown trigger effect: %s", effect)

        return s


# ===================================================================
# Module-level convenience functions
# ===================================================================

_default_dispatcher = TriggerDispatcher()


def dispatch_minion_played(state: GameState, minion: Minion, card) -> GameState:
    """Module-level shortcut for TriggerDispatcher().on_minion_played()."""
    return _default_dispatcher.on_minion_played(state, minion, card)


def dispatch_minion_dies(state: GameState, minion: Minion, position: int) -> GameState:
    """Module-level shortcut for TriggerDispatcher().on_minion_dies()."""
    return _default_dispatcher.on_minion_dies(state, minion, position)


def dispatch_turn_end(state: GameState) -> GameState:
    """Module-level shortcut for TriggerDispatcher().on_turn_end()."""
    return _default_dispatcher.on_turn_end(state)


def dispatch_turn_start(state: GameState) -> GameState:
    """Module-level shortcut for TriggerDispatcher().on_turn_start()."""
    return _default_dispatcher.on_turn_start(state)


# ===================================================================
# Self-test
# ===================================================================

if __name__ == "__main__":
    from analysis.search.game_state import GameState, Minion, HeroState, OpponentState
    from analysis.search.enchantment import Enchantment, apply_enchantment

    state = GameState()
    state.board.append(Minion(name="Raid Leader", attack=2, health=2, max_health=2))
    state.board.append(Minion(name="Wisp", attack=1, health=1, max_health=1))

    # Add an end_of_turn trigger that damages enemy hero for 2
    imp = Enchantment(
        enchantment_id="test_eot",
        trigger_type="end_of_turn",
        trigger_effect="damage:enemy_hero:2",
    )
    apply_enchantment(state.board[0], imp)

    dispatcher = TriggerDispatcher()
    state = dispatcher.on_turn_end(state)

    assert state.opponent.hero.hp == 28, f"Expected 28, got {state.opponent.hero.hp}"
    print(f"Enemy hero HP after end_of_turn trigger: {state.opponent.hero.hp}")

    # Test summon trigger
    state2 = GameState()
    state2.board.append(Minion(name="Knife Juggler", attack=2, health=2, max_health=2))
    juggler_trigger = Enchantment(
        enchantment_id="test_on_play",
        trigger_type="on_play",
        trigger_effect="damage:random_enemy:1",
    )
    apply_enchantment(state2.board[0], juggler_trigger)
    state2.opponent.board.append(Minion(name="Enemy", attack=1, health=3, max_health=3))

    new_minion = Minion(name="Wisp", attack=1, health=1, max_health=1)
    state2 = dispatcher.on_minion_played(state2, new_minion, None)
    print(f"Enemy HP after on_play trigger: {state2.opponent.board[0].health}")
    assert state2.opponent.board[0].health == 2  # 3 - 1 from knife juggler

    print("All self-tests passed!")

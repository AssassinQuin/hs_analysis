"""engine/trigger.py — Event-driven trigger system.

Central event bus for game state change notifications.
Dispatches game events (play, death, attack, etc.) to registered listeners.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from analysis.engine.state import GameState, Minion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Canonical event types for the trigger system."""
    ON_PLAY = "on_play"
    ON_DEATH = "on_death"
    ON_ATTACK = "on_attack"
    ON_DAMAGE = "on_damage"
    ON_TURN_START = "on_turn_start"
    ON_TURN_END = "on_turn_end"
    ON_SPELL_CAST = "on_spell_cast"
    ON_DRAW = "on_draw"
    ON_HEAL = "on_heal"
    ON_DISCARD = "on_discard"
    # Aliases matching old trigger_system names
    DEATHRATTLE = "deathrattle"
    START_OF_TURN = "start_of_turn"
    END_OF_TURN = "end_of_turn"
    ON_PLAY_PIRATE = "on_play_pirate"


# Type for listener functions
ListenerFn = Callable[..., Optional[GameState]]


# ---------------------------------------------------------------------------
# TriggerDispatcher
# ---------------------------------------------------------------------------

class TriggerDispatcher:
    """Central event bus that dispatches game events to registered listeners.

    Supports two registration modes:
    1. Functional listeners via register_listener(event_type, fn)
    2. Enchantment-based triggers on minions (legacy compatibility)

    All methods receive and return a GameState. Dispatches are wrapped in
    try/except for graceful degradation.
    """

    def __init__(self) -> None:
        self._listeners: Dict[str, List[ListenerFn]] = {}

    # ---------------------------------------------------------------
    # Listener registration
    # ---------------------------------------------------------------

    def register_listener(
        self,
        event_type: str,
        listener_fn: ListenerFn,
    ) -> None:
        """Register a listener function for an event type.

        Args:
            event_type: One of the EventType values or a custom string.
            listener_fn: Callable(state, **kwargs) -> GameState or None.
        """
        self._listeners.setdefault(event_type, []).append(listener_fn)

    def unregister_listener(self, event_type: str, listener_fn: ListenerFn) -> None:
        """Remove a listener function for an event type."""
        listeners = self._listeners.get(event_type, [])
        try:
            listeners.remove(listener_fn)
        except ValueError:
            pass

    def get_listeners(self, event_type: str) -> List[ListenerFn]:
        """Return listeners for an event type (empty list if none)."""
        return list(self._listeners.get(event_type, []))

    # ---------------------------------------------------------------
    # Core emit
    # ---------------------------------------------------------------

    def emit(
        self,
        state: GameState,
        event_type: str,
        **kwargs: Any,
    ) -> GameState:
        """Dispatch an event to all registered listeners.

        Args:
            state: Current game state.
            event_type: Event type string.
            **kwargs: Event-specific context (minion, target, amount, etc.)

        Returns:
            Possibly modified GameState.
        """
        s = state
        for listener_fn in self._listeners.get(event_type, []):
            try:
                result = listener_fn(s, **kwargs)
                if result is not None:
                    s = result
            except Exception as exc:
                logger.warning(
                    "Trigger listener failed for %s: %s",
                    event_type, exc,
                )
        return s

    # ---------------------------------------------------------------
    # Public event dispatchers — scan minions for enchantment triggers
    # ---------------------------------------------------------------

    def on_minion_played(self, state: GameState, minion: Minion, card=None) -> GameState:
        """Fire after a minion is played onto the board.

        Dispatches ON_PLAY event and scans for on_play triggers on other minions.
        """
        s = state
        # Emit to functional listeners
        s = self.emit(s, EventType.ON_PLAY, minion=minion, card=card)

        # Scan friendly board for enchantment triggers
        for m in s.board:
            if m is minion:
                continue
            s = self._dispatch_enchantment_triggers(s, m, "on_play")
        # Scan enemy board for opponent triggers
        for m in s.opponent.board:
            s = self._dispatch_enchantment_triggers(s, m, "on_play")
        return s

    def on_minion_dies(self, state: GameState, minion: Minion, position: int = 0) -> GameState:
        """Fire after a minion dies (health <= 0).

        Dispatches ON_DEATH event and deathrattle on the dying minion.
        """
        s = state
        s = self.emit(s, EventType.ON_DEATH, minion=minion, position=position)

        # Dying minion's own deathrattle
        s = self._dispatch_enchantment_triggers(s, minion, "deathrattle")
        # on_death triggers on surviving minions
        for m in s.board:
            if m is not minion:
                s = self._dispatch_enchantment_triggers(s, m, "on_death")
        for m in s.opponent.board:
            if m is not minion:
                s = self._dispatch_enchantment_triggers(s, m, "on_death")
        return s

    def on_turn_end(self, state: GameState) -> GameState:
        """Fire at end of turn.

        Dispatches ON_TURN_END event and ticks enchantment durations.
        """
        from analysis.engine.enchantment import _tick_entity_enchantments

        s = state
        s = self.emit(s, EventType.ON_TURN_END)

        for m in s.board:
            s = self._dispatch_enchantment_triggers(s, m, "end_of_turn")
            _tick_entity_enchantments(m)
        for m in s.opponent.board:
            _tick_entity_enchantments(m)
        return s

    def on_turn_start(self, state: GameState) -> GameState:
        """Fire at start of turn."""
        s = state
        s = self.emit(s, EventType.ON_TURN_START)

        for m in s.board:
            s = self._dispatch_enchantment_triggers(s, m, "start_of_turn")
        return s

    def on_attack(self, state: GameState, attacker: Minion, target=None) -> GameState:
        """Fire after an attack is resolved."""
        s = state
        s = self.emit(s, EventType.ON_ATTACK, attacker=attacker, target=target)

        s = self._dispatch_enchantment_triggers(s, attacker, "on_attack")
        if target is not None and isinstance(target, Minion):
            s = self._dispatch_enchantment_triggers(s, target, "on_damage")
        return s

    def on_spell_cast(self, state: GameState, card=None) -> GameState:
        """Fire after a spell is cast."""
        s = state
        s = self.emit(s, EventType.ON_SPELL_CAST, card=card)

        for m in s.board:
            s = self._dispatch_enchantment_triggers(s, m, "on_spell_cast")
        return s

    def on_damage_dealt(self, state: GameState, target=None, amount: int = 0) -> GameState:
        """Fire after damage is dealt to any target."""
        s = state
        s = self.emit(s, EventType.ON_DAMAGE, target=target, amount=amount)

        if isinstance(target, Minion):
            s = self._dispatch_enchantment_triggers(s, target, "on_damage")
        return s

    def on_heal(self, state: GameState, target=None, amount: int = 0) -> GameState:
        """Fire after healing."""
        s = state
        s = self.emit(s, EventType.ON_HEAL, target=target, amount=amount)

        if isinstance(target, Minion):
            s = self._dispatch_enchantment_triggers(s, target, "on_heal")
        return s

    def on_draw(self, state: GameState, card=None) -> GameState:
        """Fire after a card is drawn."""
        return self.emit(state, EventType.ON_DRAW, card=card)

    def on_discard(self, state: GameState, card=None) -> GameState:
        """Fire after a card is discarded."""
        return self.emit(state, EventType.ON_DISCARD, card=card)

    # ---------------------------------------------------------------
    # Death processing
    # ---------------------------------------------------------------

    def process_deaths(self, state: GameState) -> GameState:
        """Process all dead minions on both boards.

        Collects minions with health <= 0, fires ON_DEATH for each,
        then removes them from their respective boards.

        Returns:
            Modified GameState with dead minions removed.
        """
        s = state

        # Process friendly deaths
        dead_friendly = [(i, m) for i, m in enumerate(s.board) if m.health <= 0]
        for i, m in dead_friendly:
            s = self.on_minion_dies(s, m, position=i)
        s.board = [m for m in s.board if m.health > 0]

        # Process enemy deaths
        dead_enemy = [(i, m) for i, m in enumerate(s.opponent.board) if m.health <= 0]
        for i, m in dead_enemy:
            s = self.on_minion_dies(s, m, position=i)
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        return s

    # ---------------------------------------------------------------
    # Internal: enchantment-based trigger dispatch
    # ---------------------------------------------------------------

    def _dispatch_enchantment_triggers(
        self,
        state: GameState,
        minion: Minion,
        trigger_type: str,
    ) -> GameState:
        """Scan minion's enchantments for matching trigger_type and dispatch.

        For each matching enchantment, call _execute_effect with the
        trigger_effect string. Returns the (possibly modified) state.
        """
        s = state
        enchantments = getattr(minion, "enchantments", [])
        if not enchantments:
            return s

        for ench in list(enchantments):  # copy list to allow mutation
            if getattr(ench, "trigger_type", "") == trigger_type and getattr(ench, "trigger_effect", ""):
                try:
                    s = self._execute_effect(s, ench.trigger_effect, minion)
                except Exception as exc:
                    logger.warning(
                        "Trigger dispatch failed for %s/%s: %s",
                        getattr(minion, "name", "?"), ench.trigger_effect, exc,
                    )
        return s

    @staticmethod
    def _execute_effect(state: GameState, effect: str, source: Minion) -> GameState:
        """Execute a trigger effect string on the game state.

        Supported effect formats:
          damage:enemy_hero:N         — deal N damage to enemy hero
          damage:random_enemy:N       — deal N damage to random enemy minion
          damage:all_enemy:N          — deal N damage to all enemy minions
          armor:N                     — gain N armor
          heal:hero:N                 — heal friendly hero for N
          buff:friendly:A:H           — buff all friendly minions +A/+H
          summon:A:H                  — summon an A/H token
          draw:N                      — draw N cards (decrement deck_remaining)

        Graceful degradation: logs unknown effects and returns state unchanged.
        """
        s = state
        try:
            parts = effect.split(":")
            cmd = parts[0].lower()

            if cmd == "damage" and len(parts) >= 3:
                target = parts[1].lower()
                amount = int(parts[2])
                if target == "enemy_hero":
                    s.opponent.hero.hp = max(0, s.opponent.hero.hp - amount)
                elif target == "random_enemy":
                    enemies = [m for m in s.opponent.board if m.health > 0]
                    if enemies:
                        from analysis.engine.deterministic import DeterministicRNG
                        rng = DeterministicRNG.from_state(s)
                        victim = rng.choice(enemies)
                        if victim.has_divine_shield:
                            victim.has_divine_shield = False
                        else:
                            victim.health = max(0, victim.health - amount)
                elif target == "all_enemy":
                    for m in s.opponent.board:
                        if m.has_divine_shield:
                            m.has_divine_shield = False
                        else:
                            m.health = max(0, m.health - amount)
                else:
                    logger.debug("Unknown damage target: %s", target)

            elif cmd == "armor" and len(parts) >= 2:
                amount = int(parts[1])
                s.hero.armor = getattr(s.hero, 'armor', 0) + amount

            elif cmd == "heal" and len(parts) >= 3:
                target = parts[1].lower()
                amount = int(parts[2])
                if target == "hero":
                    s.hero.hp = min(
                        getattr(s.hero, 'max_hp', 30),
                        s.hero.hp + amount,
                    )

            elif cmd == "buff" and len(parts) >= 3:
                target = parts[1].lower()
                atk_bonus = int(parts[2]) if len(parts) > 2 else 0
                hp_bonus = int(parts[3]) if len(parts) > 3 else 0
                minions = []
                if target == "friendly":
                    minions = s.board
                elif target == "self":
                    minions = [source]
                for m in minions:
                    m.attack = max(0, m.attack + atk_bonus)
                    if hp_bonus != 0:
                        m.health = max(0, m.health + hp_bonus)
                        m.max_health = max(1, m.max_health + hp_bonus)

            elif cmd == "summon" and len(parts) >= 3:
                atk = int(parts[1])
                hp = int(parts[2])
                token = Minion(name="Token", attack=atk, health=hp, max_health=hp)
                if len(s.board) < 7:
                    s.board.append(token)

            elif cmd == "draw" and len(parts) >= 2:
                count = int(parts[1])
                s.deck_remaining = max(0, getattr(s, 'deck_remaining', 0) - count)

            else:
                logger.debug("Unknown trigger effect: %s", effect)
        except Exception as exc:
            logger.warning("Effect execution failed for '%s': %s", effect, exc)

        return s


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_dispatcher = TriggerDispatcher()


def get_dispatcher() -> TriggerDispatcher:
    """Return the default global TriggerDispatcher instance."""
    return _default_dispatcher

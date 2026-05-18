#!/usr/bin/env python3
"""battlecry.py — Battlecry effect dispatcher for Hearthstone AI.

Parses card text for battlecry effects and applies them to GameState.
Uses EffectParser from abilities for text parsing and executor primitives
for damage/heal/silence application.

Orchestration layer (Layer 3): handles battlecry-specific logic like
Brann doubling, target selection, and weapon equip. Delegates effect
execution to abilities/executor primitives.
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple

from analysis.card.engine.state import GameState, Minion, HeroState
from analysis.card.models.card import Card
from analysis.evaluators.composite import target_selection_eval
from analysis.effects.parser.legacy_adapter import EffectParser
from analysis.effects.primitives.damage import (
    apply_damage_to_hero,
    apply_damage_to_minion,
)
from analysis.effects.primitives.modify import (
    apply_silence_to_minion,
    apply_keyword,
)

logger = logging.getLogger(__name__)


# ===================================================================
# Battlecry text extraction
# ===================================================================

_BATTLECRY_PATTERN_EN = re.compile(r"Battlecry[：:]\s*(.+?)(?:[,.]|$)", re.DOTALL | re.IGNORECASE)
_BATTLECRY_PATTERN_ZH = re.compile(r"战吼[：:]\s*(.+)")

_FREEZE_EN = re.compile(r"Freeze\s+(?:a|an|the)?\s*(?:enemy|minion)", re.IGNORECASE)
_SILENCE_EN = re.compile(r"Silence\s+(?:a|an|the)?\s*(?:enemy|minion)", re.IGNORECASE)
_DIVINE_SHIELD_EN = re.compile(r"Give.*?Divine\s+Shield", re.IGNORECASE)
_TAUNT_EN = re.compile(r"Give.*?Taunt", re.IGNORECASE)
_RUSH_EN = re.compile(r"Give.*?Rush", re.IGNORECASE)
_DISCOVER_EN = re.compile(r"Discover\s+(?:a\s+)?", re.IGNORECASE)

_BATTLECRY_CHECKS = [
    ('freeze_target', lambda t: bool(_FREEZE_EN.search(t))),
    ('silence', lambda t: bool(_SILENCE_EN.search(t))),
    ('give_divine_shield', lambda t: bool(_DIVINE_SHIELD_EN.search(t))),
    ('give_taunt', lambda t: bool(_TAUNT_EN.search(t))),
    ('give_rush', lambda t: bool(_RUSH_EN.search(t))),
    ('discover', lambda t: bool(_DISCOVER_EN.search(t))),
]


# ===================================================================
# BattlecryDispatcher
# ===================================================================

class BattlecryDispatcher:
    """Parse and apply battlecry effects from card text.

    Workflow:
    1. Extract battlecry text from card.text using _BATTLECRY_PATTERN
    2. Parse effects using EffectParser (from spell_simulator)
    3. Apply each effect using executor primitives with target selection
    4. For targeted effects, pick the best target via greedy evaluation
    """

    def dispatch(self, state: GameState, card: Card, minion: Minion) -> GameState:
        card_text = getattr(card, 'text', '') or ''
        if not card_text:
            return state

        bc_match = _BATTLECRY_PATTERN_EN.search(card_text) or _BATTLECRY_PATTERN_ZH.search(card_text)
        if not bc_match:
            return state

        bc_text = bc_match.group(1).strip()
        if not bc_text:
            return state

        mechanics = set(getattr(card, 'mechanics', []) or [])
        if 'BATTLECRY' not in mechanics:
            pass

        s = state
        s = self._apply_battlecry_effects(s, bc_text, card, minion)

        # Brann Bronzebeard / Baron Rivendare aura: if any friendly minion
        # doubles battlecry triggers, apply effects a second time
        if self._has_battlecry_doubler(s, minion):
            s = self._apply_battlecry_effects(s, bc_text, card, minion)

        return s

    @staticmethod
    def _has_battlecry_doubler(state: GameState, played_minion: Minion) -> bool:
        for m in state.board:
            if m is played_minion:
                continue
            name = (getattr(m, 'name', '') or '').lower()
            if 'brann' in name:
                return True
            for ench in getattr(m, 'enchantments', []) or []:
                etype = getattr(ench, 'trigger_effect', '') or ''
                if 'double_battlecry' in etype:
                    return True
        return False

    # ---------------------------------------------------------------
    # Effect application
    # ---------------------------------------------------------------

    def _apply_battlecry_effects(
        self,
        state: GameState,
        bc_text: str,
        card: Card,
        minion: Minion,
    ) -> GameState:
        """Parse and apply all effects from battlecry text."""
        s = state

        # Parse standard effects using EffectParser
        # Pass card so DB-backed parsing works for real cards (with card_id)
        effects = EffectParser.parse(bc_text, card=card)

        for effect_type, params in effects:
            try:
                s = self._apply_single_effect(s, effect_type, params, minion)
            except Exception as exc:
                logger.warning(
                    "Battlecry effect failed: %s(%s) — %s",
                    effect_type, params, exc,
                )

        # Check for extra battlecry-specific effects
        s = self._apply_extra_effects(s, bc_text, minion)

        return s

    def _apply_single_effect(
        self,
        state: GameState,
        effect_type: str,
        params,
        source_minion: Minion,
    ) -> GameState:
        """Apply a single parsed effect using executor primitives."""
        s = state

        if effect_type == 'direct_damage':
            amount = params
            spell_power_bonus = sum(m.spell_power for m in state.board)
            amount += spell_power_bonus
            target = self._pick_damage_target(s, amount=amount)
            self._apply_damage_to_target(s, target, amount)

        elif effect_type == 'random_damage':
            amount = params
            apply_damage_to_hero(s.opponent.hero, amount)

        elif effect_type == 'aoe_damage':
            amount = params
            for m in s.opponent.board:
                apply_damage_to_minion(m, amount)

        elif effect_type == 'draw':
            count = params
            for _ in range(count):
                if s.deck_remaining > 0:
                    s.deck_remaining -= 1

        elif effect_type == 'summon_stats':
            atk, hp = params
            if len(s.board) < 7:
                s.board.append(Minion(
                    attack=atk, health=hp, max_health=hp,
                    name="Token", can_attack=False,
                ))

        elif effect_type == 'summon':
            if len(s.board) < 7:
                s.board.append(Minion(
                    attack=1, health=1, max_health=1,
                    name="Token", can_attack=False,
                ))

        elif effect_type == 'heal':
            amount = params
            target = self._pick_heal_target(s)
            if target == 'friendly_hero':
                s.hero.hp = min(s.hero.hp + amount, s.hero.max_hp)
            elif target.startswith('friendly_minion:'):
                idx = int(target.split(':')[1])
                if idx < len(s.board):
                    m = s.board[idx]
                    m.health = min(m.health + amount, m.max_health)

        elif effect_type == 'armor':
            s.hero.armor += params

        elif effect_type == 'buff_atk':
            amount = params
            idx = self._find_minion_index(s, source_minion)
            if idx >= 0:
                s.board[idx].attack += amount

        elif effect_type == 'destroy':
            target_idx = self._pick_destroy_target(s)
            if target_idx is not None:
                s.opponent.board.pop(target_idx)

        return s

    @staticmethod
    def _apply_damage_to_target(state: GameState, target: str, amount: int) -> None:
        """Apply damage to a target resolved as string identifier."""
        if target == 'enemy_hero':
            apply_damage_to_hero(state.opponent.hero, amount)
        elif target == 'friendly_hero':
            apply_damage_to_hero(state.hero, amount)
        elif target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if idx < len(state.opponent.board):
                apply_damage_to_minion(state.opponent.board[idx], amount)
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if idx < len(state.board):
                apply_damage_to_minion(state.board[idx], amount)

    def _apply_extra_effects(
        self,
        state: GameState,
        bc_text: str,
        minion: Minion,
    ) -> GameState:
        """Apply battlecry-specific effects using executor primitives."""
        s = state

        if _FREEZE_EN.search(bc_text):
            if s.opponent.board:
                target = self._pick_damage_target(s)
                if target.startswith('enemy_minion:'):
                    idx = int(target.split(':')[1])
                    s.opponent.board[idx].frozen_until_next_turn = True

        if _DIVINE_SHIELD_EN.search(bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                apply_keyword(s.board[idx], 'DIVINE_SHIELD')

        if _TAUNT_EN.search(bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                apply_keyword(s.board[idx], 'TAUNT')

        if _RUSH_EN.search(bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                apply_keyword(s.board[idx], 'RUSH')

        if _SILENCE_EN.search(bc_text):
            if s.opponent.board:
                target_idx = self._pick_destroy_target(s)
                if target_idx is not None:
                    apply_silence_to_minion(s.opponent.board[target_idx])

        if _DISCOVER_EN.search(bc_text):
            try:
                from analysis.search.discover import resolve_discover
                hero_class = getattr(s, 'hero', None)
                if hero_class:
                    hero_class = getattr(hero_class, 'hero_class', '') or ''
                else:
                    hero_class = ''
                s = resolve_discover(s, bc_text, hero_class)
            except (ImportError, ValueError, TypeError, KeyError):
                pass

        s = self._apply_equip_weapon(s, bc_text)

        return s

    # ---------------------------------------------------------------
    # Equip weapon from battlecry
    # ---------------------------------------------------------------

    _EQUIP_WEAPON_EN = re.compile(r'Equip\s+a\s+(\d+)/(\d+)', re.IGNORECASE)

    def _apply_equip_weapon(self, state: GameState, bc_text: str) -> GameState:
        """Handle battlecry weapon equip effects.

        Pattern: "Equip a 2/2 Sword"
        """
        m = self._EQUIP_WEAPON_EN.search(bc_text)
        if not m:
            return state

        atk = int(m.group(1))
        dur = int(m.group(2))

        # Check for race-holding condition in English text
        race_holding = re.search(
            r"if\s+you(?:'re)?\s+(?:holding\s+a|have\s+a)\s+(\w+)",
            bc_text, re.IGNORECASE,
        )
        if race_holding:
            race_name = race_holding.group(1).upper()
            has_race = any(
                getattr(h, 'race', '').upper() == race_name or
                race_name in [r.upper() for r in (getattr(h, 'races', None) or [])]
                for h in state.hand
            )
            if not has_race:
                return state

        from analysis.card.engine.state import Weapon
        state.hero.weapon = Weapon(attack=atk, health=dur, name="BattlecryWeapon")
        return state

    # ---------------------------------------------------------------
    # Target selection helpers
    # ---------------------------------------------------------------

    def _select_best_target_exhaustive(
        self,
        state: GameState,
        targets: list[tuple[str, int, int]],  # (target_id, ...)
        effect_fn,
    ) -> str | None:
        """Exhaustive target selection: try each, evaluate, pick best.

        Args:
            state: current game state
            targets: list of (target_id, ...) tuples
            effect_fn: function(state, target_id) -> state that applies the effect

        Returns:
            best target_id or None
        """
        if not targets:
            return None
        if len(targets) == 1:
            return targets[0]

        best_score = float('-inf')
        best_target = targets[0]

        for target_id in targets:
            try:
                sim = state.copy()
                sim = effect_fn(sim, target_id)
                score = target_selection_eval(sim)
                # Tiebreaker: prefer minion over hero, higher attack wins
                tiebreaker = 0.0
                if target_id.startswith('enemy_minion:'):
                    idx = int(target_id.split(':')[1])
                    if idx < len(state.opponent.board):
                        tiebreaker = state.opponent.board[idx].attack * 0.01
                if score + tiebreaker > best_score:
                    best_score = score + tiebreaker
                    best_target = target_id
            except (ValueError, TypeError, IndexError):
                continue  # fallback: skip failed evaluation

        return best_target

    def _pick_damage_target(self, state: GameState, amount: int = 1) -> str:
        """Pick the best target for damage using exhaustive evaluation.

        Tries: enemy hero + each enemy minion. Picks the one that yields
        the best state after damage is applied. Uses actual damage amount
        for the probe so removal (kills) are properly valued.

        Args:
            state: current game state
            amount: damage amount to use in the evaluation probe
        """
        candidates = ['enemy_hero']
        for i in range(len(state.opponent.board)):
            candidates.append(f'enemy_minion:{i}')

        if len(candidates) <= 1:
            return candidates[0] if candidates else 'enemy_hero'

        def apply_dmg(s, target_id):
            if target_id == 'enemy_hero':
                s.opponent.hero.hp -= amount
            else:
                idx = int(target_id.split(':')[1])
                if idx < len(s.opponent.board):
                    s.opponent.board[idx].health -= amount
            return s

        return self._select_best_target_exhaustive(state, candidates, apply_dmg)


    def _pick_heal_target(self, state: GameState) -> str:
        """Pick the best target for healing: most-damaged friendly, or hero."""
        # Check hero first
        if state.hero.hp < 30:
            return 'friendly_hero'
        # Check friendly minions
        for i, m in enumerate(state.board):
            if m.health < m.max_health:
                return f'friendly_minion:{i}'
        return 'friendly_hero'

    def _pick_destroy_target(self, state: GameState) -> Optional[int]:
        """Pick the best enemy minion to destroy: highest attack."""
        if not state.opponent.board:
            return None
        return max(range(len(state.opponent.board)),
                   key=lambda i: state.opponent.board[i].attack)

    def _find_minion_index(self, state: GameState, minion: Minion) -> int:
        """Find a minion's index on the friendly board by identity."""
        for i, m in enumerate(state.board):
            if m is minion:
                return i
        return -1


# ===================================================================
# Module-level convenience
# ===================================================================

_default_dispatcher = BattlecryDispatcher()


def dispatch_battlecry(state: GameState, card: Card, minion: Minion) -> GameState:
    """Apply battlecry effects from card to state."""
    return _default_dispatcher.dispatch(state, card, minion)


def dispatch_battlecry_branches(
    state: GameState, card: Card, minion: Minion, k: int = 3,
) -> List[Tuple[GameState, float]]:
    """Return top-k battlecry branches as (state, probability) pairs.

    For non-discover battlecries, returns [(state, 1.0)].
    For discover battlecries, returns up to k branches with different
    discovered cards added to hand.
    """
    card_text = getattr(card, 'text', '') or ''
    has_discover = bool(_DISCOVER_EN.search(card_text))
    if not has_discover:
        result = _default_dispatcher.dispatch(state, card, minion)
        return [(result, 1.0)]

    bc_match = _BATTLECRY_PATTERN_EN.search(card_text)
    if not bc_match:
        result = _default_dispatcher.dispatch(state, card, minion)
        return [(result, 1.0)]

    bc_text = bc_match.group(1).strip()

    base_state = state.copy()
    mechanics = set(getattr(card, 'mechanics', []) or [])

    s = base_state
    s = _default_dispatcher._apply_battlecry_effects(s, bc_text, card, minion)

    if _default_dispatcher._has_battlecry_doubler(s, minion):
        s = _default_dispatcher._apply_battlecry_effects(s, bc_text, card, minion)

    try:
        from analysis.search.discover import resolve_discover_top_k
        hero_class = getattr(s, 'hero', None)
        if hero_class:
            hero_class = getattr(hero_class, 'hero_class', '') or ''
        else:
            hero_class = ''
        branches = resolve_discover_top_k(s, bc_text, hero_class, k=k)
        if len(branches) > 1:
            return branches
    except (ImportError, ValueError, TypeError, KeyError):
        pass

    return [(s, 1.0)]

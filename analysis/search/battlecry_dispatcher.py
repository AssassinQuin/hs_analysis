#!/usr/bin/env python3
"""battlecry_dispatcher.py — Battlecry effect dispatcher for Hearthstone AI.

Parses card text for battlecry (战吼) effects and applies them to GameState.
Reuses EffectParser and EffectApplier from spell_simulator for regex matching
and effect application.

Usage:
    python3 -m hs_analysis.search.battlecry_dispatcher          # run self-test
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple

from analysis.search.game_state import GameState, Minion, HeroState
from analysis.models.card import Card
from analysis.utils.spell_simulator import EffectParser, EffectApplier

logger = logging.getLogger(__name__)


# ===================================================================
# Battlecry text extraction
# ===================================================================

# Pattern to extract battlecry text: "战吼：..." or "战吼:..."
_BATTLECRY_PATTERN_EN = re.compile(r"Battlecry[：:]\s*(.+?)(?:[,.]|$)", re.DOTALL | re.IGNORECASE)
_BATTLECRY_PATTERN = re.compile(r'战吼[：:]\s*(.+?)(?:，|$)', re.DOTALL)

_DESTROY_MINION_CN = re.compile(r'消灭.*?随从')
_FREEZE_EN = re.compile(r"Freeze\s+(?:a|an|the)?\s*(?:enemy|minion)", re.IGNORECASE)
_SILENCE_EN = re.compile(r"Silence\s+(?:a|an|the)?\s*(?:enemy|minion)", re.IGNORECASE)
_DIVINE_SHIELD_EN = re.compile(r"Give.*?Divine\s+Shield", re.IGNORECASE)
_TAUNT_EN = re.compile(r"Give.*?Taunt", re.IGNORECASE)
_RUSH_EN = re.compile(r"Give.*?Rush", re.IGNORECASE)
_DISCOVER_EN = re.compile(r"Discover\s+(?:a\s+)?", re.IGNORECASE)

_BATTLECRY_CHECKS = [
    ('destroy_minion', lambda t: bool(_DESTROY_MINION_CN.search(t))),
    ('freeze_target', lambda t: bool(_FREEZE_EN.search(t)) or '冻结' in t),
    ('silence', lambda t: bool(_SILENCE_EN.search(t)) or '沉默' in t),
    ('give_divine_shield', lambda t: bool(_DIVINE_SHIELD_EN.search(t)) or bool(re.search(r'获得?圣盾', t))),
    ('give_taunt', lambda t: bool(_TAUNT_EN.search(t)) or bool(re.search(r'获得?嘲讽', t))),
    ('give_charge', lambda t: bool(re.search(r'获得?冲锋', t))),
    ('give_rush', lambda t: bool(_RUSH_EN.search(t)) or bool(re.search(r'获得?突袭', t))),
    ('discover', lambda t: bool(_DISCOVER_EN.search(t)) or '发现' in t),
    ('copy_minion', lambda t: bool(re.search(r'复制.*?随从', t))),
]


# ===================================================================
# BattlecryDispatcher
# ===================================================================

class BattlecryDispatcher:
    """Parse and apply battlecry effects from card text.

    Workflow:
    1. Extract battlecry text from card.text using _BATTLECRY_PATTERN
    2. Parse effects using EffectParser (from spell_simulator)
    3. Apply each effect using EffectApplier with target selection
    4. For targeted effects, pick the best target via greedy evaluation
    """

    def dispatch(self, state: GameState, card: Card, minion: Minion) -> GameState:
        card_text = getattr(card, 'text', '') or ''
        if not card_text:
            return state

        bc_match = _BATTLECRY_PATTERN_EN.search(card_text)
        if not bc_match:
            bc_match = _BATTLECRY_PATTERN.search(card_text)
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
            if 'brann' in name or '布莱恩' in name:
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

        # Parse standard effects using spell_simulator's EffectParser
        effects = EffectParser.parse(bc_text)

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
        """Apply a single parsed effect to the game state."""
        s = state

        if effect_type == 'direct_damage':
            amount = params
            spell_power_bonus = sum(m.spell_power for m in state.board)
            amount += spell_power_bonus
            target = self._pick_damage_target(s, amount=amount)
            s = EffectApplier.apply_damage(s, target, amount)

        elif effect_type == 'random_damage':
            amount = params
            # Random damage → enemy hero (simplified)
            s = EffectApplier.apply_damage(s, 'enemy_hero', amount)

        elif effect_type == 'aoe_damage':
            amount = params
            s = EffectApplier.apply_aoe(s, amount, side='enemy')

        elif effect_type == 'draw':
            count = params
            s = EffectApplier.apply_draw(s, count)

        elif effect_type == 'summon_stats':
            atk, hp = params
            s = EffectApplier.apply_summon(s, atk, hp)

        elif effect_type == 'summon':
            # Generic summon: 1/1 token
            s = EffectApplier.apply_summon(s, 1, 1)

        elif effect_type == 'heal':
            amount = params
            target = self._pick_heal_target(s)
            s = EffectApplier.apply_heal(s, target, amount)

        elif effect_type == 'armor':
            amount = params
            s.hero.armor += amount

        elif effect_type == 'buff_atk':
            amount = params
            # Buff self (the just-played minion)
            idx = self._find_minion_index(s, source_minion)
            if idx >= 0:
                s = EffectApplier.apply_buff(s, f'friendly_minion:{idx}', amount)

        elif effect_type == 'destroy':
            # Destroy best enemy minion
            target_idx = self._pick_destroy_target(s)
            if target_idx is not None:
                s.opponent.board.pop(target_idx)

        return s

    def _apply_extra_effects(
        self,
        state: GameState,
        bc_text: str,
        minion: Minion,
    ) -> GameState:
        """Apply battlecry-specific effects not covered by spell_simulator."""
        s = state

        if _FREEZE_EN.search(bc_text) or '冻结' in bc_text:
            if s.opponent.board:
                target = self._pick_damage_target(s)
                if target.startswith('enemy_minion:'):
                    idx = int(target.split(':')[1])
                    s.opponent.board[idx].frozen_until_next_turn = True

        if _DIVINE_SHIELD_EN.search(bc_text) or re.search(r'获得?圣盾', bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                s.board[idx].has_divine_shield = True

        if _TAUNT_EN.search(bc_text) or re.search(r'获得?嘲讽', bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                s.board[idx].has_taunt = True

        if _RUSH_EN.search(bc_text) or re.search(r'获得?突袭', bc_text):
            idx = self._find_minion_index(s, minion)
            if idx >= 0:
                s.board[idx].has_rush = True

        if _SILENCE_EN.search(bc_text) or '沉默' in bc_text:
            if s.opponent.board:
                target_idx = self._pick_destroy_target(s)
                if target_idx is not None:
                    target = s.opponent.board[target_idx]
                    target.has_taunt = False
                    target.has_divine_shield = False
                    target.has_stealth = False
                    target.has_windfury = False
                    target.has_poisonous = False
                    target.has_rush = False
                    target.has_charge = False
                    target.enchantments = []

        if _DISCOVER_EN.search(bc_text) or '发现' in bc_text:
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

        return s

    # ---------------------------------------------------------------
    # Target selection helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _quick_eval(state: GameState) -> float:
        """Quick state evaluation for target selection.

        Heuristic: friendly board strength - enemy board strength + hero delta
        + removal bonus for dead enemy minions.
        """
        friendly_power = sum(m.attack + m.health for m in state.board if m.health > 0)
        enemy_power = 0
        dead_enemies = 0
        for m in state.opponent.board:
            if m.health <= 0:
                dead_enemies += 1
            else:
                enemy_power += m.attack + m.health
        removal_bonus = dead_enemies * 10  # kills are very valuable
        if state.opponent.hero.hp <= 0:
            return 1000  # lethal beats everything
        hero_delta = state.hero.hp - state.opponent.hero.hp
        return friendly_power - enemy_power + hero_delta + removal_bonus

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
                score = self._quick_eval(sim)
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
    has_discover = (
        _DISCOVER_EN.search(card_text) or '发现' in card_text
    )
    if not has_discover:
        result = _default_dispatcher.dispatch(state, card, minion)
        return [(result, 1.0)]

    bc_match = _BATTLECRY_PATTERN_EN.search(card_text)
    if not bc_match:
        bc_match = _BATTLECRY_PATTERN.search(card_text)
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


# ===================================================================
# Self-test
# ===================================================================

if __name__ == "__main__":
    from analysis.search.game_state import GameState, Minion, HeroState, OpponentState
    from analysis.models.card import Card

    state = GameState(hero=HeroState(hp=30), opponent=OpponentState(hero=HeroState(hp=30)))

    # Test 1: Battlecry damage
    state.opponent.board.append(Minion(name="Enemy", attack=5, health=5, max_health=5, owner="enemy"))
    dmg_card = Card(dbf_id=1, name="Fire Elemental", cost=4, card_type="MINION",
                    attack=3, health=3, text="战吼：造成3点伤害", mechanics=["BATTLECRY"])
    minion = Minion(name="Fire Elemental", attack=3, health=3, max_health=3)
    state.board.append(minion)

    state = dispatch_battlecry(state, dmg_card, minion)
    assert state.opponent.board[0].health == 2, f"Expected 2, got {state.opponent.board[0].health}"
    print(f"Test 1 PASS: enemy minion HP = {state.opponent.board[0].health}")

    # Test 2: No battlecry
    state2 = GameState()
    vanilla = Card(dbf_id=2, name="Yeti", cost=4, card_type="MINION",
                   attack=4, health=5, text="", mechanics=[])
    m2 = Minion(name="Yeti", attack=4, health=5, max_health=5)
    state2.board.append(m2)
    state2 = dispatch_battlecry(state2, vanilla, m2)
    print("Test 2 PASS: no crash on vanilla card")

    print("All self-tests passed!")

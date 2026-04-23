#!/usr/bin/env python3
"""spell_simulator.py — Spell Effect Simulator for Hearthstone AI.

Parses card text using regex patterns to extract effect types and parameters,
then applies those effects to GameState copies for simulation.

Usage:
    python3 -m hs_analysis.utils.spell_simulator          # run built-in self-test
"""

from __future__ import annotations

import copy
import sys
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from analysis.search.game_state import GameState, Minion, HeroState, ManaState, OpponentState, Weapon
from analysis.models.card import Card
from analysis.data.card_effects import get_effects, CardEffects


# ===================================================================
# EffectParser
# ===================================================================

class EffectParser:
    """Parse card effects using structured CardEffects data.

    Returns a list of (effect_type, params) tuples.
    """

    @staticmethod
    def parse(card_text: str, card: Card = None) -> List[Tuple[str, object]]:
        """Parse card effects from a Card object or text fallback.

        If a Card object is provided, uses structured fields via get_effects().
        Falls back to text-only parsing if no Card is given.
        """
        if card is not None:
            return EffectParser._from_card(card)
        if not card_text:
            return []
        return EffectParser._from_text_fallback(card_text)

    @staticmethod
    def _from_card(card: Card) -> List[Tuple[str, object]]:
        eff = get_effects(card)
        effects: List[Tuple[str, object]] = []

        if eff.aoe_damage > 0:
            effects.append(('aoe_damage', eff.aoe_damage))
        if eff.random_damage > 0:
            effects.append(('random_damage', eff.random_damage))
        elif eff.damage > 0:
            effects.append(('direct_damage', eff.damage))

        if eff.summon_attack > 0 and eff.summon_health > 0:
            effects.append(('summon_stats', (eff.summon_attack, eff.summon_health)))
        elif eff.has_summon:
            effects.append(('summon', True))

        if eff.draw > 0:
            effects.append(('draw', eff.draw))
        if eff.has_destroy:
            effects.append(('destroy', True))
        if eff.heal > 0:
            effects.append(('heal', eff.heal))
        if eff.armor > 0:
            effects.append(('armor', eff.armor))
        if eff.buff_attack > 0:
            if eff.buff_health > 0:
                effects.append(('hand_buff', (eff.buff_attack, eff.buff_health)))
            else:
                effects.append(('buff_atk', eff.buff_attack))
        if eff.discard > 0:
            effects.append(('discard', eff.discard))
        if eff.cost_reduce > 0:
            effects.append(('cost_reduce', eff.cost_reduce))

        return effects

    @staticmethod
    def _from_text_fallback(card_text: str) -> List[Tuple[str, object]]:
        """Minimal text fallback when no Card object is available."""
        from analysis.data.card_effects import (
            _AOE_CN, _AOE_EN, _RANDOM_DMG_CN, _RANDOM_DMG_EN,
            _DAMAGE_CN, _DAMAGE_EN, _DRAW_CN, _DRAW_EN,
            _SUMMON_STATS_CN, _SUMMON_STATS_EN, _HEAL_CN, _HEAL_EN,
            _ARMOR_CN, _ARMOR_EN, _BUFF_ATK_CN, _BUFF_ATK_EN,
            _HAND_BUFF_CN, _DISCARD_CN, _DISCARD_EN,
            _COST_REDUCE_CN, _COST_REDUCE_EN,
        )

        effects: List[Tuple[str, object]] = []
        matched_ranges: List[Tuple[int, int]] = []

        def _check(pattern, effect_name, extractor):
            m = pattern.search(card_text)
            if m:
                s = m.span()
                for rs in matched_ranges:
                    if s[0] < rs[1] and s[1] > rs[0]:
                        return
                effects.append((effect_name, extractor(m)))
                matched_ranges.append(s)

        _check(_AOE_CN, 'aoe_damage', lambda m: int(m.group(1)))
        _check(_AOE_EN, 'aoe_damage', lambda m: int(m.group(1)))
        _check(_RANDOM_DMG_CN, 'random_damage', lambda m: int(m.group(1)))
        _check(_RANDOM_DMG_EN, 'random_damage', lambda m: int(m.group(1)))
        _check(_DAMAGE_CN, 'direct_damage', lambda m: int(m.group(1)))
        _check(_DAMAGE_EN, 'direct_damage', lambda m: int(m.group(1)))
        _check(_SUMMON_STATS_CN, 'summon_stats', lambda m: (int(m.group(1)), int(m.group(2))))
        _check(_SUMMON_STATS_EN, 'summon_stats', lambda m: (int(m.group(1)), int(m.group(2))))
        has_summon_stats = any(t == 'summon_stats' for t, _ in effects)
        if not has_summon_stats:
            if "召唤" in card_text:
                effects.append(('summon', True))
            elif "Summon" in card_text:
                effects.append(('summon', True))
        _check(_DRAW_CN, 'draw', lambda m: int(m.group(1)))
        _check(_DRAW_EN, 'draw', lambda m: int(m.group(1)))
        if "消灭" in card_text or "Destroy" in card_text:
            effects.append(('destroy', True))
        _check(_HEAL_CN, 'heal', lambda m: int(m.group(1)))
        _check(_HEAL_EN, 'heal', lambda m: int(m.group(1)))
        _check(_ARMOR_CN, 'armor', lambda m: int(m.group(1)))
        _check(_ARMOR_EN, 'armor', lambda m: int(m.group(1)))
        _check(_BUFF_ATK_CN, 'buff_atk', lambda m: int(m.group(1)))
        _check(_BUFF_ATK_EN, 'buff_atk', lambda m: int(m.group(1)))
        _check(_HAND_BUFF_CN, 'hand_buff', lambda m: (int(m.group(1)), int(m.group(2))))
        _check(_DISCARD_CN, 'discard', lambda m: int(m.group(1)))
        _check(_DISCARD_EN, 'discard', lambda m: int(m.group(1)))
        _check(_COST_REDUCE_CN, 'cost_reduce', lambda m: int(m.group(1)))
        _check(_COST_REDUCE_EN, 'cost_reduce', lambda m: int(m.group(1)))

        return effects


# ===================================================================
# EffectApplier
# ===================================================================

class EffectApplier:
    """Apply parsed spell effects to GameState copies.

    All methods operate on state copies and never mutate originals.
    """

    @staticmethod
    def apply_damage(
        state: GameState,
        target: str,
        amount: int,
    ) -> GameState:
        """Apply *amount* damage to a target.

        target: 'enemy_hero', 'enemy_minion:N', 'friendly_hero', 'friendly_minion:N'
        Respects immune: if target is immune, no damage is dealt.
        """
        s = state  # already a copy from caller
        if target == 'enemy_hero':
            if s.opponent.hero.is_immune:
                return s
            # Damage goes through armor first
            if s.opponent.hero.armor >= amount:
                s.opponent.hero.armor -= amount
            else:
                remaining = amount - s.opponent.hero.armor
                s.opponent.hero.armor = 0
                s.opponent.hero.hp -= remaining
        elif target == 'friendly_hero':
            if s.hero.is_immune:
                return s
            if s.hero.armor >= amount:
                s.hero.armor -= amount
            else:
                remaining = amount - s.hero.armor
                s.hero.armor = 0
                s.hero.hp -= remaining
        elif target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.opponent.board):
                minion = s.opponent.board[idx]
                if minion.has_immune:
                    return s
                if minion.has_divine_shield:
                    minion.has_divine_shield = False
                else:
                    minion.health -= amount
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.board):
                minion = s.board[idx]
                if minion.has_immune:
                    return s
                if minion.has_divine_shield:
                    minion.has_divine_shield = False
                else:
                    minion.health -= amount
        return s

    @staticmethod
    def apply_heal(
        state: GameState,
        target: str,
        amount: int,
    ) -> GameState:
        """Heal *target* by *amount*, capped at max_health."""
        s = state
        if target == 'enemy_hero':
            s.opponent.hero.hp = min(
                s.opponent.hero.hp + amount, s.opponent.hero.max_hp
            )
        elif target == 'friendly_hero':
            s.hero.hp = min(s.hero.hp + amount, s.hero.max_hp)
        elif target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.opponent.board):
                m = s.opponent.board[idx]
                m.health = min(m.health + amount, m.max_health)
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.board):
                m = s.board[idx]
                m.health = min(m.health + amount, m.max_health)
        return s

    @staticmethod
    def apply_draw(state: GameState, count: int) -> GameState:
        """Add *count* dummy cards to hand (simulates drawing).

        Handles overdraw: if hand would exceed 10, excess cards are burned.
        """
        s = state
        for _ in range(count):
            s.deck_remaining = max(0, s.deck_remaining - 1)
            if len(s.hand) >= 10:
                pass  # overdraw: card is burned
            else:
                s.hand.append(Card(
                    dbf_id=0,
                    name="Drawn Card",
                    cost=0,
                    card_type="SPELL",
                ))
        return s

    @staticmethod
    def apply_summon(
        state: GameState,
        attack: int,
        health: int,
        position: int = -1,
    ) -> GameState:
        """Summon a generic minion with given stats."""
        s = state
        if s.board_full():
            return s
        new_minion = Minion(
            name="Summoned Minion",
            attack=attack,
            health=health,
            max_health=health,
            cost=0,
            can_attack=False,
            owner="friendly",
        )
        if position < 0 or position >= len(s.board):
            s.board.append(new_minion)
        else:
            s.board.insert(position, new_minion)
        return s

    @staticmethod
    def apply_buff(
        state: GameState,
        target: str,
        attack_delta: int,
        health_delta: int = 0,
    ) -> GameState:
        """Buff a minion's attack and/or health."""
        s = state
        if target == 'all_friendly':
            for m in s.board:
                m.attack += attack_delta
                m.health += health_delta
                m.max_health += health_delta
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.board):
                m = s.board[idx]
                m.attack += attack_delta
                m.health += health_delta
                m.max_health += health_delta
        elif target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.opponent.board):
                m = s.opponent.board[idx]
                m.attack += attack_delta
                m.health += health_delta
                m.max_health += health_delta
        return s

    @staticmethod
    def apply_aoe(
        state: GameState,
        amount: int,
        side: str = 'enemy',
    ) -> GameState:
        """Apply *amount* damage to all minions on one side.

        side: 'enemy' or 'friendly'
        """
        s = state
        if side == 'enemy':
            for m in s.opponent.board:
                if m.has_divine_shield:
                    m.has_divine_shield = False
                else:
                    m.health -= amount
        elif side == 'friendly':
            for m in s.board:
                if m.has_divine_shield:
                    m.has_divine_shield = False
                else:
                    m.health -= amount
        return s

    @staticmethod
    def apply_weapon(
        state: GameState,
        attack: int,
        durability: int,
    ) -> GameState:
        """Equip a weapon to the friendly hero."""
        s = state
        s.hero.weapon = Weapon(attack=attack, health=durability, name="Simulated Weapon")
        return s

    @staticmethod
    def apply_armor(state: GameState, amount: int) -> GameState:
        """Increase hero armor by *amount*."""
        s = state
        s.hero.armor += amount
        return s

    @staticmethod
    def apply_destroy(
        state: GameState,
        target: str,
    ) -> GameState:
        """Destroy (remove) a target minion."""
        s = state
        if target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.opponent.board):
                s.opponent.board.pop(idx)
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.board):
                s.board.pop(idx)
        return s

    @staticmethod
    def apply_silence(
        state: GameState,
        target: str,
    ) -> GameState:
        """Silence a minion: clear all keyword abilities and enchantments."""
        s = state
        minion = None
        if target.startswith('enemy_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.opponent.board):
                minion = s.opponent.board[idx]
        elif target.startswith('friendly_minion:'):
            idx = int(target.split(':')[1])
            if 0 <= idx < len(s.board):
                minion = s.board[idx]
        if minion is not None:
            minion.has_divine_shield = False
            minion.has_taunt = False
            minion.has_stealth = False
            minion.has_windfury = False
            minion.has_rush = False
            minion.has_charge = False
            minion.has_poisonous = False
            minion.enchantments = []
        return s


# ===================================================================
# resolve_effects — Main entry point
# ===================================================================

def _pick_target_for_damage(state: GameState, amount: int = 1) -> str:
    """Pick the best target for a damage effect using exhaustive evaluation.

    Tries each enemy minion + enemy hero, applies damage, evaluates state.
    Picks the target that yields the best outcome (kills valued via removal bonus).

    Args:
        state: current game state
        amount: damage amount to use in the evaluation probe
    """
    candidates = ['enemy_hero']
    for i in range(len(state.opponent.board)):
        candidates.append(f'enemy_minion:{i}')

    if len(candidates) <= 1:
        return candidates[0] if candidates else 'enemy_hero'

    best_score = float('-inf')
    best_target = candidates[0]

    for target_id in candidates:
        try:
            sim = state.copy()
            if target_id == 'enemy_hero':
                sim.opponent.hero.hp -= amount
            else:
                idx = int(target_id.split(':')[1])
                if idx < len(sim.opponent.board):
                    sim.opponent.board[idx].health -= amount
            score = _quick_eval(sim)
            # Tiebreaker: prefer minions, higher attack wins
            tiebreaker = 0.0
            if target_id.startswith('enemy_minion:'):
                idx = int(target_id.split(':')[1])
                if idx < len(state.opponent.board):
                    tiebreaker = state.opponent.board[idx].attack * 0.01
            if score + tiebreaker > best_score:
                best_score = score + tiebreaker
                best_target = target_id
        except Exception:
            continue

    return best_target


def _quick_eval(state: GameState) -> float:
    """Quick state evaluation for target selection.

    Heuristic: friendly power - enemy power + hero delta + removal bonus.
    """
    friendly_power = sum(m.attack + m.health for m in state.board if m.health > 0)
    enemy_power = 0
    dead_enemies = 0
    for m in state.opponent.board:
        if m.health <= 0:
            dead_enemies += 1
        else:
            enemy_power += m.attack + m.health
    removal_bonus = dead_enemies * 10
    if state.opponent.hero.hp <= 0:
        return 1000  # lethal beats everything
    hero_delta = state.hero.hp - state.opponent.hero.hp
    return friendly_power - enemy_power + hero_delta + removal_bonus


def _resolve_deaths(state: GameState) -> GameState:
    """Remove dead minions from both boards."""
    state.opponent.board = [m for m in state.opponent.board if m.health > 0]
    state.board = [m for m in state.board if m.health > 0]
    return state


def _resolve_target_from_index(state: GameState, target_index: int) -> str:
    """Convert numeric target_index to string target format.

    Args:
        state: current game state
        target_index: 0 = enemy hero, 1..N = enemy minion (1-based)

    Returns:
        Target string like 'enemy_hero' or 'enemy_minion:N'
    """
    if target_index == 0:
        return 'enemy_hero'
    elif target_index > 0 and target_index <= len(state.opponent.board):
        return f'enemy_minion:{target_index - 1}'
    return 'enemy_hero'


def resolve_effects(state: GameState, card: Card, target_index: int = -1) -> GameState:
    """Parse card effects and apply them to a state copy.

    Args:
        state: current game state
        card: the card being played
        target_index: if >= 0, use this target instead of greedy selection.
            0 = enemy hero, 1..N = enemy minion index (1-based)

    Returns the modified state copy. The original state is never mutated.
    """
    s = state.copy()

    effects = EffectParser.parse(card.text or "", card=card)

    if not effects:
        return s

    # Calculate spell power bonus from friendly minions
    spell_power_bonus = sum(m.spell_power for m in state.board)

    applier = EffectApplier()

    has_lifesteal = 'LIFESTEAL' in set(getattr(card, 'mechanics', []) or [])

    for effect_type, params in effects:
        if effect_type == 'direct_damage':
            amount = params + spell_power_bonus
            if target_index >= 0:
                target = _resolve_target_from_index(s, target_index)
            else:
                target = _pick_target_for_damage(s, amount=amount)
            s = applier.apply_damage(s, target, amount)
            if has_lifesteal:
                s.hero.hp = min(30, s.hero.hp + amount)

        elif effect_type == 'random_damage':
            amount = params + spell_power_bonus
            if target_index >= 0:
                target = _resolve_target_from_index(s, target_index)
            else:
                target = _pick_target_for_damage(s, amount=amount)
            s = applier.apply_damage(s, target, amount)
            if has_lifesteal:
                s.hero.hp = min(30, s.hero.hp + amount)

        elif effect_type == 'aoe_damage':
            amount = params + spell_power_bonus
            s = applier.apply_aoe(s, amount, side='enemy')

        elif effect_type == 'draw':
            count = params
            s = applier.apply_draw(s, count)

        elif effect_type == 'summon_stats':
            attack, health = params
            s = applier.apply_summon(s, attack, health)

        elif effect_type == 'summon':
            # Generic summon — no stats available; skip or summon 1/1
            s = applier.apply_summon(s, 1, 1)

        elif effect_type == 'destroy':
            # Destroy the first enemy minion if any
            if s.opponent.board:
                s = applier.apply_destroy(s, 'enemy_minion:0')

        elif effect_type == 'heal':
            amount = params
            # Heal friendly hero
            s = applier.apply_heal(s, 'friendly_hero', amount)

        elif effect_type == 'armor':
            amount = params
            s = applier.apply_armor(s, amount)

        elif effect_type == 'buff_atk':
            amount = params
            # Buff all friendly minions
            s = applier.apply_buff(s, 'all_friendly', amount, 0)

        elif effect_type == 'discard':
            count = params
            for _ in range(min(count, len(s.hand))):
                if s.hand:
                    s.hand.pop()

        elif effect_type == 'hand_buff':
            atk_delta, hp_delta = params
            for c in s.hand:
                if hasattr(c, 'attack'):
                    c.attack += atk_delta
                if hasattr(c, 'health'):
                    c.health += hp_delta

        elif effect_type == 'cost_reduce':
            reduction = params
            for c in s.hand:
                if hasattr(c, 'cost'):
                    c.cost = max(0, c.cost - reduction)

    # Resolve deaths after all effects are applied
    s = _resolve_deaths(s)

    return s


# ===================================================================
# Self-test / demo
# ===================================================================

def _build_test_state() -> GameState:
    """Build a sample game state for testing."""
    return GameState(
        hero=HeroState(hp=25, armor=0, hero_class="MAGE"),
        mana=ManaState(available=10, max_mana=10),
        board=[
            Minion(
                dbf_id=1001,
                name="Fire Fly",
                attack=2,
                health=1,
                max_health=1,
                cost=1,
                can_attack=True,
                owner="friendly",
            ),
        ],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30, armor=0),
            board=[
                Minion(
                    dbf_id=3001,
                    name="Voidwalker",
                    attack=1,
                    health=3,
                    max_health=3,
                    has_taunt=True,
                    owner="enemy",
                ),
                Minion(
                    dbf_id=3002,
                    name="Murloc Raider",
                    attack=2,
                    health=1,
                    max_health=1,
                    owner="enemy",
                ),
            ],
            hand_count=5,
        ),
        turn_number=8,
    )


if __name__ == "__main__":
    errors: list[str] = []

    # ---- Test 1: EffectParser basic parsing ----
    effects = EffectParser.parse("造成 6 点伤害")
    if not effects or effects[0][0] != 'direct_damage' or effects[0][1] != 6:
        errors.append(f"FAIL: direct_damage parse: got {effects}")
    else:
        print(f"✓ direct_damage parse: {effects}")

    effects = EffectParser.parse("抽 2 张牌")
    if not effects or effects[0][0] != 'draw' or effects[0][1] != 2:
        errors.append(f"FAIL: draw parse: got {effects}")
    else:
        print(f"✓ draw parse: {effects}")

    effects = EffectParser.parse("对所有随从造成 2 点伤害")
    if not effects or effects[0][0] != 'aoe_damage' or effects[0][1] != 2:
        errors.append(f"FAIL: aoe_damage parse: got {effects}")
    else:
        print(f"✓ aoe_damage parse: {effects}")

    effects = EffectParser.parse("召唤一个 3/5 的随从")
    if not effects or effects[0][0] != 'summon_stats' or effects[0][1] != (3, 5):
        errors.append(f"FAIL: summon_stats parse: got {effects}")
    else:
        print(f"✓ summon_stats parse: {effects}")

    effects = EffectParser.parse("获得 5 点护甲")
    if not effects or effects[0][0] != 'armor' or effects[0][1] != 5:
        errors.append(f"FAIL: armor parse: got {effects}")
    else:
        print(f"✓ armor parse: {effects}")

    effects = EffectParser.parse("+3 攻击力")
    if not effects or effects[0][0] != 'buff_atk' or effects[0][1] != 3:
        errors.append(f"FAIL: buff_atk parse: got {effects}")
    else:
        print(f"✓ buff_atk parse: {effects}")

    # ---- Test 2: Fireball (6 damage) reduces target HP by 6 ----
    base = _build_test_state()
    fireball = Card(dbf_id=5001, name="Fireball", cost=4, card_type="SPELL",
                    text="造成 6 点伤害")

    result = resolve_effects(base, fireball)
    # Fireball targets highest-attack enemy minion (Murloc Raider, attack=2)
    # or enemy hero if no minions. Let's check what happened.
    # With 2 enemy minions (Voidwalker atk=1, Murloc Raider atk=2), targets Murloc Raider (atk=2)
    # Murloc Raider: health was 1, after 6 damage → health=-5 → dead → removed
    murloc_alive = any(m.name == "Murloc Raider" for m in result.opponent.board)
    if murloc_alive:
        errors.append(f"FAIL: Fireball should kill Murloc Raider (1 HP - 6 damage)")
    else:
        print("✓ Fireball kills Murloc Raider (1 HP - 6 damage)")

    # Original state should be unchanged
    if base.opponent.hero.hp != 30:
        errors.append("FAIL: original state mutated after Fireball test")
    else:
        print("✓ Original state unchanged after Fireball test")

    # ---- Test 3: AOE clears multiple minions ----
    base = _build_test_state()
    aoe_card = Card(dbf_id=5002, name="Arcane Explosion", cost=2, card_type="SPELL",
                    text="对所有随从造成 2 点伤害")

    result = resolve_effects(base, aoe_card)
    # Both enemy minions should be dead: Voidwalker (3-2=1 alive!), Murloc Raider (1-2=-1 dead)
    voidwalker_alive = any(m.name == "Voidwalker" for m in result.opponent.board)
    murloc_alive = any(m.name == "Murloc Raider" for m in result.opponent.board)
    if murloc_alive:
        errors.append(f"FAIL: AOE should kill Murloc Raider")
    if not voidwalker_alive:
        errors.append(f"FAIL: AOE (2 dmg) should NOT kill Voidwalker (3 HP, 1 remaining)")
    else:
        # Check Voidwalker has 1 HP remaining
        vw = [m for m in result.opponent.board if m.name == "Voidwalker"][0]
        if vw.health != 1:
            errors.append(f"FAIL: Voidwalker should have 1 HP after AOE, got {vw.health}")
        else:
            print(f"✓ AOE kills Murloc Raider, leaves Voidwalker at 1 HP")

    # ---- Test 4: Buff increases minion attack/health ----
    base = _build_test_state()
    buff_card = Card(dbf_id=5003, name="Blessing of Might", cost=1, card_type="SPELL",
                     text="+3 攻击力")

    result = resolve_effects(base, buff_card)
    fire_fly = [m for m in result.board if m.name == "Fire Fly"][0]
    if fire_fly.attack != 5:  # 2 + 3 = 5
        errors.append(f"FAIL: Fire Fly attack should be 5, got {fire_fly.attack}")
    else:
        print("✓ Buff increases Fire Fly attack from 2 to 5")

    # Original should be unchanged
    original_ff = [m for m in base.board if m.name == "Fire Fly"][0]
    if original_ff.attack != 2:
        errors.append("FAIL: original state mutated by buff")
    else:
        print("✓ Original state unchanged after buff test")

    # ---- Test 5: Draw adds cards to hand ----
    base = _build_test_state()
    base.deck_remaining = 10
    draw_card = Card(dbf_id=5004, name="Arcane Intellect", cost=2, card_type="SPELL",
                     text="抽 2 张牌")

    result = resolve_effects(base, draw_card)
    added = len(result.hand) - len(base.hand)
    if added != 2:
        errors.append(f"FAIL: draw should add 2 cards, added {added}")
    else:
        print("✓ Draw adds 2 cards to hand")

    if result.deck_remaining != 8:
        errors.append(f"FAIL: deck_remaining should be 8, got {result.deck_remaining}")
    else:
        print("✓ deck_remaining decreased from 10 to 8")

    # ---- Report ----
    print()
    if errors:
        print("❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("✅ All spell_simulator tests passed.")

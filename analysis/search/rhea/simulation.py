#!/usr/bin/env python3
"""simulation.py — Action simulation (apply_action) for the RHEA search engine.

Contains the core state transition logic: play card, attack, hero power,
end turn, and draw mechanics.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from analysis.search.rhea.actions import Action, ActionType

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

from analysis.search.game_state import Minion, Weapon
from analysis.models.card import Card
from analysis.data.card_effects import (
    _COST_REDUCE_CN,
    _COST_REDUCE_EN,
    get_card_armor,
    get_card_damage,
    get_card_health_cost,
)
from analysis.search.aura_engine import recompute_auras
from analysis.search.battlecry_dispatcher import dispatch_battlecry
from analysis.search.choose_one import is_choose_one, resolve_choose_one
from analysis.search.colossal import parse_colossal_value, summon_colossal_appendages
from analysis.search.corpse import (
    gain_corpses,
    has_double_corpse_gen,
    parse_corpse_effects,
    resolve_corpse_effects,
)
from analysis.search.corrupt import check_corrupt_upgrade
from analysis.search.deathrattle import resolve_deaths
from analysis.search.dormant import is_dormant_card, apply_dormant, tick_dormant
from analysis.search.herald import check_herald, apply_herald
from analysis.search.imbue import apply_imbue, apply_hero_power
from analysis.search.kindred import apply_kindred, set_kindred_double
from analysis.search.location import activate_location, tick_location_cooldowns
from analysis.search.outcast import check_outcast, apply_outcast_bonus
from analysis.search.quest import parse_quest, track_quest_progress
from analysis.search.shatter import check_shatter_on_draw
from analysis.search.trigger_system import TriggerDispatcher
from analysis.search.secret_triggers import check_secrets
from analysis.utils.spell_simulator import resolve_effects

log = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Main simulation entry point
# ------------------------------------------------------------------


def apply_action(state, action: Action):
    """Apply *action* to a **copy** of *state* and return the modified copy."""
    s = state.copy()

    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        s = _apply_play_card(s, action)
    elif action.action_type == ActionType.ATTACK:
        s = _apply_attack(s, action)
    elif action.action_type == ActionType.HERO_POWER:
        s = _apply_hero_power(s, action)
    elif action.action_type == ActionType.ACTIVATE_LOCATION:
        s = activate_location(s, action.source_index)
    elif action.action_type == ActionType.HERO_REPLACE:
        s = _apply_hero_replace(s, action)
    elif action.action_type == ActionType.TRANSFORM:
        s = _apply_transform(s, action)
    elif action.action_type == ActionType.END_TURN:
        s = _apply_end_turn(s)

    return s


# ------------------------------------------------------------------
# Card play
# ------------------------------------------------------------------


def _apply_play_card(s, action: Action):
    """Handle PLAY and PLAY_WITH_TARGET actions."""
    card_idx = action.card_index
    if card_idx < 0 or card_idx >= len(s.hand):
        return s
    card = s.hand[card_idx]

    eff_cost = s.mana.effective_cost(card)
    s.mana.available -= eff_cost
    s.mana.consume_modifiers(card)

    card_text = getattr(card, "text", "") or ""
    overload_val = getattr(card, "overload", 0) or 0
    if overload_val == 0 and hasattr(card, "effective_overload"):
        overload_val = card.effective_overload()
    if overload_val > 0:
        s.mana.overload_next += overload_val

    card_id = getattr(card, "card_id", "") or ""
    if card_id == "GAME_005" or "幸运币" in card.name or "The Coin" in (getattr(card, "ename", "") or ""):
        s.mana.available += 1
        s.mana.add_modifier("temporary_crystal", 1, "this_turn")

    if card_id == "CS2_033" or "伺机待发" in card.name or "Preparation" in (
        getattr(card, "ename", "") or ""
    ):
        s.mana.add_modifier("reduce_next_spell", 3, "next_spell")

    reduce_match = _COST_REDUCE_CN.search(card_text) or _COST_REDUCE_EN.search(card_text)
    if reduce_match and "下一张法术" in card_text:
        s.mana.add_modifier(
            "reduce_next_spell", int(reduce_match.group(1)), "next_spell"
        )

    # --- Health cost (消耗血量) ---
    hp_cost = get_card_health_cost(card)
    if hp_cost > 0:
        # Guard: hero must have enough HP to pay the cost (min 1 HP remaining)
        if s.hero.hp <= hp_cost:
            # Can't pay health cost — skip this card play
            return s
        s.hero.hp -= hp_cost

    # --- Corpse-only guard: cards that require corpses to be playable ---
    corpse_effects = parse_corpse_effects(card_text)
    for ce in corpse_effects:
        if not ce.is_optional and s.corpses < ce.cost:
            # Mandatory corpse cost but can't afford — skip this play
            return s

    # --- Opponent cost modifiers (对手加费 e.g. 异教低阶牧师) ---
    if "对手" in card_text and "法力值消耗增加" in card_text:
        import re as _re
        _opp_cost_inc = _re.search(r'法力值消耗增加[（(]\s*(\d+)\s*[）)]', card_text)
        if _opp_cost_inc:
            amt = int(_opp_cost_inc.group(1))
            # Determine scope: 法术→next_spell, 英雄技能→hero_power
            if "法术" in card_text:
                s.opponent.opp_cost_modifiers.append(("opp_spell_increase", amt, "next_spell"))
            elif "英雄技能" in card_text:
                s.opponent.opp_cost_modifiers.append(("opp_hero_power_increase", amt, "hero_power"))
    if "opponent" in card_text.lower() and ("Cost" in card_text or "cost" in card_text):
        import re as _re
        _opp_cost_inc = _re.search(r'[Cc]osts?\s*(\d+)\s*more', card_text)
        if _opp_cost_inc:
            amt = int(_opp_cost_inc.group(1))
            if "spell" in card_text.lower():
                s.opponent.opp_cost_modifiers.append(("opp_spell_increase", amt, "next_spell"))

    # --- Death Shadow (殒命暗影) transformation tracking ---
    if card_id == "CORE_RLK_567" or card_id == "RLK_567" or "殒命暗影" in card.name or "Death Shadow" in (getattr(card, "ename", "") or ""):
        # Death Shadow transforms into copies of spells cast
        # Mark that the next spell will be "free" (0-cost) since Death Shadow costs 0
        # The actual transformation is tracked by the watcher
        pass  # No simulation action needed — card is already 0-cost

    # Check outcast bonus (before card is removed from hand)
    outcast_active = check_outcast(s, card_idx, card)
    s.hand.pop(card_idx)

    # Track cards played this turn for combo
    s.cards_played_this_turn.append(card)

    if card.card_type.upper() == "MINION":
        s = _play_minion(s, card, action, outcast_active, card_idx)
    elif card.card_type.upper() == "WEAPON":
        s.hero.weapon = Weapon(
            attack=card.attack,
            health=card.health,
            name=card.name,
        )
    elif card.card_type.upper() == "SPELL":
        s = _play_spell(s, card, action)
    elif card.card_type.upper() == "HERO":
        try:
            from analysis.search.engine.mechanics.hero_card_handler import (
                HeroCardHandler,
            )
            s = HeroCardHandler().apply_hero_card(s, card)
        except (ImportError, AttributeError):
            armor = card.effective_armor() if hasattr(card, "effective_armor") else 0
            if armor == 0:
                armor = get_card_armor(card)
            s.hero.armor += armor
            hero_class = getattr(card, "card_class", "") or ""
            if hero_class:
                s.hero.hero_class = hero_class
            s.hero.hero_power_used = False
            s.hero.imbue_level = 0

    # Post-play mechanics
    s = apply_imbue(s, card)
    s = track_quest_progress(s, ActionType.PLAY, card)
    if outcast_active:
        s = apply_outcast_bonus(s, card_idx, card)
    card_class = getattr(card, "card_class", "") or ""
    if card_class.upper() == "DEATHKNIGHT":
        s = resolve_corpse_effects(s, card)
    try:
        s = dataclasses.replace(s, last_played_card=card)
    except (TypeError, AttributeError):
        log.debug("apply_action: optional mechanic failed", exc_info=True)
    s = check_corrupt_upgrade(s, card)
    _handle_overdraw(s)

    return s


def _play_minion(s, card, action: Action, outcast_active: bool, card_idx: int):
    """Handle minion card play — summon, battlecry, triggers."""
    new_minion = Minion.from_card(card)
    pos = min(action.position, len(s.board))
    s.board.insert(pos, new_minion)

    # Colossal appendage summoning
    if parse_colossal_value(card) > 0:
        s = summon_colossal_appendages(s, new_minion, card, pos, s.herald_count)

    s = apply_kindred(s, card)
    card_text = getattr(card, "text", "") or ""
    if "延系效果会触发两次" in (card_text or ""):
        s = set_kindred_double(s)

    s = dispatch_battlecry(s, card, new_minion)

    if is_choose_one(card):
        s = resolve_choose_one(s, card, new_minion)

    if is_dormant_card(card):
        new_minion = apply_dormant(new_minion, card)

    if check_herald(card):
        s = apply_herald(s, card)

    s = TriggerDispatcher().on_minion_played(s, new_minion, card)

    s = recompute_auras(s)
    return s


def _play_spell(s, card, action: Action):
    """Handle spell card play."""
    s = resolve_effects(s, card, target_index=action.target_index)

    # --- Death Shadow (殒命暗影) transform: replaces self with copy of cast spell ---
    for i, hc in enumerate(s.hand):
        hc_card_id = getattr(hc, "card_id", "") or ""
        hc_name = getattr(hc, "name", "")
        if hc_card_id in ("CORE_RLK_567", "RLK_567") or "殒命暗影" in hc_name or "Death Shadow" in (getattr(hc, "ename", "") or ""):
            # Transform Death Shadow into a copy of this spell
            try:
                import dataclasses
                new_card = dataclasses.replace(card) if dataclasses.is_dataclass(card) else card
                # Mark the transformed card as coming from Death Shadow
                if hasattr(new_card, 'card_id'):
                    new_card.card_id = getattr(card, 'card_id', '')
                s.hand[i] = new_card
            except (TypeError, AttributeError):
                log.debug("Death Shadow transform failed", exc_info=True)
            break  # Only one Death Shadow in hand

    # Activate quest if quest card
    quest = parse_quest(card)
    if quest is not None:
        s.active_quests.append(quest)

    card_text = getattr(card, "text", "") or ""
    if "冻结" in card_text or "FREEZE" in (
        getattr(card, "mechanics", None) or []
    ):
        if s.opponent.board:
            if action.target_index > 0 and action.target_index <= len(s.opponent.board):
                s.opponent.board[action.target_index - 1].frozen_until_next_turn = True
            elif action.target_index == 0 or "所有" in card_text or "all" in card_text.lower():
                for em in s.opponent.board:
                    em.frozen_until_next_turn = True

    s = recompute_auras(s)
    return s


# ------------------------------------------------------------------
# Attack
# ------------------------------------------------------------------


def _apply_attack(s, action: Action):
    """Handle ATTACK action — minion or hero weapon attack."""
    src_idx = action.source_index
    tgt_idx = action.target_index

    # Hero weapon attack (source_index == -1)
    if src_idx == -1:
        weapon = s.hero.weapon
        if weapon is None or weapon.attack <= 0:
            return s
        if tgt_idx == 0:
            # Attack enemy hero
            damage = weapon.attack
            if s.opponent.hero.armor > 0:
                absorbed = min(s.opponent.hero.armor, damage)
                s.opponent.hero.armor -= absorbed
                damage -= absorbed
            if not s.opponent.hero.is_immune:
                s.opponent.hero.hp -= damage
            s = check_secrets(s, "on_attack_hero", {"attacker": None})
        else:
            enemy_idx = tgt_idx - 1
            if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
                return s
            target = s.opponent.board[enemy_idx]
            if target.has_divine_shield:
                target.has_divine_shield = False
            else:
                target.health -= weapon.attack
            # Hero takes counter-damage from minion
            damage = target.attack
            if s.hero.armor > 0:
                absorbed = min(s.hero.armor, damage)
                s.hero.armor -= absorbed
                damage -= absorbed
            s.hero.hp -= damage
            s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        weapon.health -= 1
        if weapon.health <= 0:
            s.hero.weapon = None
        return s

    if src_idx < 0 or src_idx >= len(s.board):
        return s
    source = s.board[src_idx]

    if tgt_idx == 0:
        # Attack enemy hero
        if s.opponent.hero.is_immune:
            pass
        else:
            damage = source.attack
            if s.opponent.hero.armor > 0:
                absorbed = min(s.opponent.hero.armor, damage)
                s.opponent.hero.armor -= absorbed
                damage -= absorbed
            s.opponent.hero.hp -= damage
            if source.has_lifesteal:
                s.hero.hp = min(s.hero.max_hp, s.hero.hp + source.attack)
        s = check_secrets(s, "on_attack_hero", {"attacker": source})
    else:
        enemy_idx = tgt_idx - 1
        if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]

        target_had_divine_shield = target.has_divine_shield
        if target.has_divine_shield:
            target.has_divine_shield = False
        elif target.has_immune:
            pass
        else:
            target.health -= source.attack

        # Poisonous: instant kill
        if source.has_poisonous and not target_had_divine_shield and not target.has_immune:
            target.health = 0

        # Counter-attack
        if source.has_divine_shield:
            source.has_divine_shield = False
        elif source.has_immune:
            pass
        else:
            source.health -= target.attack

        # Lifesteal
        if source.has_lifesteal:
            actual_damage = source.attack if not target_had_divine_shield else 0
            if actual_damage > 0:
                s.hero.hp = min(30, s.hero.hp + actual_damage)

        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    # Stealth breaks when minion attacks
    for m in s.board:
        if m is source and m.has_stealth:
            m.has_stealth = False
            break

    # Remove dead friendly minions
    s.board = [m for m in s.board if m.health > 0]

    # Resolve deathrattles
    s = resolve_deaths(s)

    # Reborn: friendly minions
    if src_idx != -1:
        for m in list(s.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1
                m.has_attacked_once = False
                m.can_attack = False
                m.has_divine_shield = False
                m.has_stealth = False
                m.has_taunt = False
        s.board = [m for m in s.board if m.health > 0]

    # Reborn for enemy minions
    for m in list(s.opponent.board):
        if m.health <= 0 and m.has_reborn:
            m.has_reborn = False
            m.health = 1
            m.max_health = 1
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    amount = 2 if has_double_corpse_gen(s) else 1
    s = gain_corpses(s, amount)
    s = recompute_auras(s)

    # Mark source as having attacked (windfury tracking)
    if src_idx < len(s.board):
        for m in s.board:
            if m is source:
                if m.has_windfury and not m.has_attacked_once:
                    m.has_attacked_once = True
                else:
                    m.can_attack = False
                break

    return s


# ------------------------------------------------------------------
# Hero power
# ------------------------------------------------------------------


def _apply_hero_power(s, action: Action):
    """Handle HERO_POWER action."""
    hp_cost = s.hero.hero_power_cost
    s.mana.available -= hp_cost
    s.hero.hero_power_used = True

    # Spell power boosts damage-dealing hero powers
    total_damage = s.hero.hero_power_damage
    if total_damage > 0:
        for m in s.board:
            total_damage += m.spell_power

    if total_damage > 0 and s.opponent.board:
        target = s.opponent.board[0]
        damage = total_damage
        if target.armor > 0:
            absorbed = min(target.armor, damage)
            target.armor -= absorbed
            damage -= absorbed
        target.health -= damage

    s = apply_hero_power(s)

    return s


# ------------------------------------------------------------------
# Hero card replace
# ------------------------------------------------------------------


def _apply_hero_replace(s, action: Action):
    """Handle HERO_REPLACE action."""
    card_idx = action.card_index
    if 0 <= card_idx < len(s.hand):
        card = s.hand.pop(card_idx)
        s.mana.available -= s.mana.effective_cost(card)
        s.mana.consume_modifiers(card)
        s.cards_played_this_turn.append(card)
        try:
            from analysis.search.engine.mechanics.hero_card_handler import (
                HeroCardHandler,
            )
            s = HeroCardHandler().apply_hero_card(s, card)
        except (ImportError, AttributeError):
            armor = getattr(card, "armor", 0) or 0
            s.hero.armor += armor
            hero_class = getattr(card, "card_class", "") or ""
            if hero_class:
                s.hero.hero_class = hero_class
            s.hero.hero_power_used = False
    return s


# ------------------------------------------------------------------
# Transform
# ------------------------------------------------------------------


def _apply_transform(s, action: Action):
    """Handle TRANSFORM action — turn target into 1/1 sheep/frog."""
    tgt_idx = action.target_index - 1
    if 0 <= tgt_idx < len(s.opponent.board):
        target = s.opponent.board[tgt_idx]
        target.attack = 1
        target.health = 1
        target.max_health = 1
        target.has_taunt = False
        target.has_divine_shield = False
        target.has_stealth = False
        target.has_windfury = False
        target.has_poisonous = False
        target.has_rush = False
        target.has_charge = False
        target.has_reborn = False
        target.enchantments = []
    return s


# ------------------------------------------------------------------
# End turn
# ------------------------------------------------------------------


def _apply_end_turn(s):
    """Handle END_TURN action."""
    # Apply overload
    s.mana.overloaded = s.mana.overload_next
    s.mana.overload_next = 0
    s.mana.available -= s.mana.overloaded

    # Snapshot races/schools for Kindred tracking (BEFORE clearing)
    try:
        s.last_turn_races = set()
        s.last_turn_schools = set()
        for card in s.cards_played_this_turn:
            race = getattr(card, "race", "") or ""
            school = (
                getattr(card, "spell_school", "")
                or getattr(card, "spellSchool", "")
                or ""
            )
            if race:
                s.last_turn_races.add(race.upper())
            if school:
                s.last_turn_schools.add(school.upper())
    except (AttributeError, TypeError):
        log.debug("apply_action: optional mechanic failed", exc_info=True)

    s.cards_played_this_turn = []

    # Fatigue
    if s.deck_remaining <= 0:
        s.fatigue_damage += 1
        s.hero.hp -= s.fatigue_damage

    s.mana.modifiers = []
    # Clear expired opponent cost modifiers (next_spell scope)
    s.opponent.opp_cost_modifiers = [
        m for m in s.opponent.opp_cost_modifiers if m[2] not in ("next_spell", "this_turn")
    ]

    # Unfreeze friendly minions
    for m in s.board:
        m.frozen_until_next_turn = False

    s = tick_dormant(s)
    s.hero.is_immune = False
    for m in s.board:
        m.has_immune = False

    s = tick_location_cooldowns(s)

    return s


# ------------------------------------------------------------------
# Draw
# ------------------------------------------------------------------


def apply_draw(state, count: int = 1):
    """Draw cards from deck. Deals fatigue damage if deck is empty.

    Handles overdraw (hand > 10 burns cards) and shatter mechanic.

    Returns a modified copy of state.
    """
    s = state.copy()
    for _ in range(count):
        if s.deck_remaining <= 0:
            s.fatigue_damage += 1
            s.hero.hp -= s.fatigue_damage
        else:
            s.deck_remaining -= 1
            drawn = Card(
                dbf_id=0,
                name="Drawn Card",
                cost=0,
                card_type="SPELL",
            )
            if len(s.hand) >= 10:
                pass  # card is burned
            else:
                s.hand.append(drawn)
                s = check_shatter_on_draw(s, len(s.hand) - 1)
    return s


def _handle_overdraw(state) -> None:
    """Burn excess cards if hand exceeds 10 (in-place)."""
    while len(state.hand) > 10:
        state.hand.pop()


# ------------------------------------------------------------------
# Multi-turn lethal check helper
# ------------------------------------------------------------------


def next_turn_lethal_check(state) -> bool:
    """Check if lethal is achievable next turn.

    Predict available mana next turn = min(current_max + 1, 10).
    Calculate burst damage potential from hand + board.
    """
    next_mana = min(state.mana.max_mana + 1, state.mana.max_mana_cap)

    # Burst from minions
    minion_burst = 0
    for m in state.board:
        minion_burst += m.attack

    # Burst from direct damage spells
    spell_burst = 0
    for c in state.hand:
        ct = getattr(c, "card_type", "").upper()
        if ct == "SPELL" and c.cost <= next_mana:
            dmg = c.total_damage() if hasattr(c, "total_damage") else 0
            if dmg == 0:
                dmg = get_card_damage(c)
            spell_burst += dmg

    # Weapon burst
    weapon_burst = 0
    if state.hero.weapon is not None:
        weapon_burst += state.hero.weapon.attack

    total_burst = minion_burst + spell_burst + weapon_burst
    opponent_health = state.opponent.hero.hp + state.opponent.hero.armor

    return total_burst >= opponent_health

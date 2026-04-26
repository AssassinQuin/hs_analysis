#!/usr/bin/env python3
"""simulation.py — Action simulation (apply_action) for the search engine.

Contains the core state transition logic: play card, attack, hero power,
end turn, and draw mechanics."""

from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

from analysis.search.abilities.actions import Action, ActionType

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

from analysis.search.game_state import Minion, Weapon
from analysis.models.card import Card
from analysis.data.card_effects import (
    get_card_armor,
    get_card_damage,
    get_card_health_cost,
)
from analysis.search.aura_engine import recompute_auras
from analysis.search.choose_one import is_choose_one, resolve_choose_one
from analysis.search.corpse import gain_corpses, has_double_corpse_gen, parse_corpse_effects
from analysis.search.deathrattle import resolve_deaths
from analysis.search.dormant import is_dormant_card, apply_dormant, tick_dormant
from analysis.search.imbue import apply_hero_power
from analysis.search.location import activate_location, tick_location_cooldowns
from analysis.search.quest import parse_quest
from analysis.search.shatter import check_shatter_on_draw
from analysis.search.trigger_system import TriggerDispatcher
from analysis.search.secret_triggers import check_secrets

log = logging.getLogger(__name__)


# ── Effect detection helpers (text-based, no card_id/name matching) ──


def _is_temporary_mana_effect(text_lower: str) -> bool:
    """Detect 'Gain N Mana Crystal(s) this turn' effect from card text.

    Matches patterns:
    - "gain 1 mana crystal this turn" / "gain 2 mana crystals"
    - "获得1个法力水晶" / "获得 2 个法力水晶"
    - "gain an empty mana crystal" (Innervate-style)
    Does NOT match:
    - "Gain 1 Mana Crystal" (permanent, like Wild Growth on full mana)
    """
    # English patterns
    if "gain" in text_lower and "mana crystal" in text_lower and "this turn" in text_lower:
        return True
    # "Gain an empty mana crystal" (temporary)
    if "gain" in text_lower and "empty mana crystal" in text_lower:
        return True
    # Chinese patterns: 获得 N 个法力水晶 + 本回合
    if "获得" in text_lower and "法力水晶" in text_lower and "本回合" in text_lower:
        return True
    return False


def _trigger_minion_on_spell_cast(s, card=None):
    """After casting a spell, check friendly minions for spell-cast triggers.

    card: the spell just cast (used to check spell_school for FEL-only triggers).
    """
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.definition import AbilityTrigger

    spell_school = getattr(card, 'spell_school', '') or '' if card else ''
    is_fel = spell_school.upper() == 'FEL'

    for m in s.board:
        if m.health <= 0:
            continue

        trigger_type = getattr(m, 'trigger_type', '')
        trigger_effect = getattr(m, 'trigger_effect', '')

        # Fast path for token trigger effects
        if trigger_effect == 'ADD_RANDOM_NAGA':
            # Only triggers on Fel spells
            if trigger_type == 'ON_FEL_SPELL_CAST' and not is_fel:
                continue
            s = _add_random_naga_to_hand(s)
            continue

        # General ability-based dispatch (for non-token abilities)
        abilities = getattr(m, 'abilities', [])
        if not abilities:
            abilities = AbilityParser.parse(m)
        for ability in abilities:
            if ability.trigger != AbilityTrigger.TRIGGER_VISUAL:
                continue
            if not ability.is_active(s, m):
                continue
            try:
                s = ability.execute(s, m)
            except Exception as exc:
                log.debug("ON_SPELL_CAST ability failed for %s: %s", getattr(m, 'name', '?'), exc)

    return s


def _add_random_naga_to_hand(s):
    """Add a random 1-Cost Naga minion to hand (e.g. Nespirah, Freed trigger)."""
    from analysis.data.token_cards import get_random_naga, create_naga_card

    naga_data = get_random_naga(max_cost=1)
    card = create_naga_card(naga_data)
    s.hand.append(card)
    return s


def _trigger_location_spell_react(s, card):
    """After casting a spell, check if any LOCATION should react.

    Uses abilities executor to detect spellSchool-based cooldown resets.
    """
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.definition import AbilityTrigger

    spell_school = getattr(card, "spell_school", "") or ""
    if not spell_school:
        return s

    locations = getattr(s, "locations", [])
    if not locations:
        return s

    for loc in locations:
        abilities = getattr(loc, 'abilities', [])
        if not abilities:
            abilities = AbilityParser.parse(loc)
        for ability in abilities:
            if ability.trigger not in (AbilityTrigger.WHENEVER, AbilityTrigger.AFTER):
                continue
            etext = ability.text_raw.lower()
            school_lower = spell_school.lower()
            if school_lower in etext and (
                "refresh" in etext
                or "reopen" in etext
                or "reduce" in etext and "cooldown" in etext
            ):
                if loc.cooldown_current > 0:
                    loc.cooldown_current = 0

    return s


def _apply_text_cost_reduction(card, hand, card_idx, current_cost):
    """Apply passive text-based cost reductions via abilities system."""
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.definition import AbilityTrigger, EffectKind

    abilities = getattr(card, 'abilities', [])
    if not abilities:
        abilities = AbilityParser.parse(card)

    for ability in abilities:
        if ability.trigger != AbilityTrigger.PASSIVE_COST:
            continue
        if ability.condition and not ability.condition.check(None, card):
            continue
        for effect in ability.effects:
            if effect.kind == EffectKind.REDUCE_COST and effect.value > 0:
                return max(0, current_cost - effect.value)

    return current_cost


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


def _validate_and_pay_cost(s, card, card_idx: int):
    """Validate card play feasibility and pay all costs (mana, overload, HP, corpses).

    Returns the modified state, or None if the play should be skipped.
    """
    card_text = getattr(card, "text", "") or ""

    # Mana cost
    eff_cost = s.mana.effective_cost(card)
    eff_cost = _apply_text_cost_reduction(card, s.hand, card_idx, eff_cost)
    s.mana.available -= eff_cost
    s.mana.consume_modifiers(card)

    # Overload
    overload_val = getattr(card, "overload", 0) or 0
    if overload_val == 0 and hasattr(card, "effective_overload"):
        overload_val = card.effective_overload()
    if overload_val > 0:
        s.mana.overload_next += overload_val

    # Temporary mana (Coin, Innervate, etc.)
    etext_lower = (getattr(card, "english_text", "") or card_text).lower()
    if _is_temporary_mana_effect(etext_lower):
        # Extract mana count without regex (Standard 5: zero regex in simulation layer)
        count = 1
        idx = etext_lower.find("gain")
        if idx >= 0:
            after = etext_lower[idx + 4:].lstrip()
            for i, ch in enumerate(after):
                if ch.isdigit():
                    # Found start of number
                    j = i
                    while j < len(after) and after[j].isdigit():
                        j += 1
                    count = int(after[i:j])
                    break
        s.mana.available += count
        s.mana.add_modifier("temporary_crystal", count, "this_turn")

    # "Your next spell costs N less"
    from analysis.data.card_effects import get_effects as _get_effects
    card_effects_data = _get_effects(card)
    if card_effects_data and card_effects_data.cost_reduce > 0:
        etext = (getattr(card, 'english_text', '') or card_text).lower()
        if "next spell" in etext or "your next spell" in etext:
            s.mana.add_modifier(
                "reduce_next_spell", card_effects_data.cost_reduce, "next_spell"
            )

    # Health cost (e.g. Warlock self-damage cards)
    hp_cost = get_card_health_cost(card)
    if hp_cost > 0:
        if s.hero.hp <= hp_cost:
            return None
        s.hero.hp -= hp_cost

    # Corpse cost guard
    corpse_effects = parse_corpse_effects(card_text)
    for ce in corpse_effects:
        if not ce.is_optional and s.corpses < ce.cost:
            return None

    # Opponent cost modifiers
    if "opponent" in etext_lower and "cost" in etext_lower and "more" in etext_lower:
        from analysis.search.abilities.extractors import extract_number_after
        amt = extract_number_after(etext_lower, "more")
        if amt > 0:
            if "spell" in etext_lower:
                s.opponent.opp_cost_modifiers.append(("opp_spell_increase", amt, "next_spell"))
            elif "hero power" in etext_lower:
                s.opponent.opp_cost_modifiers.append(("opp_hero_power_increase", amt, "hero_power"))

    return s


def _dispatch_card_type(s, card, action, card_idx: int):
    """Dispatch card play to the appropriate type-specific handler."""
    ctype = card.card_type.upper()
    if ctype == "MINION":
        return _play_minion(s, card, action, card_idx)
    elif ctype == "WEAPON":
        s.hero.weapon = Weapon(
            attack=card.attack,
            health=card.health,
            name=card.name,
        )
        return s
    elif ctype == "LOCATION":
        return _play_location(s, card)
    elif ctype == "SPELL":
        return _play_spell(s, card, action)
    elif ctype == "HERO":
        return _play_hero_card(s, card)
    return s


def _play_hero_card(s, card):
    """Handle HERO card replacement."""
    try:
        from analysis.search.engine.mechanics.hero_card_handler import HeroCardHandler
        return HeroCardHandler().apply_hero_card(s, card)
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
        return s


def _apply_play_card(s, action: Action):
    """Handle PLAY and PLAY_WITH_TARGET actions."""
    card_idx = action.card_index
    if card_idx < 0 or card_idx >= len(s.hand):
        return s
    card = s.hand[card_idx]

    # Phase 1: Validate and pay all costs
    result = _validate_and_pay_cost(s, card, card_idx)
    if result is None:
        return s
    s = result

    # Phase 2: Remove from hand and dispatch by card type
    s.hand.pop(card_idx)
    s.cards_played_this_turn.append(card)
    s = _dispatch_card_type(s, card, action, card_idx)

    # Phase 3: Post-play effects
    try:
        s = dataclasses.replace(s, last_played_card=card)
    except (TypeError, AttributeError):
        log.debug("apply_action: optional mechanic failed", exc_info=True)
    _handle_overdraw(s)

    from analysis.search.corrupt import check_corrupt_upgrade
    s = check_corrupt_upgrade(s, card)

    return s


def _play_location(s, card):
    """Handle LOCATION card play — add to locations list on board."""
    from analysis.search.location import Location
    loc = Location(
        dbf_id=getattr(card, 'dbf_id', 0),
        name=card.name,
        cost=getattr(card, 'cost', 0),
        durability=getattr(card, 'health', 3),
        cooldown_current=0,
        cooldown_max=1,
        text=getattr(card, 'text', '') or '',
        english_text=getattr(card, 'english_text', '') or '',
        card_id=getattr(card, 'card_id', '') or '',
        mechanics=getattr(card, 'mechanics', []) or [],
    )
    if not s.location_full():
        s.locations.append(loc)
    return s


def _apply_hand_transform(s, card, minion) -> None:
    """Check if card has a hand-transform effect and apply it to the minion.

    Hand-transform: "while in your hand, becomes a X/Y copy of opponent's
    last played minion".  Replaces the minion's attack/health/name with
    the opponent's last played minion, capped to transform_attack/health.
    """
    try:
        from analysis.data.card_effects import get_effects
        eff = get_effects(card)
        if not eff.has_hand_transform:
            return
        opp_last = getattr(s.opponent, 'opp_last_played_minion', {})
        if not opp_last or not opp_last.get("name"):
            # No opponent minion tracked — use transform base stats
            minion.attack = eff.transform_attack
            minion.health = eff.transform_health
            minion.max_health = eff.transform_health
            return
        # Use opponent's last minion identity with transform stats
        minion.name = opp_last["name"]
        minion.card_id = opp_last.get("card_id", "")
        minion.attack = eff.transform_attack
        minion.health = eff.transform_health
        minion.max_health = eff.transform_health
    except Exception:
        pass  # Graceful degradation


def _play_minion(s, card, action: Action, card_idx: int):
    """Handle minion card play — summon, battlecry, triggers.

    Uses the unified orchestrator for ability dispatch instead of
    calling herald/imbue/battlecry/colossal/kindred directly.
    """
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.orchestrator import orchestrate

    new_minion = Minion.from_card(card)

    # Hand-transform: replace stats with opponent's last played minion
    # if the card has a hand-transform effect (e.g. "becomes a 3/4 copy
    # of the last minion your opponent played").
    _apply_hand_transform(s, card, new_minion)

    pos = min(action.position, len(s.board))
    s.board.insert(pos, new_minion)

    # Parse all abilities from the card (herald, imbue, battlecry, colossal, kindred, etc.)
    abilities = AbilityParser.parse(card)

    # Dispatch via unified orchestrator
    ctx = {
        'target_index': action.target_index,
        'card_index': card_idx,
        'is_minion': True,
        'source_minion': new_minion,
    }
    s = orchestrate(s, card, abilities, ctx)

    # Legacy: choose one (separate concern, not part of ability parsing)
    if is_choose_one(card):
        s = resolve_choose_one(s, card, new_minion)

    # Legacy: dormant (minion state, not an ability effect)
    if is_dormant_card(card):
        new_minion = apply_dormant(new_minion, card)

    s = TriggerDispatcher().on_minion_played(s, new_minion, card)

    s = recompute_auras(s)
    return s


def _play_spell(s, card, action: Action):
    """Handle spell card play.

    Unified path: AbilityParser.parse() → orchestrate().
    Parser supplements verb parsing with structured card_effects data,
    ensuring complete coverage for both EN and CN text.
    """
    from analysis.search.abilities.parser import AbilityParser
    from analysis.search.abilities.orchestrator import orchestrate

    # Parse all abilities (verb parsing + structured data fallback)
    abilities = AbilityParser.parse(card)
    ctx = {'target_index': action.target_index, 'is_minion': False}
    s = orchestrate(s, card, abilities, ctx)

    # --- Spell-transform: replace hand cards that copy cast spells ---
    # Zero card-id hardcoding — detect via card_effects.has_spell_transform.
    # e.g. "transform this into a copy of it" / "变形成为该法术的复制"
    from analysis.data.card_effects import get_effects
    for i, hc in enumerate(s.hand):
        if get_effects(hc).has_spell_transform:
            try:
                import dataclasses
                new_card = dataclasses.replace(card) if dataclasses.is_dataclass(card) else card
                if hasattr(new_card, 'card_id'):
                    new_card.card_id = getattr(card, 'card_id', '')
                s.hand[i] = new_card
            except (TypeError, AttributeError):
                log.debug("Spell-transform failed", exc_info=True)
            break

    # Activate quest if quest card
    quest = parse_quest(card)
    if quest is not None:
        s.active_quests.append(quest)

    # Freeze via abilities system
    mechanics = set(getattr(card, 'mechanics', []) or [])
    etext = (getattr(card, 'english_text', '') or '').lower()
    if "FREEZE" in mechanics or "freeze" in etext:
        if s.opponent.board:
            if action.target_index > 0 and action.target_index <= len(s.opponent.board):
                s.opponent.board[action.target_index - 1].frozen_until_next_turn = True
            elif action.target_index == 0 or "all" in etext:
                for em in s.opponent.board:
                    em.frozen_until_next_turn = True

    s = _trigger_location_spell_react(s, card)
    s = _trigger_minion_on_spell_cast(s, card=card)

    s = recompute_auras(s)
    return s


# ------------------------------------------------------------------
# Attack
# ------------------------------------------------------------------


def _apply_attack(s, action: Action):
    """Handle ATTACK action — dispatch to hero-weapon or minion attack."""
    if action.source_index == -1:
        return _apply_hero_weapon_attack(s, action)
    return _apply_minion_attack(s, action)


def _apply_deal_damage_to_hero(hero, damage: int):
    """Apply damage to a hero, absorbing through armor first."""
    if hero.armor > 0:
        absorbed = min(hero.armor, damage)
        hero.armor -= absorbed
        damage -= absorbed
    if not hero.is_immune:
        hero.hp -= damage


def _apply_hero_weapon_attack(s, action: Action):
    """Handle hero weapon attack (source_index == -1)."""
    weapon = s.hero.weapon
    if weapon is None or weapon.attack <= 0:
        return s

    tgt_idx = action.target_index
    if tgt_idx == 0:
        _apply_deal_damage_to_hero(s.opponent.hero, weapon.attack)
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
        _apply_deal_damage_to_hero(s.hero, target.attack)
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    weapon.health -= 1
    if weapon.health <= 0:
        s.hero.weapon = None
    return s


def _minion_attack_hero(s, source: Minion):
    """Minion attacks enemy hero."""
    if s.opponent.hero.is_immune:
        return
    _apply_deal_damage_to_hero(s.opponent.hero, source.attack)
    if source.has_lifesteal:
        s.hero.hp = min(s.hero.max_hp, s.hero.hp + source.attack)


def _minion_attack_minion(s, source: Minion, target: Minion):
    """Minion attacks enemy minion — damage, poisonous, counter, lifesteal."""
    target_had_divine_shield = target.has_divine_shield

    # Target takes damage
    if target.has_divine_shield:
        target.has_divine_shield = False
    elif target.has_immune:
        pass
    else:
        target.health -= source.attack

    # Poisonous: instant kill
    if source.has_poisonous and not target_had_divine_shield and not target.has_immune:
        target.health = 0

    # Counter-attack from target
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


def _resolve_reborn(board: list):
    """Process reborn for dead minions on a board."""
    for m in list(board):
        if m.health <= 0 and m.has_reborn:
            m.has_reborn = False
            m.health = 1
            m.max_health = 1
            m.has_attacked_once = False
            m.can_attack = False
            m.has_divine_shield = False
            m.has_stealth = False
            m.has_taunt = False


def _apply_minion_attack(s, action: Action):
    """Handle minion attack + combat aftermath (deaths, reborn, windfury)."""
    src_idx = action.source_index
    tgt_idx = action.target_index

    if src_idx < 0 or src_idx >= len(s.board):
        return s
    source = s.board[src_idx]

    # Resolve combat
    if tgt_idx == 0:
        _minion_attack_hero(s, source)
        s = check_secrets(s, "on_attack_hero", {"attacker": source})
    else:
        enemy_idx = tgt_idx - 1
        if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]
        _minion_attack_minion(s, source, target)

    # Break stealth
    for m in s.board:
        if m is source and m.has_stealth:
            m.has_stealth = False
            break

    # Remove dead friendly minions
    s.board = [m for m in s.board if m.health > 0]

    # Resolve deathrattles
    s = resolve_deaths(s)

    # Reborn: friendly minions
    _resolve_reborn(s.board)
    s.board = [m for m in s.board if m.health > 0]

    # Reborn: enemy minions
    _resolve_reborn(s.opponent.board)
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    # Corpse generation
    amount = 2 if has_double_corpse_gen(s) else 1
    s = gain_corpses(s, amount)
    s = recompute_auras(s)

    # Windfury tracking
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

"""engine/simulation.py — Unified state transition engine.

Single entry point: apply_action(state, action) -> GameState
Uses engine/dispatch.py for effect execution, engine/target.py for target resolution.
Correct Hearthstone death phase semantics.
"""
from __future__ import annotations

import logging
import dataclasses
from typing import TYPE_CHECKING

from analysis.abilities.definition import Action, ActionType

if TYPE_CHECKING:
    from analysis.engine.state import GameState

from analysis.engine.state import Minion, Weapon
from analysis.models.card import Card

from analysis.engine.dispatch import dispatch_batch
from analysis.engine.target import best_target, validate_target
from analysis.engine.deterministic import DeterministicRNG

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Cost helpers
# ──────────────────────────────────────────────────────────────


def _apply_text_cost_reduction(card, hand, card_idx: int, current_cost: int) -> int:
    """Apply passive text-based cost reductions via abilities system."""
    from analysis.abilities.definition import AbilityTrigger, EffectKind
    from analysis.abilities.loader import load_abilities

    abilities = getattr(card, "abilities", [])
    if not abilities:
        cid = getattr(card, "card_id", "")
        if cid:
            abilities = load_abilities(cid)

    for ability in abilities:
        if ability.trigger != AbilityTrigger.PASSIVE_COST:
            continue
        if ability.condition and not ability.condition.check(None, card):
            continue
        for effect in ability.effects:
            if effect.kind == EffectKind.REDUCE_COST and effect.value > 0:
                return max(0, current_cost - effect.value)

    return current_cost


def _is_temporary_mana_effect(text_lower: str) -> bool:
    """Detect 'Gain N Mana Crystal(s) this turn' effect from card text."""
    if "gain" in text_lower and "mana crystal" in text_lower and "this turn" in text_lower:
        return True
    if "gain" in text_lower and "empty mana crystal" in text_lower:
        return True
    if "获得" in text_lower and "法力水晶" in text_lower and "本回合" in text_lower:
        return True
    return False


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
        count = 1
        idx = etext_lower.find("gain")
        if idx >= 0:
            after = etext_lower[idx + 4:].lstrip()
            for i, ch in enumerate(after):
                if ch.isdigit():
                    j = i
                    while j < len(after) and after[j].isdigit():
                        j += 1
                    count = int(after[i:j])
                    break
        s.mana.available += count
        s.mana.add_modifier("temporary_crystal", count, "this_turn")

    # "Your next spell costs N less"
    cost_reduce_applied = False
    try:
        from analysis.data.card_effects import get_effects as _get_effects
        card_effects_data = _get_effects(card)
        if card_effects_data and card_effects_data.cost_reduce > 0:
            etext = (getattr(card, "english_text", "") or card_text).lower()
            if "next spell" in etext or "your next spell" in etext:
                s.mana.add_modifier(
                    "reduce_next_spell", card_effects_data.cost_reduce, "next_spell"
                )
                cost_reduce_applied = True
    except (ImportError, AttributeError, TypeError):
        pass

    # Text-based fallback for "next spell costs N less" (e.g. Preparation)
    if not cost_reduce_applied:
        etext = (getattr(card, "english_text", "") or card_text).lower()
        if "next spell" in etext or "your next spell" in etext:
            import re as _re
            m = _re.search(r'costs?\s*\(?(\d+)\)?\s*less', etext)
            if m:
                reduce_amt = int(m.group(1))
                s.mana.add_modifier("reduce_next_spell", reduce_amt, "next_spell")

    # Health cost (e.g. Warlock self-damage cards)
    try:
        from analysis.data.card_effects import get_card_health_cost
        hp_cost = get_card_health_cost(card)
        if hp_cost > 0:
            if s.hero.hp <= hp_cost:
                return None
            s.hero.hp -= hp_cost
    except (ImportError, AttributeError):
        pass

    # Corpse cost guard
    try:
        from analysis.search.corpse import parse_corpse_effects
        corpse_effects = parse_corpse_effects(card_text)
        for ce in corpse_effects:
            if not ce.is_optional and s.corpses < ce.cost:
                return None
    except (ImportError, AttributeError):
        pass

    # Opponent cost modifiers
    if "opponent" in etext_lower and "cost" in etext_lower and "more" in etext_lower:
        idx = etext_lower.find("more")
        amt = 0
        if idx >= 0:
            after = etext_lower[idx + 4:].strip()
            for part in after.split():
                if part.isdigit():
                    amt = int(part)
                    break
        if amt > 0:
            if "spell" in etext_lower:
                s.opponent.opp_cost_modifiers.append(
                    ("opp_spell_increase", amt, "next_spell")
                )
            elif "hero power" in etext_lower:
                s.opponent.opp_cost_modifiers.append(
                    ("opp_hero_power_increase", amt, "hero_power")
                )

    return s


# ──────────────────────────────────────────────────────────────
# Death phase — CORRECTED Hearthstone semantics (P4b)
# ──────────────────────────────────────────────────────────────


def _resolve_deaths(state: "GameState", max_cascade: int = 3) -> "GameState":
    """Standard Hearthstone death phase:

    1. SNAPSHOT all minions with health <= 0 (friendly + enemy combined)
    2. SIMULTANEOUS removal from board
    3. Resolve deathrattles in global play order
    4. CASCADE check for new deaths (max rounds configurable, default 3)
    5. REBORN with taunt/keywords preserved
    """
    s = state

    for _ in range(max_cascade):
        # Step 1: Snapshot all dead minions (friendly + enemy)
        dead_friendly = [m for m in s.board if m.health <= 0]
        dead_enemy = [m for m in s.opponent.board if m.health <= 0]

        if not dead_friendly and not dead_enemy:
            break

        # Step 2: Simultaneous removal
        s.board = [m for m in s.board if m.health > 0]
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        # Step 3: Resolve deathrattles in play order
        # (friendly left-to-right first, then enemy left-to-right)
        dead_queue = []
        for m in dead_friendly:
            dead_queue.append(m)
        for m in dead_enemy:
            dead_queue.append(m)

        if dead_queue:
            s = _execute_deathrattles(s, dead_queue)

    # Step 5: Reborn (preserves taunt — Hearthstone rule fix P1-6)
    s = _apply_reborn(s)

    # Final cleanup: remove anything still at health <= 0
    s.board = [m for m in s.board if m.health > 0]
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s


def _execute_deathrattles(state: "GameState", dead_queue: list) -> "GameState":
    """Execute deathrattle effects for a list of dead minions in play order."""
    from analysis.abilities.definition import AbilityTrigger
    from analysis.abilities.loader import load_abilities

    s = state
    for minion in dead_queue:
        # Enchantment-based deathrattles
        for ench in list(getattr(minion, "enchantments", [])):
            if ench.trigger_type == "deathrattle" and ench.trigger_effect:
                try:
                    from analysis.engine.mechanics.deathrattle import (
                        _apply_deathrattle_effect,
                    )
                    board_type = "friendly" if minion.owner == "friendly" else "enemy"
                    position = 0
                    s = _apply_deathrattle_effect(
                        s, ench.trigger_effect, board_type, position
                    )
                except Exception as exc:
                    log.debug(
                        "Deathrattle enchantment failed: %s — %s",
                        ench.trigger_effect,
                        exc,
                    )

        # Abilities-based deathrattles
        abilities = getattr(minion, "abilities", [])
        if not abilities:
            card_ref = getattr(minion, "card_ref", None)
            if card_ref is not None:
                abilities = getattr(card_ref, "abilities", [])
            if not abilities:
                card_id = getattr(minion, "card_id", "") or (
                    getattr(card_ref, "card_id", "") if card_ref else ""
                )
                if card_id:
                    abilities = load_abilities(card_id)
                if not abilities:
                    abilities = []

        for ability in abilities:
            if ability.trigger != AbilityTrigger.DEATHRATTLE:
                continue
            if not ability.is_active(s, minion):
                continue
            try:
                s = ability.execute(s, minion)
            except Exception as exc:
                log.debug("Abilities deathrattle failed: %s — %s", ability, exc)

    return s


def _apply_reborn(state: "GameState") -> "GameState":
    """Apply Reborn keyword: revive dead minions as 1/1 with taunt preserved."""
    for m in list(state.board):
        if m.health <= 0 and m.has_reborn:
            m.has_reborn = False
            m.health = 1
            m.max_health = 1
            m.has_attacked_once = False
            m.can_attack = False
            m.has_divine_shield = False
            m.has_stealth = False
            # taunt PRESERVED (Hearthstone rule fix P1-6)

    for m in list(state.opponent.board):
        if m.health <= 0 and m.has_reborn:
            m.has_reborn = False
            m.health = 1
            m.max_health = 1
            m.has_attacked_once = False
            m.can_attack = False
            m.has_divine_shield = False
            m.has_stealth = False
            # taunt PRESERVED

    return state


# ──────────────────────────────────────────────────────────────
# Draw
# ──────────────────────────────────────────────────────────────


def _draw_card(state: "GameState") -> "GameState":
    """Draw a single card. Uses deck_list.pop(0) when available, stub fallback.

    Handles overdraw (hand > 10 burns cards).
    """
    if state.deck_remaining <= 0:
        state.fatigue_damage += 1
        state.hero.hp -= state.fatigue_damage
    else:
        state.deck_remaining -= 1
        if state.deck_list and len(state.deck_list) > 0:
            drawn = state.deck_list.pop(0)
        else:
            drawn = Card(
                dbf_id=0,
                name="Drawn Card",
                cost=0,
                card_type="SPELL",
            )
        if len(state.hand) >= 10:
            pass  # overdraw: card is burned
        else:
            state.hand.append(drawn)
            # Shatter mechanic
            try:
                from analysis.engine.mechanics.shatter import check_shatter_on_draw
                state = check_shatter_on_draw(state, len(state.hand) - 1)
            except (ImportError, AttributeError):
                pass
    return state


def _handle_overdraw(state: "GameState") -> None:
    """Burn excess cards if hand exceeds 10 (in-place)."""
    while len(state.hand) > 10:
        state.hand.pop()


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────


def apply_action(state: "GameState", action: Action) -> "GameState":
    """Apply an action to game state, return updated state.

    Single entry point for all state transitions. Dispatches to the
    appropriate handler based on action type. Uses engine/dispatch.py
    for effect execution and engine/target.py for target resolution.
    """
    s = state.copy()

    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        s = _play_card(s, action)
    elif action.action_type == ActionType.ATTACK:
        s = _attack(s, action)
    elif action.action_type == ActionType.HERO_POWER:
        s = _hero_power(s, action)
    elif action.action_type == ActionType.ACTIVATE_LOCATION:
        s = _activate_location(s, action)
    elif action.action_type == ActionType.HERO_REPLACE:
        s = _hero_replace(s, action)
    elif action.action_type == ActionType.TRANSFORM:
        s = _transform(s, action)
    elif action.action_type == ActionType.END_TURN:
        s = _end_turn(s, action)
    elif action.action_type == ActionType.DISCOVER_PICK:
        s = _discover_pick(s, action)
    elif action.action_type == ActionType.CHOOSE_ONE:
        s = _choose_one(s, action)

    return s


# ──────────────────────────────────────────────────────────────
# Action handlers
# ──────────────────────────────────────────────────────────────


def _play_card(s: "GameState", action: Action) -> "GameState":
    """Handle PLAY and PLAY_WITH_TARGET actions.

    Phases:
    1. Validate and pay all costs
    2. Remove from hand and dispatch by card type
    3. Post-play effects (corrupt, overdraw)
    """
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

    ctype = (card.card_type or "").upper()
    if ctype == "MINION":
        s = _play_minion(s, card, action, card_idx)
    elif ctype == "WEAPON":
        s = _play_weapon(s, card, action)
    elif ctype == "LOCATION":
        s = _play_location(s, card, action)
    elif ctype == "SPELL":
        s = _play_spell(s, card, action)
    elif ctype == "HERO":
        s = _play_hero_card(s, card, action)

    # Phase 3: Post-play effects
    try:
        s = dataclasses.replace(s, last_played_card=card)
    except (TypeError, AttributeError):
        log.debug("apply_action: optional mechanic failed", exc_info=True)

    _handle_overdraw(s)

    try:
        from analysis.search.corrupt import check_corrupt_upgrade
        s = check_corrupt_upgrade(s, card)
    except (ImportError, AttributeError):
        pass

    return s


def _play_minion(s: "GameState", card, action: Action, card_idx: int) -> "GameState":
    """Play a minion card: pay mana (already paid), place on board,
    trigger battlecry via dispatch_batch, resolve deaths."""
    from analysis.abilities.loader import load_abilities

    new_minion = Minion.from_card(card)

    # Hand-transform: replace stats with opponent's last played minion
    _apply_hand_transform(s, card, new_minion)

    pos = min(action.position, len(s.board))
    s.board.insert(pos, new_minion)

    # Load abilities and dispatch via engine/dispatch
    card_id = getattr(card, "card_id", "")
    abilities = load_abilities(card_id) if card_id else getattr(card, "abilities", [])

    from analysis.abilities.definition import AbilityTrigger

    for ability in abilities:
        if ability.trigger == AbilityTrigger.BATTLECRY:
            if ability.is_active(s, new_minion):
                try:
                    effects = ability.effects
                    # Resolve target if needed
                    target = None
                    if effects and effects[0].target is not None:
                        target = best_target(s, effects[0])
                    s = dispatch_batch(s, effects, source=new_minion, target=target)
                except Exception as exc:
                    log.debug(
                        "Battlecry dispatch failed for %s: %s",
                        getattr(card, "name", "?"),
                        exc,
                    )

    # Legacy: choose one
    try:
        from analysis.engine.mechanics.choose_one import is_choose_one, resolve_choose_one
        if is_choose_one(card):
            s = resolve_choose_one(s, card, new_minion)
    except (ImportError, AttributeError):
        pass

    # Legacy: dormant
    try:
        from analysis.engine.mechanics.dormant import is_dormant_card, apply_dormant
        if is_dormant_card(card):
            new_minion = apply_dormant(new_minion, card)
    except (ImportError, AttributeError):
        pass

    # Trigger system
    try:
        from analysis.engine.trigger import TriggerDispatcher
        s = TriggerDispatcher().on_minion_played(s, new_minion, card)
    except (ImportError, AttributeError):
        pass

    # Recompute auras
    try:
        from analysis.engine.aura import recompute_auras
        s = recompute_auras(s)
    except (ImportError, AttributeError):
        pass

    return s


def _play_spell(s: "GameState", card, action: Action) -> "GameState":
    """Play a spell card: pay mana (already paid), dispatch spell effects,
    resolve deaths."""
    from analysis.abilities.loader import load_abilities

    card_id = getattr(card, "card_id", "")
    abilities = load_abilities(card_id) if card_id else getattr(card, "abilities", [])

    from analysis.abilities.definition import AbilityTrigger

    for ability in abilities:
        if ability.trigger in (AbilityTrigger.BATTLECRY, AbilityTrigger.COMBO):
            if ability.is_active(s, None):
                try:
                    effects = ability.effects
                    target = None
                    if effects and effects[0].target is not None:
                        target = best_target(s, effects[0])
                    s = dispatch_batch(s, effects, source=card, target=target)
                except Exception as exc:
                    log.debug(
                        "Spell ability dispatch failed for %s: %s",
                        getattr(card, "name", "?"),
                        exc,
                    )

    # Spell-transform: replace hand cards that copy cast spells
    try:
        from analysis.data.card_effects import get_effects
        for i, hc in enumerate(s.hand):
            if get_effects(hc).has_spell_transform:
                try:
                    new_card = (
                        dataclasses.replace(card)
                        if dataclasses.is_dataclass(card)
                        else card
                    )
                    if hasattr(new_card, "card_id"):
                        new_card.card_id = getattr(card, "card_id", "")
                    s.hand[i] = new_card
                except (TypeError, AttributeError):
                    log.debug("Spell-transform failed", exc_info=True)
                break
    except (ImportError, AttributeError):
        pass

    # Quest activation
    try:
        from analysis.engine.mechanics.quest import parse_quest
        quest = parse_quest(card)
        if quest is not None:
            s.active_quests.append(quest)
    except (ImportError, AttributeError):
        pass

    # Freeze mechanic
    mechanics = set(getattr(card, "mechanics", []) or [])
    etext = (getattr(card, "english_text", "") or "").lower()
    if "FREEZE" in mechanics or "freeze" in etext:
        if s.opponent.board:
            if action.target_index > 0 and action.target_index <= len(s.opponent.board):
                s.opponent.board[action.target_index - 1].frozen_until_next_turn = True
            elif action.target_index == 0 or "all" in etext:
                for em in s.opponent.board:
                    em.frozen_until_next_turn = True

    # Text-based damage dealing for targeted spells (fallback when ability system is unavailable)
    if action.action_type == ActionType.PLAY_WITH_TARGET:
        import re as _re
        card_text = getattr(card, "text", "") or ""
        card_en = getattr(card, "english_text", "") or ""
        dmg_match = _re.search(r'造成\s*(\d+)\s*点?伤害', card_text) or \
                    _re.search(r'[Dd]eal\s+(\d+)\s*damage', card_en)
        if dmg_match:
            dmg = int(dmg_match.group(1))
            spell_power = sum(getattr(m, "spell_power", 0) for m in s.board)
            total_dmg = dmg + spell_power
            tgt = action.target_index
            if tgt == 0:
                # Target enemy hero
                remaining = total_dmg
                if s.opponent.hero.armor > 0:
                    absorbed = min(s.opponent.hero.armor, remaining)
                    s.opponent.hero.armor -= absorbed
                    remaining -= absorbed
                s.opponent.hero.hp -= remaining
            elif tgt > 0:
                # Target enemy minion
                mi = tgt - 1
                if mi < len(s.opponent.board):
                    s.opponent.board[mi].health -= total_dmg

    # Spell cast triggers on friendly minions
    s = _trigger_minion_on_spell_cast(s, card=card)

    # Location cooldown refresh on spell cast (e.g. Nespirah reopens after Fel spell)
    spell_school = getattr(card, "spell_school", "") or ""
    if spell_school and s.locations:
        for loc in s.locations:
            loc_en = getattr(loc, "english_text", "") or ""
            loc_text = getattr(loc, "text", "") or ""
            loc_lower = loc_en.lower()
            if "reopen" in loc_lower:
                # Check if this spell's school matches the location's trigger
                # e.g. "After you cast a Fel spell, reopen."
                import re as _re
                school_match = _re.search(r'cast\s+a\s+(\w+)\s+spell', loc_lower)
                if school_match and school_match.group(1).upper() == spell_school.upper():
                    loc.cooldown_current = 0
            # CN fallback
            if "施放" in loc_text and spell_school:
                import re as _re
                school_cn = {"FEL": "邪能", "FIRE": "火焰", "FROST": "冰霜",
                             "ARCANE": "奥术", "NATURE": "自然", "SHADOW": "暗影",
                             "HOLY": "神圣"}.get(spell_school.upper(), "")
                if school_cn and school_cn in loc_text:
                    loc.cooldown_current = 0

    # Recompute auras
    try:
        from analysis.engine.aura import recompute_auras
        s = recompute_auras(s)
    except (ImportError, AttributeError):
        pass

    return s


def _play_weapon(s: "GameState", card, action: Action) -> "GameState":
    """Play a weapon card: pay mana (already paid), equip weapon."""
    s.hero.weapon = Weapon(
        attack=card.attack,
        health=card.health,
        name=card.name,
    )
    return s


def _play_location(s: "GameState", card, action: Action) -> "GameState":
    """Play a location card: add to locations list on board."""
    try:
        from analysis.engine.mechanics.location import Location

        loc = Location(
            dbf_id=getattr(card, "dbf_id", 0),
            name=card.name,
            cost=getattr(card, "cost", 0),
            durability=getattr(card, "health", 3),
            cooldown_current=0,
            cooldown_max=1,
            text=getattr(card, "text", "") or "",
            english_text=getattr(card, "english_text", "") or "",
            card_id=getattr(card, "card_id", "") or "",
            mechanics=getattr(card, "mechanics", []) or [],
        )
        if not s.location_full():
            s.locations.append(loc)
    except (ImportError, AttributeError):
        log.debug("Location play failed", exc_info=True)
    return s


def _play_hero_card(s: "GameState", card, action: Action) -> "GameState":
    """Handle HERO card replacement."""
    try:
        from analysis.search.engine.mechanics.hero_card_handler import HeroCardHandler
        return HeroCardHandler().apply_hero_card(s, card)
    except (ImportError, AttributeError):
        try:
            from analysis.data.card_effects import get_card_armor
            armor = get_card_armor(card)
        except (ImportError, AttributeError):
            armor = getattr(card, "armor", 0) or 0
        s.hero.armor += armor
        hero_class = getattr(card, "card_class", "") or ""
        if hero_class:
            s.hero.hero_class = hero_class
        s.hero.hero_power_used = False
        s.hero.imbue_level = 0
        return s


# ──────────────────────────────────────────────────────────────
# Attack
# ──────────────────────────────────────────────────────────────


def _attack(s: "GameState", action: Action) -> "GameState":
    """Handle ATTACK action — minion/hero attacks.

    Validates target (taunt), deals damage both ways, resolves deaths
    with corrected Hearthstone semantics.
    """
    if action.source_index == -1:
        s = _hero_weapon_attack(s, action)
    else:
        s = _minion_attack(s, action)

    # Corrected death phase
    s = _resolve_deaths(s)

    # Corpse generation
    try:
        from analysis.search.corpse import gain_corpses, has_double_corpse_gen
        amount = 2 if has_double_corpse_gen(s) else 1
        s = gain_corpses(s, amount)
    except (ImportError, AttributeError):
        pass

    # Recompute auras
    try:
        from analysis.engine.aura import recompute_auras
        s = recompute_auras(s)
    except (ImportError, AttributeError):
        pass

    return s


def _apply_damage_to_hero(hero, damage: int) -> None:
    """Apply damage to a hero, absorbing through armor first."""
    if hero.armor > 0:
        absorbed = min(hero.armor, damage)
        hero.armor -= absorbed
        damage -= absorbed
    if not hero.is_immune:
        hero.hp -= damage


def _hero_weapon_attack(s: "GameState", action: Action) -> "GameState":
    """Handle hero weapon attack (source_index == -1)."""
    weapon = s.hero.weapon
    if weapon is None or weapon.attack <= 0:
        return s

    tgt_idx = action.target_index
    if tgt_idx == 0:
        _apply_damage_to_hero(s.opponent.hero, weapon.attack)
        try:
            from analysis.engine.mechanics.secret import check_secrets
            s = check_secrets(s, "on_attack_hero", {"attacker": None})
        except (ImportError, AttributeError):
            pass
    else:
        enemy_idx = tgt_idx - 1
        if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]
        if target.has_divine_shield:
            target.has_divine_shield = False
        else:
            target.health -= weapon.attack
        _apply_damage_to_hero(s.hero, target.attack)
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    weapon.health -= 1
    if weapon.health <= 0:
        s.hero.weapon = None
    return s


def _minion_attack(s: "GameState", action: Action) -> "GameState":
    """Handle minion attack + combat aftermath."""
    src_idx = action.source_index
    tgt_idx = action.target_index

    if src_idx < 0 or src_idx >= len(s.board):
        return s
    source = s.board[src_idx]

    # Resolve combat
    if tgt_idx == 0:
        # Attack enemy hero
        if not s.opponent.hero.is_immune:
            _apply_damage_to_hero(s.opponent.hero, source.attack)
            if source.has_lifesteal:
                s.hero.hp = min(s.hero.max_hp, s.hero.hp + source.attack)
        try:
            from analysis.engine.mechanics.secret import check_secrets
            s = check_secrets(s, "on_attack_hero", {"attacker": source})
        except (ImportError, AttributeError):
            pass
    else:
        # Attack enemy minion
        enemy_idx = tgt_idx - 1
        if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]

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

    # Break stealth
    for m in s.board:
        if m is source and m.has_stealth:
            m.has_stealth = False
            break

    # Remove obviously dead minions immediately (pre-death-phase cleanup)
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

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


# ──────────────────────────────────────────────────────────────
# Hero power
# ──────────────────────────────────────────────────────────────


def _hero_power(s: "GameState", action: Action) -> "GameState":
    """Use hero power: pay mana, dispatch hero power ability."""
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
        if hasattr(target, "armor") and target.armor > 0:
            absorbed = min(target.armor, damage)
            target.armor -= absorbed
            damage -= absorbed
        target.health -= damage

    # Dispatch hero power via abilities system
    try:
        from analysis.search.imbue import apply_hero_power
        s = apply_hero_power(s)
    except (ImportError, AttributeError):
        pass

    return s


# ──────────────────────────────────────────────────────────────
# End turn
# ──────────────────────────────────────────────────────────────


def _end_turn(s: "GameState", action: Action) -> "GameState":
    """End turn: draw card for next turn, increment turn, reset mana."""
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

    # Draw a card (uses deck_list.pop(0) when available, stub fallback)
    s = _draw_card(s)

    # Increment turn and mana
    s.turn_number += 1
    if s.mana.max_mana < s.mana.max_mana_cap:
        s.mana.max_mana += 1
    s.mana.available = s.mana.max_mana - s.mana.overloaded

    # Clear expired modifiers
    s.mana.modifiers = []
    s.opponent.opp_cost_modifiers = [
        m
        for m in s.opponent.opp_cost_modifiers
        if m[2] not in ("next_spell", "this_turn")
    ]

    # Unfreeze friendly minions
    for m in s.board:
        m.frozen_until_next_turn = False

    # Tick dormant minions
    try:
        from analysis.engine.mechanics.dormant import tick_dormant
        s = tick_dormant(s)
    except (ImportError, AttributeError):
        pass

    s.hero.is_immune = False
    for m in s.board:
        m.has_immune = False

    # Tick location cooldowns
    try:
        from analysis.engine.mechanics.location import tick_location_cooldowns
        s = tick_location_cooldowns(s)
    except (ImportError, AttributeError):
        pass

    # Resolve any deaths from end-of-turn effects
    s = _resolve_deaths(s)

    return s


# ──────────────────────────────────────────────────────────────
# Location activation
# ──────────────────────────────────────────────────────────────


def _activate_location(s: "GameState", action: Action) -> "GameState":
    """Activate location card: pay cooldown, dispatch ability."""
    try:
        from analysis.engine.mechanics.location import activate_location
        s = activate_location(s, action.source_index)
    except (ImportError, AttributeError):
        log.debug("Location activation failed", exc_info=True)
    return s


# ──────────────────────────────────────────────────────────────
# Discover pick
# ──────────────────────────────────────────────────────────────


def _discover_pick(s: "GameState", action: Action) -> "GameState":
    """Pick from discover options."""
    # Discover picks are handled externally; this is a placeholder
    # that updates state with the chosen card if available.
    choice_idx = action.discover_choice_index
    if choice_idx < 0:
        return s

    # If state has discover options stored, pick the chosen one
    discover_options = getattr(s, "_discover_options", [])
    if discover_options and 0 <= choice_idx < len(discover_options):
        chosen = discover_options[choice_idx]
        if len(s.hand) < 10:
            s.hand.append(chosen)

    return s


# ──────────────────────────────────────────────────────────────
# Choose one
# ──────────────────────────────────────────────────────────────


def _choose_one(s: "GameState", action: Action) -> "GameState":
    """Handle CHOOSE_ONE action — apply chosen effect."""
    try:
        from analysis.engine.mechanics.choose_one import resolve_choose_one_effect
        s = resolve_choose_one_effect(s, action)
    except (ImportError, AttributeError):
        log.debug("Choose one resolution failed", exc_info=True)
    return s


# ──────────────────────────────────────────────────────────────
# Hero replace
# ──────────────────────────────────────────────────────────────


def _hero_replace(s: "GameState", action: Action) -> "GameState":
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


# ──────────────────────────────────────────────────────────────
# Transform
# ──────────────────────────────────────────────────────────────


def _transform(s: "GameState", action: Action) -> "GameState":
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


# ──────────────────────────────────────────────────────────────
# Helper: hand transform
# ──────────────────────────────────────────────────────────────


def _apply_hand_transform(s: "GameState", card, minion: Minion) -> None:
    """Check if card has a hand-transform effect and apply it to the minion.

    Hand-transform: "while in your hand, becomes a X/Y copy of opponent's
    last played minion". Replaces the minion's attack/health/name with
    the opponent's last played minion, capped to transform_attack/health.
    """
    try:
        from analysis.data.card_effects import get_effects
        eff = get_effects(card)
    except (ImportError, TypeError):
        eff = None

    if eff is None:
        # Fallback: text-based hand-transform detection
        text = getattr(card, "text", "") or ""
        if not ('手牌' in text and '变成' in text):
            return
        import re as _re
        m = _re.search(r'(\d+)/(\d+)', text)
        if not m:
            return
        ta, th = int(m.group(1)), int(m.group(2))
        opp_last = getattr(s.opponent, "opp_last_played_minion", {})
        if not opp_last or not opp_last.get("name"):
            minion.attack = ta
            minion.health = th
            minion.max_health = th
            return
        minion.name = opp_last["name"]
        minion.card_id = opp_last.get("card_id", "")
        minion.attack = ta
        minion.health = th
        minion.max_health = th
        return

    if not eff.has_hand_transform:
        return
    opp_last = getattr(s.opponent, "opp_last_played_minion", {})
    if not opp_last or not opp_last.get("name"):
        minion.attack = eff.transform_attack
        minion.health = eff.transform_health
        minion.max_health = eff.transform_health
        return
    minion.name = opp_last["name"]
    minion.card_id = opp_last.get("card_id", "")
    minion.attack = eff.transform_attack
    minion.health = eff.transform_health
    minion.max_health = eff.transform_health


# ──────────────────────────────────────────────────────────────
# Helper: spell-cast triggers on friendly minions
# ──────────────────────────────────────────────────────────────


def _trigger_minion_on_spell_cast(s: "GameState", card=None) -> "GameState":
    """After casting a spell, check friendly minions for spell-cast triggers.

    card: the spell just cast (used to check spell_school for FEL-only triggers).
    """
    from analysis.abilities.definition import AbilityTrigger
    from analysis.abilities.loader import load_abilities

    spell_school = getattr(card, "spell_school", "") or "" if card else ""
    is_fel = spell_school.upper() == "FEL"

    for m in s.board:
        if m.health <= 0:
            continue

        trigger_type = getattr(m, "trigger_type", "")
        trigger_effect = getattr(m, "trigger_effect", "")

        # Fast path for token trigger effects
        if trigger_effect == "ADD_RANDOM_NAGA":
            if trigger_type == "ON_FEL_SPELL_CAST" and not is_fel:
                continue
            try:
                from analysis.data.token_cards import get_random_naga, create_naga_card
                naga_data = get_random_naga(max_cost=1)
                naga_card = create_naga_card(naga_data)
                s.hand.append(naga_card)
            except (ImportError, AttributeError):
                pass
            continue

        # General ability-based dispatch
        abilities = getattr(m, "abilities", [])
        if not abilities:
            mid = getattr(m, "card_id", "")
            if mid:
                abilities = load_abilities(mid)
        for ability in abilities:
            if ability.trigger != AbilityTrigger.TRIGGER_VISUAL:
                continue
            if not ability.is_active(s, m):
                continue
            try:
                s = ability.execute(s, m)
            except Exception as exc:
                log.debug(
                    "ON_SPELL_CAST ability failed for %s: %s",
                    getattr(m, "name", "?"),
                    exc,
                )

    return s


def apply_draw(state: "GameState", count: int = 1) -> "GameState":
    """Draw cards from deck. Deals fatigue damage if deck is empty.

    Handles overdraw (hand > 10 burns cards) and shatter mechanic.
    Uses actual deck_list if available, falls back to stub.

    Returns a modified copy of state.
    """
    s = state.copy()
    for _ in range(count):
        if s.deck_remaining <= 0:
            s.fatigue_damage += 1
            s.hero.hp -= s.fatigue_damage
        else:
            s.deck_remaining -= 1
            if s.deck_list and len(s.deck_list) > 0:
                drawn = s.deck_list.pop(0)
            else:
                drawn = Card(
                    dbf_id=0,
                    name="Drawn Card",
                    cost=0,
                    card_type="SPELL",
                )
            if len(s.hand) >= 10:
                pass  # card is burned (overdraw)
            else:
                s.hand.append(drawn)
                try:
                    from analysis.engine.mechanics.shatter import check_shatter_on_draw
                    s = check_shatter_on_draw(s, len(s.hand) - 1)
                except (ImportError, AttributeError):
                    pass
    return s


# ──────────────────────────────────────────────────────────────
# Multi-turn lethal check helper (retained for compatibility)
# ──────────────────────────────────────────────────────────────


def next_turn_lethal_check(state: "GameState") -> bool:
    """Check if lethal is achievable next turn.

    Predict available mana next turn = min(current_max + 1, 10).
    Calculate burst damage potential from hand + board.
    """
    next_mana = min(state.mana.max_mana + 1, state.mana.max_mana_cap)

    minion_burst = sum(m.attack for m in state.board)

    spell_burst = 0
    try:
        from analysis.data.card_effects import get_card_damage
        for c in state.hand:
            ct = getattr(c, "card_type", "").upper()
            if ct == "SPELL" and c.cost <= next_mana:
                dmg = c.total_damage() if hasattr(c, "total_damage") else 0
                if dmg == 0:
                    dmg = get_card_damage(c)
                spell_burst += dmg
    except (ImportError, AttributeError):
        pass

    weapon_burst = 0
    if state.hero.weapon is not None:
        weapon_burst += state.hero.weapon.attack

    total_burst = minion_burst + spell_burst + weapon_burst
    opponent_health = state.opponent.hero.hp + state.opponent.hero.armor

    return total_burst >= opponent_health

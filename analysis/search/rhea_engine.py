#!/usr/bin/env python3
"""rhea_engine.py — RHEA (Rolling Horizon Evolutionary Algorithm) search engine.

Searches for optimal action sequences within a single Hearthstone turn using
evolutionary optimization (population-based, tournament selection, uniform
crossover, mutation).

Usage:
    python3 -m hs_analysis.search.rhea_engine          # run built-in demo
"""

from __future__ import annotations

import copy
import logging
import random
import time
import dataclasses
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import package modules
# ---------------------------------------------------------------------------
from analysis.search.game_state import (
    GameState,
    Minion,
    HeroState,
    ManaState,
    OpponentState,
    Weapon,
)
from analysis.models.card import Card
from analysis.models.phase import detect_phase
from analysis.evaluators.composite import evaluate, evaluate_delta, quick_eval
from analysis.utils.score_provider import load_scores_into_hand

# V9: Layered decision pipeline imports (all optional for graceful degradation)
try:
    from analysis.search.lethal_checker import check_lethal
except ImportError:
    check_lethal = None

try:
    from analysis.search.risk_assessor import RiskAssessor, RiskReport
except ImportError:
    RiskAssessor = None
    RiskReport = None

try:
    from analysis.search.opponent_simulator import OpponentSimulator
except ImportError:
    OpponentSimulator = None

try:
    from analysis.search.action_normalize import normalize_chromosome
except ImportError:
    normalize_chromosome = None

try:
    from analysis.evaluators.composite import (
        evaluate_with_risk,
        evaluate_delta_with_risk,
    )
except ImportError:
    evaluate_with_risk = None
    evaluate_delta_with_risk = None


# ===================================================================
# 1. Action dataclass
# ===================================================================


@dataclass
class Action:
    action_type: str
    card_index: int = -1
    position: int = -1
    source_index: int = -1
    target_index: int = -1
    data: int = 0
    discover_choice_index: int = -1
    step_order: int = 0

    def describe(self, state: Optional[GameState] = None) -> str:
        if self.action_type == "PLAY":
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            tgt = ""
            if self.target_index > 0:
                tgt = f" → 目标#{self.target_index}"
            return f"手牌[{self.card_index}] 打出 [{card_name}]{tgt}"
        elif self.action_type == "PLAY_WITH_TARGET":
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            return f"手牌[{self.card_index}] 定向打出 [{card_name}] → 目标#{self.target_index}"
        elif self.action_type == "ATTACK":
            if self.source_index == -1:
                return f"英雄武器 攻击 目标#{self.target_index}"
            return f"随从#{self.source_index} 攻击 目标#{self.target_index}"
        elif self.action_type == "HERO_POWER":
            return "使用英雄技能"
        elif self.action_type == "END_TURN":
            return "结束回合"
        elif self.action_type == "ACTIVATE_LOCATION":
            return f"激活地标#{self.source_index}"
        elif self.action_type == "HERO_REPLACE":
            card_name = "未知英雄牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = state.hand[self.card_index].name or "英雄牌"
            return f"手牌[{self.card_index}] 替换英雄 [{card_name}]"
        elif self.action_type == "DISCOVER_PICK":
            return f"发现选择#{self.discover_choice_index}"
        elif self.action_type == "TRANSFORM":
            return f"变形 目标#{self.target_index}"
        return f"未知动作({self.action_type})"


# ===================================================================
# 2. enumerate_legal_actions
# ===================================================================


_spell_target_resolver = None


def _get_spell_target_resolver():
    global _spell_target_resolver
    if _spell_target_resolver is None:
        from analysis.search.engine.mechanics.spell_target_resolver import (
            SpellTargetResolver,
        )
        _spell_target_resolver = SpellTargetResolver()
    return _spell_target_resolver


def enumerate_legal_actions(state: GameState) -> List[Action]:
    """Return all legal actions for the given state."""
    actions: List[Action] = []

    # --- PLAY actions ---
    for idx, card in enumerate(state.hand):
        eff_cost = state.mana.effective_cost(card)
        if eff_cost > state.mana.available:
            continue
        if card.card_type.upper() == "MINION":
            if not state.board_full():
                for pos in range(len(state.board) + 1):
                    actions.append(
                        Action(
                            action_type="PLAY",
                            card_index=idx,
                            position=pos,
                        )
                    )
        elif card.card_type.upper() == "HERO":
            actions.append(
                Action(
                    action_type="HERO_REPLACE",
                    card_index=idx,
                )
            )
        elif card.card_type.upper() == "SPELL":
            try:
                targets = _get_spell_target_resolver().resolve_targets(state, card)
                if targets:
                    for tgt in targets:
                        actions.append(
                            Action(
                                action_type="PLAY_WITH_TARGET",
                                card_index=idx,
                                target_index=tgt,
                            )
                        )
                else:
                    actions.append(
                        Action(
                            action_type="PLAY",
                            card_index=idx,
                        )
                    )
            except Exception:
                actions.append(
                    Action(
                        action_type="PLAY",
                        card_index=idx,
                    )
                )
        elif card.card_type.upper() == "WEAPON":
            actions.append(
                Action(
                    action_type="PLAY",
                    card_index=idx,
                )
            )
        elif card.card_type.upper() == "LOCATION":
            if not state.location_full():
                actions.append(
                    Action(
                        action_type="PLAY",
                        card_index=idx,
                        position=0,
                    )
                )

    # --- ATTACK actions ---
    # Check if enemy has taunt minions
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    for src_idx, minion in enumerate(state.board):
        # Can attack if: can_attack flag is set, OR has windfury and has attacked once
        can_act = minion.can_attack or (
            minion.has_windfury and minion.has_attacked_once
        )
        if not can_act:
            continue
        # Frozen minions cannot attack
        if minion.frozen_until_next_turn:
            continue
        # Dormant minions cannot attack
        if minion.is_dormant:
            continue
        # Minions with cant_attack cannot attack
        if minion.cant_attack:
            continue

        if enemy_taunts:
            # Must attack taunt minions — taunt blocks ALL face attacks,
            # including charge minions (charge bypasses summoning sickness, NOT taunt)
            for tgt_idx, _ in enumerate(enemy_taunts):
                # Find the actual index in opponent.board
                real_idx = _find_enemy_minion_index(state, enemy_taunts[tgt_idx])
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=real_idx + 1,  # 1-indexed (0 = hero)
                    )
                )
        else:
            # No taunts: can attack enemy hero or any enemy minion
            # Enemy hero
            can_attack_hero = not minion.has_rush  # Rush can only attack minions
            if can_attack_hero:
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=0,
                    )
                )
            # Enemy minions (skip stealthed)
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=tgt_idx + 1,  # 1-indexed
                    )
                )

    # --- Hero weapon ATTACK ---
    if state.hero.weapon is not None and state.hero.weapon.attack > 0:
        # Hero immune check: immune hero can still attack but doesn't take damage
        if enemy_taunts:
            for t in enemy_taunts:
                real_idx = _find_enemy_minion_index(state, t)
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=-1,
                        target_index=real_idx + 1,
                    )
                )
        else:
            actions.append(
                Action(
                    action_type="ATTACK",
                    source_index=-1,
                    target_index=0,
                )
            )
            # Weapon attack enemy minions (skip stealthed)
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if enemy_minion.has_stealth:
                    continue
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=-1,
                        target_index=tgt_idx + 1,
                    )
                )

    # --- HERO_POWER action ---
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        actions.append(Action(action_type="HERO_POWER"))

    # --- ACTIVATE_LOCATION actions ---
    for loc_idx, loc in enumerate(state.locations):
        if loc.durability > 0 and loc.cooldown_current == 0:
            actions.append(
                Action(
                    action_type="ACTIVATE_LOCATION",
                    source_index=loc_idx,
                )
            )

    # --- END_TURN (always legal) ---
    actions.append(Action(action_type="END_TURN"))

    return actions


def _find_enemy_minion_index(state: GameState, minion: Minion) -> int:
    """Find the index of a minion object in the opponent's board."""
    for i, m in enumerate(state.opponent.board):
        if m is minion:
            return i
    return 0


# ===================================================================
# 3. apply_action
# ===================================================================


def _try_mechanic(state: GameState, module_path: str, func_name: str, *args, **kwargs) -> GameState:
    """Try applying an optional mechanic; return state unchanged on failure."""
    try:
        mod = __import__(module_path, fromlist=[func_name])
        func = getattr(mod, func_name)
        result = func(state, *args, **kwargs)
        return result if isinstance(result, GameState) else state
    except Exception:
        log.debug("apply_action: %s.%s failed", module_path, func_name, exc_info=True)
        return state


def apply_action(state: GameState, action: Action) -> GameState:
    """Apply *action* to a **copy** of *state* and return the modified copy."""
    s = state.copy()

    if action.action_type in ("PLAY", "PLAY_WITH_TARGET"):
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

        if "幸运币" in card.name or "The Coin" in (getattr(card, "ename", "") or ""):
            s.mana.available += 1
            s.mana.add_modifier("temporary_crystal", 1, "this_turn")

        if "伺机待发" in card.name or "Preparation" in (
            getattr(card, "ename", "") or ""
        ):
            s.mana.add_modifier("reduce_next_spell", 3, "next_spell")

        from analysis.data.card_effects import _COST_REDUCE_CN, _COST_REDUCE_EN
        reduce_match = _COST_REDUCE_CN.search(card_text) or _COST_REDUCE_EN.search(card_text)
        if reduce_match and "下一张法术" in card_text:
            s.mana.add_modifier(
                "reduce_next_spell", int(reduce_match.group(1)), "next_spell"
            )

        # V10 Phase 3: Check outcast bonus (before card is removed from hand)
        outcast_active = False
        try:
            from analysis.search.outcast import check_outcast

            outcast_active = check_outcast(s, card_idx, card)
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)
        s.hand.pop(card_idx)

        # Track cards played this turn for combo
        s.cards_played_this_turn.append(card)

        if card.card_type.upper() == "MINION":
            mechanics = set(card.mechanics or [])
            new_minion = Minion(
                dbf_id=card.dbf_id,
                name=card.name,
                attack=card.attack,
                health=card.health,
                max_health=card.health,
                cost=card.cost,
                can_attack="CHARGE" in mechanics,
                has_charge="CHARGE" in mechanics,
                has_rush="RUSH" in mechanics,
                has_taunt="TAUNT" in mechanics,
                has_divine_shield="DIVINE_SHIELD" in mechanics,
                has_windfury="WINDFURY" in mechanics,
                has_stealth="STEALTH" in mechanics,
                has_poisonous="POISONOUS" in mechanics,
                has_lifesteal="LIFESTEAL" in mechanics,
                has_reborn="REBORN" in mechanics,
                has_immune="IMMUNE" in mechanics,
                cant_attack="CANT_ATTACK" in mechanics,
                owner="friendly",
            )
            pos = min(action.position, len(s.board))
            s.board.insert(pos, new_minion)

            # V10 Phase 3: Colossal appendage summoning
            try:
                from analysis.search.colossal import (
                    parse_colossal_value,
                    summon_colossal_appendages,
                )

                if parse_colossal_value(card) > 0:
                    s = summon_colossal_appendages(
                        s, new_minion, card, pos, s.herald_count
                    )
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            s = _try_mechanic(s, "analysis.search.kindred", "apply_kindred", card)
            try:
                from analysis.search.kindred import has_kindred as _has_kindred

                card_text = getattr(card, "text", "") or ""
                if "延系效果会触发两次" in (card_text or ""):
                    from analysis.search.kindred import set_kindred_double

                    s = set_kindred_double(s)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            s = _try_mechanic(s, "analysis.search.battlecry_dispatcher", "dispatch_battlecry", card, new_minion)

            try:
                from analysis.search.choose_one import is_choose_one, resolve_choose_one
                if is_choose_one(card):
                    s = resolve_choose_one(s, card, new_minion)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            try:
                from analysis.search.dormant import is_dormant_card, apply_dormant
                if is_dormant_card(card):
                    new_minion = apply_dormant(new_minion, card)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            try:
                from analysis.search.herald import check_herald, apply_herald
                if check_herald(card):
                    s = apply_herald(s, card)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            try:
                from analysis.search.trigger_system import TriggerDispatcher

                s = TriggerDispatcher().on_minion_played(s, new_minion, card)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

            s = _try_mechanic(s, "analysis.search.aura_engine", "recompute_auras")

        elif card.card_type.upper() == "WEAPON":
            s.hero.weapon = Weapon(
                attack=card.attack,
                health=card.health,
                name=card.name,
            )

        elif card.card_type.upper() == "SPELL":
            try:
                from analysis.utils.spell_simulator import resolve_effects

                s = resolve_effects(s, card, target_index=action.target_index)
            except Exception:
                log.debug("apply_action: spell resolve_effects failed for %s", getattr(card, 'name', '?'), exc_info=True)
            # V10 Phase 3: Activate quest if quest card
            try:
                from analysis.search.quest import parse_quest

                quest = parse_quest(card)
                if quest is not None:
                    s.active_quests.append(quest)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)
            card_text = getattr(card, "text", "") or ""
            if "冻结" in card_text or "FREEZE" in (
                getattr(card, "mechanics", None) or []
            ):
                if s.opponent.board:
                    if action.target_index > 0 and action.target_index <= len(s.opponent.board):
                        # Freeze specific target (e.g., Frostbolt, Polymorph)
                        s.opponent.board[action.target_index - 1].frozen_until_next_turn = True
                    elif action.target_index == 0 or "所有" in card_text or "all" in card_text.lower():
                        # Freeze all enemy minions (e.g., Blizzard, Glacial Mysteries)
                        for em in s.opponent.board:
                            em.frozen_until_next_turn = True
            s = _try_mechanic(s, "analysis.search.aura_engine", "recompute_auras")

        elif card.card_type.upper() == "HERO":
            try:
                from analysis.search.engine.mechanics.hero_card_handler import (
                    HeroCardHandler,
                )

                s = HeroCardHandler().apply_hero_card(s, card)
            except Exception:
                armor = card.effective_armor() if hasattr(card, "effective_armor") else 0
                if armor == 0:
                    from analysis.data.card_effects import get_card_armor
                    armor = get_card_armor(card)
                s.hero.armor += armor
                hero_class = getattr(card, "card_class", "") or ""
                if hero_class:
                    s.hero.hero_class = hero_class
                s.hero.hero_power_used = False
                s.hero.imbue_level = 0
        s = _try_mechanic(s, "analysis.search.imbue", "apply_imbue", card)
        s = _try_mechanic(s, "analysis.search.quest", "track_quest_progress", "PLAY", card)
        if outcast_active:
            s = _try_mechanic(s, "analysis.search.outcast", "apply_outcast_bonus", card_idx, card)
        try:
            from analysis.search.corpse import resolve_corpse_effects
            card_class = getattr(card, "card_class", "") or ""
            if card_class.upper() == "DEATHKNIGHT":
                s = resolve_corpse_effects(s, card)
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)
        try:
            s = dataclasses.replace(s, last_played_card=card)
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)
        s = _try_mechanic(s, "analysis.search.corrupt", "check_corrupt_upgrade", card)
        _handle_overdraw(s)
        # OTHER card types: just removed from hand

    elif action.action_type == "ATTACK":
        src_idx = action.source_index
        tgt_idx = action.target_index

        # Hero weapon attack (source_index == -1)
        if src_idx == -1:
            weapon = s.hero.weapon
            if weapon is None or weapon.attack <= 0:
                return s
            if tgt_idx == 0:
                # Attack enemy hero (check immune)
                # V10 Fix P0-4: damage should reduce armor first
                damage = weapon.attack
                if s.opponent.hero.armor > 0:
                    absorbed = min(s.opponent.hero.armor, damage)
                    s.opponent.hero.armor -= absorbed
                    damage -= absorbed
                if not s.opponent.hero.is_immune:
                    s.opponent.hero.hp -= damage
                # V10 Phase 2: Check opponent secrets (e.g. Explosive Trap)
                try:
                    from analysis.search.secret_triggers import check_secrets

                    s = check_secrets(s, "on_attack_hero", {"attacker": None})
                except Exception:
                    log.debug("apply_action: optional mechanic failed", exc_info=True)
            else:
                enemy_idx = tgt_idx - 1
                if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
                    return s
                target = s.opponent.board[enemy_idx]
                if target.has_divine_shield:
                    target.has_divine_shield = False
                else:
                    target.health -= weapon.attack
                # V10 Fix P0-4: hero damage should reduce armor first
                # Hero takes counter-damage from minion
                damage = target.attack
                if s.hero.armor > 0:
                    absorbed = min(s.hero.armor, damage)
                    s.hero.armor -= absorbed
                    damage -= absorbed
                s.hero.hp -= damage
                # Remove dead enemy minions
                s.opponent.board = [m for m in s.opponent.board if m.health > 0]
            # Reduce weapon durability
            weapon.health -= 1
            if weapon.health <= 0:
                s.hero.weapon = None
            return s

        if src_idx < 0 or src_idx >= len(s.board):
            return s
        source = s.board[src_idx]

        if tgt_idx == 0:
            # V10 Fix P0-4: damage should reduce armor first
            # Check opponent immune
            if s.opponent.hero.is_immune:
                pass  # damage prevented
            else:
                damage = source.attack
                if s.opponent.hero.armor > 0:
                    absorbed = min(s.opponent.hero.armor, damage)
                    s.opponent.hero.armor -= absorbed
                    damage -= absorbed
                s.opponent.hero.hp -= damage
                if source.has_lifesteal:
                    s.hero.hp = min(s.hero.max_hp, s.hero.hp + source.attack)
            s = _try_mechanic(s, "analysis.search.secret_triggers", "check_secrets", "on_attack_hero", {"attacker": source})
        else:
            enemy_idx = tgt_idx - 1
            if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
                return s
            target = s.opponent.board[enemy_idx]

            target_had_divine_shield = target.has_divine_shield
            if target.has_divine_shield:
                target.has_divine_shield = False
            elif target.has_immune:
                pass  # immune prevents all damage
            else:
                target.health -= source.attack

            # Poisonous: instant kill if hit connected (target had no divine shield)
            # V10 Fix P0-3: poisonous should not kill immune targets
            if source.has_poisonous and not target_had_divine_shield and not target.has_immune:
                target.health = 0

            # Counter-attack: deal target attack to source
            if source.has_divine_shield:
                source.has_divine_shield = False
            elif source.has_immune:
                pass  # immune prevents counter damage
            else:
                source.health -= target.attack

            # Lifesteal: heal hero for damage dealt to target
            if source.has_lifesteal:
                actual_damage = source.attack if not target_had_divine_shield else 0
                if actual_damage > 0:
                    s.hero.hp = min(30, s.hero.hp + actual_damage)

            # Remove dead enemy minions
            s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        # Stealth breaks when minion attacks
        for m in s.board:
            if m is source and m.has_stealth:
                m.has_stealth = False
                break

        # Remove dead friendly minions (may have died from counter-attack)
        s.board = [m for m in s.board if m.health > 0]

        # V10 Phase 2: Resolve deathrattles (replaces inline removal above
        # for cases where minions have deathrattle enchantments)
        try:
            from analysis.search.deathrattle import resolve_deaths

            s = resolve_deaths(s)
        except Exception:
            log.debug("apply_action ATTACK: resolve_deaths failed", exc_info=True)

        # Reborn: friendly minions with has_reborn that died resummon as 1/1
        if src_idx != -1:
            for m in list(s.board):
                if m.health <= 0 and m.has_reborn:
                    m.has_reborn = False
                    m.health = 1
                    m.max_health = 1
                    m.has_attacked_once = False
                    m.can_attack = False
                    # Remove combat keywords on reborn
                    m.has_divine_shield = False
                    m.has_stealth = False
                    m.has_taunt = False
            # Remove truly dead minions (health still <= 0 after reborn check)
            s.board = [m for m in s.board if m.health > 0]

        # Reborn for enemy minions
        for m in list(s.opponent.board):
            if m.health <= 0 and m.has_reborn:
                m.has_reborn = False
                m.health = 1
                m.max_health = 1
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        try:
            from analysis.search.corpse import gain_corpses, has_double_corpse_gen
            amount = 2 if has_double_corpse_gen(s) else 1
            s = gain_corpses(s, amount)
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)
        s = _try_mechanic(s, "analysis.search.aura_engine", "recompute_auras")

        # Mark source as having attacked (windfury tracking)
        if src_idx < len(s.board):
            # Source may have been removed if it died
            for m in s.board:
                if m is source:
                    if m.has_windfury and not m.has_attacked_once:
                        # First attack for windfury minion: allow second attack
                        m.has_attacked_once = True
                        # keep can_attack = True for second swing
                    else:
                        m.can_attack = False
                    break
        # If source died, it's already removed above

    elif action.action_type == "HERO_POWER":
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
            # V10 Fix P0-4: hero power damage should reduce armor first
            damage = total_damage
            if target.armor > 0:
                absorbed = min(target.armor, damage)
                target.armor -= absorbed
                damage -= absorbed
            target.health -= damage

        try:
            from analysis.search.imbue import apply_hero_power

            s = apply_hero_power(s)
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)

    elif action.action_type == "ACTIVATE_LOCATION":
        s = _try_mechanic(s, "analysis.search.location", "activate_location", action.source_index)

    elif action.action_type == "HERO_REPLACE":
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
            except Exception:
                armor = getattr(card, "armor", 0) or 0
                s.hero.armor += armor
                hero_class = getattr(card, "card_class", "") or ""
                if hero_class:
                    s.hero.hero_class = hero_class
                s.hero.hero_power_used = False

    elif action.action_type == "TRANSFORM":
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

    elif action.action_type == "END_TURN":
        # Apply overload: this turn's overload_next becomes next turn's overloaded
        s.mana.overloaded = s.mana.overload_next
        s.mana.overload_next = 0
        # Deduct overloaded mana from available
        s.mana.available -= s.mana.overloaded
        # V10 Phase 3: Snapshot races/schools for Kindred tracking (BEFORE clearing)
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
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)
        s.cards_played_this_turn = []
        # Fatigue: if deck is empty, increment and deal damage
        if s.deck_remaining <= 0:
            s.fatigue_damage += 1
            s.hero.hp -= s.fatigue_damage
        s.mana.modifiers = []
        # Unfreeze friendly minions at end of turn
        for m in s.board:
            m.frozen_until_next_turn = False
        s = _try_mechanic(s, "analysis.search.dormant", "tick_dormant")
        s.hero.is_immune = False
        for m in s.board:
            m.has_immune = False
        s = _try_mechanic(s, "analysis.search.location", "tick_location_cooldowns")

    return s


def apply_draw(state: GameState, count: int = 1) -> GameState:
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
            # Create a placeholder drawn card
            drawn = Card(
                dbf_id=0,
                name="Drawn Card",
                cost=0,
                card_type="SPELL",
            )
            # V10: Check if hand is full (overdraw) — burn the card
            if len(s.hand) >= 10:
                pass  # card is burned (not added to hand)
            else:
                s.hand.append(drawn)
                # V10: Check shatter on draw
                try:
                    from analysis.search.shatter import check_shatter_on_draw

                    s = check_shatter_on_draw(s, len(s.hand) - 1)
                except Exception:
                    log.debug("apply_action: optional mechanic failed", exc_info=True)
    return s


def _handle_overdraw(state: GameState) -> None:
    """Burn excess cards if hand exceeds 10 (in-place)."""
    while len(state.hand) > 10:
        state.hand.pop()  # burn the rightmost card


# ===================================================================
# 5. SearchResult dataclass
# ===================================================================


@dataclass
class SearchResult:
    """Result of an RHEA search."""

    best_chromosome: List[Action]
    best_fitness: float
    alternatives: List[Tuple[List[Action], float]]  # top 3 (chromosome, fitness)
    generations_run: int
    time_elapsed: float
    population_diversity: float  # std of fitnesses
    confidence: float  # gap between best and 2nd-best, normalised
    pareto_front: List[Tuple[List[Action], float]] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    def describe(self) -> str:
        """Return a formatted Chinese description of the search result."""
        lines = [
            "====== RHEA 搜索结果 ======",
            f"  运行代数  : {self.generations_run}",
            f"  耗时      : {self.time_elapsed:.2f} ms",
            f"  最佳适应度: {self.best_fitness:+.2f}",
            f"  种群多样性: {self.population_diversity:.4f}",
            f"  置信度    : {self.confidence:.4f}",
        ]
        if self.timings:
            lines.append("  --- 各阶段耗时 ---")
            for k, v in self.timings.items():
                lines.append(f"    {k}: {v:.1f}ms")
        lines.append("")
        lines.append("  --- 最佳动作序列 ---")
        for i, act in enumerate(self.best_chromosome):
            lines.append(f"    {i + 1}. {act.describe()}")
        if self.alternatives:
            lines.append("")
            lines.append("  --- 备选方案 ---")
            for rank, (chromo, fit) in enumerate(self.alternatives, 1):
                desc = " → ".join(a.describe() for a in chromo)
                lines.append(f"    方案{rank} (适应度={fit:+.2f}): {desc}")
        lines.append("=" * 30)
        return "\n".join(lines)


# ===================================================================
# 4. Multi-turn lethal setup helper
# ===================================================================


def next_turn_lethal_check(state: GameState) -> bool:
    """Check if lethal is achievable next turn.

    Predict available mana next turn = min(current_max + 1, 10).
    Calculate burst damage potential from hand + board.
    """
    next_mana = min(state.mana.max_mana + 1, state.mana.max_mana_cap)

    # Burst from minions that can attack next turn
    minion_burst = 0
    for m in state.board:
        minion_burst += m.attack  # all friendly minions can attack next turn

    # Burst from direct damage spells in hand
    spell_burst = 0
    for c in state.hand:
        ct = getattr(c, "card_type", "").upper()
        if ct == "SPELL" and c.cost <= next_mana:
            dmg = c.total_damage() if hasattr(c, "total_damage") else 0
            if dmg == 0:
                from analysis.data.card_effects import get_card_damage
                dmg = get_card_damage(c)
            spell_burst += dmg

    # Weapon burst
    weapon_burst = 0
    if state.hero.weapon is not None:
        weapon_burst += state.hero.weapon.attack

    total_burst = minion_burst + spell_burst + weapon_burst
    opponent_health = state.opponent.hero.hp + state.opponent.hero.armor

    return total_burst >= opponent_health


# ===================================================================
# 5. RHEA Engine
# ===================================================================


class RHEAEngine:
    """Rolling Horizon Evolutionary Algorithm for Hearthstone turn planning.

    V11: Cross-turn planning with adaptive time budgets (3-5s normal / 5-15s complex).

    Time budget allocation:
        Layer 0  Lethal Check     5ms
        Layer 0.5 UTP (beam)      10%
        Layer 1  RHEA evolution    50%
        Phase B  Multi-turn setup  10%
        Opp Sim  Opponent sim      10%
        Phase C  Cross-turn sim    20%
    """

    COMPLEXITY_NORMAL = 0
    COMPLEXITY_HARD = 1

    def __init__(
        self,
        pop_size: int = 50,
        tournament_size: int = 5,
        crossover_rate: float = 0.8,
        mutation_rate: Optional[float] = None,
        elite_count: int = 2,
        max_gens: int = 200,
        time_limit: float = 75.0,
        max_chromosome_length: int = 6,
        cross_turn: bool = True,
    ):
        self.pop_size = pop_size
        self.tournament_size = tournament_size
        self.crossover_rate = crossover_rate
        self.mutation_rate = (
            mutation_rate if mutation_rate is not None else 1.0 / max_chromosome_length
        )
        self.elite_count = elite_count
        self.max_gens = max_gens
        self.time_limit = time_limit
        self.max_chromosome_length = max_chromosome_length
        self.cross_turn = cross_turn
        self._target_diversity = 0.5
        self._adaptive_mutation_rate = self.mutation_rate
        self._time_limit_explicit = time_limit != 75.0

    # ---------------------------------------------------------------
    # Main search entry point
    # ---------------------------------------------------------------

    def search(
        self,
        initial_state: GameState,
        weights: Optional[dict] = None,
    ) -> SearchResult:
        """Run the RHEA search with layered decision pipeline.

        V11: Uses adaptive time budget (3-5s normal / 5-15s hard).
        """
        t_start = time.perf_counter()
        timings = {}

        budget_ms = self._adaptive_time_limit(initial_state)
        budget_s = budget_ms / 1000.0

        load_scores_into_hand(initial_state)

        # ========== Layer 0: Lethal Check (5ms budget) ==========
        t_lethal_start = time.perf_counter()
        if check_lethal is not None:
            try:
                lethal_result = check_lethal(initial_state, time_budget_ms=5.0)
                if lethal_result is not None:
                    lethal_actions = lethal_result + [Action(action_type="END_TURN")]
                    timings['lethal'] = (time.perf_counter() - t_lethal_start) * 1000.0
                    timings['total'] = (time.perf_counter() - t_start) * 1000.0
                    log.info(
                        "RHEA: Turn %d | LETHAL found | %.1fms",
                        initial_state.turn_number, timings['total'],
                    )
                    return SearchResult(
                        best_chromosome=lethal_actions,
                        best_fitness=10000.0,
                        alternatives=[],
                        generations_run=0,
                        time_elapsed=(time.perf_counter() - t_start) * 1000.0,
                        population_diversity=0.0,
                        confidence=1.0,
                        pareto_front=[],
                    )
            except Exception:
                log.warning("RHEA: lethal check failed", exc_info=True)

        # ========== Phase Detection + Adaptive Params ==========
        phase = self._detect_phase(initial_state)
        phase_params = self._get_phase_params(phase)
        desperate = self._is_desperate(initial_state)
        if desperate:
            phase_params["max_gens"] = max(phase_params["max_gens"], 80)
            phase_params["weights"]["w_threat"] = phase_params["weights"].get("w_threat", 1.0) * 2.0
            log.debug("RHEA: desperate mode detected, increasing gens and threat weight")

        # ========== Layer 0.5: UnifiedTacticalPlanner (10% of budget) ==========
        t_utp_start = time.perf_counter()
        utp_plans = None
        if not desperate:
            try:
                from analysis.search.engine.unified_tactical import (
                    UnifiedTacticalPlanner,
                )
                from analysis.search.engine.factors.factor_graph import (
                    FactorGraphEvaluator,
                )
                from analysis.search.engine.factors.factor_base import EvalContext

                fg = FactorGraphEvaluator()
                try:
                    from analysis.search.engine.factors.board_control import BoardControlFactor
                    fg.register(BoardControlFactor())
                except Exception:
                    pass
                try:
                    from analysis.search.engine.factors.lethal_threat import LethalThreatFactor
                    fg.register(LethalThreatFactor())
                except Exception:
                    pass
                try:
                    from analysis.search.engine.factors.tempo import TempoFactor
                    fg.register(TempoFactor())
                except Exception:
                    pass
                try:
                    from analysis.search.engine.factors.value import ValueFactor
                    fg.register(ValueFactor())
                except Exception:
                    pass
                try:
                    from analysis.search.engine.factors.survival import SurvivalFactor
                    fg.register(SurvivalFactor())
                except Exception:
                    pass

                utp = UnifiedTacticalPlanner(
                    evaluator=fg,
                    beam_width=5,
                    max_steps=self.max_chromosome_length,
                    time_budget_ms=budget_ms * 0.10,
                )
                utp_plans = utp.plan(initial_state)

                if utp_plans and utp_plans[0].state_after.is_lethal():
                    best_plan = utp_plans[0]
                    timings['utp'] = (time.perf_counter() - t_utp_start) * 1000.0
                    timings['total'] = (time.perf_counter() - t_start) * 1000.0
                    log.info(
                        "RHEA: Turn %d | UTP LETHAL | %.1fms",
                        initial_state.turn_number, timings['total'],
                    )
                    return SearchResult(
                        best_chromosome=best_plan.actions,
                        best_fitness=10000.0,
                        alternatives=[
                            (p.actions, p.score) for p in utp_plans[1:4]
                        ],
                        generations_run=0,
                        time_elapsed=timings['total'],
                        population_diversity=0.0,
                        confidence=1.0,
                        pareto_front=[],
                    )
            except Exception:
                log.debug("RHEA: UnifiedTacticalPlanner failed, falling back to RHEA", exc_info=True)

        timings['utp'] = (time.perf_counter() - t_utp_start) * 1000.0

        # Override instance params with phase-appropriate ones
        saved_pop_size = self.pop_size
        saved_max_gens = self.max_gens
        saved_max_chrom_len = self.max_chromosome_length

        self.pop_size = phase_params["pop_size"]
        self.max_gens = phase_params["max_gens"]
        self.max_chromosome_length = phase_params["max_chromosome_length"]

        effective_weights = {**phase_params["weights"], **(weights or {})}

        # ========== Layer 1: RHEA Evolutionary Search (50% of budget) ==========
        t_rhea_start = time.perf_counter()
        risk_report = None
        if RiskAssessor is not None:
            try:
                assessor = RiskAssessor()
                risk_report = assessor.assess(initial_state)
            except Exception:
                log.debug("RHEA: risk assessment failed", exc_info=True)
        population = self._init_population(initial_state)

        if utp_plans:
            for i, plan in enumerate(utp_plans[: min(3, len(population))]):
                if plan.actions:
                    population[i] = list(plan.actions)

        fitnesses: List[float] = [
            self._evaluate_chromosome(
                initial_state, chromo, effective_weights, risk_report
            )
            for chromo in population
        ]

        best_ever = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
        best_ever_chromo = list(population[best_ever])
        best_ever_fit = fitnesses[best_ever]

        gen = 0
        rhea_budget_ms = budget_ms * 0.50
        for gen in range(1, self.max_gens + 1):
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            if elapsed_ms >= rhea_budget_ms:
                break

            indexed = sorted(
                range(len(fitnesses)),
                key=lambda i: fitnesses[i],
                reverse=True,
            )

            new_pop: List[List[Action]] = []
            for ei in indexed[: self.elite_count]:
                new_pop.append(list(population[ei]))

            while len(new_pop) < self.pop_size:
                parent1 = self._tournament_select(population, fitnesses)
                parent2 = self._tournament_select(population, fitnesses)

                if random.random() < self.crossover_rate:
                    child = self._crossover(parent1, parent2, initial_state)
                else:
                    child = list(parent1)

                child = self._mutate(child, initial_state)
                new_pop.append(child)

            population = new_pop
            fitnesses = [
                self._evaluate_chromosome(
                    initial_state, chromo, effective_weights, risk_report
                )
                for chromo in population
            ]

            gen_best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
            if fitnesses[gen_best_idx] > best_ever_fit:
                best_ever_fit = fitnesses[gen_best_idx]
                best_ever_chromo = list(population[gen_best_idx])

        # ---- Phase B: Multi-turn lethal setup bonus (10% of budget) ----
        t_phase_b_start = time.perf_counter()
        try:
            phase_b_start = time.perf_counter()
            phase_b_budget_s = budget_s * 0.10

            indexed_by_fitness = sorted(
                range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
            )
            top3_indices = indexed_by_fitness[:3]

            for idx in top3_indices:
                elapsed_b = time.perf_counter() - phase_b_start
                if elapsed_b >= phase_b_budget_s:
                    break

                end_state = self._replay_chromosome(initial_state, population[idx])

                if end_state is not None and not end_state.is_lethal():
                    if next_turn_lethal_check(end_state):
                        fitnesses[idx] += 5000.0
                        if fitnesses[idx] > best_ever_fit:
                            best_ever_fit = fitnesses[idx]
                            best_ever_chromo = list(population[idx])
        except Exception:
            log.debug("RHEA: Phase B failed", exc_info=True)

        timings['phase_b'] = (time.perf_counter() - t_phase_b_start) * 1000.0

        # ---- Opponent Simulation (10% of budget) ----
        t_opp_start = time.perf_counter()
        if OpponentSimulator is not None:
            try:
                sim = OpponentSimulator()
                opp_budget_ms = budget_ms * 0.10
                opp_start = time.perf_counter()

                indexed_sorted = sorted(
                    range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
                )
                top_k = indexed_sorted[:5]

                for idx in top_k:
                    if (time.perf_counter() - opp_start) * 1000.0 >= opp_budget_ms:
                        break

                    end_state = self._replay_chromosome(initial_state, population[idx])

                    if end_state is not None:
                        opp_result = sim.simulate_best_response(
                            end_state, time_budget_ms=opp_budget_ms / 5.0
                        )
                        resilience_penalty = (
                            1.0 - opp_result.board_resilience_delta
                        ) * 200.0
                        fitnesses[idx] -= resilience_penalty
                        if opp_result.lethal_exposure:
                            fitnesses[idx] -= 2000.0

                        if fitnesses[idx] > best_ever_fit:
                            best_ever_fit = fitnesses[idx]
                            best_ever_chromo = list(population[idx])
            except Exception:
                log.debug("RHEA: Opponent sim failed", exc_info=True)

        timings['opp_sim'] = (time.perf_counter() - t_opp_start) * 1000.0

        # ---- Phase C: Cross-turn simulation (20% of budget) ----
        t_cross_start = time.perf_counter()
        if self.cross_turn:
            try:
                self._cross_turn_evaluation(
                    initial_state, population, fitnesses,
                    effective_weights, budget_s * 0.20, t_start,
                )
                gen_best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
                if fitnesses[gen_best_idx] > best_ever_fit:
                    best_ever_fit = fitnesses[gen_best_idx]
                    best_ever_chromo = list(population[gen_best_idx])
            except Exception:
                log.debug("RHEA: Phase C cross-turn failed", exc_info=True)

        timings['cross_turn'] = (time.perf_counter() - t_cross_start) * 1000.0

        # ========== Restore original params ==========
        self.pop_size = saved_pop_size
        self.max_gens = saved_max_gens
        self.max_chromosome_length = saved_max_chrom_len

        # ========== Layer 3: Selection & Confidence ==========
        # Compute diversity
        mean_f = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0
        variance = (
            sum((f - mean_f) ** 2 for f in fitnesses) / len(fitnesses)
            if fitnesses
            else 0.0
        )
        diversity = variance**0.5

        if diversity < self._target_diversity * 0.5:
            self._adaptive_mutation_rate = min(self.mutation_rate * 2.0, 1.0)
        elif diversity > self._target_diversity * 2.0:
            self._adaptive_mutation_rate = max(self.mutation_rate * 0.5, 0.01)
        else:
            self._adaptive_mutation_rate = self.mutation_rate

        sorted_fits = sorted(fitnesses, reverse=True)
        # V10 Fix P1-9: negative fitness confidence fix
        if len(sorted_fits) >= 2:
            if sorted_fits[0] == 0:
                confidence = 0.5
            elif sorted_fits[1] < 0 and sorted_fits[0] > 0:
                confidence = 1.0  # clearly positive vs negative
            else:
                ratio = sorted_fits[1] / sorted_fits[0] if sorted_fits[0] != 0 else 0
                confidence = max(0.0, min(1.0, 1.0 - ratio))
        else:
            confidence = 1.0

        indexed_sorted = sorted(
            range(len(fitnesses)),
            key=lambda i: fitnesses[i],
            reverse=True,
        )
        alternatives: List[Tuple[List[Action], float]] = []
        for idx in indexed_sorted:
            chromo = population[idx]
            if len(alternatives) >= 3:
                break
            if population[idx] is not population[indexed_sorted[0]]:
                alternatives.append((list(chromo), fitnesses[idx]))

        elapsed = (time.perf_counter() - t_start) * 1000.0

        # Pareto front
        pareto_front_list: List[Tuple[List[Action], float]] = []
        try:
            scored = []
            for i, chromo in enumerate(population):
                end_state = self._replay_chromosome(initial_state, chromo)
                if end_state is not None:
                    try:
                        delta = evaluate(end_state) - evaluate(initial_state)
                        scored.append((delta, i))
                    except Exception:
                        log.debug("pareto: evaluate failed", exc_info=True)

            scored.sort(key=lambda x: -x[0])
            for score_val, idx in scored[:5]:
                pareto_front_list.append((list(population[idx]), score_val))
        except Exception:
            log.debug("apply_action: optional mechanic failed", exc_info=True)

        timings['total'] = (time.perf_counter() - t_start) * 1000.0
        timings['rhea'] = (t_phase_b_start - t_rhea_start) * 1000.0

        complexity_str = "HARD" if self._assess_complexity(initial_state) else "NORMAL"
        log.info(
            "RHEA: Turn %d | %s | phase=%s | pop=%d gens=%d/%d | "
            "score=%.2f | conf=%.2f | div=%.2f | "
            "budget=%.0fms total=%.0fms [utp=%.0f rhea=%.0f phaseB=%.0f oppSim=%.0f crossTurn=%.0f]",
            initial_state.turn_number,
            complexity_str,
            phase,
            self.pop_size, gen, self.max_gens,
            best_ever_fit, confidence, diversity,
            budget_ms, timings['total'],
            timings.get('utp', 0),
            timings.get('rhea', 0),
            timings.get('phase_b', 0),
            timings.get('opp_sim', 0),
            timings.get('cross_turn', 0),
        )

        return SearchResult(
            best_chromosome=best_ever_chromo,
            best_fitness=best_ever_fit,
            alternatives=alternatives,
            generations_run=gen,
            time_elapsed=elapsed,
            population_diversity=diversity,
            confidence=confidence,
            pareto_front=pareto_front_list,
            timings=timings,
        )

    # ---------------------------------------------------------------
    # Population initialisation
    # ---------------------------------------------------------------

    def _assess_complexity(self, state: GameState) -> int:
        """Assess board complexity to determine time budget tier.

        Returns COMPLEXITY_NORMAL (0) or COMPLEXITY_HARD (1).

        Factors: board size, hand size, mana available, secrets, lethal proximity.
        """
        score = 0

        board_total = len(state.board) + len(state.opponent.board)
        score += board_total * 2

        score += len(state.hand) * 2

        score += state.mana.available * 3

        if state.opponent.secrets:
            score += len(state.opponent.secrets) * 5

        opp_health = state.opponent.hero.hp + state.opponent.hero.armor
        our_attack = sum(m.attack for m in state.board)
        if our_attack > 0 and opp_health <= our_attack + 10:
            score += 8

        our_health = state.hero.hp + state.hero.armor
        opp_attack = sum(m.attack for m in state.opponent.board)
        if opp_attack > 0 and our_health <= opp_attack + 5:
            score += 10

        if state.mana.available >= 8:
            score += 5

        if state.opponent.hand_count >= 6:
            score += 3

        for m in state.board:
            if m.has_windfury or m.has_mega_windfury:
                score += 3
            if m.has_divine_shield:
                score += 2

        threshold = 35
        return self.COMPLEXITY_HARD if score >= threshold else self.COMPLEXITY_NORMAL

    def _adaptive_time_limit(self, state: GameState) -> float:
        """Compute adaptive time limit in ms based on board complexity.

        Normal: 3000-5000ms, Hard: 5000-15000ms.
        Uses turn number to scale within tiers.
        """
        complexity = self._assess_complexity(state)
        turn = max(state.turn_number, 1)

        if complexity == self.COMPLEXITY_HARD:
            base = 5000.0
            ceiling = 15000.0
            turn_scale = min(turn / 15.0, 1.0)
            budget = base + (ceiling - base) * turn_scale
        else:
            base = 3000.0
            ceiling = 5000.0
            turn_scale = min(turn / 12.0, 1.0)
            budget = base + (ceiling - base) * turn_scale

        if self._time_limit_explicit:
            budget = self.time_limit

        log.debug(
            "RHEA: complexity=%s turn=%d budget=%.0fms",
            "HARD" if complexity else "NORMAL",
            turn,
            budget,
        )
        return budget

    def _detect_phase(self, state: GameState) -> str:
        """Detect game phase using unified Phase enum."""
        return detect_phase(state.turn_number).value

    def _get_phase_params(self, phase: str) -> dict:
        """Get search parameters for game phase."""
        params = {
            "early": {
                "pop_size": 30,
                "max_gens": 100,
                "max_chromosome_length": 4,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 0.8,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
            "mid": {
                "pop_size": 50,
                "max_gens": 200,
                "max_chromosome_length": 6,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 1.5,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
            "late": {
                "pop_size": 60,
                "max_gens": 150,
                "max_chromosome_length": 8,
                "weights": {
                    "w_hand": 1.0,
                    "w_board": 1.0,
                    "w_threat": 2.0,
                    "w_lingering": 0.8,
                    "w_trigger": 0.5,
                },
            },
        }
        return params.get(phase, params["mid"])

    @staticmethod
    def _replay_chromosome(
        initial_state: GameState, chromo: List[Action]
    ) -> Optional[GameState]:
        """Replay a chromosome from initial_state and return end state.

        Returns None if any action is invalid during replay.
        """
        end_state = initial_state.copy()
        for action in chromo:
            legal = enumerate_legal_actions(end_state)
            if not _action_in_list(action, legal):
                return None
            end_state = apply_action(end_state, action)
        return end_state

    def _is_desperate(self, state: GameState) -> bool:
        """Detect if we are in a desperate situation (extreme board disadvantage)."""
        friendly_board_power = sum(m.attack + m.health for m in state.board)
        enemy_board_power = sum(m.attack + m.health for m in state.opponent.board)
        if state.opponent.board and not state.board and enemy_board_power > 15:
            return True
        if enemy_board_power > friendly_board_power * 3 + 10:
            return True
        if state.hero.hp <= 10 and enemy_board_power > 10:
            return True
        return False

    def _cross_turn_evaluation(
        self,
        initial_state: GameState,
        population: List[List[Action]],
        fitnesses: List[float],
        weights: dict,
        budget_s: float,
        t_start: float,
    ) -> None:
        """Phase C: Cross-turn simulation for top-K chromosomes.

        For each top candidate:
        1. Replay chromosome → end_state (our turn)
        2. Simulate opponent's best response → opp_end_state
        3. Simulate our next turn (draw + greedy plan) → next_turn_value
        4. Adjust fitness += alpha * (next_turn_value - current_value)

        Modifies fitnesses in-place.
        """
        deadline = time.perf_counter() + budget_s * 0.9

        indexed = sorted(
            range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True
        )
        top_k = indexed[:5]

        sim = None
        if OpponentSimulator is not None:
            sim = OpponentSimulator()

        alpha = 0.3

        for idx in top_k:
            if time.perf_counter() >= deadline:
                break

            end_state = self._replay_chromosome(initial_state, population[idx])

            if end_state is None or end_state.is_lethal():
                continue

            opp_end = self._simulate_opponent_response(end_state, sim, deadline)
            if opp_end is None:
                continue

            next_value = self._simulate_our_next_turn(opp_end, deadline)
            if next_value is None:
                continue

            current_value = evaluate(end_state, weights)
            cross_turn_delta = next_value - current_value
            fitnesses[idx] += alpha * cross_turn_delta

            if sim is not None:
                opp_result = sim.simulate_best_response(
                    end_state, time_budget_ms=50.0
                )
                if opp_result.lethal_exposure:
                    fitnesses[idx] -= 1500.0

    def _simulate_opponent_response(
        self,
        state: GameState,
        sim: Optional['OpponentSimulator'],
        deadline: float,
    ) -> Optional[GameState]:
        """Simulate opponent's best response to our turn end state.

        Creates a flipped perspective state, applies greedy opponent actions,
        then flips back. Uses known opponent cards when available.
        """
        if time.perf_counter() >= deadline:
            return None

        opp_state = state.copy()

        next_mana = min(opp_state.mana.max_mana + 1, opp_state.mana.max_mana_cap)
        opp_mana_available = next_mana - opp_state.mana.overloaded

        opp_state.mana.available = max(0, opp_mana_available)
        opp_state.mana.max_mana = next_mana
        opp_state.mana.overloaded = opp_state.mana.overload_next
        opp_state.mana.overload_next = 0

        for m in opp_state.opponent.board:
            if not m.has_rush:
                m.can_attack = True
            m.has_attacked_once = False

        opp_state.hero.is_immune = False
        for m in opp_state.board:
            m.frozen_until_next_turn = False
            m.has_immune = False

        if opp_state.deck_remaining > 0:
            opp_state.deck_remaining -= 1

        return opp_state

    def _simulate_our_next_turn(
        self,
        state: GameState,
        deadline: float,
    ) -> Optional[float]:
        """Simulate our next turn value after opponent's response.

        Applies turn transition (draw, mana refill), then evaluates
        the resulting state as a proxy for next-turn potential.
        """
        if time.perf_counter() >= deadline:
            return None

        next_state = state.copy()

        next_mana = min(next_state.mana.max_mana + 1, next_state.mana.max_mana_cap)
        next_state.mana.max_mana = next_mana
        next_state.mana.available = max(0, next_mana - next_state.mana.overloaded)
        next_state.mana.overloaded = next_state.mana.overload_next
        next_state.mana.overload_next = 0
        next_state.mana.modifiers = []

        for m in next_state.board:
            m.can_attack = True
            m.has_attacked_once = False
            m.frozen_until_next_turn = False
            m.has_immune = False

        if next_state.deck_remaining > 0:
            next_state.deck_remaining -= 1

        next_state.turn_number += 1

        return evaluate(next_state)

    def _init_population(self, state: GameState) -> List[List[Action]]:
        """Create initial population of random legal action sequences."""
        population: List[List[Action]] = []
        for _ in range(self.pop_size):
            chromo = self._random_chromosome(state)
            # V9: normalize to eliminate equivalent orderings
            if normalize_chromosome is not None:
                try:
                    chromo = normalize_chromosome(chromo, state)
                except Exception:
                    log.debug("apply_action: optional mechanic failed", exc_info=True)
            population.append(chromo)
        return population

    def _random_chromosome(self, state: GameState) -> List[Action]:
        """Generate one random legal action sequence ending with END_TURN."""
        chromo: List[Action] = []
        current = state.copy()

        for _ in range(self.max_chromosome_length):
            legal = enumerate_legal_actions(current)
            non_end = [a for a in legal if a.action_type != "END_TURN"]

            if not non_end:
                # Only END_TURN available or nothing to do
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            # Randomly pick an action (including END_TURN with small probability)
            if random.random() < 0.15:
                # Sometimes just end the sequence early
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            action = random.choice(non_end)
            chromo.append(action)
            current = apply_action(current, action)

        # Ensure sequence ends with END_TURN
        if not chromo or chromo[-1].action_type != "END_TURN":
            chromo.append(Action(action_type="END_TURN"))

        return chromo

    # ---------------------------------------------------------------
    # Fitness evaluation
    # ---------------------------------------------------------------

    def _evaluate_chromosome(
        self,
        initial_state: GameState,
        chromo: List[Action],
        weights: Optional[dict],
        risk_report=None,
    ) -> float:
        """Apply all actions and return evaluate_delta.

        Returns -9999.0 if any action is invalid.
        Uses lazy validation: skip intermediate enumerate_legal_actions
        and only check action validity against the current hand/mana state.
        """
        current = initial_state
        legal_cache = enumerate_legal_actions(current)
        legal_action_keys = {_action_key(a) for a in legal_cache}

        for action in chromo:
            ak = _action_key(action)
            if ak not in legal_action_keys:
                return -9999.0

            current = apply_action(current, action)
            if current.is_lethal():
                return 10000.0

            legal_cache = enumerate_legal_actions(current)
            legal_action_keys = {_action_key(a) for a in legal_cache}

        if evaluate_delta_with_risk is not None and risk_report is not None:
            try:
                return evaluate_delta_with_risk(
                    initial_state, current, weights, risk_report
                )
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return evaluate_delta(initial_state, current, weights)

    # ---------------------------------------------------------------
    # Tournament selection
    # ---------------------------------------------------------------

    def _tournament_select(
        self,
        population: List[List[Action]],
        fitnesses: List[float],
    ) -> List[Action]:
        """Pick tournament_size random individuals; return the fittest."""
        candidates = random.sample(
            range(len(population)),
            min(self.tournament_size, len(population)),
        )
        best = max(candidates, key=lambda i: fitnesses[i])
        return population[best]

    # ---------------------------------------------------------------
    # Crossover
    # ---------------------------------------------------------------

    def _crossover(
        self,
        parent1: List[Action],
        parent2: List[Action],
        state: GameState,
    ) -> List[Action]:
        """Sequence-preserving n-point crossover.

        Pick 1-2 crossover points and swap contiguous subsequence.
        Validate child chromosome; fall back to cloning fitter parent if invalid.
        """
        if not parent1 or not parent2:
            return list(parent1) if parent1 else list(parent2)

        # Pick crossover point(s)
        max_len = min(len(parent1), len(parent2))
        if max_len <= 1:
            return copy.deepcopy(parent1)

        # Single crossover point
        cp = random.randint(1, max_len - 1)

        # Child = first part of p1 + second part of p2
        child = [copy.deepcopy(a) for a in parent1[:cp]]
        child += [copy.deepcopy(a) for a in parent2[cp:]]

        # Ensure child ends with END_TURN
        if child and child[-1].action_type != "END_TURN":
            child.append(Action(action_type="END_TURN"))

        # V9: normalize crossover children
        if normalize_chromosome is not None:
            try:
                child = normalize_chromosome(child, state)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return child

    # ---------------------------------------------------------------
    # Chromosome validation
    # ---------------------------------------------------------------

    def _validate_chromosome(self, state: GameState, chromosome: List[Action]) -> bool:
        """Replay chromosome from state; return True if all actions legal in sequence."""
        current = state.copy()
        for action in chromosome:
            legal = enumerate_legal_actions(current)
            if not _action_in_list(action, legal):
                return False
            current = apply_action(current, action)
        return True

    # ---------------------------------------------------------------
    # Mutation
    # ---------------------------------------------------------------

    def _mutate(
        self,
        chromo: List[Action],
        state: GameState,
    ) -> List[Action]:
        """With probability mutation_rate, replace a random gene."""
        result = [copy.deepcopy(a) for a in chromo]

        if random.random() < self._adaptive_mutation_rate and result:
            # Pick a random position to mutate
            pos = random.randrange(len(result))

            # For simplicity, regenerate a random action for that position
            # by replaying the chromosome up to that position to get the state
            current = state.copy()
            for i in range(pos):
                legal = enumerate_legal_actions(current)
                act = result[i]
                if _action_in_list(act, legal):
                    current = apply_action(current, act)
                else:
                    break

            legal = enumerate_legal_actions(current)
            if legal:
                result[pos] = random.choice(legal)

        # V9: normalize after mutation
        if normalize_chromosome is not None:
            try:
                result = normalize_chromosome(result, state)
            except Exception:
                log.debug("apply_action: optional mechanic failed", exc_info=True)

        return result


# ===================================================================
# Helper: action-in-list comparison
# ===================================================================


def _action_key(action: Action) -> tuple:
    return (
        action.action_type,
        action.card_index,
        action.position,
        action.source_index,
        action.target_index,
    )


def _action_in_list(action: Action, legal: List[Action]) -> bool:
    ak = _action_key(action)
    return any(_action_key(la) == ak for la in legal)


# ===================================================================
# 6. __main__ demo
# ===================================================================


def _build_demo_state() -> GameState:
    """Build a sample game state for the demo."""
    return GameState(
        hero=HeroState(
            hp=25,
            armor=2,
            hero_class="MAGE",
            hero_power_used=False,
        ),
        mana=ManaState(available=8, max_mana=8),
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
            Minion(
                dbf_id=1002,
                name="Tar Creeper",
                attack=1,
                health=5,
                max_health=5,
                cost=3,
                can_attack=True,
                has_taunt=True,
                owner="friendly",
            ),
            Minion(
                dbf_id=1003,
                name="Southsea Deckhand",
                attack=2,
                health=1,
                max_health=1,
                cost=1,
                can_attack=True,
                has_charge=True,
                owner="friendly",
            ),
        ],
        hand=[
            Card(dbf_id=2001, name="Frostbolt", cost=2, card_type="SPELL"),
            Card(
                dbf_id=2002,
                name="Boulderfist Ogre",
                cost=6,
                card_type="MINION",
                attack=6,
                health=7,
            ),
            Card(
                dbf_id=2003,
                name="Arcanite Reaper",
                cost=5,
                card_type="WEAPON",
                attack=5,
                health=2,
            ),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=18, armor=0),
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
            hand_count=4,
        ),
        turn_number=8,
    )


def main() -> None:
    print("=" * 60)
    print("RHEA Engine — Demo")
    print("=" * 60)

    state = _build_demo_state()
    print(f"\n初始状态:")
    print(
        f"  英雄 HP={state.hero.hp} 法力={state.mana.available}/{state.mana.max_mana}"
    )
    print(f"  手牌: {[c.name for c in state.hand]}")
    print(f"  友方随从: {[(m.name, m.attack, m.health) for m in state.board]}")
    print(f"  敌方随从: {[(m.name, m.attack, m.health) for m in state.opponent.board]}")
    print(f"  敌方英雄 HP={state.opponent.hero.hp}")

    # Show legal actions
    legal = enumerate_legal_actions(state)
    print(f"\n合法动作 ({len(legal)} 个):")
    for i, a in enumerate(legal):
        print(f"  {i + 1}. {a.describe(state)}")

    # Run RHEA with small parameters for quick demo
    print("\n--- 开始 RHEA 搜索 (pop=20, gens=50) ---")
    t0 = time.perf_counter()

    engine = RHEAEngine(
        pop_size=20,
        max_gens=50,
        time_limit=500.0,  # 500ms budget
        max_chromosome_length=6,
    )
    result = engine.search(state)

    elapsed = (time.perf_counter() - t0) * 1000.0
    print(f"\n搜索完成, 耗时 {elapsed:.1f} ms")
    print(result.describe())

    # Quick sanity checks
    errors: list[str] = []
    if not result.best_chromosome:
        errors.append("FAIL: best_chromosome is empty")
    if result.generations_run <= 0:
        errors.append(f"FAIL: generations_run={result.generations_run}, expected > 0")
    if result.time_elapsed <= 0:
        errors.append(f"FAIL: time_elapsed={result.time_elapsed}, expected > 0")

    # Verify the best chromosome ends with END_TURN
    if result.best_chromosome and result.best_chromosome[-1].action_type != "END_TURN":
        errors.append(
            f"FAIL: best chromosome does not end with END_TURN, "
            f"last action={result.best_chromosome[-1].action_type}"
        )

    # Verify apply_action isolation
    original_hp = state.opponent.hero.hp
    test_state = apply_action(
        state,
        Action(action_type="ATTACK", source_index=0, target_index=0),
    )
    if state.opponent.hero.hp != original_hp:
        errors.append("FAIL: apply_action mutated the original state")

    if errors:
        print("\n❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("\n✅ All sanity checks passed.")


if __name__ == "__main__":
    main()

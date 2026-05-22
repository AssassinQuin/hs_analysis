"""engine/simulation.py — Unified state transition engine.

Single entry point: apply_action(state, action) -> GameState
Uses engine/dispatch.py for effect execution, engine/target.py for target resolution.
Correct Hearthstone death phase semantics.
"""
from __future__ import annotations

import logging
import dataclasses
import re
from typing import TYPE_CHECKING

from analysis.card.abilities.definition import Action, ActionType

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

from analysis.card.engine.state import Minion, Weapon
from analysis.card.models.card import Card

from analysis.card.engine.deterministic import DeterministicRNG

# Opponent v2 SpellDesc executor (extracted module)
from analysis.card.engine import opponent_executor

log = logging.getLogger(__name__)


def _fire_event(event_name: str, state, **kwargs):
    """统一事件触发：同时通知 SpellExecutor 事件总线和 TriggerDispatcher。"""
    try:
        from analysis.card.abilities.executor import SpellExecutor
        state = SpellExecutor.fire_event(event_name, state, **kwargs)
    except (ImportError, AttributeError):
        pass
    return state


def _dispatch_trigger(method_name: str, state, **kwargs):
    """统一 TriggerDispatcher 调用。method_name 如 'on_minion_played'。"""
    try:
        from analysis.card.engine.trigger import get_dispatcher
        handler = getattr(get_dispatcher(), method_name, None)
        if handler:
            state = handler(state, **kwargs)
    except (ImportError, AttributeError):
        pass
    return state


# ──────────────────────────────────────────────────────────────
# Inlined from analysis/search/corpse.py — Corpse resource system
# ──────────────────────────────────────────────────────────────

@dataclasses.dataclass
class CorpseEffect:
    """A parsed corpse cost + effect pair from card text."""
    cost: int
    is_optional: bool
    effect_text: str


_CORPSE_SPEND_RE = re.compile(
    r"Spend\s*(\d+)\s*Corpse(?:s)?"
    r"|Spend\s*up\s*to\s*(\d+)\s*Corpse(?:s)?"
)


def _parse_corpse_effects(card_text: str) -> list[CorpseEffect]:
    """Parse corpse spend requirements from card text."""
    if not card_text:
        return []

    effects: list[CorpseEffect] = []
    text = card_text or ""

    for m in _CORPSE_SPEND_RE.finditer(text):
        spend_exact = m.group(1)
        spend_up_to = m.group(2)

        if spend_up_to:
            effects.append(CorpseEffect(
                cost=int(spend_up_to),
                is_optional=True,
                effect_text=text[m.end():].strip()[:80],
            ))
        elif spend_exact:
            effects.append(CorpseEffect(
                cost=int(spend_exact),
                is_optional=False,
                effect_text=text[m.end():].strip()[:80],
            ))

    return effects


def _gain_corpses(state: "GameState", amount: int) -> "GameState":
    """Add corpses to state."""
    return dataclasses.replace(state, corpses=state.corpses + amount)


def _has_double_corpse_gen(state: "GameState") -> bool:
    """Check if Falric is on the friendly board for double corpse generation."""
    for m in state.board:
        if "Falric" in (m.name or ""):
            return True
    return False


# ──────────────────────────────────────────────────────────────
# Inlined from analysis/search/corrupt.py — Corrupt mechanic
# ──────────────────────────────────────────────────────────────

def _has_corrupt(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    return 'CORRUPT' in mechanics


def _corrupt_upgrade_card(card: Card) -> Card:
    old_cost = getattr(card, 'cost', 0)
    new_cost = old_cost + 1

    return Card(
        dbf_id=getattr(card, 'dbf_id', 0),
        name=getattr(card, 'name', ''),
        cost=new_cost,
        original_cost=new_cost,
        card_type=getattr(card, 'card_type', ''),
        attack=getattr(card, 'attack', 0) + 1,
        health=getattr(card, 'health', 0) + 1,
        text=getattr(card, 'text', ''),
        rarity=getattr(card, 'rarity', ''),
        card_class=getattr(card, 'card_class', ''),
        race=getattr(card, 'race', ''),
        mechanics=[m for m in (getattr(card, 'mechanics', []) or []) if m != 'CORRUPT'],
    )


def _check_corrupt_upgrade(state: "GameState", played_card) -> "GameState":
    played_cost = getattr(played_card, 'cost', 0)
    for i, card in enumerate(state.hand):
        if not _has_corrupt(card):
            continue
        card_cost = getattr(card, 'cost', 0)
        if played_cost > card_cost:
            state.hand[i] = _corrupt_upgrade_card(card)
    return state


# ──────────────────────────────────────────────────────────────
# Inlined from analysis/search/imbue.py — Imbue hero power system
# ──────────────────────────────────────────────────────────────

# TODO: 当 v2 card_abilities_v2.json 补全 11 职业基础英雄技能后，
# 删除此表，_apply_hero_power() 全部走 v2 SpellExecutor 路径。
_IMBUE_HERO_POWERS = {
    "DRUID": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
    },
    "HUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
    },
    "MAGE": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
    },
    "PALADIN": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
    },
    "PRIEST": {
        "effect": "heal",
        "base_heal": 2,
        "scaling": True,
    },
    "ROGUE": {
        "effect": "weapon",
        "base_attack": 1,
        "base_durability": 2,
        "scaling": True,
    },
    "SHAMAN": {
        "effect": "random_totem",
    },
    "WARLOCK": {
        "effect": "damage_self_draw",
        "base_damage": 2,
        "base_draw": 1,
    },
    "WARRIOR": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
    },
    "DEMONHUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
    },
    "DEATHKNIGHT": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
    },
}


def _apply_hero_power(state: "GameState") -> "GameState":
    """Apply the hero power effect based on class and imbue_level.

    If hero.hero_power_card_id is set, dispatches through the v2 abilities
    system (SpellExecutor) instead of the hardcoded _IMBUE_HERO_POWERS table.
    """
    # ── 替换英雄技能：通过 v2 abilities 系统调度 ──
    hero_power_card_id = getattr(state.hero, "hero_power_card_id", "")
    if hero_power_card_id:
        try:
            from analysis.card.abilities.loader_v2 import get_loader_v2
            from analysis.card.abilities.executor import SpellExecutor
            from analysis.card.abilities.model import CardAbility
            loader = get_loader_v2()
            ability = loader.get(hero_power_card_id)
            if ability and ability.has_any:
                state = SpellExecutor._execute_desc(
                    ability.on_play or ability.deathrattle,
                    state, source=state.hero,
                )
                return state
        except (ImportError, AttributeError, TypeError) as e:
            log.warning("替换英雄技能 %s 执行失败: %s", hero_power_card_id, e)
        # fall through if v2 execution fails

    # ── 默认英雄技能：基于职业和灌注等级的硬编码表 ──
    raw_class = getattr(state.hero, "hero_class", "")
    if hasattr(raw_class, "name"):
        hero_class = str(getattr(raw_class, "name")).upper()
    else:
        hero_class = (str(raw_class) if raw_class is not None else "").upper()
    imbue_level = getattr(state.hero, "imbue_level", 0)

    power_info = _IMBUE_HERO_POWERS.get(hero_class)
    if power_info is None:
        # Generic fallback: deal 1 + imbue_level damage
        if state.opponent.board:
            state.opponent.board[0].health -= (1 + imbue_level)
        else:
            state.opponent.hero.hp -= (1 + imbue_level)
        return state

    effect = power_info.get("effect", "")

    if effect == "damage":
        base = power_info.get("base_damage", 1)
        total = base + imbue_level
        if state.opponent.board:
            state.opponent.board[0].health -= total
        else:
            state.opponent.hero.hp -= total

    elif effect == "heal":
        base = power_info.get("base_heal", 2)
        total = base + imbue_level
        state.hero.hp += total

    elif effect == "armor":
        base = power_info.get("base_armor", 2)
        total = base + imbue_level
        state.hero.armor += total

    elif effect == "summon":
        base_atk = power_info.get("base_attack", 1)
        base_hp = power_info.get("base_health", 1)
        atk = base_atk + imbue_level
        hp = base_hp + imbue_level
        if not state.board_full():
            state.board.append(Minion(
                name="Hero Power Minion",
                attack=atk,
                health=hp,
                max_health=hp,
                owner="friendly",
            ))

    elif effect == "weapon":
        base_atk = power_info.get("base_attack", 1)
        base_dur = power_info.get("base_durability", 2)
        atk = base_atk + imbue_level
        state.hero.weapon = Weapon(
            attack=atk,
            health=base_dur,
            name="Hero Power Weapon",
        )

    elif effect == "random_totem":
        if not state.board_full():
            state.board.append(Minion(
                name="Totem",
                attack=0,
                health=1,
                max_health=1,
                owner="friendly",
            ))

    elif effect == "damage_self_draw":
        dmg = power_info.get("base_damage", 2)
        draw_count = power_info.get("base_draw", 1)
        state.hero.hp -= dmg
        for _ in range(draw_count):
            if state.deck_remaining > 0:
                state.deck_remaining -= 1
            else:
                state.fatigue_damage += 1
                state.hero.hp -= state.fatigue_damage

    return state


# ──────────────────────────────────────────────────────────────
# Target resolution helper
# ──────────────────────────────────────────────────────────────


def _resolve_action_target(s: "GameState", action: Action):
    """Resolve action.target_index to a concrete target entity."""
    target = None
    action_target = getattr(action, 'target_index', -1)
    if action_target == 0:
        target = s.opponent.hero if hasattr(s, 'opponent') else None
    elif action_target > 0:
        idx = action_target - 1
        if hasattr(s, 'opponent') and idx < len(s.opponent.board):
            target = s.opponent.board[idx]
    return target


def _is_temporary_mana_effect(text_lower: str) -> bool:
    """Detect 'Gain N Mana Crystal(s) this turn' effect from card text."""
    if "gain" in text_lower and "mana crystal" in text_lower and "this turn" in text_lower:
        return True
    if "gain" in text_lower and "empty mana crystal" in text_lower:
        return True
    return False


def _validate_and_pay_cost(s, card, card_idx: int):
    """Validate card play feasibility and pay all costs (mana, overload, HP, corpses).

    Returns the modified state, or None if the play should be skipped.
    """
    card_text = getattr(card, "text", "") or ""

    # Mana cost
    eff_cost = s.mana.effective_cost(card)
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
        from analysis.card.data.card_effects import get_effects as _get_effects
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
        from analysis.card.data.card_effects import get_card_health_cost
        hp_cost = get_card_health_cost(card)
        if hp_cost > 0:
            if s.hero.hp <= hp_cost:
                return None
            s.hero.hp -= hp_cost
    except (ImportError, AttributeError):
        pass

    # Corpse cost guard
    try:
        corpse_effects = _parse_corpse_effects(card_text)
        for ce in corpse_effects:
            if not ce.is_optional and s.corpses < ce.cost:
                return None
    except (AttributeError, TypeError):
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
    """Execute deathrattle effects: enchantment-based first, then CardPower data-driven."""
    s = state
    for minion in dead_queue:
        # Enchantment-based deathrattles (from trigger attachments)
        for ench in list(getattr(minion, "enchantments", [])):
            if ench.trigger_type == "deathrattle" and ench.trigger_effect:
                try:
                    from analysis.card.engine.mechanics.deathrattle import (
                        _apply_deathrattle_effect,
                    )
                    board_type = "friendly" if minion.owner == "friendly" else "enemy"
                    position = 0
                    s = _apply_deathrattle_effect(
                        s, ench.trigger_effect, board_type, position
                    )
                except Exception as exc:
                    log.debug(
                        "Enchantment deathrattle failed: %s — %s",
                        ench.trigger_effect,
                        exc,
                    )

        # CardPower data-driven deathrattle (old v1 system)
        card_ref = getattr(minion, "card_ref", None)
        power = None
        if card_ref is not None:
            power = getattr(card_ref, "power", None)
        if power is None:
            power = getattr(minion, "_power", None)

        if power is not None and power.has_deathrattle:
            for spell in power.deathrattle:
                try:
                    s = spell.execute(s, source=minion, target=None)
                except Exception as exc:
                    log.debug("CardPower deathrattle failed %s: %s",
                              getattr(minion, "name", "?"), exc)

        # v2 CardAbility deathrattle (from card_abilities_v2.json DEATHRATTLE)
        if card_ref is not None:
            try:
                card_ability = getattr(card_ref, 'ability', None)
                if card_ability is not None and card_ability.deathrattle is not None:
                    if minion.owner == "friendly":
                        # 友方死亡 → player-context executor
                        from analysis.card.abilities.executor import SpellExecutor as FriendlyExecutor
                        s = FriendlyExecutor._execute_desc(
                            card_ability.deathrattle, s, source=minion,
                        )
                    else:
                        # 敌方死亡 → opponent-context executor (friendly=对手, enemy=我方)
                        from analysis.card.engine.opponent_executor import (
                            opponent_execute_spell_desc,
                        )
                        s = opponent_execute_spell_desc(
                            card_ability.deathrattle, s, source=minion,
                        )
            except Exception as exc:
                log.debug("v2 deathrattle failed for %s: %s",
                          getattr(minion, "name", "?"), exc)

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
            drawn.turn_drawn = state.turn_number
            state.hand.append(drawn)
            # Shatter mechanic
            try:
                from analysis.card.engine.mechanics.shatter import check_shatter_on_draw
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

    When s.is_opponent_turn is True, dispatches to opponent-specific
    handlers so card actions use opponent.hand instead of state.hand.
    """
    s = state.copy()

    # ── Opponent turn dispatch ──
    if s.is_opponent_turn:
        s = _apply_opponent_action(s, action)
        s = _resolve_deaths(s)
        return s

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

    # Single death phase: all action types resolve deaths here
    s = _resolve_deaths(s)

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
        s = _check_corrupt_upgrade(s, card)
    except (AttributeError, TypeError):
        pass

    return s


def _play_minion(s: "GameState", card, action: Action, card_idx: int) -> "GameState":
    """Execute a minion card: place on board, trigger v2 SpellExecutor battlecry."""
    new_minion = Minion.from_card(card)

    # Hand-transform: replace attributes with opponent's last played minion
    _apply_hand_transform(s, card, new_minion)

    pos = min(action.position, len(s.board))
    s.board.insert(pos, new_minion)

    # Battlecry dispatch via v2 SpellExecutor (no v1 CardPower fallback)
    target = _resolve_action_target(s, action)
    try:
        from analysis.card.abilities.executor import SpellExecutor
        ability = getattr(card, 'ability', None)
        if ability and ability.has_any and ability.on_play:
            s = SpellExecutor.execute(ability, s, source=new_minion, target=target)
    except Exception as exc:
        log.debug("v2 battlecry failed %s: %s", getattr(card, 'name', '?'), exc)

    # Legacy: choose one
    try:
        from analysis.card.engine.mechanics.choose_one import is_choose_one, resolve_choose_one
        if is_choose_one(card):
            s = resolve_choose_one(s, card, new_minion)
    except (ImportError, AttributeError):
        pass

    # Legacy: dormant
    try:
        from analysis.card.engine.mechanics.dormant import is_dormant_card, apply_dormant
        if is_dormant_card(card):
            new_minion = apply_dormant(new_minion, card)
    except (ImportError, AttributeError):
        pass

    # Trigger system (uses singleton dispatcher for consistent event routing)
    s = _dispatch_trigger('on_minion_played', s, minion=new_minion, card=card)

    # Recompute auras
    try:
        from analysis.card.engine.aura import recompute_auras
        s = recompute_auras(s)
    except (ImportError, AttributeError):
        pass

    return s


def _play_spell(s: "GameState", card, action: Action) -> "GameState":
    """Execute a spell card via v2 SpellExecutor (no v1 fallback)."""
    target = _resolve_action_target(s, action)

    try:
        from analysis.card.abilities.executor import SpellExecutor
        ability = getattr(card, 'ability', None)
        if ability and ability.has_any and ability.on_play:
            s = SpellExecutor.execute(ability, s, source=card, target=target)
    except Exception as exc:
        log.debug("v2 spell execute failed %s: %s", getattr(card, 'name', '?'), exc)

    # Spell-transform: replace hand cards that copy cast spells
    try:
        from analysis.card.data.card_effects import get_effects
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
        from analysis.card.engine.mechanics.quest import parse_quest
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

    # Trigger system: on_spell_cast
    s = _dispatch_trigger('on_spell_cast', s, card=card)

    # Spell cast triggers on friendly minions (+ spellburst)
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
            # English text check (location text may have english_text attr)
            if spell_school:
                loc_en = getattr(loc, "english_text", "") or ""
                if "reopen" in loc_en.lower() and spell_school.upper() in loc_en.upper():
                    loc.cooldown_current = 0

    # Recompute auras
    try:
        from analysis.card.engine.aura import recompute_auras
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
        from analysis.card.engine.mechanics.location import Location

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
    """Handle HERO card placement (armor, class, power upgrade)."""
    try:
        from analysis.card.engine.mechanics.hero_card import HeroCardHandler
        return HeroCardHandler().apply_hero_card(s, card)
    except (ImportError, AttributeError):
        try:
            from analysis.card.data.card_effects import get_card_armor
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

    # Corrected death phase — deferred to apply_action() single _resolve_deaths() call
    # 不立即移除死亡随从 — apply_action() 末尾统一 _resolve_deaths()

    # Corpse generation
    try:
        amount = 2 if _has_double_corpse_gen(s) else 1
        s = _gain_corpses(s, amount)
    except (AttributeError, TypeError):
        pass

    # Recompute auras
    try:
        from analysis.card.engine.aura import recompute_auras
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
            from analysis.card.engine.mechanics.secret import check_secrets
            s = check_secrets(s, "on_attack_hero", {"attacker": None})
        except (ImportError, AttributeError):
            pass
    else:
        enemy_idx = tgt_idx - 1
        if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]
        target_took_damage = not target.has_divine_shield
        if target.has_divine_shield:
            target.has_divine_shield = False
        else:
            target.health -= weapon.attack
        # Frenzy: trigger when target takes damage and survives
        if target_took_damage:
            s = _dispatch_trigger('on_damage_dealt', s, target=target)
        _apply_damage_to_hero(s.hero, target.attack)
        # 不立即移除 — apply_action() 末尾统一 _resolve_deaths()

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
            from analysis.card.engine.mechanics.secret import check_secrets
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
        target_took_damage = False
        if target.has_divine_shield:
            target.has_divine_shield = False
        elif target.has_immune:
            pass
        else:
            target.health -= source.attack
            target_took_damage = True

        # Poisonous: instant kill
        if source.has_poisonous and not target_had_divine_shield and not target.has_immune:
            target.health = 0

        # Frenzy: trigger when target takes non-lethal damage
        if target_took_damage:
            s = _dispatch_trigger('on_damage_dealt', s, target=target)

        # Counter-attack from target
        source_took_damage = False
        if source.has_divine_shield:
            source.has_divine_shield = False
        elif source.has_immune:
            pass
        else:
            source.health -= target.attack
            source_took_damage = True

        # Frenzy: trigger when source takes non-lethal damage
        if source_took_damage:
            s = _dispatch_trigger('on_damage_dealt', s, target=source)

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

    # 不立即移除死亡随从 — apply_action() 末尾统一 _resolve_deaths()
    # 批处理确保亡语正确触发

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
        s = _apply_hero_power(s)
    except (AttributeError, TypeError):
        pass

    # Fire AFTER_HERO_POWER triggers
    s = _fire_event("AFTER_HERO_POWER", s, event_source=s.hero)

    return s


# ──────────────────────────────────────────────────────────────
# End turn
# ──────────────────────────────────────────────────────────────


def _end_turn(s: "GameState", action: Action) -> "GameState":
    """End OUR turn, switch to opponent turn.

    Overload is recorded (affects OUR next turn). Opponent mana is
    estimated from current turn_number. The turn counter and card draw
    are deferred to _opponent_end_turn.
    """
    # Trigger system: on_turn_end
    s = _dispatch_trigger('on_turn_end', s)

    # Apply overload (affects OUR next turn, not opponent's)
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

    # Clear expired modifiers (own modifiers cleared, opponent's persist)
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
        from analysis.card.engine.mechanics.dormant import tick_dormant
        s = tick_dormant(s)
    except (ImportError, AttributeError):
        pass

    s.hero.is_immune = False
    for m in s.board:
        m.has_immune = False

    # Tick location cooldowns
    try:
        from analysis.card.engine.mechanics.location import tick_location_cooldowns
        s = tick_location_cooldowns(s)
    except (ImportError, AttributeError):
        pass

    # Resolve deaths — deferred to apply_action() single _resolve_deaths() call
    # 不立即移除 — apply_action() 末尾统一处理

    # ── Switch to opponent turn ──
    # Turn counter, card draw, and our mana are handled in
    # _opponent_end_turn when the opponent finishes their turn.
    s.is_opponent_turn = True

    # Estimate opponent mana: same crystal count as current turn
    opp_mana = min(s.turn_number, 10)
    s.opponent.mana_available = opp_mana
    s.opponent.mana_max = opp_mana

    return s


# ═══════════════════════════════════════════════════════════════
# Opponent turn handlers
# ═══════════════════════════════════════════════════════════════
# These dispatch when state.is_opponent_turn is True.
# Instead of accessing state.hand (our hand), they use
# state.opponent.hand and state.opponent.board to simulate
# plausible opponent actions during MCTS rollouts.
# ═══════════════════════════════════════════════════════════════


def _apply_opponent_action(s: "GameState", action: Action) -> "GameState":
    """Dispatch opponent actions during is_opponent_turn."""
    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        return _opponent_play_card(s, action)
    elif action.action_type == ActionType.ATTACK:
        return _opponent_attack(s, action)
    elif action.action_type == ActionType.HERO_POWER:
        return _opponent_hero_power(s)
    elif action.action_type == ActionType.END_TURN:
        return _opponent_end_turn(s, action)
    return s


def _opponent_card_effective_cost(card, opp_state: "GameState") -> int:
    """Calculate effective cost for an opponent card, applying opp_cost_modifiers."""
    base = getattr(card, 'cost', 0)
    card_type = (getattr(card, 'card_type', '') or '').upper()
    for mod_type, mod_val, mod_scope in opp_state.opponent.opp_cost_modifiers:
        if mod_type == "opp_spell_increase" and card_type == "SPELL":
            base += mod_val
        elif mod_type == "opp_hero_power_increase":
            pass  # handled separately
    return max(0, base)


def _opponent_play_card(s: "GameState", action: Action) -> "GameState":
    """Opponent plays a card from their hand to their board.

    Incorporates:
    - opp_cost_modifiers for spell cost increases
    - Better spell effect diversity (AOE, heal, buff)
    - Simple battlecry stat buff for minions
    """
    card_idx = action.card_index
    if card_idx < 0 or card_idx >= len(s.opponent.hand):
        return s
    card = s.opponent.hand[card_idx]

    eff_cost = _opponent_card_effective_cost(card, s)
    if eff_cost > s.opponent.mana_available:
        return s
    s.opponent.mana_available -= eff_cost

    # Remove from opponent hand
    s.opponent.hand.pop(card_idx)

    ctype = (getattr(card, 'card_type', '') or '').upper()
    if ctype == 'MINION':
        if len(s.opponent.board) < 7:
            new_minion = Minion.from_card(card)
            pos = min(action.position, len(s.opponent.board))
            new_minion.can_attack = False  # summoning sickness
            new_minion.owner = "enemy"

            # Simple battlecry shim: taunt/token-related buffs
            mechanics = set(getattr(card, 'mechanics', []) or [])
            if 'TAUNT' in mechanics:
                new_minion.has_taunt = True
            if 'RUSH' in mechanics or 'CHARGE' in mechanics:
                new_minion.can_attack = True
            if 'LIFESTEAL' in mechanics:
                new_minion.has_lifesteal = True
            if 'DIVINE_SHIELD' in mechanics:
                new_minion.has_divine_shield = True

            s.opponent.board.insert(pos, new_minion)

            # ── 战吼执行 (v2 SpellDesc 能力系统) ──
            # 使用 card_abilities_v2.json 中的 ON_PLAY 效果，
            # 将效果应用于对手上下文（friendly=对手, enemy=我方）
            try:
                ability = getattr(card, 'ability', None)
                if ability is not None and ability.has_any and ability.on_play is not None:
                    opponent_executor.opponent_execute_spell_desc(ability.on_play, s, source=new_minion)
            except Exception as e:
                log.debug("Opponent battlecry failed for %s: %s", card, e)

    elif ctype == 'SPELL':
        _opponent_play_spell_v2(s, card)
    elif ctype == 'WEAPON':
        s.opponent.hero.weapon = Weapon(
            attack=getattr(card, 'attack', 0),
            health=getattr(card, 'health', 1),
            name=getattr(card, 'name', ''),
        )
    elif ctype == 'HERO':
        armor = getattr(card, 'armor', 0) or 0
        if armor > 0:
            s.opponent.hero.armor += armor
        hp = getattr(card, 'hp', 0) or 0
        if hp > 0:
            s.opponent.hero.hp = min(s.opponent.hero.max_hp, s.opponent.hero.hp + hp)

    # Resolve deaths
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]
    s.board = [m for m in s.board if m.health > 0]

    return s


def _opponent_play_spell_v2(s: "GameState", card) -> None:
    """Opponent spell effects — 优先使用 v2 CardAbility, 回退到文本启发式。"""
    # 优先使用 v2 SpellDesc 能力数据（结构化、精确）
    try:
        ability = getattr(card, 'ability', None)
        if ability is not None and ability.has_any and ability.on_play is not None:
            opponent_executor.opponent_execute_spell_desc(ability.on_play, s, source=card)
            return
    except Exception as e:
        log.debug("Opponent v2 spell failed for %s: %s", card, e)

    # ── Fallback: 文本启发式（原始逻辑） ──
    try:
        from analysis.card.data.card_effects import get_effects
        eff = get_effects(card)
    except (ImportError, AttributeError):
        eff = None

    card_text = (getattr(card, 'text', '') or getattr(card, 'english_text', '') or '').lower()
    mechanics = set(getattr(card, 'mechanics', []) or [])
    school = (getattr(card, 'spell_school', '') or '').upper()

    # 1. Direct damage (highest confidence)
    damage = 0
    if eff and eff.damage > 0:
        damage = eff.damage
    else:
        damage = getattr(card, 'attack', 0)

    if damage > 0:
        # AOE detection: card_text containing "all" + "minions" or "enemy"
        if ('all' in card_text and 'minion' in card_text) or 'deal' in card_text and 'all' in card_text:
            # AOE: damage all our minions
            for m in s.board:
                m.health -= damage
        elif ('aoe' in mechanics or school == 'FIRE' and damage >= 2):
            # Fire school or AOE-tagged spells often have splash
            for m in s.board:
                m.health -= damage
        else:
            # Single target: damage our hero
            _apply_damage_to_hero(s.hero, damage)

    # 2. Healing (card text contains "heal" or "restore")
    heal_amount = getattr(card, 'healing', 0) or 0
    if heal_amount <= 0 and eff and hasattr(eff, 'heal') and eff.heal > 0:
        heal_amount = eff.heal
    if heal_amount <= 0 and ('heal' in card_text or 'restore' in card_text):
        heal_amount = max(2, damage) if damage else 3
    if heal_amount > 0:
        s.opponent.hero.hp = min(s.opponent.hero.max_hp, s.opponent.hero.hp + heal_amount)

    # 3. Armor gain
    armor_val = getattr(card, 'armor', 0) or 0
    if armor_val > 0:
        s.opponent.hero.armor += armor_val

    # 4. Buff own minions (if text contains "give" and "minion")
    if 'give' in card_text and 'minion' in card_text:
        buff_atk = 1 if 'attack' in card_text else 0
        buff_hp = 1 if 'health' in card_text else 0
        if buff_atk > 0 or buff_hp > 0:
            for m in s.opponent.board:
                m.attack += buff_atk
                m.health += buff_hp
                m.max_health += buff_hp

    # 5. Draw detection
    if 'draw' in card_text:
        draw_count = 1
        m = re.search(r'draw\s+(\d+)', card_text)
        if m:
            draw_count = int(m.group(1))
        for _ in range(draw_count):
            s = opponent_executor.opponent_draw_card(s)


def _opponent_attack(s: "GameState", action: Action) -> "GameState":
    """Opponent minion attacks our hero or our minions.

    source_index indexes into s.opponent.board (opponent's minions).
    target_index: 0 = our hero, 1+ = our minion (1-based).
    """
    src_idx = action.source_index
    if src_idx < 0 or src_idx >= len(s.opponent.board):
        return s
    source = s.opponent.board[src_idx]

    if not source.can_attack_now:
        return s

    tgt_idx = action.target_index
    if tgt_idx == 0:
        # Attack our hero
        _apply_damage_to_hero(s.hero, source.attack)
        if source.has_lifesteal:
            s.opponent.hero.hp = min(
                s.opponent.hero.max_hp,
                s.opponent.hero.hp + source.attack,
            )
    else:
        # Attack our minion
        our_idx = tgt_idx - 1
        if our_idx < 0 or our_idx >= len(s.board):
            return s
        target = s.board[our_idx]

        # Target takes damage
        if target.has_divine_shield:
            target.has_divine_shield = False
        else:
            target.health -= source.attack

        # Counter-attack
        if source.has_divine_shield:
            source.has_divine_shield = False
        else:
            source.health -= target.attack

        # Poisonous
        if source.has_poisonous and not target.has_divine_shield:
            target.health = 0

    # Mark attacker as used
    source.can_attack = False

    # Resolve deaths
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]
    s.board = [m for m in s.board if m.health > 0]

    return s


def _opponent_hero_power(s: "GameState") -> "GameState":
    """Opponent uses their hero power — class-specific effects.

    Mirrors the friendly _IMBUE_HERO_POWERS table but applied against us.
    """
    hp_cost = s.opponent.hero.hero_power_cost
    if s.opponent.hero.hero_power_used:
        return s
    if hp_cost > s.opponent.mana_available:
        return s

    s.opponent.mana_available -= hp_cost
    s.opponent.hero.hero_power_used = True

    raw_class = getattr(s.opponent.hero, "hero_class", "")
    if hasattr(raw_class, "name"):
        hero_class = str(getattr(raw_class, "name")).upper()
    else:
        hero_class = (str(raw_class) if raw_class is not None else "").upper()

    power_info = _IMBUE_HERO_POWERS.get(hero_class)
    if power_info is None:
        # Generic fallback: deal 1 damage to our hero
        _apply_damage_to_hero(s.hero, 1)
        return s

    effect = power_info.get("effect", "")

    if effect == "damage":
        base = power_info.get("base_damage", 1)
        total = base + getattr(s.opponent.hero, "imbue_level", 0)
        # Opponent's damage effect targets US (our hero or our board)
        if s.board:
            s.board[0].health -= total
        else:
            _apply_damage_to_hero(s.hero, total)

    elif effect == "heal":
        base = power_info.get("base_heal", 2)
        total = base + getattr(s.opponent.hero, "imbue_level", 0)
        # Opponent heals THEIR hero
        s.opponent.hero.hp = min(
            s.opponent.hero.max_hp,
            s.opponent.hero.hp + total,
        )

    elif effect == "armor":
        base = power_info.get("base_armor", 2)
        total = base + getattr(s.opponent.hero, "imbue_level", 0)
        s.opponent.hero.armor += total

    elif effect == "summon":
        base_atk = power_info.get("base_attack", 1)
        base_hp = power_info.get("base_health", 1)
        imbue = getattr(s.opponent.hero, "imbue_level", 0)
        atk = base_atk + imbue
        hp_val = base_hp + imbue
        if len(s.opponent.board) < 7:
            s.opponent.board.append(Minion(
                name="Opponent HP Minion",
                attack=atk,
                health=hp_val,
                max_health=hp_val,
                owner="enemy",
                can_attack=True,  # already had the turn to play HP, can't attack same turn
            ))

    elif effect == "weapon":
        base_atk = power_info.get("base_attack", 1)
        base_dur = power_info.get("base_durability", 2)
        imbue = getattr(s.opponent.hero, "imbue_level", 0)
        atk = base_atk + imbue
        s.opponent.hero.weapon = Weapon(
            attack=atk,
            health=base_dur,
            name="Opponent HP Weapon",
        )

    elif effect == "random_totem":
        if len(s.opponent.board) < 7:
            s.opponent.board.append(Minion(
                name="Opponent Totem",
                attack=0,
                health=1,
                max_health=1,
                owner="enemy",
                can_attack=False,
            ))

    elif effect == "damage_self_draw":
        dmg = power_info.get("base_damage", 2)
        draw_count = power_info.get("base_draw", 1)
        # Opponent takes self-damage and draws
        s.opponent.hero.hp -= dmg
        for _ in range(draw_count):
            s = opponent_executor.opponent_draw_card(s)

    # Fire AFTER_HERO_POWER triggers
    s = _fire_event("AFTER_HERO_POWER", s, event_source=s.opponent.hero)

    return s


def _opponent_end_turn(s: "GameState", action: Action) -> "GameState":
    """End opponent turn, switch back to OUR turn.

    Increments turn counter, draws a card for us, draws a card for opponent,
    resets our mana (accounting for overload recorded in _end_turn), and
    clears opponent's turn mana.
    """
    s.is_opponent_turn = False

    # Trigger system: on_turn_start (our turn begins)
    s = _dispatch_trigger('on_turn_start', s)

    # Increment turn (deferred from _end_turn)
    s.turn_number += 1

    # Draw a card for us
    s = _draw_card(s)

    # Draw a card for opponent (simulates opponent drawing on their turn)
    s = opponent_executor.opponent_draw_card(s)

    # Set up our mana for new turn
    if s.mana.max_mana < s.mana.max_mana_cap:
        s.mana.max_mana += 1
    s.mana.available = s.mana.max_mana - s.mana.overloaded

    # Clear opponent's turn mana and reset
    s.opponent.mana_available = 0
    s.opponent.mana_max = 0

    # Reset opponent hero power
    s.opponent.hero.hero_power_used = False

    # Unfreeze OUR frozen minions (opponent's turn is over)
    for m in s.board:
        m.frozen_until_next_turn = False

    # Unfreeze opponent minions (our turn just ended from their perspective)
    for m in s.opponent.board:
        m.frozen_until_next_turn = False

    return s


# ──────────────────────────────────────────────────────────────
# Location activation
# ──────────────────────────────────────────────────────────────


def _activate_location(s: "GameState", action: Action) -> "GameState":
    """Activate location card: pay cooldown, dispatch ability."""
    try:
        from analysis.card.engine.mechanics.location import activate_location
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
            from analysis.card.models.card import Card
            s.hand.append(Card.from_hsdb_dict(chosen) if isinstance(chosen, dict) else chosen)

    return s


# ──────────────────────────────────────────────────────────────
# Choose one
# ──────────────────────────────────────────────────────────────


def _choose_one(s: "GameState", action: Action) -> "GameState":
    """Handle CHOOSE_ONE action — apply chosen effect."""
    try:
        from analysis.card.engine.mechanics.choose_one import resolve_choose_one_effect
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
            from analysis.card.engine.mechanics.hero_card import HeroCardHandler
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
        from analysis.card.data.card_effects import get_effects
        eff = get_effects(card)
    except (ImportError, TypeError):
        eff = None

    if eff is None:
        # Fallback: text-based hand-transform detection
        text = getattr(card, "english_text", "") or getattr(card, "text", "") or ""
        if 'becomes' not in text.lower():
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
    from analysis.card.abilities.definition import AbilityTrigger
    from analysis.card.abilities.loader import load_abilities

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
                from analysis.card.data.token_cards import get_random_naga, create_naga_card
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
                    from analysis.card.engine.mechanics.shatter import check_shatter_on_draw
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
        from analysis.card.data.card_effects import get_card_damage
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

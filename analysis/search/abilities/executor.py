#!/usr/bin/env python3
"""executor.py — Unified ability execution engine.

Layer 2 in the ability system architecture:
  Layer 1: Parsing (parser.py) — card → List[CardAbility]
  Layer 2: Execution (this file) — THE single source of truth for effect application
  Layer 3: Orchestration (orchestrator.py) — spell power, target selection, lifesteal

Handles all effect kinds with proper armor/shield/immune/stealth mechanics.
Called by orchestrator.orchestrate(), AbilityExecutor.trigger(), and directly
by deathrattle/location/trigger modules.
"""
from __future__ import annotations

import logging
import random
from typing import List, Optional, TYPE_CHECKING

from analysis.search.abilities.definition import (
    CardAbility, AbilityTrigger, EffectSpec, EffectKind,
    ConditionSpec, ConditionKind, TargetSpec, TargetKind,
)

if TYPE_CHECKING:
    from analysis.search.game_state import GameState, Minion, HeroState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# Section 1: AbilityExecutor — trigger-based dispatch
# ═══════════════════════════════════════════════════════════════

class AbilityExecutor:
    """Scan entities for matching abilities and execute them."""

    @staticmethod
    def trigger(
        state: GameState,
        event: AbilityTrigger,
        source=None,
        target=None,
    ) -> GameState:
        entities = _collect_entities(state, source)
        for entity in entities:
            abilities = getattr(entity, 'abilities', [])
            if not abilities:
                card_ref = getattr(entity, 'card_ref', None)
                if card_ref is not None:
                    abilities = getattr(card_ref, 'abilities', [])
            for ability in abilities:
                if ability.trigger != event:
                    continue
                if not ability.is_active(state, entity):
                    continue
                try:
                    state = ability.execute(state, entity, target)
                except Exception as exc:
                    log.debug("Ability execution failed: %s — %s", ability, exc)
        return state


# ═══════════════════════════════════════════════════════════════
# Section 2: Condition checking
# ═══════════════════════════════════════════════════════════════

def check_condition(spec: ConditionSpec, state: GameState, source) -> bool:
    """Evaluate a condition spec against current game state."""
    if spec.kind == ConditionKind.HOLDING_RACE:
        race = spec.params.get("race", "")
        hand = getattr(state, 'hand', [])
        source_idx = None
        for i, h in enumerate(hand):
            if h is source:
                source_idx = i
                break
        for i, h in enumerate(hand):
            if i == source_idx:
                continue
            h_race = getattr(h, 'race', '').upper()
            h_races = getattr(h, 'races', None)
            if h_race == race:
                return True
            if h_races and race in [r.upper() for r in h_races]:
                return True
        return False

    if spec.kind == ConditionKind.THIS_TURN:
        return True

    if spec.kind == ConditionKind.FOR_EACH:
        return True

    if spec.kind == ConditionKind.PLAYED_THIS_TURN:
        card_type = spec.params.get("card_type", "")
        played = getattr(state, 'cards_played_this_turn', [])
        for p in played:
            p_type = getattr(p, 'card_type', '').upper()
            p_school = getattr(p, 'spell_school', '').upper()
            if card_type == p_type or card_type == p_school:
                return True
        return False

    return True


# ═══════════════════════════════════════════════════════════════
# Section 3: Effect execution — THE core of the engine
# ═══════════════════════════════════════════════════════════════

def execute_effects(
    state: GameState,
    source,
    effects: List[EffectSpec],
    target=None,
) -> GameState:
    """Apply a list of effects sequentially to the game state."""
    s = state
    for effect in effects:
        s = _execute_single(s, source, effect, target)
    return s


def _execute_single(
    state: GameState,
    source,
    effect: EffectSpec,
    target=None,
) -> GameState:
    """Apply a single effect. Dispatch by EffectKind."""
    kind = effect.kind

    if kind == EffectKind.WEAPON_EQUIP:
        from analysis.search.game_state import Weapon
        state.hero.weapon = Weapon(
            attack=effect.value, health=effect.value2,
            name=getattr(source, 'name', 'Weapon'),
        )
        return state

    if kind == EffectKind.DAMAGE:
        return _exec_damage(state, effect, target)

    if kind == EffectKind.SUMMON:
        return _exec_summon(state, effect)

    if kind == EffectKind.DRAW:
        return _exec_draw(state, effect)

    if kind == EffectKind.GAIN:
        return _exec_gain(state, effect)

    if kind == EffectKind.HEAL:
        return _exec_heal(state, effect, target)

    if kind == EffectKind.GIVE:
        return _exec_give(state, effect, target)

    if kind == EffectKind.DESTROY:
        return _exec_destroy(state, effect, target)

    if kind == EffectKind.FREEZE:
        return _exec_freeze(state, effect, target)

    if kind == EffectKind.SILENCE:
        return _exec_silence(state, effect, target)

    if kind == EffectKind.DISCOVER:
        return _exec_discover(state, effect)

    if kind == EffectKind.COPY:
        return _exec_copy(state, effect, target)

    if kind == EffectKind.SHUFFLE:
        return state

    if kind == EffectKind.REDUCE_COST:
        return _exec_reduce_cost(state, effect)

    if kind == EffectKind.TRANSFORM:
        return state

    if kind == EffectKind.RETURN:
        return state

    if kind == EffectKind.TAKE_CONTROL:
        return state

    if kind == EffectKind.DISCARD:
        return _exec_discard(state, effect)

    if kind == EffectKind.SWAP:
        return state

    if kind == EffectKind.CAST_SPELL:
        return state

    if kind == EffectKind.ENCHANT:
        return _exec_enchant(state, effect, target)

    # ── Keyword effects (from standalone modules) ──
    if kind == EffectKind.HERALD_SUMMON:
        return _exec_herald_summon(state, effect, source)

    if kind == EffectKind.IMBUE_UPGRADE:
        return _exec_imbue_upgrade(state, effect)

    if kind == EffectKind.COMBO_DISCOUNT:
        return _exec_combo_discount(state, effect)

    if kind == EffectKind.OUTCAST_DRAW:
        return _exec_outcast_draw(state, effect)

    if kind == EffectKind.OUTCAST_BUFF:
        return _exec_outcast_buff(state, effect, source)

    if kind == EffectKind.OUTCAST_COST:
        return _exec_outcast_cost(state, effect, source)

    if kind == EffectKind.COLOSSAL_SUMMON:
        return _exec_colossal_summon(state, effect, source)

    if kind == EffectKind.KINDRED_BUFF:
        return _exec_kindred_buff(state, effect, source)

    if kind == EffectKind.CORRUPT_UPGRADE:
        return _exec_corrupt_upgrade(state, effect, source)

    if kind == EffectKind.CORPSE_EFFECT:
        return _exec_corpse_effect(state, effect, source)

    return state


# ═══════════════════════════════════════════════════════════════
# Section 4: Primitive operations (damage, heal, summon, etc.)
# ═══════════════════════════════════════════════════════════════

def _apply_damage_to_hero(hero: HeroState, amount: int) -> None:
    """Deal damage to a hero, respecting armor."""
    if getattr(hero, 'is_immune', False):
        return
    absorbed = min(hero.armor, amount)
    hero.armor -= absorbed
    hero.hp -= (amount - absorbed)


def _apply_damage_to_minion(minion: Minion, amount: int) -> None:
    """Deal damage to a minion, respecting divine shield and immune."""
    if getattr(minion, 'has_immune', False):
        return
    if getattr(minion, 'has_divine_shield', False):
        minion.has_divine_shield = False
        return
    minion.health -= amount


def _silence_minion(minion: Minion) -> None:
    """Strip all keywords and enchantments from a minion."""
    bool_fields = [
        'has_divine_shield', 'has_taunt', 'has_stealth', 'has_windfury',
        'has_rush', 'has_charge', 'has_poisonous', 'has_lifesteal',
        'has_reborn', 'has_immune', 'cant_attack', 'has_magnetic',
        'has_invoke', 'has_corrupt', 'has_spellburst', 'is_outcast',
        'frozen_until_next_turn', 'has_ward', 'has_mega_windfury',
    ]
    for f in bool_fields:
        if hasattr(minion, f):
            setattr(minion, f, False)
    minion.enchantments = []
    minion.abilities = []


def _resolve_deaths(state: GameState) -> None:
    """Remove dead minions from both boards (health <= 0)."""
    state.board = [m for m in state.board if m.health > 0]
    state.opponent.board = [m for m in state.opponent.board if m.health > 0]


# ═══════════════════════════════════════════════════════════════
# Section 4b: Effect-specific execution helpers
# ═══════════════════════════════════════════════════════════════

def _exec_damage(state: GameState, effect: EffectSpec, target) -> GameState:
    """DAMAGE: deal damage respecting armor, divine shield, immune."""
    amount = effect.value
    if amount <= 0:
        return state
    tgt = _resolve_target(state, effect.target, target)
    if tgt is None or tgt == "enemy_hero":
        _apply_damage_to_hero(state.opponent.hero, amount)
    elif tgt == "friendly_hero":
        _apply_damage_to_hero(state.hero, amount)
    elif isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            _apply_damage_to_minion(board[tgt], amount)
    elif tgt == "all_enemy":
        for m in list(state.opponent.board):
            _apply_damage_to_minion(m, amount)
    elif tgt == "all_friendly":
        for m in list(state.board):
            _apply_damage_to_minion(m, amount)
    elif tgt == "all_minions":
        for m in list(state.board):
            _apply_damage_to_minion(m, amount)
        for m in list(state.opponent.board):
            _apply_damage_to_minion(m, amount)
    return state


def _exec_summon(state: GameState, effect: EffectSpec) -> GameState:
    """SUMMON: create a token minion on the friendly board."""
    from analysis.search.game_state import Minion as _Minion
    atk = effect.value
    hp = effect.value2
    if atk > 0 or hp > 0:
        m = _Minion(attack=atk, health=hp, max_health=hp, name="Token", can_attack=False)
        if len(state.board) < 7:
            state.board.append(m)
    return state


def _exec_draw(state: GameState, effect: EffectSpec) -> GameState:
    """DRAW: draw cards from deck."""
    count = max(effect.value, 1)
    for _ in range(count):
        if state.deck_remaining > 0:
            state.deck_remaining -= 1
    return state


def _exec_gain(state: GameState, effect: EffectSpec) -> GameState:
    """GAIN: gain armor or health."""
    subtype = effect.subtype
    amount = effect.value
    if subtype == "armor":
        state.hero.armor += amount
    elif subtype == "health":
        state.hero.hp += amount
    return state


def _exec_heal(state: GameState, effect: EffectSpec, target) -> GameState:
    """HEAL: restore health to hero or minion (up to max)."""
    amount = effect.value
    if amount <= 0:
        return state
    tgt = _resolve_target(state, effect.target, target)
    if tgt is None or tgt == "friendly_hero":
        state.hero.hp = min(state.hero.hp + amount, state.hero.max_hp)
    elif tgt == "enemy_hero":
        state.opponent.hero.hp = min(
            state.opponent.hero.hp + amount, state.opponent.hero.max_hp)
    elif isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            m = board[tgt]
            m.health = min(m.health + amount, m.max_health)
    elif tgt == "all_friendly":
        for m in state.board:
            m.health = min(m.health + amount, m.max_health)
    elif tgt == "all_enemy":
        for m in state.opponent.board:
            m.health = min(m.health + amount, m.max_health)
    return state


def _exec_give(state: GameState, effect: EffectSpec, target) -> GameState:
    """GIVE: buff stats and/or keyword on target minion."""
    atk = effect.value
    hp = effect.value2
    keyword = effect.keyword
    tgt = _resolve_target(state, effect.target, target)

    if tgt is None:
        # Default: buff all friendly minions
        for m in state.board:
            if atk > 0:
                m.attack += atk
            if hp > 0:
                m.health += hp
                m.max_health += hp
            _apply_keyword(m, keyword)
    elif isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            m = board[tgt]
            if atk > 0:
                m.attack += atk
            if hp > 0:
                m.health += hp
                m.max_health += hp
            _apply_keyword(m, keyword)
    elif tgt == "all_friendly":
        for m in state.board:
            if atk > 0:
                m.attack += atk
            if hp > 0:
                m.health += hp
                m.max_health += hp
            _apply_keyword(m, keyword)
    return state


def _exec_destroy(state: GameState, effect: EffectSpec, target) -> GameState:
    """DESTROY: remove a minion from the board."""
    tgt = _resolve_target(state, effect.target, target)
    if isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            board.pop(tgt)
    return state


def _exec_freeze(state: GameState, effect: EffectSpec, target) -> GameState:
    """FREEZE: set frozen_until_next_turn on target minion."""
    tgt = _resolve_target(state, effect.target, target)
    if isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            board[tgt].frozen_until_next_turn = True
    elif tgt == "all_enemy":
        for m in state.opponent.board:
            m.frozen_until_next_turn = True
    elif tgt == "all_friendly":
        for m in state.board:
            m.frozen_until_next_turn = True
    return state


def _exec_silence(state: GameState, effect: EffectSpec, target) -> GameState:
    """SILENCE: strip all keywords and enchantments from target."""
    tgt = _resolve_target(state, effect.target, target)
    if isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            _silence_minion(board[tgt])
    return state


def _exec_discover(state: GameState, effect: EffectSpec) -> GameState:
    """DISCOVER: placeholder — full discover needs pool query + branching."""
    # Discover is handled at the orchestration layer (simulation.py)
    # because it requires branching the search tree.
    return state


def _exec_copy(state: GameState, effect: EffectSpec, target) -> GameState:
    """COPY: copy a minion (placeholder)."""
    return state


def _exec_reduce_cost(state: GameState, effect: EffectSpec) -> GameState:
    """REDUCE_COST: reduce cost of cards in hand."""
    reduction = effect.value
    if reduction <= 0:
        return state
    for card in getattr(state, 'hand', []):
        if hasattr(card, 'cost'):
            card.cost = max(0, card.cost - reduction)
    return state


def _exec_discard(state: GameState, effect: EffectSpec) -> GameState:
    """DISCARD: discard N random cards from hand."""
    count = max(effect.value, 1)
    hand = getattr(state, 'hand', [])
    for _ in range(min(count, len(hand))):
        if hand:
            hand.pop(random.randint(0, len(hand) - 1))
    return state


def _exec_enchant(state: GameState, effect: EffectSpec, target) -> GameState:
    """ENCHANT: attach an enchantment to target."""
    tgt = _resolve_target(state, effect.target, target)
    if isinstance(tgt, int) and tgt >= 0:
        is_enemy = _is_enemy_target(effect.target)
        board = state.opponent.board if is_enemy else state.board
        if tgt < len(board):
            board[tgt].enchantments.append({
                'name': effect.subtype or 'enchant',
                'attack': effect.value,
                'health': effect.value2,
            })
    return state


def _apply_keyword(minion: Minion, keyword: str) -> None:
    """Apply a keyword string to a minion's boolean flags."""
    if not keyword:
        return
    kw = keyword.upper()
    mapping = {
        'TAUNT': 'has_taunt',
        'DIVINE_SHIELD': 'has_divine_shield',
        'RUSH': 'has_rush',
        'CHARGE': 'has_charge',
        'WINDFURY': 'has_windfury',
        'STEALTH': 'has_stealth',
        'LIFESTEAL': 'has_lifesteal',
        'POISONOUS': 'has_poisonous',
        'REBORN': 'has_reborn',
        'IMMUNE': 'has_immune',
        'WARD': 'has_ward',
    }
    field = mapping.get(kw)
    if field and hasattr(minion, field):
        setattr(minion, field, True)


# ═══════════════════════════════════════════════════════════════
# Section 5: Target resolution
# ═══════════════════════════════════════════════════════════════

def _resolve_target(state, target_spec: Optional[TargetSpec], fallback_target=None):
    """Resolve a TargetSpec to a concrete target identifier.

    Returns one of:
      - "enemy_hero" / "friendly_hero" — hero targets
      - int >= 0 — board index (use _is_enemy_target to determine which board)
      - "all_enemy" / "all_friendly" / "all_minions" — multi-target
      - fallback_target — if no spec or unrecognized
    """
    if target_spec is None:
        return fallback_target
    kind = target_spec.kind
    if kind == TargetKind.ALL_ENEMY:
        return "all_enemy"
    if kind == TargetKind.ALL_MINIONS:
        return "all_minions"
    if kind == TargetKind.ALL_FRIENDLY:
        return "all_friendly"
    if kind == TargetKind.FRIENDLY_HERO:
        return "friendly_hero"
    if kind == TargetKind.RANDOM_ENEMY:
        opp_board = state.opponent.board
        if opp_board:
            return random.randint(0, len(opp_board) - 1)
        return "enemy_hero"
    if kind == TargetKind.RANDOM:
        # Random from combined pool based on side
        if target_spec.side == "enemy":
            opp_board = state.opponent.board
            if opp_board:
                return random.randint(0, len(opp_board) - 1)
            return "enemy_hero"
        board = state.board
        if board:
            return random.randint(0, len(board) - 1)
        return 0
    if kind in (TargetKind.SINGLE_MINION, TargetKind.ENEMY):
        if fallback_target is not None:
            return fallback_target
        opp_board = state.opponent.board
        if opp_board:
            return random.randint(0, len(opp_board) - 1)
        return "enemy_hero"
    if kind == TargetKind.FRIENDLY_MINION:
        if fallback_target is not None:
            return fallback_target
        return 0
    if kind == TargetKind.SELF:
        return 0
    if kind in (TargetKind.DAMAGED, TargetKind.UNDAMAGED):
        board = state.board if target_spec.side != "enemy" else state.opponent.board
        for i, m in enumerate(board):
            is_dmg = m.health < m.max_health
            if kind == TargetKind.DAMAGED and is_dmg:
                return i
            if kind == TargetKind.UNDAMAGED and not is_dmg:
                return i
        return 0
    return fallback_target


def _resolve_target_board(state, target_spec: Optional[TargetSpec], fallback_target=None):
    """Resolve target to (board_list, index) for minion operations.

    Returns (board, index) or (None, None) if hero target.
    """
    tgt = _resolve_target(state, target_spec, fallback_target)
    if isinstance(tgt, str) and 'hero' in tgt:
        return None, None
    is_enemy = _is_enemy_target(target_spec)
    board = state.opponent.board if is_enemy else state.board
    idx = tgt if isinstance(tgt, int) else 0
    return board, idx


def _is_enemy_target(target_spec: Optional[TargetSpec]) -> bool:
    """Check if the target spec points to an enemy entity."""
    if target_spec is None:
        return True
    return target_spec.kind in (
        TargetKind.ENEMY, TargetKind.RANDOM_ENEMY, TargetKind.ALL_ENEMY,
    )


def _collect_entities(state: GameState, source=None):
    """Collect all entities that might have abilities (board + source)."""
    entities = list(state.board)
    if source is not None and source not in entities:
        entities.append(source)
    return entities


# ═══════════════════════════════════════════════════════════════
# Section 5: Keyword effect handlers (from standalone modules)
# ═══════════════════════════════════════════════════════════════

def _exec_herald_summon(state: GameState, effect: EffectSpec, source) -> GameState:
    """HERALD_SUMMON: increment herald_count, summon class-specific soldier.

    Data: HERALD_SOLDIERS table keyed by card_class.
    Source: migrated from herald.py apply_herald().
    """
    from analysis.search.herald import HERALD_SOLDIERS

    state.herald_count += 1
    card_class = (getattr(source, 'card_class', '') or '').upper()
    soldier_def = HERALD_SOLDIERS.get(card_class, HERALD_SOLDIERS["NEUTRAL"])

    if len(state.board) < 7:
        from analysis.search.game_state import Minion as _Minion
        soldier = _Minion(
            dbf_id=0, name=soldier_def["name"],
            attack=soldier_def["attack"], health=soldier_def["health"],
            max_health=soldier_def["health"], cost=0,
            can_attack=False, owner="friendly",
        )
        state.board.append(soldier)
    return state


def _exec_imbue_upgrade(state: GameState, effect: EffectSpec) -> GameState:
    """IMBUE_UPGRADE: increment hero.imbue_level by 1.

    The actual hero power upgrade resolution is handled by imbue.apply_hero_power()
    at hero power use time — this only increments the counter.

    Source: migrated from imbue.py apply_imbue().
    """
    state.hero.imbue_level += 1
    return state


def _exec_combo_discount(state: GameState, effect: EffectSpec) -> GameState:
    """COMBO_DISCOUNT: add 'next_combo_card' mana modifier with N discount.

    Source: migrated from battlecry_dispatcher._apply_extra_effects().
    """
    discount = effect.value if isinstance(effect.value, int) else 2
    state.mana.add_modifier('combo_discount', discount, 'next_combo_card')
    return state


def _exec_outcast_draw(state: GameState, effect: EffectSpec) -> GameState:
    """OUTCAST_DRAW: draw N cards (outcast position bonus).

    Source: migrated from outcast.py apply_outcast_bonus().
    """
    count = effect.value if isinstance(effect.value, int) else 1
    for _ in range(count):
        if state.deck_remaining > 0:
            state.deck_remaining -= 1
        else:
            state.fatigue_damage += 1
            state.hero.hp -= state.fatigue_damage
    return state


def _exec_outcast_buff(state: GameState, effect: EffectSpec, source) -> GameState:
    """OUTCAST_BUFF: buff last played minion +N/+N (outcast position bonus).

    Source: migrated from outcast.py apply_outcast_bonus().
    """
    atk = effect.value if isinstance(effect.value, int) else 0
    hp = effect.value2 if isinstance(effect.value2, int) else 0
    if state.board:
        last = state.board[-1]
        last.attack += atk
        last.health += hp
        last.max_health += hp
    return state


def _exec_outcast_cost(state: GameState, effect: EffectSpec, source) -> GameState:
    """OUTCAST_COST: refund mana to target cost (outcast position bonus).

    Source: migrated from outcast.py apply_outcast_bonus().
    """
    target_cost = effect.value if isinstance(effect.value, int) else 0
    original_cost = getattr(source, 'cost', 0)
    refund = max(0, original_cost - target_cost)
    state.mana.available += refund
    return state


def _exec_colossal_summon(state: GameState, effect: EffectSpec, source) -> GameState:
    """COLOSSAL_SUMMON: summon N class-specific appendage minions with herald buffs.

    Source: migrated from colossal.py summon_colossal_appendages().
    """
    from analysis.search.colossal import COLOSSAL_APPENDAGES, parse_colossal_value

    appendage_count = effect.value if isinstance(effect.value, int) else parse_colossal_value(source)
    if appendage_count <= 0:
        return state

    card_class = (getattr(source, 'card_class', '') or '').upper()
    appendage_def = COLOSSAL_APPENDAGES.get(card_class, COLOSSAL_APPENDAGES["NEUTRAL"])

    # Herald upgrade bonuses
    bonus_atk = 2 if state.herald_count >= 4 else (1 if state.herald_count >= 2 else 0)
    bonus_hp = bonus_atk

    # Find main minion position (last played)
    insert_pos = len(state.board)  # default end
    for i in range(len(state.board) - 1, -1, -1):
        if getattr(state.board[i], 'name', '') == getattr(source, 'name', ''):
            insert_pos = i + 1
            break

    from analysis.search.game_state import Minion as _Minion
    for i in range(appendage_count):
        if len(state.board) >= 7:
            break
        appendage = _Minion(
            dbf_id=0, name=appendage_def["name"],
            attack=appendage_def["attack"] + bonus_atk,
            health=appendage_def["health"] + bonus_hp,
            max_health=appendage_def["health"] + bonus_hp,
            cost=0, can_attack=False, owner="friendly",
        )
        insert_at = min(insert_pos + i, len(state.board))
        state.board.insert(insert_at, appendage)

    return state


def _exec_kindred_buff(state: GameState, effect: EffectSpec, source) -> GameState:
    """KINDRED_BUFF: apply bonus if card's race/school matches last turn plays.

    Source: migrated from kindred.py apply_kindred().
    """
    from analysis.search.kindred import (
        check_kindred_active, parse_kindred_bonus, _apply_bonus_effect,
    )

    card_text = getattr(source, 'text', '') or getattr(source, 'english_text', '') or ''
    if not check_kindred_active(state, source):
        return state

    bonus = parse_kindred_bonus(card_text)
    if bonus:
        trigger_count = 2 if getattr(state, 'kindred_double_next', False) else 1
        if trigger_count == 2:
            state.kindred_double_next = False
        for _ in range(trigger_count):
            state = _apply_bonus_effect(state, bonus, source)

    return state


def _exec_corrupt_upgrade(state: GameState, effect: EffectSpec, source) -> GameState:
    """CORRUPT_UPGRADE: upgrade corrupt cards in hand when a higher-cost card is played.

    Source: migrated from corrupt.py check_corrupt_upgrade().
    """
    from analysis.search.corrupt import has_corrupt
    from analysis.models.card import Card

    played_cost = getattr(source, 'cost', 0)
    for i, card in enumerate(state.hand):
        if not has_corrupt(card):
            continue
        card_cost = getattr(card, 'cost', 0)
        if played_cost > card_cost:
            old_cost = getattr(card, 'cost', 0)
            state.hand[i] = Card(
                dbf_id=getattr(card, 'dbf_id', 0),
                name=getattr(card, 'name', ''),
                cost=old_cost + 1, original_cost=old_cost + 1,
                card_type=getattr(card, 'card_type', ''),
                attack=getattr(card, 'attack', 0) + 1,
                health=getattr(card, 'health', 0) + 1,
                text=getattr(card, 'text', ''),
                rarity=getattr(card, 'rarity', ''),
                card_class=getattr(card, 'card_class', ''),
                race=getattr(card, 'race', ''),
                mechanics=[m for m in (getattr(card, 'mechanics', []) or []) if m != 'CORRUPT'],
            )
    return state


def _exec_corpse_effect(state: GameState, effect: EffectSpec, source) -> GameState:
    """CORPSE_EFFECT: spend/gain corpse resource and apply bonus.

    Source: migrated from corpse.py resolve_corpse_effects().
    """
    from analysis.search.corpse import (
        parse_corpse_effects, parse_corpse_gain, gain_corpses,
        has_double_corpse_gen, _apply_corpse_bonus,
    )

    card_text = getattr(source, 'text', '') or ''
    effects_list = parse_corpse_effects(card_text)

    for eff in effects_list:
        if state.corpses < eff.cost:
            if eff.is_optional:
                continue
            continue
        state.corpses -= eff.cost
        state = _apply_corpse_bonus(state, eff.effect_text, source)

    # Check for gain effects
    gain = parse_corpse_gain(card_text)
    if gain > 0:
        if has_double_corpse_gen(state):
            gain *= 2
        state.corpses += gain

    return state

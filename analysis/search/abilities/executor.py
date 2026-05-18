#!/usr/bin/env python3
"""executor.py — Unified ability execution engine.

Layer 2 in the ability system architecture:
  Layer 1: Parsing (parser.py, effect_parser.py)
  Layer 2: Execution (this file) — THE single source of truth for effect application
  Layer 3: Orchestration (spell_simulator.resolve_effects, battlecry_dispatcher.dispatch)

Handles all effect kinds with proper armor/shield/immune/stealth mechanics.
Called by AbilityExecutor.trigger(), resolve_effects(), dispatch_battlecry(),
and directly by deathrattle/location/trigger modules.
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

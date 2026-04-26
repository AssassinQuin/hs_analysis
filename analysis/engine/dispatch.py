"""dispatch.py — 效果分发表（统一执行路径入口）。

替代 executor.py 的 if-chain 结构，所有效果经由 dispatch() → EffectHandler 执行。
Phase 1: 注册全部 35 种 EffectKind，7 种 stub 效果先为 pass-through。

Architecture:
  EffectKind → EFFECT_HANDLERS[kind] → handler(state, effect, target) → GameState
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from analysis.abilities.definition import (
    EffectKind, EffectSpec, TargetKind, TargetSpec,
)

if TYPE_CHECKING:
    from analysis.engine.state import GameState

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Target resolution helpers (used by dispatch handlers)
# ──────────────────────────────────────────────────────────────

def _resolve_target(state: "GameState", target_spec: Optional[TargetSpec], fallback: Any) -> Any:
    """Resolve a TargetSpec to a concrete target descriptor.

    Returns: str ("enemy_hero", "friendly_hero", "all_enemy", "all_friendly", "all_minions"),
             int (board index), or None.
    """
    if target_spec is None:
        return fallback
    kind = target_spec.kind if hasattr(target_spec, 'kind') else None
    if kind is None:
        return fallback

    _MAP = {
        TargetKind.ALL_ENEMY: "all_enemy",
        TargetKind.ALL_FRIENDLY: "all_friendly",
        TargetKind.ALL_MINIONS: "all_minions",
        TargetKind.ALL: "all_minions",
        TargetKind.RANDOM_ENEMY: "enemy_hero",
        TargetKind.RANDOM: "enemy_hero",
        TargetKind.FRIENDLY_HERO: "friendly_hero",
        TargetKind.SELF: "friendly_hero",
    }
    if kind in _MAP:
        return _MAP[kind]
    if kind in (TargetKind.ENEMY, TargetKind.SINGLE_MINION, TargetKind.FRIENDLY_MINION,
                TargetKind.DAMAGED, TargetKind.UNDAMAGED):
        return fallback
    return fallback


def _is_enemy_target(target_spec: Optional[TargetSpec]) -> bool:
    """Check whether the target spec points to enemy side."""
    if target_spec is None:
        return True  # default enemy
    kind = target_spec.kind if hasattr(target_spec, 'kind') else None
    if kind is None:
        return True
    _ENEMY_KINDS = {TargetKind.ENEMY, TargetKind.ALL_ENEMY, TargetKind.RANDOM_ENEMY,
                    TargetKind.SINGLE_MINION, TargetKind.RANDOM}
    _FRIENDLY_KINDS = {TargetKind.FRIENDLY_HERO, TargetKind.FRIENDLY_MINION,
                       TargetKind.ALL_FRIENDLY, TargetKind.SELF}
    if kind in _ENEMY_KINDS:
        return True
    if kind in _FRIENDLY_KINDS:
        return False
    return True  # default


def _resolve_minion_target(state: "GameState", target_spec: Optional[TargetSpec], target: Any) -> Any:
    """Resolve a target to a minion object or board-index-aware descriptor.

    When target is an int and target_spec indicates enemy, returns the enemy
    board minion at that index. Otherwise returns the target as-is (string
    descriptors like 'all_enemy' are passed through to executor primitives).
    """
    if isinstance(target, int) and _is_enemy_target(target_spec):
        if 0 <= target < len(state.opponent.board):
            return state.opponent.board[target]
        return target
    if isinstance(target, int) and not _is_enemy_target(target_spec):
        if 0 <= target < len(state.board):
            return state.board[target]
        return target
    return target

# ──────────────────────────────────────────────────────────────
# Type aliases
# ──────────────────────────────────────────────────────────────

# EffectHandler: (GameState, EffectSpec, target) → GameState
EffectHandler = Callable[["GameState", EffectSpec, Any], "GameState"]

# ──────────────────────────────────────────────────────────────
# Handler registry
# ──────────────────────────────────────────────────────────────

EFFECT_HANDLERS: Dict[EffectKind, EffectHandler] = {}


def register_handler(kind: EffectKind):
    """效果处理器注册装饰器。

    Usage:
        @register_handler(EffectKind.DAMAGE)
        def _handle_damage(state, effect, target):
            ...
    """
    def decorator(fn: EffectHandler) -> EffectHandler:
        EFFECT_HANDLERS[kind] = fn
        return fn
    return decorator


# ──────────────────────────────────────────────────────────────
# Dispatch functions
# ──────────────────────────────────────────────────────────────

def dispatch(state: "GameState", effect: EffectSpec, target: Any = None) -> "GameState":
    """单效果分派 — 查找注册的 handler 并执行。"""
    handler = EFFECT_HANDLERS.get(effect.kind)
    if handler is None:
        log.debug("dispatch: unregistered effect kind %s, skipping", effect.kind)
        return state
    return handler(state, effect, target)


def dispatch_batch(
    state: "GameState",
    effects: List[EffectSpec],
    source: Any = None,
    target: Any = None,
) -> "GameState":
    """批量效果分派 — 顺序执行效果列表。"""
    for effect in effects:
        # If no explicit target, resolve from effect's target spec
        resolved_target = target
        if resolved_target is None and effect.selector is not None:
            resolved_target = effect.selector.select(state, source)
            if resolved_target and len(resolved_target) == 1:
                resolved_target = resolved_target[0]
        state = dispatch(state, effect, resolved_target)
    return state


# ──────────────────────────────────────────────────────────────
# Handler implementations
# ──────────────────────────────────────────────────────────────
# Delegates to executor primitives (clean signatures, no EffectSpec).

from analysis.engine.executor import (
    damage,
    summon_minion,
    draw_cards,
    heal,
    buff_minion,
    destroy_minion,
    transform_minion,
    silence_minion,
    freeze_target,
    take_control,
    return_to_hand,
    copy_minion,
    shuffle_into_deck,
    swap_stats,
    equip_weapon,
    gain_armor,
    reduce_cost,
    discard_cards,
    enchant_minion,
    discover_card,
)


# ── Core effects (delegating to executor primitives) ──

@register_handler(EffectKind.DAMAGE)
def _handle_damage(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.resolve_value(state) if hasattr(effect, 'resolve_value') else (effect.value if isinstance(effect.value, int) else 0)
    if amount <= 0:
        return state
    tgt = _resolve_minion_target(state, effect.target, target)
    return damage(state, amount, target=tgt)


@register_handler(EffectKind.SUMMON)
def _handle_summon(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    # effect.value may be a dict with attack/health/name, or a card ref, or None
    minion_data = effect.value if isinstance(effect.value, dict) else None
    return summon_minion(state, card_id_or_minion=minion_data)


@register_handler(EffectKind.DRAW)
def _handle_draw(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    count = effect.value if isinstance(effect.value, int) else 1
    return draw_cards(state, count=max(count, 1))


@register_handler(EffectKind.GAIN)
def _handle_gain(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 0
    return gain_armor(state, amount)


@register_handler(EffectKind.HEAL)
def _handle_heal(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 0
    if amount <= 0:
        return state
    tgt = _resolve_minion_target(state, effect.target, target)
    return heal(state, amount, target=tgt)


@register_handler(EffectKind.GIVE)
def _handle_give(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    atk = effect.value if isinstance(effect.value, int) else 0
    hp = effect.value2 if isinstance(effect.value2, int) else 0
    keyword = getattr(effect, 'subtype', '') or ''
    keywords = [keyword] if keyword else []
    return buff_minion(state, tgt, attack_delta=atk, health_delta=hp, keywords=keywords)


@register_handler(EffectKind.DESTROY)
def _handle_destroy(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return destroy_minion(state, tgt)


@register_handler(EffectKind.FREEZE)
def _handle_freeze(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return freeze_target(state, tgt)


@register_handler(EffectKind.SILENCE)
def _handle_silence(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return silence_minion(state, tgt)


@register_handler(EffectKind.DISCOVER)
def _handle_discover(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    pool = getattr(effect, 'value', None) or []
    if not isinstance(pool, list):
        pool = []
    return discover_card(state, pool)


@register_handler(EffectKind.REDUCE_COST)
def _handle_reduce_cost(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 1
    card_type = getattr(effect, 'subtype', '') or ''
    return reduce_cost(state, amount, card_type_filter=card_type if card_type else None)


@register_handler(EffectKind.DISCARD)
def _handle_discard(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    count = effect.value if isinstance(effect.value, int) else 1
    return discard_cards(state, count=max(count, 1))


@register_handler(EffectKind.ENCHANT)
def _handle_enchant(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    enchant_dict = {
        "name": getattr(effect, 'subtype', '') or 'enchant',
        "attack": effect.value if isinstance(effect.value, int) else 0,
        "health": effect.value2 if isinstance(effect.value2, int) else 0,
    }
    return enchant_minion(state, tgt, enchant_dict)


@register_handler(EffectKind.WEAPON_EQUIP)
def _handle_weapon_equip(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    card = {
        "attack": effect.value if isinstance(effect.value, int) else 0,
        "health": effect.value2 if isinstance(effect.value2, int) else 0,
        "name": getattr(effect, 'subtype', '') or 'Weapon',
    }
    return equip_weapon(state, card)


# ── Bridged from effects.py ──

@register_handler(EffectKind.BUFF)
def _handle_buff(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    atk = effect.value if isinstance(effect.value, int) else 0
    hp = effect.value2 if isinstance(effect.value2, int) else 0
    keyword = getattr(effect, 'subtype', '') or ''
    keywords = [keyword] if keyword else []
    return buff_minion(state, tgt, attack_delta=atk, health_delta=hp, keywords=keywords)


@register_handler(EffectKind.ARMOR)
def _handle_armor(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 0
    return gain_armor(state, amount)


@register_handler(EffectKind.RANDOM_DAMAGE)
def _handle_random_damage(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 0
    if amount <= 0:
        return state
    tgt = _resolve_minion_target(state, effect.target, target)
    return damage(state, amount, target=tgt)


@register_handler(EffectKind.AOE_DAMAGE)
def _handle_aoe_damage(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 0
    if amount <= 0:
        return state
    tgt = _resolve_minion_target(state, effect.target, target)
    return damage(state, amount, target=tgt)


@register_handler(EffectKind.MANA)
def _handle_mana(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 1
    card_type = getattr(effect, 'subtype', '') or ''
    return reduce_cost(state, amount, card_type_filter=card_type if card_type else None)


# ── Mechanic-specific effects (inline logic + executor primitives + _data) ──

@register_handler(EffectKind.HERALD_SUMMON)
def _handle_herald_summon(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import HERALD_SOLDIERS
    source = target
    # Determine class from source card
    card_class = getattr(source, 'card_class', None) or getattr(source, 'playerClass', 'NEUTRAL')
    if isinstance(card_class, str):
        card_class = card_class.upper()
    soldier = HERALD_SOLDIERS.get(card_class, HERALD_SOLDIERS["NEUTRAL"])
    return summon_minion(state, card_id_or_minion=soldier)


@register_handler(EffectKind.IMBUE_UPGRADE)
def _handle_imbue_upgrade(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    state.imbue_level = getattr(state, 'imbue_level', 0) + 1
    return state


@register_handler(EffectKind.COMBO_DISCOUNT)
def _handle_combo_discount(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    amount = effect.value if isinstance(effect.value, int) else 1
    return reduce_cost(state, amount)


@register_handler(EffectKind.OUTCAST_DRAW)
def _handle_outcast_draw(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import _parse_outcast_bonus
    source = target
    text = getattr(source, 'text', '') or ''
    eng_text = getattr(source, 'english_text', '') or ''
    bonus = _parse_outcast_bonus(text, eng_text)
    if bonus.get("type") == "draw":
        return draw_cards(state, count=bonus.get("count", 1))
    return state


@register_handler(EffectKind.OUTCAST_BUFF)
def _handle_outcast_buff(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import _parse_outcast_bonus
    source = target
    text = getattr(source, 'text', '') or ''
    eng_text = getattr(source, 'english_text', '') or ''
    bonus = _parse_outcast_bonus(text, eng_text)
    if bonus.get("type") == "buff":
        atk = bonus.get("attack", 0)
        hp = bonus.get("health", 0)
        return buff_minion(state, "all_friendly", attack_delta=atk, health_delta=hp)
    return state


@register_handler(EffectKind.OUTCAST_COST)
def _handle_outcast_cost(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import _parse_outcast_bonus
    source = target
    text = getattr(source, 'text', '') or ''
    eng_text = getattr(source, 'english_text', '') or ''
    bonus = _parse_outcast_bonus(text, eng_text)
    if bonus.get("type") == "cost":
        # Set hand cost to specific value — approximate via reduce_cost
        return reduce_cost(state, bonus.get("value", 1))
    return state


@register_handler(EffectKind.COLOSSAL_SUMMON)
def _handle_colossal_summon(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import COLOSSAL_APPENDAGES, parse_colossal_value
    source = target
    count = parse_colossal_value(source) if source else 1
    if count <= 0:
        return state
    card_class = getattr(source, 'card_class', None) or getattr(source, 'playerClass', 'NEUTRAL')
    if isinstance(card_class, str):
        card_class = card_class.upper()
    appendage = COLOSSAL_APPENDAGES.get(card_class, COLOSSAL_APPENDAGES["NEUTRAL"])
    for _ in range(count):
        state = summon_minion(state, card_id_or_minion=appendage)
    return state


@register_handler(EffectKind.KINDRED_BUFF)
def _handle_kindred_buff(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import check_kindred_active, _KINDRED_STAT_RE
    source = target
    if source and check_kindred_active(state, source):
        # Try to parse +N/+N from the card text
        text = getattr(source, 'text', '') or ''
        eng_text = getattr(source, 'english_text', '') or ''
        m = _KINDRED_STAT_RE.search(eng_text) or _KINDRED_STAT_RE.search(text)
        if m:
            atk = int(m.group(1))
            hp = int(m.group(2))
            return buff_minion(state, "all_friendly", attack_delta=atk, health_delta=hp)
    return state


@register_handler(EffectKind.CORRUPT_UPGRADE)
def _handle_corrupt_upgrade(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    # Corrupt: if a higher-cost card was played, buff self (approximate: buff all friendly)
    # This is a simplified stub — full corrupt tracking requires hand comparison
    return state


@register_handler(EffectKind.CORPSE_EFFECT)
def _handle_corpse_effect(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    from analysis.engine.mechanics._data import parse_corpse_effects, can_afford_corpses, parse_corpse_gain
    source = target
    text = getattr(source, 'text', '') or '' if source else ''
    gain = parse_corpse_gain(text)
    if gain > 0:
        state.corpses = getattr(state, 'corpses', 0) + gain
    return state


# ── formerly stub effects (Phase 4 implemented) ──

@register_handler(EffectKind.COPY)
def _handle_copy(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return copy_minion(state, tgt)


@register_handler(EffectKind.SHUFFLE)
def _handle_shuffle(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    card_id = getattr(effect, 'subtype', None)
    count = effect.value if isinstance(effect.value, int) and effect.value > 1 else 1
    for _ in range(count):
        state = shuffle_into_deck(state, card_id=card_id)
    return state


@register_handler(EffectKind.TRANSFORM)
def _handle_transform(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    atk = effect.value if isinstance(effect.value, int) else 1
    hp = effect.value2 if isinstance(effect.value2, int) else 1
    return transform_minion(state, tgt, attack=atk, health=hp)


@register_handler(EffectKind.RETURN)
def _handle_return(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return return_to_hand(state, tgt)


@register_handler(EffectKind.TAKE_CONTROL)
def _handle_take_control(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return take_control(state, tgt)


@register_handler(EffectKind.SWAP)
def _handle_swap(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    tgt = _resolve_minion_target(state, effect.target, target)
    return swap_stats(state, tgt)


@register_handler(EffectKind.CAST_SPELL)
def _handle_cast_spell(state: "GameState", effect: EffectSpec, target: Any) -> "GameState":
    # Cast a spell effect — load the referenced card's abilities and dispatch
    # effect.subtype may contain a card_id to cast
    if effect.subtype:
        from analysis.abilities.loader import load_abilities
        abilities = load_abilities(effect.subtype)
        for ability in abilities:
            try:
                state = ability.execute(state, None, target)
            except Exception as exc:
                log.debug("CAST_SPELL ability execution failed: %s", exc)
    return state

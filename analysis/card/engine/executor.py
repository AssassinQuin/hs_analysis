"""engine/executor.py — Pure effect executor primitives.

Called by engine/dispatch.py handlers. All functions take (state, ...) and return GameState.
All random operations use DeterministicRNG instead of random module.

Architecture:
  dispatch.py handlers → executor.damage(), executor.summon_minion(), etc.
  No EffectSpec dependency — handlers extract values before calling primitives.
  No target resolution — handlers resolve targets and pass concrete values.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING, Union

from analysis.card.engine.deterministic import DeterministicRNG, det_top_k
from analysis.card.engine.tags import GameTag, MECHANIC_TO_TAG, set_tag

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState, HeroState, Minion, Weapon
    from analysis.card.abilities.definition import CardAbility, AbilityTrigger

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# Keyword application helper
# ──────────────────────────────────────────────────────────────


def _apply_keyword(minion: Any, keyword: str) -> None:
    """将关键字字符串应用到随从的 tags 字典。

    Args:
        minion: Minion 实例。
        keyword: 关键字名称（不区分大小写），如 'TAUNT', 'divine_shield'。
    """
    if not keyword:
        return
    kw = keyword.upper()
    tag = MECHANIC_TO_TAG.get(kw)
    if tag is not None and hasattr(minion, "tags"):
        set_tag(minion.tags, tag, 1)


# ──────────────────────────────────────────────────────────────
# Internal helpers (not exported as public primitives)
# ──────────────────────────────────────────────────────────────

def _get_target_entity(state: "GameState", target: Any) -> Optional[Any]:
    """Resolve a target descriptor to the actual game entity.

    Args:
        state: GameState instance.
        target: int (board index), 'enemy_hero', 'friendly_hero',
                'all_enemy', 'all_friendly', 'all_minions',
                or a Minion/HeroState object directly.

    Returns:
        The resolved entity, or None if unresolvable.
    """
    if target is None:
        return None
    if isinstance(target, int):
        if target >= 0 and target < len(state.board):
            return state.board[target]
        return None
    if target == "enemy_hero":
        return state.opponent.hero
    if target == "friendly_hero":
        return state.hero
    # Already a Minion or HeroState object
    if hasattr(target, "health") or hasattr(target, "hp"):
        return target
    return None


def _iter_targets(state: "GameState", target: Any) -> list:
    """Iterate over all entities matching a target descriptor.

    Args:
        state: GameState instance.
        target: Same descriptors as _get_target_entity, plus
                'all_enemy', 'all_friendly', 'all_minions'.

    Returns:
        List of matching entities.
    """
    if target == "all_enemy":
        return list(state.opponent.board)
    if target == "all_friendly":
        return list(state.board)
    if target == "all_minions":
        return list(state.board) + list(state.opponent.board)
    # Single target
    entity = _get_target_entity(state, target)
    return [entity] if entity is not None else []


def _apply_damage_to_hero(hero: "HeroState", amount: int) -> None:
    """Deal damage to a hero, respecting armor and immune.

    Args:
        hero: HeroState to damage.
        amount: Raw damage amount.
    """
    if getattr(hero, "is_immune", False):
        return
    absorbed = min(hero.armor, amount)
    hero.armor -= absorbed
    hero.hp -= (amount - absorbed)


def _apply_damage_to_minion(minion: "Minion", amount: int) -> None:
    """Deal damage to a minion, respecting divine shield and immune.

    Args:
        minion: Minion to damage.
        amount: Raw damage amount.
    """
    if getattr(minion, "has_immune", False):
        return
    if getattr(minion, "has_divine_shield", False):
        minion.has_divine_shield = False
        return
    minion.health -= amount


# ══════════════════════════════════════════════════════════════
# Public executor primitives
# ══════════════════════════════════════════════════════════════

def damage(
    state: "GameState",
    amount: int,
    target: Any = None,
    spell_power: int = 0,
    lifesteal: bool = False,
) -> "GameState":
    """Deal damage to a target, respecting armor/divine_shield/immune.

    Args:
        state: GameState to mutate.
        amount: Base damage amount.
        target: int (board index), 'enemy_hero', 'friendly_hero',
                'all_enemy', 'all_friendly', 'all_minions', or Minion/Hero object.
        spell_power: Additional spell power to add to damage.
        lifesteal: If True, restore damage dealt to friendly hero HP.

    Returns:
        The mutated GameState (same object).
    """
    total = amount + spell_power
    if total <= 0:
        return state

    if target in ("all_enemy", "all_friendly", "all_minions"):
        entities = _iter_targets(state, target)
        for entity in entities:
            if hasattr(entity, "health") and not hasattr(entity, "hp"):
                # Minion
                _apply_damage_to_minion(entity, total)
            elif hasattr(entity, "hp"):
                # Hero
                _apply_damage_to_hero(entity, total)
        if lifesteal and entities:
            heal(state, total, "friendly_hero")
        return state

    entity = _get_target_entity(state, target)
    if entity is None:
        # Default: enemy hero
        entity = state.opponent.hero

    if hasattr(entity, "hp"):
        # Hero target
        _apply_damage_to_hero(entity, total)
        if lifesteal:
            heal(state, total, "friendly_hero")
    elif hasattr(entity, "health"):
        # Minion target
        _apply_damage_to_minion(entity, total)
        if lifesteal:
            heal(state, total, "friendly_hero")

    return state


def summon_minion(
    state: "GameState",
    card_id_or_minion: Any = None,
    position: int = -1,
) -> "GameState":
    """Create and place a minion on the friendly board.

    Args:
        state: GameState to mutate.
        card_id_or_minion: A Minion object to place directly, or a dict with
            keys 'attack', 'health', 'name' to create a token, or None for a
            1/1 token.
        position: Board position (-1 = append at end).

    Returns:
        The mutated GameState (same object).
    """
    from analysis.card.engine.state import Minion as _Minion

    if len(state.board) >= 7:
        return state

    if isinstance(card_id_or_minion, _Minion):
        minion = card_id_or_minion
    elif isinstance(card_id_or_minion, dict):
        minion = _Minion(
            attack=card_id_or_minion.get("attack", 1),
            health=card_id_or_minion.get("health", 1),
            max_health=card_id_or_minion.get("health", 1),
            name=card_id_or_minion.get("name", "Token"),
            can_attack=False,
        )
    else:
        minion = _Minion(attack=1, health=1, max_health=1, name="Token", can_attack=False)

    if position < 0 or position >= len(state.board):
        state.board.append(minion)
    else:
        state.board.insert(position, minion)

    return state


def draw_cards(state: "GameState", count: int) -> "GameState":
    """Draw cards from the deck.

    Decrements deck_remaining. If the deck is empty, applies fatigue damage
    using DeterministicRNG for consistency.

    Args:
        state: GameState to mutate.
        count: Number of cards to draw.

    Returns:
        The mutated GameState (same object).
    """
    count = max(count, 0)
    for _ in range(count):
        if state.deck_remaining > 0:
            state.deck_remaining -= 1
        else:
            # Fatigue: incremental damage
            state.fatigue_damage += 1
            state.hero.hp -= state.fatigue_damage
    return state


def heal(state: "GameState", amount: int, target: Any = None) -> "GameState":
    """Restore HP up to max for hero or minion.

    Args:
        state: GameState to mutate.
        amount: Healing amount.
        target: int (board index), 'enemy_hero', 'friendly_hero',
                'all_enemy', 'all_friendly', or Minion/Hero object.
                Defaults to friendly_hero.

    Returns:
        The mutated GameState (same object).
    """
    if amount <= 0:
        return state

    if target is None:
        target = "friendly_hero"

    if target in ("all_enemy", "all_friendly", "all_minions"):
        entities = _iter_targets(state, target)
        for entity in entities:
            if hasattr(entity, "hp"):
                # Hero
                entity.hp = min(entity.hp + amount, entity.max_hp)
            elif hasattr(entity, "health"):
                # Minion
                entity.health = min(entity.health + amount, entity.max_health)
        return state

    entity = _get_target_entity(state, target)
    if entity is None:
        entity = state.hero

    if hasattr(entity, "hp"):
        # Hero
        entity.hp = min(entity.hp + amount, entity.max_hp)
    elif hasattr(entity, "health"):
        # Minion
        entity.health = min(entity.health + amount, entity.max_health)

    return state


def buff_minion(
    state: "GameState",
    target: Any,
    attack_delta: int = 0,
    health_delta: int = 0,
    keywords: Optional[List[str]] = None,
) -> "GameState":
    """Buff a minion's stats and optionally grant keywords.

    Args:
        state: GameState to mutate.
        target: int (board index), Minion object, or 'all_friendly'.
        attack_delta: Attack to add (can be negative for debuff).
        health_delta: Health to add (can be negative for debuff).
        keywords: List of keyword strings to grant, e.g. ['TAUNT', 'DIVINE_SHIELD'].

    Returns:
        The mutated GameState (same object).
    """
    if keywords is None:
        keywords = []

    if target == "all_friendly":
        for m in state.board:
            if attack_delta != 0:
                m.attack += attack_delta
            if health_delta != 0:
                m.health += health_delta
                m.max_health += health_delta
            for kw in keywords:
                _apply_keyword(m, kw)
        return state

    entity = _get_target_entity(state, target)
    if entity is not None and hasattr(entity, "attack"):
        if attack_delta != 0:
            entity.attack += attack_delta
        if health_delta != 0:
            entity.health += health_delta
            entity.max_health += health_delta
        for kw in keywords:
            _apply_keyword(entity, kw)

    return state


def destroy_minion(state: "GameState", target: Any) -> "GameState":
    """Remove a minion from the board.

    Args:
        state: GameState to mutate.
        target: int (board index), 'all_enemy', 'all_friendly', or Minion object.

    Returns:
        The mutated GameState (same object).
    """
    if target == "all_enemy":
        state.opponent.board = []
        return state
    if target == "all_friendly":
        state.board = []
        return state

    if isinstance(target, int):
        # Try friendly board first, then enemy
        if 0 <= target < len(state.board):
            state.board.pop(target)
        elif 0 <= target < len(state.opponent.board):
            state.opponent.board.pop(target)
    elif hasattr(target, "health"):
        # Minion object — remove by identity
        if target in state.board:
            state.board.remove(target)
        elif target in state.opponent.board:
            state.opponent.board.remove(target)

    return state


def transform_minion(
    state: "GameState",
    target: Any,
    attack: int = 1,
    health: int = 1,
) -> "GameState":
    """Replace a minion's stats (Polymorph, Hex, etc.).

    Strips all keywords, enchantments, and abilities; resets stats.

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object.
        attack: New attack value.
        health: New health value (also sets max_health).

    Returns:
        The mutated GameState (same object).
    """
    entity = _get_target_entity(state, target)
    if entity is None or not hasattr(entity, "attack"):
        return state

    entity.attack = attack
    entity.health = health
    entity.max_health = health

    # 清空所有标签（变形后无关键字）
    entity.tags.clear()
    entity.attacks_this_turn = 0

    entity.enchantments = []
    entity.abilities = []
    return state


def silence_minion(state: "GameState", target: Any) -> "GameState":
    """Strip all keywords, enchantments, and abilities from a minion.

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object.

    Returns:
        The mutated GameState (same object).
    """
    entity = _get_target_entity(state, target)
    if entity is None or not hasattr(entity, "attack"):
        return state

    # 沉默: 清空所有标签和附加效果
    entity.tags.clear()
    entity.attacks_this_turn = 0

    entity.enchantments = []
    entity.abilities = []
    return state


def freeze_target(state: "GameState", target: Any) -> "GameState":
    """Set the frozen flag on a target minion.

    Args:
        state: GameState to mutate.
        target: int (board index), 'all_enemy', 'all_friendly', or Minion object.

    Returns:
        The mutated GameState (same object).
    """
    if target == "all_enemy":
        for m in state.opponent.board:
            m.frozen_until_next_turn = True
        return state
    if target == "all_friendly":
        for m in state.board:
            m.frozen_until_next_turn = True
        return state

    entity = _get_target_entity(state, target)
    if entity is not None and hasattr(entity, "frozen_until_next_turn"):
        entity.frozen_until_next_turn = True

    return state


def take_control(state: "GameState", target: Any) -> "GameState":
    """Mind control: move an enemy minion to the friendly board.

    The minion loses can_attack and has_attacked_once (can't attack immediately
    unless it has Rush/Charge).

    Args:
        state: GameState to mutate.
        target: int (index into enemy board) or Minion object on enemy board.

    Returns:
        The mutated GameState (same object).
    """
    if isinstance(target, int):
        if 0 <= target < len(state.opponent.board):
            minion = state.opponent.board.pop(target)
        else:
            return state
    elif hasattr(target, "health") and target in state.opponent.board:
        minion = target
        state.opponent.board.remove(minion)
    else:
        return state

    minion.has_attacked_once = False
    minion.can_attack = False
    if len(state.board) < 7:
        state.board.append(minion)

    return state


def return_to_hand(state: "GameState", target: Any) -> "GameState":
    """Move a friendly minion back to hand.

    For enemy minions, they are simply removed from the board (no hand tracking).

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object.

    Returns:
        The mutated GameState (same object).
    """
    if isinstance(target, int):
        minion = None
        board = None
        is_enemy = False
        if 0 <= target < len(state.board):
            minion = state.board.pop(target)
            board = state.board
        elif 0 <= target < len(state.opponent.board):
            minion = state.opponent.board.pop(target)
            is_enemy = True
        if minion is None:
            return state
    elif hasattr(target, "health"):
        minion = target
        is_enemy = False
        if minion in state.board:
            state.board.remove(minion)
        elif minion in state.opponent.board:
            state.opponent.board.remove(minion)
            is_enemy = True
            return state  # Enemy: just remove, no hand tracking
        else:
            return state
    else:
        return state

    # Add to hand as a Card (friendly only)
    if not is_enemy and len(state.hand) < 10:
        from analysis.card.models.card import Card

        card = Card(
            name=getattr(minion, "name", ""),
            cost=getattr(minion, "cost", 0),
            card_type="MINION",
            attack=getattr(minion, "attack", 0),
            health=getattr(minion, "max_health", 0),
        )
        state.hand.append(card)

    return state


def copy_minion(state: "GameState", target: Any) -> "GameState":
    """Copy a target minion to the friendly board.

    The copy starts with has_attacked_once=False and can_attack=False.

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object to copy.

    Returns:
        The mutated GameState (same object).
    """
    import dataclasses

    entity = _get_target_entity(state, target)
    if entity is None or not hasattr(entity, "attack"):
        return state

    if len(state.board) >= 7:
        return state

    copy_m = dataclasses.replace(entity)
    copy_m.has_attacked_once = False
    copy_m.can_attack = False
    # Preserve dynamic attributes not in dataclass fields
    for attr in ("trigger_type", "trigger_effect", "english_text", "abilities"):
        val = getattr(entity, attr, None)
        if val is not None:
            setattr(copy_m, attr, val)
    state.board.append(copy_m)

    return state


def shuffle_into_deck(
    state: "GameState",
    card_id: Optional[str] = None,
) -> "GameState":
    """Add a card to the deck (increment deck_remaining).

    For MCTS determinism, we just track the count rather than storing
    actual card objects in the deck.

    Args:
        state: GameState to mutate.
        card_id: Optional card ID for tracking (not used in simulation).

    Returns:
        The mutated GameState (same object).
    """
    state.deck_remaining += 1
    return state


def swap_stats(state: "GameState", target: Any) -> "GameState":
    """Swap a minion's attack and health.

    After swap: minion.attack = old_health, minion.health = old_attack.

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object.

    Returns:
        The mutated GameState (same object).
    """
    entity = _get_target_entity(state, target)
    if entity is None or not hasattr(entity, "attack"):
        return state

    old_atk = entity.attack
    old_hp = entity.health
    entity.attack = old_hp
    entity.health = old_atk
    entity.max_health = old_atk

    return state


def equip_weapon(state: "GameState", card: Any = None) -> "GameState":
    """Equip a weapon to the friendly hero.

    Args:
        state: GameState to mutate.
        card: Dict with 'attack', 'health' (durability), 'name' keys,
              or a Weapon object, or None for a default 0/0 weapon.

    Returns:
        The mutated GameState (same object).
    """
    from analysis.card.engine.state import Weapon

    if isinstance(card, Weapon):
        state.hero.weapon = card
    elif isinstance(card, dict):
        state.hero.weapon = Weapon(
            attack=card.get("attack", 0),
            health=card.get("health", 0),
            name=card.get("name", "Weapon"),
        )
    else:
        state.hero.weapon = Weapon()

    return state


def gain_armor(state: "GameState", amount: int) -> "GameState":
    """Add armor to the friendly hero.

    Args:
        state: GameState to mutate.
        amount: Armor to gain.

    Returns:
        The mutated GameState (same object).
    """
    if amount > 0:
        state.hero.armor += amount
    return state


def reduce_cost(
    state: "GameState",
    amount: int,
    card_type_filter: Optional[str] = None,
) -> "GameState":
    """Reduce the cost of cards in hand.

    Args:
        state: GameState to mutate.
        amount: Cost reduction amount (applied per card).
        card_type_filter: Optional card type to filter, e.g. 'SPELL', 'MINION'.
            If None, reduces cost of all cards.

    Returns:
        The mutated GameState (same object).
    """
    if amount <= 0:
        return state
    for card in getattr(state, "hand", []):
        if card_type_filter is not None:
            card_type = getattr(card, "card_type", "").upper()
            if card_type != card_type_filter.upper():
                continue
        if hasattr(card, "cost"):
            card.cost = max(0, card.cost - amount)
    return state


def discard_cards(state: "GameState", count: int) -> "GameState":
    """Discard N random cards from hand using DeterministicRNG.

    Args:
        state: GameState to mutate.
        count: Number of cards to discard.

    Returns:
        The mutated GameState (same object).
    """
    count = max(count, 0)
    hand = getattr(state, "hand", [])
    if not hand or count <= 0:
        return state

    rng = DeterministicRNG.from_state(state)
    indices_to_discard = rng.sample(list(range(len(hand))), k=min(count, len(hand)))
    # Sort descending to avoid index shifting when removing
    for idx in sorted(indices_to_discard, reverse=True):
        if idx < len(hand):
            hand.pop(idx)

    return state


def enchant_minion(
    state: "GameState",
    target: Any,
    enchantment_dict: Dict[str, Any],
) -> "GameState":
    """Attach an enchantment dict to a target minion.

    The enchantment is appended to the minion's enchantments list.
    Callers are responsible for applying stat changes separately.

    Args:
        state: GameState to mutate.
        target: int (board index) or Minion object.
        enchantment_dict: Dict with enchantment data, e.g.
            {'name': 'enchant', 'attack': 2, 'health': 2}.

    Returns:
        The mutated GameState (same object).
    """
    entity = _get_target_entity(state, target)
    if entity is None or not hasattr(entity, "enchantments"):
        return state

    entity.enchantments.append(enchantment_dict)

    # Also apply stat deltas if present in the enchantment
    atk_delta = enchantment_dict.get("attack", 0)
    hp_delta = enchantment_dict.get("health", 0)
    if atk_delta:
        entity.attack += atk_delta
    if hp_delta:
        entity.health += hp_delta
        entity.max_health += hp_delta

    return state


def discover_card(
    state: "GameState",
    pool: List[Any],
    count: int = 3,
    score_fn: Optional[Callable[[Any], float]] = None,
) -> "GameState":
    """Discover: pick the best card from a pool and add to hand.

    Uses det_top_k for deterministic selection (no randomness).

    Args:
        state: GameState to mutate.
        pool: List of candidate cards to choose from.
        count: Number of cards to offer (picks top 1 from top K).
        score_fn: Scoring function (card) -> float. If None, uses
            a default heuristic (cost + attack + health).

    Returns:
        The mutated GameState (same object).
    """
    if not pool:
        return state
    if len(state.hand) >= 10:
        return state

    if score_fn is None:
        def score_fn(c: Any) -> float:
            """Default heuristic: prefer higher cost + stats."""
            cost = getattr(c, "cost", 0)
            attack = getattr(c, "attack", 0)
            health = getattr(c, "health", 0)
            return float(cost + attack + health)

    # Deterministic top-K selection
    top_cards = det_top_k(pool, k=min(count, len(pool)), score_fn=score_fn)
    if top_cards:
        # Pick the best one (index 0 after det_top_k sorting)
        best = top_cards[0]
        if len(state.hand) < 10:
            state.hand.append(best)

    return state

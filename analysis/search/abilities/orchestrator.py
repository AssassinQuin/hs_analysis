#!/usr/bin/env python3
"""orchestrator.py — Unified effect orchestration layer.

Single entry point for resolving card effects:
  - Target selection (greedy evaluation)
  - Spell power bonus
  - Lifesteal healing
  - Keyword triggers (herald, imbue, kindred, etc.)
  - Death resolution

Replaces the parallel paths in spell_simulator.py and battlecry_dispatcher.py.

Architecture:
  Card → AbilityParser.parse() → List[CardAbility]
       → orchestrate(state, card, abilities, context) → GameState
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, TYPE_CHECKING

from analysis.search.abilities.definition import (
    CardAbility, AbilityTrigger, EffectKind, EffectSpec,
)
from analysis.search.abilities.executor import execute_effects

if TYPE_CHECKING:
    from analysis.search.game_state import GameState
    from analysis.models.card import Card

log = logging.getLogger(__name__)

# Default target selector — can be overridden for testing or MCTS integration.
# This lazy import avoids coupling simulation → evaluation at module level.
_default_target_selector: Optional[Callable] = None


def _get_default_target_selector():
    """Lazy-load the greedy target evaluator (avoids sim→eval import coupling)."""
    global _default_target_selector
    if _default_target_selector is None:
        from analysis.evaluators.composite import target_selection_eval
        _default_target_selector = target_selection_eval
    return _default_target_selector


# ═══════════════════════════════════════════════════════════════
# Main orchestration entry point
# ═══════════════════════════════════════════════════════════════

def orchestrate(
    state: "GameState",
    card: "Card",
    abilities: List[CardAbility],
    context: Optional[dict] = None,
) -> "GameState":
    """Apply all card abilities to game state in the correct order.

    Args:
        state: Mutable game state (caller must copy beforehand).
        card: The card being played.
        abilities: Parsed abilities from AbilityParser.parse(card).
        context: Optional dict with extra info:
            - 'target_index': explicit target for targeted effects
            - 'card_index': hand position (for Outcast check)
            - 'is_minion': True if a minion is being played

    Returns:
        Modified game state (same object, mutated in-place).
    """
    ctx = context or {}
    target_index = ctx.get('target_index', -1)
    card_index = ctx.get('card_index', -1)
    is_minion = ctx.get('is_minion', False)
    source_minion = ctx.get('source_minion', None)

    # Calculate spell power bonus from friendly board
    spell_power = sum(getattr(m, 'spell_power', 0) for m in state.board)
    has_lifesteal = 'LIFESTEAL' in set(getattr(card, 'mechanics', []) or [])

    for ability in abilities:
        trigger = ability.trigger

        # Skip triggers that don't fire on play
        if trigger in (AbilityTrigger.TURN_START, AbilityTrigger.TURN_END,
                       AbilityTrigger.WHENEVER, AbilityTrigger.AFTER,
                       AbilityTrigger.ON_ATTACK, AbilityTrigger.ON_DAMAGE,
                       AbilityTrigger.ON_SPELL_CAST, AbilityTrigger.ON_FEL_SPELL_CAST,
                       AbilityTrigger.ON_DEATH, AbilityTrigger.SECRET,
                       AbilityTrigger.QUEST, AbilityTrigger.AURA,
                       AbilityTrigger.INFUSE, AbilityTrigger.CORRUPT):
            continue

        # Handle each trigger type
        if trigger == AbilityTrigger.BATTLECRY:
            state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)
            # Brann doubling: re-execute battlecry if a doubler is present
            if _has_battlecry_doubler(state, source_minion):
                state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)

        elif trigger == AbilityTrigger.COMBO:
            if len(state.cards_played_this_turn) > 0:
                state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)
                if _has_battlecry_doubler(state, source_minion):
                    state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)

        elif trigger == AbilityTrigger.OUTCAST:
            if _is_outcast_position(state, card, card_index):
                state = _handle_outcast(state, card, ability)

        elif trigger == AbilityTrigger.HERALD:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.IMBUE:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.KINDRED:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.COLOSSAL:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.DORMANT:
            state = _handle_dormant(state, card)

        elif trigger == AbilityTrigger.CORPSE_SPEND:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.ACTIVATE:
            state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)

        elif trigger == AbilityTrigger.DEATHRATTLE:
            state = execute_effects(state, card, ability.effects)

        elif trigger == AbilityTrigger.CHOOSE_ONE:
            pass  # handled separately by resolve_choose_one

    return state


# ═══════════════════════════════════════════════════════════════
# Trigger-specific handlers
# ═══════════════════════════════════════════════════════════════

def _apply_effects_with_modifiers(
    state: "GameState",
    card: "Card",
    ability: CardAbility,
    target_index: int,
    spell_power: int,
    has_lifesteal: bool,
) -> "GameState":
    """Apply ability effects with spell power, target selection, and lifesteal.

    Unified handler for BATTLECRY, COMBO, and ACTIVATE (spell) triggers.
    """
    for effect in ability.effects:
        # Add spell power to damage effects
        if effect.kind == EffectKind.DAMAGE and spell_power > 0:
            base_val = effect.value if isinstance(effect.value, int) else 0
            effect = EffectSpec(
                kind=effect.kind,
                value=base_val + spell_power,
                value2=effect.value2,
                subtype=effect.subtype,
                keyword=effect.keyword,
                target=effect.target,
                selector=effect.selector,
                condition=effect.condition,
                text_raw=effect.text_raw,
            )

        # Resolve target for targeted effects
        target = None
        if effect.kind in (EffectKind.DAMAGE, EffectKind.HEAL):
            target = _pick_target(state, target_index, effect)

        state = execute_effects(state, card, [effect], target)

        # Lifesteal: heal hero for damage dealt
        if has_lifesteal and effect.kind == EffectKind.DAMAGE:
            dmg = effect.value if isinstance(effect.value, int) else 0
            if dmg > 0:
                state.hero.hp = min(
                    getattr(state.hero, 'max_hp', 30),
                    state.hero.hp + dmg,
                )

    return state


def _handle_outcast(
    state: "GameState",
    card: "Card",
    ability: CardAbility,
) -> "GameState":
    """Apply outcast bonus effects."""
    return execute_effects(state, card, ability.effects)


def _handle_dormant(
    state: "GameState",
    card: "Card",
) -> "GameState":
    """Mark minion as dormant for N turns."""
    from analysis.search.abilities.extractors import extract_number_after
    text = (getattr(card, 'english_text', '') or getattr(card, 'text', '') or '').lower()
    turns = extract_number_after(text, 'dormant')
    if turns <= 0:
        turns = 2  # default

    if state.board:
        last = state.board[-1]
        last.is_dormant = True  # type: ignore[attr-defined]
        last.dormant_turns_remaining = turns  # type: ignore[attr-defined]
        last.can_attack = False
    return state


def _is_outcast_position(state: "GameState", card: "Card", card_index: int) -> bool:
    """Check if card is at leftmost or rightmost position in hand."""
    hand_size = len(state.hand)
    if hand_size <= 1:
        return True
    return card_index == 0 or card_index == hand_size - 1


def _pick_target(
    state: "GameState",
    target_index: int,
    effect: EffectSpec,
    target_selector: Optional[Callable] = None,
) -> Optional[str]:
    """Resolve target for targeted effects.

    If target_index >= 0, use it directly.
    Otherwise, use greedy evaluation to pick the best target.

    Args:
        target_selector: Optional callable(state) → float for greedy evaluation.
            Defaults to lazy-loaded target_selection_eval from composite module.
            Pass None to use the default, or a custom function for testing/MCTS.
    """
    if target_index >= 0:
        if target_index == 0:
            return 'enemy_hero'
        elif target_index > 0 and target_index <= len(state.opponent.board):
            return f'enemy_minion:{target_index - 1}'
        return 'enemy_hero'

    # Lazy-load the default selector only when actually needed
    if target_selector is None:
        target_selector = _get_default_target_selector()

    # Greedy target selection
    amount = effect.value if isinstance(effect.value, int) else 1
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
            score = target_selector(sim)
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


def _has_battlecry_doubler(state: "GameState", played_minion) -> bool:
    """Check if a friendly minion doubles battlecry triggers (e.g. Brann).

    Detects via:
    1. Enchantment with 'double_battlecry' trigger_effect (set by aura engine)
    2. Card English text containing both 'battlecry' and 'trigger twice'
    """
    if played_minion is None:
        return False
    for m in state.board:
        if m is played_minion:
            continue
        # Check enchantment for battlecry doubling (set by aura engine)
        for ench in getattr(m, 'enchantments', []) or []:
            etype = getattr(ench, 'trigger_effect', '') or ''
            if 'double_battlecry' in etype:
                return True
        # Generic: detect from card English text
        card = getattr(m, 'card_ref', None)
        if card:
            text = (getattr(card, 'english_text', '') or '').lower()
            if 'battlecry' in text and 'trigger twice' in text:
                return True
    return False

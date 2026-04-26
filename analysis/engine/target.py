"""target.py — 目标解析与确定性选择（零 copy-eval）。

替代 orchestrator._pick_target() 中的 copy-eval 循环（每次候选做 state.copy()）。
新方案：纯算术启发式打分 + 确定性排序，0 次 state.copy()。

Architecture:
  resolve_candidates(state, target_spec) → list
  best_target(state, effect) → Any
  validate_target(state, action) → bool
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Optional

from analysis.abilities.definition import EffectKind, EffectSpec, TargetKind

if TYPE_CHECKING:
    from analysis.engine.state import GameState

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# Candidate resolution
# ──────────────────────────────────────────────────────────────

def resolve_candidates(state: Any, target_spec: Any) -> list:
    """从目标规格解析候选列表。

    Args:
        state: GameState 实例（Any 类型，Phase 2 后改为具体类型）。
        target_spec: TargetSpec 或 EntitySelector 实例。

    Returns:
        候选目标列表。
    """
    # If target_spec has a select() method (EntitySelector), use it
    if target_spec is not None and hasattr(target_spec, 'select'):
        return target_spec.select(state)

    # If target_spec is a TargetSpec, resolve manually
    if target_spec is not None and hasattr(target_spec, 'kind'):
        kind = target_spec.kind  # type: ignore[union-attr]
        if kind in (TargetKind.ALL_ENEMY, TargetKind.ENEMY):
            return list(state.opponent.board)
        if kind == TargetKind.ALL_FRIENDLY:
            return list(state.board)
        if kind in (TargetKind.ALL_MINIONS, TargetKind.ALL):
            return list(state.board) + list(state.opponent.board)
        if kind == TargetKind.FRIENDLY_MINION:
            return list(state.board)
        if kind == TargetKind.FRIENDLY_HERO:
            return [state.hero]
        if kind in (TargetKind.RANDOM_ENEMY, TargetKind.RANDOM):
            if getattr(target_spec, 'side', '') == "enemy":
                return list(state.opponent.board)
            return list(state.board)
        if kind == TargetKind.SINGLE_MINION:
            return list(state.opponent.board)
        if kind == TargetKind.DAMAGED:
            board = state.board if getattr(target_spec, 'side', '') != "enemy" else state.opponent.board
            return [m for m in board if getattr(m, 'health', 0) < getattr(m, 'max_health', 0)]
        if kind == TargetKind.UNDAMAGED:
            board = state.board if getattr(target_spec, 'side', '') != "enemy" else state.opponent.board
            return [m for m in board if getattr(m, 'health', 0) >= getattr(m, 'max_health', 0)]
        if kind == TargetKind.SELF:
            return []

    # Fallback: empty candidates
    return []


# ──────────────────────────────────────────────────────────────
# Deterministic best target (zero copy-eval)
# ──────────────────────────────────────────────────────────────

def best_target(state: Any, effect: Any) -> Any:
    """确定性启发式目标选择 — 不做 state.copy()。

    Args:
        state: GameState 实例（Any 类型，Phase 2 后改为具体类型）。
        effect: EffectSpec 实例（Any 类型，Phase 2 后改为具体类型）。

    Returns:
        最佳目标（随从对象、英雄对象、或索引）。
    """
    target_spec = getattr(effect, 'target', None) or getattr(effect, 'selector', None)
    candidates = resolve_candidates(state, target_spec)

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Score each candidate
    scored = []
    for c in candidates:
        score = _target_heuristic(state, effect, c)
        scored.append((c, score))

    # Deterministic sort (no randomness)
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]


def _target_heuristic(state: Any, effect: Any, target: Any) -> float:
    """轻量级目标启发式打分函数。

    根据效果类型和目标属性计算分数：
    - DAMAGE: 优先击杀 (health <= value) + 高攻击优先
    - BUFF: 选最高 stats 的随从
    - HEAL: 选受伤最重的友方
    - 默认: 返回 0

    Args:
        state: GameState 实例。
        effect: EffectSpec 实例。
        target: 候选目标（Minion 或 Hero）。

    Returns:
        启发式分数（越高越优先）。
    """
    kind = getattr(effect, 'kind', None)
    value = getattr(effect, 'value', 0)
    if isinstance(value, int) is False:
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = 0

    if kind == EffectKind.DAMAGE:
        # Minion target
        if hasattr(target, 'health') and hasattr(target, 'attack'):
            hp = getattr(target, 'health', 0)
            atk = getattr(target, 'attack', 0)
            max_hp = getattr(target, 'max_health', hp)
            # Kill priority: can we kill it?
            if hp <= value:
                # Higher attack = higher threat = more value in killing
                kill_score = 100 + atk
                # Prefer targets with divine shield (waste removal)
                if getattr(target, 'has_divine_shield', False):
                    kill_score += 50
                return kill_score
            # Not killable: prefer high-threat minions
            return atk - hp * 0.5
        # Hero target
        if hasattr(target, 'hp'):
            hero_hp = getattr(target, 'hp', 30)
            hero_armor = getattr(target, 'armor', 0)
            return (30 - hero_hp - hero_armor) * 2
        return 0

    if kind == EffectKind.BUFF:
        if hasattr(target, 'attack') and hasattr(target, 'health'):
            atk = getattr(target, 'attack', 0)
            hp = getattr(target, 'health', 0)
            return atk + hp
        return 0

    if kind == EffectKind.HEAL:
        if hasattr(target, 'health') and hasattr(target, 'max_health'):
            hp = getattr(target, 'health', 0)
            max_hp = getattr(target, 'max_health', 0)
            damage_taken = max_hp - hp
            # Prioritize most damaged
            if damage_taken > 0:
                return 50 + damage_taken
            return 0
        if hasattr(target, 'hp'):
            hero_hp = getattr(target, 'hp', 0)
            max_hp = getattr(target, 'max_hp', 30)
            damage_taken = max_hp - hero_hp
            if damage_taken > 0:
                return 50 + damage_taken
            return 0
        return 0

    if kind == EffectKind.DESTROY:
        # Prefer high-value targets
        if hasattr(target, 'attack') and hasattr(target, 'health'):
            atk = getattr(target, 'attack', 0)
            hp = getattr(target, 'health', 0)
            cost = getattr(target, 'cost', 0)
            return atk + hp + cost
        return 0

    # Default: neutral score
    return 0


# ──────────────────────────────────────────────────────────────
# Target validation
# ──────────────────────────────────────────────────────────────

def validate_target(state: Any, action: Any) -> bool:
    """验证动作目标是否合法（嘲讽/潜行/免疫）。

    Args:
        state: GameState 实例（Any 类型，Phase 2 后改为具体类型）。
        action: 动作对象，需有 target 属性。

    Returns:
        True 如果目标合法，False 如果被嘲讽/潜行/免疫阻挡。
    """
    target = getattr(action, 'target', None)
    if target is None:
        return True

    action_type = getattr(action, 'action_type', getattr(action, 'type', ''))

    # Only validate attack actions
    if action_type not in ('ATTACK', 'attack', 'hero_attack'):
        return True

    target_idx = None
    if isinstance(target, int):
        target_idx = target
    elif isinstance(target, str) and target.startswith('enemy_minion:'):
        try:
            target_idx = int(target.split(':')[1])
        except (IndexError, ValueError):
            return True

    opp_board = getattr(state, 'opponent', None)
    if opp_board is None:
        return True
    enemy_board = getattr(opp_board, 'board', [])

    if target_idx is not None and target_idx < len(enemy_board):
        target_minion = enemy_board[target_idx]

        # Check stealth — cannot target stealthed minions (unless revealed)
        if getattr(target_minion, 'has_stealth', False):
            return False

        # Check immune — cannot target immune minions
        if getattr(target_minion, 'has_immune', False):
            return False

    # Check taunt — must attack taunt minions first
    has_taunt = any(getattr(m, 'has_taunt', False) for m in enemy_board)
    if has_taunt:
        # If attacking face but there's a taunt, invalid
        if action_type in ('hero_attack',) or (isinstance(target, str) and 'hero' in target):
            return False
        # If attacking a non-taunt minion but taunts exist, invalid
        if target_idx is not None and target_idx < len(enemy_board):
            if not getattr(enemy_board[target_idx], 'has_taunt', False):
                return False

    return True


# ──────────────────────────────────────────────────────────────
# Orchestration (migrated from abilities/orchestrator.py)
# ──────────────────────────────────────────────────────────────

def orchestrate(
    state,
    card,
    abilities: list,
    context: Optional[dict] = None,
):
    """Apply all card abilities to game state in the correct order.

    Unified entry point for resolving card effects:
      - Target selection (greedy evaluation)
      - Spell power bonus
      - Lifesteal healing
      - Keyword triggers (herald, imbue, kindred, etc.)
      - Death resolution

    Args:
        state: Mutable game state (caller must copy beforehand).
        card: The card being played.
        abilities: Parsed abilities from AbilityParser.parse(card).
        context: Optional dict with extra info:
            - 'target_index': explicit target for targeted effects
            - 'card_index': hand position (for Outcast check)
            - 'is_minion': True if a minion is being played
            - 'source_minion': the minion being played (for Brann check)

    Returns:
        Modified game state (same object, mutated in-place).
    """
    from analysis.abilities.definition import (
        AbilityTrigger, EffectKind, EffectSpec,
    )
    from analysis.engine.executor import execute_effects

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
            if _has_battlecry_doubler(state, source_minion):
                state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)

        elif trigger == AbilityTrigger.COMBO:
            if len(state.cards_played_this_turn) > 0:
                state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)
                if _has_battlecry_doubler(state, source_minion):
                    state = _apply_effects_with_modifiers(state, card, ability, target_index, spell_power, has_lifesteal)

        elif trigger == AbilityTrigger.OUTCAST:
            if _is_outcast_position(state, card, card_index):
                state = execute_effects(state, card, ability.effects)

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


def _apply_effects_with_modifiers(
    state, card, ability, target_index: int, spell_power: int, has_lifesteal: bool,
):
    """Apply ability effects with spell power, target selection, and lifesteal."""
    from analysis.abilities.definition import EffectKind, EffectSpec

    for effect in ability.effects:
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

        target = None
        if effect.kind in (EffectKind.DAMAGE, EffectKind.HEAL):
            target = _pick_target(state, target_index, effect)

        state = execute_effects(state, card, [effect], target)

        if has_lifesteal and effect.kind == EffectKind.DAMAGE:
            dmg = effect.value if isinstance(effect.value, int) else 0
            if dmg > 0:
                state.hero.hp = min(
                    getattr(state.hero, 'max_hp', 30),
                    state.hero.hp + dmg,
                )

    return state


def _handle_dormant(state, card):
    """Mark minion as dormant for N turns."""
    text = (getattr(card, 'english_text', '') or getattr(card, 'text', '') or '').lower()
    turns = 0
    idx = text.find('dormant')
    if idx >= 0:
        after = text[idx + 7:].strip()
        for part in after.split():
            if part.isdigit():
                turns = int(part)
                break
    if turns <= 0:
        turns = 2

    if state.board:
        last = state.board[-1]
        last.is_dormant = True
        last.dormant_turns_remaining = turns
        last.can_attack = False
    return state


def _is_outcast_position(state, card, card_index: int) -> bool:
    """Check if card is at leftmost or rightmost position in hand."""
    hand_size = len(state.hand)
    if hand_size <= 1:
        return True
    return card_index == 0 or card_index == hand_size - 1


def _pick_target(state, target_index: int, effect, target_selector=None):
    """Resolve target for targeted effects.

    If target_index >= 0, use it directly.
    Otherwise, use greedy evaluation to pick the best target.
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

    if target_selector is None:
        return 'enemy_hero'

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


_default_target_selector = None


def _get_default_target_selector():
    """Lazy-load the greedy target evaluator."""
    global _default_target_selector
    if _default_target_selector is None:
        try:
            from analysis.evaluators.composite import target_selection_eval
            _default_target_selector = target_selection_eval
        except (ImportError, AttributeError):
            _default_target_selector = False
    return _default_target_selector if _default_target_selector else None


def _has_battlecry_doubler(state, played_minion) -> bool:
    """Check if a friendly minion doubles battlecry triggers (e.g. Brann)."""
    if played_minion is None:
        return False
    for m in state.board:
        if m is played_minion:
            continue
        for ench in getattr(m, 'enchantments', []) or []:
            etype = getattr(ench, 'trigger_effect', '') or ''
            if 'double_battlecry' in etype:
                return True
        card = getattr(m, 'card_ref', None)
        if card:
            text = (getattr(card, 'english_text', '') or '').lower()
            if 'battlecry' in text and 'trigger twice' in text:
                return True
    return False

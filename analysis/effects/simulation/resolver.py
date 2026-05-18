"""resolver.py — Effect → GameState mutation dispatcher.

Takes a parsed Effect object and dispatches to the correct primitive(s),
handling target resolution, condition checking, and logging.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from analysis.effects.types import (
    Effect, EffectKind, ResolvedEffect, TargetKind, TargetSpec,
)

# Effect kinds that don't need explicit target resolution
# Effect kinds that deal damage → prefer enemy targets
_DAMAGE_KINDS: frozenset[EffectKind] = frozenset({
    EffectKind.DAMAGE, EffectKind.AOE_DAMAGE, EffectKind.RANDOM_DAMAGE,
    EffectKind.DESTROY, EffectKind.SILENCE, EffectKind.TRANSFORM,
    EffectKind.DEBUFF,
})

# Effect kinds that are beneficial → prefer friendly targets
_BENEFICIAL_KINDS: frozenset[EffectKind] = frozenset({
    EffectKind.BUFF, EffectKind.HEAL, EffectKind.ARMOR,
    EffectKind.HAND_BUFF, EffectKind.DECK_BUFF,
})

_NO_TARGET_KINDS: frozenset[EffectKind] = frozenset({
    EffectKind.SUMMON, EffectKind.DRAW, EffectKind.DISCARD,
    EffectKind.SHUFFLE, EffectKind.ARMOR, EffectKind.GAIN_MANA,
    EffectKind.OVERLOAD, EffectKind.CORPSE_GAIN, EffectKind.CORPSE_SPEND,
    EffectKind.WEAPON_EQUIP, EffectKind.HERO_POWER_SET,
    EffectKind.DISCOVER, EffectKind.CREATE,
    EffectKind.DECK_BUFF, EffectKind.HAND_BUFF,
    EffectKind.ENCHANT,
    EffectKind.HERALD_SUMMON, EffectKind.IMBUE_UPGRADE,
    EffectKind.COLOSSAL_SUMMON, EffectKind.DARK_GIFT_APPLY,
    EffectKind.FATIGUE,
})

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


class EffectResolver:
    """Resolve and apply Effects against a GameState.

    Usage:
        resolver = EffectResolver()
        for effect in parsed_card.battlecry.effects:
            resolver.apply(state, effect)
    """

    def __init__(self) -> None:
        self._pending: list[ResolvedEffect] = []

    def _dispatch_no_target(self, state: GameState,
                            effect: Effect) -> None:
        """Dispatch effects that don't need target resolution."""
        kind = effect.kind
        params = effect.params

        if kind == EffectKind.SUMMON:
            from analysis.effects.primitives.summon import apply_summon
            apply_summon(state, **params)
        elif kind == EffectKind.DRAW:
            from analysis.effects.primitives.draw import apply_draw
            apply_draw(state, **params)
        elif kind == EffectKind.ARMOR:
            from analysis.effects.primitives.damage import apply_armor
            apply_armor(state, **params)
        elif kind == EffectKind.HAND_BUFF:
            from analysis.effects.primitives.modify import apply_hand_buff
            apply_hand_buff(state, **params)
        elif kind == EffectKind.DISCARD:
            from analysis.effects.primitives.draw import apply_discard
            apply_discard(state, **params)
        elif kind == EffectKind.GAIN_MANA:
            from analysis.effects.primitives.resource import apply_gain_mana
            apply_gain_mana(state, **params)
        elif kind == EffectKind.CORPSE_GAIN:
            from analysis.effects.primitives.resource import apply_corpse_gain
            apply_corpse_gain(state, **params)
        elif kind == EffectKind.WEAPON_EQUIP:
            from analysis.effects.primitives.resource import apply_weapon_equip
            apply_weapon_equip(state, **params)
        else:
            log.debug("Unhandled no-target EffectKind: %s (%s)", kind, params)

    # ════════════════════════════════════════════════════════════
    # Public API
    # ════════════════════════════════════════════════════════════

    def apply(self, state: GameState, effect: Effect,
              source_id: str = "") -> list[ResolvedEffect]:
        """Resolve and apply a single Effect to the GameState.

        Returns list of ResolvedEffect for logging/replay.
        """
        # Check conditions first
        if effect.condition is not None:
            if not self._check_condition(state, effect.condition):
                return []

        # Resolve targets
        targets = self._resolve_targets(state, effect.target, effect.kind)

        # Effects that work zone-wide (summon, draw, etc.) need no targets
        if not targets and not effect.target.is_aoe():
            if effect.kind in _NO_TARGET_KINDS:
                self._dispatch_no_target(state, effect)
                return [ResolvedEffect(
                    effect=effect, target_ids=[],
                    source_id=source_id,
                    resolution_note="no-target",
                )]
            # No valid targets for a targeted effect → nothing happens
            return []

        resolved: list[ResolvedEffect] = []
        for target_id in targets:
            result = ResolvedEffect(
                effect=effect,
                target_ids=[target_id],
                source_id=source_id,
            )
            self._dispatch(state, effect, target_id)
            resolved.append(result)

        # For AOE effects with no explicit targets, still dispatch once
        if not targets and effect.target.is_aoe():
            self._dispatch_aoe(state, effect)
            resolved.append(ResolvedEffect(
                effect=effect,
                target_ids=[],
                source_id=source_id,
                resolution_note="aoe",
            ))

        # Self-targeting effects (Armor, etc.)
        if not targets and effect.target.kind == TargetKind.SELF:
            self._dispatch_self(state, effect)
            resolved.append(ResolvedEffect(
                effect=effect,
                target_ids=["self"],
                source_id=source_id,
            ))

        return resolved

    # ════════════════════════════════════════════════════════════
    # Target resolution
    # ════════════════════════════════════════════════════════════

    def _resolve_targets(self, state: GameState,
                         spec: TargetSpec,
                         effect_kind: EffectKind | None = None) -> list[str]:
        """Resolve a TargetSpec to concrete entity IDs.

        Returns list of target ID strings like:
          "hero", "friendly:0", "enemy:2", "minion:1"

        Args:
            state: Current GameState.
            spec: TargetSpec to resolve.
            effect_kind: The EffectKind, used to bias default target selection.
        """
        kind = spec.kind

        # — No target —
        if kind == TargetKind.NONE:
            return []
        if kind == TargetKind.SELF:
            return []

        # — Board-wide —
        if kind == TargetKind.ALL_ENEMIES:
            return [f"enemy:{i}" for i in range(len(state.opponent.board))]
        if kind == TargetKind.ALL_MINIONS:
            friendly = [f"friendly:{i}" for i in range(len(state.board))]
            enemy = [f"enemy:{i}" for i in range(len(state.opponent.board))]
            return friendly + enemy
        if kind == TargetKind.ALL_CHARACTERS:
            ids = ["hero"]
            ids += [f"friendly:{i}" for i in range(len(state.board))]
            ids += [f"enemy:{i}" for i in range(len(state.opponent.board))]
            return ids
        if kind == TargetKind.ALL_FRIENDLY:
            return [f"friendly:{i}" for i in range(len(state.board))]
        if kind == TargetKind.ALL_OTHER_MINIONS:
            return [f"friendly:{i}" for i in range(1, len(state.board))] + \
                   [f"enemy:{i}" for i in range(len(state.opponent.board))]

        # — Heroes —
        if kind == TargetKind.HERO:
            return ["hero"]
        if kind == TargetKind.ENEMY_HERO:
            return ["enemy_hero"]

        # — Random —
        import random
        if kind in (TargetKind.RANDOM_ENEMY, TargetKind.RANDOM_ENEMY_MINION):
            board = state.opponent.board
            if board:
                return [f"enemy:{random.randrange(len(board))}"]
            return []
        if kind == TargetKind.RANDOM_MINION:
            all_minions = (
                [f"friendly:{i}" for i in range(len(state.board))] +
                [f"enemy:{i}" for i in range(len(state.opponent.board))]
            )
            if all_minions:
                return [random.choice(all_minions)]
            return []

        # — Selected / targeted —
        if kind == TargetKind.SELECTED or kind == TargetKind.ANY_MINION:
            return self._default_target(state, spec, effect_kind)

        if kind == TargetKind.ENEMY_MINION:
            if state.opponent.board:
                return ["enemy:0"]
            return []

        if kind == TargetKind.FRIENDLY_MINION:
            if state.board:
                return ["friendly:0"]
            return []

        if kind == TargetKind.DAMAGED_MINION:
            for i, m in enumerate(state.opponent.board):
                if m.health < m.max_health:
                    return [f"enemy:{i}"]
            for i, m in enumerate(state.board):
                if m.health < m.max_health:
                    return [f"friendly:{i}"]
            return []

        # — Zones —
        if kind == TargetKind.BOARD:
            return ["board"]  # placeholder — summon effects target the board
        if kind == TargetKind.DECK:
            return ["deck"]
        if kind == TargetKind.HAND:
            return ["hand"]

        log.debug("Unhandled TargetSpec: %s", spec)
        return []

    # ════════════════════════════════════════════════════════════
    # Condition checking
    # ════════════════════════════════════════════════════════════

    def _default_target(self, state: GameState,
                        spec: TargetSpec,
                        effect_kind: EffectKind | None = None) -> list[str]:
        """Choose a default target when player selection is not available.

        Bias: damaging effects hit enemy, beneficial effects hit friendly.
        """
        # Damage-dealing effects → enemy first
        if effect_kind in _DAMAGE_KINDS:
            if state.opponent.board:
                return ["enemy:0"]
            if state.board:
                return ["friendly:0"]
            return ["enemy_hero"]

        # Buff/healing effects → friendly first
        if effect_kind in _BENEFICIAL_KINDS:
            if state.board:
                return ["friendly:0"]
            if state.opponent.board:
                return ["enemy:0"]
            return ["hero"]

        # Neutral: enemy minion first, then friendly, then hero
        if state.opponent.board:
            return ["enemy:0"]
        if state.board:
            return ["friendly:0"]
        return ["hero"]

    def _check_condition(self, state: GameState,
                         condition: Any) -> bool:
        """Check a ConditionSpec (stub — full impl in Phase 4)."""
        from analysis.effects.types import ConditionKind, ConditionSpec

        if not isinstance(condition, ConditionSpec):
            return True

        kind = condition.kind
        params = condition.params

        if kind == ConditionKind.BOARD_SIZE:
            op = params.get("op", ">=")
            val = params.get("value", 7)
            size = len(state.board)
            return _cmp(size, op, val)

        if kind == ConditionKind.CORPSES_AVAILABLE:
            return (state.corpses or 0) >= params.get("value", 1)

        if kind == ConditionKind.SPELLS_CAST_THIS_TURN:
            op = params.get("op", ">=")
            val = params.get("value", 1)
            return _cmp(state.spells_cast_this_turn, op, val)

        if kind == ConditionKind.CARDS_DRAWN_THIS_TURN:
            op = params.get("op", ">=")
            val = params.get("value", 1)
            return _cmp(state.cards_drawn_this_turn, op, val)

        if kind == ConditionKind.CARDS_PLAYED_THIS_TURN:
            played = len(state.cards_played_this_turn)
            op = params.get("op", ">=")
            val = params.get("value", 1)
            return _cmp(played, op, val)

        # Composition
        if kind == ConditionKind.AND:
            return all(self._check_condition(state, sub)
                       for sub in condition.sub)
        if kind == ConditionKind.OR:
            return any(self._check_condition(state, sub)
                       for sub in condition.sub)
        if kind == ConditionKind.NOT:
            return not self._check_condition(state, condition.sub[0])

        return True

    # ════════════════════════════════════════════════════════════
    # Dispatch
    # ════════════════════════════════════════════════════════════

    def _dispatch(self, state: GameState, effect: Effect,
                  target_id: str) -> None:
        """Dispatch a single effect to the correct primitive."""
        kind = effect.kind
        params = effect.params

        if kind == EffectKind.DAMAGE:
            amount = params.get("amount", 0)
            from analysis.effects.primitives.damage import apply_damage
            apply_damage(state, target_id, amount)

        elif kind == EffectKind.HEAL:
            amount = params.get("amount", 0)
            from analysis.effects.primitives.damage import apply_heal
            apply_heal(state, target_id, amount)

        elif kind == EffectKind.ARMOR:
            amount = params.get("amount", 0)
            from analysis.effects.primitives.damage import apply_armor
            apply_armor(state, amount)

        elif kind == EffectKind.SUMMON:
            from analysis.effects.primitives.summon import apply_summon
            apply_summon(state, **params)

        elif kind == EffectKind.DRAW:
            count = params.get("count", 1)
            from analysis.effects.primitives.draw import apply_draw
            apply_draw(state, count)

        elif kind == EffectKind.DISCARD:
            count = params.get("count", 1)
            from analysis.effects.primitives.draw import apply_discard
            apply_discard(state, count)

        elif kind == EffectKind.BUFF:
            atk = params.get("attack", 0)
            hp = params.get("health", 0)
            from analysis.effects.primitives.modify import apply_buff
            apply_buff(state, target_id, atk, hp)

        elif kind == EffectKind.HAND_BUFF:
            atk = params.get("attack", 0)
            hp = params.get("health", 0)
            from analysis.effects.primitives.modify import apply_hand_buff
            apply_hand_buff(state, atk, hp)

        elif kind == EffectKind.DESTROY:
            from analysis.effects.primitives.modify import apply_destroy
            apply_destroy(state, target_id)

        elif kind == EffectKind.SILENCE:
            from analysis.effects.primitives.modify import apply_silence
            apply_silence(state, target_id)

        elif kind == EffectKind.TRANSFORM:
            from analysis.effects.primitives.modify import apply_transform
            apply_transform(state, target_id)

        elif kind == EffectKind.GAIN_MANA:
            amount = params.get("amount", 0)
            temp = params.get("temporary", False)
            from analysis.effects.primitives.resource import apply_gain_mana
            apply_gain_mana(state, amount, temporary=temp)

        elif kind == EffectKind.CORPSE_GAIN:
            amount = params.get("amount", 0)
            from analysis.effects.primitives.resource import apply_corpse_gain
            apply_corpse_gain(state, amount)

        elif kind == EffectKind.WEAPON_EQUIP:
            atk = params.get("attack", 0)
            dur = params.get("durability", 0)
            from analysis.effects.primitives.resource import apply_weapon_equip
            apply_weapon_equip(state, attack=atk, durability=dur)

        elif kind == EffectKind.DISCOVER:
            log.debug("DISCOVER effect: %s (stub — needs UI integration)", params)

        else:
            log.debug("Unhandled EffectKind: %s", kind)

    def _dispatch_aoe(self, state: GameState, effect: Effect) -> None:
        """Dispatch an AOE damage effect."""
        kind = effect.kind
        params = effect.params

        if kind == EffectKind.AOE_DAMAGE:
            amount = params.get("amount", 0)
            target_kind = effect.target.kind.value if effect.target else "enemy"
            from analysis.effects.primitives.damage import apply_aoe_damage
            apply_aoe_damage(state, amount, target_kind)

        elif kind == EffectKind.DESTROY:
            # AOE destroy — handle all minions
            target_kind = effect.target.kind
            if target_kind in (TargetKind.ALL_MINIONS, TargetKind.ALL_ENEMIES):
                board = (state.opponent.board
                         if target_kind == TargetKind.ALL_ENEMIES
                         else state.board + state.opponent.board)
                for minion in board:
                    minion.health = 0

    def _dispatch_self(self, state: GameState, effect: Effect) -> None:
        """Dispatch a self-targeting effect."""
        kind = effect.kind
        params = effect.params

        if kind == EffectKind.ARMOR:
            from analysis.effects.primitives.damage import apply_armor
            apply_armor(state, params.get("amount", 0))
        elif kind == EffectKind.BUFF:
            atk = params.get("attack", 0)
            hp = params.get("health", 0)
            if state.board:
                from analysis.effects.primitives.modify import apply_buff
                apply_buff(state, "friendly:0", atk, hp)
        elif kind == EffectKind.WEAPON_EQUIP:
            from analysis.effects.primitives.resource import apply_weapon_equip
            apply_weapon_equip(state, **params)


def _cmp(value: int, op: str, target: int) -> bool:
    if op == ">=":
        return value >= target
    elif op == ">":
        return value > target
    elif op == "<=":
        return value <= target
    elif op == "<":
        return value < target
    elif op == "==":
        return value == target
    return False

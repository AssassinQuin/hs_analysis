"""abilities/executor.py — v2 SpellExecutor 编排引擎。

职责:
  1. 接收 CardAbility + source + target
  2. 解析 SpellDesc 递归树
  3. 调用对应的 Spell 子类
  4. 管理触发器调度
  5. 返回变更后的 GameState

入口:
  SpellExecutor.execute(card_ability, state, source, target)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from analysis.card.abilities.model import CardAbility, SpellDesc
    from analysis.card.engine.state import GameState
    from analysis.card.trigger.trigger import TriggerRegistry

log = logging.getLogger(__name__)


class SpellExecutor:
    """法术执行引擎。

    无状态（所有状态在 GameState 和 SpellDesc 中），可复用。
    """

    @staticmethod
    def execute(
        ability: "CardAbility",
        state: "GameState",
        source: Any = None,
        target: Any = None,
        **context,
    ) -> "GameState":
        """执行 CardAbility 的全部效果。

        参数:
            ability: 要执行的 CardAbility
            state: 游戏状态
            source: 效果来源（随从/卡牌/英雄）
            target: 玩家选择的目标（法术目标/随从目标）
        返回:
            变更后的 GameState
        """
        if not ability or not ability.has_any:
            return state

        # 1. 执行 on_play / battlecry
        if ability.on_play:
            state = SpellExecutor._execute_desc(
                ability.on_play, state, source, target,
            )

        # 2. 执行 combo（如果 applicable）
        _cpt = getattr(state, 'cards_played_this_turn', 0)
        if isinstance(_cpt, list):
            _cpt = len(_cpt)
        if ability.combo and _cpt > 0:
            state = SpellExecutor._execute_desc(
                ability.combo, state, source, target,
            )

        # 3. 执行 outcast
        if ability.outcast:
            state = SpellExecutor._execute_desc(
                ability.outcast, state, source, target,
            )

        # 4. 注册触发器（亡语 + triggers）
        trigger_registry: Optional[TriggerRegistry] = getattr(
            state, '_trigger_registry', None
        )
        if trigger_registry and (ability.deathrattle or ability.triggers):
            owner_id = getattr(source, 'card_id', '') or str(id(source))
            trigger_registry.register_card_ability(ability, source, owner_id)

        # 5. 注册光环
        if ability.aura:
            state = SpellExecutor._register_aura(ability.aura, state, source)

        return state

    @staticmethod
    def _execute_desc(
        desc: "SpellDesc",
        state: "GameState",
        source: Any = None,
        target: Any = None,
    ) -> "GameState":
        """执行单个 SpellDesc。"""
        # 确保 spell 注册表已初始化
        from analysis.card.abilities.registry import init_all
        init_all()
        from analysis.card.spells import get_spell_class
        spell_cls = get_spell_class(desc.spell_class)
        if spell_cls is None:
            if desc.spell_class != "TODO":
                log.warning("executor: 未找到 Spell 类 %r", desc.spell_class)
            return state
        return spell_cls().execute(desc, state, source, target)

    @staticmethod
    def _register_aura(
        aura_desc: "SpellDesc",
        state: "GameState",
        source: Any = None,
    ) -> "GameState":
        """注册光环效果。"""
        aura_registry = getattr(state, '_aura_registry', None)
        if aura_registry is None:
            return state
        aura_registry.register(aura_desc, source)
        # 立即施加光环
        from analysis.card.spells.aura import AuraBuffSpell
        return AuraBuffSpell().execute(aura_desc, state, source)

    # ── 便捷入口 ──

    @staticmethod
    def execute_on_play(
        state: "GameState",
        source: Any,
        target: Any = None,
    ) -> "GameState":
        """便捷方法: 仅执行卡牌的 on_play 效果。"""
        ability: Optional[CardAbility] = getattr(source, 'ability', None) or getattr(source, 'abilities', None)
        if ability is None or not ability.has_any:
            return state
        return SpellExecutor.execute(ability, state, source, target)

    @staticmethod
    def fire_event(
        event: str,
        state: "GameState",
        event_source: Any = None,
        event_target: Any = None,
    ) -> "GameState":
        """触发指定事件的所有触发器。"""
        trigger_registry = getattr(state, '_trigger_registry', None)
        if trigger_registry is None:
            return state
        return trigger_registry.fire(event, state, event_source, event_target)

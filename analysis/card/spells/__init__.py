"""spells/ — v2 Spell 系统。

所有 Spell 子类通过 @register_spell 装饰器自动注册到 SPELL_REGISTRY。
Spell 实例是无状态的（状态在 SpellDesc 中），可复用。
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from analysis.card.abilities.model import SpellDesc
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════════════════════════

SPELL_REGISTRY: Dict[str, type["Spell"]] = {}


def register_spell(cls: type["Spell"]) -> type["Spell"]:
    """装饰器: 将 Spell 子类注册到 SPELL_REGISTRY。"""
    name = cls.__name__
    SPELL_REGISTRY[name] = cls
    return cls


def get_spell_class(name: str) -> Optional[type["Spell"]]:
    """按名称查找 Spell 类。"""
    return SPELL_REGISTRY.get(name)


# ═══════════════════════════════════════════════════════════════
# Spell 基类
# ═══════════════════════════════════════════════════════════════

class Spell(ABC):
    """v2 Spell 基类。

    execute() 接收 SpellDesc 而非构造时参数，使 Spell 实例无状态。
    """

    @abstractmethod
    def execute(
        self,
        desc: "SpellDesc",
        state: "GameState",
        source: Any = None,
        target: Any = None,
    ) -> "GameState":
        ...

    def to_action_desc(self, desc: "SpellDesc") -> Dict:
        """将 SpellDesc 转为旧版 action dict（用于兼容层）。"""
        return {}

    @classmethod
    def from_desc(cls, desc: "SpellDesc") -> "Spell":
        """从 SpellDesc 查找并返回 Spell 实例（工厂）。"""
        spell_cls = get_spell_class(desc.spell_class)
        if spell_cls is None:
            log.warning("Spell 注册表中未找到 %r，使用 NoOp", desc.spell_class)
            from analysis.card.spells.effects import NoOpSpell
            return NoOpSpell()
        return spell_cls()


# 全局空操作实例（避免重复分配）
_NOOP_SPELL: Optional["Spell"] = None

def _get_noop():
    global _NOOP_SPELL
    if _NOOP_SPELL is None:
        from analysis.card.spells.effects import NoOpSpell
        _NOOP_SPELL = NoOpSpell()
    return _NOOP_SPELL

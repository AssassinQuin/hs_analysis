"""spells/aura.py — Aura 相关 Spell。

AuraBuffSpell 是数据驱动的光环效果，替代 engine/aura.py 的硬编码逻辑。

JSON:
  {"class": "AuraBuffSpell",
   "attack_bonus": 1, "health_bonus": 1,
   "target": "OTHER_FRIENDLY_MINIONS"}

配合 TriggerRegistry 在每次场面变更后自动重算。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Any

from analysis.card.spells import Spell, register_spell
from analysis.card.target.selector import resolve_target
from analysis.card.target.filter import apply_filter

if TYPE_CHECKING:
    from analysis.card.abilities.model import SpellDesc
    from analysis.card.engine.state import GameState, Minion

log = logging.getLogger(__name__)


@register_spell
class AuraBuffSpell(Spell):
    """光环增益 — 持续性地给符合条件的随从加攻击/生命。

    此 Spell 是"重算型"：每次场面变更后，清除旧光环效果，
    然后对所有当前符合条件的随从重新施加。

    工作原理:
      1. 每张光环随从的 abilities 中包含此 SpellDesc
      2. recompute_auras() 会遍历所有活跃光环
      3. 每个光环先清除自己的贡献，再重新施加
    """
    def execute(self, desc, state, source=None, target=None):
        """施加/刷新光环效果。"""
        targets = self._get_aura_targets(desc, state, source)
        for t in targets:
            self._apply_buff(t, desc)
        return state

    def clear(self, desc, state, source=None):
        """清除本光环对目标的影响。"""
        targets = self._get_aura_targets(desc, state, source)
        for t in targets:
            self._remove_buff(t, desc)
        return state

    def _get_aura_targets(self, desc, state, source):
        targets = resolve_target(desc.target or "OTHER_FRIENDLY_MINIONS",
                                 state, source, None)
        if desc.filter:
            targets = apply_filter(targets, desc.filter, source)
        return targets

    def _apply_buff(self, target, desc):
        atk = desc.attack_bonus or 0
        hp = desc.health_bonus or 0
        if atk:
            target.attack += atk
        if hp:
            target.health += hp
            target.max_health += hp

    def _remove_buff(self, target, desc):
        atk = desc.attack_bonus or 0
        hp = desc.health_bonus or 0
        if atk:
            target.attack -= atk
        if hp:
            target.health = max(1, target.health - hp)
            target.max_health -= hp

"""card-abilities v2 — 数据驱动的卡牌效果系统。

代替旧版 card_abilities.json + 文本回退 scheme。
提供递归 SpellDesc 模型 + SpellExecutor 引擎 + TriggerRegistry 触发器系统。
"""
from analysis.card.abilities.model import CardAbility, SpellDesc, TriggerDesc
from analysis.card.abilities.executor import SpellExecutor
from analysis.card.abilities.registry import init_all, spell_classes, available_spells
from analysis.card.abilities.loader_v2 import AbilityLoader, get_loader_v2

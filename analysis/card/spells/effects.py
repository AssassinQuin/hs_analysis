"""spells/effects.py — 全部"一次性效果"Spell 实现。

包括: Damage, Heal, Destroy, Draw, Armor, Mana, Discard,
      Summon, Buff, Enchant, Transform, Copy, Return,
      Silence, Freeze, Give, Discover, Shuffle, WeaponEquip,
      TakeControl, Armor, Mana, NoOp
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List

from analysis.card.spells import Spell, register_spell
from analysis.card.target.selector import resolve_target
from analysis.card.target.filter import apply_filter
from analysis.card.value.providers import resolve_value

if TYPE_CHECKING:
    from analysis.card.abilities.model import SpellDesc
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 基础执行器工具
# ═══════════════════════════════════════════════════════════════

def _get_targets(desc: "SpellDesc", state, source, target) -> List[Any]:
    """统一的 target 解析 + filter 应用。"""
    targets = resolve_target(desc.target, state, source, target)
    if desc.filter:
        targets = apply_filter(targets, desc.filter, source)
    return targets


def _get_hp(entity) -> int:
    return getattr(entity, 'hp', None) or getattr(entity, 'health', 0)


def _set_hp(entity, value: int):
    if hasattr(entity, 'hp'):
        entity.hp = value
    elif hasattr(entity, 'health'):
        entity.health = value


def _get_max_hp(entity) -> int:
    return getattr(entity, 'max_hp', None) or getattr(entity, 'max_health', 0)


# ═══════════════════════════════════════════════════════════════
# NoOp
# ═══════════════════════════════════════════════════════════════

@register_spell
class NoOpSpell(Spell):
    """空操作 — 用于未知类名的 fallback。"""
    def execute(self, desc, state, source=None, target=None):
        return state


# ═══════════════════════════════════════════════════════════════
# Damage
# ═══════════════════════════════════════════════════════════════

@register_spell
class DamageSpell(Spell):
    """造成伤害。支持 spell damage 加成。"""
    def execute(self, desc, state, source=None, target=None):
        amount = resolve_value(desc.value, state, source)
        targets = _get_targets(desc, state, source, target)

        from analysis.card.engine.executor import damage
        for t in targets:
            state = damage(state, amount, t)
        return state


@register_spell
class DestroySpell(Spell):
    """摧毁随从。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import destroy_minion
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = destroy_minion(state, t)
        return state


@register_spell
class PoisonsSpell(Spell):
    """剧毒Spell — 对目标造成等额当前生命值的伤害。"""
    def execute(self, desc, state, source=None, target=None):
        targets = _get_targets(desc, state, source, target)
        from analysis.card.engine.executor import damage
        for t in targets:
            hp = _get_hp(t)
            state = damage(state, hp, t)
        return state


# ═══════════════════════════════════════════════════════════════
# Heal
# ═══════════════════════════════════════════════════════════════

@register_spell
class HealSpell(Spell):
    """治疗目标。"""
    def execute(self, desc, state, source=None, target=None):
        amount = resolve_value(desc.value, state, source)
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            cur = _get_hp(t)
            max_hp = _get_max_hp(t)
            new_hp = min(max_hp, cur + amount)
            _set_hp(t, new_hp)
        return state


# ═══════════════════════════════════════════════════════════════
# Draw
# ═══════════════════════════════════════════════════════════════

@register_spell
class DrawSpell(Spell):
    """抽牌。"""
    def execute(self, desc, state, source=None, target=None):
        count = resolve_value(desc.count if desc.count is not None
                              else desc.value, state, source)
        if count <= 0:
            count = 1
        from analysis.card.engine.executor import draw_cards
        return draw_cards(state, count)


# ═══════════════════════════════════════════════════════════════
# Armor
# ═══════════════════════════════════════════════════════════════

@register_spell
class ArmorSpell(Spell):
    """获得护甲。"""
    def execute(self, desc, state, source=None, target=None):
        amount = resolve_value(desc.value, state, source)
        state.hero.armor += amount
        return state


# ═══════════════════════════════════════════════════════════════
# Mana
# ═══════════════════════════════════════════════════════════════

@register_spell
class ManaSpell(Spell):
    """获得/锁定法力水晶 / 减费效果。"""
    def execute(self, desc, state, source=None, target=None):
        amount = resolve_value(desc.value, state, source)
        # 过载
        if desc.target == "OVERLOAD":
            state.mana.overload_next += amount
        # 减费效果：添加修饰器而非直接修改可用法力
        elif desc.target in ("NEXT_COMBO_CARD", "NEXT_SPELL", "NEXT_MINION") and amount < 0:
            state.mana.add_modifier("cost_reduction", abs(amount), desc.target.lower())
        else:
            state.mana.available += amount
        return state


# ═══════════════════════════════════════════════════════════════
# Discard
# ═══════════════════════════════════════════════════════════════

@register_spell
class DiscardSpell(Spell):
    """随机弃牌。"""
    def execute(self, desc, state, source=None, target=None):
        count = resolve_value(desc.count if desc.count is not None
                              else desc.value, state, source)
        from analysis.card.engine.executor import discard_cards
        return discard_cards(state, count)


# ═══════════════════════════════════════════════════════════════
# Summon
# ═══════════════════════════════════════════════════════════════

@register_spell
class SummonSpell(Spell):
    """召唤随从到场上。"""
    def execute(self, desc, state, source=None, target=None):
        card_id = desc.card_id or ""
        position = getattr(desc, 'position', -1)
        from analysis.card.engine.executor import summon_minion_by_id
        return summon_minion_by_id(state, card_id, position=position)


@register_spell
class SummonCopySpell(Spell):
    """复制并召唤目标随从的复制。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import copy_minion
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = copy_minion(state, t)
        return state


# ═══════════════════════════════════════════════════════════════
# Buff
# ═══════════════════════════════════════════════════════════════

@register_spell
class BuffSpell(Spell):
    """增益随从（+攻击/+生命）。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import buff_minion
        atk = resolve_value(desc.attack_bonus or 0, state, source)
        hp = resolve_value(desc.health_bonus or 0, state, source)
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = buff_minion(state, t, atk, hp)
        return state


@register_spell
class EnchantSpell(Spell):
    """附魔 — 带持续时间的属性修改。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import buff_minion
        atk = resolve_value(desc.attack_bonus or 0, state, source)
        hp = resolve_value(desc.health_bonus or 0, state, source)
        duration = resolve_value(desc.duration or 0, state, source)
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = buff_minion(state, t, atk, hp)
            if duration > 0 and hasattr(t, "enchantments"):
                t.enchantments.append({
                    "attack": atk, "health": hp,
                    "duration": duration, "turns_left": duration,
                })
        return state


@register_spell
class AddKeywordSpell(Spell):
    """给予关键词/标签。从 GiveSpell 改名。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.tags import (GameTag, set_tag, has_tag)
        tag_map = {
            "TAUNT": GameTag.TAUNT, "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
            "STEALTH": GameTag.STEALTH, "WINDFURY": GameTag.WINDFURY,
            "CHARGE": GameTag.CHARGE, "RUSH": GameTag.RUSH,
            "LIFESTEAL": GameTag.LIFESTEAL, "POISONOUS": GameTag.POISONOUS,
            "REBORN": GameTag.REBORN, "IMMUNE": GameTag.IMMUNE,
            "SPELL_BURST": GameTag.SPELL_BURST, "FRENZY": GameTag.FRENZY,
            "MAGNETIC": GameTag.MAGNETIC, "ELUSIVE": GameTag.ELUSIVE,
            "WARD": GameTag.WARD,
        }
        keyword = (desc.keyword or "").upper()
        tag = tag_map.get(keyword)
        if tag:
            targets = _get_targets(desc, state, source, target)
            for t in targets:
                set_tag(getattr(t, 'tags', {}), tag, 1)
        return state


@register_spell
class RemoveKeywordSpell(Spell):
    """移除关键词。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.tags import (GameTag, set_tag)
        tag_map = {
            "TAUNT": GameTag.TAUNT, "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
            "STEALTH": GameTag.STEALTH, "POISONOUS": GameTag.POISONOUS,
            "REBORN": GameTag.REBORN,
        }
        keyword = (desc.keyword or "").upper()
        tag = tag_map.get(keyword)
        if tag:
            targets = _get_targets(desc, state, source, target)
            for t in targets:
                set_tag(getattr(t, 'tags', {}), tag, 0)
        return state


# ═══════════════════════════════════════════════════════════════
# Transform / Copy / Return
# ═══════════════════════════════════════════════════════════════

@register_spell
class TransformSpell(Spell):
    """变形随从为另一张卡。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import transform_minion
        card_id = desc.card_id or ""
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = transform_minion(state, t, card_id)
        return state


@register_spell
class CopySpell(Spell):
    """复制（到手牌/场上）。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import copy_minion
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = copy_minion(state, t)
        return state


@register_spell
class ReturnSpell(Spell):
    """将随从返回手牌。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import return_to_hand
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = return_to_hand(state, t)
        return state


# ═══════════════════════════════════════════════════════════════
# Silence / Freeze
# ═══════════════════════════════════════════════════════════════

@register_spell
class SilenceSpell(Spell):
    """沉默随从。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import silence_minion
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = silence_minion(state, t)
        return state


@register_spell
class FreezeSpell(Spell):
    """冻结目标。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import freeze_entity
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = freeze_entity(state, t)
        return state


# ═══════════════════════════════════════════════════════════════
# Control
# ═══════════════════════════════════════════════════════════════

@register_spell
class TakeControlSpell(Spell):
    """获得随从控制权。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import take_control
        targets = _get_targets(desc, state, source, target)
        for t in targets:
            state = take_control(state, t)
        return state


# ═══════════════════════════════════════════════════════════════
# Discover
# ═══════════════════════════════════════════════════════════════

@register_spell
class DiscoverSpell(Spell):
    """发现机制。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import discover
        pool = desc.pool or ""
        count = desc.count or 3
        return discover(state, pool=pool, count=count)


# ═══════════════════════════════════════════════════════════════
# AddToHand — 置入手牌
# ═══════════════════════════════════════════════════════════════

@register_spell
class AddToHandSpell(Spell):
    """将 card_id 卡牌置入手牌（若手牌未满）。"""
    def execute(self, desc, state, source=None, target=None):
        card_id = desc.card_id or ""
        if not card_id:
            return state
        from analysis.card.data.card_data import get_db
        db = get_db()
        card_data = db.get_card(card_id)
        if card_data and len(state.hand) < 10:
            from analysis.card.models.card import Card
            state.hand.append(Card(card_data))
        return state


# ═══════════════════════════════════════════════════════════════
# Shuffle
# ═══════════════════════════════════════════════════════════════

@register_spell
class ShuffleSpell(Spell):
    """洗入牌库。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import shuffle_into_deck
        card_id = desc.card_id or ""
        return shuffle_into_deck(state, card_id)


# ═══════════════════════════════════════════════════════════════
# WeaponEquip
# ═══════════════════════════════════════════════════════════════

@register_spell
class WeaponEquipSpell(Spell):
    """装备武器。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import equip_weapon
        return equip_weapon(state, desc.card_id or "")


# ═══════════════════════════════════════════════════════════════
# Counter / Bounce
# ═══════════════════════════════════════════════════════════════

@register_spell
class CounterSpell(Spell):
    """反制法术（奥秘专用）。"""
    def execute(self, desc, state, source=None, target=None):
        state._last_spell_countered = True
        return state

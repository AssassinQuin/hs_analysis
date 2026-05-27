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
            "WARD": GameTag.WARD, "CANT_ATTACK": GameTag.CANT_ATTACK,
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
        from analysis.card.engine.executor import discover_card
        pool = desc.pool or ""
        count = desc.count or 3
        if isinstance(pool, str):
            pool = self._resolve_pool(pool, state)
        if not pool:
            return state
        return discover_card(state, pool=pool, count=count)

    @staticmethod
    def _resolve_pool(pool_name: str, state) -> list:
        """Resolve a string pool name to a list of cards.

        Supports:
          - Card types: "SPELL", "MINION", "WEAPON"
          - Races: "BEAST", "DRAGON", "DEMON", "MECHANICAL", etc.
          - Class+type: "MAGE_SPELL", "DRUID_SPELL" → class-specific discover pool
          - School+type: "NATURE_SPELL" → spell school filter
          - Special: "DREAM", "MULTI_TYPE_MINION", "BONUS_EFFECTS"
        """
        from analysis.card.data.card_data import get_db
        db = get_db()
        pool_name_upper = pool_name.upper()

        # ── Card type pools ──
        card_type_map = {"SPELL": "SPELL", "MINION": "MINION", "WEAPON": "WEAPON"}
        if pool_name_upper in card_type_map:
            try:
                return db.discover_pool("NEUTRAL", card_type=card_type_map[pool_name_upper])[:20]
            except Exception:
                return []

        # ── Race pools ──
        race_map = {
            "BEAST": "BEAST", "UNDEAD": "UNDEAD", "DRAGON": "DRAGON",
            "DEMON": "DEMON", "MECHANICAL": "MECHANICAL", "ELEMENTAL": "ELEMENTAL",
            "MURLOC": "MURLOC", "PIRATE": "PIRATE", "TOTEM": "TOTEM",
        }
        if pool_name_upper in race_map:
            try:
                cards = db.get_pool(format="standard")
                return [c for c in cards if c.get("race", "").upper() == pool_name_upper][:20]
            except Exception:
                return []

        # ── Class + Spell type: "MAGE_SPELL", "DRUID_SPELL" ──
        if pool_name_upper.endswith("_SPELL"):
            class_part = pool_name_upper[:-6]  # strip "_SPELL"
            # Map known class prefixes
            _class_map = {
                "MAGE": "MAGE", "DRUID": "DRUID", "HUNTER": "HUNTER",
                "WARRIOR": "WARRIOR", "PALADIN": "PALADIN", "PRIEST": "PRIEST",
                "SHAMAN": "SHAMAN", "WARLOCK": "WARLOCK", "ROGUE": "ROGUE",
                "DEMON": "DEMONHUNTER", "DEATHKNIGHT": "DEATHKNIGHT",
                "NATURE": None,  # Nature is a spell school, not a class
            }
            mapped_class = _class_map.get(class_part)
            if mapped_class:
                try:
                    return db.discover_pool(mapped_class, card_type="SPELL")[:20]
                except Exception:
                    return []
            if class_part == "NATURE":
                try:
                    return db.get_pool(card_type="SPELL", school="NATURE", format="standard")[:20]
                except Exception:
                    return []

        # ── Special pools ──
        _special_pools = {
            "DREAM": ["DREAM_01", "DREAM_02", "DREAM_03", "DREAM_04", "DREAM_05"],
            "BONUS_EFFECTS": [],
        }
        if pool_name_upper in _special_pools:
            cids = _special_pools[pool_name_upper]
            if not cids:
                return []
            results = []
            for cid in cids:
                c = db.get_card(cid)
                if c:
                    results.append(c)
            return results[:20]

        return []


# ═══════════════════════════════════════════════════════════════
# AddToHand — 置入手牌
# ═══════════════════════════════════════════════════════════════

@register_spell
class AddToHandSpell(Spell):
    """将 card_id 卡牌置入手牌（若手牌未满）。

    也支持 pool 参数：当 pool 指定时，从池中随机选一张。
    池类型：DREAM, MULTI_TYPE_MINION, NATURE_SPELL 等。
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.data.card_data import get_db
        db = get_db()
        card_id = desc.card_id or ""
        pool = desc.pool or ""

        if not card_id and pool:
            candidates = self._resolve_add_pool(pool, db)
            if not candidates:
                return state
            import random
            card_data = random.choice(candidates)
        elif card_id:
            card_data = db.get_card(card_id)
        else:
            return state

        if card_data and len(state.hand) < 10:
            from analysis.card.models.card import Card
            state.hand.append(Card.from_hsdb_dict(card_data))
        return state

    @staticmethod
    def _resolve_add_pool(pool_name: str, db) -> list:
        """Resolve pool names specific to AddToHandSpell."""
        p = pool_name.upper()

        if p == "DREAM":
            cids = ["DREAM_01", "DREAM_02", "DREAM_03", "DREAM_04", "DREAM_05"]
            return [db.get_card(cid) for cid in cids if db.get_card(cid)]

        if p == "MULTI_TYPE_MINION":
            try:
                cards = db.get_pool(card_type="MINION", format="standard")
                return [c for c in cards if len(c.get("races", [])) > 1][:20]
            except Exception:
                return []

        if p == "NATURE_SPELL":
            try:
                return db.get_pool(card_type="SPELL", school="NATURE", format="standard")[:20]
            except Exception:
                return []

        return DiscoverSpell._resolve_pool(pool_name, None) if DiscoverSpell else []


@register_spell
class FillHandSpell(Spell):
    """用随机卡牌填满手牌。

    炉石效果: "用随机X牌填满你的手牌"（如唤醒、太阳之井等）。
    在 MCTS 模拟中，用占位符卡牌填充手牌至 10 张，
    因为精确的随机池对搜索树分支因子影响过大。
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.models.card import Card
        while len(state.hand) < 10:
            placeholder = Card(
                card_id="_fill_placeholder",
                name="?",
                cost=0,
                card_type="SPELL",
            )
            state.hand.append(placeholder)
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


# ═══════════════════════════════════════════════════════════════
# ImbueSpell — 英雄技能灌注
# ═══════════════════════════════════════════════════════════════

@register_spell
class ImbueSpell(Spell):
    """英雄技能灌注：增加 imbue_level 1 级。

    JSON 格式:
      {"class": "ImbueSpell"}
    或:
      {"class": "ImbueSpell", "value": 2}  # 灌注 N 级
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.value.providers import resolve_value
        amount = resolve_value(desc.value, state, source) if desc.value is not None else 1
        state.hero.imbue_level += amount
        return state


# ═══════════════════════════════════════════════════════════════
# TriggerHeroPowerSpell — 触发英雄技能
# ═══════════════════════════════════════════════════════════════

@register_spell
class TriggerHeroPowerSpell(Spell):
    """触发英雄技能（不消耗法力水晶，不需要目标，不消耗英雄攻击机会）。

    JSON 格式:
      {"class": "TriggerHeroPowerSpell"}
    """
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.simulation import _apply_hero_power
        try:
            state = _apply_hero_power(state)
        except (AttributeError, TypeError) as e:
            log.warning("TriggerHeroPowerSpell 执行失败: %s", e)
        return state


# ═══════════════════════════════════════════════════════════════
# SetHeroPowerSpell — 替换英雄技能
# ═══════════════════════════════════════════════════════════════

@register_spell
class SetHeroPowerSpell(Spell):
    """将英雄技能替换为指定卡牌。

    JSON 格式:
      {"class": "SetHeroPowerSpell", "card_id": "END_000p"}
    """
    def execute(self, desc, state, source=None, target=None):
        card_id = desc.card_id or ""
        if card_id:
            state.hero.hero_power_card_id = card_id
            state.hero.hero_power_used = False
        return state


# ═══════════════════════════════════════════════════════════════
# TempControlSpell — 临时控制（到回合结束归还）
# ═══════════════════════════════════════════════════════════════

@register_spell
class TempControlSpell(Spell):
    """夺取敌方随从控制权直到回合结束，被控制的随从不能攻击。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import take_control
        from analysis.card.engine.tags import GameTag, set_tag
        targets = _get_targets(desc, state, source, target)
        duration = getattr(desc, 'duration', 1) or 1
        for t in targets:
            state = take_control(state, t)
            set_tag(t.tags, GameTag.CANT_ATTACK, 1)
            t.enchantments.append({
                "type": "temp_control", "duration": duration,
                "turns_left": duration, "original_owner": "enemy",
            })
        return state


# ═══════════════════════════════════════════════════════════════
# HeroBuffSpell — 英雄临时攻击力增益
# ═══════════════════════════════════════════════════════════════

@register_spell
class HeroBuffSpell(Spell):
    """给予英雄临时攻击力加成（回合结束清零）。"""
    def execute(self, desc, state, source=None, target=None):
        atk = resolve_value(getattr(desc, 'attack_bonus', 0) or desc.value or 0, state, source)
        if hasattr(state.hero, 'temporary_attack'):
            state.hero.temporary_attack += atk
        return state


# ═══════════════════════════════════════════════════════════════
# SpendManaBuffSpell — 消耗所有法力值增益随从
# ═══════════════════════════════════════════════════════════════

@register_spell
class SpendManaBuffSpell(Spell):
    """消耗所有剩余法力值，每点提供 attack_bonus/health_bonus 给最近召唤的随从。"""
    def execute(self, desc, state, source=None, target=None):
        spent = state.mana.available
        if spent <= 0:
            return state
        atk_per = getattr(desc, 'attack_bonus', 1) or 1
        hp_per = getattr(desc, 'health_bonus', 1) or 1
        count = getattr(desc, 'count', 2) or 2
        state.mana.available = 0
        recent = state.board[-count:] if len(state.board) >= count else list(state.board)
        for m in recent:
            m.attack += spent * atk_per
            m.health += spent * hp_per
            m.max_health += spent * hp_per
        return state


# ═══════════════════════════════════════════════════════════════
# EscalationDrawSpell — 递增抽牌
# ═══════════════════════════════════════════════════════════════

@register_spell
class EscalationDrawSpell(Spell):
    """抽牌数随递增计数器增长。每次施放计数+1。"""
    def execute(self, desc, state, source=None, target=None):
        from analysis.card.engine.executor import draw_cards
        card_id = getattr(source, 'card_id', '') or ''
        counter = state.escalation_counters.get(card_id, 0)
        base = resolve_value(desc.value if desc.value is not None else 1, state, source)
        count = base + counter
        state = draw_cards(state, max(1, count))
        state.escalation_counters[card_id] = counter + 1
        return state


# ═══════════════════════════════════════════════════════════════
# ManaDiscountSpell — 法力费用折扣
# ═══════════════════════════════════════════════════════════════

@register_spell
class ManaDiscountSpell(Spell):
    """下张法术/随从费用减少。利用 ManaState.modifiers 系统。"""
    def execute(self, desc, state, source=None, target=None):
        value = getattr(desc, 'value', 0) or 0
        scope = getattr(desc, 'scope', 'next_spell') or 'next_spell'
        if value != 0:
            state.mana.add_modifier("discount", abs(value), scope)
        return state


# ═══════════════════════════════════════════════════════════════
# CorpseSpendSpell — 尸体消耗
# ═══════════════════════════════════════════════════════════════

@register_spell
class CorpseSpendSpell(Spell):
    """消耗 N 份残骸。DK 机制。"""
    def execute(self, desc, state, source=None, target=None):
        cost = getattr(desc, 'value', 0) or getattr(desc, 'count', 0) or 0
        if state.corpses >= cost:
            state.corpses -= cost
        else:
            state.corpses = 0
        return state

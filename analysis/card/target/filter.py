"""target/filter.py — 目标过滤器系统。

用在 SpellDesc.filter 字段中，对已解析的目标列表做二次过滤。
支持种族、属性、血量等条件的组合。

JSON 格式:
  {"race": "DRAGON", "attr": "DIVINE_SHIELD", "min_health": 2}
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

if TYPE_CHECKING:
    from analysis.card.engine.state import Minion


def apply_filter(
    targets: List[Any],
    filter_desc: Dict,
    source: Any = None,
) -> List[Any]:
    """对目标列表应用过滤条件。

    多个条件之间是 AND 关系。
    """
    if not filter_desc or not targets:
        return targets

    result = list(targets)

    # 种族过滤
    race = filter_desc.get("race")
    if race:
        result = [t for t in result if getattr(t, 'race', '').upper() == race.upper()]

    # 属性/关键词过滤
    attr = filter_desc.get("attr") or filter_desc.get("keyword")
    if attr:
        from analysis.card.engine.tags import GameTag, has_tag
        tag_map = {
            "TAUNT": GameTag.TAUNT, "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
            "STEALTH": GameTag.STEALTH, "WINDFURY": GameTag.WINDFURY,
            "RUSH": GameTag.RUSH, "CHARGE": GameTag.CHARGE,
            "LIFESTEAL": GameTag.LIFESTEAL, "POISONOUS": GameTag.POISONOUS,
            "REBORN": GameTag.REBORN, "IMMUNE": GameTag.IMMUNE,
            "SPELL_BURST": GameTag.SPELL_BURST, "FRENZY": GameTag.FRENZY,
            "MAGNETIC": GameTag.MAGNETIC,
        }
        tag = tag_map.get(attr.upper())
        if tag is not None:
            result = [t for t in result if has_tag(getattr(t, 'tags', {}), tag)]
        else:
            # fallback: 检查属性
            result = [t for t in result if getattr(t, attr.lower(), False)]

    # 最小生命值
    min_h = filter_desc.get("min_health")
    if min_h is not None:
        result = [t for t in result if _get_hp(t) >= min_h]

    # 最大生命值
    max_h = filter_desc.get("max_health")
    if max_h is not None:
        result = [t for t in result if _get_hp(t) <= max_h]

    # 最小攻击力
    min_a = filter_desc.get("min_attack")
    if min_a is not None:
        result = [t for t in result if getattr(t, 'attack', 0) >= min_a]

    # NOT 条件
    not_attr = filter_desc.get("not_attr")
    if not_attr:
        from analysis.card.engine.tags import GameTag, has_tag
        tag_map = {
            "TAUNT": GameTag.TAUNT, "DIVINE_SHIELD": GameTag.DIVINE_SHIELD,
            "STEALTH": GameTag.STEALTH,
        }
        tag = tag_map.get(not_attr.upper())
        if tag is not None:
            result = [t for t in result if not has_tag(getattr(t, 'tags', {}), tag)]

    return result


def _get_hp(entity) -> int:
    """统一获取实体当前血量（兼容 HeroState.hp 和 Minion.health）。"""
    return getattr(entity, 'hp', None) or getattr(entity, 'health', 0)

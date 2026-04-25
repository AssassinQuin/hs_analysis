"""基于费用曲线的卡组风格分类器

通过分析卡组中所有卡牌的法力值消耗分布，判断卡组的打法风格（快攻/中速/控制等）。
支持与 bayesian_opponent 的关键词分类结果配合使用，实现更准确的分类。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Tuple

log = logging.getLogger(__name__)


@dataclass
class ManaCurve:
    """费用曲线分析结果"""
    total_cost: int         # 所有卡牌费用 × 数量的总和
    card_count: int         # 卡牌总数（含重复）
    avg_cost: float         # 平均费用 = total_cost / card_count
    low_cost: int           # 低费卡数量（0-2费）
    mid_cost: int           # 中费卡数量（3-4费）
    high_cost: int          # 高费卡数量（5费以上）
    curve: List[int]        # 费用直方图，索引=法力值，上限为10


def analyze_mana_curve(cards: List[Tuple[int, int]]) -> ManaCurve:
    """从 (dbfId, count) 对分析费用曲线

    Args:
        cards: (dbfId, count) 元组列表，来自 Deck.cards

    Returns:
        ManaCurve 完整分析结果
    """
    # 延迟导入，避免循环依赖和启动开销
    from analysis.data.hsdb import get_db

    try:
        db = get_db()
    except Exception:
        log.warning("无法加载卡牌数据库，返回空费用曲线")
        return ManaCurve(
            total_cost=0, card_count=0, avg_cost=0.0,
            low_cost=0, mid_cost=0, high_cost=0,
            curve=[0] * 11,
        )

    histogram = [0] * 11  # 索引0-9对应0-9费，索引10对应10+费
    total_cost = 0
    card_count = 0
    low_cost = 0    # 0-2费
    mid_cost = 0    # 3-4费
    high_cost = 0   # 5费以上

    for dbf_id, count in cards:
        card_info = db.get_by_dbf(dbf_id)
        if card_info is None:
            # 未找到卡牌，默认费用为0
            cost = 0
            log.debug("dbfId=%s 未在数据库中找到，假定费用为0", dbf_id)
        else:
            cost = card_info.get("cost", 0)

        # 累加统计
        total_cost += cost * count
        card_count += count

        # 更新直方图
        bucket = min(cost, 10)
        histogram[bucket] += count

        # 费用区间统计
        if cost <= 2:
            low_cost += count
        elif cost <= 4:
            mid_cost += count
        else:
            high_cost += count

    avg_cost = total_cost / card_count if card_count > 0 else 0.0

    return ManaCurve(
        total_cost=total_cost,
        card_count=card_count,
        avg_cost=round(avg_cost, 2),
        low_cost=low_cost,
        mid_cost=mid_cost,
        high_cost=high_cost,
        curve=histogram,
    )


def classify_by_mana_curve(mana_curve: ManaCurve) -> str:
    """根据费用曲线分类卡组打法风格

    Args:
        mana_curve: 费用曲线分析结果

    Returns:
        'aggro' | 'tempo' | 'midrange' | 'control' | 'unknown'
    """
    n = mana_curve.card_count
    if n == 0:
        return 'unknown'

    low_pct = mana_curve.low_cost / n
    mid_pct = mana_curve.mid_cost / n
    high_pct = mana_curve.high_cost / n
    avg = mana_curve.avg_cost

    # 按优先级依次判断
    if avg <= 2.0 and low_pct >= 0.60:
        return 'aggro'
    if avg <= 2.8 and low_pct >= 0.45 and high_pct <= 0.15:
        return 'tempo'
    if avg >= 4.0 and high_pct >= 0.30:
        return 'control'
    if low_pct >= 0.35 and mid_pct >= 0.30:
        return 'midrange'

    return 'unknown'


# combo 关键词列表，用于 classify_deck 中识别组合技卡组
_COMBO_KEYWORDS = {'combo', 'otk', 'miracle', 'malygos', 'mechathun',
                   'tiva', 'togg', 'rattlegore', 'shudderwock', 'exodia'}


def classify_deck(cards: List[Tuple[int, int]], name: str = "") -> str:
    """综合分类卡组打法风格

    优先使用卡组名称中的关键词进行分类（如果可用），
    否则回退到基于费用曲线的分类。

    特殊处理：combo 类型只能通过关键词识别，费用曲线无法检测。

    Args:
        cards: (dbfId, count) 元组列表
        name: 可选的卡组名称，用于关键词覆盖

    Returns:
        'aggro' | 'tempo' | 'midrange' | 'control' | 'combo' | 'unknown'
    """
    from analysis.utils.bayesian_opponent import classify_playstyle

    # 1. 如果提供了卡组名称，优先使用关键词分类
    if name:
        name_lower = name.lower()
        # combo 只能通过关键词识别
        for kw in _COMBO_KEYWORDS:
            if kw in name_lower:
                log.debug("卡组名称 '%s' 匹配 combo 关键词 '%s'", name, kw)
                return 'combo'

        keyword_result = classify_playstyle(name)
        if keyword_result != 'unknown':
            log.debug("卡组名称 '%s' 关键词分类结果: %s", name, keyword_result)
            return keyword_result

    # 2. 回退到费用曲线分类
    curve = analyze_mana_curve(cards)
    result = classify_by_mana_curve(curve)
    log.debug("费用曲线分类结果: %s (avg=%.2f, low=%d, mid=%d, high=%d)",
              result, curve.avg_cost, curve.low_cost, curve.mid_cost, curve.high_cost)
    return result


def format_mana_curve(curve: ManaCurve) -> str:
    """将费用曲线格式化为可视化字符串

    每个费用等级用方块字符的数量表示该费用的卡牌数量。

    Example::

        "avg=2.4 | 0█ 1██ 2███ 3██ 4█ 5░ 6░ ..."

    Args:
        curve: ManaCurve 分析结果

    Returns:
        格式化的可视化字符串
    """
    if curve.card_count == 0:
        return "avg=0.0 | (empty deck)"

    # 找到最大值用于归一化
    max_count = max(curve.curve) if any(curve.curve) else 1

    # 方块字符，从少到多表示密度
    blocks = ['░', '▒', '█']

    parts = []
    for cost, count in enumerate(curve.curve):
        if count == 0:
            bar = '░'
        else:
            # 归一化：1-3用1个█，4-6用2个，7+用3个，以此类推
            proportion = count / max_count
            if proportion <= 0.33:
                bar = blocks[0]
            elif proportion <= 0.66:
                bar = blocks[1]
            else:
                bar = blocks[2]
        label = f"{cost}" if cost < 10 else "10+"
        parts.append(f"{label}{bar}")

    return f"avg={curve.avg_cost:.1f} | {' '.join(parts)}"

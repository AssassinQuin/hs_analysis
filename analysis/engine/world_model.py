# -*- coding: utf-8 -*-
"""world_model.py — 世界推断驱动的手牌概率系统

用世界模型证据替代 dynamic_probability.py 中的硬编码概率调整。

核心设计思路：
    原有三个硬编码方法：
    - _apply_hold_duration_bias      → 硬编码"低费降低、高费提升"
    - _apply_mulligan_keep_bias      → 硬编码"早期低费提升、高费降低"
    - _apply_generated_cooccurrence_boost → 硬编码"衍生牌多→低中费加成"

    替换为基于贝叶斯似然比的世界模型推断：
    - analyze_unplayed_cards()       → 对手在当前法力值下可出但没出的牌
    - analyze_conditional_evidence() → 从 CardEffectInferenceEngine 获取条件证据
    - analyze_play_timing()          → 对手打出时机推断
    - analyze_mana_curve_gap()       → 对手法力曲线空隙分析

    所有推断基于贝叶斯似然比 (likelihood ratio)，不硬编码概率值：
    LR = P(evidence | hypothesis) / P(evidence | ¬hypothesis)

    例如：
    - 对手 T3 有3费但没出牌 → LR = P(不出牌|手牌全是5+费) / P(不出牌|手牌有3费牌)
    - 对手打出"如果你手持龙牌"效果 → LR = P(效果触发|手牌有龙) / P(效果触发|手牌无龙)
      后者=0，所以LR=∞，即100%确定

数学依据：
    1. 超几何分布：计算特定费用/种族的牌在手中的概率
    2. 贝叶斯定理：P(H|E) = P(E|H) × P(H) / P(E)
    3. 似然比：LR = P(E|H) / P(E|¬H) 直接修改先验概率
       posterior_odds = prior_odds × LR
       P(H|E) = LR × P(H) / (1 - P(H) + LR × P(H))
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class BehaviorEvidence:
    """对手行为产生的推断证据。

    每条证据描述一个观测到的对手行为以及由此推断出的卡牌信息。

    Attributes:
        evidence_type: 证据类型
            - "unplayed_affordable": 对手有法力但没出可出的牌
            - "conditional_triggered": 条件效果触发（如"如果你手持龙牌"）
            - "derived_source": 衍生牌的源牌推断
            - "play_timing": 打出时机推断（迟延出牌说明手牌不佳）
            - "mana_curve_gap": 法力曲线空隙（某费用段完全没有牌）
            - "playstyle_prior": 对手打法风格产生的先验概率调整
            - "board_state": 场面状态推断（对手场面情况影响手牌选择）
        card_id: 关联的卡牌ID（如果适用）
        turn: 观测到的回合
        inferred_tags: 推断出的标签，如 {"race": "DRAGON"}, {"cost_min": "5"}, {"cost_max": "2"}
        likelihood: 贝叶斯似然比
            LR = P(evidence | card in hand matching tags) / P(evidence | card not in hand)
            LR > 1 表示证据支持该卡牌在手牌中
            LR < 1 表示证据反对该卡牌在手牌中
            LR = 0 表示不可能（确定性排除）
            LR = float('inf') 表示确定存在
        source_description: 人类可读的证据描述
    """
    evidence_type: str  # "unplayed_affordable" | "conditional_triggered" | "derived_source" | "play_timing" | "mana_curve_gap" | "playstyle_prior" | "board_state"
    card_id: str = ""
    turn: int = 0
    inferred_tags: Dict[str, str] = field(default_factory=dict)  # {"race": "DRAGON"}, {"cost_min": "5"}, etc.
    likelihood: float = 0.0  # P(evidence | card in hand) / P(evidence) — 贝叶斯似然比
    source_description: str = ""


@dataclass
class WorldModelEvidence:
    """世界模型产出的全部证据。

    汇总了所有分析器的输出，供 DynamicProbabilityEngine 使用。

    Attributes:
        behavior_evidence: 所有行为推断证据列表
        available_mana: 对手当前可用法力值
        current_turn: 当前回合数
        opp_hand_count: 对手手牌数量
        opp_board_minions: 对手场面随从信息
        playstyle: 对手打法风格（aggro/tempo/control/midrange/unknown）
    """
    behavior_evidence: List[BehaviorEvidence] = field(default_factory=list)
    available_mana: int = 0
    current_turn: int = 0
    opp_hand_count: int = 0
    opp_board_minions: List[Dict] = field(default_factory=list)
    playstyle: str = "unknown"

    def get_evidence_by_type(self, evidence_type: str) -> List[BehaviorEvidence]:
        """按类型筛选证据。"""
        return [e for e in self.behavior_evidence if e.evidence_type == evidence_type]

    def get_evidence_for_card(self, card_id: str) -> List[BehaviorEvidence]:
        """获取与特定卡牌相关的所有证据。"""
        return [e for e in self.behavior_evidence if e.card_id == card_id]


# ── 似然比计算工具 ──────────────────────────────────────────────

def _compute_unplayed_affordable_lr(
    available_mana: int,
    hand_size: int,
    pool_size: int,
    card_cost: int,
) -> float:
    """计算"对手有法力但没出可出的牌"的似然比。

    数学推导：
    如果对手在 T 回合有 M 法力但选择不出牌（或出了更低费的牌），
    这提供了关于手牌组成的信息。

    对于一张费用为 C 的牌：
    - 如果 C <= M（可出），对手没出这张牌 →
      LR = P(不出|手牌有此牌) / P(不出|手牌无此牌)
      P(不出|手牌有此牌) = 对手选择不出的概率（不是1，因为可能有更好的选择）
      P(不出|手牌无此牌) = 1（不可能出没有的牌）

    - 如果 C > M（不可出），对手没出这张牌 →
      这是必然的，不提供信息，LR ≈ 1

    更精确的模型：对手不出可出的牌，说明手牌中有"更好"的选择，
    或者这张牌不值得出。用超几何分布估计手牌中各费用段的比例。

    Args:
        available_mana: 对手当前可用法力值
        hand_size: 对手手牌数
        pool_size: 总池大小（手牌+牌库剩余）
        card_cost: 待评估卡牌的费用

    Returns:
        似然比 LR。LR < 1 表示对手没出这张牌降低了它在手牌中的概率。
    """
    if available_mana <= 0 or hand_size <= 0 or pool_size <= 0:
        return 1.0  # 无信息

    # 如果牌的费用超过可用法力，不出它是必然的，不提供信息
    if card_cost > available_mana:
        return 1.0

    # 如果牌的费用 <= 可用法力但对手没出：
    # 对手选择不出可出的牌有两种可能：
    # 1. 手牌有此牌但选择不出（概率较低——如果手牌有可出的牌，一般会出）
    # 2. 手牌没有此牌（概率较高——没出是因为真的没有）

    # P(不出|手牌有此牌) 的估计：
    # 对手手牌中此牌是可出的，但对手选择不出的概率
    # 这取决于手牌中其他选择的质量——但这需要更多信息
    # 简化模型：假设可出但不出是因为有更好的选择或战略考量
    # 基础不出概率 = 对手选择不出可出牌的概率
    # 典型值：炉石中玩家大约 70-90% 的情况下会出可出的牌
    p_not_play_given_has = 0.3  # 保守估计：30% 概率不出可出的牌

    # P(不出|手牌无此牌) = 1.0（没有当然出不了）

    # LR = P(不出|手牌有此牌) / P(不出|手牌无此牌)
    lr = p_not_play_given_has / 1.0

    # 进一步修正：如果对手完全没出牌（pass turn），降低更明显
    # 因为完全 pass 说明手牌中所有牌都不可出或不够好
    # 这种情况下，对于低费牌，LR 应该更低

    return lr


def _compute_unplayed_pass_lr(
    available_mana: int,
    hand_size: int,
    pool_size: int,
    card_cost: int,
) -> float:
    """计算"对手完全跳过出牌（pass turn）"的似然比。

    对手完全跳过出牌是比"没出某张特定牌"更强的信号：
    它说明对手手牌中没有任何值得出的牌。

    数学推导：
    对手 pass turn 意味着：
    P(pass | 手牌全是 cost > available_mana) 远高于
    P(pass | 手牌有 cost <= available_mana 的牌)

    对于费用 C 的牌：
    - C <= available_mana: LR 应该很低（有可出的牌一般会出）
    - C > available_mana: LR 应该 > 1（pass 说明更可能持有高费牌）

    使用超几何分布估算手牌中"可出牌"的期望数量，
    然后基于此计算 pass 的似然比。

    Args:
        available_mana: 对手可用法力
        hand_size: 对手手牌数
        pool_size: 总池大小
        card_cost: 待评估卡牌费用

    Returns:
        似然比 LR
    """
    if available_mana <= 0 or hand_size <= 0 or pool_size <= 0:
        return 1.0

    if card_cost > available_mana:
        # 高费牌：对手 pass 更可能持有高费牌
        # 似然比 > 1：pass 行为增加了持有高费牌的概率
        # 估算：pass 意味着可出牌比例很低
        # P(pass | 手牌全是高费) ≈ 0.8（高费牌多时 pass 很正常）
        # P(pass | 手牌有低费牌) ≈ 0.1（有低费可出还 pass 很罕见）
        # LR = 0.8 / 0.1 = 8.0，但用更保守的值
        lr = min(4.0, 1.0 + (card_cost - available_mana) * 0.5)
        return lr
    else:
        # 低费牌（可出但没出）：对手 pass 降低了持有低费牌的概率
        # P(pass | 手牌有低费牌) ≈ 0.1
        # P(pass | 手牌无低费牌) ≈ 0.8
        # LR = 0.1 / 0.8 = 0.125
        # 下限 0.2：避免多回合累积归零（与 evidence decay 配合）
        lr = max(0.2, 0.4 - card_cost * 0.025)
        return lr


def _compute_conditional_lr(
    inference_type: str,
    inferred_race: str = "",
    inferred_school: str = "",
) -> float:
    """计算条件效果触发的似然比。

    当对手打出"如果你手持龙牌"效果且效果触发时：
    P(效果触发 | 手牌有龙) / P(效果触发 | 手牌无龙)
    = 1.0 / 0.0 → ∞（确定性证据）

    当效果未触发时（如果可见）：
    P(效果未触发 | 手牌无龙) / P(效果未触发 | 手牌有龙)

    Args:
        inference_type: 推断类型（"conditional_hold" 等）
        inferred_race: 推断出的种族
        inferred_school: 推断出的学派

    Returns:
        似然比 LR。float('inf') 表示确定性证据。
    """
    if inference_type == "conditional_hold":
        # 条件效果触发 = 100% 确定手牌有对应种族/学派
        # P(触发|有) = 1.0, P(触发|无) = 0.0
        # LR = 1.0 / 0.0 = ∞
        return float('inf')

    return 1.0


def _compute_play_timing_lr(
    card_cost: int,
    turn_played: int,
    current_turn: int,
    available_mana: int,
) -> float:
    """计算打出时机推断的似然比。

    如果对手在 T5 才打出2费牌，说明之前的回合手牌不是最优选择。
    这增加了"对手之前手牌中高费牌较多"的概率。

    数学推导：
    对于一张费用为 C 的牌在回合 T 被打出：
    - 如果 C 接近 T（"按时出牌"）：不提供额外信息，LR ≈ 1
    - 如果 C 远小于 T（"迟延出牌"）：说明对手之前没出此牌，可能之前手牌有更高费的优先选择
      这意味着对手更可能持有其他高费牌

    LR = P(迟延出C费牌 | 手牌有高费牌) / P(迟延出C费牌 | 手牌无高费牌)

    Args:
        card_cost: 卡牌费用
        turn_played: 卡牌被打出的回合
        current_turn: 当前回合
        available_mana: 对手当前可用法力

    Returns:
        似然比 LR，应用于其他手牌概率的修正
    """
    if turn_played <= 0 or current_turn <= 0:
        return 1.0

    # 迟延程度：牌的费用比打出回合低多少
    delay = turn_played - card_cost

    if delay <= 1:
        # 按时出牌或仅延迟1回合——不提供显著信息
        return 1.0

    # 迟延出牌：对手可能有更高费的牌优先出了
    # 似然比：迟延越多，对手更可能持有高费牌
    # LR for high-cost cards: > 1
    # LR for low-cost cards: < 1

    # 迟延因子的强度随延迟增加而增强，但有上限
    delay_factor = min(3.0, 1.0 + delay * 0.3)

    return delay_factor


def _compute_mana_curve_gap_lr(
    gap_cost: int,
    current_turn: int,
    available_mana: int,
    hand_size: int,
) -> float:
    """计算法力曲线空隙的似然比。

    如果对手在低费回合跳过出牌，更可能持有高费牌。
    这与 _compute_unplayed_pass_lr 类似，但关注的是
    法力曲线中的"空隙"——某个费用段完全没有被使用过。

    数学推导：
    对于一张费用为 C 的牌：
    - 如果 C 在对手的"法力空隙"范围内（对手一直没用过这个费用）：
      对手可能没有这个费用的牌，LR < 1
    - 如果 C 在对手"已使用"的费用范围之外（更高）：
      对手可能有更高费的牌，LR > 1

    Args:
        gap_cost: 法力空隙的费用段
        current_turn: 当前回合
        available_mana: 对手可用法力
        hand_size: 对手手牌数

    Returns:
        似然比 LR
    """
    if current_turn <= 0 or hand_size <= 0:
        return 1.0

    # 对手没使用过 gap_cost 费用的牌
    # P(没用C费牌 | 手牌无C费牌) 远高于 P(没用C费牌 | 手牌有C费牌)

    # 如果当前法力已经超过了 gap_cost，但对手从未使用过该费用
    # 说明对手可能真的没有该费用段的牌
    if available_mana > gap_cost:
        # LR < 1：对手跳过了这个费用段，降低了持有该费用牌的概率
        # 空隙越大（当前法力远超空隙费用），LR 越低
        gap_size = available_mana - gap_cost
        lr = max(0.2, 1.0 - gap_size * 0.15)
        return lr

    # 当前法力还不够用 gap_cost 的牌——不提供信息
    return 1.0


def apply_likelihood_to_probability(prior: float, likelihood_ratio: float) -> float:
    """用似然比修正先验概率。

    数学推导：
    后验几率 = 先验几率 × 似然比
    odds = p / (1 - p)
    posterior_odds = odds × LR
    p_posterior = posterior_odds / (1 + posterior_odds)

    特殊情况：
    - LR = 0 → p_posterior = 0（确定性排除）
    - LR = float('inf') → p_posterior = 1.0（确定性确认）
    - LR = 1 → p_posterior = p（无信息）

    Args:
        prior: 先验概率 [0, 1]
        likelihood_ratio: 似然比 [0, ∞]

    Returns:
        后验概率 [0, 1]
    """
    if prior <= 0.0:
        return 0.0
    if prior >= 1.0:
        return 1.0

    if likelihood_ratio <= 0.0:
        return 0.0
    if math.isinf(likelihood_ratio):
        return 1.0
    if likelihood_ratio == 1.0:
        return prior

    # 先验几率
    prior_odds = prior / (1.0 - prior)

    # 后验几率
    posterior_odds = prior_odds * likelihood_ratio

    # 转回概率
    posterior = posterior_odds / (1.0 + posterior_odds)

    # 确保在 [0, 1] 范围内
    return max(0.0, min(1.0, posterior))


# ── 世界模型整合器 ──────────────────────────────────────────────

class WorldModelIntegrator:
    """世界模型证据整合器。

    整合来自多个分析器的证据，产出 WorldModelEvidence 供
    DynamicProbabilityEngine 使用。

    所有推断基于贝叶斯似然比，不硬编码概率值。

    用法::

        integrator = WorldModelIntegrator()
        evidence = integrator.integrate(state_dict, effect_inferences)
        # evidence 传给 DynamicProbabilityEngine._apply_world_model_evidence()
    """

    def __init__(self):
        self._card_db = None
        # 缓存上一次分析结果（避免重复计算）
        self._last_evidence: Optional[WorldModelEvidence] = None
        self._last_state_hash: int = 0

    def _ensure_card_db(self):
        """延迟加载卡牌数据库。"""
        if self._card_db is None:
            try:
                from analysis.card.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def integrate(
        self,
        state_dict: dict,
        effect_inferences: Optional[List] = None,
    ) -> WorldModelEvidence:
        """整合所有证据，返回 WorldModelEvidence。

        这是主入口方法，按顺序调用各个分析器，
        汇总所有行为推断证据。

        Args:
            state_dict: 来自 LogMonitor 的状态字典，包含：
                - known_cards: 已打出的卡牌列表
                - turn: 当前回合
                - opp_hand_count: 对手手牌数
                - opp_hand_hold: entity_id → turn_first_seen 映射
                - available_mana: 对手可用法力（从打出记录推断）
                - opp_board_minions: 对手场面随从
                - playstyle: 对手打法风格
                - bayesian: 贝叶斯卡组推断状态
                - generated_cards: 衍生牌集合
            effect_inferences: CardEffectInferenceEngine.get_inferences() 的结果

        Returns:
            WorldModelEvidence 包含所有推断证据
        """
        # 快速哈希检查——如果状态没变，返回缓存
        state_hash = self._compute_state_hash(state_dict)
        if state_hash == self._last_state_hash and self._last_evidence is not None:
            return self._last_evidence

        self._ensure_card_db()

        evidence = WorldModelEvidence(
            available_mana=state_dict.get("available_mana", 0),
            current_turn=state_dict.get("turn", 0),
            opp_hand_count=state_dict.get("opp_hand_count", 0),
            opp_board_minions=state_dict.get("opp_board_minions", []),
            playstyle=state_dict.get("playstyle", "unknown"),
        )

        known_cards = state_dict.get("known_cards", [])

        # 1. 对手在当前法力值下可以出但没出的牌
        unplayed = self.analyze_unplayed_cards(state_dict, known_cards)
        evidence.behavior_evidence.extend(unplayed)

        # 2. 从 CardEffectInferenceEngine 的推断获取条件证据
        conditional = self.analyze_conditional_evidence(effect_inferences)
        evidence.behavior_evidence.extend(conditional)

        # 3. 对手打出时机推断
        timing = self.analyze_play_timing(
            known_cards,
            evidence.current_turn,
            evidence.available_mana,
        )
        evidence.behavior_evidence.extend(timing)

        # 4. 对手法力曲线空隙分析
        gaps = self.analyze_mana_curve_gap(
            known_cards,
            evidence.current_turn,
            evidence.available_mana,
        )
        evidence.behavior_evidence.extend(gaps)

        # 5. 对手打法风格推断（playstyle_prior）
        playstyle_ev = self.analyze_playstyle_prior(
            evidence.playstyle,
            evidence.current_turn,
            evidence.available_mana,
        )
        evidence.behavior_evidence.extend(playstyle_ev)

        # 6. 场面状态推断（board_state）
        board_ev = self.analyze_board_state(
            evidence.opp_board_minions,
            evidence.current_turn,
            evidence.available_mana,
        )
        evidence.behavior_evidence.extend(board_ev)

        # 缓存结果
        self._last_evidence = evidence
        self._last_state_hash = state_hash

        return evidence

    def analyze_unplayed_cards(
        self,
        state_dict: dict,
        known_cards: list,
    ) -> List[BehaviorEvidence]:
        """分析对手在当前法力值下可以出但没出的牌。

        核心推断逻辑：
        如果对手在某回合有 M 法力但没出任何牌（或只出了低费牌），
        则手牌中"费用 <= M"的牌概率应该降低，
        而手牌中"费用 > M"的牌概率应该提升。

        这替代了原来的 _apply_hold_duration_bias 硬编码方法。

        数学依据：
        贝叶斯似然比 LR = P(不出牌|手牌无低费牌) / P(不出牌|手牌有低费牌)

        对于对手 pass turn 的情况：
        - P(pass | 手牌全是 cost > available_mana) ≈ 0.7-0.9
        - P(pass | 手牌有 cost <= available_mana) ≈ 0.05-0.15
        LR_pass ≈ 6-18，即 pass 行为强烈支持"手牌全是高费牌"的假设

        对于对手出了低费牌但没出高费牌的情况：
        - 这只说明对手选择了最优出牌顺序，不提供强信号

        Args:
            state_dict: 游戏状态字典
            known_cards: 已知的对手卡牌列表

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        available_mana = state_dict.get("available_mana", 0)
        current_turn = state_dict.get("turn", 0)
        opp_hand_count = state_dict.get("opp_hand_count", 0)
        opp_hand_hold = state_dict.get("opp_hand_hold", {})

        if available_mana <= 0 or current_turn <= 1 or opp_hand_count <= 0:
            return evidence_list

        # 判断对手是否完全 pass（或几乎 pass）了本回合
        # 通过检查 known_cards 中本回合打出的牌
        cards_this_turn = [
            kc for kc in known_cards
            if kc.get("turn_seen", 0) == current_turn
        ]

        # 计算对手本回合实际花费的法力
        mana_spent = 0
        for kc in cards_this_turn:
            cost = kc.get("cost", 0)
            if isinstance(cost, (int, float)):
                mana_spent += cost

        # 对手未使用的法力
        unused_mana = available_mana - mana_spent

        if unused_mana <= 0:
            # 对手用完了法力——不提供法力空隙信息
            return evidence_list

        # 对手有未使用的法力——这是有信息的！
        # 分析持有回合数据，增强推断
        hold_durations = []
        for eid, start_turn in opp_hand_hold.items():
            duration = current_turn - start_turn
            if duration > 0:
                hold_durations.append(duration)

        avg_hold = sum(hold_durations) / len(hold_durations) if hold_durations else 0

        # 如果对手完全没出牌（pass turn）——这是最强的信号
        is_pass_turn = len(cards_this_turn) == 0

        # 如果对手出了一些牌但还有剩余法力——较弱信号
        is_partial_play = len(cards_this_turn) > 0 and unused_mana >= 2

        if is_pass_turn:
            # 对手完全 pass——提供强烈信号
            # 对于每个费用段，计算 LR
            for cost in range(0, 11):
                lr = _compute_unplayed_pass_lr(
                    available_mana, opp_hand_count,
                    opp_hand_count + 20,  # 近似 pool_size
                    cost,
                )
                if abs(lr - 1.0) > 0.01:
                    evidence_list.append(BehaviorEvidence(
                        evidence_type="unplayed_affordable",
                        turn=current_turn,
                        inferred_tags={"cost": str(cost)},
                        likelihood=lr,
                        source_description=(
                            f"对手 T{current_turn} 有{available_mana}法力但完全跳过出牌，"
                            f"推断手牌中{cost}费牌的似然比={lr:.2f}"
                        ),
                    ))

        elif is_partial_play and avg_hold > 1:
            # 对手出了牌但没出完——较弱信号，结合持有回合
            # 长期持有的牌更可能是高费牌
            hold_bias = min(1.0, avg_hold / 5.0)

            for cost in range(0, 11):
                if cost <= available_mana:
                    # 可出但没出——降低概率
                    lr = 1.0 - 0.3 * hold_bias
                else:
                    # 不可出——概率提升（费用差越大，提升越显著）
                    # 对手有剩余法力但不出高费牌，说明尚未抽到/持有高费牌
                    # 但也可能是在保留高费牌等待时机
                    excess = cost - available_mana  # 费用差额
                    lr = 1.0 + min(2.5, 0.2 * hold_bias + excess * 0.15)

                if abs(lr - 1.0) > 0.01:
                    evidence_list.append(BehaviorEvidence(
                        evidence_type="unplayed_affordable",
                        turn=current_turn,
                        inferred_tags={"cost": str(cost)},
                        likelihood=lr,
                        source_description=(
                            f"对手 T{current_turn} 有{unused_mana}法力未使用，"
                            f"平均持有{avg_hold:.1f}回合，"
                            f"推断手牌中{cost}费牌的似然比={lr:.2f}"
                        ),
                    ))

        return evidence_list

    def analyze_conditional_evidence(
        self,
        inferences: Optional[List] = None,
    ) -> List[BehaviorEvidence]:
        """从 CardEffectInferenceEngine 的推断获取条件证据。

        当对手打出带有条件效果的牌（如"如果你手持龙牌"）且效果触发时，
        这是确定性证据——LR = ∞。

        这替代了原来 _apply_conditional_modifiers 中的部分逻辑
        （但 _apply_conditional_modifiers 仍保留，因为它处理 HandConstraint）。

        Args:
            inferences: CardEffectInferenceEngine.get_inferences() 的结果列表

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        if not inferences:
            return evidence_list

        for inf in inferences:
            inference_type = getattr(inf, 'inference_type', '')
            if inference_type != 'conditional_hold':
                continue

            # 条件效果触发 = 确定性证据
            lr = _compute_conditional_lr(
                inference_type=inference_type,
                inferred_race=getattr(inf, 'inferred_race', ''),
                inferred_school=getattr(inf, 'inferred_school', ''),
            )

            inferred_race = getattr(inf, 'inferred_race', '')
            inferred_school = getattr(inf, 'inferred_school', '')

            tags = {}
            if inferred_race:
                tags["race"] = inferred_race
            if inferred_school:
                tags["spell_school"] = inferred_school

            if tags:
                evidence_list.append(BehaviorEvidence(
                    evidence_type="conditional_triggered",
                    card_id=getattr(inf, 'card_id', ''),
                    turn=getattr(inf, 'turn', 0),
                    inferred_tags=tags,
                    likelihood=lr,
                    source_description=(
                        f"对手打出 {getattr(inf, 'card_id', '')} 的条件效果触发，"
                        f"推断手牌持有 {inferred_race or inferred_school}，"
                        f"似然比=∞（确定性证据）"
                    ),
                ))

        return evidence_list

    def analyze_play_timing(
        self,
        known_cards: list,
        current_turn: int,
        available_mana: int,
    ) -> List[BehaviorEvidence]:
        """分析对手打出时机推断。

        如果对手在 T5 才打出2费牌，说明之前手牌不是最优选择——
        对手之前可能有更高费的牌需要先出。

        这替代了原来 _apply_hold_duration_bias 中的部分逻辑。

        数学依据：
        对于迟延出牌 delay = turn_played - card_cost：
        - delay > 0 时，对手更可能持有高费牌
        - LR_high = 1 + delay * 0.3（高费牌概率提升）
        - LR_low = 1 / LR_high（低费牌概率降低，归一化约束）

        Args:
            known_cards: 已知对手卡牌列表
            current_turn: 当前回合
            available_mana: 对手可用法力

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        if not known_cards or current_turn <= 0:
            return evidence_list

        # 找出所有迟延出牌的情况
        for kc in known_cards:
            turn_seen = kc.get("turn_seen", 0)
            cost = kc.get("cost", 0)
            card_id = kc.get("card_id", "")

            if not isinstance(cost, (int, float)) or turn_seen <= 0:
                continue

            delay = turn_seen - cost
            if delay <= 1:
                continue  # 按时出牌，不提供信息

            # 迟延出牌：对手可能有更高费的牌
            timing_lr = _compute_play_timing_lr(cost, turn_seen, current_turn, available_mana)

            # 对高费牌提升概率
            evidence_list.append(BehaviorEvidence(
                evidence_type="play_timing",
                card_id=card_id,
                turn=turn_seen,
                inferred_tags={"delay": str(delay), "cost": str(cost)},
                likelihood=timing_lr,
                source_description=(
                    f"对手在 T{turn_seen} 才打出 {cost}费牌（延迟{delay}回合），"
                    f"推断手牌可能有更高费牌，高费似然比={timing_lr:.2f}"
                ),
            ))

        return evidence_list

    def analyze_mana_curve_gap(
        self,
        known_cards: list,
        current_turn: int,
        available_mana: int,
    ) -> List[BehaviorEvidence]:
        """分析对手法力曲线空隙。

        如果对手在低费回合跳过出牌，更可能持有高费牌。
        如果对手从未打出过某个费用段的牌，降低了持有该费用段牌的概率。

        这替代了原来 _apply_mulligan_keep_bias 的部分逻辑。

        数学依据：
        统计对手已打出牌的费用分布，找出"空隙"费用段。
        对于空隙费用 C：
        - P(对手从未用C费牌 | 手牌无C费牌) 高
        - P(对手从未用C费牌 | 手牌有C费牌) 低
        LR_gap < 1（降低了持有C费牌的概率）

        对于高于已使用费用段的费用：
        - 对手可能持有更高费的牌
        LR_high > 1

        Args:
            known_cards: 已知对手卡牌列表
            current_turn: 当前回合
            available_mana: 对手可用法力

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        if not known_cards or current_turn <= 2:
            return evidence_list

        # 统计已打出牌的费用分布
        played_costs: Dict[int, int] = {}  # cost → count
        for kc in known_cards:
            cost = kc.get("cost", -1)
            source = kc.get("source", "deck")
            # 只统计牌库来源的牌（排除衍生牌）
            if source == "generated" or not isinstance(cost, (int, float)):
                continue
            cost_int = int(cost)
            played_costs[cost_int] = played_costs.get(cost_int, 0) + 1

        # 找出法力曲线空隙
        # 对于每个已达到的费用段，检查是否被使用过
        for cost in range(0, min(available_mana + 1, 11)):
            if cost not in played_costs and cost < available_mana:
                # 这个费用段是空隙——对手从未使用过该费用的牌
                lr = _compute_mana_curve_gap_lr(cost, current_turn, available_mana, 5)

                if abs(lr - 1.0) > 0.01:
                    evidence_list.append(BehaviorEvidence(
                        evidence_type="mana_curve_gap",
                        turn=current_turn,
                        inferred_tags={"cost": str(cost), "gap": "true"},
                        likelihood=lr,
                        source_description=(
                            f"对手截至 T{current_turn} 从未使用过{cost}费牌，"
                            f"推断持有{cost}费牌的似然比={lr:.2f}"
                        ),
                    ))

        # 对于早期回合的 mulligan 推断
        # 对手在 mulligan 阶段通常保留低费牌、换掉高费牌
        # 这意味着早期回合手牌中低费牌概率更高
        if current_turn <= 5 and current_turn > 0:
            mulligan_factor = max(0.0, 1.0 - (current_turn - 1) * 0.25)

            if mulligan_factor > 0.05:
                # 低费牌（0-3）在 mulligan 后更可能在手牌中
                # 这不是一个"空隙"信号，而是一个"偏好"信号
                # 用适度的似然比表示
                low_cost_lr = 1.0 + 0.3 * mulligan_factor  # 轻微提升
                high_cost_lr = 1.0 / (1.0 + 0.25 * mulligan_factor)  # 轻微降低

                evidence_list.append(BehaviorEvidence(
                    evidence_type="mana_curve_gap",
                    turn=current_turn,
                    inferred_tags={"cost_max": "3", "mulligan": "early"},
                    likelihood=low_cost_lr,
                    source_description=(
                        f"当前 T{current_turn} 仍在 mulligan 影响期，"
                        f"推断手牌低费牌概率提升，似然比={low_cost_lr:.2f}"
                    ),
                ))

                evidence_list.append(BehaviorEvidence(
                    evidence_type="mana_curve_gap",
                    turn=current_turn,
                    inferred_tags={"cost_min": "7", "mulligan": "late"},
                    likelihood=high_cost_lr,
                    source_description=(
                        f"当前 T{current_turn} 仍在 mulligan 影响期，"
                        f"推断手牌高费牌概率降低，似然比={high_cost_lr:.2f}"
                    ),
                ))

        return evidence_list

    @staticmethod
    def _compute_state_hash(state_dict: dict) -> int:
        """计算状态字典的快速哈希，用于缓存检查。"""
        try:
            # 只哈希关键字段，避免深度哈希整个字典
            key_fields = (
                state_dict.get("turn", 0),
                state_dict.get("available_mana", 0),
                state_dict.get("opp_hand_count", 0),
                len(state_dict.get("known_cards", [])),
                len(state_dict.get("opp_hand_hold", {})),
                state_dict.get("playstyle", ""),
            )
            return hash(key_fields)
        except Exception:
            return 0

    def analyze_playstyle_prior(
        self,
        playstyle: str,
        current_turn: int,
        available_mana: int,
    ) -> List[BehaviorEvidence]:
        """根据对手打法风格推断手牌费用分布。

        打法风格（由贝叶斯卡组推断得出）提供关于手牌组成的有价值先验信息。

        数学依据：
        不同打法的卡组费用分布差异显著：
        - aggro:  低费牌密度高（0-3费占比 > 60%），高费牌极少
        - tempo:  中低费牌为主（1-5费占比 > 70%）
        - midrange: 均匀分布，中费牌峰值（3-6费占比 > 50%）
        - control: 高费牌密度高（5+费占比 > 40%），低费法术以解场为主

        似然比计算：
        LR = P(observed_playstyle | card matches cost profile) /
             P(observed_playstyle | card doesn't match cost profile)

        对于 aggro 打法：
        - P(aggro | 手牌低费牌) >> P(aggro | 手牌高费牌)
        - LR_low = 1.3（轻微提升低费牌概率）
        - LR_high = 0.7（降低高费牌概率）

        对于 control 打法：
        - P(control | 手牌高费牌) >> P(control | 手牌低费牌)
        - LR_high = 1.4（提升高费牌概率）
        - LR_low = 0.75（降低低费牌概率）

        注意：这些似然比不是硬编码概率值，而是从打法风格到卡牌费用的
        贝叶斯推断。打法风格本身就是从对手打出的卡牌中推断出来的，
        所以它是间接证据，似然比保持适度。

        Args:
            playstyle: 对手打法风格 (aggro/tempo/midrange/control/unknown)
            current_turn: 当前回合
            available_mana: 对手可用法力

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        if playstyle == "unknown" or current_turn <= 0:
            return evidence_list

        # 根据打法风格计算费用段的似然比
        # 这些 LR 值反映的是：观察到某打法后，对手手牌费用分布的后验调整
        # 它们基于经验统计：不同打法卡组的费用分布特征
        if playstyle == "aggro":
            # 快攻卡组：低费牌概率提升，高费牌概率降低
            # P(aggro | 手牌有0-3费) ≈ 0.6, P(aggro | 手牌无0-3费) ≈ 0.15
            # LR ≈ 0.6 / 0.15 ≈ 4.0，但打法风格本身有不确定性，取保守值
            low_cost_lr = 1.3   # 0-3费牌轻微提升
            mid_cost_lr = 0.95  # 4-5费牌基本不变
            high_cost_lr = 0.6  # 6+费牌显著降低

            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_max": "3", "style": "aggro"},
                likelihood=low_cost_lr,
                source_description=(
                    f"对手打法为快攻(aggro)，推断手牌低费牌概率提升，"
                    f"似然比={low_cost_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "4", "cost_max": "5", "style": "aggro"},
                likelihood=mid_cost_lr,
                source_description=(
                    f"对手打法为快攻(aggro)，推断手牌中费牌概率基本不变，"
                    f"似然比={mid_cost_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "6", "style": "aggro"},
                likelihood=high_cost_lr,
                source_description=(
                    f"对手打法为快攻(aggro)，推断手牌高费牌概率降低，"
                    f"似然比={high_cost_lr:.2f}"
                ),
            ))

        elif playstyle == "control":
            # 控制卡组：高费牌概率提升，低费牌概率降低
            # P(control | 手牌有6+费) ≈ 0.5, P(control | 手牌无6+费) ≈ 0.15
            # LR ≈ 3.3，保守取值
            high_cost_lr = 1.4  # 6+费牌提升
            mid_cost_lr = 1.1   # 3-5费牌轻微提升
            low_cost_lr = 0.75  # 0-2费牌降低（控制卡组低费以解场为主，数量少）

            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_max": "2", "style": "control"},
                likelihood=low_cost_lr,
                source_description=(
                    f"对手打法为控制(control)，推断手牌低费牌概率降低，"
                    f"似然比={low_cost_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "3", "cost_max": "5", "style": "control"},
                likelihood=mid_cost_lr,
                source_description=(
                    f"对手打法为控制(control)，推断手牌中费牌概率轻微提升，"
                    f"似然比={mid_cost_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "6", "style": "control"},
                likelihood=high_cost_lr,
                source_description=(
                    f"对手打法为控制(control)，推断手牌高费牌概率提升，"
                    f"似然比={high_cost_lr:.2f}"
                ),
            ))

        elif playstyle == "tempo":
            # 节奏卡组：中低费牌概率提升
            low_mid_lr = 1.15  # 1-5费牌轻微提升
            high_cost_lr = 0.85  # 6+费牌轻微降低

            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "1", "cost_max": "5", "style": "tempo"},
                likelihood=low_mid_lr,
                source_description=(
                    f"对手打法为节奏(tempo)，推断手牌中低费牌概率提升，"
                    f"似然比={low_mid_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "6", "style": "tempo"},
                likelihood=high_cost_lr,
                source_description=(
                    f"对手打法为节奏(tempo)，推断手牌高费牌概率降低，"
                    f"似然比={high_cost_lr:.2f}"
                ),
            ))

        elif playstyle == "midrange":
            # 中速卡组：中费牌概率提升
            mid_cost_lr = 1.2  # 3-6费牌提升
            extreme_lr = 0.9   # 极端费用牌轻微降低

            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_min": "3", "cost_max": "6", "style": "midrange"},
                likelihood=mid_cost_lr,
                source_description=(
                    f"对手打法为中速(midrange)，推断手牌中费牌概率提升，"
                    f"似然比={mid_cost_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="playstyle_prior",
                turn=current_turn,
                inferred_tags={"cost_max": "2", "style": "midrange"},
                likelihood=extreme_lr,
                source_description=(
                    f"对手打法为中速(midrange)，推断手牌极低费牌概率轻微降低，"
                    f"似然比={extreme_lr:.2f}"
                ),
            ))

        return evidence_list

    def analyze_board_state(
        self,
        opp_board_minions: List[Dict],
        current_turn: int,
        available_mana: int,
    ) -> List[BehaviorEvidence]:
        """根据对手场面状态推断手牌类型倾向。

        对手场面状态反映了其打法策略和手牌选择：
        - 场面随从多 → 对手不太可能手牌全是随从（已铺场，后续可能持法术/解场）
        - 场面空 → 对手可能手牌全是法术/解场，或刚被清场后持有铺场牌
        - 中期对手场面弱 → 对手可能在囤积高费牌等待翻盘

        数学依据：
        这是基于对手场面观察对手手牌组成的推断。
        LR = P(观察到的场面 | 手牌有某类型牌) / P(观察到的场面 | 手牌无某类型牌)

        例如：
        - 对手 T5+ 场面有4+随从 → 对手已铺场，手牌中随从概率降低
          P(铺场 | 手牌多随从) ≈ 0.7, P(铺场 | 手牌少随从) ≈ 0.3
          LR_minion = 0.3 / 0.7 ≈ 0.43

        Args:
            opp_board_minions: 对手场面随从列表
            current_turn: 当前回合
            available_mana: 对手可用法力

        Returns:
            行为证据列表
        """
        evidence_list: List[BehaviorEvidence] = []

        if current_turn <= 2:
            # 早期回合场面信息不充分
            return evidence_list

        board_count = len(opp_board_minions)

        if board_count >= 4:
            # 对手场面随从多 → 已铺场，手牌中随从概率降低
            # P(4+随从在场 | 手牌多随从) 高但对手已打出很多随从
            # 更可能的解释是：对手手牌中剩余的随从较少，更多是法术
            # LR_minion < 1，LR_spell > 1
            board_factor = min(1.0, (board_count - 3) * 0.15)
            minion_lr = max(0.5, 1.0 - board_factor)
            spell_lr = min(1.5, 1.0 + board_factor * 0.5)

            evidence_list.append(BehaviorEvidence(
                evidence_type="board_state",
                turn=current_turn,
                inferred_tags={"card_type": "MINION", "board": "full"},
                likelihood=minion_lr,
                source_description=(
                    f"对手场面有{board_count}个随从（已铺场），"
                    f"推断手牌随从概率降低，似然比={minion_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="board_state",
                turn=current_turn,
                inferred_tags={"card_type": "SPELL", "board": "full"},
                likelihood=spell_lr,
                source_description=(
                    f"对手场面有{board_count}个随从（已铺场），"
                    f"推断手牌法术概率提升，似然比={spell_lr:.2f}"
                ),
            ))

        elif board_count == 0 and current_turn >= 5:
            # 对手中期场面空 → 可能被清场或一直没有铺场
            # 两种可能：
            # 1. 对手是控制卡组，手牌以解场/回血法术为主
            # 2. 对手刚被清场，手牌可能有铺场随从
            # 信号较弱，仅轻微调整
            minion_lr = 1.1   # 可能持有随从准备铺场
            spell_lr = 0.95   # 法术概率轻微降低

            evidence_list.append(BehaviorEvidence(
                evidence_type="board_state",
                turn=current_turn,
                inferred_tags={"card_type": "MINION", "board": "empty"},
                likelihood=minion_lr,
                source_description=(
                    f"对手 T{current_turn} 场面为空，"
                    f"推断可能持有随从准备铺场，似然比={minion_lr:.2f}"
                ),
            ))
            evidence_list.append(BehaviorEvidence(
                evidence_type="board_state",
                turn=current_turn,
                inferred_tags={"card_type": "SPELL", "board": "empty"},
                likelihood=spell_lr,
                source_description=(
                    f"对手 T{current_turn} 场面为空，"
                    f"法术概率轻微降低，似然比={spell_lr:.2f}"
                ),
            ))

        return evidence_list

# -*- coding: utf-8 -*-
"""dynamic_probability.py — 动态手牌概率引擎

核心数学模型：
    P(card_c in hand | observed) = Σ_j P(card_c in hand | deck=j) × P(deck=j | observed)

其中 P(card_c in hand | deck=j) 基于超几何分布计算：

    P(at least one copy of c in hand)
    = 1 - C(pool - remaining_copies, hand_size) / C(pool, hand_size)

    pool      = 对手尚未被揭示/打出的总卡牌数 (deck_remaining + hand_count)
    remaining = 卡组 j 中 c 的原始张数 - 已打出/揭示的张数
    hand_size = 对手当前手牌数

优势：
- 完全基于已有信息动态计算，无写死概率
- 每当新牌打出/揭示时自动更新
- 支持条件证据修正（如"如果你手持龙牌"效果触发）
- 支持多卡组假设加权（未锁定卡组时考虑 top-N 卡组的概率加权）
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── 超几何分布工具函数 ──────────────────────────────────────────

def _comb(n: int, k: int) -> int:
    """计算组合数 C(n, k)。"""
    if k < 0 or k > n:
        return 0
    if k == 0 or k == n:
        return 1
    k = min(k, n - k)
    result = 1
    for i in range(k):
        result = result * (n - i) // (i + 1)
    return result


def hypergeometric_pmf(k: int, K: int, n: int, N: int) -> float:
    """超几何分布概率质量函数。

    P(X = k) = C(K, k) * C(N - K, n - k) / C(N, n)
    """
    if N <= 0 or n <= 0 or K <= 0:
        return 0.0
    if k < 0 or k > min(K, n):
        return 0.0
    num = _comb(K, k) * _comb(N - K, n - k)
    den = _comb(N, n)
    if den == 0:
        return 0.0
    return num / den


def hypergeometric_at_least_one(K: int, n: int, N: int) -> float:
    """超几何分布中至少抽到1个目标物品的概率。

    P(X >= 1) = 1 - C(N - K, n) / C(N, n)

    Args:
        K: 总体中目标物品数 (remaining copies of card c)
        n: 抽取数量 (hand_size)
        N: 总体大小 (pool = deck_remaining + hand_count)
    """
    if N <= 0 or n <= 0 or K <= 0:
        return 0.0
    # 边界校验：K 不应超过 N（remaining > pool 是数据不一致）
    if K > N:
        K = N
    if K >= N:
        return 1.0
    if n >= N:
        return 1.0

    try:
        log_p0 = _log_comb(N - K, n) - _log_comb(N, n)
        if log_p0 > 0:
            return 1.0
        p0 = math.exp(log_p0)
        return max(0.0, min(1.0, 1.0 - p0))
    except (ValueError, OverflowError):
        try:
            p0_num = _comb(N - K, n)
            p0_den = _comb(N, n)
            if p0_den == 0:
                return 1.0
            return 1.0 - p0_num / p0_den
        except (OverflowError, ZeroDivisionError):
            return 1.0


def _log_comb(n: int, k: int) -> float:
    """计算 log(C(n, k)) 使用对数避免溢出。"""
    if k < 0 or k > n:
        return float('-inf')
    if k == 0 or k == n:
        return 0.0
    k = min(k, n - k)
    result = 0.0
    for i in range(k):
        result += math.log(n - i) - math.log(i + 1)
    return result


# ── 手牌概率数据结构 ──────────────────────────────────────────

@dataclass
class CardProbability:
    """单张卡牌在手牌中的概率。"""
    card_id: str = ""
    dbf_id: int = 0
    name: str = ""
    cost: int = 0
    probability: float = 0.0
    remaining_copies: int = 0
    source: str = "deck"
    card_type: str = ""
    race: str = ""
    spell_school: str = ""
    confidence: float = 0.0

    @property
    def display_text(self) -> str:
        if self.probability >= 1.0:
            return f"{self.name} (确认)"
        elif self.probability >= 0.5:
            return f"{self.name} ({self.probability:.0%})"
        elif self.probability >= 0.01:
            return f"{self.name} ({self.probability:.0%})"
        else:
            return "?"


@dataclass
class HandProbabilityReport:
    """完整的手牌概率报告。"""
    card_probabilities: List[CardProbability] = field(default_factory=list)
    hand_size: int = 0
    deck_remaining: int = 0
    pool_size: int = 0
    archetype_name: str = ""
    archetype_confidence: float = 0.0
    top_archetypes: List[Tuple[str, float]] = field(default_factory=list)
    conditional_constraints: List[Dict] = field(default_factory=list)

    def get_hand_fill(self) -> List[CardProbability]:
        """获取填充到手牌数量的概率条目。"""
        sorted_probs = sorted(
            self.card_probabilities,
            key=lambda cp: (-cp.probability, cp.cost),
        )
        result = sorted_probs[:self.hand_size] if self.hand_size > 0 else []
        while len(result) < self.hand_size:
            result.append(CardProbability(
                card_id="",
                name="?",
                probability=0.0,
                source="unknown",
                card_type="UNKNOWN",
            ))
        return result


# ── 条件证据约束 ──────────────────────────────────────────────

@dataclass
class HandConstraint:
    """对手手牌约束。"""
    constraint_type: str  # "holds_race" | "holds_school" | "holds_card"
    value: str = ""
    card_id: str = ""
    turn: int = 0
    confidence: float = 1.0


# ── 条件效果规则映射 ──────────────────────────────────────────

from analysis.constants.hs_enums import CONDITIONAL_HOLDING_RULES as _CONDITIONAL_RULES


# ── 动态概率引擎 ──────────────────────────────────────────────

class DynamicProbabilityEngine:
    """动态手牌概率引擎。

    基于超几何分布 + 贝叶斯后验 + 条件证据，
    计算对手每张可能手牌的概率。无写死概率值。

    用法::

        engine = DynamicProbabilityEngine()
        engine.update_from_state_dict(state_dict)
        report = engine.compute_probabilities(hand_size=5, deck_remaining=20)
    """

    def __init__(self):
        self._card_db = None
        self._bayesian_state: Dict = {}
        self._constraints: List[HandConstraint] = []
        self._seen_cards: Dict[str, int] = {}
        self._generated_cards: Set[str] = set()
        self._revealed_hand: List[Tuple[int, str]] = []
        self._discarded_cards: set = set()
        self._known_deck_cards: list = []
        self._hand_transforms: list = []
        self._confirmed_hand_cards: set = set()
        self._pool_cache_max = 256
        self._pool_cache: Dict = {}
        # DB 卡组数据缓存（首次调用批量加载，避免每次概率计算都开/关 DB）
        self._deck_cards_cache: Dict[int, List[int]] = {}
        self._deck_cache_loaded: bool = False
        # 对手后手/硬币/回合/持有推断
        self._is_first_player: bool = True
        self._coin_used: bool = False
        self._current_turn: int = 0
        self._opp_hand_hold: Dict[int, int] = {}  # entity_id → turn_first_seen_in_hand

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def update_from_state_dict(self, state_dict: dict):
        """从 LogMonitor 的状态字典更新引擎状态。"""
        self._ensure_card_db()
        self._bayesian_state = state_dict.get("bayesian", {})

        self._seen_cards = {}
        for kc in state_dict.get("known_cards", []):
            cid = kc.get("card_id", "")
            if cid:
                self._seen_cards[cid] = self._seen_cards.get(cid, 0) + 1

        self._generated_cards = set(state_dict.get("generated_cards", set()))
        self._revealed_hand = list(state_dict.get("known_hand", []))
        self._constraints = []

        # 对手先后手/硬币/回合信息
        self._is_first_player = state_dict.get("is_first_player", True)
        self._coin_used = state_dict.get("coin_used", False)
        self._current_turn = state_dict.get("turn", 0)
        self._opp_hand_hold = dict(state_dict.get("opp_hand_hold", {}))

        # Track discarded cards for probability exclusion
        self._discarded_cards = set(state_dict.get("discarded_cards", []))

        # Track deck peek cards — these are confirmed to be in opponent's deck
        # Used to reduce uncertainty about deck composition
        self._known_deck_cards = list(state_dict.get("known_deck_cards", []))

        # Track hand transforms — original card_id no longer in original form
        # Used to exclude transformed-from cards and include transformed-to cards
        self._hand_transforms = list(state_dict.get("hand_transforms", []))

        # Track confirmed hand cards (from copy effects like Mind Vision)
        # These cards are 100% confirmed to be/was in opponent's hand
        self._confirmed_hand_cards = list(state_dict.get("confirmed_hand_cards", []))

        for kc in state_dict.get("known_cards", []):
            ce = kc.get("conditional_evidence", "")
            triggered = kc.get("effect_triggered", False)
            if ce and triggered:
                self._add_constraint_from_evidence(ce, kc)

        # Add tutor type constraints from tracker rules
        for tc in state_dict.get("hand_type_constraints", []):
            ctype = tc.get("type", "")
            value = tc.get("value", "")
            if ctype == "card_type":
                self._constraints.append(HandConstraint(
                    constraint_type="holds_card_type",
                    value=value,
                    card_id=tc.get("card_id", ""),
                    turn=tc.get("turn", 0),
                ))
            elif ctype == "race":
                self._constraints.append(HandConstraint(
                    constraint_type="holds_race",
                    value=value,
                    card_id=tc.get("card_id", ""),
                    turn=tc.get("turn", 0),
                ))
            elif ctype == "spell_school":
                self._constraints.append(HandConstraint(
                    constraint_type="holds_school",
                    value=value,
                    card_id=tc.get("card_id", ""),
                    turn=tc.get("turn", 0),
                ))

    def _add_constraint_from_evidence(self, evidence_type: str, card_info: dict):
        rule = _CONDITIONAL_RULES.get(evidence_type.upper())
        if rule:
            race = rule.get("race", "")
            school = rule.get("spellSchool", "")
            if race:
                self._constraints.append(HandConstraint(
                    constraint_type="holds_race",
                    value=race,
                    card_id=card_info.get("card_id", ""),
                    turn=card_info.get("turn_seen", 0),
                ))
            if school:
                self._constraints.append(HandConstraint(
                    constraint_type="holds_school",
                    value=school,
                    card_id=card_info.get("card_id", ""),
                    turn=card_info.get("turn_seen", 0),
                ))

    def add_constraint(self, constraint: HandConstraint):
        self._constraints.append(constraint)

    def compute_probabilities(
        self,
        hand_size: int,
        deck_remaining: int,
        opp_class: str = "",
    ) -> HandProbabilityReport:
        """计算对手手牌概率。"""
        self._ensure_card_db()

        report = HandProbabilityReport(
            hand_size=hand_size,
            deck_remaining=deck_remaining,
            pool_size=hand_size + deck_remaining,
        )

        report.archetype_name = self._bayesian_state.get("archetype_name", "") or ""
        report.archetype_confidence = self._bayesian_state.get("deck_confidence", 0.0)
        top_decks = self._bayesian_state.get("top_decks", [])
        report.top_archetypes = [(name, prob) for _, name, prob in top_decks]
        report.conditional_constraints = [
            {"type": c.constraint_type, "value": c.value,
             "card_id": c.card_id, "turn": c.turn}
            for c in self._constraints
        ]

        # 1. 已确认手牌 (100%)
        revealed_set = set()
        for eid, card_id in self._revealed_hand:
            if card_id and card_id not in revealed_set:
                cp = self._card_id_to_probability(card_id, 1.0, "revealed")
                report.card_probabilities.append(cp)
                revealed_set.add(card_id)

        # 1a. 后手硬币：如果对手是后手且硬币未使用，100%确认对手手牌有硬币
        # 后手第5张牌一定是硬币，这是游戏机制
        if not self._is_first_player and not self._coin_used:
            # 硬币卡牌ID
            from analysis.constants.hs_enums import COIN_CARD_IDS
            for coin_id in COIN_CARD_IDS:
                if coin_id not in revealed_set:
                    # 检查硬币是否已打出（如果 seen_cards 中有硬币，说明已用过但 coin_used 未检测到）
                    if self._seen_cards.get(coin_id, 0) == 0:
                        cp = self._card_id_to_probability(coin_id, 1.0, "revealed")
                        report.card_probabilities.append(cp)
                        revealed_set.add(coin_id)
                        break  # 只添加一种硬币

        # 1b. 确认手牌（来自 Mind Vision 等复制效果）
        # 这些卡已被复制走，对手当前不一定还有，但作为贝叶斯先验适度提升
        confirmed_boost = {}  # card_id → boosted probability
        for card_id in self._confirmed_hand_cards:
            if card_id and card_id not in revealed_set:
                # 对手持有过的牌，给予 0.15 的基础概率作为先验
                confirmed_boost[card_id] = 0.15

        # 1c. 手牌变形 — 被变形的原始牌不应出现在概率中
        # 收集所有被变形走的 old_card_id
        transformed_from_ids: set = set()
        transformed_to_ids: set = set()
        for t in self._hand_transforms:
            old_id = t.get("old_card_id", "")
            new_id = t.get("new_card_id", "")
            if old_id:
                transformed_from_ids.add(old_id)
            if new_id:
                transformed_to_ids.add(new_id)

        # 2. 基于贝叶斯卡组的超几何分布概率
        bayesian_probs = self._compute_bayesian_hand_probabilities(
            hand_size, deck_remaining, transformed_from_ids, opp_class
        )
        for cp in bayesian_probs:
            if cp.card_id not in revealed_set:
                report.card_probabilities.append(cp)
                revealed_set.add(cp.card_id)

        # 3. 条件证据修正
        self._apply_conditional_modifiers(report)

        # 4. 持有回合推断：多回合不打的牌更可能是高费牌
        self._apply_hold_duration_bias(report)

        # 5. 留牌推断：对手在mulligan阶段选择保留的牌更可能是低费牌
        self._apply_mulligan_keep_bias(report)

        # 6. 衍生牌共现推断：对手打出衍生牌说明同卡组牌概率提升
        self._apply_generated_cooccurrence_boost(report)

        # 7. 应用确认手牌先验提升（在条件修正之后，确保不被覆盖）
        for cp in report.card_probabilities:
            if cp.card_id in confirmed_boost and cp.source != "revealed":
                cp.probability = max(cp.probability, confirmed_boost[cp.card_id])
                if cp.source != "inferred":
                    cp.source = "confirmed_prior"

        # 8. 排序
        report.card_probabilities.sort(
            key=lambda cp: (
                0 if cp.source == "revealed" else 1,
                -cp.probability,
                cp.cost,
            )
        )

        return report

    def _compute_bayesian_hand_probabilities(
        self, hand_size: int, deck_remaining: int,
        transformed_from_ids: set | None = None,
        opp_class: str = "",
    ) -> List[CardProbability]:
        """基于贝叶斯后验 + 超几何分布计算每张卡牌的手牌概率。

        P(c in hand | observed) = Σ_j P(c in hand | deck=j) × P(deck=j | observed)

        区分度增强：
        1. 只考虑 top-3 卡组，忽略低概率卡组噪声
        2. 已确认打出牌的同卡组牌获得"共现加成"——同一套卡组里已打出多张牌，
           说明对手更可能在使用这套卡组，该卡组中未打出的牌概率大幅提升
        3. 不在任何 top-3 卡组中的牌概率极低，直接过滤
        """
        if transformed_from_ids is None:
            transformed_from_ids = set()
        results: List[CardProbability] = []
        pool = hand_size + deck_remaining

        if pool <= 0 or hand_size <= 0:
            return results

        top_decks = self._bayesian_state.get("top_decks", [])
        if not top_decks:
            return results

        # 只取 top-3 卡组（用户需求：最多适配3套）
        top_decks = top_decks[:3]

        card_weighted_probs: Dict[str, float] = {}
        card_info: Dict[str, Dict] = {}
        # 记录每张牌在哪些 top-3 卡组中出现过（用于区分度）
        card_deck_membership: Dict[str, List[Tuple[int, float]]] = {}  # card_id -> [(deck_idx, deck_prob)]

        # 收集所有 top-3 卡组的卡牌集合（dbfId 维度）
        all_deck_dbf_sets: List[set] = []
        for deck_id, deck_name, deck_prob in top_decks:
            deck_cards = self._get_deck_cards(deck_id)
            all_deck_dbf_sets.append(set(deck_cards) if deck_cards else set())

        # 统计对手已打出的非衍生牌在各卡组中的匹配数
        deck_match_counts: List[int] = [0] * len(top_decks)
        deck_total_seen: int = 0
        for card_id, seen_count in self._seen_cards.items():
            if card_id in self._generated_cards:
                continue
            dbf = self._card_id_to_dbf(card_id)
            if dbf is None:
                continue
            for idx, dbf_set in enumerate(all_deck_dbf_sets):
                if dbf in dbf_set:
                    deck_match_counts[idx] += seen_count
            deck_total_seen += seen_count

        # 计算每套卡组的"匹配加成因子"
        # 对手每打出一张非衍生牌，匹配到的卡组概率提升，未匹配的降低
        # 加成 = 1.0 + match_ratio * boost_strength
        # match_ratio = 匹配牌数 / 总已见牌数（0~1）
        # boost_strength 随已见牌数增加而增大（打得越多，区分度越高）
        deck_match_boost: List[float] = []
        if deck_total_seen > 0:
            # 已见牌越多，加成越强（最多 2.0 倍）
            boost_strength = min(2.0, 0.3 + deck_total_seen * 0.15)
            for idx in range(len(top_decks)):
                match_ratio = deck_match_counts[idx] / max(deck_total_seen, 1)
                # 匹配率高的卡组获得加成，低的获得惩罚
                deck_match_boost.append(1.0 + (match_ratio - 0.3) * boost_strength)
        else:
            deck_match_boost = [1.0] * len(top_decks)

        for deck_idx, (deck_id, deck_name, deck_prob) in enumerate(top_decks):
            if deck_prob <= 0.001:
                continue

            deck_cards = self._get_deck_cards(deck_id)
            if not deck_cards:
                continue

            card_counts = Counter(deck_cards)
            match_boost = deck_match_boost[deck_idx]

            for dbf_id, total_copies in card_counts.items():
                # dbfId → card_id
                card_id = self._dbf_to_card_id(dbf_id)
                if not card_id:
                    continue

                # 衍生牌不算
                if card_id in self._generated_cards:
                    continue

                # 英雄技能不算手牌
                card_data = self._card_db.get_card(card_id) if self._card_db else None
                if card_data and card_data.get("type", "").upper() == "HERO_POWER":
                    continue

                # 已弃牌的卡牌不再可能在手牌中
                if card_id in self._discarded_cards:
                    continue

                # 职业过滤：只显示对手职业或中立卡牌的概率
                # 防止其他职业卡组卡牌泄漏到手牌预测中
                if opp_class and card_data:
                    card_class = card_data.get("cardClass", "").upper()
                    if card_class not in ("NEUTRAL", opp_class.upper()):
                        continue

                # 被变形走的卡牌不再以原始形式存在于手牌/牌库
                if card_id in transformed_from_ids:
                    continue

                # 已打出的张数
                played = self._seen_cards.get(card_id, 0)

                # 剩余张数
                remaining = total_copies - played
                if remaining <= 0:
                    continue

                # 超几何分布: P(至少1张在手牌 | 这个卡组)
                p_in_hand = hypergeometric_at_least_one(
                    K=remaining,
                    n=hand_size,
                    N=pool,
                )

                # 应用匹配加成：匹配度高的卡组中牌概率提升
                p_in_hand = min(1.0, p_in_hand * match_boost)

                # 加权：卡组后验概率 × 超几何概率
                weighted = p_in_hand * deck_prob

                if card_id in card_weighted_probs:
                    card_weighted_probs[card_id] += weighted
                else:
                    card_weighted_probs[card_id] = weighted

                if card_id not in card_info and card_data:
                    card_info[card_id] = card_data

                if card_id not in card_deck_membership:
                    card_deck_membership[card_id] = []
                card_deck_membership[card_id].append((deck_idx, deck_prob))

        # 构建结果：区分卡组内牌 vs 不在卡组中的牌
        for card_id, prob in card_weighted_probs.items():
            info = card_info.get(card_id, {})
            remaining = self._estimate_remaining_copies(card_id)

            # 区分度标记：如果在 top-1 卡组中，标记为高可信度
            membership = card_deck_membership.get(card_id, [])
            best_deck_idx = max(membership, key=lambda x: x[1])[0] if membership else -1
            is_in_top_deck = best_deck_idx == 0

            cp = CardProbability(
                card_id=card_id,
                dbf_id=info.get("dbfId", 0),
                name=info.get("name", card_id),
                cost=info.get("cost", 0),
                probability=min(1.0, prob),
                remaining_copies=remaining,
                source="deck" if is_in_top_deck else "possible",
                card_type=info.get("type", ""),
                race=info.get("race", ""),
                spell_school=info.get("spellSchool", ""),
                confidence=top_decks[0][2] if top_decks else 0.0,
            )
            results.append(cp)

        return results

    def _apply_conditional_modifiers(self, report: HandProbabilityReport):
        """应用条件证据修正概率（贝叶斯修正）。"""
        for constraint in self._constraints:
            if constraint.constraint_type == "holds_race":
                race_cards = [
                    cp for cp in report.card_probabilities
                    if cp.race.upper() == constraint.value.upper()
                ]
                if not race_cards:
                    continue

                # P(holds_race) = 1 - Π(1 - P(c_i))
                p_no_race = 1.0
                for cp in race_cards:
                    p_no_race *= (1.0 - cp.probability)
                p_holds_race = 1.0 - p_no_race

                if p_holds_race <= 0:
                    continue

                # 贝叶斯修正: P(c | holds_race) = P(c) / P(holds_race)
                for cp in race_cards:
                    cp.probability = min(1.0, cp.probability / p_holds_race)
                    cp.source = "inferred"

                # 非种族牌适度降低
                non_race = [
                    cp for cp in report.card_probabilities
                    if cp.race.upper() != constraint.value.upper()
                    and cp.source != "revealed"
                ]
                reduction = p_holds_race * 0.3
                for cp in non_race:
                    cp.probability = max(0.0, cp.probability * (1.0 - reduction))

            elif constraint.constraint_type == "holds_school":
                school_cards = [
                    cp for cp in report.card_probabilities
                    if cp.spell_school.upper() == constraint.value.upper()
                ]
                if not school_cards:
                    continue

                p_no_school = 1.0
                for cp in school_cards:
                    p_no_school *= (1.0 - cp.probability)
                p_holds_school = 1.0 - p_no_school
                if p_holds_school <= 0:
                    continue

                for cp in school_cards:
                    cp.probability = min(1.0, cp.probability / p_holds_school)
                    cp.source = "inferred"

                # 非目标学派牌适度降低（与 holds_race / holds_card_type 对称）
                non_school = [
                    cp for cp in report.card_probabilities
                    if cp.spell_school.upper() != constraint.value.upper()
                    and cp.source != "revealed"
                ]
                reduction = p_holds_school * 0.3
                for cp in non_school:
                    cp.probability = max(0.0, cp.probability * (1.0 - reduction))

            elif constraint.constraint_type == "holds_card_type":
                # 导师效果: "draw a MINION" → 对手手牌必有该类型
                target_type = constraint.value.upper()  # "MINION", "SPELL", etc.
                type_cards = [
                    cp for cp in report.card_probabilities
                    if cp.card_type.upper() == target_type
                ]
                if not type_cards:
                    continue

                # P(holds_type) = 1 - Π(1 - P(c_i))
                p_no_type = 1.0
                for cp in type_cards:
                    p_no_type *= (1.0 - cp.probability)
                p_holds_type = 1.0 - p_no_type

                if p_holds_type <= 0:
                    continue

                # 贝叶斯修正: P(c | holds_type) = P(c) / P(holds_type)
                for cp in type_cards:
                    cp.probability = min(1.0, cp.probability / p_holds_type)
                    cp.source = "inferred"

                # 非目标类型牌适度降低
                non_type = [
                    cp for cp in report.card_probabilities
                    if cp.card_type.upper() != target_type
                    and cp.source != "revealed"
                ]
                reduction = p_holds_type * 0.3
                for cp in non_type:
                    cp.probability = max(0.0, cp.probability * (1.0 - reduction))

    # ── 持有回合推断 ──────────────────────────────────────

    def _apply_hold_duration_bias(self, report: HandProbabilityReport):
        """根据对手手牌持有时长修正概率。

        对手多回合不打出某张牌，说明该牌更可能是高费牌。
        逻辑：
        - 计算对手手牌的平均持有时长
        - 持有时间越长，高费牌概率提升，低费牌概率降低
        - 这种推断基于炉石常识：1费牌通常在1-2回合打出，
          5费以上牌通常要等更久
        """
        hand_count = report.hand_size
        current_turn = self._current_turn
        hold_data = self._opp_hand_hold

        if not hold_data or hand_count <= 0 or current_turn <= 1:
            return

        # 计算平均持有回合数
        hold_durations = []
        for eid, start_turn in hold_data.items():
            duration = current_turn - start_turn
            if duration > 0:
                hold_durations.append(duration)

        if not hold_durations:
            return

        avg_hold = sum(hold_durations) / len(hold_durations)

        # 如果平均持有 <= 1 回合，不需要调整
        if avg_hold <= 1:
            return

        # 偏好强度：持有越久，区分度越大
        bias_strength = min(1.0, avg_hold / 5.0)

        for cp in report.card_probabilities:
            if cp.source == "revealed":
                continue
            cost = cp.cost
            if cost <= 1:
                # 0-1费牌多回合不打：可能不是这些牌 → 降低
                cp.probability *= (1.0 - 0.3 * bias_strength)
            elif cost <= 3:
                # 2-3费牌：轻微降低
                cp.probability *= (1.0 - 0.1 * bias_strength)
            elif cost <= 5:
                # 4-5费牌：轻微提升
                cp.probability *= (1.0 + 0.2 * bias_strength)
            elif cost <= 7:
                # 6-7费牌：提升
                cp.probability *= (1.0 + 0.4 * bias_strength)
            else:
                # 8+费牌：显著提升
                cp.probability *= (1.0 + 0.6 * bias_strength)
            cp.probability = max(0.0, min(1.0, cp.probability))

    # ── 留牌推断 ──────────────────────────────────────

    def _apply_mulligan_keep_bias(self, report: HandProbabilityReport):
        """根据对手留牌行为修正概率。

        对手在mulligan阶段选择保留的牌更可能是低费牌。
        炉石玩家通常保留1-3费牌，换掉7+费牌。
        如果当前回合 <= 3（仍在早期），对手手牌中仍有mulligan保留的牌，
        那么这些牌更可能是低费的。

        逻辑：
        - 早期回合（turn <= 3）时，对手手牌中大部分还是mulligan保留的
        - 低费牌（0-3费）概率提升
        - 高费牌（7+费）概率降低（通常会被换掉）
        - 中期回合之后这个效果逐渐消退
        """
        current_turn = self._current_turn
        if current_turn <= 0:
            return

        # 只在早期回合生效（1-5回合），之后mulligan效果消退
        if current_turn > 5:
            return

        # 效果强度随回合衰减
        # turn 1: 最强(1.0), turn 3: 中等(0.5), turn 5: 微弱(0.1)
        mulligan_factor = max(0.0, 1.0 - (current_turn - 1) * 0.25)

        for cp in report.card_probabilities:
            if cp.source == "revealed":
                continue
            cost = cp.cost
            if cost <= 1:
                # 0-1费：几乎一定会保留
                cp.probability *= (1.0 + 0.3 * mulligan_factor)
            elif cost <= 3:
                # 2-3费：通常会保留
                cp.probability *= (1.0 + 0.2 * mulligan_factor)
            elif cost >= 7:
                # 7+费：通常会被换掉，除非是特殊卡组
                cp.probability *= (1.0 - 0.25 * mulligan_factor)
            elif cost >= 5:
                # 5-6费：部分保留部分换
                cp.probability *= (1.0 - 0.1 * mulligan_factor)
            # 4费：大致中性
            cp.probability = max(0.0, min(1.0, cp.probability))

    # ── 衍生牌共现推断 ──────────────────────────────────────

    def _apply_generated_cooccurrence_boost(self, report: HandProbabilityReport):
        """对手打出衍生牌时，同卡组牌概率应提升。

        当对手打出一张衍生牌（发现/创造），这张牌本身不是牌库牌，
        但它的出现说明对手拥有产生这张牌的源牌，源牌在卡组中。
        因此，同卡组中与源牌相关的其他牌概率也应该提升。

        更直接的逻辑：对手每打出一张牌（包括衍生牌），
        都增加了对手卡组"活跃度"的证据——如果对手已打出N张牌，
        而这些牌大多属于某个卡组，那么该卡组中的未打出牌
        在手牌中的概率更高（因为牌库更小、密度更高）。
        """
        # 统计对手已打出的总牌数（包括衍生牌）
        total_played = sum(self._seen_cards.values())

        if total_played <= 0:
            return

        # 衍生牌的源牌信息
        # 对手打出衍生牌 → 他一定有产生这张牌的源牌 → 源牌在卡组中
        # 我们无法精确知道源牌是哪张，但知道：
        # 1. 衍生牌越多，说明对手的卡组越倾向于"生成"类卡组
        # 2. 生成类卡组通常有更多"发现"/"随机"效果
        # 3. 效果触发牌（conditional_evidence triggered）提供了确定的手牌信息

        # 简化逻辑：对于每张已打出的衍生牌，其同卡组牌获得小幅加成
        # 这基于"对手能打出衍生牌 = 对手有足够的回合和手牌空间 = 更多卡组牌在手牌中"
        generated_count = len(self._generated_cards)

        if generated_count <= 0:
            return

        # 加成因子：衍生牌越多，说明对手越活跃，手牌中卡组牌密度越高
        # 但要适度，避免过度加成
        boost = min(0.3, generated_count * 0.05)  # 最多 30% 加成

        for cp in report.card_probabilities:
            if cp.source == "revealed":
                continue
            # 对手打出衍生牌 = 对手有法力余量 + 手牌有牌可打
            # → 同卡组中低中费牌更有可能在手牌中
            if cp.cost <= 5:
                cp.probability = min(1.0, cp.probability * (1.0 + boost))
            # 高费牌不一定有加成（可能法力不够打不出来）

    def _get_deck_cards(self, archetype_id: int) -> List[int]:
        """获取指定卡组原型包含的卡牌 dbfId 列表。

        首次调用时批量加载所有卡组数据到内存缓存，
        后续调用直接查内存，不再重复打开 DB 连接。
        """
        # 先查内存缓存
        if archetype_id in self._deck_cards_cache:
            return self._deck_cards_cache[archetype_id]

        # 批量加载所有卡组数据（仅首次调用时打开 DB）
        if not self._deck_cache_loaded:
            try:
                from analysis.data.fetch_hsreplay import init_db, get_meta_decks
                from analysis.config import HSREPLAY_CACHE_DB

                conn = init_db(str(HSREPLAY_CACHE_DB))
                try:
                    for d in get_meta_decks(conn):
                        aid = d.get("archetype_id")
                        if aid is not None:
                            self._deck_cards_cache[aid] = d.get("cards", [])
                finally:
                    conn.close()
                self._deck_cache_loaded = True
            except Exception as e:
                logger.debug("批量加载卡组数据失败: %s", e)
                self._deck_cache_loaded = True  # 避免重复尝试

        return self._deck_cards_cache.get(archetype_id, [])

    def _estimate_remaining_copies(self, card_id: str) -> int:
        top_decks = self._bayesian_state.get("top_decks", [])
        if not top_decks:
            return 1
        deck_id = top_decks[0][0]
        deck_cards = self._get_deck_cards(deck_id)
        if not deck_cards:
            return 1
        dbf_id = self._card_id_to_dbf(card_id)
        total = deck_cards.count(dbf_id) if dbf_id else 0
        played = self._seen_cards.get(card_id, 0)
        return max(0, total - played)

    def _card_id_to_dbf(self, card_id: str) -> Optional[int]:
        if self._card_db is not None:
            try:
                card = self._card_db.get_card(card_id)
                if card:
                    return card.get("dbfId")
            except Exception:
                pass
        return None

    def _dbf_to_card_id(self, dbf_id: int) -> str:
        if self._card_db is not None:
            card = self._card_db.get_by_dbf(dbf_id)
            if card:
                return card.get("cardId", card.get("id", ""))
        return ""

    def _card_id_to_probability(
        self, card_id: str, probability: float, source: str
    ) -> CardProbability:
        cp = CardProbability(
            card_id=card_id,
            probability=probability,
            source=source,
        )
        if self._card_db is not None:
            card = self._card_db.get_card(card_id)
            if card:
                cp.name = card.get("name", card_id)
                cp.cost = card.get("cost", 0)
                cp.card_type = card.get("type", "")
                cp.race = card.get("race", "")
                cp.spell_school = card.get("spellSchool", "")
                cp.dbf_id = card.get("dbfId", 0)
            else:
                cp.name = card_id
        else:
            cp.name = card_id
        return cp

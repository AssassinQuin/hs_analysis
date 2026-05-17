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

        for kc in state_dict.get("known_cards", []):
            ce = kc.get("conditional_evidence", "")
            triggered = kc.get("effect_triggered", False)
            if ce and triggered:
                self._add_constraint_from_evidence(ce, kc)

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

        # 2. 基于贝叶斯卡组的超几何分布概率
        bayesian_probs = self._compute_bayesian_hand_probabilities(
            hand_size, deck_remaining
        )
        for cp in bayesian_probs:
            if cp.card_id not in revealed_set:
                report.card_probabilities.append(cp)
                revealed_set.add(cp.card_id)

        # 3. 条件证据修正
        self._apply_conditional_modifiers(report)

        # 4. 排序
        report.card_probabilities.sort(
            key=lambda cp: (
                0 if cp.source == "revealed" else 1,
                -cp.probability,
                cp.cost,
            )
        )

        return report

    def _compute_bayesian_hand_probabilities(
        self, hand_size: int, deck_remaining: int
    ) -> List[CardProbability]:
        """基于贝叶斯后验 + 超几何分布计算每张卡牌的手牌概率。

        P(c in hand | observed) = Σ_j P(c in hand | deck=j) × P(deck=j | observed)
        """
        results: List[CardProbability] = []
        pool = hand_size + deck_remaining

        if pool <= 0 or hand_size <= 0:
            return results

        top_decks = self._bayesian_state.get("top_decks", [])
        if not top_decks:
            return results

        card_weighted_probs: Dict[str, float] = {}
        card_info: Dict[str, Dict] = {}

        for deck_id, deck_name, deck_prob in top_decks:
            if deck_prob <= 0.001:
                continue

            deck_cards = self._get_deck_cards(deck_id)
            if not deck_cards:
                continue

            card_counts = Counter(deck_cards)

            for dbf_id, total_copies in card_counts.items():
                # dbfId → card_id
                card_id = self._dbf_to_card_id(dbf_id)
                if not card_id:
                    continue

                # 衍生牌不算
                if card_id in self._generated_cards:
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

                # 加权
                weighted = p_in_hand * deck_prob

                if card_id in card_weighted_probs:
                    card_weighted_probs[card_id] += weighted
                else:
                    card_weighted_probs[card_id] = weighted

                if card_id not in card_info and self._card_db is not None:
                    card = self._card_db.get_card(card_id)
                    if card:
                        card_info[card_id] = card

        for card_id, prob in card_weighted_probs.items():
            info = card_info.get(card_id, {})
            remaining = self._estimate_remaining_copies(card_id)

            cp = CardProbability(
                card_id=card_id,
                dbf_id=info.get("dbfId", 0),
                name=info.get("name", card_id),
                cost=info.get("cost", 0),
                probability=min(1.0, prob),
                remaining_copies=remaining,
                source="deck",
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

    def _get_deck_cards(self, archetype_id: int) -> List[int]:
        try:
            from analysis.data.fetch_hsreplay import init_db, get_meta_decks
            from analysis.config import HSREPLAY_CACHE_DB

            conn = init_db(str(HSREPLAY_CACHE_DB))
            try:
                decks = get_meta_decks(conn)
                for d in decks:
                    if d["archetype_id"] == archetype_id:
                        return d.get("cards", [])
            finally:
                conn.close()
        except Exception as e:
            logger.debug("获取卡组卡牌失败: %s", e)
        return []

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

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

概率调整方法（MCTS/UCT 驱动）：
    粒子滤波采样 + UCT 对手行为模拟修正，无启发式回退。
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── 逐位手牌预测数据结构 ──────────────────────────────────────


@dataclass
class PositionPrediction:
    """逐位手牌预测结果。

    对手手牌中某一位（zone_position）的卡牌预测。
    位置从 1 开始编号（最左边 = 1）。
    """
    position: int             # zone_position (1-based)
    entity_id: int = 0        # 对应实体 ID (0=未知)
    card_id: str = ""         # 确认的 card_id（source=revealed 时非空）
    name: str = ""            # 卡牌名称
    probability: float = 0.0  # 此卡牌在该位置的概率
    source: str = "unknown"   # "revealed" | "predicted" | "unknown"
    cost: int = 0             # 卡牌费用
    alternatives: List[Tuple[str, float]] = field(default_factory=list)
    """备选卡牌 (card_id, probability) 列表，source!=revealed 时使用"""


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
        likelihood_ratio: 似然比 [0, ∞)

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

    prior_odds = prior / (1.0 - prior)
    posterior_odds = prior_odds * likelihood_ratio
    posterior = posterior_odds / (1.0 + posterior_odds)
    return max(0.0, min(1.0, posterior))


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
    mcts_applied: bool = False                    # Whether MCTS simulation was used
    mcts_top_predictions: List[Tuple[str, float]] = field(default_factory=list)  # Top MCTS predictions

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

from analysis.card.constants.hs_enums import CONDITIONAL_HOLDING_RULES as _CONDITIONAL_RULES


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
        self._revealed_hand: List[Tuple] = []
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
        # ── MCTS 对手行为模拟引擎 ──
        self._mcts_engine: Optional[object] = None  # OpponentHandMCTS 延迟初始化
        self._last_mcts_result: Optional[Dict[str, float]] = None  # MCTS推断结果缓存
        # MCTS模拟状态缓存哈希
        self._last_mcts_hash: int = 0
        # ── Power.log + Tracker 实时数据 ──
        # v2: 当 log_monitor 可用时，使用真实 GameState 构建
        self._log_monitor = None  # CoreLogMonitor 实例（外部注入）
        self._our_controller: int = 0
        self._opp_controller: int = 0

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.card.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def update_from_state_dict(self, state_dict: dict):
        """从 LogMonitor 的状态字典更新引擎状态。"""
        self._ensure_card_db()
        self._bayesian_state = state_dict.get("bayesian", {})

        self._seen_cards = {}
        self._known_cards_with_info = list(state_dict.get("known_cards", []))
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

        self._available_mana = state_dict.get("available_mana", 0)
        self._opp_cards_played_this_turn = list(state_dict.get("opp_cards_played_this_turn", []))

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

        # 重置世界模型证据缓存（状态已更新）
        self._last_world_evidence = None

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

    def set_log_monitor(
        self,
        log_monitor,
        our_controller: int = 0,
        opp_controller: int = 0,
    ):
        """注入 CoreLogMonitor 实例，启用 Power.log 实时数据模式。

        当 log_monitor 可用时，MCTS 模拟会使用真实的 GameState
        （从 entity_cache 构建），而非手动构建的简化 GameState。

        这显著提升了模拟精度，因为：
        1. 英雄 HP/护甲从 entity_cache 精确提取
        2. 法力值从 PLAYER 标签精确提取
        3. 场面随从的属性和关键词从实体标签精确提取
        4. 武器状态从 WEAPON 实体提取

        Args:
            log_monitor: CoreLogMonitor 实例
            our_controller: 我方控制器 ID（1 或 2）
            opp_controller: 对手控制器 ID（1 或 2）
        """
        self._log_monitor = log_monitor
        self._our_controller = our_controller
        self._opp_controller = opp_controller

    def on_turn_changed(self, turn: int, state_dict: dict):
        """回合切换时触发MCTS对手手牌推断。

        核心逻辑：
        1. 从最大概率卡组中提取非衍生牌列表
        2. 减去已使用的非衍生卡牌
        3. 将剩余的非衍生卡牌作为对手手牌候选传入MCTS模拟
        4. 聚合多回合信息更新概率

        Args:
            turn: 当前回合数
            state_dict: 当前游戏状态字典
        """
        # 更新内部状态
        self.update_from_state_dict(state_dict)

        # 提取最大概率卡组的非衍生卡牌
        non_derived_candidates = self._compute_non_derived_hand_candidates(state_dict)

        if non_derived_candidates and self._mcts_engine is None:
            try:
                from analysis.engine.opponent_hand_mcts import OpponentHandMCTS
                self._mcts_engine = OpponentHandMCTS(time_budget_ms=2000.0)
            except Exception as e:
                logger.debug("MCTS引擎初始化失败: %s", e)
                return

        # 将非衍生候选注入MCTS推断
        if non_derived_candidates and self._mcts_engine is not None:
            try:
                from analysis.engine.opponent_hand_mcts import ObservedBehavior

                opp_cards_this_turn = self._opp_cards_played_this_turn
                mana_spent = 0
                for kc in self._known_cards_with_info:
                    if kc.get("turn_seen", 0) == turn:
                        cost = kc.get("cost", 0)
                        if isinstance(cost, (int, float)):
                            mana_spent += int(cost)

                is_pass = len(opp_cards_this_turn) == 0 and mana_spent == 0 and turn > 1

                observed = ObservedBehavior(
                    played_cards=list(opp_cards_this_turn),
                    mana_spent=mana_spent,
                    available_mana=self._available_mana,
                    passed=is_pass,
                    turn=turn,
                )

                hand_size = state_dict.get("opp_hand_count", 0)
                if turn <= 1 and not observed.played_cards:
                    return

                # 执行MCTS推断（优先使用tracker模式）
                if self._log_monitor is not None and self._our_controller and self._opp_controller:
                    mcts_probs = self._mcts_engine.infer_from_tracker(
                        log_monitor=self._log_monitor,
                        our_controller=self._our_controller,
                        opp_controller=self._opp_controller,
                        observed=observed,
                        bayesian_state=self._bayesian_state,
                        seen_cards=self._seen_cards,
                        generated_cards=self._generated_cards,
                        hand_size=hand_size,
                        non_derived_candidates=non_derived_candidates,
                        time_budget_ms=2000.0,
                    )
                else:
                    mcts_probs = self._mcts_engine.infer_hand_probabilities(
                        bayesian_state=self._bayesian_state,
                        observed=observed,
                        seen_cards=self._seen_cards,
                        generated_cards=self._generated_cards,
                        hand_size=hand_size,
                        non_derived_candidates=non_derived_candidates,
                        time_budget_ms=2000.0,
                    )

                if mcts_probs:
                    self._last_mcts_result = mcts_probs
                    logger.debug("回合%d MCTS推断完成: %d张牌有概率", turn, len(mcts_probs))
            except Exception as e:
                logger.debug("回合%d MCTS推断失败: %s", turn, e)

    def _compute_non_derived_hand_candidates(self, state_dict: dict) -> List[str]:
        """计算对手手牌的非衍生候选卡牌。

        核心逻辑：
        top-N 卡组加权候选池 - 已使用的非衍生卡 = 对手手牌非衍生候选

        改进：不再仅取 top-1 卡组，而是从 top-N 卡组中按后验概率
        加权收集候选卡牌。这增加了手牌假设的覆盖度，特别是当
        对手实际使用的卡组与 top-1 卡组不完全匹配时。

        Args:
            state_dict: 当前游戏状态字典

        Returns:
            非衍生候选卡牌的card_id列表
        """
        self._ensure_card_db()
        top_decks = self._bayesian_state.get("top_decks", [])
        if not top_decks:
            return []

        # ── deck_codes 独占约束 ──
        top_deck_sources = self._bayesian_state.get("top_deck_sources", {})
        is_deck_codes_exclusive = False
        if top_decks and top_decks[0][0] in top_deck_sources:
            is_deck_codes_exclusive = top_deck_sources[top_decks[0][0]] == "deck_codes"
        if is_deck_codes_exclusive:
            # 独占：仅从 top-1 卡组收集候选
            max_decks = 1
        else:
            max_decks = min(5, len(top_decks))  # 最多取 top-5 卡组

        candidates_set = set()
        for deck_idx in range(max_decks):
            deck_id, deck_name, deck_prob = top_decks[deck_idx]

            # 如果卡组概率太低，跳过
            if deck_prob < 0.01:
                continue

            # 获取卡组卡牌列表
            deck_cards = self._get_deck_cards_cached(deck_id)
            if not deck_cards:
                continue

            card_counts = Counter(deck_cards)
            for dbf_id, total_copies in card_counts.items():
                card_id = self._dbf_to_card_id(dbf_id)
                if not card_id:
                    continue
                if card_id in self._generated_cards:
                    continue  # 排除衍生牌
                # 卡牌类型检查
                if self._card_db:
                    card_data = self._card_db.get_card(card_id)
                    if card_data and card_data.get("type", "").upper() == "HERO_POWER":
                        continue
                # 计算剩余非衍生张数
                played = self._seen_cards.get(card_id, 0)
                remaining = total_copies - played
                if remaining > 0:
                    candidates_set.add(card_id)

        return list(candidates_set)

    def _get_deck_cards_cached(self, archetype_id: int) -> List[int]:
        """获取卡组的dbfId列表（带缓存）。"""
        if archetype_id in self._deck_cards_cache:
            return self._deck_cards_cache[archetype_id]

        try:
            from analysis.data.fetch_hsreplay import init_db, get_meta_decks
            from analysis.config import HSREPLAY_CACHE_DB
            conn = init_db(str(HSREPLAY_CACHE_DB))
            if conn is None:
                return []
            meta_decks = get_meta_decks(conn)
            deck_map = {d["archetype_id"]: d for d in meta_decks}
            target = deck_map.get(archetype_id)
            if target and target.get("cards"):
                cards = target["cards"]
                self._deck_cards_cache[archetype_id] = cards
                return cards
        except Exception:
            pass
        return []

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
        for eid, card_id, *_ in self._revealed_hand:
            if card_id and card_id not in revealed_set:
                cp = self._card_id_to_probability(card_id, 1.0, "revealed")
                report.card_probabilities.append(cp)
                revealed_set.add(card_id)

        # 1a. 后手硬币：如果对手是后手且硬币未使用，100%确认对手手牌有硬币
        # 后手第5张牌一定是硬币，这是游戏机制
        if not self._is_first_player and not self._coin_used:
            # 硬币卡牌ID
            from analysis.card.constants.hs_enums import COIN_CARD_IDS
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

        # 4. MCTS/UCT 世界节点模拟推断
        #    (粒子滤波采样 → UCT搜索模拟 → 行为匹配 → 概率融合)
        self._apply_world_model_evidence(report, hand_size=hand_size)

        # 5. 应用确认手牌先验提升（在条件修正之后，确保不被覆盖）
        for cp in report.card_probabilities:
            if cp.card_id in confirmed_boost and cp.source != "revealed":
                cp.probability = max(cp.probability, confirmed_boost[cp.card_id])
                if cp.source != "inferred":
                    cp.source = "confirmed_prior"

        # 7. 标记MCTS应用状态
        if self._mcts_engine is not None and self._last_mcts_result:
            report.mcts_applied = True
            sorted_mcts = sorted(self._last_mcts_result.items(), key=lambda x: -x[1])[:5]
            report.mcts_top_predictions = [(cid, prob) for cid, prob in sorted_mcts]

        # 6. 排序
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

        # ── deck_codes 独占约束 ──
        # 当 top-1 卡组来自 deck_codes.txt（完整已知卡组），
        # 独占使用其卡牌列表，不与其他卡组交叉混合。
        top_deck_sources = self._bayesian_state.get("top_deck_sources", {})
        is_deck_codes_exclusive = False
        if top_decks and top_decks[0][0] in top_deck_sources:
            is_deck_codes_exclusive = top_deck_sources[top_decks[0][0]] == "deck_codes"
        if is_deck_codes_exclusive:
            # 仅使用 top-1 卡组，不跨卡组聚合
            top_decks = top_decks[:1]

        card_weighted_probs: Dict[str, float] = {}
        card_info: Dict[str, Dict] = {}
        # 记录每张牌在哪些 top-3 卡组中出现过（用于区分度）
        card_deck_membership: Dict[str, List[Tuple[int, float]]] = {}  # card_id -> [(deck_idx, deck_prob)]

        # 收集所有 top-N 卡组的卡牌集合（dbfId 维度）
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

    # ── 世界模型证据修正 ──────────────────────────────────────

    def _apply_world_model_evidence(
        self,
        report: HandProbabilityReport,
        hand_size: int = 0,
    ):
        """仅使用MCTS世界节点模拟推断修正手牌概率（去除所有启发式回退）。

        核心逻辑通过 _apply_mcts_simulation_evidence 实现：
        - 采样候选手牌世界（粒子滤波）
        - UCT搜索模拟对手决策
        - 比较模拟行为与观测行为的匹配度
        - 完全不硬编码概率值，通过模拟得出

        Args:
            report: 手牌概率报告（会被就地修改）
            hand_size: 对手手牌数量
        """
        mcts_applied = self._apply_mcts_simulation_evidence(report, hand_size=hand_size)
        if mcts_applied:
            logger.debug("MCTS模拟推断成功应用于手牌概率")

    def _apply_mcts_simulation_evidence(
        self,
        report: HandProbabilityReport,
        hand_size: int = 0,
    ) -> bool:
        """通过MCTS世界节点模拟推断修正手牌概率。

        核心思路：
        1. 优先使用 on_turn_changed() 中已缓存的MCTS结果（避免重复计算）
        2. 如果没有缓存结果，则重新执行MCTS推断
        3. 将MCTS概率与超几何分布基础概率做贝叶斯融合

        融合策略：
        MCTS给出的概率被视为"似然比"(likelihood ratio)，
        通过贝叶斯公式修正超几何分布的先验概率：
        P(card_in_hand | mcts_evidence) = LR × P_prior / (1 + LR × P_prior - P_prior)

        其中 LR = P_mcts_odds / P_prior_odds

        Args:
            report: 手牌概率报告（会被就地修改）
            hand_size: 对手手牌数量

        Returns:
            True 如果MCTS成功应用，False 如果需要回退
        """
        # 优先使用 on_turn_changed() 中缓存的MCTS结果
        mcts_probs = self._last_mcts_result

        if mcts_probs is None:
            # 没有缓存结果，尝试在此处执行MCTS推断
            # 延迟初始化MCTS引擎
            if self._mcts_engine is None:
                try:
                    from analysis.engine.opponent_hand_mcts import OpponentHandMCTS
                    self._mcts_engine = OpponentHandMCTS(time_budget_ms=2000.0)
                except Exception as e:
                    logger.debug("MCTS引擎初始化失败: %s", e)
                    return False

            # 构建MCTS所需的输入
            try:
                from analysis.engine.opponent_hand_mcts import ObservedBehavior

                # 构建观测行为
                opp_cards_this_turn = self._opp_cards_played_this_turn
                mana_spent = 0
                for kc in self._known_cards_with_info:
                    if kc.get("turn_seen", 0) == self._current_turn:
                        cost = kc.get("cost", 0)
                        if isinstance(cost, (int, float)):
                            mana_spent += int(cost)

                is_pass = len(opp_cards_this_turn) == 0 and mana_spent == 0 and self._current_turn > 1

                observed = ObservedBehavior(
                    played_cards=list(opp_cards_this_turn),
                    mana_spent=mana_spent,
                    available_mana=self._available_mana,
                    passed=is_pass,
                    turn=self._current_turn,
                )

                # 如果没有足够信息（回合太早或没有观测行为），跳过MCTS
                if self._current_turn <= 1 and not observed.played_cards:
                    return False

                # 执行MCTS推断
                # 优先使用 Power.log + Tracker 实时数据（v2）
                if self._log_monitor is not None and self._our_controller and self._opp_controller:
                    mcts_probs = self._mcts_engine.infer_from_tracker(
                        log_monitor=self._log_monitor,
                        our_controller=self._our_controller,
                        opp_controller=self._opp_controller,
                        observed=observed,
                        bayesian_state=self._bayesian_state,
                        seen_cards=self._seen_cards,
                        generated_cards=self._generated_cards,
                        hand_size=hand_size,
                        time_budget_ms=1000.0,
                    )
                else:
                    # 回退到简化模式（兼容旧接口）
                    mcts_probs = self._mcts_engine.infer_hand_probabilities(
                        bayesian_state=self._bayesian_state,
                        observed=observed,
                        seen_cards=self._seen_cards,
                        generated_cards=self._generated_cards,
                        hand_size=hand_size,
                        time_budget_ms=1000.0,
                    )

                if not mcts_probs:
                    return False

                # 缓存结果供后续帧使用
                self._last_mcts_result = mcts_probs

            except Exception as e:
                logger.debug("MCTS推断执行失败: %s", e)
                return False

        if not mcts_probs:
            return False

        # 将MCTS推断结果应用到报告
        # 策略：MCTS给出了每张牌在手牌中的概率
        # 我们用它作为似然比来修正超几何分布的基础概率
        for cp in report.card_probabilities:
            if cp.source == "revealed":
                continue

            mcts_prob = mcts_probs.get(cp.card_id, 0.0)
            if mcts_prob <= 0.0:
                continue

            # 将MCTS概率转化为似然比
            # 如果MCTS认为牌在手牌中的概率高于超几何基础概率 → 提升
            # 如果MCTS认为概率低于基础概率 → 降低
            if cp.probability > 0.0 and cp.probability < 1.0:
                # LR = P(mcts|card_in_hand) / P(mcts|card_not_in_hand)
                # 近似：LR = mcts_prob / (1 - mcts_prob) / (prior_prob / (1 - prior_prob))
                prior_odds = cp.probability / (1.0 - cp.probability)
                mcts_odds = mcts_prob / max(0.001, 1.0 - mcts_prob)
                if prior_odds > 0:
                    lr = mcts_odds / prior_odds
                    # 限制似然比范围，避免过度调整
                    lr = max(0.1, min(10.0, lr))
                    cp.probability = apply_likelihood_to_probability(cp.probability, lr)
                    if abs(lr - 1.0) > 0.1 and cp.source not in ("revealed", "inferred"):
                        cp.source = "inferred"
            elif cp.probability == 0.0 and mcts_prob > 0.0:
                # 基础概率为0但MCTS认为有可能
                cp.probability = mcts_prob * 0.5  # 保守提升
                cp.source = "inferred"

        # 为不在超几何报告中但MCTS给出概率的卡牌添加新条目
        existing_ids = {cp.card_id for cp in report.card_probabilities}
        for card_id, mcts_prob in mcts_probs.items():
            if card_id not in existing_ids and mcts_prob >= 0.1:
                # MCTS发现了新候选牌（可能不在top-3卡组中）
                cp = self._card_id_to_probability(card_id, mcts_prob, "inferred")
                if cp:
                    report.card_probabilities.append(cp)
                    existing_ids.add(card_id)

        return True



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

    def compute_position_predictions(
        self,
        hand_size: int,
        deck_remaining: int,
        opp_class: str = "",
        known_hand_with_pos: Optional[List[Tuple[int, str, int]]] = None,
        opp_hand_positions: Optional[Dict[int, int]] = None,
        opp_hand_hold: Optional[Dict[int, int]] = None,
        current_turn: int = 0,
    ) -> List[PositionPrediction]:
        """逐位手牌预测。

        对手手牌按 zone_position (1-based) 逐位预测：
        - source=revealed: 该位已揭示 → 100% 确认
        - source=predicted: 持有回合长 → 用 cost_bias 缩小候选
        - source=unknown: 无额外信息 → 用 flat 概率结果填充

        Args:
            hand_size: 对手手牌数
            deck_remaining: 对手牌库剩余
            opp_class: 对手职业
            known_hand_with_pos: [(entity_id, card_id, zone_position), ...]
            opp_hand_positions: entity_id → zone_position
            opp_hand_hold: entity_id → turn_first_seen
            current_turn: 当前回合

        Returns:
            List[PositionPrediction]: 逐位预测，按 position 排序
        """
        if hand_size <= 0:
            return []

        known_hand_with_pos = known_hand_with_pos or []
        opp_hand_positions = opp_hand_positions or {}
        opp_hand_hold = opp_hand_hold or {}

        # 1. 先计算 flat 概率作为后备
        report = self.compute_probabilities(hand_size, deck_remaining, opp_class)
        flat_probs: Dict[str, float] = {}
        flat_cards: Dict[str, Dict] = {}
        for cp in report.card_probabilities:
            flat_probs[cp.card_id] = cp.probability
            flat_cards[cp.card_id] = {
                "name": cp.name, "cost": cp.cost,
                "source": cp.source, "card_type": cp.card_type,
            }

        # 2. 按 position 构建预测
        predictions: List[PositionPrediction] = []

        # 倒排：entity_id → card_id（从 known_hand_with_pos）
        eid_to_card: Dict[int, str] = {}
        eid_to_pos: Dict[int, int] = {}
        pos_to_eid: Dict[int, int] = {}
        pos_to_card: Dict[int, str] = {}
        for eid, cid, pos in known_hand_with_pos:
            if eid and cid:
                eid_to_card[eid] = cid
            if pos > 0:
                eid_to_pos[eid] = pos
                pos_to_eid[pos] = eid
                if cid:
                    pos_to_card[pos] = cid

        # 对每个位置 1..hand_size
        for pos in range(1, hand_size + 1):
            eid = pos_to_eid.get(pos, 0)
            card_id = pos_to_card.get(pos, "") or eid_to_card.get(eid, "")

            if card_id and flat_cards.get(card_id, {}).get("source") == "revealed":
                # 已揭示 → 100% 确认
                info = flat_cards.get(card_id, {})
                predictions.append(PositionPrediction(
                    position=pos, entity_id=eid, card_id=card_id,
                    name=info.get("name", card_id), probability=1.0,
                    source="revealed", cost=info.get("cost", 0),
                ))
            else:
                # 未揭示 → 用 flat 概率 + 持有推断
                hold_turn = opp_hand_hold.get(eid, 0)
                base_prob = flat_probs.get(card_id, 0.0) if card_id else 0.0

                # 持有回合推断：长期未打 → 高费偏好
                if hold_turn > 0 and current_turn > hold_turn:
                    duration = current_turn - hold_turn
                    if duration >= 2 and self._card_db:
                        # 用费用偏差修正概率
                        from analysis.utils.bayesian_opponent import BayesianOpponentModel
                        bias_model = BayesianOpponentModel.__new__(BayesianOpponentModel)
                        bias_model._hand_hold_since = opp_hand_hold
                        # 用 get_cost_bias_for_hand 的简化版本
                        bias_strength = min(1.0, duration / 5.0)
                        cost_bias = {}
                        for c in range(0, 11):
                            if c <= 2:
                                cost_bias[c] = 1.0 - 0.3 * bias_strength
                            elif c <= 4:
                                cost_bias[c] = 1.0
                            elif c <= 6:
                                cost_bias[c] = 1.0 + 0.5 * bias_strength
                            else:
                                cost_bias[c] = 1.0 + 1.0 * bias_strength

                        # 对 flat 候选按费用加权
                        weighted_candidates = []
                        for cid, prob in flat_probs.items():
                            info = flat_cards.get(cid, {})
                            cost = info.get("cost", 5)
                            bias = cost_bias.get(cost, 1.0)
                            weighted_prob = prob * bias
                            if weighted_prob > 0.01:
                                weighted_candidates.append((cid, weighted_prob, cost))

                        weighted_candidates.sort(key=lambda x: -x[1])

                        if weighted_candidates:
                            best_cid, best_prob, best_cost = weighted_candidates[0]
                            alternatives = [(cid, p) for cid, p, _ in weighted_candidates[1:4]]
                            predictions.append(PositionPrediction(
                                position=pos, entity_id=eid,
                                card_id=best_cid, name=flat_cards.get(best_cid, {}).get("name", best_cid),
                                probability=min(1.0, best_prob),
                                source="predicted", cost=best_cost,
                                alternatives=alternatives,
                            ))
                            continue

                # 默认：用 flat 概率中该位置对应的已知卡牌
                if card_id and base_prob > 0:
                    info = flat_cards.get(card_id, {})
                    predictions.append(PositionPrediction(
                        position=pos, entity_id=eid,
                        card_id=card_id, name=info.get("name", card_id),
                        probability=base_prob,
                        source="predicted", cost=info.get("cost", 0),
                    ))
                else:
                    # 完全未知位置 → 用 top-1 flat 卡牌填充
                    top_cards = sorted(flat_probs.items(), key=lambda x: -x[1])
                    best = top_cards[0] if top_cards else ("", 0.0)
                    best_cid, best_prob = best
                    info = flat_cards.get(best_cid, {})
                    predictions.append(PositionPrediction(
                        position=pos, entity_id=eid,
                        card_id=best_cid, name=info.get("name", best_cid),
                        probability=best_prob,
                        source="unknown", cost=info.get("cost", 0),
                    ))

        return predictions

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

#!/usr/bin/env python3
"""deck_pool_tracker.py — 滑动窗口 deck pool + 手牌推断引擎

当 Power.log 未揭示玩家手牌的 card_id 时，通过"滑动窗口"方法推断
可能的卡牌组合：

1. 初始池 = 标准模式该职业 + 中立的所有可收集卡牌
2. 追踪已确认卡牌 (SHOW_ENTITY 揭示、己方打出)
3. 对手打出非衍生卡 → 从池中排除（对手牌组中的卡，不可能是我们的）
4. 衍生卡标记为衍生（不属于原始牌库）
5. 每回合未知手牌 = 从剩余池中采样填入
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class TurnHandState:
    """某回合的手牌推断快照。"""
    turn: int
    known_hand: List[str] = field(default_factory=list)
    unknown_count: int = 0
    available_pool_size: int = 0
    sampled: List[str] = field(default_factory=list)

    @property
    def filled_hand(self) -> List[str]:
        """已知 + 采样填充后的完整手牌列表。"""
        return self.known_hand + self.sampled


class DeckPoolTracker:
    """滑动窗口牌库推断引擎。

    用法:
        tracker = DeckPoolTracker("ROGUE")
        tracker.register_revealed(11, "CATA_154")
        tracker.register_player_played("CATA_154")
        tracker.register_opp_played("TLC_461")
        hand = tracker.fill_unknown_hand(["CATA_154"], 7)
    """

    def __init__(self, player_class: str = "ROGUE"):
        from analysis.card.data.card_data import get_db

        self.db = get_db()
        self.player_class = player_class

        # 初始可能池：标准该职业 + 中立可收集卡牌
        self._pool: Set[str] = self._build_initial_pool()
        logger.info(
            "DeckPoolTracker[%s]: 初始池 %d 张",
            player_class, len(self._pool),
        )

        # 追踪集合
        self._confirmed_hand: Dict[int, str] = {}
        self._confirmed_played: Set[str] = set()
        self._opp_non_derived_played: Set[str] = set()
        self._generated: Set[str] = set()
        self._all_revealed: Set[str] = set()

        # 回合快照
        self._turn_states: Dict[int, TurnHandState] = {}

    # ── 池初始化 ───────────────────────────────────────────

    def _build_initial_pool(self) -> Set[str]:
        """构建初始卡牌池：标准模式的职业牌 + 中立牌。"""
        pool: Set[str] = set()
        std_cards = self.db.by_format.get("standard", [])
        for c in std_cards:
            cls = c.get("cardClass", "NEUTRAL")
            cid = c.get("cardId", "")
            if not cid:
                continue
            if cls == self.player_class or cls == "NEUTRAL":
                pool.add(cid)
        return pool

    # ── 注册接口 ─────────────────────────────────────────

    def register_revealed(self, entity_id: int, card_id: str):
        """SHOW_ENTITY 揭示的玩家手牌。"""
        self._confirmed_hand[entity_id] = card_id
        self._all_revealed.add(card_id)

    def register_player_played(self, card_id: str):
        """玩家打出的卡牌（从手牌中消耗）。"""
        self._confirmed_played.add(card_id)

    def register_opp_played(self, card_id: str, is_derived: bool = False):
        """对手打出的卡牌。

        Args:
            card_id: 卡牌 ID
            is_derived: 是否为衍生牌（生成而非从牌库抽的）
        """
        if is_derived:
            self._generated.add(card_id)
        else:
            self._opp_non_derived_played.add(card_id)

    def register_generated(self, card_id: str):
        """标记为衍生牌。"""
        self._generated.add(card_id)

    # ── 池查询 ─────────────────────────────────────────

    def get_available_pool(self) -> Set[str]:
        """获取当前可用的卡牌池（初始 - 已排除）。

        排除规则:
        - 已打出的牌（我方）：从手牌/牌库消耗，排除
        - 对手打出的非衍生牌：在对手卡组中，不可能在我方牌库，排除
        - 已揭示的卡牌：减去衍生牌（生成的不影响原始牌库中的副本）

        注意：当牌池小于采样需求时，fill_unknown_hand 会使用
        rng.choices（有放回采样）兜底，避免崩溃。
        """
        excluded_from_revealed = self._all_revealed - self._generated
        unavailable = (
            self._confirmed_played
            | self._opp_non_derived_played
            | excluded_from_revealed
        )
        return self._pool - unavailable

    def fill_unknown_hand(
        self,
        known_hand_ids: List[str],
        hand_count: int,
        seed: Optional[int] = None,
    ) -> List[str]:
        """从可用池采样填充未知手牌。

        Args:
            known_hand_ids: 已知手牌的 card_id 列表
            hand_count: 总手牌数
            seed: 随机种子 (None = 不固定)

        Returns:
            填充后的手牌 card_id 列表 (已知 + 采样)
        """
        rng = random.Random(seed)

        available = self.get_available_pool()
        remaining = available - set(known_hand_ids)
        remaining_list = sorted(remaining)

        unknown_count = hand_count - len(known_hand_ids)
        if unknown_count <= 0:
            return known_hand_ids[:hand_count]

        if len(remaining_list) < unknown_count:
            sampled = rng.choices(remaining_list, k=unknown_count)
        else:
            sampled = rng.sample(remaining_list, unknown_count)

        return known_hand_ids + sampled

    def snapshot(
        self,
        turn: int,
        known_hand_ids: List[str],
        hand_count: int,
        seed: Optional[int] = None,
    ) -> TurnHandState:
        """记录回合快照并返回填充后的手牌。"""
        available = self.get_available_pool()
        sampled = self.fill_unknown_hand(known_hand_ids, hand_count, seed)
        state = TurnHandState(
            turn=turn,
            known_hand=known_hand_ids,
            unknown_count=hand_count - len(known_hand_ids),
            available_pool_size=len(available),
            sampled=sampled,
        )
        self._turn_states[turn] = state
        logger.debug(
            "Turn %d: known=%d, unknown=%d, pool=%d, total_hand=%d",
            turn, len(known_hand_ids), state.unknown_count,
            state.available_pool_size, len(sampled) + len(known_hand_ids),
        )
        return state

    @property
    def pool_size(self) -> int:
        return len(self._pool)

    @property
    def available_size(self) -> int:
        return len(self.get_available_pool())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    t = DeckPoolTracker("ROGUE")
    print(f"初始池大小: {t.pool_size}")
    print(f"可用池大小: {t.available_size}")

    t.register_player_played("AT_028")
    t.register_opp_played("TLC_461")
    print(f"注册后可用池: {t.available_size}")

    hand = t.fill_unknown_hand(["CORE_EX1_145"], 5, seed=42)
    print(f"填充手牌 (5张, 1已知): {hand}")

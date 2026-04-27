"""deterministic.py — 确定性伪随机数生成器（MCTS 友好）。

替代所有 random.* 调用，确保同一 GameState + 同一动作产出确定结果。
核心算法：xorshift32 — 快速、无外部依赖、周期 2^32-1。

Usage:
    rng = DeterministicRNG(seed=42)
    card = rng.choice(pool)
    cards = rng.sample(pool, k=3)
    top = det_top_k(pool, k=3, score_fn=lambda c: c.attack)
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional


class DeterministicRNG:
    """基于 xorshift32 的确定性伪随机数生成器。

    相同 seed → 相同序列。用于 MCTS 模拟中的确定性化。
    """

    def __init__(self, seed: int):
        """初始化 RNG。seed 会被截断为 32 位无符号整数。"""
        self._state = seed & 0xFFFFFFFF

    def _next(self) -> int:
        """xorshift32 — 生成下一个 32 位伪随机数。"""
        s = self._state
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= (s >> 17)
        s ^= (s << 5) & 0xFFFFFFFF
        self._state = s
        return s

    def choice(self, seq: list) -> Any:
        """确定性选择 — 从序列中选一个元素。"""
        if not seq:
            raise IndexError("cannot choose from empty sequence")
        if len(seq) == 1:
            return seq[0]
        idx = self._next() % len(seq)
        return seq[idx]

    def sample(self, seq: list, k: int) -> list:
        """确定性采样 — Fisher-Yates 变体，无重复。

        Args:
            seq: 源序列。
            k: 采样数量。

        Returns:
            采样结果列表（不修改原序列）。
        """
        pool = list(seq)
        result = []
        for _ in range(min(k, len(pool))):
            idx = self._next() % len(pool)
            result.append(pool.pop(idx))
        return result

    @staticmethod
    def from_state(state: Any) -> "DeterministicRNG":
        """从游戏状态创建确定性 RNG。

        Args:
            state: GameState 实例。当前使用 Any 类型，因为 GameState
                   正在从 analysis/search/game_state.py 迁移到
                   analysis/engine/state.py。Phase 2 后将改为具体类型。

        Returns:
            DeterministicRNG 实例，seed 由状态快照哈希决定。
        """
        seed = hash((
            getattr(state, 'turn_number', 0),
            tuple(getattr(m, 'card_id', '') for m in getattr(state, 'board', [])),
            tuple(getattr(m, 'card_id', '') for m in getattr(getattr(state, 'opponent', None), 'board', [])),
            getattr(getattr(state, 'hero', None), 'hp', 0),
            getattr(getattr(getattr(state, 'opponent', None), 'hero', None), 'hp', 0),
        )) & 0xFFFFFFFF
        return DeterministicRNG(seed)


def det_top_k(pool: list, k: int, score_fn: Callable[[Any], float]) -> list:
    """确定性 top-K 选择 — 按 score 排序取前 K 个（无随机性）。

    用于 Discover 效果：从候选池中选出 score 最高的 K 个卡牌。

    Args:
        pool: 候选池列表。
        k: 选取数量。
        score_fn: 评分函数 (item) → float，越高越优先。

    Returns:
        得分最高的 K 个元素列表（按分数降序）。
    """
    if k <= 0:
        return []
    scored = [(item, score_fn(item)) for item in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [item for item, _ in scored[:k]]

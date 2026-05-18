"""engine_adapter.py — Thin adapter so DecisionLoop can use MCTS engine.

核心设计：整个游戏生命周期只有一个 MCTSEngine 实例 + 一个 BayesianOpponentModel。
UCT 选择策略是 MCTSEngine 内部的无状态函数，天然单例。

架构:
    GameEngine (singleton per game)
      ├── MCTSEngine   (singleton — 跨回合复用，TT 可继承)
      └── BayesianOpponentModel (singleton — 跨回合累积证据)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from analysis.search.abilities.actions import Action

log = logging.getLogger(__name__)


class ActionProb:
    """Per-action probability and win-rate for display."""

    __slots__ = ("action", "visit_count", "probability", "win_rate", "q_value")

    def __init__(
        self,
        action: Action,
        visit_count: int = 0,
        probability: float = 0.0,
        win_rate: float = 0.0,
        q_value: float = 0.0,
    ):
        self.action = action
        self.visit_count = visit_count
        self.probability = probability
        self.win_rate = win_rate
        self.q_value = q_value


class UnifiedSearchResult:
    """Normalised search result that DecisionLoop / DecisionPresenter can consume.

    Wraps an MCTS ``SearchResult`` and exposes a uniform attribute interface.
    """

    __slots__ = (
        "_raw",
        "best_chromosome",
        "best_fitness",
        "alternatives",
        "confidence",
        "population_diversity",
        "generations_run",
        "timings",
        "action_probs",
        "mcts_stats",
        "mcts_detailed_log",
    )

    def __init__(self, raw: Any):
        self._raw = raw

        self.alternatives: List[Tuple[List[Action], float]] = getattr(raw, "alternatives", [])

        self.best_chromosome: List[Action] = raw.best_sequence
        self.best_fitness: float = raw.fitness
        mcts_stats = getattr(raw, "mcts_stats", None)
        self.confidence: float = 0.0
        self.population_diversity: float = 0.0
        self.generations_run: int = getattr(mcts_stats, "iterations", 0) if mcts_stats else 0
        self.timings: dict = (
            {"mcts": getattr(mcts_stats, "time_used_ms", 0.0)} if mcts_stats else {}
        )
        raw_action_stats = getattr(raw, "action_stats", [])
        self.action_probs: List[ActionProb] = [
            ActionProb(
                action=ast.action,
                visit_count=ast.visit_count,
                probability=ast.visit_probability,
                win_rate=ast.win_rate,
                q_value=ast.q_value,
            )
            for ast in raw_action_stats
        ]
        self.mcts_stats = mcts_stats
        self.mcts_detailed_log = getattr(raw, "detailed_log", None)


# ── 单例引擎 ──────────────────────────────────────────────

class GameEngine:
    """游戏引擎单例 — 整场游戏只有一个 MCTSEngine + BayesianOpponentModel。

    设计原则:
    - MCTSEngine 在整个游戏生命周期内只创建一次，跨回合复用
    - BayesianOpponentModel 跨回合累积对手出牌证据
    - UCT 选择策略是 MCTSEngine 内部的无状态函数 (uct.select_child)
    - 每次 search() 调用会创建新的 _SearchContext (root node, worlds, TT)，
      但引擎实例本身（config 等）保持不变

    用法::

        engine = GameEngine(params)
        # 游戏开始时
        engine.on_game_start(opp_class="ROGUE")
        # 每回合
        result = engine.search(state)
        # 游戏结束
        engine.on_game_end()
    """

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        from analysis.search.mcts.engine import MCTSEngine
        from analysis.search.mcts.config import MCTSConfig
        from analysis.utils.bayesian_opponent import BayesianOpponentModel

        params = params or {}
        config = MCTSConfig(
            time_budget_ms=params.get("time_budget_ms", 8000.0),
            num_worlds=params.get("num_worlds", 7),
        )
        for key in ("uct_constant", "time_decay_gamma", "max_actions_per_turn"):
            if key in params:
                setattr(config, key, params[key])

        # ── 单例核心 ──
        self._mcts_engine: MCTSEngine = MCTSEngine(config=config)
        self._bayesian_model: BayesianOpponentModel = BayesianOpponentModel()
        self._config = config
        self._params = params

        # 游戏状态追踪
        self._opp_class: Optional[str] = None
        self._prev_opp_known: set = set()
        self._game_active: bool = False
        self._decision_count: int = 0

    @property
    def mcts_engine(self):
        """获取底层 MCTSEngine 单例。"""
        return self._mcts_engine

    @property
    def bayesian_model(self):
        """获取贝叶斯对手推断模型单例。"""
        return self._bayesian_model

    @property
    def config(self):
        """获取 MCTS 配置。"""
        return self._config

    def on_game_start(self, opp_class: Optional[str] = None) -> None:
        """游戏开始 — 初始化/重建贝叶斯模型。

        Args:
            opp_class: 对手职业（如 "ROGUE", "WARRIOR"），用于贝叶斯模型过滤。
        """
        from analysis.utils.bayesian_opponent import BayesianOpponentModel

        if opp_class:
            self._bayesian_model = BayesianOpponentModel(player_class=opp_class)
            self._opp_class = opp_class
            log.info(
                "GameEngine: 新游戏开始, 对手职业=%s, %d archetypes",
                opp_class, len(self._bayesian_model.decks),
            )
        else:
            self._bayesian_model = BayesianOpponentModel()
            self._opp_class = None
            log.info("GameEngine: 新游戏开始, 对手职业未知, %d archetypes",
                     len(self._bayesian_model.decks))

        self._prev_opp_known = set()
        self._game_active = True
        self._decision_count = 0

    def on_game_end(self) -> None:
        """游戏结束 — 重置状态但保留引擎实例。"""
        self._game_active = False
        log.info("GameEngine: 游戏结束, 共 %d 次决策", self._decision_count)

    def update_bayesian(self, opp_dbf_ids: set) -> List[dict]:
        """用新对手卡牌更新贝叶斯模型。

        Args:
            opp_dbf_ids: 当前已知的对手 dbfId 集合

        Returns:
            新增卡牌的推断结果列表 [{dbf, name, top_deck, top_prob}]
        """
        new_cards = opp_dbf_ids - self._prev_opp_known
        results = []
        for dbf in new_cards:
            self._bayesian_model.update(dbf)
            card_name = self._bayesian_model.card_name(dbf)
            top = self._bayesian_model.get_top_decks(1)
            entry = {
                "dbf": dbf,
                "name": card_name,
                "top_deck": top[0][1] if top else "?",
                "top_prob": top[0][2] if top else 0.0,
                "locked": self._bayesian_model.locked,
            }
            results.append(entry)
            log.debug(
                "贝叶斯更新: %s → %s@%.0f%%  %s",
                card_name, entry["top_deck"], entry["top_prob"] * 100,
                "[LOCKED]" if entry["locked"] else "",
            )
        self._prev_opp_known = opp_dbf_ids
        return results

    def search(self, state, time_budget_ms: Optional[float] = None,
               opp_playstyle: str = "unknown") -> Any:
        """执行 MCTS 搜索（使用单例引擎）。

        Args:
            state: 当前游戏状态
            time_budget_ms: 时间预算 (None=使用 config 默认值)
            opp_playstyle: 对手风格

        Returns:
            MCTS SearchResult
        """
        self._decision_count += 1
        return self._mcts_engine.search(
            state,
            time_budget_ms=time_budget_ms,
            bayesian_model=self._bayesian_model,
            opp_playstyle=opp_playstyle,
        )


# ── 兼容旧 API 的工厂函数 ────────────────────────────────

def _mcts_factory(params: Dict[str, Any]) -> Callable[[], Any]:
    """Return a callable that returns the singleton GameEngine.

    每次调用 factory() 返回同一个 GameEngine 实例。
    """
    engine = GameEngine(params)

    def factory() -> Any:
        return engine

    return factory


_ENGINES = {
    "mcts": _mcts_factory,
}


def create_engine(name: str, params: Dict[str, Any] | None = None) -> Callable[[], Any]:
    """Return a zero-arg factory that produces the GameEngine singleton.

    **重要**: 现在工厂返回的是同一个 GameEngine 实例，而非每次创建新引擎。
    MCTSEngine 和 BayesianOpponentModel 在整个游戏生命周期内只存在一份。

    Args:
        name: Engine name (only ``"mcts"`` supported; ``"rhea"`` silently redirected).
        params: Engine-specific parameters forwarded to the constructor.

    Returns:
        A callable ``() -> GameEngine`` whose ``search(state)`` returns a result
        that can be wrapped with :class:`UnifiedSearchResult`.
    """
    if name == "rhea":
        name = "mcts"
    factory_fn = _ENGINES.get(name)
    if factory_fn is None:
        raise ValueError(f"Unknown engine '{name}'. Only 'mcts' is supported.")
    return factory_fn(params or {})

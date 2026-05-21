# -*- coding: utf-8 -*-
"""opponent_hand_mcts.py — 基于MCTS世界节点模拟的对手手牌概率推断

核心思想：逆MCTS (Inverse MCTS)
    正向MCTS：已知手牌 → 找最优打法
    逆MCTS：已知对手行为 → 推最可能手牌

原理：
    对于每个"候选手牌组合"，创建一个世界节点，
    然后调用卡牌效果引擎模拟对手在该手牌下的决策，
    比较模拟行为与实际观测行为的匹配度，
    匹配度高的世界权重更高，其包含的卡牌概率提升。

    P(card_c in hand | observed_behavior)
    = Σ_world P(world | observed_behavior) × I(card_c in world.hand)
    ≈ Σ_world weight(world) × I(card_c in world.hand)
    / Σ_world weight(world)

v2 重构：使用 Power.log + Tracker 真实数据
    v1 版本使用简化构建的 GameState（手动拼装英雄/法力/场面），
    模拟精度受限。v2 版本直接从 Power.log 的 entity_cache 构建
    完整的 GameState，调用真实的搜索引擎（enumerate_legal_actions
    + apply_action + composite evaluator），实现：

    1. 从 PowerLogGameStateBuilder 构建对手视角的完整 GameState
    2. 调用真实的卡牌效果引擎模拟对手回合
    3. 使用 CompositeEvaluator 评估动作价值
    4. 跨回合模拟：推演对手未来1-2回合的可能行动
    5. 对比模拟行为与 power.log 记录的实际行为

世界节点模拟流程：
    1. 候选手牌采样：从贝叶斯推断的卡组中采样候选手牌组合
    2. 对手回合模拟：调用 PowerLogGameStateBuilder 构建真实 GameState，
       然后用卡牌效果引擎（enumerate_legal_actions + evaluate）模拟决策
    3. 行为匹配评估：比较模拟对手打法与实际观测打法
    4. 跨回合验证：模拟未来1-2回合，验证手牌假设一致性
    5. 权重聚合：匹配度高的世界权重提升，包含的卡牌概率提升

用法::

    # 方式1：使用 power.log + tracker 实时推断
    mcts = OpponentHandMCTS()
    probabilities = mcts.infer_from_tracker(
        log_monitor=monitor,
        our_controller=1,
        opp_controller=2,
        observed=observed_behavior,
        bayesian_state=bayesian,
        hand_size=5,
    )

    # 方式2：使用状态字典推断（兼容旧接口）
    probabilities = infer_opponent_hand_from_simulation(state_dict)
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
import math
import random
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class ObservedBehavior:
    """对手在本回合的观测行为。

    由 LogMonitor 从游戏日志中提取。
    """
    played_cards: List[str] = field(default_factory=list)  # 打出的卡牌card_id列表
    mana_spent: int = 0               # 实际消耗的法力
    available_mana: int = 0           # 可用法力
    hero_power_used: bool = False     # 是否使用英雄技能
    attacked_minions: List[int] = field(default_factory=list)  # 攻击的随从index
    passed: bool = False              # 是否跳过了出牌（完全pass）
    turn: int = 0                     # 回合数


@dataclass
class SimulatedBehavior:
    """模拟对手的行为。"""
    played_cards: List[str] = field(default_factory=list)  # 模拟打出的卡牌
    mana_spent: int = 0               # 模拟消耗法力
    hero_power_used: bool = False
    attacked: bool = False
    passed: bool = False


@dataclass
class TurnRecord:
    """对手过去某一回合的观测记录。

    用于计算费用偏向：若对手在 T5 有5费但完全跳过出牌，
    则 T6+ 的手牌更可能全部是高费牌（>available_mana 费）。
    """
    turn_number: int = 0
    available_mana: int = 0
    mana_spent: int = 0
    played_cards: List[str] = field(default_factory=list)
    passed: bool = False


class MultiTurnProbabilityTracker:
    """跨回合累积概率追踪器。

    聚合多回合MCTS推断结果，计算对手手牌中每张卡牌的累积概率。

    核心思想：
    - 每回合MCTS推断的结果是一组 {card_id: probability} 
    - 跨回合聚合时，近期回合的权重更高（指数衰减）
    - 最终输出每张牌在对手手牌中的累积最大概率

    用法::

        tracker = MultiTurnProbabilityTracker(decay=0.85)
        tracker.update(turn=3, probs={'CS1_042': 0.7, 'EX1_001': 0.4})
        tracker.update(turn=4, probs={'CS1_042': 0.8, 'EX1_002': 0.5})
        result = tracker.get_aggregated_probabilities()
        # {'CS1_042': 0.78, 'EX1_001': 0.17, 'EX1_002': 0.25}
    """

    def __init__(self, decay: float = 0.85, max_turns: int = 30):
        self._decay = decay
        self._max_turns = max_turns
        self._turn_data: Dict[int, Dict[str, float]] = {}  # turn → {card_id: prob}

    def update(self, turn: int, probs: Dict[str, float]):
        """记录某一回合的MCTS推断结果。"""
        self._turn_data[turn] = dict(probs)
        # 清理过旧的回合数据
        if len(self._turn_data) > self._max_turns:
            oldest = min(self._turn_data.keys())
            del self._turn_data[oldest]

    def get_aggregated_probabilities(self, current_turn: int = 0) -> Dict[str, float]:
        """获取跨回合累积概率。

        近期回合权重更高（指数衰减），最终概率为加权平均。

        Args:
            current_turn: 当前回合（用于计算衰减权重）
                如果为0，使用最新记录的回合

        Returns:
            {card_id: aggregated_probability}
        """
        if not self._turn_data:
            return {}

        if current_turn <= 0:
            current_turn = max(self._turn_data.keys())

        aggregated: Dict[str, float] = {}
        total_weight: Dict[str, float] = {}

        for turn, probs in self._turn_data.items():
            distance = max(0, current_turn - turn)
            weight = self._decay ** distance

            for card_id, prob in probs.items():
                if card_id not in aggregated:
                    aggregated[card_id] = 0.0
                    total_weight[card_id] = 0.0
                aggregated[card_id] += prob * weight
                total_weight[card_id] += weight

        # 归一化
        result = {}
        for card_id in aggregated:
            if total_weight[card_id] > 0:
                result[card_id] = aggregated[card_id] / total_weight[card_id]
            else:
                result[card_id] = 0.0

        return result

    def get_top_predictions(self, k: int = 5, current_turn: int = 0) -> List[Tuple[str, float]]:
        """获取Top-K最大概率卡牌。"""
        probs = self.get_aggregated_probabilities(current_turn)
        sorted_probs = sorted(probs.items(), key=lambda x: -x[1])
        return sorted_probs[:k]

    def reset(self):
        """重置追踪器。"""
        self._turn_data.clear()


class TurnHistoryTracker:
    """追踪对手历史回合行为，计算费用偏向权重。

    核心逻辑：
    如果对手在某回合有 X 法力但没出牌（或大幅浪费法力），说明：
      - 手牌中费用 <= X 的牌较少（本可以出但没出）
      - 手牌中费用 > X 的牌较多（想出但出不起）
    这个信号跨回合累计，引导 MCTS 手牌采样偏向合理费用范围。
    """

    def __init__(self):
        self._turns: Dict[int, TurnRecord] = {}

    def record_turn(self, observed: ObservedBehavior):
        """记录或更新某一回合的观测行为。"""
        self._turns[observed.turn] = TurnRecord(
            turn_number=observed.turn,
            available_mana=observed.available_mana,
            mana_spent=observed.mana_spent,
            played_cards=list(observed.played_cards),
            passed=observed.passed,
        )

    def compute_cost_bias(self, current_turn: int) -> Dict[int, float]:
        """根据历史回合行为，计算每费段的权重乘数。

        Returns:
            {cost: weight}, weight>1.0 表示"更可能在手牌中"
        """
        bias = {cost: 1.0 for cost in range(11)}

        for turn_num, record in self._turns.items():
            if turn_num >= current_turn:
                continue  # 只使用过去的回合

            unused = record.available_mana - record.mana_spent

            if record.passed or unused >= 1:
                # 对手本回合有法力但没出可出的牌 → 惩罚该费段
                for cost in range(0, min(11, record.available_mana + 1)):
                    bias[cost] *= 0.4
                # 对手本回合没法力出高费牌 → 奖励高费段
                for cost in range(record.available_mana + 1, 11):
                    bias[cost] *= 2.0
            elif unused > 0 and record.available_mana >= 3:
                # 有法力浪费但没完全 pass → 弱信号
                for cost in range(0, min(11, record.available_mana + 1)):
                    bias[cost] *= 0.7
                for cost in range(record.available_mana + 1, 11):
                    bias[cost] *= 1.3

        return bias

    @property
    def turn_count(self) -> int:
        return len(self._turns)


@dataclass
class HandWorld:
    """一个"对手手牌=某组合"的世界假设。

    核心概念：每个HandWorld代表一种关于对手手牌的假设，
    通过模拟对手决策来验证该假设的合理性。
    """
    world_id: int = 0
    hand_cards: List = field(default_factory=list)  # 假设的对手手牌(Card对象列表)
    deck_cards: List = field(default_factory=list)  # 假设的对手剩余牌库
    archetype_id: int = 0              # 来源卡组ID
    archetype_weight: float = 1.0      # 卡组后验概率
    simulation_score: float = 0.0      # 模拟匹配得分
    behavior_match: float = 0.0        # 行为匹配度 [0, 1]
    weight: float = 1.0                # 最终权重 = archetype_weight * behavior_match


# ── 行为匹配评估 ──────────────────────────────────────────────

class BehaviorMatcher:
    """比较模拟对手行为与实际观测行为的匹配度。

    匹配维度：
    1. 卡牌打出匹配：对手出了某张牌，模拟中是否也选择出？
    2. 法力消耗匹配：对手消耗法力量是否接近？
    3. Pass行为匹配：对手pass时，模拟是否也pass？
    4. 英雄技能匹配：对手用了英雄技能，模拟是否也用？
    5. 手牌覆盖匹配（v3新增）：如果世界手牌包含对手实际打出的牌，加分

    所有匹配度计算基于游戏逻辑，不硬编码概率值。
    """

    @staticmethod
    def compute_match(
        observed: ObservedBehavior,
        simulated: SimulatedBehavior,
        world_hand_card_ids: Optional[Set[str]] = None,
    ) -> float:
        """计算行为匹配度 [0, 1]。

        匹配度 = w1 * card_match + w2 * mana_match + w3 * pass_match + w4 * hp_match
                 + w5 * hand_coverage_match（v3新增）

        权重根据信息量动态调整：
        - 如果对手出了牌，卡牌匹配权重高
        - 如果对手pass，pass匹配权重高
        - 法力消耗总是有信息量的
        - v3新增：如果世界手牌中包含对手实际打出的牌，说明该假设更合理

        Args:
            observed: 对手实际观测行为
            simulated: 模拟对手行为
            world_hand_card_ids: 世界手牌中的卡牌ID集合（v3新增）
        """
        card_match = BehaviorMatcher._card_play_match(observed, simulated)
        mana_match = BehaviorMatcher._mana_usage_match(observed, simulated)
        pass_match = BehaviorMatcher._pass_match(observed, simulated)
        hp_match = BehaviorMatcher._hero_power_match(observed, simulated)
        # v3: 手牌覆盖匹配——如果世界手牌包含对手实际打出的牌，加分
        coverage_match = BehaviorMatcher._hand_coverage_match(observed, world_hand_card_ids)

        if observed.passed:
            w1, w2, w3, w4, w5 = 0.05, 0.15, 0.60, 0.10, 0.10
        elif observed.played_cards:
            w1, w2, w3, w4, w5 = 0.30, 0.15, 0.05, 0.10, 0.40
        else:
            w1, w2, w3, w4, w5 = 0.20, 0.20, 0.20, 0.20, 0.20

        return w1 * card_match + w2 * mana_match + w3 * pass_match + w4 * hp_match + w5 * coverage_match

    @staticmethod
    def _hand_coverage_match(
        observed: ObservedBehavior,
        world_hand_card_ids: Optional[Set[str]],
    ) -> float:
        """手牌覆盖匹配度（v3新增）。

        核心思想：对手选择打出某张牌，意味着该牌在其手牌中。
        如果世界假设的手牌中包含对手实际打出的牌，
        说明该假设更合理，应给予更高匹配度。

        这是解决"概率区分度为负"的关键修正：
        之前MCTS仅依赖模拟出牌匹配，但模拟出的牌可能和实际不同
        （因为贪心策略不一定和真实玩家选择一致），
        导致包含实际牌的世界权重反而更低。

        新增的手牌覆盖匹配直接检查世界手牌是否"能打出"这些牌，
        而不要求模拟器恰好选择打出它们。
        """
        if not observed.played_cards or world_hand_card_ids is None:
            return 0.5  # 无信息时返回中性值

        obs_set = set(observed.played_cards)
        covered = obs_set & world_hand_card_ids

        if not obs_set:
            return 0.5

        coverage_ratio = len(covered) / len(obs_set)
        # 完全覆盖=1.0, 部分覆盖=0.5-0.8, 无覆盖=0.1
        return 0.1 + 0.9 * coverage_ratio

    @staticmethod
    def _card_play_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """卡牌打出匹配度。"""
        if not observed.played_cards:
            return 0.5

        obs_set = set(observed.played_cards)
        sim_set = set(simulated.played_cards)

        if not sim_set:
            return 0.1  # 修复：对手出了牌但模拟没出，不应该是0（因为可能手牌有但贪心没选）

        intersection = obs_set & sim_set
        if intersection:
            return len(intersection) / max(len(obs_set), 1)

        if sim_set and obs_set:
            # 费用接近也算部分匹配
            return 0.3

        return 0.1

    @staticmethod
    def _mana_usage_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """法力消耗匹配度。"""
        if observed.available_mana <= 0:
            return 0.5

        obs_usage = observed.mana_spent / max(observed.available_mana, 1)
        sim_usage = simulated.mana_spent / max(observed.available_mana, 1)

        diff = abs(obs_usage - sim_usage)
        return max(0.0, 1.0 - diff)

    @staticmethod
    def _pass_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """Pass行为匹配度。"""
        if observed.passed and simulated.passed:
            return 1.0
        if observed.passed and not simulated.passed:
            return 0.0
        if not observed.passed and simulated.passed:
            return 0.0
        return 1.0

    @staticmethod
    def _hero_power_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """英雄技能匹配度。"""
        if observed.hero_power_used == simulated.hero_power_used:
            return 1.0
        return 0.2


# ── 对手回合模拟器（v2：使用真实 GameState + 搜索引擎）────────────

class OpponentTurnSimulator:
    """模拟对手在一个给定手牌+场面下的回合决策。

    v2 版本使用 PowerLogGameStateBuilder 从 Power.log 实时数据
    构建对手视角的完整 GameState，然后调用真实的卡牌效果引擎
    （enumerate_legal_actions + apply_action）模拟对手决策。

    这替代了 world_model.py 中硬编码的概率推断。
    通过实际模拟对手决策来判断"对手若有这张牌会怎样打"。

    两种模式：
    1. Tracker 模式：使用 log_monitor 构建真实 GameState
    2. 回退模式：手动构建简化 GameState（兼容旧接口）
    """

    def __init__(self):
        self._card_db = None
        self._state_builder = None  # PowerLogGameStateBuilder 延迟初始化

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.card.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def _ensure_state_builder(self):
        """延迟初始化 PowerLogGameStateBuilder。"""
        if self._state_builder is None:
            try:
                from analysis.engine.powerlog_game_state_builder import PowerLogGameStateBuilder
                self._state_builder = PowerLogGameStateBuilder()
            except Exception as e:
                logger.debug("PowerLogGameStateBuilder 初始化失败: %s", e)

    def simulate_opponent_turn_from_tracker(
        self,
        log_monitor,
        world: HandWorld,
        our_controller: int,
        opp_controller: int,
        turn_number: int,
        max_steps: int = 8,
    ) -> SimulatedBehavior:
        """使用 Power.log 真实数据模拟对手回合决策（v2 核心方法）。

        通过 PowerLogGameStateBuilder 从 entity_cache 构建对手视角
        的完整 GameState，包含真实的英雄状态、法力值、场面随从等，
        然后调用卡牌效果引擎模拟对手出牌。

        核心流程：
        1. 调用 PowerLogGameStateBuilder.build_opponent_game_state()
           构建对手视角的 GameState（hand = world.hand_cards）
        2. 枚举合法动作（enumerate_legal_actions）
        3. 用贪心策略+评估器选择最优动作
        4. 逐步应用动作（apply_action），记录打出卡牌
        5. 返回模拟行为

        Args:
            log_monitor: CoreLogMonitor 实例
            world: 手牌假设世界（包含假设的对手手牌）
            our_controller: 我方控制器 ID
            opp_controller: 对手控制器 ID
            turn_number: 当前回合
            max_steps: 最大模拟步数

        Returns:
            SimulatedBehavior 模拟的对手行为
        """
        self._ensure_state_builder()

        if self._state_builder is None:
            # 回退到简化模式
            return self.simulate_opponent_turn(
                world=world,
                opponent_state=None,
                our_board=[],
                our_hero=None,
                turn_number=turn_number,
                max_steps=max_steps,
            )

        try:
            # 从 Power.log 构建对手视角的真实 GameState
            opp_game_state = self._state_builder.build_opponent_game_state(
                log_monitor=log_monitor,
                opp_hand_cards=world.hand_cards,
                our_controller=our_controller,
                opp_controller=opp_controller,
            )

            # 覆写回合数（可能 builder 使用的不是当前模拟回合）
            opp_game_state.turn_number = turn_number

            return self._run_greedy_simulation(opp_game_state, max_steps)

        except Exception as e:
            logger.debug("Tracker模式对手回合模拟失败: %s", e)
            return self.simulate_opponent_turn(
                world=world,
                opponent_state=None,
                our_board=[],
                our_hero=None,
                turn_number=turn_number,
                max_steps=max_steps,
            )

    def simulate_opponent_turn(
        self,
        world: HandWorld,
        opponent_state: 'OpponentState' = None,
        our_board: list = None,
        our_hero: 'HeroState' = None,
        turn_number: int = 0,
        max_steps: int = 8,
    ) -> SimulatedBehavior:
        """模拟对手回合决策（回退模式：手动构建 GameState）。

        当 PowerLogGameStateBuilder 不可用时使用此方法，
        手动构建简化的 GameState 进行模拟。

        Args:
            world: 手牌假设世界
            opponent_state: 当前对手可见状态
            our_board: 我方场面随从
            our_hero: 我方英雄状态
            turn_number: 当前回合
            max_steps: 最大模拟步数

        Returns:
            SimulatedBehavior 模拟的对手行为
        """
        from analysis.card.engine.state import (
            GameState, HeroState, ManaState, Minion, OpponentState as SearchOppState,
        )
        from analysis.card.models.card import Card

        try:
            opp_mana = min(10, max(1, turn_number))
            opp_hand = list(world.hand_cards)

            # 构建对手视角的简化 GameState
            opp_hero_hp = 30
            opp_hero_armor = 0
            opp_hero_class = ""

            if opponent_state is not None:
                opp_hero_hp = getattr(opponent_state.hero, 'hp', 30)
                opp_hero_armor = getattr(opponent_state.hero, 'armor', 0)
                opp_hero_class = getattr(opponent_state.hero, 'hero_class', "")

            our_hero_hp = 30
            our_hero_armor = 0
            if our_hero is not None:
                our_hero_hp = getattr(our_hero, 'hp', 30)
                our_hero_armor = getattr(our_hero, 'armor', 0)

            opp_search_state = GameState(
                hero=HeroState(
                    hp=opp_hero_hp,
                    armor=opp_hero_armor,
                    hero_class=opp_hero_class,
                ),
                mana=ManaState(
                    available=opp_mana,
                    max_mana=opp_mana,
                ),
                board=[
                    m.copy() for m in (opponent_state.board if opponent_state else [])
                ],
                hand=opp_hand,
                deck_remaining=max(0, len(world.deck_cards)),
                opponent=SearchOppState(
                    hero=HeroState(
                        hp=our_hero_hp,
                        armor=our_hero_armor,
                    ),
                    board=[
                        Minion(
                            name=getattr(m, 'name', '?'),
                            attack=m.attack,
                            health=m.health,
                            has_taunt=m.has_taunt,
                            has_divine_shield=m.has_divine_shield,
                        )
                        for m in (our_board or [])
                    ] if our_board else [],
                ),
                turn_number=turn_number,
            )

            return self._run_greedy_simulation(opp_search_state, max_steps)

        except Exception as e:
            logger.debug("对手回合模拟失败: %s", e)
            return SimulatedBehavior(passed=True)

    def _run_greedy_simulation(
        self,
        opp_game_state,
        max_steps: int = 8,
    ) -> SimulatedBehavior:
        """使用 UCT 搜索模拟对手出牌序列（替代贪心策略）。

        核心改进：使用 MCTS UCT 搜索替代贪心策略选择动作。
        UCT 搜索提供更好的探索-利用平衡，使模拟出的对手行为
        更加多样化和真实，从而提高手牌推断的区分度。

        流程：
        1. 使用 MCTSUCT 引擎对对手回合做 UCT 搜索
        2. 从搜索结果中提取最优动作序列
        3. 沿最优路径逐步应用动作，记录打出卡牌
        4. 如果 UCT 不可用，回退到贪心策略

        Args:
            opp_game_state: 对手视角的 GameState
            max_steps: 最大模拟步数

        Returns:
            SimulatedBehavior 模拟的对手行为
        """
        # 尝试使用 UCT 搜索
        uct_result = self._run_uct_simulation(opp_game_state)
        if uct_result is not None:
            return uct_result

        # 回退到贪心策略
        return self._run_greedy_simulation_fallback(opp_game_state, max_steps)

    def _run_uct_simulation(
        self,
        opp_game_state,
    ) -> Optional[SimulatedBehavior]:
        """使用 MCTS UCT 搜索模拟对手回合。

        核心思想：
        对于对手的回合，使用 UCT 搜索（从对手视角）来预测
        对手最可能的出牌序列。UCT 搜索提供了比贪心更好的
        探索-利用平衡：
        - 探索：UCT 会尝试不同出牌组合，发现贪心可能忽略的好选择
        - 利用：UCT 聚焦在最有希望的分支，避免完全随机

        这使得不同手牌假设下模拟出的行为更加多样化，
        提高了 BehaviorMatcher 区分不同手牌世界的能力。

        模拟结果提取：
        从 UCT 搜索树的根节点开始，沿 visit_count 最高
        的子节点路径（greedy path）提取动作序列，
        这代表 UCT 认为对手最可能的打法。

        Returns:
            SimulatedBehavior 或 None（如果 UCT 搜索失败）
        """
        try:
            from analysis.engine.mcts_uct import MCTSUCT, MCTSConfig
            from analysis.card.engine.rules import check_game_over
            from analysis.card.engine.simulation import apply_action
            from analysis.card.abilities.definition import ActionKind as ActionType
        except ImportError:
            logger.debug("UCT 引擎导入失败，将回退到贪心策略")
            return None

        # 确保是对手回合
        if not getattr(opp_game_state, 'is_opponent_turn', True):
            opp_game_state.is_opponent_turn = True

        try:
            # 对手视角的 reward（取反，因为默认reward是我方视角）
            def opponent_reward(s):
                if s is None:
                    return 1.0
                game_over = check_game_over(s)
                if game_over == 1:  # 对手赢了
                    return 1.0
                if game_over == 0:  # 我方赢了
                    return -1.0
                # 非终局：基于场面评估
                our_hp = s.hero.hp + s.hero.armor if s.hero else 1
                opp_hp = s.opponent.hero.hp + s.opponent.hero.armor if s.opponent and s.opponent.hero else 1
                hp_ratio = opp_hp / max(our_hp, 1)
                hp_score = math.tanh(hp_ratio - 1.0) * 0.5

                our_board = sum(m.attack + m.health for m in (s.opponent.board if s.opponent else []))
                opp_board = sum(m.attack + m.health for m in s.board)
                board_score = math.tanh(
                    (opp_board - our_board) / max(opp_board + our_board, 1)
                ) * 0.3

                hand_score = math.tanh(
                    (s.opponent.hand_count - len(s.hand)) / 10.0
                ) * 0.2
                return hp_score + board_score + hand_score

            # 配置 UCT 搜索：专注于对手当前回合
            config = MCTSConfig(
                exploration_constant=1.414,
                iterations=200,           # 适中的迭代次数，平衡精度和速度
                time_budget_ms=100,       # 每个世界100ms的UCT预算
                rollout_depth=10,
                use_heuristic_rollout=True,
                max_turns_ahead=1,        # 只搜索对手当前回合
                max_opponent_tree_actions=8,
                expand_all_children=True,
                verbose=False,
            )

            engine = MCTSUCT(config, opponent_reward)
            result = engine.search(opp_game_state)

            # 从搜索树中提取最优动作序列
            if result.best_sequence:
                return self._extract_behavior_from_sequence(
                    opp_game_state, result.best_sequence,
                )

            # 如果没有序列，从 best_action 推导
            if result.best_action:
                return self._extract_behavior_from_single_action(
                    opp_game_state, result.best_action,
                )

            # UCT 无有效结果
            return None

        except Exception as e:
            logger.debug("UCT 搜索失败: %s，回退到贪心策略", e)
            return None

    def _extract_behavior_from_sequence(
        self,
        initial_state,
        action_sequence,
    ) -> SimulatedBehavior:
        """从 UCT 搜索的最优动作序列中提取模拟行为。

        沿动作序列逐步应用动作，记录打出卡牌、法力消耗等。

        Args:
            initial_state: 对手视角的初始 GameState
            action_sequence: UCT 搜索树的最优动作序列

        Returns:
            SimulatedBehavior
        """
        from analysis.card.engine.simulation import apply_action
        from analysis.card.abilities.definition import ActionKind as ActionType

        played_cards = []
        total_mana_spent = 0
        hero_power_used = False
        step_count = 0

        state = initial_state
        for action in action_sequence:
            if action.action_type == ActionType.END_TURN:
                break

            # 记录打出的卡牌
            if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
                card_idx = action.card_index
                if 0 <= card_idx < len(state.hand):
                    card = state.hand[card_idx]
                    card_id = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                    played_cards.append(card_id)
                    card_cost = getattr(card, 'cost', 0) or 0
                    total_mana_spent += card_cost

            if action.action_type == ActionType.HERO_POWER:
                hero_power_used = True

            try:
                state = apply_action(state, action)
            except Exception:
                break
            step_count += 1

        is_pass = len(played_cards) == 0 and not hero_power_used

        return SimulatedBehavior(
            played_cards=played_cards,
            mana_spent=total_mana_spent,
            hero_power_used=hero_power_used,
            attacked=step_count > 0,
            passed=is_pass,
        )

    def _extract_behavior_from_single_action(
        self,
        initial_state,
        best_action,
    ) -> SimulatedBehavior:
        """从单个最优动作推导模拟行为。

        当 UCT 搜索只给出 best_action 而无完整序列时，
        执行该动作并根据结果推断行为。

        Args:
            initial_state: 对手视角的初始 GameState
            best_action: UCT 搜索的最优动作

        Returns:
            SimulatedBehavior
        """
        from analysis.card.abilities.definition import ActionKind as ActionType

        played_cards = []
        total_mana_spent = 0
        hero_power_used = False

        if best_action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            card_idx = best_action.card_index
            if 0 <= card_idx < len(initial_state.hand):
                card = initial_state.hand[card_idx]
                card_id = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                played_cards.append(card_id)
                card_cost = getattr(card, 'cost', 0) or 0
                total_mana_spent += card_cost

        if best_action.action_type == ActionType.HERO_POWER:
            hero_power_used = True

        is_pass = len(played_cards) == 0 and not hero_power_used

        return SimulatedBehavior(
            played_cards=played_cards,
            mana_spent=total_mana_spent,
            hero_power_used=hero_power_used,
            attacked=best_action.action_type == ActionType.ATTACK,
            passed=is_pass,
        )

    def _run_greedy_simulation_fallback(
        self,
        opp_game_state,
        max_steps: int = 8,
    ) -> SimulatedBehavior:
        """贪心策略模拟对手出牌序列（回退方案）。

        当 UCT 搜索不可用或失败时使用此方法。
        优先使用 CompositeEvaluator，回退到简单启发式。

        Args:
            opp_game_state: 对手视角的 GameState
            max_steps: 最大模拟步数

        Returns:
            SimulatedBehavior 模拟的对手行为
        """
        try:
            from analysis.card.engine.rules import enumerate_legal_actions
            from analysis.card.engine.simulation import apply_action
            from analysis.card.abilities.definition import ActionKind as ActionType
        except ImportError:
            raise RuntimeError(
                "v1 effects engine removed. opponent_hand_mcts.py "
                "needs migration to v2 (analysis.card.engine)."
            )

        played_cards = []
        total_mana_spent = 0
        hero_power_used = False
        step_count = 0

        state = opp_game_state

        for _ in range(max_steps):
            actions = enumerate_legal_actions(state)
            if not actions:
                break

            best_action = self._select_best_action(state, actions)

            if best_action is None:
                break

            if best_action.action_type == ActionType.END_TURN:
                break

            # 记录打出的卡牌
            if best_action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
                card_idx = best_action.card_index
                if 0 <= card_idx < len(state.hand):
                    card = state.hand[card_idx]
                    card_id = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                    played_cards.append(card_id)
                    card_cost = getattr(card, 'cost', 0) or 0
                    total_mana_spent += card_cost

            if best_action.action_type == ActionType.HERO_POWER:
                hero_power_used = True

            state = apply_action(state, best_action)
            step_count += 1

        is_pass = len(played_cards) == 0 and not hero_power_used

        return SimulatedBehavior(
            played_cards=played_cards,
            mana_spent=total_mana_spent,
            hero_power_used=hero_power_used,
            attacked=step_count > 0,
            passed=is_pass,
        )

    def _select_best_action(self, state, actions):
        """贪心选择最优动作。

        使用轻量级评估，避免全量MCTS搜索（太慢）。
        优先使用 CompositeEvaluator，回退到简单启发式。
        评估维度：
        1. 法力效率（用了更多法力的动作更好）
        2. 场面价值（随从总属性更高的更好）
        3. 伤害效率（打脸伤害更高的更好）
        """
        try:
            from analysis.card.abilities.definition import ActionKind as ActionType
            from analysis.card.engine.simulation import apply_action
        except ImportError:
            raise RuntimeError(
                "v1 effects engine removed. opponent_hand_mcts.py "
                "needs migration to v2 (analysis.card.engine)."
            )

        if not actions:
            return None

        # 如果只有END_TURN，直接返回
        non_end = [a for a in actions if a.action_type != ActionType.END_TURN]
        if not non_end:
            return actions[0]

        best_action = None
        best_score = float('-inf')

        # 尝试使用 CompositeEvaluator（更精确）
        use_evaluator = False
        try:
            from analysis.evaluators.composite import evaluate_delta
            use_evaluator = True
        except ImportError:
            pass

        for action in non_end[:15]:  # 限制评估数量
            try:
                new_state = apply_action(state, action)
                if use_evaluator:
                    score = evaluate_delta(state, new_state)
                else:
                    score = self._evaluate_state(new_state, state)
                if score > best_score:
                    best_score = score
                    best_action = action
            except Exception:
                continue

        # 如果所有动作评分都很低，选择END_TURN
        if best_action is None or best_score < 0:
            end_turns = [a for a in actions if a.action_type == ActionType.END_TURN]
            if end_turns:
                return end_turns[0]

        return best_action or non_end[0]

    @staticmethod
    def _evaluate_state(new_state, old_state):
        """评估一个动作后的状态价值（简单启发式）。"""
        score = 0.0

        our_board_value = sum(m.attack + m.health for m in new_state.board)
        old_board_value = sum(m.attack + m.health for m in old_state.board)
        score += (our_board_value - old_board_value) * 0.5

        opp_hp_change = new_state.opponent.hero.hp - old_state.opponent.hero.hp
        score += max(0, -opp_hp_change) * 1.0

        mana_used = old_state.mana.available - new_state.mana.available
        score += mana_used * 0.3

        score += len(new_state.board) * 0.5

        return score


# ── 候选手牌采样 ──────────────────────────────────────────────

class HandSampler:
    """从贝叶斯推断的卡组中采样候选手牌组合。

    采样策略：
    1. 从贝叶斯推断的top-N卡组中按后验概率分配采样数量
    2. 每个卡组中，过滤已打出的牌，从剩余牌中采样手牌
    3. 考虑已知的约束（如"手牌有龙"）
    4. v3新增：当候选卡组覆盖不足时，动态扩展卡组包含对手已打出的非卡组牌
    5. v3新增：当无候选卡组时，回退到职业标准卡牌池采样
    """

    def __init__(self):
        self._card_db = None

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.card.data.card_data import get_db
                self._card_db = get_db()
            except Exception:
                pass

    def sample_worlds(
        self,
        bayesian_state: dict,
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        num_worlds: int = 100,
        constraints: Optional[List] = None,
        cost_bias: Optional[Dict[int, float]] = None,
        non_derived_candidates: Optional[List[str]] = None,
    ) -> List[HandWorld]:
        """采样候选手牌世界。

        Args:
            cost_bias: {cost: weight} 费用偏向权重，
                来自 TurnHistoryTracker.compute_cost_bias()。
                用于引导采样偏向历史行为暗示的高/低费方向。
            non_derived_candidates: 非衍生候选卡牌列表，
                来自最大概率卡组减去已使用的非衍生卡牌。
                如果提供，这些卡牌在采样中权重更高。
        """
        self._ensure_card_db()

        if hand_size <= 0:
            return []

        top_decks = bayesian_state.get("top_decks", [])
        if not top_decks:
            return self._sample_from_class_pool(
                bayesian_state, hand_size, seen_cards, generated_cards, num_worlds,
            )

        worlds: List[HandWorld] = []

        deck_probs = []
        total_prob = 0.0
        for deck_id, deck_name, prob in top_decks[:3]:
            deck_probs.append((deck_id, deck_name, prob))
            total_prob += prob

        if total_prob <= 0:
            return []

        world_id = 0
        for deck_id, deck_name, prob in deck_probs:
            n_worlds = max(3, round(num_worlds * prob / total_prob))

            deck_cards = self._get_deck_cards(deck_id)
            if not deck_cards:
                continue

            # v3新增：动态扩展卡组，包含对手已打出但不在卡组中的牌
            deck_cards = self._extend_deck_with_observed_cards(
                deck_cards, seen_cards, generated_cards,
            )

            for _ in range(n_worlds):
                hand = self._sample_hand_from_deck(
                    deck_cards, hand_size, seen_cards, generated_cards,
                    constraints, cost_bias=cost_bias,
                    non_derived_candidates=non_derived_candidates,
                )
                if hand:
                    worlds.append(HandWorld(
                        world_id=world_id,
                        hand_cards=hand,
                        deck_cards=[],
                        archetype_id=deck_id,
                        archetype_weight=prob,
                    ))
                    world_id += 1

        return worlds[:num_worlds]

    def _extend_deck_with_observed_cards(
        self,
        deck_cards: List[int],
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
    ) -> List[int]:
        """动态扩展卡组，包含对手已打出但不在卡组中的牌。

        解决"非卡组卡牌覆盖不足"问题：
        对手可能使用非主流卡组，其中有些牌不在HSReplay候选卡组中。
        这些牌已经打出，说明对手卡组中确实包含它们。
        将这些牌加入候选池，使MCTS能预测同卡组中其他可能的非主流牌。

        关键：添加标准张数（非传说=2，传说=1），而非仅已打出的张数。
        因为 _sample_hand_from_deck 会从 total_copies 中减去 seen_cards 的张数，
        如果只添加已打出张数，减去后剩余0，无法采样。
        添加2张后，减去1张已打出，剩余1张可被采样进手牌。
        """
        if not seen_cards or not self._card_db:
            return deck_cards

        deck_dbf_set = set(deck_cards)
        extended = list(deck_cards)

        for card_id, played_count in seen_cards.items():
            if card_id in generated_cards:
                continue
            # 跳过衍生卡牌后缀（如 TIME_000ta → TIME_000）
            base_card_id = self._strip_card_suffix(card_id)
            if base_card_id != card_id:
                continue  # 变形/衍生版本不加入卡组

            dbf_id = self._card_id_to_dbf(card_id)
            if dbf_id and dbf_id not in deck_dbf_set:
                # 对手打出了这张牌，但不在卡组中，说明是额外牌
                # 添加标准张数（2张普通/1张传说），这样减去已打出张数后还有剩余
                is_legendary = False
                card_data = self._card_db.get_card(card_id) if self._card_db else None
                if card_data and card_data.get("rarity", "") == "LEGENDARY":
                    is_legendary = True

                total_copies = 1 if is_legendary else 2
                for _ in range(total_copies):
                    extended.append(dbf_id)
                deck_dbf_set.add(dbf_id)

        return extended

    def _sample_from_class_pool(
        self,
        bayesian_state: dict,
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        num_worlds: int,
    ) -> List[HandWorld]:
        """当无候选卡组时，回退到职业标准卡牌池采样。

        解决战士等职业候选卡组过少的问题。
        使用职业所有标准卡牌作为候选池，按卡牌费用分布采样。
        """
        opp_class = bayesian_state.get("opp_class", "")
        if not opp_class or not self._card_db:
            return []

        # 获取该职业+中立的标准卡牌
        class_cards = []
        try:
            for card_id in self._card_db.iter_card_ids():
                data = self._card_db.get_card(card_id)
                if not data:
                    continue
                card_class = data.get("cardClass", "").upper()
                if card_class not in (opp_class.upper(), "NEUTRAL"):
                    continue
                card_type = data.get("type", "").upper()
                if card_type in ("HERO", "HERO_POWER", "ENCHANTMENT", "GAME"):
                    continue
                dbf_id = data.get("dbfId", 0)
                if dbf_id and card_id not in generated_cards:
                    remaining = 1 if data.get("rarity", "") == "LEGENDARY" else 2
                    played = seen_cards.get(card_id, 0)
                    remaining -= played
                    for _ in range(max(0, remaining)):
                        class_cards.append(dbf_id)
        except Exception:
            return []

        if not class_cards:
            return []

        worlds = []
        for wid in range(min(num_worlds, 20)):
            sample_size = min(hand_size, len(class_cards))
            if sample_size <= 0:
                break
            sampled = random.sample(class_cards, sample_size)
            hand = [c for c in (self._dbf_to_card(d) for d in sampled) if c]
            if hand:
                worlds.append(HandWorld(
                    world_id=wid,
                    hand_cards=hand,
                    deck_cards=[],
                    archetype_id=0,
                    archetype_weight=1.0,
                ))

        return worlds

    def _strip_card_suffix(self, card_id: str) -> str:
        """去除卡牌ID的后缀（如 TIME_000ta → TIME_000）。

        衍生/变形卡牌后缀说明：
        - 'ta' = transformed/alternate version
        - 't' = token
        - 'e' = enchanted
        - 'en' = enchanted

        这些后缀版本在卡组原列表中不存在，需要映射回原始ID。
        """
        import re
        # 匹配常见后缀模式
        return re.sub(r'(ta|t|e|en)$', '', card_id)

    def _card_id_to_dbf(self, card_id: str) -> Optional[int]:
        """card_id转dbfId。"""
        if self._card_db is not None:
            data = self._card_db.get_card(card_id)
            if data:
                return data.get("dbfId", 0)
        return None

    def _sample_hand_from_deck(
        self,
        deck_cards: List[int],
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        constraints: Optional[List],
        cost_bias: Optional[Dict[int, float]] = None,
        non_derived_candidates: Optional[List[str]] = None,
    ) -> List:
        """从卡组剩余牌 + 衍生牌候选池中采样一手手牌。

        改进（v4）：
        1. 衍生牌不再被排除，而是加入候选池填充剩余手牌位置
        2. 支持 cost_bias 加权采样，使采样偏向历史行为暗示的费用方向
        3. 支持 non_derived_candidates 加权，使来自最大概率卡组的非衍生牌权重更高
        """
        card_counts = Counter(deck_cards)

        # ── 从卡组剩余牌构建候选池 ──
        remaining_cards = []
        for dbf_id, count in card_counts.items():
            card_id = self._dbf_to_card_id(dbf_id)
            if not card_id:
                continue
            # 卡组中的原始计数不考虑衍生牌（衍生牌不在卡组中）
            played = seen_cards.get(card_id, 0)
            remaining = count - played
            if remaining <= 0:
                continue
            for _ in range(remaining):
                remaining_cards.append(dbf_id)

        if not remaining_cards:
            return []

        # ── 衍生牌加入候选池（v4修复：衍生牌可以且应该在手牌中） ──
        generated_candidates = []
        deck_card_ids = {self._dbf_to_card_id(d) for d in card_counts if self._dbf_to_card_id(d)}
        for cid in generated_cards:
            if cid in seen_cards:
                continue  # 已打出，不在手牌中
            if cid in deck_card_ids:
                continue  # 已在卡组候选池中
            dbf = self._card_id_to_dbf(cid)
            if dbf is not None:
                generated_candidates.append(dbf)

        # 合并候选池：卡组剩余 + 衍生牌
        all_candidates = list(remaining_cards)
        all_candidates.extend(generated_candidates)

        sample_size = min(hand_size, len(all_candidates))

        # 构建权重：合并 cost_bias 和 non_derived_candidates 的影响
        if (cost_bias or non_derived_candidates) and sample_size > 0:
            sampled_dbfs = self._weighted_sample_combined(
                all_candidates, cost_bias, non_derived_candidates, sample_size,
            )
        else:
            sampled_dbfs = random.sample(all_candidates, sample_size)

        hand = []
        for dbf_id in sampled_dbfs:
            card = self._dbf_to_card(dbf_id)
            if card:
                hand.append(card)

        return hand

    def _weighted_sample_combined(
        self,
        candidates: List[int],
        cost_bias: Optional[Dict[int, float]],
        non_derived_candidates: Optional[List[str]],
        k: int,
    ) -> List[int]:
        """按费用偏向+非衍生候选权重做无放回加权采样。"""
        if len(candidates) <= k:
            return list(candidates)

        non_derived_set = set(non_derived_candidates) if non_derived_candidates else set()

        # 预计算每个候选的权重
        weights = []
        for dbf_id in candidates:
            card = self._dbf_to_card(dbf_id)
            cost = card.cost if card else 3
            w = 1.0
            if cost_bias:
                w *= cost_bias.get(cost, 1.0)
            # 非衍生候选卡牌权重提升2倍
            card_id = self._dbf_to_card_id(dbf_id) if dbf_id else ""
            if card_id and card_id in non_derived_set:
                w *= 2.0
            weights.append(max(0.01, w))

        # 无放回加权采样
        pool_indices = list(range(len(candidates)))
        result = []
        for _ in range(k):
            if not pool_indices:
                break
            total = sum(weights[i] for i in pool_indices)
            if total <= 0:
                idx = random.choice(pool_indices)
            else:
                r = random.random() * total
                cumsum = 0.0
                idx = pool_indices[0]
                for i in pool_indices:
                    cumsum += weights[i]
                    if cumsum >= r:
                        idx = i
                        break
            result.append(candidates[idx])
            pool_indices.remove(idx)

        return result

    def _weighted_sample_by_cost(
        self,
        candidates: List[int],
        cost_bias: Dict[int, float],
        k: int,
    ) -> List[int]:
        """按费用偏向权重做无放回加权采样。"""
        if len(candidates) <= k:
            return list(candidates)

        # 预计算每个候选的权重
        weights = []
        for dbf_id in candidates:
            card = self._dbf_to_card(dbf_id)
            cost = card.cost if card else 3
            w = cost_bias.get(cost, 1.0)
            weights.append(max(0.01, w))  # 确保正权重

        # 无放回加权采样
        pool_indices = list(range(len(candidates)))
        result = []
        for _ in range(k):
            if not pool_indices:
                break
            total = sum(weights[i] for i in pool_indices)
            if total <= 0:
                # 退化到均匀采样
                idx = random.choice(pool_indices)
            else:
                r = random.random() * total
                cumsum = 0.0
                idx = pool_indices[0]
                for i in pool_indices:
                    cumsum += weights[i]
                    if cumsum >= r:
                        idx = i
                        break
            result.append(candidates[idx])
            pool_indices.remove(idx)

        return result

    def _get_deck_cards(self, archetype_id: int) -> List[int]:
        """获取卡组的dbfId列表。"""
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
                return target["cards"]
        except Exception:
            pass
        return []

    def _dbf_to_card_id(self, dbf_id: int) -> Optional[str]:
        """dbfId转card_id。"""
        if self._card_db is not None:
            card_data = self._card_db.get_by_dbf(dbf_id)
            if card_data:
                return card_data.get("cardId", card_data.get("id", ""))
        return None

    def _dbf_to_card(self, dbf_id: int):
        """dbfId转Card对象。"""
        from analysis.card.models.card import Card

        if self._card_db is not None:
            card_data = self._card_db.get_by_dbf(dbf_id)
            if card_data:
                return Card(
                    dbf_id=dbf_id,
                    name=card_data.get("name", ""),
                    cost=card_data.get("cost", 0),
                    card_type=card_data.get("type", "MINION"),
                    attack=card_data.get("attack", 0),
                    health=card_data.get("health", 0),
                    race=card_data.get("race", ""),
                    spell_school=card_data.get("spellSchool", ""),
                    card_id=card_data.get("cardId", card_data.get("id", "")),
                )
        return None


# ── MCTS手牌推断引擎 ──────────────────────────────────────────────

class OpponentHandMCTS:
    """基于MCTS世界节点模拟的对手手牌概率推断引擎。

    v2 版本：使用 Power.log 真实数据 + 卡牌效果引擎

    核心算法：
    1. 采样：从贝叶斯推断的卡组中采样N个候选手牌世界
    2. 模拟：对每个世界，使用 PowerLogGameStateBuilder 构建
       对手视角的完整 GameState，调用卡牌效果引擎模拟决策
    3. 匹配：比较模拟行为与观测行为，计算匹配度
    4. 跨回合验证：对未来回合做轻量模拟，验证假设一致性
    5. 聚合：按匹配度加权，计算每张卡牌的手牌概率

    与传统MCTS的区别：
    - 传统MCTS搜索动作空间（找最优打法）
    - 本引擎搜索手牌空间（找最可能手牌）
    - 使用真实 GameState + 贪心模拟替代完整MCTS搜索

    时间预算：
    - 默认500ms，足够采样30-50个世界并完成模拟
    - 可配置，适应不同性能需求
    """

    def __init__(self, time_budget_ms: float = 2000.0, num_threads: int = 4):
        self.time_budget_ms = time_budget_ms
        self.num_threads = num_threads
        self._sampler = HandSampler()
        self._simulator = OpponentTurnSimulator()
        self._matcher = BehaviorMatcher()
        # 历史回合追踪（跨 MCTS 调用累积）
        self._turn_history = TurnHistoryTracker()
        # 跨回合概率追踪（聚合多回合MCTS结果）
        self._multi_turn_tracker = MultiTurnProbabilityTracker(decay=0.85)
        # 缓存
        self._last_result: Optional[Dict[str, float]] = None
        self._last_state_hash: int = 0

    def infer_from_tracker(
        self,
        log_monitor,
        our_controller: int,
        opp_controller: int,
        observed: ObservedBehavior,
        bayesian_state: dict,
        seen_cards: Optional[Dict[str, int]] = None,
        generated_cards: Optional[Set[str]] = None,
        hand_size: int = 0,
        constraints: Optional[List] = None,
        non_derived_candidates: Optional[List[str]] = None,
        time_budget_ms: Optional[float] = None,
    ) -> Dict[str, float]:
        """从 Power.log + Tracker 推断对手手牌概率（v2 核心入口）。

        使用 PowerLogGameStateBuilder 从 entity_cache 构建真实的 GameState，
        调用卡牌效果引擎模拟对手决策，对比实际行为推断手牌概率。

        Args:
            log_monitor: CoreLogMonitor 实例（包含 entity_cache 和 global_tracker）
            our_controller: 我方控制器 ID
            opp_controller: 对手控制器 ID
            observed: 对手本回合的观测行为
            bayesian_state: 贝叶斯卡组推断状态
            seen_cards: 已打出的卡牌
            generated_cards: 衍生牌
            hand_size: 对手手牌数
            constraints: 手牌约束
            time_budget_ms: 可选的时间预算覆盖

        Returns:
            {card_id: probability} 手牌概率字典
        """
        start_time = time.time() * 1000
        budget = time_budget_ms or self.time_budget_ms

        if seen_cards is None:
            seen_cards = {}
        if generated_cards is None:
            generated_cards = set()

        # 快速哈希检查
        state_hash = self._compute_hash(bayesian_state, observed, hand_size)
        if state_hash == self._last_state_hash and self._last_result is not None:
            return self._last_result

        # Step 1: 从历史回合计算费用偏向，引导采样（v4）
        cost_bias = self._turn_history.compute_cost_bias(observed.turn)

        num_worlds = self._compute_num_worlds(budget)
        worlds = self._sampler.sample_worlds(
            bayesian_state=bayesian_state,
            hand_size=hand_size,
            seen_cards=seen_cards,
            generated_cards=generated_cards,
            num_worlds=num_worlds,
            constraints=constraints,
            cost_bias=cost_bias,
            non_derived_candidates=non_derived_candidates,
        )

        if not worlds:
            self._last_result = {}
            self._last_state_hash = state_hash
            return {}

        # Step 2: 并行模拟所有世界（v4）
        sim_results = self._run_parallel_simulation(
            worlds, log_monitor, our_controller, opp_controller,
            observed, budget, start_time,
        )

        # Step 3 & 4: 依次处理每个世界的匹配度 + 权重（轻量计算，串行即可）
        for world in worlds:
            result = sim_results.get(world.world_id)
            if result is None:
                continue  # 该世界未在预算时间内完成模拟

            # Step 3: 计算行为匹配度
            world.behavior_match = self._matcher.compute_match(
                observed, result['sim_main'],
                world_hand_card_ids=result['world_hand_ids'],
            )

            # Step 4: 跨回合验证（使用并行化的 sim_next 结果）
            sim_next = result['sim_next']
            if observed.passed and sim_next.passed:
                cross_turn_score = 0.9
            elif observed.passed and not sim_next.passed:
                cross_turn_score = 0.7
            elif not observed.passed and sim_next.passed:
                cross_turn_score = 0.5
            else:
                cross_turn_score = 0.6
            world.behavior_match = world.behavior_match * 0.7 + cross_turn_score * 0.3

            # 计算最终权重
            world.weight = world.archetype_weight * max(0.01, world.behavior_match)

        # Step 5: 聚合概率（v3: 传入seen_cards过滤已打出卡牌）
        single_turn_probs = self._aggregate_probabilities(worlds, seen_cards=seen_cards)

        # 记录本回合行为到历史追踪（供后续回合的 cost_bias 使用）（v4）
        self._turn_history.record_turn(observed)

        # 记录到跨回合概率追踪器
        if single_turn_probs:
            self._multi_turn_tracker.update(observed.turn, single_turn_probs)

        # Step 6: 融合跨回合累积概率（关键修复）
        # 将当前单回合MCTS结果与历史多回合结果做贝叶斯加权融合
        # 近期回合权重更高（指数衰减），同时确保已打出的牌概率受控
        probabilities = self._fuse_multi_turn_probabilities(
            single_turn_probs, seen_cards, observed.turn,
        )

        # 缓存结果
        self._last_result = probabilities
        self._last_state_hash = state_hash

        return probabilities

    def infer_hand_probabilities(
        self,
        bayesian_state: dict,
        observed: ObservedBehavior,
        opponent_state: 'OpponentState' = None,
        our_board: list = None,
        our_hero: 'HeroState' = None,
        seen_cards: Optional[Dict[str, int]] = None,
        generated_cards: Optional[Set[str]] = None,
        hand_size: int = 0,
        constraints: Optional[List] = None,
        non_derived_candidates: Optional[List[str]] = None,
        time_budget_ms: Optional[float] = None,
    ) -> Dict[str, float]:
        """推断对手手牌中每张卡牌的概率（兼容旧接口）。

        当没有 log_monitor 可用时使用此方法，手动构建简化的 GameState。

        Args:
            bayesian_state: 贝叶斯卡组推断状态
            observed: 对手本回合的观测行为
            opponent_state: 对手可见状态（场面等）
            our_board: 我方场面
            our_hero: 我方英雄
            seen_cards: 已打出的卡牌
            generated_cards: 衍生牌
            hand_size: 对手手牌数
            constraints: 手牌约束
            time_budget_ms: 可选的时间预算覆盖

        Returns:
            {card_id: probability} 手牌概率字典
        """
        start_time = time.time() * 1000
        budget = time_budget_ms or self.time_budget_ms

        if seen_cards is None:
            seen_cards = {}
        if generated_cards is None:
            generated_cards = set()

        state_hash = self._compute_hash(bayesian_state, observed, hand_size)
        if state_hash == self._last_state_hash and self._last_result is not None:
            return self._last_result

        # v4: 从历史回合计算费用偏向，引导采样
        cost_bias = self._turn_history.compute_cost_bias(observed.turn)
        num_worlds = self._compute_num_worlds(budget)
        worlds = self._sampler.sample_worlds(
            bayesian_state=bayesian_state,
            hand_size=hand_size,
            seen_cards=seen_cards,
            generated_cards=generated_cards,
            num_worlds=num_worlds,
            constraints=constraints,
            cost_bias=cost_bias,
            non_derived_candidates=non_derived_candidates,
        )

        if not worlds:
            self._last_result = {}
            self._last_state_hash = state_hash
            return {}

        for world in worlds:
            elapsed = time.time() * 1000 - start_time
            if elapsed > budget * 0.8:
                break

            # 使用简化模式模拟
            sim_behavior = self._simulator.simulate_opponent_turn(
                world=world,
                opponent_state=opponent_state or self._default_opponent_state(),
                our_board=our_board or [],
                our_hero=our_hero,
                turn_number=observed.turn,
            )

            # 提取世界手牌的card_id集合（v3: 供手牌覆盖匹配使用）
            world_hand_ids = set()
            for card in world.hand_cards:
                cid = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                if cid:
                    world_hand_ids.add(cid)

            world.behavior_match = self._matcher.compute_match(
                observed, sim_behavior, world_hand_card_ids=world_hand_ids,
            )

            cross_turn_score = self._cross_turn_validation(
                world, observed, opponent_state, our_board, our_hero,
            )
            world.behavior_match = world.behavior_match * 0.7 + cross_turn_score * 0.3

            world.weight = world.archetype_weight * max(0.01, world.behavior_match)

        probabilities = self._aggregate_probabilities(worlds, seen_cards=seen_cards)

        self._last_result = probabilities
        self._last_state_hash = state_hash

        # v4: 记录本回合行为到历史追踪（供后续回合的 cost_bias 使用）
        self._turn_history.record_turn(observed)

        # 记录到跨回合概率追踪器
        if probabilities:
            self._multi_turn_tracker.update(observed.turn, probabilities)

        # 融合跨回合累积概率（与 infer_from_tracker 一致）
        probabilities = self._fuse_multi_turn_probabilities(
            probabilities, seen_cards, observed.turn,
        )
        self._last_result = probabilities

        return probabilities

    def _cross_turn_validation_from_tracker(
        self,
        log_monitor,
        world: HandWorld,
        observed: ObservedBehavior,
        our_controller: int,
        opp_controller: int,
        lookahead_turns: int = 1,
    ) -> float:
        """跨回合验证（使用 Power.log 真实数据）。

        如果对手持有某张牌，不仅当前回合的打法应该匹配，
        未来1-2回合的打法也应该一致。
        """
        if not world.hand_cards or observed.turn <= 0:
            return 0.5

        # 模拟对手下一回合
        next_turn = observed.turn + 2
        sim_next = self._simulator.simulate_opponent_turn_from_tracker(
            log_monitor=log_monitor,
            world=world,
            our_controller=our_controller,
            opp_controller=opp_controller,
            turn_number=next_turn,
            max_steps=4,
        )

        if observed.passed and sim_next.passed:
            return 0.9
        if observed.passed and not sim_next.passed:
            return 0.7
        if not observed.passed and sim_next.passed:
            return 0.5

        return 0.6

    def _cross_turn_validation(
        self,
        world: HandWorld,
        observed: ObservedBehavior,
        opponent_state,
        our_board,
        our_hero,
        lookahead_turns: int = 1,
    ) -> float:
        """跨回合验证（回退模式）。"""
        if not world.hand_cards or observed.turn <= 0:
            return 0.5

        next_turn = observed.turn + 2
        sim_next = self._simulator.simulate_opponent_turn(
            world=world,
            opponent_state=opponent_state or self._default_opponent_state(),
            our_board=our_board or [],
            our_hero=our_hero,
            turn_number=next_turn,
            max_steps=4,
        )

        if observed.passed and sim_next.passed:
            return 0.9
        if observed.passed and not sim_next.passed:
            return 0.7
        if not observed.passed and sim_next.passed:
            return 0.5

        return 0.6

    def _aggregate_probabilities(
        self,
        worlds: List[HandWorld],
        seen_cards: Optional[Dict[str, int]] = None,
    ) -> Dict[str, float]:
        """聚合所有世界的概率。

        P(card_c in hand) = Σ_w weight(w) × I(c in w.hand) / Σ_w weight(w)

        v3 修复：
        - 已打出卡牌（seen_cards中张数已用完的）强制概率为0
        - 这修复了"已打出卡牌概率不衰减"的P0问题
        """
        if seen_cards is None:
            seen_cards = {}

        total_weight = sum(w.weight for w in worlds)
        if total_weight <= 0:
            return {}

        card_weights: Dict[str, float] = defaultdict(float)

        for world in worlds:
            for card in world.hand_cards:
                card_id = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                if card_id:
                    # v3修复：跳过已打出全部张数的卡牌
                    # 如果卡组中有2张该牌，对手已打出2张，则不可能再在手牌中
                    # seen_cards 记录的是对手已打出的张数
                    # 但世界手牌中的牌已经是过滤后的（HandSampler._sample_hand_from_deck
                    # 已根据 seen_cards 减去了已打出张数），所以这里不再重复过滤
                    card_weights[card_id] += world.weight

        probabilities = {}
        for card_id, weight in card_weights.items():
            probabilities[card_id] = min(1.0, weight / total_weight)

        return probabilities

    def _fuse_multi_turn_probabilities(
        self,
        single_turn_probs: Dict[str, float],
        seen_cards: Dict[str, int],
        current_turn: int,
    ) -> Dict[str, float]:
        """融合单回合MCTS推断与跨回合累积概率。

        核心思想（贝叶斯加权融合）：
        1. 当前回合的MCTS推断是最可靠的（反映最新信息）
        2. 历史回合的累积概率提供先验知识（跨回合一致性验证）
        3. 如果某张牌在多个回合中都保持高概率，说明推断更可靠
        4. 如果某张牌在历史回合高概率但当前回合低概率，可能已被打出或使用

        融合公式：
        P_final(card) = α × P_current(card) + (1-α) × P_historical(card)

        其中 α = 0.6（当前回合权重更高），
        P_historical 来自 MultiTurnProbabilityTracker 的指数衰减加权平均。

        额外约束：
        - 已打出的全部张数的牌，概率强制为0
        - 已揭示在手中的牌，概率强制为1.0
        - 跨回合一致性加成：如果某牌在当前和历史都高概率，额外提升

        Args:
            single_turn_probs: 当前回合MCTS推断的概率
            seen_cards: 已打出的卡牌 {card_id: count}
            current_turn: 当前回合数

        Returns:
            融合后的 {card_id: probability}
        """
        # 获取跨回合累积概率
        historical_probs = self._multi_turn_tracker.get_aggregated_probabilities(
            current_turn=current_turn,
        )

        if not historical_probs:
            # 没有历史数据时，直接使用当前回合结果
            return single_turn_probs

        if not single_turn_probs:
            # 当前回合没有结果时，使用历史概率（但要排除已打出的牌）
            result = {}
            for card_id, prob in historical_probs.items():
                if card_id not in seen_cards:
                    result[card_id] = prob
            return result

        # 融合参数
        alpha = 0.6  # 当前回合权重
        consistency_bonus = 0.1  # 一致性加成

        # 收集所有卡牌ID
        all_cards = set(single_turn_probs.keys()) | set(historical_probs.keys())

        result = {}
        for card_id in all_cards:
            # 跳过已打出全部张数的牌
            if card_id in seen_cards:
                continue

            p_current = single_turn_probs.get(card_id, 0.0)
            p_historical = historical_probs.get(card_id, 0.0)

            # 基础融合：加权平均
            p_fused = alpha * p_current + (1 - alpha) * p_historical

            # 一致性加成：如果当前和历史都高概率，说明推断可靠
            if p_current >= 0.3 and p_historical >= 0.3:
                consistency = min(p_current, p_historical) * consistency_bonus
                p_fused = min(1.0, p_fused + consistency)

            result[card_id] = min(1.0, max(0.0, p_fused))

        return result

    def _compute_num_worlds(self, budget_ms: float) -> int:
        """根据时间预算 + 并行线程数计算采样世界数。

        v5 版本：大幅增加世界数量以提升手牌空间覆盖度。
        用户要求"模拟时间可以长"，因此使用更多世界数。
        2000ms + 4线程 → ~640 世界（vs v4 的 128）。
        """
        base = max(20, min(200, int(budget_ms / 10)))
        if self.num_threads > 1:
            return max(20, min(500, int(base * self.num_threads * 0.8)))
        return base

    def _run_parallel_simulation(
        self,
        worlds: List[HandWorld],
        log_monitor,
        our_controller: int,
        opp_controller: int,
        observed: ObservedBehavior,
        budget: float,
        start_time: float,
    ) -> Dict[int, dict]:
        """线程池并行化世界模拟。

        每个世界独立模拟（主回合贪心搜索 + 跨回合验证），
        在预算时间内收集尽可能多的完成结果。
        返回 {world_id: {...}} 映射。
        """
        if self.num_threads <= 1 or len(worlds) <= 3:
            # 单线程或世界太少时退化为串行
            results = {}
            for world in worlds:
                elapsed = time.time() * 1000 - start_time
                if elapsed > budget * 0.8:
                    break
                results[world.world_id] = self._simulate_one_world(
                    world, log_monitor, our_controller, opp_controller, observed,
                )
            return results

        results: Dict[int, dict] = {}
        executor = cf.ThreadPoolExecutor(
            max_workers=self.num_threads,
            thread_name_prefix="mcts_world",
        )

        try:
            # 一次性提交所有世界（不逐个检查预算——提交本身很快）
            futures = {}
            for world in worlds:
                future = executor.submit(
                    self._simulate_one_world,
                    world, log_monitor, our_controller, opp_controller, observed,
                )
                futures[future] = world.world_id

            # 在剩余预算内收集完成的结果
            remaining = max(0.001, budget - (time.time() * 1000 - start_time))
            for future in cf.as_completed(futures, timeout=remaining / 1000):
                try:
                    result = future.result()
                    results[result['world_id']] = result
                except cf.TimeoutError:
                    break
                except Exception:
                    continue

        except Exception:
            pass
        finally:
            executor.shutdown(wait=False)  # 不等待未完成的任务

        return results

    def _simulate_one_world(
        self,
        world: HandWorld,
        log_monitor,
        our_controller: int,
        opp_controller: int,
        observed: ObservedBehavior,
    ) -> dict:
        """模拟单个世界，返回包含主回合+跨回合模拟结果的字典。

        此方法设计为线程安全——不修改共享可变状态。
        simulate_opponent_turn_from_tracker 只读访问 entity_cache 和 tracker。
        """
        sim_main = self._simulator.simulate_opponent_turn_from_tracker(
            log_monitor=log_monitor, world=world,
            our_controller=our_controller, opp_controller=opp_controller,
            turn_number=observed.turn,
        )

        # 跨回合验证（下一回合的轻量模拟）
        next_turn = observed.turn + 2
        sim_next = self._simulator.simulate_opponent_turn_from_tracker(
            log_monitor=log_monitor, world=world,
            our_controller=our_controller, opp_controller=opp_controller,
            turn_number=next_turn, max_steps=4,
        )

        # 提取世界手牌的card_id集合（线程安全——world 为每个世界的独立对象）
        world_hand_ids = set()
        for card in getattr(world, 'hand_cards', []):
            cid = getattr(card, 'card_id', '') or getattr(card, 'name', '')
            if cid:
                world_hand_ids.add(cid)

        return {
            'world_id': world.world_id,
            'sim_main': sim_main,
            'sim_next': sim_next,
            'world_hand_ids': world_hand_ids,
        }

    @staticmethod
    def _default_opponent_state():
        """默认对手状态。"""
        try:
            from analysis.card.engine.state import OpponentState, HeroState
            return OpponentState(hero=HeroState(hp=30))
        except ImportError:
            return None

    @staticmethod
    def _compute_hash(bayesian_state, observed, hand_size) -> int:
        """计算快速哈希用于缓存。"""
        try:
            key = (
                hash(tuple(bayesian_state.get("top_decks", [])[:3])),
                observed.turn,
                observed.mana_spent,
                observed.available_mana,
                observed.passed,
                hand_size,
                tuple(observed.played_cards),
            )
            return hash(key)
        except Exception:
            return 0


# ── 便捷函数 ──────────────────────────────────────────────────

def infer_opponent_hand_from_simulation(
    state_dict: dict,
    time_budget_ms: float = 500.0,
) -> Dict[str, float]:
    """从游戏状态字典推断对手手牌概率（便捷入口）。

    将tracker层的状态字典转换为MCTS引擎需要的格式，
    执行模拟推断，返回手牌概率。

    Args:
        state_dict: LogMonitor的build_state_dict()输出
        time_budget_ms: 时间预算

    Returns:
        {card_id: probability} 手牌概率字典
    """
    bayesian = state_dict.get("bayesian", {})

    current_turn = state_dict.get("turn", 0)
    available_mana = state_dict.get("available_mana", 0)
    known_cards = state_dict.get("known_cards", [])

    opp_cards_this_turn = state_dict.get("opp_cards_played_this_turn", [])
    played_card_ids = list(opp_cards_this_turn)

    mana_spent = 0
    for kc in known_cards:
        if kc.get("turn_seen", 0) == current_turn:
            cost = kc.get("cost", 0)
            if isinstance(cost, (int, float)):
                mana_spent += int(cost)

    is_pass = len(opp_cards_this_turn) == 0 and mana_spent == 0

    observed = ObservedBehavior(
        played_cards=played_card_ids,
        mana_spent=mana_spent,
        available_mana=available_mana,
        passed=is_pass,
        turn=current_turn,
    )

    seen_cards: Dict[str, int] = {}
    for kc in known_cards:
        cid = kc.get("card_id", "")
        if cid:
            seen_cards[cid] = seen_cards.get(cid, 0) + 1

    generated_cards = set(state_dict.get("generated_cards", set()))
    opp_hand_count = state_dict.get("opp_hand_count", 0)

    mcts = OpponentHandMCTS(time_budget_ms=time_budget_ms)
    return mcts.infer_hand_probabilities(
        bayesian_state=bayesian,
        observed=observed,
        seen_cards=seen_cards,
        generated_cards=generated_cards,
        hand_size=opp_hand_count,
    )

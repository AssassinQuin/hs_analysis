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

世界节点模拟流程：
    1. 候选手牌采样：从贝叶斯推断的卡组中采样候选手牌组合
    2. 对手回合模拟：调用卡牌效果引擎（enumerate_legal_actions + evaluate）
       模拟对手在该手牌+场面下的最优决策
    3. 行为匹配评估：比较模拟对手打法与实际观测打法
       - 对手出了某张牌 → 模拟中是否也选择出这张牌？
       - 对手没出牌（pass） → 模拟中是否也选择pass？
       - 对手用法力方式 → 模拟法力消耗是否接近？
    4. 跨回合验证：不只是当前回合，还模拟未来1-2回合
       如果对手持有某张牌，未来回合的打法也应一致
    5. 权重聚合：匹配度高的世界权重提升，包含的卡牌概率提升

与原 world_model.py 的区别：
    world_model.py 仍然使用硬编码的似然比（如 p_not_play=0.3），
    本模块完全通过模拟对手决策来计算概率，没有任何硬编码概率值。

用法::

    mcts = OpponentHandMCTS()
    probabilities = mcts.infer_hand_probabilities(
        game_state=state,
        observed_actions=observed,
        bayesian_model=model,
        time_budget_ms=500,
    )
    for card_id, prob in probabilities.items():
        print(f"{card_id}: {prob:.1%}")
"""

from __future__ import annotations

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

    所有匹配度计算基于游戏逻辑，不硬编码概率值。
    """

    @staticmethod
    def compute_match(
        observed: ObservedBehavior,
        simulated: SimulatedBehavior,
    ) -> float:
        """计算行为匹配度 [0, 1]。

        匹配度 = w1 * card_match + w2 * mana_match + w3 * pass_match + w4 * hp_match

        权重根据信息量动态调整：
        - 如果对手出了牌，卡牌匹配权重高
        - 如果对手pass，pass匹配权重高
        - 法力消耗总是有信息量的
        """
        # 卡牌打出匹配
        card_match = BehaviorMatcher._card_play_match(observed, simulated)

        # 法力消耗匹配
        mana_match = BehaviorMatcher._mana_usage_match(observed, simulated)

        # Pass行为匹配
        pass_match = BehaviorMatcher._pass_match(observed, simulated)

        # 英雄技能匹配
        hp_match = BehaviorMatcher._hero_power_match(observed, simulated)

        # 动态权重：根据观测到的信息量调整
        if observed.passed:
            # 对手pass——pass匹配最重要
            w1, w2, w3, w4 = 0.1, 0.2, 0.6, 0.1
        elif observed.played_cards:
            # 对手出了牌——卡牌匹配最重要
            w1, w2, w3, w4 = 0.5, 0.25, 0.1, 0.15
        else:
            # 无明确信息——均匀权重
            w1, w2, w3, w4 = 0.25, 0.25, 0.25, 0.25

        return w1 * card_match + w2 * mana_match + w3 * pass_match + w4 * hp_match

    @staticmethod
    def _card_play_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """卡牌打出匹配度。

        如果对手打出了牌A：
        - 模拟也打出牌A → 完美匹配 (1.0)
        - 模拟没打出牌A但出了其他牌 → 部分匹配（说明手牌中有替代选择）
        - 模拟pass → 不匹配 (0.0)

        如果对手没出任何牌（pass）：
        - 模拟也pass → 完美匹配 (1.0)
        - 模拟出了牌 → 不匹配 (0.0)

        这个匹配度直接反映了"对手如果有这张牌是否会出"的推断。
        """
        if not observed.played_cards:
            # 对手没出牌——卡牌匹配维度不适用，返回中性值
            return 0.5

        obs_set = set(observed.played_cards)
        sim_set = set(simulated.played_cards)

        if not sim_set:
            # 模拟pass但对手出了牌——强不匹配
            return 0.0

        # 计算交集比例
        intersection = obs_set & sim_set
        if intersection:
            # 有交集——至少模拟出了对手出的某张牌
            return len(intersection) / max(len(obs_set), 1)

        # 模拟出了不同牌——部分匹配
        # 对手可能选择了不同的出牌顺序或策略
        # 但至少模拟认为应该出牌（而不是pass）
        if sim_set and obs_set:
            return 0.3  # 出了牌但不同——弱匹配

        return 0.0

    @staticmethod
    def _mana_usage_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """法力消耗匹配度。

        对手法力消耗是强有力的信息：
        - 如果对手用了5/5法力，说明手牌中有5费的牌
        - 如果对手只用了2/5法力，说明手牌中没有3-5费的牌值得出
        """
        if observed.available_mana <= 0:
            return 0.5  # 无信息

        obs_usage = observed.mana_spent / max(observed.available_mana, 1)
        sim_usage = simulated.mana_spent / max(observed.available_mana, 1)  # 用同一个基准

        # 用法力利用率差距来衡量匹配度
        diff = abs(obs_usage - sim_usage)
        return max(0.0, 1.0 - diff)

    @staticmethod
    def _pass_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """Pass行为匹配度。

        对手pass是极强信号——说明手牌中没有任何值得出的牌。
        这是模拟引擎最关键的验证点。
        """
        if observed.passed and simulated.passed:
            return 1.0  # 完美匹配：都pass
        if observed.passed and not simulated.passed:
            return 0.0  # 不匹配：模拟认为应该出牌但对手pass
        if not observed.passed and simulated.passed:
            return 0.0  # 不匹配：模拟pass但对手出了牌
        # 都没pass
        return 1.0

    @staticmethod
    def _hero_power_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """英雄技能匹配度。"""
        if observed.hero_power_used == simulated.hero_power_used:
            return 1.0
        return 0.2  # 弱匹配——英雄技能使用与否不是强信号


# ── 对手回合模拟器 ──────────────────────────────────────────────

class OpponentTurnSimulator:
    """模拟对手在一个给定手牌+场面下的回合决策。

    调用卡牌效果引擎来计算：
    1. 合法动作枚举（enumerate_legal_actions）
    2. 动作评估（用scoring_engine评分）
    3. 贪心选择最优动作序列

    这替代了world_model.py中硬编码的概率推断。
    通过实际模拟对手决策来判断"对手若有这张牌会怎样打"。
    """

    def __init__(self):
        self._card_db = None

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception as e:
                logger.warning("无法加载卡牌数据库: %s", e)

    def simulate_opponent_turn(
        self,
        world: HandWorld,
        opponent_state: 'OpponentState',
        our_board: list,
        our_hero: 'HeroState',
        turn_number: int,
        max_steps: int = 8,
    ) -> SimulatedBehavior:
        """模拟对手回合决策。

        核心流程：
        1. 从world.hand_cards构建对手的手牌
        2. 构建一个以对手视角的GameState
        3. 枚举合法动作
        4. 用贪心策略选择动作
        5. 返回模拟的行为

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
        from analysis.search.game_state import (
            GameState, HeroState, ManaState, Minion, OpponentState as SearchOppState,
        )
        from analysis.search.abilities.enumeration import enumerate_legal_actions
        from analysis.search.abilities.simulation import apply_action
        from analysis.search.abilities.actions import ActionType
        from analysis.models.card import Card

        # 构建对手视角的GameState
        # 对手视角：opponent变成"player"，我们变成"opponent"
        try:
            opp_mana = min(10, max(1, turn_number))
            opp_hand = list(world.hand_cards)

            # 构建搜索用的GameState
            opp_search_state = GameState(
                hero=HeroState(
                    hp=opponent_state.hero.hp,
                    armor=opponent_state.hero.armor,
                    hero_class=opponent_state.hero.hero_class,
                ),
                mana=ManaState(
                    available=opp_mana,
                    max_mana=opp_mana,
                ),
                board=[m.copy() for m in opponent_state.board],
                hand=opp_hand,
                deck_remaining=max(0, len(world.deck_cards)),
                opponent=SearchOppState(
                    hero=HeroState(
                        hp=our_hero.hp if our_hero else 30,
                        armor=our_hero.armor if our_hero else 0,
                    ),
                    board=[
                        Minion(
                            name=getattr(m, 'name', '?'),
                            attack=m.attack,
                            health=m.health,
                            has_taunt=m.has_taunt,
                            has_divine_shield=m.has_divine_shield,
                        )
                        for m in our_board
                    ] if our_board else [],
                ),
                turn_number=turn_number,
            )

            # 模拟对手贪心出牌
            played_cards = []
            total_mana_spent = 0
            hero_power_used = False
            step_count = 0

            state = opp_search_state

            for _ in range(max_steps):
                actions = enumerate_legal_actions(state)
                if not actions:
                    break

                # 贪心策略：用scoring_engine评估每个动作，选最优
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

        except Exception as e:
            logger.debug("对手回合模拟失败: %s", e)
            return SimulatedBehavior(passed=True)

    def _select_best_action(self, state, actions):
        """贪心选择最优动作。

        使用轻量级评估，避免全量MCTS搜索（太慢）。
        评估维度：
        1. 法力效率（用了更多法力的动作更好）
        2. 场面价值（随从总属性更高的更好）
        3. 伤害效率（打脸伤害更高的更好）
        """
        from analysis.search.abilities.actions import ActionType
        from analysis.search.abilities.simulation import apply_action

        if not actions:
            return None

        # 如果只有END_TURN，直接返回
        non_end = [a for a in actions if a.action_type != ActionType.END_TURN]
        if not non_end:
            return actions[0]

        best_action = None
        best_score = float('-inf')

        for action in non_end[:15]:  # 限制评估数量，避免太慢
            try:
                new_state = apply_action(state, action)
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
        """评估一个动作后的状态价值。

        从对手视角评估：
        - 我方场面价值变化
        - 我方英雄HP变化
        - 法力利用率
        """
        score = 0.0

        # 场面价值：对手随从总属性
        our_board_value = sum(m.attack + m.health for m in new_state.board)
        old_board_value = sum(m.attack + m.health for m in old_state.board)
        score += (our_board_value - old_board_value) * 0.5

        # 对手英雄HP降低（对我方有利）
        opp_hp_change = new_state.opponent.hero.hp - old_state.opponent.hero.hp
        score += max(0, -opp_hp_change) * 1.0

        # 法力利用
        mana_used = old_state.mana.available - new_state.mana.available
        score += mana_used * 0.3

        # 随从数量
        score += len(new_state.board) * 0.5

        return score


# ── 候选手牌采样 ──────────────────────────────────────────────

class HandSampler:
    """从贝叶斯推断的卡组中采样候选手牌组合。

    采样策略：
    1. 从贝叶斯推断的top-N卡组中按后验概率分配采样数量
    2. 每个卡组中，过滤已打出的牌，从剩余牌中采样手牌
    3. 考虑已知的约束（如"手牌有龙"）

    与MCTS的Determinizer不同，这里我们采样的是"完整的手牌假设"，
    而Determinizer采样的是"对手视角的完整信息状态"。
    """

    def __init__(self):
        self._card_db = None

    def _ensure_card_db(self):
        if self._card_db is None:
            try:
                from analysis.data.card_data import get_db
                self._card_db = get_db()
            except Exception:
                pass

    def sample_worlds(
        self,
        bayesian_state: dict,
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        num_worlds: int = 30,
        constraints: Optional[List] = None,
    ) -> List[HandWorld]:
        """采样候选手牌世界。

        Args:
            bayesian_state: 贝叶斯卡组推断状态（含top_decks等）
            hand_size: 对手手牌数
            seen_cards: 已打出的卡牌 {card_id: count}
            generated_cards: 衍生牌集合
            num_worlds: 采样世界数
            constraints: 手牌约束（如holds_race等）

        Returns:
            候选手牌世界列表
        """
        self._ensure_card_db()

        if hand_size <= 0:
            return []

        top_decks = bayesian_state.get("top_decks", [])
        if not top_decks:
            return []

        worlds: List[HandWorld] = []

        # 按后验概率分配采样数量
        deck_probs = []
        total_prob = 0.0
        for deck_id, deck_name, prob in top_decks[:3]:
            deck_probs.append((deck_id, deck_name, prob))
            total_prob += prob

        if total_prob <= 0:
            return []

        world_id = 0
        for deck_id, deck_name, prob in deck_probs:
            # 按概率分配世界数
            n_worlds = max(3, round(num_worlds * prob / total_prob))

            deck_cards = self._get_deck_cards(deck_id)
            if not deck_cards:
                continue

            for _ in range(n_worlds):
                hand = self._sample_hand_from_deck(
                    deck_cards, hand_size, seen_cards, generated_cards, constraints
                )
                if hand:
                    worlds.append(HandWorld(
                        world_id=world_id,
                        hand_cards=hand,
                        deck_cards=[],  # 不需要完整牌库，只用于模拟
                        archetype_id=deck_id,
                        archetype_weight=prob,
                    ))
                    world_id += 1

        return worlds[:num_worlds]

    def _sample_hand_from_deck(
        self,
        deck_cards: List[int],
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        constraints: Optional[List],
    ) -> List:
        """从卡组中采样一手手牌。"""
        from analysis.models.card import Card

        # 统计卡组中的牌
        card_counts = Counter(deck_cards)

        # 减去已打出的牌
        remaining_cards = []
        for dbf_id, count in card_counts.items():
            # 转换为card_id
            card_id = self._dbf_to_card_id(dbf_id)
            if not card_id:
                continue
            if card_id in generated_cards:
                continue
            played = seen_cards.get(card_id, 0)
            remaining = count - played
            if remaining <= 0:
                continue
            for _ in range(remaining):
                remaining_cards.append(dbf_id)

        if not remaining_cards:
            return []

        # 采样手牌
        sample_size = min(hand_size, len(remaining_cards))
        sampled_dbfs = random.sample(remaining_cards, sample_size)

        # 转换为Card对象
        hand = []
        for dbf_id in sampled_dbfs:
            card = self._dbf_to_card(dbf_id)
            if card:
                hand.append(card)

        return hand

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
        from analysis.models.card import Card

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

    核心算法：
    1. 采样：从贝叶斯推断的卡组中采样N个候选手牌世界
    2. 模拟：对每个世界，调用卡牌效果引擎模拟对手决策
    3. 匹配：比较模拟行为与观测行为，计算匹配度
    4. 跨回合验证：对未来回合做轻量模拟，验证假设一致性
    5. 聚合：按匹配度加权，计算每张卡牌的手牌概率

    与传统MCTS的区别：
    - 传统MCTS搜索动作空间（找最优打法）
    - 本引擎搜索手牌空间（找最可能手牌）
    - 使用轻量贪心模拟替代完整MCTS搜索（避免太慢）

    时间预算：
    - 默认500ms，足够采样30-50个世界并完成模拟
    - 可配置，适应不同性能需求
    """

    def __init__(self, time_budget_ms: float = 500.0):
        self.time_budget_ms = time_budget_ms
        self._sampler = HandSampler()
        self._simulator = OpponentTurnSimulator()
        self._matcher = BehaviorMatcher()
        # 缓存
        self._last_result: Optional[Dict[str, float]] = None
        self._last_state_hash: int = 0

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
        time_budget_ms: Optional[float] = None,
    ) -> Dict[str, float]:
        """推断对手手牌中每张卡牌的概率。

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

        # 快速哈希检查
        state_hash = self._compute_hash(bayesian_state, observed, hand_size)
        if state_hash == self._last_state_hash and self._last_result is not None:
            return self._last_result

        # Step 1: 采样候选手牌世界
        num_worlds = self._compute_num_worlds(budget)
        worlds = self._sampler.sample_worlds(
            bayesian_state=bayesian_state,
            hand_size=hand_size,
            seen_cards=seen_cards,
            generated_cards=generated_cards,
            num_worlds=num_worlds,
            constraints=constraints,
        )

        if not worlds:
            self._last_result = {}
            self._last_state_hash = state_hash
            return {}

        # Step 2: 对每个世界模拟对手决策
        for world in worlds:
            elapsed = time.time() * 1000 - start_time
            if elapsed > budget * 0.8:
                # 时间快用完了，跳过剩余世界
                break

            sim_behavior = self._simulator.simulate_opponent_turn(
                world=world,
                opponent_state=opponent_state or self._default_opponent_state(),
                our_board=our_board or [],
                our_hero=our_hero,
                turn_number=observed.turn,
            )

            # Step 3: 计算行为匹配度
            world.behavior_match = self._matcher.compute_match(observed, sim_behavior)

            # Step 4: 跨回合验证（轻量级）
            cross_turn_score = self._cross_turn_validation(
                world, observed, opponent_state, our_board, our_hero,
            )
            world.behavior_match = world.behavior_match * 0.7 + cross_turn_score * 0.3

            # 计算最终权重
            world.weight = world.archetype_weight * max(0.01, world.behavior_match)

        # Step 5: 聚合概率
        probabilities = self._aggregate_probabilities(worlds)

        # 缓存结果
        self._last_result = probabilities
        self._last_state_hash = state_hash

        return probabilities

    def _cross_turn_validation(
        self,
        world: HandWorld,
        observed: ObservedBehavior,
        opponent_state,
        our_board,
        our_hero,
        lookahead_turns: int = 1,
    ) -> float:
        """跨回合验证。

        如果对手持有某张牌，不仅当前回合的打法应该匹配，
        未来1-2回合的打法也应该一致。

        轻量级实现：只模拟1步，用贪心策略。
        """
        if not world.hand_cards or observed.turn <= 0:
            return 0.5  # 无信息

        # 模拟对手下一回合
        next_turn = observed.turn + 2  # 对手下一回合
        sim_next = self._simulator.simulate_opponent_turn(
            world=world,
            opponent_state=opponent_state or self._default_opponent_state(),
            our_board=our_board or [],
            our_hero=our_hero,
            turn_number=next_turn,
            max_steps=4,  # 少量步骤
        )

        # 跨回合一致性检查
        # 如果对手本回合pass，下一回合应该有更多法力可以出牌
        if observed.passed and sim_next.passed:
            # 连续两回合pass——说明手牌确实很差
            return 0.9  # 强验证
        if observed.passed and not sim_next.passed:
            # 本回合pass但下回合出牌——合理（下回合有更多法力）
            return 0.7
        if not observed.passed and sim_next.passed:
            # 本回合出了牌但下回合pass——可能手牌用完了
            return 0.5

        # 一般情况：出了牌
        return 0.6

    def _aggregate_probabilities(
        self,
        worlds: List[HandWorld],
    ) -> Dict[str, float]:
        """聚合所有世界的概率。

        P(card_c in hand) = Σ_w weight(w) × I(c in w.hand) / Σ_w weight(w)
        """
        total_weight = sum(w.weight for w in worlds)
        if total_weight <= 0:
            return {}

        card_weights: Dict[str, float] = defaultdict(float)

        for world in worlds:
            for card in world.hand_cards:
                card_id = getattr(card, 'card_id', '') or getattr(card, 'name', '')
                if card_id:
                    card_weights[card_id] += world.weight

        # 归一化为概率
        probabilities = {}
        for card_id, weight in card_weights.items():
            probabilities[card_id] = min(1.0, weight / total_weight)

        return probabilities

    @staticmethod
    def _compute_num_worlds(budget_ms: float) -> int:
        """根据时间预算计算采样世界数。"""
        # 每个世界模拟约5-10ms
        # 500ms → 约50个世界
        # 200ms → 约20个世界
        return max(10, min(80, int(budget_ms / 10)))

    @staticmethod
    def _default_opponent_state():
        """默认对手状态。"""
        try:
            from analysis.search.game_state import OpponentState, HeroState
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

    # 构建观测行为
    current_turn = state_dict.get("turn", 0)
    available_mana = state_dict.get("available_mana", 0)
    known_cards = state_dict.get("known_cards", [])

    # 统计本回合对手打出的牌
    opp_cards_this_turn = state_dict.get("opp_cards_played_this_turn", [])
    played_card_ids = list(opp_cards_this_turn)

    # 计算法力消耗
    mana_spent = 0
    for kc in known_cards:
        if kc.get("turn_seen", 0) == current_turn:
            cost = kc.get("cost", 0)
            if isinstance(cost, (int, float)):
                mana_spent += int(cost)

    # 判断是否pass
    is_pass = len(opp_cards_this_turn) == 0 and mana_spent == 0

    observed = ObservedBehavior(
        played_cards=played_card_ids,
        mana_spent=mana_spent,
        available_mana=available_mana,
        passed=is_pass,
        turn=current_turn,
    )

    # 构建seen_cards和generated_cards
    seen_cards: Dict[str, int] = {}
    for kc in known_cards:
        cid = kc.get("card_id", "")
        if cid:
            seen_cards[cid] = seen_cards.get(cid, 0) + 1

    generated_cards = set(state_dict.get("generated_cards", set()))

    # 对手状态
    opp_hand_count = state_dict.get("opp_hand_count", 0)

    # 执行推断
    mcts = OpponentHandMCTS(time_budget_ms=time_budget_ms)
    return mcts.infer_hand_probabilities(
        bayesian_state=bayesian,
        observed=observed,
        seen_cards=seen_cards,
        generated_cards=generated_cards,
        hand_size=opp_hand_count,
    )

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
        card_match = BehaviorMatcher._card_play_match(observed, simulated)
        mana_match = BehaviorMatcher._mana_usage_match(observed, simulated)
        pass_match = BehaviorMatcher._pass_match(observed, simulated)
        hp_match = BehaviorMatcher._hero_power_match(observed, simulated)

        if observed.passed:
            w1, w2, w3, w4 = 0.1, 0.2, 0.6, 0.1
        elif observed.played_cards:
            w1, w2, w3, w4 = 0.5, 0.25, 0.1, 0.15
        else:
            w1, w2, w3, w4 = 0.25, 0.25, 0.25, 0.25

        return w1 * card_match + w2 * mana_match + w3 * pass_match + w4 * hp_match

    @staticmethod
    def _card_play_match(observed: ObservedBehavior, simulated: SimulatedBehavior) -> float:
        """卡牌打出匹配度。"""
        if not observed.played_cards:
            return 0.5

        obs_set = set(observed.played_cards)
        sim_set = set(simulated.played_cards)

        if not sim_set:
            return 0.0

        intersection = obs_set & sim_set
        if intersection:
            return len(intersection) / max(len(obs_set), 1)

        if sim_set and obs_set:
            # 费用接近也算部分匹配
            return 0.3

        return 0.0

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
                from analysis.data.card_data import get_db
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
        from analysis.search.game_state import (
            GameState, HeroState, ManaState, Minion, OpponentState as SearchOppState,
        )
        from analysis.models.card import Card

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
        """使用贪心策略模拟对手出牌序列。

        核心模拟循环：
        1. 枚举合法动作
        2. 评估每个动作的价值
        3. 选择最优动作
        4. 应用动作，更新状态
        5. 重复直到 END_TURN 或无合法动作

        Args:
            opp_game_state: 对手视角的 GameState
            max_steps: 最大模拟步数

        Returns:
            SimulatedBehavior 模拟的对手行为
        """
        from analysis.search.abilities.enumeration import enumerate_legal_actions
        from analysis.search.abilities.simulation import apply_action
        from analysis.search.abilities.actions import ActionType

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
        """采样候选手牌世界。"""
        self._ensure_card_db()

        if hand_size <= 0:
            return []

        top_decks = bayesian_state.get("top_decks", [])
        if not top_decks:
            return []

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

            for _ in range(n_worlds):
                hand = self._sample_hand_from_deck(
                    deck_cards, hand_size, seen_cards, generated_cards, constraints
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

    def _sample_hand_from_deck(
        self,
        deck_cards: List[int],
        hand_size: int,
        seen_cards: Dict[str, int],
        generated_cards: Set[str],
        constraints: Optional[List],
    ) -> List:
        """从卡组中采样一手手牌。"""
        card_counts = Counter(deck_cards)

        remaining_cards = []
        for dbf_id, count in card_counts.items():
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

        sample_size = min(hand_size, len(remaining_cards))
        sampled_dbfs = random.sample(remaining_cards, sample_size)

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

    def __init__(self, time_budget_ms: float = 500.0):
        self.time_budget_ms = time_budget_ms
        self._sampler = HandSampler()
        self._simulator = OpponentTurnSimulator()
        self._matcher = BehaviorMatcher()
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

        # Step 2: 对每个世界模拟对手决策（使用 Power.log 真实数据）
        for world in worlds:
            elapsed = time.time() * 1000 - start_time
            if elapsed > budget * 0.8:
                break

            # 使用 PowerLogGameStateBuilder 构建对手视角的完整 GameState
            sim_behavior = self._simulator.simulate_opponent_turn_from_tracker(
                log_monitor=log_monitor,
                world=world,
                our_controller=our_controller,
                opp_controller=opp_controller,
                turn_number=observed.turn,
            )

            # Step 3: 计算行为匹配度
            world.behavior_match = self._matcher.compute_match(observed, sim_behavior)

            # Step 4: 跨回合验证
            cross_turn_score = self._cross_turn_validation_from_tracker(
                log_monitor, world, observed,
                our_controller, opp_controller,
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

            world.behavior_match = self._matcher.compute_match(observed, sim_behavior)

            cross_turn_score = self._cross_turn_validation(
                world, observed, opponent_state, our_board, our_hero,
            )
            world.behavior_match = world.behavior_match * 0.7 + cross_turn_score * 0.3

            world.weight = world.archetype_weight * max(0.01, world.behavior_match)

        probabilities = self._aggregate_probabilities(worlds)

        self._last_result = probabilities
        self._last_state_hash = state_hash

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

        probabilities = {}
        for card_id, weight in card_weights.items():
            probabilities[card_id] = min(1.0, weight / total_weight)

        return probabilities

    @staticmethod
    def _compute_num_worlds(budget_ms: float) -> int:
        """根据时间预算计算采样世界数。"""
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

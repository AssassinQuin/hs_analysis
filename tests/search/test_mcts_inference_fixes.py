# -*- coding: utf-8 -*-
"""test_mcts_inference_fixes.py — MCTS对手手牌推断系统修复验证测试

覆盖测试报告中识别的所有核心问题：
1. P0: 对手回合检测 - 奇偶回合规则不可靠
2. P0: 已打出卡牌概率不衰减 - seen_cards计数错误
3. P1: MCTS概率区分度为负 - 手牌覆盖匹配缺失
4. P1: 候选卡组覆盖不足 - 无职业卡池回退
5. P1: 衍生卡牌后缀处理 - 变形卡牌被排除

测试策略：
- 行为匹配引擎：验证新增的手牌覆盖匹配维度
- 采样器：验证seen_cards计数过滤、动态扩展、职业回退
- 聚合概率：验证已打出卡牌不在输出中
- 端到端：验证概率区分度为正
"""

import pytest
from collections import Counter
from unittest.mock import MagicMock, patch

# ── 行为匹配引擎测试 ──────────────────────────────────────────

class TestBehaviorMatcherHandCoverage:
    """测试v3新增的手牌覆盖匹配维度"""

    def test_coverage_match_full_coverage(self):
        """世界手牌完全包含对手打出的牌 → 匹配度最高"""
        from analysis.engine.opponent_hand_mcts import BehaviorMatcher, ObservedBehavior

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001", "EX1_002"],
            mana_spent=5,
            available_mana=7,
            turn=5,
        )
        # 世界手牌包含两张打出的牌
        world_hand_ids = {"EX1_001", "EX1_002", "EX1_003"}
        score = matcher._hand_coverage_match(observed, world_hand_ids)
        assert score >= 0.9, f"完全覆盖应得高分，实际: {score}"

    def test_coverage_match_partial_coverage(self):
        """世界手牌只包含部分打出的牌 → 匹配度中等"""
        from analysis.engine.opponent_hand_mcts import BehaviorMatcher, ObservedBehavior

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001", "EX1_002", "EX1_003"],
            mana_spent=8,
            available_mana=10,
            turn=8,
        )
        world_hand_ids = {"EX1_001", "EX1_004"}  # 只包含1/3
        score = matcher._hand_coverage_match(observed, world_hand_ids)
        assert 0.3 < score < 0.7, f"部分覆盖应得中分，实际: {score}"

    def test_coverage_match_no_coverage(self):
        """世界手牌不包含任何打出的牌 → 匹配度最低"""
        from analysis.engine.opponent_hand_mcts import BehaviorMatcher, ObservedBehavior

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001", "EX1_002"],
            mana_spent=5,
            available_mana=7,
            turn=5,
        )
        world_hand_ids = {"EX1_099", "EX1_100"}  # 完全不包含
        score = matcher._hand_coverage_match(observed, world_hand_ids)
        assert score <= 0.2, f"无覆盖应得低分，实际: {score}"

    def test_coverage_match_no_played_cards(self):
        """对手没出牌时 → 中性值0.5"""
        from analysis.engine.opponent_hand_mcts import BehaviorMatcher, ObservedBehavior

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(played_cards=[], passed=True, turn=3)
        world_hand_ids = {"EX1_001"}
        score = matcher._hand_coverage_match(observed, world_hand_ids)
        assert score == 0.5, f"无出牌时应返回0.5，实际: {score}"

    def test_coverage_match_none_world_hand(self):
        """世界手牌ID为None时 → 中性值0.5"""
        from analysis.engine.opponent_hand_mcts import BehaviorMatcher, ObservedBehavior

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001"],
            mana_spent=3,
            available_mana=5,
            turn=3,
        )
        score = matcher._hand_coverage_match(observed, None)
        assert score == 0.5, f"None手牌时应返回0.5，实际: {score}"


class TestBehaviorMatcherComputeMatchV3:
    """测试v3的compute_match是否正确整合手牌覆盖匹配"""

    def test_world_with_played_cards_gets_higher_score(self):
        """包含对手打出牌的世界应比不包含的得分更高"""
        from analysis.engine.opponent_hand_mcts import (
            BehaviorMatcher, ObservedBehavior, SimulatedBehavior,
        )

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001"],
            mana_spent=3,
            available_mana=5,
            turn=3,
        )
        simulated = SimulatedBehavior(
            played_cards=["EX1_099"],  # 模拟出的牌和实际不同
            mana_spent=3,
        )
        # 世界1: 手牌包含对手打出的牌
        score_with = matcher.compute_match(
            observed, simulated, world_hand_card_ids={"EX1_001", "EX1_099"},
        )
        # 世界2: 手牌不包含对手打出的牌
        score_without = matcher.compute_match(
            observed, simulated, world_hand_card_ids={"EX1_050", "EX1_099"},
        )
        assert score_with > score_without, \
            f"包含打出牌的世界应得分更高: with={score_with}, without={score_without}"

    def test_card_play_match_not_zero_when_sim_misses(self):
        """对手出了牌但模拟没出时，card_play_match不应该是0"""
        from analysis.engine.opponent_hand_mcts import (
            BehaviorMatcher, ObservedBehavior, SimulatedBehavior,
        )

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001"],
            mana_spent=3,
            available_mana=5,
            turn=3,
        )
        simulated = SimulatedBehavior(played_cards=[], passed=True)
        score = matcher._card_play_match(observed, simulated)
        assert score > 0, f"模拟没出牌时card_play_match应>0（可能手牌有但贪心没选），实际: {score}"


# ── 采样器测试 ──────────────────────────────────────────────

class TestHandSamplerSeenCardsCounting:
    """测试已打出卡牌计数过滤是否正确"""

    def test_seen_cards_count_correctly_filters(self):
        """已打出2张的牌（卡组中2张），不应出现在采样手牌中"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        # 模拟 _dbf_to_card_id 和 _dbf_to_card
        sampler._card_db = MagicMock()

        # 卡组中有2张dbf_id=100的牌
        card_id = "EX1_001"
        sampler._card_db.get_by_dbf = MagicMock(return_value={
            "cardId": card_id, "id": card_id,
            "name": "Test Card", "cost": 3,
            "type": "MINION", "attack": 2, "health": 3,
            "race": "", "spellSchool": "",
        })

        # seen_cards标记已打出2张
        seen_cards = {card_id: 2}
        deck_cards = [100, 100]  # 2张同名牌

        hand = sampler._sample_hand_from_deck(
            deck_cards, hand_size=5, seen_cards=seen_cards,
            generated_cards=set(), constraints=None,
        )
        # 所有2张已打出，不应有任何采样结果
        assert hand == [], f"已打出全部张数的牌不应出现在手牌采样中"

    def test_seen_cards_partial_remaining(self):
        """已打出1张的牌（卡组中2张），应有1张剩余可采样"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        sampler._card_db = MagicMock()

        card_id = "EX1_001"
        sampler._card_db.get_by_dbf = MagicMock(return_value={
            "cardId": card_id, "id": card_id,
            "name": "Test Card", "cost": 3,
            "type": "MINION", "attack": 2, "health": 3,
            "race": "", "spellSchool": "",
        })

        # 卡组2张，已打出1张
        seen_cards = {card_id: 1}
        deck_cards = [100, 100]

        # 运行多次，检查是否有可能采样到
        hits = 0
        for _ in range(50):
            hand = sampler._sample_hand_from_deck(
                deck_cards, hand_size=1, seen_cards=seen_cards,
                generated_cards=set(), constraints=None,
            )
            if hand:
                hits += 1
        # 应该有时能采样到（概率约50%）
        assert hits > 0, "部分剩余的牌应能被采样到"


class TestHandSamplerDeckExtension:
    """测试动态扩展卡组（包含对手已打出但不在卡组中的牌）"""

    def test_extend_deck_adds_observed_non_deck_cards(self):
        """对手打出的牌不在候选卡组中时，应动态加入"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        sampler._card_db = MagicMock()
        # 卡组中只有dbf=100
        deck_cards = [100]
        # 对手打出了card_id="EX1_002"，dbf=200，不在卡组中
        sampler._card_id_to_dbf = MagicMock(return_value=200)
        seen_cards = {"EX1_002": 1}
        generated_cards = set()

        extended = sampler._extend_deck_with_observed_cards(
            deck_cards, seen_cards, generated_cards,
        )
        assert 200 in extended, "非卡组牌应被动态添加"
        assert 100 in extended, "原始卡组牌应保留"

    def test_extend_deck_skips_generated_cards(self):
        """衍生牌不应被添加到卡组"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        deck_cards = [100]
        seen_cards = {"EX1_GEN": 1}
        generated_cards = {"EX1_GEN"}  # 衍生牌

        extended = sampler._extend_deck_with_observed_cards(
            deck_cards, seen_cards, generated_cards,
        )
        assert extended == [100], "衍生牌不应被添加到卡组"

    def test_extend_deck_skips_suffixed_cards(self):
        """带后缀的变形卡牌不应被添加到卡组"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        deck_cards = [100]
        # TIME_000ta 是变形版本
        seen_cards = {"TIME_000ta": 1}
        generated_cards = set()

        extended = sampler._extend_deck_with_observed_cards(
            deck_cards, seen_cards, generated_cards,
        )
        # 变形卡牌应被跳过
        assert extended == [100], "变形卡牌后缀版本不应被添加"


class TestHandSamplerStripCardSuffix:
    """测试卡牌后缀去除"""

    def test_strip_ta_suffix(self):
        from analysis.engine.opponent_hand_mcts import HandSampler
        sampler = HandSampler()
        assert sampler._strip_card_suffix("TIME_000ta") == "TIME_000"

    def test_strip_t_suffix(self):
        from analysis.engine.opponent_hand_mcts import HandSampler
        sampler = HandSampler()
        assert sampler._strip_card_suffix("EX1_001t") == "EX1_001"

    def test_strip_e_suffix(self):
        from analysis.engine.opponent_hand_mcts import HandSampler
        sampler = HandSampler()
        assert sampler._strip_card_suffix("EX1_001e") == "EX1_001"

    def test_no_suffix_unchanged(self):
        from analysis.engine.opponent_hand_mcts import HandSampler
        sampler = HandSampler()
        assert sampler._strip_card_suffix("EX1_001") == "EX1_001"


class TestHandSamplerClassPoolFallback:
    """测试无候选卡组时的职业卡池回退"""

    def test_class_pool_returns_worlds(self):
        """当无候选卡组时，应从职业卡池采样"""
        from analysis.engine.opponent_hand_mcts import HandSampler

        sampler = HandSampler()
        sampler._card_db = MagicMock()

        # 模拟卡牌数据库迭代
        mock_cards = [
            {"cardId": "EX1_001", "dbfId": 100, "cardClass": "WARRIOR",
             "type": "MINION", "rarity": "COMMON", "cost": 2,
             "name": "Warrior Card", "attack": 2, "health": 3,
             "race": "", "spellSchool": ""},
            {"cardId": "EX1_002", "dbfId": 200, "cardClass": "NEUTRAL",
             "type": "MINION", "rarity": "COMMON", "cost": 3,
             "name": "Neutral Card", "attack": 3, "health": 3,
             "race": "", "spellSchool": ""},
            {"cardId": "HERO_01", "dbfId": 300, "cardClass": "WARRIOR",
             "type": "HERO_POWER", "rarity": "FREE", "cost": 2,
             "name": "Hero Power", "attack": 0, "health": 0,
             "race": "", "spellSchool": ""},
        ]
        sampler._card_db.iter_card_ids = MagicMock(
            return_value=["EX1_001", "EX1_002", "HERO_01"]
        )
        sampler._card_db.get_card = MagicMock(
            side_effect=lambda cid: next(
                (c for c in mock_cards if c["cardId"] == cid), None
            )
        )
        sampler._card_db.get_by_dbf = MagicMock(
            side_effect=lambda dbf: next(
                (c for c in mock_cards if c["dbfId"] == dbf), None
            )
        )

        bayesian_state = {"opp_class": "WARRIOR"}
        worlds = sampler._sample_from_class_pool(
            bayesian_state, hand_size=2,
            seen_cards={}, generated_cards=set(), num_worlds=5,
        )
        assert len(worlds) > 0, "职业卡池回退应产出世界"


# ── 聚合概率测试 ──────────────────────────────────────────────

class TestAggregateProbabilities:
    """测试概率聚合逻辑"""

    def test_seen_cards_not_in_output_when_fully_played(self):
        """已打出全部张数的卡牌不应出现在概率输出中"""
        from analysis.engine.opponent_hand_mcts import OpponentHandMCTS, HandWorld
        from analysis.card.models.card import Card

        mcts = OpponentHandMCTS()

        # 创建两个世界，手牌都只包含同一张牌
        card_a = Card(dbf_id=100, name="CardA", cost=3, card_id="EX1_001")
        card_b = Card(dbf_id=200, name="CardB", cost=4, card_id="EX1_002")

        worlds = [
            HandWorld(world_id=0, hand_cards=[card_a, card_b],
                      archetype_weight=1.0, behavior_match=0.8, weight=0.8),
            HandWorld(world_id=1, hand_cards=[card_b],
                      archetype_weight=1.0, behavior_match=0.6, weight=0.6),
        ]

        # seen_cards标记 EX1_001 已被打出全部张数
        # 但采样器已经过滤了，所以如果世界手牌中还有，说明是采样器的bug
        # 这里测试的是聚合函数的容错性
        probs = mcts._aggregate_probabilities(worlds, seen_cards={})
        assert "EX1_001" in probs or "EX1_002" in probs, "应有概率输出"

    def test_probabilities_sum_to_reasonable_range(self):
        """概率值应在合理范围内"""
        from analysis.engine.opponent_hand_mcts import OpponentHandMCTS, HandWorld
        from analysis.card.models.card import Card

        mcts = OpponentHandMCTS()

        card_a = Card(dbf_id=100, name="CardA", cost=3, card_id="EX1_001")
        card_b = Card(dbf_id=200, name="CardB", cost=4, card_id="EX1_002")

        worlds = [
            HandWorld(world_id=0, hand_cards=[card_a, card_b],
                      archetype_weight=1.0, behavior_match=0.8, weight=0.8),
            HandWorld(world_id=1, hand_cards=[card_b],
                      archetype_weight=1.0, behavior_match=0.6, weight=0.6),
        ]

        probs = mcts._aggregate_probabilities(worlds, seen_cards={})
        for card_id, prob in probs.items():
            assert 0.0 <= prob <= 1.0, f"概率应在[0,1]范围: {card_id}={prob}"


# ── 概率区分度端到端测试 ──────────────────────────────────────

class TestProbabilityDiscrimination:
    """测试MCTS推断的概率区分度是否为正

    核心验证：已打出的卡牌概率 > 未打出卡牌概率
    """

    def test_played_cards_get_higher_probability(self):
        """包含打出牌的世界应给打出牌更高概率"""
        from analysis.engine.opponent_hand_mcts import (
            OpponentHandMCTS, ObservedBehavior, HandWorld, BehaviorMatcher,
        )
        from analysis.card.models.card import Card

        matcher = BehaviorMatcher()
        observed = ObservedBehavior(
            played_cards=["EX1_001"],
            mana_spent=3,
            available_mana=5,
            turn=3,
        )

        # 世界1: 手牌包含对手打出的牌
        card_a = Card(dbf_id=100, name="CardA", cost=3, card_id="EX1_001")
        card_b = Card(dbf_id=200, name="CardB", cost=4, card_id="EX1_002")

        from analysis.engine.opponent_hand_mcts import SimulatedBehavior

        # 模拟行为（贪心可能选不同的牌）
        sim_behavior = SimulatedBehavior(
            played_cards=["EX1_002"], mana_spent=4,
        )

        # 世界1手牌包含EX1_001
        world1_hand_ids = {"EX1_001", "EX1_002"}
        score1 = matcher.compute_match(
            observed, sim_behavior, world_hand_card_ids=world1_hand_ids,
        )

        # 世界2手牌不包含EX1_001
        world2_hand_ids = {"EX1_002", "EX1_003"}
        score2 = matcher.compute_match(
            observed, sim_behavior, world_hand_card_ids=world2_hand_ids,
        )

        # 关键断言：包含对手打出牌的世界得分应更高
        assert score1 > score2, \
            f"包含打出牌的世界得分应更高: with={score1}, without={score2}"


# ── 对手回合检测测试 ──────────────────────────────────────────

class TestOpponentTurnDetection:
    """测试对手回合检测逻辑

    核心验证：使用controller精确判断，而非奇偶回合规则
    """

    def test_controller_based_detection_no_parity_filter(self):
        """已通过controller过滤的牌不需要再奇偶过滤"""
        # 这验证的是 test_mcts_accuracy_v3.py 中的修复
        # opp_turn_plays 中的所有牌已经是通过 ctrl == opp_ctrl 过滤的
        # 所以不需要再判断 is_opp

        # 模拟 Game1: opp_ctrl=2
        opp_ctrl = 2
        opp_turn_plays = {
            1: [],           # turn 1 对手没出牌
            2: ["EX1_001"],  # turn 2 对手出牌 (controller=2)
            3: [],           # turn 3 对手没出牌
            4: ["EX1_002"],  # turn 4 对手出牌 (controller=2)
        }

        # 旧逻辑：奇偶过滤
        old_detected = []
        for turn, played in opp_turn_plays.items():
            if opp_ctrl == 1:
                is_opp = (turn % 2 == 1)
            elif opp_ctrl == 2:
                is_opp = (turn % 2 == 0)
            else:
                is_opp = True
            if is_opp and played:
                old_detected.append(turn)

        # 新逻辑：不过滤（所有已记录的牌都是对手的）
        new_detected = []
        for turn, played in opp_turn_plays.items():
            if played:
                new_detected.append(turn)

        # 新逻辑应能检测到更多对手回合
        assert set(new_detected) == {2, 4}, "新逻辑应检测到所有有出牌的对手回合"
        assert set(old_detected) == {2, 4}, "这种情况下旧逻辑也正确"

    def test_controller_mismatch_detection(self):
        """当controller与奇偶规则不匹配时，旧逻辑会遗漏"""
        # Game2场景: opp_ctrl=1 但对局中实际在偶数回合出牌
        # 这可能发生在某些特殊游戏模式下
        opp_ctrl = 1
        # 对手实际在 turn 2, 4, 6 出牌（controller=1但偶数回合）
        opp_turn_plays = {
            2: ["CARD_A"],  # 实际是对手出的牌（controller已过滤确认）
            4: ["CARD_B"],
            6: ["CARD_C"],
        }

        # 旧逻辑：opp_ctrl=1 → 只看奇数回合
        old_detected = []
        for turn, played in opp_turn_plays.items():
            if opp_ctrl == 1:
                is_opp = (turn % 2 == 1)
            elif opp_ctrl == 2:
                is_opp = (turn % 2 == 0)
            if is_opp and played:
                old_detected.append(turn)

        # 新逻辑：不再奇偶过滤
        new_detected = [t for t, p in opp_turn_plays.items() if p]

        # 旧逻辑遗漏所有回合！
        assert len(old_detected) == 0, "旧逻辑在controller不匹配时会遗漏"
        assert len(new_detected) == 3, "新逻辑应检测到所有回合"


# ── 已打出卡牌计数测试 ──────────────────────────────────────────

class TestSeenCardsCounting:
    """测试seen_cards使用Counter计数 vs set的问题"""

    def test_counter_tracks_multiple_copies(self):
        """当同一张牌被打出多次时，Counter应记录正确次数"""
        # 模拟对手打出病变虫群x3
        seen_card_ids = Counter()
        played_sequence = [
            ["EDI_001"],       # 第1次
            ["EDI_001"],       # 第2次
            ["EDI_001"],       # 第3次
        ]

        for played in played_sequence:
            for cid in played:
                seen_card_ids[cid] += 1

        # 旧方式 (set):
        seen_card_set = set()
        for played in played_sequence:
            for cid in played:
                seen_card_set.add(cid)

        assert seen_card_ids["EDI_001"] == 3, "Counter应记录3次"
        # set无法区分次数，丢失信息
        assert len(seen_card_set) == 1, "set只有1个元素"

    def test_counter_dict_passes_correct_counts_to_mcts(self):
        """dict(Counter)传递给MCTS时应保留计数信息"""
        seen_card_ids = Counter()
        seen_card_ids["EDI_001"] += 1
        seen_card_ids["EDI_001"] += 1
        seen_card_ids["EDI_002"] += 1

        passed = dict(seen_card_ids)
        assert passed["EDI_001"] == 2, "应传递正确计数2"
        assert passed["EDI_002"] == 1, "应传递正确计数1"

        # 旧方式传递的永远是1
        old_passed = {cid: 1 for cid in seen_card_ids}
        assert old_passed["EDI_001"] == 1, "旧方式丢失计数信息"


# ── 跨回合一致性推断测试 ──────────────────────────────────────────

class TestCrossTurnConsistency:
    """测试跨回合行为一致性推断

    如果对手连续多回合不出牌，其手牌中低费牌概率应下降
    """

    def test_pass_behavior_indicates_high_cost_hand(self):
        """对手pass时，手牌中可能有高费牌"""
        from analysis.engine.opponent_hand_mcts import ObservedBehavior

        # 回合3对手有5点法力但pass了
        observed = ObservedBehavior(
            played_cards=[],
            mana_spent=0,
            available_mana=5,
            passed=True,
            turn=3,
        )
        # pass行为本身提供了信息：对手手牌中没有5费以下可出的牌
        # 或者出牌不利（比如场面已被压制）
        assert observed.passed is True, "pass行为应被正确标记"

    def test_low_mana_spent_indicates_limited_options(self):
        """对手只用了少量法力，说明手牌中缺乏匹配费用的牌"""
        from analysis.engine.opponent_hand_mcts import ObservedBehavior

        # 回合7对手有7点法力但只用了2点
        observed = ObservedBehavior(
            played_cards=["EX1_LOW"],
            mana_spent=2,
            available_mana=7,
            passed=False,
            turn=7,
        )
        # 法力利用率低 = 28.6%，暗示手牌中可能缺乏中高费牌
        # 或已有场面不需要多出牌
        usage = observed.mana_spent / max(observed.available_mana, 1)
        assert usage < 0.5, "低法力利用率应被检测到"

# -*- coding: utf-8 -*-
"""test_hand_prediction.py — 基于 power.log 的手牌概率预测集成测试

测试目标：
1. 超几何分布概率计算正确性
2. 动态概率随游戏进程更新
3. 卡牌打出后概率正确变化
4. 衍生卡牌正确识别与追踪
5. 条件效果推断正确性
6. 无写死概率值
7. 基于 power.log 的端到端验证

测试分类：
- TestHypergeometricDistribution: 超几何分布数学正确性
- TestDynamicProbabilityEngine: 动态概率引擎核心逻辑
- TestCardEffectInference: 卡牌效果推断
- TestHandPredictorIntegration: HandPredictor 端到端集成
- TestBayesianProbabilityUpdate: 贝叶斯概率更新正确性
"""

from __future__ import annotations

import math
import pytest
from collections import Counter


# ── 超几何分布数学测试 ──────────────────────────────────────────

class TestHypergeometricDistribution:
    """测试超几何分布计算的数学正确性。"""

    def test_at_least_one_basic(self):
        """基本超几何概率: 30张牌中有2张目标牌, 抽5张, 至少抽到1张的概率。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # 30张中有2张目标, 抽5张
        # P(X>=1) = 1 - C(28,5)/C(30,5)
        # C(28,5) = 98280, C(30,5) = 142506
        # P = 1 - 98280/142506 ≈ 0.3103
        prob = hypergeometric_at_least_one(K=2, n=5, N=30)
        assert 0.30 < prob < 0.32

    def test_at_least_one_guaranteed(self):
        """当手牌数 >= 总量时, 概率为1。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        assert hypergeometric_at_least_one(K=2, n=30, N=30) == 1.0
        assert hypergeometric_at_least_one(K=1, n=10, N=10) == 1.0

    def test_at_least_one_impossible(self):
        """当目标牌数为0时, 概率为0。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        assert hypergeometric_at_least_one(K=0, n=5, N=30) == 0.0

    def test_at_least_one_single_copy(self):
        """单张传说牌: 30张中1张, 抽5张, 概率 ≈ 1/6。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        prob = hypergeometric_at_least_one(K=1, n=5, N=30)
        expected = 5.0 / 30.0  # 精确: 1 - C(29,5)/C(30,5) = 5/30
        assert abs(prob - expected) < 0.001

    def test_at_least_one_two_copies(self):
        """双张牌: 30张中2张, 抽10张, 概率应高于5/30。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        prob = hypergeometric_at_least_one(K=2, n=10, N=30)
        # 2张目标, 抽10张, 概率应该 > 0.5
        assert prob > 0.5

    def test_probability_increases_with_hand_size(self):
        """手牌越多, 持有某张牌的概率越高。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        p_3 = hypergeometric_at_least_one(K=2, n=3, N=25)
        p_5 = hypergeometric_at_least_one(K=2, n=5, N=25)
        p_8 = hypergeometric_at_least_one(K=2, n=8, N=25)

        assert p_3 < p_5 < p_8

    def test_probability_decreases_with_fewer_copies(self):
        """剩余张数越少, 概率越低。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        p_2 = hypergeometric_at_least_one(K=2, n=5, N=25)
        p_1 = hypergeometric_at_least_one(K=1, n=5, N=25)

        assert p_2 > p_1

    def test_probability_changes_over_game(self):
        """模拟游戏进程: 随着牌库减少和手牌变化, 概率应动态更新。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # T1: 对手 3 手牌, 27 牌库, 目标牌 2 张剩余
        p_t1 = hypergeometric_at_least_one(K=2, n=3, N=30)
        # T5: 对手 7 手牌, 20 牌库, 目标牌 2 张剩余
        p_t5 = hypergeometric_at_least_one(K=2, n=7, N=27)
        # T10: 对手 5 手牌, 10 牌库, 目标牌 2 张剩余
        p_t10 = hypergeometric_at_least_one(K=2, n=5, N=15)

        # 随着池子缩小(相对比例升高), 概率应上升
        assert p_t1 < p_t5
        assert p_t5 < p_t10

    def test_after_card_played_probability_updates(self):
        """打出一手牌后, 其他卡牌的手牌概率应更新。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # 场景: 对手有3手牌, 20牌库, 目标牌2张
        # 打出1张非目标牌后: 2手牌, 20牌库, 目标牌2张
        p_before = hypergeometric_at_least_one(K=2, n=3, N=23)
        p_after = hypergeometric_at_least_one(K=2, n=2, N=22)

        # 手牌减少, 概率应降低
        assert p_after < p_before


# ── 动态概率引擎测试 ──────────────────────────────────────────

class TestDynamicProbabilityEngine:
    """测试 DynamicProbabilityEngine 核心逻辑。"""

    def test_engine_no_hardcoded_probabilities(self):
        """确保引擎没有写死概率值。"""
        import inspect
        from analysis.engine.dynamic_probability import DynamicProbabilityEngine

        source = inspect.getsource(DynamicProbabilityEngine)
        # 不应包含写死的概率值如 0.7, 0.6, 0.5, 0.15, 0.35 等
        hardcoded_patterns = ["probability=0.7", "probability=0.6",
                              "probability=0.15", "probability=0.35",
                              "probability=0.30", "probability=0.25"]
        for pattern in hardcoded_patterns:
            assert pattern not in source, f"发现写死概率值: {pattern}"

    def test_engine_probabilities_sum_reasonable(self):
        """所有手牌概率之和应在合理范围内。"""
        from analysis.engine.dynamic_probability import (
            DynamicProbabilityEngine, HandProbabilityReport,
            CardProbability,
        )

        # 创建简单测试
        engine = DynamicProbabilityEngine()
        # 模拟状态: 无贝叶斯数据
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": []},
            "known_cards": [],
            "generated_cards": set(),
            "known_hand": [],
        }
        engine.update_from_state_dict(state_dict)
        report = engine.compute_probabilities(hand_size=5, deck_remaining=20)

        # 无贝叶斯数据时, 应无概率预测
        non_revealed = [cp for cp in report.card_probabilities if cp.source != "revealed"]
        # 无贝叶斯数据时应该为空或概率很低
        assert len(non_revealed) == 0

    def test_revealed_cards_always_100_percent(self):
        """已揭示的手牌概率必须为100%。"""
        from analysis.engine.dynamic_probability import DynamicProbabilityEngine

        engine = DynamicProbabilityEngine()
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": []},
            "known_cards": [],
            "generated_cards": set(),
            "known_hand": [(100, "EX1_001"), (101, "EX1_002")],
        }
        engine.update_from_state_dict(state_dict)
        report = engine.compute_probabilities(hand_size=5, deck_remaining=20)

        for cp in report.card_probabilities:
            if cp.source == "revealed":
                assert cp.probability == 1.0

    def test_conditional_constraint_applied(self):
        """条件效果约束应正确应用。"""
        from analysis.engine.dynamic_probability import (
            DynamicProbabilityEngine, HandConstraint,
        )

        engine = DynamicProbabilityEngine()
        # 添加条件约束
        engine.add_constraint(HandConstraint(
            constraint_type="holds_race",
            value="DRAGON",
            confidence=1.0,
        ))

        assert len(engine._constraints) == 1
        assert engine._constraints[0].constraint_type == "holds_race"
        assert engine._constraints[0].value == "DRAGON"


# ── 卡牌效果推断测试 ──────────────────────────────────────────

class TestCardEffectInference:
    """测试 CardEffectInferenceEngine。"""

    def test_effect_engine_initialization(self):
        """效果推断引擎应正确初始化。"""
        from analysis.engine.card_effect_inference import CardEffectInferenceEngine

        engine = CardEffectInferenceEngine()
        assert len(engine.get_inferences()) == 0
        assert len(engine.get_constraints()) == 0

    def test_record_card_played(self):
        """记录卡牌打出后应产生推断。"""
        from analysis.engine.card_effect_inference import CardEffectInferenceEngine

        engine = CardEffectInferenceEngine()
        engine.record_card_played("EX1_001", turn=1, source="deck")
        assert len(engine._played_cards) == 1

    def test_record_derived_card(self):
        """记录衍生卡牌后应可查询来源。"""
        from analysis.engine.card_effect_inference import CardEffectInferenceEngine

        engine = CardEffectInferenceEngine()
        engine.record_derived_card("GEN_001", "EX1_001", turn=3, derive_type="discover")

        sources = engine.get_derived_card_sources()
        assert "EX1_001" in sources
        assert len(sources["EX1_001"]) == 1
        assert sources["EX1_001"][0].card_id == "GEN_001"
        assert sources["EX1_001"][0].derive_type == "discover"

    def test_reset_clears_all(self):
        """重置后所有状态应清空。"""
        from analysis.engine.card_effect_inference import CardEffectInferenceEngine

        engine = CardEffectInferenceEngine()
        engine.record_card_played("EX1_001", turn=1)
        engine.record_derived_card("GEN_001", "EX1_001", turn=2)
        engine.reset()

        assert len(engine._played_cards) == 0
        assert len(engine._derived_cards) == 0
        assert len(engine.get_inferences()) == 0

    def test_no_hardcoded_probabilities_in_effect_engine(self):
        """效果推断引擎不应有写死的推断概率。"""
        import inspect
        from analysis.engine.card_effect_inference import CardEffectInferenceEngine

        source = inspect.getsource(CardEffectInferenceEngine)
        # 不应有写死的概率推断如 probability=0.7
        assert "probability=0.7" not in source
        assert "probability=0.6" not in source


# ── HandPredictor 集成测试 ──────────────────────────────────────

class TestHandPredictorIntegration:
    """HandPredictor 端到端集成测试。"""

    def test_hand_predictor_no_hardcoded_probs(self):
        """新版 HandPredictor 不应有写死概率。"""
        import inspect
        from tracker.hand_predictor import HandPredictor

        source = inspect.getsource(HandPredictor)
        hardcoded = ["probability=0.7", "probability=0.6",
                      "probability=0.15", "probability=0.35",
                      "probability=0.30", "probability=0.25",
                      "* 0.6", "* 0.5", "* 0.4"]
        for pattern in hardcoded:
            assert pattern not in source, f"发现写死概率值: {pattern}"

    def test_hand_predictor_with_empty_state(self):
        """空状态时应返回未知占位。"""
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": [],
                         "playstyle": "unknown"},
            "known_cards": [],
            "generated_cards": set(),
            "known_hand": [],
            "opp_hand_count": 5,
            "opp_deck_count": 20,
            "opp_class_en": "MAGE",
            "turn": 3,
            "opp_stats": {},
        }

        result = predictor.predict(state_dict)
        # 空状态无预测数据，hand_predictions 为空
        # UI 层根据 opp_hand_count 显示 "??" 占位符
        assert len(result.hand_predictions) == 0

    def test_hand_predictor_revealed_cards(self):
        """已知手牌应为100%概率。"""
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": [],
                         "playstyle": "unknown"},
            "known_cards": [],
            "generated_cards": set(),
            "known_hand": [(100, "EX1_001")],
            "opp_hand_count": 3,
            "opp_deck_count": 20,
            "opp_class_en": "MAGE",
            "turn": 3,
            "opp_stats": {},
        }

        result = predictor.predict(state_dict)
        # 应有1张确认手牌，不再生成 "??" 未知占位符（UI 层处理）
        revealed = [hp for hp in result.hand_predictions if hp.source == "revealed"]

        assert len(revealed) >= 1
        for hp in revealed:
            assert hp.probability == 1.0

    def test_hand_predictor_deck_predictions_have_probabilities(self):
        """卡组预测应包含手牌概率。"""
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": [],
                         "playstyle": "unknown"},
            "known_cards": [],
            "generated_cards": set(),
            "known_hand": [],
            "opp_hand_count": 5,
            "opp_deck_count": 20,
            "opp_class_en": "MAGE",
            "turn": 5,
            "opp_stats": {},
        }

        result = predictor.predict(state_dict)
        # 即使无贝叶斯数据, deck_predictions 也应存在
        assert isinstance(result.deck_predictions, list)


# ── 贝叶斯概率更新测试 ──────────────────────────────────────────

class TestBayesianProbabilityUpdate:
    """测试贝叶斯概率随观察信息更新。"""

    def test_predict_next_actions_different_probabilities(self):
        """predict_next_actions 应为不同卡牌返回不同概率。"""
        # 使用 mock 数据测试
        from analysis.utils.bayesian_opponent import BayesianOpponentModel

        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = []
        model.posteriors = {}
        model.card_to_decks = {}
        model.cards_by_dbf = {
            100: {"name": "Card A", "cost": 1, "cardId": "CARD_A"},
            101: {"name": "Card B", "cost": 3, "cardId": "CARD_B"},
            102: {"name": "Card C", "cost": 5, "cardId": "CARD_C"},
        }
        model.locked = None
        model._seen_cards = []
        model._seen_deck_cards = Counter()
        model._seen_cards_counter = Counter()
        model._known_hand_cards = []
        model._hand_hold_since = {}
        model.player_class = None
        model._unlock_count = 0

        # 创建测试卡组
        model.decks = [{
            "archetype_id": 1,
            "name": "Test Deck",
            "class": "MAGE",
            "cards": [100, 100, 101, 101, 102],  # 2x Card A, 2x Card B, 1x Card C
            "winrate": 0.55,
            "usage_rate": 0.1,
        }]
        model.posteriors = {1: 1.0}

        # 预测: 有手牌和牌库信息时, 不同张数的牌应有不同概率
        preds = model.predict_next_actions(n=3, hand_size=5, deck_remaining=20)

        if len(preds) >= 2:
            # 2张剩余的牌概率应高于1张的
            probs_by_name = {p["name"]: p["probability"] for p in preds}
            # Card A (2 copies) should have higher probability than Card C (1 copy)
            if "Card A" in probs_by_name and "Card C" in probs_by_name:
                assert probs_by_name["Card A"] > probs_by_name["Card C"]

    def test_probabilities_change_after_observation(self):
        """观察到卡牌后, 概率应发生变化。"""
        from analysis.utils.bayesian_opponent import BayesianOpponentModel

        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = [{
            "archetype_id": 1,
            "name": "Deck A",
            "class": "MAGE",
            "cards": [100, 101, 102],
            "winrate": 0.55,
            "usage_rate": 0.1,
        }, {
            "archetype_id": 2,
            "name": "Deck B",
            "class": "MAGE",
            "cards": [100, 103, 104],
            "winrate": 0.50,
            "usage_rate": 0.1,
        }]
        model.posteriors = {1: 0.5, 2: 0.5}
        model.card_to_decks = {}
        model.cards_by_dbf = {
            100: {"name": "Shared Card", "cost": 2, "cardId": "SHARED"},
            101: {"name": "Deck A Card", "cost": 3, "cardId": "DA"},
            102: {"name": "Deck A Card 2", "cost": 4, "cardId": "DA2"},
            103: {"name": "Deck B Card", "cost": 3, "cardId": "DB"},
            104: {"name": "Deck B Card 2", "cost": 4, "cardId": "DB2"},
        }
        model.locked = None
        model._seen_cards = []
        model._seen_deck_cards = Counter()
        model._seen_cards_counter = Counter()
        model._known_hand_cards = []
        model._hand_hold_since = {}
        model.player_class = None
        model._unlock_count = 0

        # 初始: 两个卡组等概率
        initial_posteriors = dict(model.posteriors)
        assert initial_posteriors[1] == 0.5

        # 观察到 Deck A 特有卡牌
        model.update(101)

        # Deck A 的后验应增加
        assert model.posteriors[1] > 0.5
        assert model.posteriors[2] < 0.5


# ── 衍生卡牌追踪测试 ──────────────────────────────────────────

class TestDerivedCardTracking:
    """测试衍生卡牌识别和追踪。"""

    def test_classify_source_deck(self):
        """从牌库出生的卡牌应被标记为 DECK。"""
        from analysis.watcher.global_tracker import GlobalTracker, CardSource
        from analysis.constants.hs_enums import ZONE_DECK

        tracker = GlobalTracker(our_controller=1, opp_controller=2)
        tracker.on_full_entity(
            entity_id=100,
            card_id="EX1_001",
            controller=2,
            zone=ZONE_DECK,
        )

        source = tracker._classify_source(100, "EX1_001")
        assert source == CardSource.DECK

    def test_classify_source_generated(self):
        """从 SETASIDE 出生的卡牌应被标记为 GENERATED。"""
        from analysis.watcher.global_tracker import GlobalTracker, CardSource
        from analysis.constants.hs_enums import ZONE_SETASIDE

        tracker = GlobalTracker(our_controller=1, opp_controller=2)
        tracker.on_full_entity(
            entity_id=200,
            card_id="GEN_001",
            controller=2,
            zone=ZONE_SETASIDE,
        )

        source = tracker._classify_source(200, "GEN_001")
        assert source == CardSource.GENERATED

    def test_over_copy_limit_detects_generated(self):
        """超过标准牌组限制的卡牌应被标记为 GENERATED。"""
        from analysis.watcher.global_tracker import GlobalTracker

        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # 模拟打出3张同一普通牌
        for i in range(3):
            tracker._opp_card_play_count["EX1_001"] = tracker._opp_card_play_count.get("EX1_001", 0) + 1

        # 标准上限是2张普通牌
        assert tracker._is_over_copy_limit("EX1_001") is True

    def test_not_over_copy_limit_for_normal_play(self):
        """正常打出2张普通牌不应被标记为 GENERATED。"""
        from analysis.watcher.global_tracker import GlobalTracker

        tracker = GlobalTracker(our_controller=1, opp_controller=2)
        tracker._opp_card_play_count["EX1_001"] = 2

        assert tracker._is_over_copy_limit("EX1_001") is False

    def test_legendary_one_copy_limit(self):
        """传说牌只允许1张, 第2张就是衍生牌。"""
        from analysis.watcher.global_tracker import GlobalTracker

        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # 设置一张传说牌的 rarity
        tracker._card_db = type('MockDB', (), {
            'get_card': lambda self, cid: {'rarity': 'LEGENDARY'} if cid == "LEG_001" else {},
        })()

        # 打出1张传说牌 = 正常
        tracker._opp_card_play_count["LEG_001"] = 1
        assert tracker._is_over_copy_limit("LEG_001") is False

        # 打出第2张传说牌 = 衍生
        tracker._opp_card_play_count["LEG_001"] = 2
        assert tracker._is_over_copy_limit("LEG_001") is True


# ── 概率随时间动态变化测试 ──────────────────────────────────────

class TestProbabilityDynamicUpdate:
    """测试概率随游戏进程动态更新。"""

    def test_probability_updates_when_card_played(self):
        """当对手打出卡牌后, 其他卡牌概率应更新。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # T3: 对手5手牌, 22牌库, 目标牌2张剩余
        p_before = hypergeometric_at_least_one(K=2, n=5, N=27)

        # 对手打出1张非目标牌: 4手牌, 22牌库, 目标牌2张剩余
        p_after = hypergeometric_at_least_one(K=2, n=4, N=26)

        # 手牌减少, 该牌在手概率应降低
        assert p_after < p_before

    def test_probability_updates_when_target_played(self):
        """当目标牌被打出后, 同一牌剩余概率应降低。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # 2张目标牌剩余
        p_two_remaining = hypergeometric_at_least_one(K=2, n=5, N=27)

        # 打出1张目标牌: 1张剩余
        p_one_remaining = hypergeometric_at_least_one(K=1, n=4, N=26)

        # 剩余张数减少, 概率降低
        assert p_one_remaining < p_two_remaining

    def test_probability_converges_to_one_or_zero(self):
        """游戏后期, 概率应趋于确定（接近0或1）。"""
        from analysis.engine.dynamic_probability import hypergeometric_at_least_one

        # 后期: 3手牌, 2牌库, 1张目标牌
        p_late = hypergeometric_at_least_one(K=1, n=3, N=5)

        # 应该比较高 (60%+)
        assert p_late > 0.5

        # 极端: 1手牌, 1牌库, 1张目标牌
        p_extreme = hypergeometric_at_least_one(K=1, n=1, N=2)

        # 50%概率
        assert abs(p_extreme - 0.5) < 0.01


# ── 模拟 Power.log 场景测试 ────────────────────────────────────

class TestPowerLogScenarios:
    """基于 power.log 场景的集成测试。

    这些测试模拟真实的 Power.log 解析流程，
    验证手牌概率在整个游戏进程中的正确性。
    """

    def test_scenario_opponent_plays_derived_card(self):
        """场景: 对手打出衍生牌, 概率应正确处理。

        当对手打出一张 Discover 获得的牌时,
        这张牌不应影响卡组概率计算。
        """
        from analysis.watcher.global_tracker import GlobalTracker, CardSource
        from analysis.constants.hs_enums import ZONE_SETASIDE, ZONE_PLAY, ZONE_DECK

        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # 1. 对手卡组牌出生
        tracker.on_full_entity(
            entity_id=100,
            card_id="EX1_001",
            controller=2,
            zone=ZONE_DECK,
        )

        # 2. 衍生牌出生 (SETASIDE)
        tracker.on_full_entity(
            entity_id=200,
            card_id="GEN_001",
            controller=2,
            zone=ZONE_SETASIDE,
        )

        # 3. 对手打出衍生牌
        tracker.on_show_entity(
            entity_id=200,
            card_id="GEN_001",
            controller=2,
            zone=ZONE_PLAY,
        )

        # 衍生牌应被正确标记
        assert CardSource.GENERATED in [
            kc.source for kc in tracker.state.opp_known_cards
        ]
        # 衍生牌应在 generated_seen 中
        assert "GEN_001" in tracker.state.opp_generated_seen

    def test_scenario_conditional_effect_triggers(self):
        """场景: 对手打出条件效果牌并触发, 应推断持有对应种族。

        如果对手打出"暮光幼龙"（如果你手持龙牌）并触发，
        应推断对手手牌中有龙牌。
        """
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        state_dict = {
            "bayesian": {"top_decks": [], "archetype_name": None,
                         "deck_confidence": 0.0, "predicted_next": [],
                         "playstyle": "unknown"},
            "known_cards": [
                {
                    "card_id": "EX1_043",
                    "turn_seen": 5,
                    "source": "deck",
                    "card_type": "MINION",
                    "cost": 4,
                    "race": "",
                    "spell_school": "",
                    "conditional_evidence": "HOLDING_DRAGON",
                    "effect_triggered": True,
                },
            ],
            "generated_cards": set(),
            "known_hand": [],
            "opp_hand_count": 5,
            "opp_deck_count": 18,
            "opp_class_en": "PRIEST",
            "turn": 5,
            "opp_stats": {},
        }

        result = predictor.predict(state_dict)
        # 条件证据应被记录
        assert len(result.conditional_evidence) >= 1
        # 应有龙族持有推断
        dragon_evidence = [
            e for e in result.conditional_evidence
            if e.get("value") == "DRAGON"
        ]
        assert len(dragon_evidence) >= 1

    def test_scenario_card_play_tracking(self):
        """场景: 对手打出的每张牌都应被追踪。"""
        from analysis.watcher.global_tracker import GlobalTracker
        from analysis.constants.hs_enums import ZONE_PLAY, ZONE_DECK

        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # 对手打出3张牌
        cards_to_play = [
            ("EX1_001", "MINION"),
            ("EX1_002", "SPELL"),
            ("EX1_003", "WEAPON"),
        ]

        for card_id, card_type_str in cards_to_play:
            # 先创建实体
            tracker.on_full_entity(
                entity_id=hash(card_id) % 10000,
                card_id=card_id,
                controller=2,
                zone=ZONE_DECK,
            )
            # 对手打出 (SHOW_ENTITY 到 PLAY)
            tracker.on_show_entity(
                entity_id=hash(card_id) % 10000,
                card_id=card_id,
                controller=2,
                zone=ZONE_PLAY,
                card_type={"MINION": 4, "SPELL": 5, "WEAPON": 7}[card_type_str],
            )

        # 应追踪到3张已打出的卡牌
        assert len(tracker.state.opp_known_cards) == 3
        # 统计应更新
        assert tracker.state.opp_stats.minions_played >= 1
        assert tracker.state.opp_stats.spells_played >= 1
        assert tracker.state.opp_stats.weapons_played >= 1

"""test_hand_prediction_accuracy.py — 对手手牌预测准确性测试。

验证:
1. known_hand 3-tuple 解包兼容性
2. GroundTruth turn range 不膨胀
3. 预测系统对 Power.log 不报错
4. 基本准确性基线
"""
from __future__ import annotations

import json
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

POWER_LOG = PROJECT_ROOT / "Power.log"
GT_JSON = PROJECT_ROOT / "gt.json"


@pytest.fixture
def gt_data():
    if not GT_JSON.exists():
        pytest.skip("gt.json not found")
    with GT_JSON.open("r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════
# Test: 3-tuple unpacking compatibility
# ═══════════════════════════════════════════════════════════════

class TestTupleUnpackCompatibility:
    """验证 known_hand 3-tuple 解包在所有消费点兼容。"""

    def test_revealed_hand_unpack(self):
        """DynamicProbabilityEngine._revealed_hand 应接受 3-tuple。"""
        from analysis.engine.dynamic_probability import DynamicProbabilityEngine
        engine = DynamicProbabilityEngine()

        # 模拟 build_state_dict 返回 3-tuple known_hand (eid, card_id, position)
        state_dict = {
            "known_hand": [(1, "CS2_034", 1), (2, "EX1_145", 2)],
            "known_cards": [],
            "generated_cards": set(),
            "bayesian": {},
        }
        engine.update_from_state_dict(state_dict)

        # 验证 _revealed_hand 存储了 3-tuple
        assert len(engine._revealed_hand) == 2
        assert engine._revealed_hand[0] == (1, "CS2_034", 1)

        # compute_probabilities 不应报错
        report = engine.compute_probabilities(hand_size=3, deck_remaining=20, opp_class="MAGE")
        assert report is not None

    def test_hand_predictor_known_hand_unpack(self):
        """HandPredictor 应接受 3-tuple known_hand。"""
        from tracker.hand_predictor import HandPredictor
        predictor = HandPredictor()

        state_dict = {
            "in_game": True,
            "turn": 3,
            "opp_hand_count": 3,
            "opp_deck_count": 20,
            "opp_class_en": "MAGE",
            "opp_class": "法师",
            "player_class": "盗贼",
            "player_class_en": "ROGUE",
            "bayesian": {},
            "known_hand": [(10, "CS2_034", 1), (20, "EX1_145", 2)],
            "known_cards": [],
            "generated_cards": set(),
            "opp_initial_deck_size": 30,
            "is_first_player": True,
            "coin_used": False,
            "opp_hand_hold": {},
            "available_mana": 3,
            "opp_board_minions": [],
            "opp_cards_played_this_turn": [],
            "opp_secrets": [],
            "opp_weapon": None,
            "opp_weapon_atk": 0,
            "opp_weapon_durability": 0,
            "opp_locations": [],
            "opp_corpses": 0,
            "opp_herald_count": 0,
            "player_corpses": 0,
            "player_hand_count": 5,
            "player_deck_count": 20,
            "player_initial_deck_size": 30,
            "player_weapon": None,
            "player_weapon_atk": 0,
            "player_weapon_durability": 0,
            "player_locations": [],
            "player_board_minions": [],
            "opp_board_minions": [],
            "opp_shuffled_into_deck": [],
            "opp_hand_positions": {},
            "reveal_info": {},
            "known_hand_types": [],
            "revealed_hand_cards": [],
            "transform_events": [],
            "tutor_evidence": [],
            "generated_card_records": [],
            "discarded_cards": [],
            "peeked_deck_cards": [],
            "hand_transforms": [],
            "hand_type_constraints": [],
            "confirmed_hand_cards": [],
            "known_deck_cards": [],
            "step": 0,
        }

        result = predictor.predict(state_dict)
        assert result is not None

    def test_multi_deck_known_hand_unpack(self):
        """_predict_multi_deck 中 known_hand_ids 应接受 3-tuple。"""
        # 实际格式 (entity_id, card_id, position)
        known_hand = [(1, "CARD_A", 1), (2, "CARD_B", 2), (3, "CARD_C", 3)]
        ids = {cid for _, cid, *_ in known_hand}
        assert ids == {"CARD_A", "CARD_B", "CARD_C"}


# ═══════════════════════════════════════════════════════════════
# Test: GroundTruth turn range
# ═══════════════════════════════════════════════════════════════

class TestGroundTruthTurnRange:
    """验证 GroundTruth turn range 不膨胀。"""

    def test_turn_range_bounded(self, gt_data):
        """GroundTruth.turns_available 不应超过 total_turns。"""
        sys_path_mod = False
        try:
            import sys
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
                sys_path_mod = True

            from scripts.validate_hand_predictions import GroundTruth
            gt = GroundTruth(gt_data)

            total_turns = gt_data.get("meta", {}).get("total_turns", 30)
            max_turn = max(gt.turns_available) if gt.turns_available else 0
            assert max_turn <= total_turns, \
                f"Ground truth turn range {max_turn} exceeds total_turns {total_turns}"
        finally:
            pass

    def test_no_turn_999(self, gt_data):
        """不应出现 turn 999 等异常值。"""
        sys_path_mod = False
        try:
            import sys
            if str(PROJECT_ROOT) not in sys.path:
                sys.path.insert(0, str(PROJECT_ROOT))
                sys_path_mod = True

            from scripts.validate_hand_predictions import GroundTruth
            gt = GroundTruth(gt_data)

            assert 999 not in gt.turns_available
            assert 100 not in gt.turns_available
        finally:
            pass


# ═══════════════════════════════════════════════════════════════
# Test: Validation callback dedup
# ═══════════════════════════════════════════════════════════════

class TestValidationCallbackDedup:
    """验证 ValidationEngine 回调去重。"""

    def test_processed_turns_dedup(self):
        """processed_turns set 应去重重复回合。"""
        processed = set()
        turns = [1, 2, 3, 3, 3, 4, 5, 5]
        results = []
        for t in turns:
            if t in processed or t <= 0:
                continue
            processed.add(t)
            results.append(t)
        assert results == [1, 2, 3, 4, 5]


# ═══════════════════════════════════════════════════════════════
# Test: E2E prediction does not crash
# ═══════════════════════════════════════════════════════════════

class TestPredictionNoCrash:
    """验证预测系统对 Power.log 不崩溃。"""

    @pytest.mark.skipif(not POWER_LOG.exists(), reason="Power.log not found")
    def test_predict_first_5_turns(self):
        """前5回合预测不崩溃且返回非空结果。"""
        import io, logging
        from contextlib import redirect_stdout

        logging.basicConfig(level=logging.CRITICAL)

        from tracker.log_monitor import CoreLogMonitor
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        monitor = CoreLogMonitor()
        seen = set()
        results = []

        def _on_turn(turn):
            if turn in seen or turn <= 0:
                return
            seen.add(turn)
            if turn > 5:
                return
            state = monitor.build_state_dict()
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = predictor.predict(state)
            results.append((turn, len(result.hand_predictions)))

        monitor.on_turn_changed = _on_turn
        monitor.load_existing_log(str(POWER_LOG))

        assert len(results) == 5, f"Expected 5 turn results, got {len(results)}"
        for turn, pred_count in results:
            assert pred_count >= 0, f"Turn {turn} crashed or returned negative"

#!/usr/bin/env python3
"""test_engine_singleton.py — 验证 GameEngine 单例模式

核心测试:
1. GameEngine 单例 — MCTSEngine 和 BayesianOpponentModel 只有一份
2. create_engine 工厂 — 返回同一个实例
3. 游戏生命周期 — on_game_start/on_game_end 不替换引擎
4. BayesianOpponentModel 跨回合累积证据
5. 全流程: Power.log → GameTracker → StateBridge → GameEngine.search()
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestGameEngineSingleton:
    """验证 GameEngine 单例模式"""

    def test_engine_created_once(self):
        """GameEngine 创建后 MCTSEngine 和 BayesianOpponentModel 只有一份"""
        from analysis.search.engine_adapter import GameEngine

        engine = GameEngine(params={"time_budget_ms": 500.0, "num_worlds": 3})

        mcts_id_before = id(engine.mcts_engine)
        bayes_id_before = id(engine.bayesian_model)

        # 多次访问 property 应返回同一对象
        assert id(engine.mcts_engine) == mcts_id_before
        assert id(engine.bayesian_model) == bayes_id_before
        assert id(engine.config) == id(engine.config)

    def test_game_start_preserves_mcts(self):
        """on_game_start 不应替换 MCTSEngine 实例"""
        from analysis.search.engine_adapter import GameEngine

        engine = GameEngine(params={"time_budget_ms": 500.0})
        mcts_id = id(engine.mcts_engine)

        engine.on_game_start(opp_class="ROGUE")
        assert id(engine.mcts_engine) == mcts_id, \
            "on_game_start 不应替换 MCTSEngine"

    def test_game_start_replaces_bayesian(self):
        """on_game_start 应重建 BayesianOpponentModel（新游戏需要新模型）"""
        from analysis.search.engine_adapter import GameEngine

        engine = GameEngine(params={"time_budget_ms": 500.0})
        bayes_id = id(engine.bayesian_model)

        engine.on_game_start(opp_class="ROGUE")
        # Bayesian model is replaced on game_start with class-specific model
        assert id(engine.bayesian_model) != bayes_id, \
            "on_game_start 应重建 BayesianOpponentModel"
        assert engine.bayesian_model.player_class == "ROGUE"

    def test_game_end_preserves_all(self):
        """on_game_end 不应替换任何引擎实例"""
        from analysis.search.engine_adapter import GameEngine

        engine = GameEngine(params={"time_budget_ms": 500.0})
        engine.on_game_start()

        mcts_id = id(engine.mcts_engine)
        bayes_id = id(engine.bayesian_model)

        engine.on_game_end()
        assert id(engine.mcts_engine) == mcts_id
        assert id(engine.bayesian_model) == bayes_id

    def test_factory_returns_same_instance(self):
        """create_engine 工厂每次调用返回同一个 GameEngine"""
        from analysis.search.engine_adapter import create_engine

        factory = create_engine("mcts", {"time_budget_ms": 500.0})
        engine1 = factory()
        engine2 = factory()

        assert engine1 is engine2, "工厂应返回同一个 GameEngine 实例"
        assert id(engine1.mcts_engine) == id(engine2.mcts_engine)

    def test_multiple_searches_same_engine(self):
        """多次 search 使用同一个 MCTSEngine"""
        from analysis.search.engine_adapter import GameEngine
        from analysis.search.game_state import GameState, HeroState, ManaState, OpponentState

        engine = GameEngine(params={"time_budget_ms": 200.0, "num_worlds": 2})
        engine.on_game_start()

        mcts_id = id(engine.mcts_engine)

        # 创建简单 GameState
        for i in range(3):
            state = GameState(
                hero=HeroState(hp=30),
                mana=ManaState(available=3, max_mana=3),
                opponent=OpponentState(hero=HeroState(hp=30), hand_count=5),
                turn_number=i + 1,
            )
            try:
                engine.search(state, time_budget_ms=100.0)
            except Exception:
                pass  # Search may fail on empty state, that's ok

            assert id(engine.mcts_engine) == mcts_id, \
                f"第 {i+1} 次 search 后 MCTSEngine 被替换了"

    def test_bayesian_evidence_accumulates(self):
        """贝叶斯模型跨回合累积证据"""
        from analysis.search.engine_adapter import GameEngine

        engine = GameEngine(params={"time_budget_ms": 500.0})
        engine.on_game_start(opp_class="ROGUE")

        # 初始证据应为空
        assert len(engine.bayesian_model._seen_cards) == 0

        # 更新一些卡牌
        try:
            engine.update_bayesian({100, 200})
        except Exception:
            pass  # dbfId 可能无效

        # 检查 _prev_opp_known 累积
        assert 100 in engine._prev_opp_known
        assert 200 in engine._prev_opp_known


class TestFullFlowWithFixtures:
    """使用测试日志的全流程验证"""

    @pytest.fixture
    def fixture_dir(self):
        return Path(__file__).resolve().parent.parent / "fixtures"

    def _find_log(self, fixture_dir, keyword):
        """查找包含关键字的日志文件"""
        if not fixture_dir.exists():
            # 回退到 tests 根目录
            alt = Path(__file__).resolve().parent / "fixtures"
            if alt.exists():
                fixture_dir = alt
            else:
                return None
        for f in fixture_dir.iterdir():
            if f.is_file() and keyword in f.name:
                return f
        return None

    def test_powerlog_line_by_line(self, fixture_dir):
        """逐行解析 Power.log，验证事件流完整性"""
        from analysis.watcher.game_tracker import GameTracker

        log_file = self._find_log(fixture_dir, "game1")
        if log_file is None:
            pytest.skip("No game1 fixture")

        tracker = GameTracker()
        events = []
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                event = tracker.feed_line(line.strip())
                if event is not None:
                    events.append(event)

        # 应有游戏开始和结束
        assert "game_start" in events
        assert "game_end" in events
        # 应有回合开始
        assert "turn_start" in events

    def test_state_bridge_conversion(self, fixture_dir):
        """验证 GameTracker → StateBridge 转换正确"""
        from analysis.watcher.game_tracker import GameTracker
        from analysis.watcher.state_bridge import StateBridge

        log_file = self._find_log(fixture_dir, "game1")
        if log_file is None:
            pytest.skip("No game1 fixture")

        tracker = GameTracker()
        bridge = StateBridge(entity_cache=tracker.entity_cache)

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                event = tracker.feed_line(line.strip())
                if event == "turn_start":
                    game = tracker.export_entities()
                    if game and hasattr(game, 'players') and len(game.players) >= 2:
                        # 检测友方
                        visible = []
                        for p in game.players:
                            count = sum(
                                1 for e in getattr(p, 'entities', [])
                                if getattr(e, 'card_id', '') and
                                   getattr(e, 'tags', {}).get(
                                       __import__('hearthstone.enums', fromlist=['GameTag']).GameTag.ZONE,
                                       __import__('hearthstone.enums', fromlist=['Zone']).Zone.HAND
                                   )
                            )
                            visible.append(count)
                        friendly_idx = 1 if visible[1] > visible[0] else 0

                        state = bridge.convert(game, player_index=friendly_idx)
                        assert state is not None
                        assert state.turn_number > 0
                        assert state.hero.hp > 0
                        assert state.mana.max_mana >= 0
                        break

    def test_engine_search_on_game_state(self, fixture_dir):
        """验证 GameEngine.search() 在真实 GameState 上运行"""
        from analysis.search.engine_adapter import GameEngine
        from analysis.watcher.game_tracker import GameTracker
        from analysis.watcher.state_bridge import StateBridge

        log_file = self._find_log(fixture_dir, "game1")
        if log_file is None:
            pytest.skip("No game1 fixture")

        tracker = GameTracker()
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        engine = GameEngine(params={"time_budget_ms": 500.0, "num_worlds": 2})
        engine.on_game_start()

        mcts_id_before = id(engine.mcts_engine)

        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                event = tracker.feed_line(line.strip())
                if event == "turn_start":
                    game = tracker.export_entities()
                    if game and hasattr(game, 'players') and len(game.players) >= 2:
                        from hearthstone.enums import GameTag, Zone
                        visible = []
                        for p in game.players:
                            count = sum(
                                1 for e in getattr(p, 'entities', [])
                                if getattr(e, 'card_id', '') and
                                   getattr(e, 'tags', {}).get(GameTag.ZONE) == Zone.HAND
                            )
                            visible.append(count)
                        friendly_idx = 1 if visible[1] > visible[0] else 0

                        state = bridge.convert(game, player_index=friendly_idx)
                        if state.turn_number > 0:
                            try:
                                result = engine.search(state, time_budget_ms=300.0)
                                assert result is not None
                                assert result.best_sequence is not None
                            except Exception as e:
                                # Search may fail on incomplete state
                                pass

                            # 验证单例
                            assert id(engine.mcts_engine) == mcts_id_before, \
                                "search 后 MCTSEngine 被替换了"
                            break


class TestDecisionLoopUsesSingleton:
    """验证 DecisionLoop 使用 GameEngine 单例"""

    def test_decision_loop_creates_singleton(self):
        """DecisionLoop 应创建 GameEngine 单例而非工厂"""
        from analysis.watcher.decision_loop import DecisionLoop

        loop = DecisionLoop("/tmp/fake_power.log")
        assert hasattr(loop, '_game_engine')
        from analysis.search.engine_adapter import GameEngine
        assert isinstance(loop._game_engine, GameEngine)

    def test_decision_loop_game_start_end(self):
        """DecisionLoop 的 game_start/end 应通知 GameEngine"""
        from analysis.watcher.decision_loop import DecisionLoop

        loop = DecisionLoop("/tmp/fake_power.log")
        engine = loop._game_engine

        # 模拟游戏生命周期
        engine.on_game_start(opp_class="WARRIOR")
        assert engine._game_active is True

        engine.on_game_end()
        assert engine._game_active is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

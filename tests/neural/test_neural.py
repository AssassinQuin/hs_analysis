"""Tests for analysis/search/neural/ package"""

import math
import pytest

from analysis.search.neural import (
    NeuralMCTS, ModelRegistry, PolicyNet, ValueNet,
    compute_mcts_prior, compute_state_value, blend_ucb,
)
from analysis.search.neural.interfaces import RandomPolicyNet, HeuristicValueNet


class TestRandomPolicyNet:
    def test_uniform_distribution(self):
        net = RandomPolicyNet()
        probs = net.predict(
            state_vector=[0.0]*294,
            action_mask=[1.0, 1.0, 0.0, 1.0],
            action_features=[[0.0]*13]*4,
        )
        # RandomPolicyNet returns one entry per legal action (3 legal here)
        assert len(probs) == 3
        assert abs(probs[0] - 1/3) < 0.01  # 3 legal actions
        assert abs(sum(probs) - 1.0) < 0.01

    def test_not_loaded(self):
        net = RandomPolicyNet()
        assert not net.is_loaded

    def test_load_is_noop(self):
        net = RandomPolicyNet()
        net.load("/nonexistent/path")  # should not raise


class TestHeuristicValueNet:
    def test_default_state_value(self):
        net = HeuristicValueNet()
        v = net.predict([0.0]*294)
        assert -1.0 <= v <= 1.0

    def test_not_loaded(self):
        net = HeuristicValueNet()
        assert not net.is_loaded


class TestModelRegistry:
    def setup_method(self):
        # Reset singleton between tests for isolation
        ModelRegistry._instance = None

    def test_singleton(self):
        r1 = ModelRegistry.get()
        r2 = ModelRegistry.get()
        assert r1 is r2

    def test_default_no_models(self):
        reg = ModelRegistry.get()
        assert not reg.has_models()

    def test_fallback_policy(self):
        reg = ModelRegistry.get()
        assert isinstance(reg.policy, RandomPolicyNet)

    def test_fallback_value(self):
        reg = ModelRegistry.get()
        assert isinstance(reg.value, HeuristicValueNet)

    def test_reset(self):
        reg = ModelRegistry.get()
        reg.reset()
        assert not reg.has_models()


class TestNeuralMCTS:
    def test_no_models_fallback(self):
        mcts = NeuralMCTS()
        assert not mcts._has_models()

    def test_from_registry(self):
        ModelRegistry._instance = None
        mcts = NeuralMCTS.from_registry()
        assert not mcts._has_models()

    def test_with_none_models(self):
        mcts = NeuralMCTS(policy_net=None, value_net=None)
        assert not mcts._has_models()


class TestPUCT:
    def test_blend_ucb(self):
        # With high prior and low visits, should be high
        val1 = blend_ucb(q_value=0.5, prior=0.8, visit_count=1, c_puct=1.5)
        # With low prior and high visits, should be lower
        val2 = blend_ucb(q_value=0.5, prior=0.1, visit_count=100, c_puct=1.5)
        assert val1 > val2

    def test_blend_ucb_zero_visits(self):
        # Should handle zero visits (use prior with safety floor)
        val = blend_ucb(q_value=0.0, prior=0.5, visit_count=0, c_puct=1.5)
        assert isinstance(val, float)

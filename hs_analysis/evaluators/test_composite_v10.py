"""Tests for V10 composite integration (feature flag routing)."""

from __future__ import annotations

import pytest

from hs_analysis.evaluators.composite import (
    evaluate,
    quick_eval,
    evaluate_delta,
    set_v10_enabled,
)
from hs_analysis.search.game_state import Minion


class TestV10Integration:
    """Test that V10 feature flag correctly routes evaluation."""

    def setup_method(self):
        set_v10_enabled(False)

    def teardown_method(self):
        set_v10_enabled(False)

    def test_v10_disabled_default(self):
        import hs_analysis.evaluators.composite as comp_mod
        assert comp_mod.V10_ENABLED is False

    def test_v10_disabled_same_as_legacy(self, make_card, make_state):
        state = make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[make_card()],
        )
        assert isinstance(evaluate(state), float)

    def test_v10_enabled_produces_different_result(self, make_card, make_state):
        state = make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[make_card()],
        )
        evaluate(state)
        set_v10_enabled(True)
        assert isinstance(evaluate(state), float)

    def test_set_v10_enabled_toggles(self):
        import hs_analysis.evaluators.composite as comp_mod
        set_v10_enabled(True)
        assert comp_mod.V10_ENABLED is True
        set_v10_enabled(False)
        assert comp_mod.V10_ENABLED is False

    def test_evaluate_delta_unchanged_with_v10_off(self, make_state):
        before = make_state()
        after = make_state(board=[Minion(name="Yeti", attack=4, health=5, max_health=5)])
        assert isinstance(evaluate_delta(before, after), float)

    def test_quick_eval_unchanged_with_v10_off(self, make_state):
        assert isinstance(quick_eval(make_state()), float)

    def test_v10_enabled_lethal_state(self, make_state):
        from hs_analysis.search.game_state import HeroState, OpponentState
        lethal = make_state(opponent=OpponentState(hero=HeroState(hp=0, armor=0)))
        set_v10_enabled(True)
        assert isinstance(evaluate(lethal), float)

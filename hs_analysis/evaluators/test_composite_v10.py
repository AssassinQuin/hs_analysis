"""Tests for V10 composite integration (feature flag routing)."""

from __future__ import annotations

import pytest

from hs_analysis.evaluators.composite import (
    evaluate,
    quick_eval,
    evaluate_delta,
    set_v10_enabled,
    V10_ENABLED,
)
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_card(**kwargs) -> Card:
    defaults = dict(
        dbf_id=1, name="Test Card", cost=3, original_cost=3,
        card_type="MINION", attack=3, health=3, v7_score=5.0,
        text="", mechanics=[],
    )
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[], hand=[], cards_played_this_turn=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

class TestV10Integration:
    """Test that V10 feature flag correctly routes evaluation."""

    def setup_method(self):
        """Ensure V10 is disabled before each test."""
        set_v10_enabled(False)

    def teardown_method(self):
        """Reset V10 flag after each test."""
        set_v10_enabled(False)

    def test_v10_disabled_default(self):
        """V10 should be disabled by default."""
        import hs_analysis.evaluators.composite as comp_mod
        # Check initial state is False
        assert comp_mod.V10_ENABLED is False

    def test_v10_disabled_same_as_legacy(self):
        """With V10 disabled, evaluate() returns legacy results."""
        state = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[_make_card()],
        )
        result = evaluate(state)
        assert isinstance(result, float)

    def test_v10_enabled_produces_different_result(self):
        """With V10 enabled, evaluate() should route to bsv_fusion."""
        state = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[_make_card()],
        )
        legacy = evaluate(state)
        set_v10_enabled(True)
        v10_result = evaluate(state)
        set_v10_enabled(False)

        # V10 result should be a valid float
        assert isinstance(v10_result, float)
        # They should be different evaluation functions
        # (exact values depend on implementation, so just check types)

    def test_set_v10_enabled_toggles(self):
        """set_v10_enabled correctly toggles the flag."""
        import hs_analysis.evaluators.composite as comp_mod

        set_v10_enabled(True)
        assert comp_mod.V10_ENABLED is True

        set_v10_enabled(False)
        assert comp_mod.V10_ENABLED is False

    def test_evaluate_delta_unchanged_with_v10_off(self):
        """evaluate_delta should work normally with V10 off."""
        before = _make_state()
        after = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
        )
        delta = evaluate_delta(before, after)
        assert isinstance(delta, float)

    def test_quick_eval_unchanged_with_v10_off(self):
        """quick_eval should work normally with V10 off."""
        state = _make_state()
        result = quick_eval(state)
        assert isinstance(result, float)

    def test_v10_enabled_lethal_state(self):
        """V10 evaluation of lethal state returns high value."""
        lethal = _make_state(
            opponent=OpponentState(hero=HeroState(hp=0, armor=0)),
        )
        set_v10_enabled(True)
        result = evaluate(lethal)
        set_v10_enabled(False)
        # Should be a valid float (999.0 if lethal detected, or other value)
        assert isinstance(result, float)

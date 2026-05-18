"""Tests for keyword_interactions module."""
import pytest
from analysis.scorers.keyword_interactions import (
    INTERACTIONS,
    get_interaction_multiplier,
)


class TestInteractionTable:
    """Verify the INTERACTIONS table has expected entries."""

    def test_poisonous_divine_shield(self):
        assert INTERACTIONS[("poisonous", "divine_shield")] == 0.1

    def test_stealth_taunt(self):
        assert INTERACTIONS[("stealth", "taunt")] == 0.0

    def test_immune_taunt(self):
        assert INTERACTIONS[("immune", "taunt")] == 0.0

    def test_freeze_windfury(self):
        assert INTERACTIONS[("freeze", "windfury")] == 0.5

    def test_lifesteal_divine_shield_enemy(self):
        assert INTERACTIONS[("lifesteal", "divine_shield_enemy")] == 0.0

    def test_reborn_deathrattle(self):
        assert INTERACTIONS[("reborn", "deathrattle")] == 1.5

    def test_brann_battlecry(self):
        assert INTERACTIONS[("brann", "battlecry")] == 2.0

    def test_rivendare_deathrattle(self):
        assert INTERACTIONS[("rivendare", "deathrattle")] == 2.0

    def test_total_entries(self):
        assert len(INTERACTIONS) == 8


class TestGetInteractionMultiplier:
    """Verify get_interaction_multiplier logic."""

    def test_no_interaction_returns_1(self):
        result = get_interaction_multiplier(["charge"], ["taunt"])
        assert result == 1.0

    def test_empty_keywords_returns_1(self):
        result = get_interaction_multiplier([], [])
        assert result == 1.0

    def test_poisonous_vs_divine_shield(self):
        result = get_interaction_multiplier(["poisonous"], ["divine_shield"])
        assert result == 0.1

    def test_mixed_multiply(self):
        # brann + battlecry (2.0) AND reborn + deathrattle (1.5) = 3.0
        result = get_interaction_multiplier(
            ["brann", "reborn"],
            ["battlecry", "deathrattle"],
        )
        assert result == pytest.approx(3.0)

    def test_zero_multiplier_cascades(self):
        # stealth + taunt → 0.0, everything else irrelevant
        result = get_interaction_multiplier(
            ["stealth", "poisonous"],
            ["taunt", "divine_shield"],
        )
        assert result == pytest.approx(0.0)

    def test_case_insensitive(self):
        result = get_interaction_multiplier(["POISONOUS"], ["DIVINE_SHIELD"])
        assert result == 0.1

    def test_non_matching_returns_1(self):
        result = get_interaction_multiplier(["charge", "rush"], ["windfury"])
        assert result == 1.0

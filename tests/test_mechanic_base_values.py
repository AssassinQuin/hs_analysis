"""Tests for mechanic_base_values module."""
import math
import pytest
from hs_analysis.scorers.mechanic_base_values import (
    MECHANIC_FORMULAS,
    get_mechanic_base_value,
)


class TestMechanicFormulas:
    """Verify each formula computes correctly."""

    def test_imbue_single(self):
        result = get_mechanic_base_value("imbue", {"base_hp": 1.0, "k": 1})
        assert result == pytest.approx(1.0)

    def test_imbue_multiple(self):
        # 1.0 + 0.8 + 0.64 = 2.44
        result = get_mechanic_base_value("imbue", {"base_hp": 1.0, "k": 3})
        assert result == pytest.approx(2.44)

    def test_herald_zero_count(self):
        result = get_mechanic_base_value("herald", {"soldier_value": 2.0, "count": 0})
        assert result == pytest.approx(2.0)

    def test_herald_four_count(self):
        # 2.0 * (1 + 0.5 * floor(4/2)) = 2.0 * 2.0 = 4.0
        result = get_mechanic_base_value("herald", {"soldier_value": 2.0, "count": 4})
        assert result == pytest.approx(4.0)

    def test_shatter(self):
        # (3 * 2) * 1.3 = 7.8
        result = get_mechanic_base_value("shatter", {"half": 3.0})
        assert result == pytest.approx(7.8)

    def test_kindred(self):
        result = get_mechanic_base_value("kindred", {"base": 5.0, "match_prob": 0.4})
        assert result == pytest.approx(2.0)

    def test_rewind_max(self):
        result = get_mechanic_base_value("rewind", {"a": 3.0, "b": 7.0})
        assert result == pytest.approx(7.0)

    def test_dark_gift(self):
        result = get_mechanic_base_value("dark_gift", {"gift_values": [2.0, 4.0, 6.0]})
        assert result == pytest.approx(4.0)

    def test_dark_gift_empty(self):
        result = get_mechanic_base_value("dark_gift", {"gift_values": []})
        assert result == pytest.approx(0.0)

    def test_colossal(self):
        result = get_mechanic_base_value(
            "colossal", {"body": 5.0, "append": 2.0, "n": 3, "space_penalty": 0.8}
        )
        # (5 + 3*2) * 0.8 = 8.8
        assert result == pytest.approx(8.8)

    def test_dormant(self):
        result = get_mechanic_base_value(
            "dormant", {"awakened": 10.0, "survival_prob": 0.6}
        )
        assert result == pytest.approx(6.0)

    def test_quest(self):
        result = get_mechanic_base_value(
            "quest", {"reward": 8.0, "completion_prob": 0.5}
        )
        assert result == pytest.approx(4.0)


class TestGetMechanicBaseValue:
    """Test edge cases for get_mechanic_base_value."""

    def test_unknown_mechanic_returns_0(self):
        result = get_mechanic_base_value("nonexistent")
        assert result == 0.0

    def test_none_params_defaults(self):
        result = get_mechanic_base_value("imbue")
        assert result == pytest.approx(1.0)  # base_hp=1.0, k=1

    def test_total_formulas(self):
        assert len(MECHANIC_FORMULAS) == 9

    def test_formula_exception_returns_0(self):
        # Pass params that would cause an error
        # e.g., pass string where math operation expected
        result = get_mechanic_base_value("shatter", {"half": "invalid"})
        assert result == 0.0

    def test_empty_params(self):
        result = get_mechanic_base_value("rewind", {})
        assert result == pytest.approx(0.0)  # max(0, 0) = 0

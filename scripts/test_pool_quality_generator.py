#!/usr/bin/env python3
"""Tests for pool_quality_generator.py

Run: python -m pytest scripts/test_pool_quality_generator.py -v
"""

import json, math, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pool_quality_generator import (
    load_cards, load_v7_scores, build_pools, compute_pool_metrics,
    generate_pool_report, load_turn_data,
    CARDS_PATH, V7_PATH, POOL_OUT, TURN_OUT,
    RACE_POOLS, SCHOOL_POOLS, TYPE_POOLS,
)


def test_pool_sizes_positive():
    """Pool sizes are positive integers."""
    report = generate_pool_report()
    for pool_name, metrics in report.items():
        assert metrics["pool_size"] > 0, f"{pool_name} has size {metrics['pool_size']}"
        assert isinstance(metrics["pool_size"], int)


def test_dragon_pool_avg_v7():
    """Dragon pool avg_v7 is a float > 0."""
    report = generate_pool_report()
    dragon_key = f"race_{RACE_POOLS[0]}"  # 龙
    assert dragon_key in report, f"Expected {dragon_key} in report"
    avg = report[dragon_key]["avg_v7"]
    assert isinstance(avg, float), f"avg_v7 should be float, got {type(avg)}"
    assert avg > 0, f"Dragon pool avg_v7 should be > 0, got {avg}"


def test_unknown_pool_returns_zero():
    """Unknown pool returns empty/zero defaults."""
    metrics = compute_pool_metrics([], {})
    assert metrics["avg_v7"] == 0.0
    assert metrics["pool_size"] == 0
    assert metrics["top_10_pct_v7"] == 0.0
    assert metrics["quality_std"] == 0.0


def test_top_10_pct_greater_than_avg():
    """top_10_pct >= avg for pools with > 5 cards."""
    report = generate_pool_report()
    for pool_name, metrics in report.items():
        if metrics["pool_size"] > 5:
            assert metrics["top_10_pct_v7"] >= metrics["avg_v7"], \
                f"{pool_name}: top_10_pct ({metrics['top_10_pct_v7']}) < avg ({metrics['avg_v7']})"


def test_output_json_valid():
    """Output JSON is valid and parseable."""
    # Run the generator
    from pool_quality_generator import main
    main()
    assert os.path.isfile(POOL_OUT)
    with open(POOL_OUT, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    assert len(data) > 0


def test_avg_turns_lookup():
    """avg_turns lookup works for known cards."""
    turn_data = load_turn_data()
    # There should be some cards with turn data
    if turn_data:
        first_key = list(turn_data.keys())[0]
        assert "optimal_turn" in turn_data[first_key]
        assert "confidence" in turn_data[first_key]
        assert turn_data[first_key]["optimal_turn"] > 0


def test_avg_turns_fallback():
    """avg_turns fallback for unknown cards."""
    turn_data = load_turn_data()
    # Non-existent dbfId should not be in turn_data
    assert "99999999" not in turn_data


def test_idempotent():
    """Re-running produces same output."""
    from pool_quality_generator import main
    main()
    with open(POOL_OUT, encoding="utf-8") as f:
        first = json.load(f)
    main()
    with open(POOL_OUT, encoding="utf-8") as f:
        second = json.load(f)
    assert first == second

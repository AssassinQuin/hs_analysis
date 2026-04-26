#!/usr/bin/env python3
"""Unit tests for score_provider module.

Run: python3 scripts/test_score_provider.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

# migrated to tests/

from analysis.engine.state import GameState
from analysis.models.card import Card
from analysis.utils.score_provider import ScoreProvider, load_scores_into_hand


def test_basic_lookup():
    """V7 scores loaded and returned by dbf_id."""
    data = [
        {"dbfId": 100, "score": 5.5, "L6": 3.0},
        {"dbfId": 200, "score": 8.1, "L6": 7.0},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="score")
        assert sp.get_score(100) == 5.5
        assert sp.get_score(200) == 8.1
        assert sp.get_score(999) == 0.0
    finally:
        os.unlink(path)


def test_snake_case_dbf_id():
    """Handle entries using dbf_id (snake_case) instead of dbfId (camelCase)."""
    data = [{"dbf_id": 300, "score": 2.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="score")
        assert sp.get_score(300) == 2.0
    finally:
        os.unlink(path)


def test_lazy_loading():
    """Cache is None until first get_score call."""
    data = [{"dbfId": 1, "score": 1.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path)
        assert sp._cache is None
        sp.get_score(1)
        assert sp._cache is not None
    finally:
        os.unlink(path)


def test_missing_file():
    """Missing JSON file returns 0.0 for all scores (graceful degradation)."""
    sp = ScoreProvider("/nonexistent/file.json")
    assert sp.get_score(1) == 0.0
    assert sp.get_score(2) == 0.0


def test_malformed_score():
    """Non-numeric score defaults to 0.0 without crashing."""
    data = [{"dbfId": 10, "score": "bad"}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="score")
        assert sp.get_score(10) == 0.0
    finally:
        os.unlink(path)


def test_malformed_dbf_id():
    """Non-numeric dbfId is skipped gracefully."""
    data = [{"dbfId": "not_a_number", "score": 5.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="score")
        assert sp.get_score(0) == 0.0  # nothing loaded
    finally:
        os.unlink(path)


def test_load_into_hand():
    """load_into_hand populates card.score for matched cards."""
    data = [
        {"dbfId": 500, "score": 3.3},
        {"dbfId": 501, "score": 6.6},
    ]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="score")
        cards = [Card(dbf_id=500, name="A"), Card(dbf_id=501, name="B"), Card(dbf_id=999, name="Missing")]
        count = sp.load_into_hand(cards)
        assert cards[0].score == 3.3
        assert cards[1].score == 6.6
        assert cards[2].score == 0.0
        assert count == 2
    finally:
        os.unlink(path)


def test_load_scores_into_hand_with_gamestate():
    """Convenience function works with a GameState object."""
    data = [{"dbfId": 600, "score": 9.9}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        state = GameState(hand=[Card(dbf_id=600, name="Test")])
        load_scores_into_hand(state, report_path=path)
        assert state.hand[0].score == 9.9
    finally:
        os.unlink(path)


def test_load_scores_into_hand_with_list():
    """Convenience function works with a plain list of Cards."""
    data = [{"dbfId": 700, "score": 4.4}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        cards = [Card(dbf_id=700, name="Test")]
        load_scores_into_hand(cards, report_path=path)
        assert cards[0].score == 4.4
    finally:
        os.unlink(path)


def test_l6_source():
    """Source='l6' reads the L6 field from JSON."""
    data = [{"dbfId": 800, "score": 10.0, "L6": 5.0}]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        path = f.name
    try:
        sp = ScoreProvider(path, score_field="L6")
        assert sp.get_score(800) == 5.0
    finally:
        os.unlink(path)


def test_empty_json_array():
    """Empty JSON array produces empty cache — all scores 0.0."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([], f)
        path = f.name
    try:
        sp = ScoreProvider(path)
        assert sp.get_score(1) == 0.0
    finally:
        os.unlink(path)


if __name__ == "__main__":
    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    failed = 0
    for func in test_funcs:
        try:
            func()
            print(f"  ✅ {func.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {func.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {func.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    if failed:
        sys.exit(1)

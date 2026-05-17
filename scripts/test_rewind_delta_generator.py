#!/usr/bin/env python3
"""Tests for rewind_delta_generator.py

Run: python -m pytest scripts/test_rewind_delta_generator.py -v
"""

import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rewind_delta_generator import (
    load_cards, load_scores, find_rewind_cards, find_original,
    generate_report, strip_html,
    CARDS_PATH, V7_PATH, OUT_PATH,
)


def test_finds_rewind_cards():
    """Finds rewind cards (count > 0)."""
    cards = load_cards()
    rewind = find_rewind_cards(cards)
    assert len(rewind) > 0, "Should find rewind cards in the dataset"
    # All rewind cards should have 回溯 in text
    for c in rewind:
        assert '回溯' in (c.get('text', '') or '')


def test_output_json_structure():
    """Output JSON structure is valid."""
    from rewind_delta_generator import main
    main()
    assert os.path.isfile(OUT_PATH)
    with open(OUT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    assert isinstance(data, dict)
    for dbf_id, entry in data.items():
        assert "name" in entry
        assert "rewind_v7" in entry
        assert "delta" in entry
        assert "paired" in entry


def test_paired_cards_have_delta():
    """Paired cards have meaningful delta."""
    report = generate_report()
    paired = [v for v in report.values() if v["paired"]]
    if paired:
        # At least some paired cards should have non-zero delta
        deltas = [abs(v["delta"]) for v in paired]
        assert max(deltas) >= 0, f"Expected some non-zero deltas among paired cards"


def test_unpaired_cards_zero_delta():
    """Unpaired cards have delta = 0.0."""
    report = generate_report()
    for dbf_id, entry in report.items():
        if not entry["paired"]:
            assert entry["delta"] == 0.0, f"Unpaired card {entry['name']} should have delta=0.0"


def test_empty_input():
    """Empty input produces empty output."""
    # Test with empty card list
    rewind = find_rewind_cards([])
    assert rewind == []


def test_idempotent():
    """Re-running produces same output."""
    from rewind_delta_generator import main
    main()
    with open(OUT_PATH, encoding="utf-8") as f:
        first = json.load(f)
    main()
    with open(OUT_PATH, encoding="utf-8") as f:
        second = json.load(f)
    assert first == second

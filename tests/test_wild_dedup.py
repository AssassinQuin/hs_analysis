#!/usr/bin/env python3
"""Tests for wild card database building from HSJSON data."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hs_analysis.data.build_wild_db import build_wild_db


def _make_data_dir(tmp: Path, standard_cards=None, wild_cards=None):
    """Create a fake data dir with zhCN/enUS collectible JSON."""
    standard_cards = standard_cards or []
    wild_cards = wild_cards or []

    zh_cards = []
    for i, c in enumerate(standard_cards):
        zh_cards.append({
            "id": f"STD_{i}", "dbfId": c.get("dbfId", i),
            "name": c.get("name", f"标准{i}"), "set": "CORE",
            "type": c.get("type", "MINION"), "cost": c.get("cost", 1),
            "attack": 1, "health": 1, "cardClass": "NEUTRAL",
        })
    for i, c in enumerate(wild_cards):
        zh_cards.append({
            "id": f"WLD_{i}", "dbfId": c.get("dbfId", 100 + i),
            "name": c.get("name", f"狂野{i}"), "set": "LEGACY",
            "type": c.get("type", "MINION"), "cost": c.get("cost", 3),
            "attack": 1, "health": 1, "cardClass": "NEUTRAL",
        })

    zh_dir = tmp / "zhCN"
    en_dir = tmp / "enUS"
    zh_dir.mkdir(parents=True)
    en_dir.mkdir(parents=True)

    (zh_dir / "cards.collectible.json").write_text(
        json.dumps(zh_cards, ensure_ascii=False), encoding="utf-8"
    )
    (en_dir / "cards.collectible.json").write_text(
        json.dumps(zh_cards, ensure_ascii=False), encoding="utf-8"
    )
    return tmp


class TestBuildWildDb(unittest.TestCase):

    def test_separates_wild_from_standard(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _make_data_dir(
                Path(tmp),
                standard_cards=[{"dbfId": 1, "name": "标准1"}],
                wild_cards=[
                    {"dbfId": 100, "name": "狂野1"},
                    {"dbfId": 101, "name": "狂野2"},
                ],
            )
            out_path = Path(tmp) / "wild.json"
            stats = build_wild_db(data_dir=data_dir, output_path=out_path)

            self.assertEqual(stats["standard_count"], 1)
            self.assertEqual(stats["wild_only"], 2)

            wild_cards = json.loads(out_path.read_text(encoding="utf-8"))
            names = {c["name"] for c in wild_cards}
            self.assertEqual(names, {"狂野1", "狂野2"})
            for c in wild_cards:
                self.assertEqual(c["format"], "wild")

    def test_no_wild_cards_produces_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = _make_data_dir(
                Path(tmp),
                standard_cards=[{"dbfId": 1, "name": "标准1"}],
            )
            out_path = Path(tmp) / "wild.json"
            stats = build_wild_db(data_dir=data_dir, output_path=out_path)
            self.assertEqual(stats["wild_only"], 0)

    def test_missing_data_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            build_wild_db(
                data_dir=Path("/nonexistent_data_dir"),
                output_path=Path("/tmp/test_out.json"),
            )


if __name__ == "__main__":
    unittest.main()

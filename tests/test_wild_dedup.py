#!/usr/bin/env python3
"""Tests for wild card deduplication logic in build_wild_db."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hs_analysis.data.build_wild_db import build_wild_db, load_dbfids


class TestLoadDbfids(unittest.TestCase):
    """Test dbfId loading from JSON card array."""

    def test_loads_ids(self):
        cards = [
            {"dbfId": 100, "name": "A"},
            {"dbfId": 200, "name": "B"},
            {"dbfId": 300, "name": "C"},
        ]
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump(cards, f)
            tmp = Path(f.name)

        try:
            ids = load_dbfids(tmp)
            self.assertEqual(ids, {100, 200, 300})
        finally:
            tmp.unlink()

    def test_missing_file_returns_empty(self):
        ids = load_dbfids(Path("/nonexistent/file.json"))
        self.assertEqual(ids, set())

    def test_empty_array(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump([], f)
            tmp = Path(f.name)

        try:
            ids = load_dbfids(tmp)
            self.assertEqual(ids, set())
        finally:
            tmp.unlink()


class TestBuildWildDb(unittest.TestCase):
    """Test wild card dedup logic."""

    def _make_files(self):
        """Create temp standard and all-cards files."""
        standard = [
            {"dbfId": 1, "name": "标准卡1", "type": "MINION",
             "cardClass": "NEUTRAL", "cost": 1},
            {"dbfId": 2, "name": "标准卡2", "type": "SPELL",
             "cardClass": "MAGE", "cost": 2},
        ]

        all_cards = [
            # Standard cards (also in standard pool → should be skipped)
            {"dbfId": 1, "name": "标准卡1", "type": "MINION",
             "cardClass": "NEUTRAL", "cost": 1, "standard": 1, "wild": 1},
            {"dbfId": 2, "name": "标准卡2", "type": "SPELL",
             "cardClass": "MAGE", "cost": 2, "standard": 1, "wild": 1},
            # Wild-only cards (not in standard → should be kept)
            {"dbfId": 100, "name": "狂野卡1", "type": "MINION",
             "cardClass": "NEUTRAL", "cost": 3, "standard": 0, "wild": 1},
            {"dbfId": 101, "name": "狂野卡2", "type": "SPELL",
             "cardClass": "WARLOCK", "cost": 4, "standard": 0, "wild": 1},
            # Standard-only (wild=0 → should be skipped)
            {"dbfId": 200, "name": "仅标准", "type": "MINION",
             "cardClass": "NEUTRAL", "cost": 1, "standard": 1, "wild": 0},
            # No dbfId → should be skipped
            {"name": "无ID卡", "type": "MINION",
             "cardClass": "NEUTRAL", "cost": 1, "standard": 0, "wild": 1},
        ]

        std_file = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        json.dump(standard, std_file)
        std_file.close()

        all_file = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        json.dump(all_cards, all_file)
        all_file.close()

        out_file = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        )
        out_file.close()

        return Path(std_file.name), Path(all_file.name), Path(out_file.name)

    def test_dedup_removes_standard(self):
        std_path, all_path, out_path = self._make_files()
        try:
            stats = build_wild_db(
                all_cards_path=all_path,
                standard_path=std_path,
                output_path=out_path,
                run_cleaner=False,
            )

            self.assertEqual(stats["total_input"], 6)
            self.assertEqual(stats["standard_dbfids"], 2)
            self.assertEqual(stats["skipped_standard"], 2)
            self.assertEqual(stats["skipped_no_wild"], 1)
            self.assertEqual(stats["skipped_no_dbf"], 1)
            self.assertEqual(stats["wild_only"], 2)

            # Verify output content
            wild_cards = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(len(wild_cards), 2)
            names = {c["name"] for c in wild_cards}
            self.assertEqual(names, {"狂野卡1", "狂野卡2"})

            # Verify standard/wild helper fields removed
            for c in wild_cards:
                self.assertNotIn("standard", c)
                self.assertNotIn("wild", c)
                self.assertEqual(c.get("format"), "wild")
        finally:
            std_path.unlink()
            all_path.unlink()
            out_path.unlink()

    def test_missing_all_cards_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            build_wild_db(
                all_cards_path=Path("/nonexistent.json"),
                standard_path=Path("/nonexistent2.json"),
                output_path=Path("/tmp/test_out.json"),
            )

    def test_no_wild_cards_produces_empty(self):
        """If all cards are standard → wild pool is empty."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump([{"dbfId": 1, "standard": 1, "wild": 0}], f)
            all_path = Path(f.name)

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump([{"dbfId": 1}], f)
            std_path = Path(f.name)

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            out_path = Path(f.name)

        try:
            stats = build_wild_db(
                all_cards_path=all_path,
                standard_path=std_path,
                output_path=out_path,
                run_cleaner=False,
            )
            self.assertEqual(stats["wild_only"], 0)
        finally:
            all_path.unlink()
            std_path.unlink()
            out_path.unlink()


if __name__ == "__main__":
    unittest.main()

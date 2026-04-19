#!/usr/bin/env python3
"""Tests for fetch_wild wild parameter support."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hs_analysis.data.fetch_wild import fetch_all_cards, fetch_page, normalize_card


class TestFetchPageWildParam(unittest.TestCase):
    """Test that fetch_page sends wild=1 when wild=True."""

    @patch("hs_analysis.data.fetch_wild.urllib.request.urlopen")
    def test_default_no_wild_param(self, mock_urlopen):
        """Default behavior: no 'wild' key in request body."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "data": {"cards": [], "total": 0},
        }).encode("utf-8")
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        fetch_page(1, size=10)
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = req.data.decode("utf-8")

        self.assertNotIn("wild", body)
        self.assertIn("page=1", body)
        self.assertIn("size=10", body)

    @patch("hs_analysis.data.fetch_wild.urllib.request.urlopen")
    def test_wild_true_adds_param(self, mock_urlopen):
        """When wild=True, 'wild=1' should be in request body."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "data": {"cards": [], "total": 0},
        }).encode("utf-8")
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        fetch_page(1, size=10, wild=True)
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = req.data.decode("utf-8")

        self.assertIn("wild=1", body)
        self.assertIn("page=1", body)
        self.assertIn("size=10", body)

    @patch("hs_analysis.data.fetch_wild.urllib.request.urlopen")
    def test_wild_false_no_param(self, mock_urlopen):
        """When wild=False, no 'wild' key in request body."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "success": True,
            "data": {"cards": [], "total": 0},
        }).encode("utf-8")
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        fetch_page(1, size=10, wild=False)
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = req.data.decode("utf-8")

        self.assertNotIn("wild", body)


class TestFetchAllCardsWildParam(unittest.TestCase):
    """Test that fetch_all_cards passes wild to fetch_page."""

    @patch("hs_analysis.data.fetch_wild.fetch_page")
    def test_default_calls_without_wild(self, mock_fetch_page):
        """Default fetch_all_cards should call fetch_page with wild=False."""
        mock_fetch_page.return_value = {
            "success": True,
            "data": {"cards": [], "total": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.json"
            norm_path = Path(tmpdir) / "norm.json"
            fetch_all_cards(
                output_raw=raw_path,
                output_normalized=norm_path,
            )

        mock_fetch_page.assert_called_once_with(1, size=50, wild=False)

    @patch("hs_analysis.data.fetch_wild.fetch_page")
    def test_wild_true_passes_through(self, mock_fetch_page):
        """fetch_all_cards(wild=True) should call fetch_page with wild=True."""
        mock_fetch_page.return_value = {
            "success": True,
            "data": {"cards": [], "total": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.json"
            norm_path = Path(tmpdir) / "norm.json"
            fetch_all_cards(
                output_raw=raw_path,
                output_normalized=norm_path,
                wild=True,
            )

        mock_fetch_page.assert_called_once_with(1, size=50, wild=True)

    @patch("hs_analysis.data.fetch_wild.fetch_page")
    def test_custom_page_size_and_delay(self, mock_fetch_page):
        """page_size and delay still work with wild param."""
        mock_fetch_page.return_value = {
            "success": True,
            "data": {"cards": [], "total": 0},
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            raw_path = Path(tmpdir) / "raw.json"
            norm_path = Path(tmpdir) / "norm.json"
            fetch_all_cards(
                output_raw=raw_path,
                output_normalized=norm_path,
                page_size=30,
                wild=True,
            )

        mock_fetch_page.assert_called_once_with(1, size=30, wild=True)


class TestNormalizeCardWildFields(unittest.TestCase):
    """Verify normalize_card captures standard/wild flags."""

    def test_standard_and_wild_flags(self):
        raw = {
            "gameid": 100,
            "cname": "Test Card",
            "mana": 3,
            "standard": 1,
            "wild": 1,
        }
        card = normalize_card(raw)
        self.assertEqual(card["standard"], 1)
        self.assertEqual(card["wild"], 1)

    def test_wild_only_flags(self):
        raw = {
            "gameid": 101,
            "cname": "Wild Only",
            "mana": 5,
            "standard": 0,
            "wild": 1,
        }
        card = normalize_card(raw)
        self.assertEqual(card["standard"], 0)
        self.assertEqual(card["wild"], 1)

    def test_missing_flags_default_zero(self):
        raw = {
            "gameid": 102,
            "cname": "No Flags",
            "mana": 2,
        }
        card = normalize_card(raw)
        self.assertEqual(card["standard"], 0)
        self.assertEqual(card["wild"], 0)


if __name__ == "__main__":
    unittest.main()

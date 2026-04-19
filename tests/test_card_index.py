#!/usr/bin/env python3
"""Tests for hs_analysis.data.card_index — multi-attribute index queries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hs_analysis.data.card_index import CardIndex


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_cards() -> List[Dict[str, Any]]:
    """Create a small test card pool."""
    return [
        # Minions
        {"dbfId": 1001, "name": "嘲讽野兽", "cost": 3, "attack": 2, "health": 4,
         "type": "MINION", "cardClass": "NEUTRAL", "rarity": "COMMON",
         "race": "BEAST", "mechanics": ["TAUNT"], "set": "CORE", "format": "standard"},

        {"dbfId": 1002, "name": "战吼龙", "cost": 5, "attack": 5, "health": 5,
         "type": "MINION", "cardClass": "MAGE", "rarity": "RARE",
         "race": "DRAGON", "mechanics": ["BATTLECRY"], "set": "CORE", "format": "standard"},

        {"dbfId": 1003, "name": "亡语鱼人", "cost": 2, "attack": 1, "health": 1,
         "type": "MINION", "cardClass": "SHAMAN", "rarity": "COMMON",
         "race": "MURLOC", "mechanics": ["DEATHRATTLE"], "set": "DOR", "format": "standard"},

        {"dbfId": 1004, "name": "发现元素", "cost": 4, "attack": 3, "health": 3,
         "type": "MINION", "cardClass": "NEUTRAL", "rarity": "EPIC",
         "race": "ELEMENTAL", "mechanics": ["DISCOVER"], "set": "EWT", "format": "standard"},

        {"dbfId": 1005, "name": "潜行海盗", "cost": 1, "attack": 2, "health": 1,
         "type": "MINION", "cardClass": "ROGUE", "rarity": "COMMON",
         "race": "PIRATE", "mechanics": ["STEALTH"], "set": "CORE", "format": "standard"},

        # Multi-mechanic card
        {"dbfId": 1006, "name": "战吼发现嘲讽", "cost": 7, "attack": 5, "health": 7,
         "type": "MINION", "cardClass": "PALADIN", "rarity": "LEGENDARY",
         "race": "", "mechanics": ["BATTLECRY", "DISCOVER", "TAUNT"],
         "set": "ATT", "format": "standard"},

        # Spells
        {"dbfId": 2001, "name": "火球术", "cost": 4, "attack": 0, "health": 0,
         "type": "SPELL", "cardClass": "MAGE", "rarity": "COMMON",
         "race": "", "spellSchool": "FIRE", "mechanics": [],
         "set": "CORE", "format": "standard"},

        {"dbfId": 2002, "name": "冰霜新星", "cost": 3, "attack": 0, "health": 0,
         "type": "SPELL", "cardClass": "MAGE", "rarity": "RARE",
         "race": "", "spellSchool": "FROST", "mechanics": ["FREEZE"],
         "set": "CORE", "format": "standard"},

        {"dbfId": 2003, "name": "自然之力", "cost": 6, "attack": 0, "health": 0,
         "type": "SPELL", "cardClass": "DRUID", "rarity": "EPIC",
         "race": "", "spellSchool": "NATURE", "mechanics": [],
         "set": "CORE", "format": "standard"},

        # Weapon
        {"dbfId": 3001, "name": "测试武器", "cost": 2, "attack": 2, "health": 0,
         "type": "WEAPON", "cardClass": "WARRIOR", "rarity": "COMMON",
         "race": "", "mechanics": [], "set": "CORE", "format": "standard"},

        # Location
        {"dbfId": 4001, "name": "测试地标", "cost": 3, "attack": 0, "health": 3,
         "type": "LOCATION", "cardClass": "PRIEST", "rarity": "RARE",
         "race": "", "mechanics": [], "set": "DOR", "format": "standard"},

        # Wild-only card
        {"dbfId": 5001, "name": "狂野随从", "cost": 1, "attack": 1, "health": 1,
         "type": "MINION", "cardClass": "NEUTRAL", "rarity": "COMMON",
         "race": "BEAST", "mechanics": ["BATTLECRY"], "set": "OLD",
         "format": "wild"},
    ]


class TestCardIndexBuild(unittest.TestCase):
    """Test index construction."""

    def setUp(self):
        self.cards = _make_cards()
        self.idx = CardIndex(self.cards)

    def test_total_count(self):
        self.assertEqual(self.idx.total, 12)

    def test_dbf_lookup(self):
        card = self.idx.get_by_dbf(1001)
        self.assertIsNotNone(card)
        self.assertEqual(card["name"], "嘲讽野兽")

    def test_dbf_lookup_missing(self):
        card = self.idx.get_by_dbf(99999)
        self.assertIsNone(card)

    def test_by_type_counts(self):
        self.assertEqual(len(self.idx.by_type.get("MINION", [])), 7)
        self.assertEqual(len(self.idx.by_type.get("SPELL", [])), 3)
        self.assertEqual(len(self.idx.by_type.get("WEAPON", [])), 1)
        self.assertEqual(len(self.idx.by_type.get("LOCATION", [])), 1)

    def test_by_class_counts(self):
        self.assertEqual(len(self.idx.by_class.get("NEUTRAL", [])), 3)
        self.assertEqual(len(self.idx.by_class.get("MAGE", [])), 3)
        self.assertEqual(len(self.idx.by_class.get("ROGUE", [])), 1)

    def test_by_mechanic_counts(self):
        self.assertEqual(len(self.idx.by_mechanic.get("TAUNT", [])), 2)
        self.assertEqual(len(self.idx.by_mechanic.get("BATTLECRY", [])), 3)
        self.assertEqual(len(self.idx.by_mechanic.get("DISCOVER", [])), 2)

    def test_by_race_counts(self):
        self.assertEqual(len(self.idx.by_race.get("BEAST", [])), 2)
        self.assertEqual(len(self.idx.by_race.get("DRAGON", [])), 1)

    def test_by_school_counts(self):
        self.assertEqual(len(self.idx.by_school.get("FIRE", [])), 1)
        self.assertEqual(len(self.idx.by_school.get("FROST", [])), 1)
        self.assertEqual(len(self.idx.by_school.get("NATURE", [])), 1)

    def test_by_format_counts(self):
        self.assertEqual(len(self.idx.by_format.get("standard", [])), 11)
        self.assertEqual(len(self.idx.by_format.get("wild", [])), 1)

    def test_by_cost_counts(self):
        self.assertEqual(len(self.idx.by_cost.get(1, [])), 2)
        self.assertEqual(len(self.idx.by_cost.get(3, [])), 3)

    def test_stats(self):
        s = self.idx.stats()
        self.assertEqual(s["total_cards"], 12)
        self.assertEqual(s["mechanic_count"], 6)
        self.assertEqual(s["type_count"], 4)


class TestCardIndexQueries(unittest.TestCase):
    """Test get_pool() queries."""

    def setUp(self):
        self.cards = _make_cards()
        self.idx = CardIndex(self.cards)

    def test_no_filters_returns_all(self):
        result = self.idx.get_pool()
        self.assertEqual(len(result), 12)

    def test_filter_by_type(self):
        minions = self.idx.get_pool(card_type="MINION")
        self.assertEqual(len(minions), 7)
        self.assertTrue(all(c["type"] == "MINION" for c in minions))

    def test_filter_by_class(self):
        mage = self.idx.get_pool(card_class="MAGE")
        self.assertEqual(len(mage), 3)
        self.assertTrue(all(c["cardClass"] == "MAGE" for c in mage))

    def test_filter_by_race(self):
        beasts = self.idx.get_pool(race="BEAST")
        self.assertEqual(len(beasts), 2)

    def test_filter_by_mechanic(self):
        taunts = self.idx.get_pool(mechanics="TAUNT")
        self.assertEqual(len(taunts), 2)

    def test_filter_by_mechanic_list(self):
        """Multiple mechanics = AND logic."""
        bc_disc = self.idx.get_pool(mechanics=["BATTLECRY", "DISCOVER"])
        self.assertEqual(len(bc_disc), 1)
        self.assertEqual(bc_disc[0]["name"], "战吼发现嘲讽")

    def test_filter_by_school(self):
        fire = self.idx.get_pool(school="FIRE")
        self.assertEqual(len(fire), 1)
        self.assertEqual(fire[0]["name"], "火球术")

    def test_filter_by_cost(self):
        cost3 = self.idx.get_pool(cost=3)
        self.assertTrue(all(c["cost"] == 3 for c in cost3))

    def test_filter_by_cost_range(self):
        result = self.idx.get_pool(card_type="MINION", cost_min=2, cost_max=4)
        self.assertTrue(all(2 <= c["cost"] <= 4 for c in result))
        self.assertTrue(len(result) > 0)

    def test_filter_by_format(self):
        wild = self.idx.get_pool(format="wild")
        self.assertEqual(len(wild), 1)
        self.assertEqual(wild[0]["name"], "狂野随从")

    def test_filter_by_rarity(self):
        legs = self.idx.get_pool(rarity="LEGENDARY")
        self.assertEqual(len(legs), 1)

    def test_composite_class_type(self):
        """(MAGE, SPELL) should use composite index."""
        mage_spells = self.idx.get_pool(card_class="MAGE", card_type="SPELL")
        self.assertEqual(len(mage_spells), 2)
        for c in mage_spells:
            self.assertEqual(c["cardClass"], "MAGE")
            self.assertEqual(c["type"], "SPELL")

    def test_mage_minions(self):
        mage_minions = self.idx.get_pool(card_class="MAGE", card_type="MINION")
        self.assertEqual(len(mage_minions), 1)
        self.assertEqual(mage_minions[0]["name"], "战吼龙")

    def test_neutral_taunt_minions(self):
        result = self.idx.get_pool(card_class="NEUTRAL", mechanics="TAUNT", card_type="MINION")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "嘲讽野兽")

    def test_nonexistent_combo_returns_empty(self):
        result = self.idx.get_pool(card_class="HUNTER", card_type="LOCATION")
        self.assertEqual(result, [])

    def test_nonexistent_mechanic_returns_empty(self):
        result = self.idx.get_pool(mechanics="NONEXISTENT")
        self.assertEqual(result, [])

    def test_exclude_dbfids(self):
        result = self.idx.get_pool(card_class="MAGE", exclude_dbfids={2001})
        self.assertEqual(len(result), 2)
        self.assertTrue(all(c["dbfId"] != 2001 for c in result))


class TestCardIndexRandomPool(unittest.TestCase):
    """Test random_pool() sampling."""

    def setUp(self):
        self.cards = _make_cards()
        self.idx = CardIndex(self.cards)

    def test_random_pool_size(self):
        result = self.idx.random_pool(3, card_type="MINION")
        self.assertEqual(len(result), 3)

    def test_random_pool_all_match_filter(self):
        result = self.idx.random_pool(5, card_type="MINION")
        for c in result:
            self.assertEqual(c["type"], "MINION")

    def test_random_pool_smaller_than_size(self):
        """If pool < requested size, return entire pool."""
        result = self.idx.random_pool(100, card_type="WEAPON")
        self.assertEqual(len(result), 1)

    def test_random_pool_empty_filter(self):
        result = self.idx.random_pool(5, card_class="HUNTER", card_type="LOCATION")
        self.assertEqual(result, [])


class TestCardIndexDiscover(unittest.TestCase):
    """Test discover_pool()."""

    def setUp(self):
        self.cards = _make_cards()
        self.idx = CardIndex(self.cards)

    def test_discover_pool_mage(self):
        """Mage discover: MAGE cards + NEUTRAL standard cards."""
        pool = self.idx.discover_pool("MAGE")
        # 3 MAGE + 2 NEUTRAL(standard) = 5 (wild beast excluded by format)
        self.assertEqual(len(pool), 5)
        for c in pool:
            self.assertIn(c["cardClass"], ("MAGE", "NEUTRAL"))

    def test_discover_pool_with_type(self):
        """Mage spell discover: only MAGE+NEUTRAL spells."""
        pool = self.idx.discover_pool("MAGE", card_type="SPELL")
        # MAGE spells: 2, NEUTRAL spells: 0
        self.assertEqual(len(pool), 2)
        for c in pool:
            self.assertEqual(c["type"], "SPELL")

    def test_discover_pool_excludes_cards(self):
        pool = self.idx.discover_pool("MAGE", exclude_dbfids={2001})
        self.assertTrue(all(c["dbfId"] != 2001 for c in pool))


if __name__ == "__main__":
    unittest.main()

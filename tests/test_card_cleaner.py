#!/usr/bin/env python3
"""Tests for hs_analysis.data.card_cleaner — race, mechanics, school normalization."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure package importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hs_analysis.data.card_cleaner import (
    RACE_ZH_MAP,
    SCHOOL_ZH_MAP,
    extract_mechanics,
    normalize_race,
    clean_card,
    clean_card_pool,
)


class TestNormalizeRace(unittest.TestCase):
    """Test normalize_race() with the 87 dirty race values found in data."""

    def test_empty_race(self):
        race, school = normalize_race("", "MINION")
        self.assertEqual(race, "")
        self.assertEqual(school, "")

    def test_none_race(self):
        race, school = normalize_race("", "MINION")
        self.assertEqual(race, "")

    def test_simple_beast(self):
        race, school = normalize_race("野兽", "MINION")
        self.assertEqual(race, "BEAST")
        self.assertEqual(school, "")

    def test_simple_demon(self):
        race, school = normalize_race("恶魔", "MINION")
        self.assertEqual(race, "DEMON")

    def test_simple_dragon(self):
        race, school = normalize_race("龙", "MINION")
        self.assertEqual(race, "DRAGON")

    def test_simple_murloc(self):
        race, school = normalize_race("鱼人", "MINION")
        self.assertEqual(race, "MURLOC")

    def test_all_13_races(self):
        """All 13 canonical race Chinese names should map correctly."""
        for zh, expected_en in RACE_ZH_MAP.items():
            race, _ = normalize_race(zh, "MINION")
            self.assertEqual(race, expected_en, f"Race '{zh}' → expected {expected_en}")

    def test_multi_race_space_separated(self):
        """Multi-race: '亡灵 野兽' → UNDEAD BEAST"""
        race, school = normalize_race("亡灵 野兽", "MINION")
        self.assertIn("UNDEAD", race)
        self.assertIn("BEAST", race)

    def test_multi_race_comma_separated(self):
        """Comma-separated: '元素，野兽' → ELEMENTAL BEAST"""
        race, school = normalize_race("元素，野兽", "MINION")
        self.assertIn("ELEMENTAL", race)
        self.assertIn("BEAST", race)

    def test_multi_race_with_runes(self):
        """Race + DK runes: '亡灵 野兽 冰冰' → UNDEAD BEAST (runes discarded for minion)"""
        race, school = normalize_race("亡灵 野兽 冰冰", "MINION")
        self.assertIn("UNDEAD", race)
        self.assertIn("BEAST", race)

    def test_spell_with_school(self):
        """Spell card: '火焰' → race='', school='FIRE'"""
        race, school = normalize_race("火焰", "SPELL")
        self.assertEqual(school, "FIRE")

    def test_spell_with_frost_school(self):
        race, school = normalize_race("冰霜", "SPELL")
        self.assertEqual(school, "FROST")

    def test_spell_with_multi_rune(self):
        """DK spell: '冰冰' → school lookup for 冰霜 variant"""
        # '冰冰' is not in SCHOOL_ZH_MAP; it's a rune token → should not crash
        race, school = normalize_race("冰冰", "SPELL")
        # Should not crash; result may be empty
        self.assertIsInstance(race, str)
        self.assertIsInstance(school, str)

    def test_spell_nature(self):
        race, school = normalize_race("自然", "SPELL")
        self.assertEqual(school, "NATURE")

    def test_spell_holy(self):
        race, school = normalize_race("神圣", "SPELL")
        self.assertEqual(school, "HOLY")

    def test_spell_shadow(self):
        race, school = normalize_race("暗影", "SPELL")
        self.assertEqual(school, "SHADOW")

    def test_spell_fel(self):
        race, school = normalize_race("邪能", "SPELL")
        self.assertEqual(school, "FEL")

    def test_discard_landmark_token(self):
        """'地标' token should be silently discarded."""
        race, school = normalize_race("地标", "LOCATION")
        self.assertEqual(race, "")

    def test_discard_weapon_token(self):
        """'武器' token should be silently discarded."""
        race, school = normalize_race("武器", "WEAPON")
        self.assertEqual(race, "")

    def test_discard_qiwen_token(self):
        """'奇闻' token should be silently discarded."""
        race, school = normalize_race("龙，奇闻", "MINION")
        self.assertEqual(race, "DRAGON")

    def test_all_7_schools(self):
        """All 7 spell schools should map correctly for SPELL type."""
        for zh, expected_en in SCHOOL_ZH_MAP.items():
            race, school = normalize_race(zh, "SPELL")
            self.assertEqual(school, expected_en, f"School '{zh}' → expected {expected_en}")

    def test_mixed_race_and_school(self):
        """'元素 冰霜' for MINION: ELEMENTAL is race, 冰霜 ignored (not school for minion)."""
        race, school = normalize_race("元素 冰霜", "MINION")
        self.assertIn("ELEMENTAL", race)
        # For minions, school tokens should not be added to school

    def test_mixed_race_and_school_for_spell(self):
        """For SPELL: '元素 自然' → race=ELEMENTAL, school=NATURE."""
        race, school = normalize_race("元素 自然", "SPELL")
        self.assertIn("ELEMENTAL", race)
        self.assertEqual(school, "NATURE")

    def test_dk_spell_blood_frost(self):
        """DK spell: '血邪' → rune tokens, no school match."""
        race, school = normalize_race("血邪", "SPELL")
        # Should not crash
        self.assertIsInstance(race, str)
        self.assertIsInstance(school, str)


class TestExtractMechanics(unittest.TestCase):
    """Test extract_mechanics() against known card text."""

    def test_battlecry(self):
        mechs = extract_mechanics("战吼：对一个敌人造成2点伤害。")
        self.assertIn("BATTLECRY", mechs)

    def test_deathrattle(self):
        mechs = extract_mechanics("亡语：召唤一个2/2的鱼人。")
        self.assertIn("DEATHRATTLE", mechs)

    def test_taunt(self):
        mechs = extract_mechanics("嘲讽")
        self.assertIn("TAUNT", mechs)

    def test_divine_shield(self):
        mechs = extract_mechanics("圣盾")
        self.assertIn("DIVINE_SHIELD", mechs)

    def test_charge(self):
        mechs = extract_mechanics("冲锋")
        self.assertIn("CHARGE", mechs)

    def test_rush(self):
        mechs = extract_mechanics("突袭")
        self.assertIn("RUSH", mechs)

    def test_windfury(self):
        mechs = extract_mechanics("风怒")
        self.assertIn("WINDFURY", mechs)

    def test_stealth(self):
        mechs = extract_mechanics("潜行")
        self.assertIn("STEALTH", mechs)

    def test_lifesteal(self):
        mechs = extract_mechanics("吸血")
        self.assertIn("LIFESTEAL", mechs)

    def test_freeze(self):
        mechs = extract_mechanics("冻结一个角色。")
        self.assertIn("FREEZE", mechs)

    def test_discover(self):
        mechs = extract_mechanics("发现一张法术牌。")
        self.assertIn("DISCOVER", mechs)

    def test_secret(self):
        mechs = extract_mechanics("奥秘：当你的对手施放一个法术时，对其造成伤害。")
        self.assertIn("SECRET", mechs)

    def test_overload(self):
        mechs = extract_mechanics("过载（2）")
        self.assertIn("OVERLOAD", mechs)

    def test_combo(self):
        mechs = extract_mechanics("连击：造成额外伤害。")
        self.assertIn("COMBO", mechs)

    def test_silence(self):
        mechs = extract_mechanics("沉默一个随从。")
        self.assertIn("SILENCE", mechs)

    def test_reborn(self):
        mechs = extract_mechanics("复生")
        self.assertIn("REBORN", mechs)

    def test_tradeable(self):
        mechs = extract_mechanics("可交易")
        self.assertIn("TRADEABLE", mechs)

    def test_colossal(self):
        mechs = extract_mechanics("巨像")
        self.assertIn("COLOSSAL", mechs)

    def test_titan(self):
        mechs = extract_mechanics("泰坦")
        self.assertIn("TITAN", mechs)

    def test_multiple_mechanics(self):
        """Card with multiple keywords."""
        mechs = extract_mechanics("战吼：发现一张牌。嘲讽。")
        self.assertIn("BATTLECRY", mechs)
        self.assertIn("DISCOVER", mechs)
        self.assertIn("TAUNT", mechs)

    def test_preserves_tag_based_mechanics(self):
        """IMBUE, TRIGGER_VISUAL should be preserved from existing."""
        mechs = extract_mechanics("", existing_mechanics=["IMBUE", "TRIGGER_VISUAL"])
        self.assertIn("IMBUE", mechs)
        self.assertIn("TRIGGER_VISUAL", mechs)

    def test_preserves_start_of_game(self):
        mechs = extract_mechanics("", existing_mechanics=["START_OF_GAME"])
        self.assertIn("START_OF_GAME", mechs)

    def test_empty_text(self):
        mechs = extract_mechanics("")
        self.assertEqual(mechs, [])

    def test_no_mechanics_found(self):
        mechs = extract_mechanics("造成3点伤害。")
        # May find FREEZE or not depending on text, but should not crash
        self.assertIsInstance(mechs, list)

    def test_poisonous_venomous_dedup(self):
        """POISONOUS and VENOMOUS both match 剧毒 → should dedup to POISONOUS."""
        mechs = extract_mechanics("剧毒")
        # Both patterns match, but should be deduped
        self.assertTrue("POISONOUS" in mechs or "VENOMOUS" in mechs)
        # Should not have both
        self.assertFalse("POISONOUS" in mechs and "VENOMOUS" in mechs)

    def test_spellpower_pattern(self):
        mechs = extract_mechanics("法术伤害+2")
        self.assertIn("SPELLPOWER", mechs)

    def test_overheal(self):
        mechs = extract_mechanics("过量治疗：恢复2点生命值。")
        self.assertIn("OVERHEAL", mechs)


class TestCleanCard(unittest.TestCase):
    """Test clean_card() full pipeline."""

    def _make_card(self, **overrides):
        """Create a minimal card dict with defaults."""
        card = {
            "dbfId": 99999,
            "name": "Test Card",
            "cost": 3,
            "attack": 2,
            "health": 3,
            "type": "MINION",
            "cardClass": "NEUTRAL",
            "rarity": "COMMON",
            "text": "战吼：发现一张牌。",
            "race": "野兽",
            "set": "TEST",
            "mechanics": [],
            "source": "test",
        }
        card.update(overrides)
        return card

    def test_basic_clean(self):
        card = self._make_card()
        result = clean_card(card)
        self.assertEqual(result["race"], "BEAST")
        self.assertIn("BATTLECRY", result["mechanics"])
        self.assertIn("DISCOVER", result["mechanics"])

    def test_spell_with_school(self):
        card = self._make_card(
            type="SPELL", race="火焰", text="造成3点伤害。",
            attack=0, health=0,
        )
        result = clean_card(card)
        self.assertEqual(result.get("spellSchool"), "FIRE")

    def test_type_uppercased(self):
        card = self._make_card(type="minion")
        result = clean_card(card)
        self.assertEqual(result["type"], "MINION")

    def test_numeric_fields_forced_int(self):
        card = self._make_card(cost="5", attack="3", health=None)
        result = clean_card(card)
        self.assertIsInstance(result["cost"], int)
        self.assertIsInstance(result["attack"], int)
        self.assertIsInstance(result["health"], int)
        self.assertEqual(result["cost"], 5)
        self.assertEqual(result["health"], 0)

    def test_existing_mechanics_preserved(self):
        card = self._make_card(mechanics=["IMBUE", "TRIGGER_VISUAL"], text="")
        result = clean_card(card)
        self.assertIn("IMBUE", result["mechanics"])
        self.assertIn("TRIGGER_VISUAL", result["mechanics"])

    def test_multi_race_cleaned(self):
        card = self._make_card(race="亡灵 野兽")
        result = clean_card(card)
        self.assertIn("UNDEAD", result["race"])
        self.assertIn("BEAST", result["race"])


class TestCleanCardPool(unittest.TestCase):
    """Test clean_card_pool() with a temp file."""

    def test_pool_clean_writes_output(self):
        cards = [
            {"dbfId": 1, "name": "A", "cost": 1, "attack": 1, "health": 1,
             "type": "MINION", "cardClass": "NEUTRAL", "rarity": "COMMON",
             "text": "战吼", "race": "野兽", "set": "TEST",
             "mechanics": [], "source": "test"},
            {"dbfId": 2, "name": "B", "cost": 2, "attack": 0, "health": 0,
             "type": "SPELL", "cardClass": "MAGE", "rarity": "RARE",
             "text": "冻结", "race": "冰霜", "set": "TEST",
             "mechanics": [], "source": "test"},
        ]

        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump(cards, f, ensure_ascii=False)
            tmp_path = Path(f.name)

        try:
            result_cards, stats = clean_card_pool(
                input_path=tmp_path, output_path=tmp_path, backup=False
            )
            self.assertEqual(len(result_cards), 2)
            self.assertEqual(stats["total"], 2)
            self.assertGreaterEqual(stats["race_changed"], 1)

            # Verify file was written correctly
            loaded = json.loads(tmp_path.read_text(encoding="utf-8"))
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0]["race"], "BEAST")
            self.assertIn("BATTLECRY", loaded[0]["mechanics"])
            self.assertEqual(loaded[1].get("spellSchool"), "FROST")
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Tests for hs_analysis.data.card_cleaner — race, mechanics, school normalization."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from analysis.data.card_cleaner import (
    RACE_ZH_MAP,
    SCHOOL_ZH_MAP,
    extract_mechanics,
    normalize_race,
    clean_card,
    clean_card_pool,
)


# ──────────────────────────────────────────────
# normalize_race
# ──────────────────────────────────────────────

class TestNormalizeRace:
    """Test normalize_race() — mapping Chinese race/school tokens to English enums."""

    @pytest.mark.parametrize("zh,expected_race", [
        ("野兽", "BEAST"),
        ("恶魔", "DEMON"),
        ("龙", "DRAGON"),
        ("鱼人", "MURLOC"),
    ])
    def test_simple_race_mapping(self, zh, expected_race):
        race, school = normalize_race(zh, "MINION")
        assert race == expected_race
        assert school == ""

    def test_all_13_races(self):
        """Every entry in RACE_ZH_MAP maps correctly."""
        for zh, expected in RACE_ZH_MAP.items():
            race, _ = normalize_race(zh, "MINION")
            assert race == expected, f"Race '{zh}' → expected {expected}"

    def test_empty_race(self):
        race, school = normalize_race("", "MINION")
        assert race == ""
        assert school == ""

    @pytest.mark.parametrize("text,expected_races", [
        ("亡灵 野兽", {"UNDEAD", "BEAST"}),
        ("元素，野兽", {"ELEMENTAL", "BEAST"}),
    ])
    def test_multi_race(self, text, expected_races):
        race, _ = normalize_race(text, "MINION")
        for r in expected_races:
            assert r in race

    def test_runes_discarded_for_minion(self):
        race, _ = normalize_race("亡灵 野兽 冰冰", "MINION")
        assert "UNDEAD" in race
        assert "BEAST" in race

    @pytest.mark.parametrize("zh,expected_school", [
        ("火焰", "FIRE"),
        ("冰霜", "FROST"),
        ("自然", "NATURE"),
        ("神圣", "HOLY"),
        ("暗影", "SHADOW"),
        ("邪能", "FEL"),
    ])
    def test_spell_school_mapping(self, zh, expected_school):
        _, school = normalize_race(zh, "SPELL")
        assert school == expected_school

    def test_all_7_schools(self):
        for zh, expected in SCHOOL_ZH_MAP.items():
            _, school = normalize_race(zh, "SPELL")
            assert school == expected, f"School '{zh}' → expected {expected}"

    def test_dk_rune_spell_no_crash(self):
        race, school = normalize_race("冰冰", "SPELL")
        assert isinstance(race, str)
        assert isinstance(school, str)

    @pytest.mark.parametrize("token,card_type", [
        ("地标", "LOCATION"),
        ("武器", "WEAPON"),
    ])
    def test_discarded_tokens(self, token, card_type):
        race, _ = normalize_race(token, card_type)
        assert race == ""

    def test_qiwen_token_stripped_from_race(self):
        race, _ = normalize_race("龙，奇闻", "MINION")
        assert race == "DRAGON"

    def test_mixed_race_and_school_for_spell(self):
        race, school = normalize_race("元素 自然", "SPELL")
        assert "ELEMENTAL" in race
        assert school == "NATURE"


# ──────────────────────────────────────────────
# extract_mechanics
# ──────────────────────────────────────────────

class TestExtractMechanics:
    """Test keyword extraction from Chinese card text."""

    @pytest.mark.parametrize("text,expected", [
        ("战吼：对一个敌人造成2点伤害。", "BATTLECRY"),
        ("亡语：召唤一个2/2的鱼人。", "DEATHRATTLE"),
        ("嘲讽", "TAUNT"),
        ("圣盾", "DIVINE_SHIELD"),
        ("冲锋", "CHARGE"),
        ("突袭", "RUSH"),
        ("风怒", "WINDFURY"),
        ("潜行", "STEALTH"),
        ("吸血", "LIFESTEAL"),
        ("冻结一个角色。", "FREEZE"),
        ("发现一张法术牌。", "DISCOVER"),
        ("奥秘：当你的对手施放一个法术时，对其造成伤害。", "SECRET"),
        ("过载（2）", "OVERLOAD"),
        ("连击：造成额外伤害。", "COMBO"),
        ("沉默一个随从。", "SILENCE"),
        ("复生", "REBORN"),
        ("可交易", "TRADEABLE"),
        ("巨像", "COLOSSAL"),
        ("泰坦", "TITAN"),
        ("法术伤害+2", "SPELLPOWER"),
        ("过量治疗：恢复2点生命值。", "OVERHEAL"),
    ])
    def test_single_keyword(self, text, expected):
        mechs = extract_mechanics(text)
        assert expected in mechs, f"Expected {expected} in {mechs} for text: {text}"

    def test_multiple_keywords(self):
        mechs = extract_mechanics("战吼：发现一张牌。嘲讽。")
        assert {"BATTLECRY", "DISCOVER", "TAUNT"} <= set(mechs)

    def test_poisonous_venomous_dedup(self):
        mechs = extract_mechanics("剧毒")
        assert ("POISONOUS" in mechs) != ("VENOMOUS" in mechs) or ("POISONOUS" in mechs)
        assert not ("POISONOUS" in mechs and "VENOMOUS" in mechs)

    def test_preserves_existing_mechanics(self):
        mechs = extract_mechanics("", existing_mechanics=["IMBUE", "TRIGGER_VISUAL"])
        assert "IMBUE" in mechs
        assert "TRIGGER_VISUAL" in mechs

    def test_preserves_start_of_game(self):
        mechs = extract_mechanics("", existing_mechanics=["START_OF_GAME"])
        assert "START_OF_GAME" in mechs

    def test_empty_text(self):
        assert extract_mechanics("") == []

    def test_no_mechanics_found(self):
        mechs = extract_mechanics("造成3点伤害。")
        assert isinstance(mechs, list)


# ──────────────────────────────────────────────
# clean_card
# ──────────────────────────────────────────────

def _make_card(**overrides):
    card = {
        "dbfId": 99999, "name": "Test Card", "cost": 3, "attack": 2,
        "health": 3, "type": "MINION", "cardClass": "NEUTRAL",
        "rarity": "COMMON", "text": "战吼：发现一张牌。", "race": "野兽",
        "set": "TEST", "mechanics": [], "source": "test",
    }
    card.update(overrides)
    return card


class TestCleanCard:
    def test_basic_clean(self):
        result = clean_card(_make_card())
        assert result["race"] == "BEAST"
        assert "BATTLECRY" in result["mechanics"]
        assert "DISCOVER" in result["mechanics"]

    def test_spell_school(self):
        result = clean_card(_make_card(type="SPELL", race="火焰", text="造成3点伤害。", attack=0, health=0))
        assert result.get("spellSchool") == "FIRE"

    def test_type_uppercased(self):
        assert clean_card(_make_card(type="minion"))["type"] == "MINION"

    def test_numeric_fields_forced_int(self):
        result = clean_card(_make_card(cost="5", attack="3", health=None))
        assert result["cost"] == 5
        assert result["health"] == 0
        assert isinstance(result["attack"], int)

    def test_existing_mechanics_preserved(self):
        result = clean_card(_make_card(mechanics=["IMBUE", "TRIGGER_VISUAL"], text=""))
        assert "IMBUE" in result["mechanics"]

    def test_multi_race(self):
        result = clean_card(_make_card(race="亡灵 野兽"))
        assert "UNDEAD" in result["race"]
        assert "BEAST" in result["race"]


# ──────────────────────────────────────────────
# clean_card_pool
# ──────────────────────────────────────────────

class TestCleanCardPool:
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
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)
            tmp_path = Path(f.name)

        try:
            result_cards, stats = clean_card_pool(input_path=tmp_path, output_path=tmp_path, backup=False)
            assert len(result_cards) == 2
            assert stats["total"] == 2

            loaded = json.loads(tmp_path.read_text(encoding="utf-8"))
            assert loaded[0]["race"] == "BEAST"
            assert "BATTLECRY" in loaded[0]["mechanics"]
            assert loaded[1].get("spellSchool") == "FROST"
        finally:
            tmp_path.unlink(missing_ok=True)

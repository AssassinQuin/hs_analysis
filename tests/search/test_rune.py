"""Tests for rune.py — DK 符文 (Rune) system."""

from __future__ import annotations
import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)


from analysis.card.engine.state import GameState
from analysis.card.engine.mechanics._data import (
    RUNE_MAP,
    filter_by_rune,
    get_rune_type,
    check_last_played_rune,
    parse_rune_discover_target,
)


def _card(spell_school: str = "", dbf_id: int = 0, **kw) -> dict:
    return {"spellSchool": spell_school, "dbfId": dbf_id, **kw}


class TestRuneMap:
    def test_frost(self):
        assert RUNE_MAP["FROST"] == "冰霜符文"

    def test_shadow(self):
        assert RUNE_MAP["SHADOW"] == "邪恶符文"

    def test_fire(self):
        assert RUNE_MAP["FIRE"] == "鲜血符文"


class TestGetRuneType:
    def test_frost_school(self):
        assert get_rune_type(_card(spell_school="FROST")) == "冰霜符文"

    def test_shadow_school(self):
        assert get_rune_type(_card(spell_school="SHADOW")) == "邪恶符文"

    def test_fire_school(self):
        assert get_rune_type(_card(spell_school="FIRE")) == "鲜血符文"

    def test_no_school(self):
        assert get_rune_type(_card()) is None

    def test_unknown_school(self):
        assert get_rune_type(_card(spell_school="ARCANE")) is None

    def test_case_insensitive(self):
        assert get_rune_type(_card(spell_school="frost")) == "冰霜符文"


class TestFilterByRune:
    def test_filter_frost(self):
        pool = [
            _card(spell_school="FROST", name="A"),
            _card(spell_school="SHADOW", name="B"),
            _card(spell_school="FROST", name="C"),
        ]
        result = filter_by_rune(pool, "冰霜符文")
        assert len(result) == 2
        assert all(c["spellSchool"] == "FROST" for c in result)

    def test_no_match(self):
        pool = [_card(spell_school="FROST")]
        result = filter_by_rune(pool, "鲜血符文")
        assert len(result) == 0

    def test_empty_pool(self):
        assert filter_by_rune([], "冰霜符文") == []


class TestCheckLastPlayedRune:
    def test_matching(self):
        state = GameState(last_played_card=_card(spell_school="FROST"))
        assert check_last_played_rune(state, "冰霜符文")

    def test_not_matching(self):
        state = GameState(last_played_card=_card(spell_school="FROST"))
        assert not check_last_played_rune(state, "邪恶符文")

    def test_no_last_card(self):
        state = GameState(last_played_card=None)
        assert not check_last_played_rune(state, "冰霜符文")


class TestParseRuneDiscoverTarget:
    def test_frost_discover(self):
        result = parse_rune_discover_target("发现一张冰霜符文牌")
        assert result == "冰霜符文"

    def test_unholy_discover(self):
        result = parse_rune_discover_target("战吼：发现一张邪恶符文牌")
        assert result == "邪恶符文"

    def test_no_rune(self):
        assert parse_rune_discover_target("发现一张随从牌") is None

    def test_empty(self):
        assert parse_rune_discover_target("") is None

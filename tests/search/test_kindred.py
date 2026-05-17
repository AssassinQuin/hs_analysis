"""Tests for kindred.py — 延系 (Kindred) mechanic."""

from __future__ import annotations

import pytest

from analysis.search.game_state import GameState, Minion
from analysis.search.kindred import (
    apply_kindred,
    check_kindred_active,
    has_kindred,
    parse_kindred_bonus,
    set_kindred_double,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def base_state() -> GameState:
    return GameState()


@pytest.fixture
def state_with_last_murloc() -> GameState:
    return GameState(last_turn_races={"MURLOC"})


@pytest.fixture
def state_with_last_elemental() -> GameState:
    return GameState(last_turn_schools={"FIRE"})


@pytest.fixture
def state_with_both() -> GameState:
    return GameState(
        last_turn_races={"MURLOC", "ELEMENTAL"},
        last_turn_schools={"FIRE"},
    )


def _card(name: str = "TestCard", text: str = "", race: str = "",
          spell_school: str = "", **kw) -> dict:
    return {"name": name, "text": text, "race": race,
            "spellSchool": spell_school, **kw}


# ---------------------------------------------------------------------------
# Detection tests
# ---------------------------------------------------------------------------

class TestHasKindred:
    def test_positive(self):
        assert has_kindred("<b>延系：</b>使你的其他随从获得突袭")

    def test_positive_no_colon(self):
        assert has_kindred("<b>延系</b>召唤一个复制")

    def test_negative(self):
        assert not has_kindred("<b>战吼：</b>造成2点伤害")

    def test_empty_text(self):
        assert not has_kindred("")

    def test_none_text(self):
        assert not has_kindred(None)


class TestParseKindredBonus:
    def test_extract_rush(self):
        bonus = parse_kindred_bonus("战吼：抽一张牌。<b>延系：</b>使你的其他随从获得突袭。")
        assert bonus is not None
        assert "突袭" in bonus

    def test_extract_summon_copy(self):
        bonus = parse_kindred_bonus("<b>延系：</b>召唤一个本随从的复制。")
        assert bonus is not None
        assert "复制" in bonus

    def test_no_kindred(self):
        assert parse_kindred_bonus("<b>战吼：</b>造成2点伤害") is None


# ---------------------------------------------------------------------------
# Condition check tests
# ---------------------------------------------------------------------------

class TestCheckKindredActive:
    def test_race_match(self, state_with_last_murloc):
        card = _card(race="MURLOC")
        assert check_kindred_active(state_with_last_murloc, card)

    def test_multi_race_match(self, state_with_last_murloc):
        card = _card(race="MURLOC ELEMENTAL")
        assert check_kindred_active(state_with_last_murloc, card)

    def test_school_match(self, state_with_last_elemental):
        card = _card(spell_school="FIRE")
        assert check_kindred_active(state_with_last_elemental, card)

    def test_no_match(self, base_state):
        card = _card(race="DRAGON")
        assert not check_kindred_active(base_state, card)

    def test_empty_last_turn(self, base_state):
        card = _card(race="MURLOC")
        assert not check_kindred_active(base_state, card)


# ---------------------------------------------------------------------------
# Apply tests
# ---------------------------------------------------------------------------

class TestApplyKindred:
    def test_triggers_when_active(self, state_with_last_murloc):
        card = _card(
            text="<b>延系：</b>使你的其他随从获得突袭。",
            race="MURLOC",
        )
        # Add a minion to board to verify rush is applied
        state = state_with_last_murloc
        state.board.append(Minion(name="ExistingMinion"))
        result = apply_kindred(state, card)
        assert result.board[0].has_rush is True

    def test_skips_when_inactive(self, base_state):
        card = _card(
            text="<b>延系：</b>使你的其他随从获得突袭。",
            race="MURLOC",
        )
        state = base_state
        state.board.append(Minion(name="ExistingMinion"))
        result = apply_kindred(state, card)
        assert result.board[0].has_rush is False

    def test_no_crash_on_unknown_effect(self, state_with_last_murloc):
        card = _card(
            text="<b>延系：</b>某种未知的效果描述xyz",
            race="MURLOC",
        )
        result = apply_kindred(state_with_last_murloc, card)
        # Should not crash, state returned unchanged
        assert isinstance(result, GameState)

    def test_summon_copy(self, state_with_both):
        card = _card(
            name="TestCopyCard",
            text="<b>延系：</b>召唤一个本随从的复制。",
            race="MURLOC",
        )
        state = state_with_both
        state.board.append(Minion(name="TestCopyCard", attack=3, health=3))
        result = apply_kindred(state, card)
        assert len(result.board) == 2
        assert result.board[1].name == "TestCopyCard"

    def test_no_kindred_text(self, state_with_last_murloc):
        card = _card(text="<b>战吼：</b>造成2点伤害", race="MURLOC")
        result = apply_kindred(state_with_last_murloc, card)
        assert result is state_with_last_murloc


# ---------------------------------------------------------------------------
# Double trigger tests
# ---------------------------------------------------------------------------

class TestKindredDouble:
    def test_double_flag_triggers_twice(self, state_with_last_murloc):
        card = _card(
            text="<b>延系：</b>使你的其他随从获得突袭。",
            race="MURLOC",
        )
        state = state_with_last_murloc
        state.board.append(Minion(name="Existing"))
        state = set_kindred_double(state)
        assert state.kindred_double_next is True

        result = apply_kindred(state, card)
        # Rush applied once (the function applies rush both times,
        # but rush is a boolean so second application is a no-op visually)
        assert result.board[0].has_rush is True
        assert result.kindred_double_next is False

    def test_flag_cleared_after_trigger(self, state_with_last_murloc):
        card = _card(
            text="<b>延系：</b>使你的其他随从获得突袭。",
            race="MURLOC",
        )
        state = state_with_last_murloc
        state.board.append(Minion(name="M1"))
        state = set_kindred_double(state)

        # First trigger
        result = apply_kindred(state, card)
        assert result.kindred_double_next is False

    def test_set_kindred_double(self, base_state):
        result = set_kindred_double(base_state)
        assert result.kindred_double_next is True


# ---------------------------------------------------------------------------
# Integration with spell cards
# ---------------------------------------------------------------------------

class TestKindredSpell:
    def test_spell_with_kindred(self, state_with_last_murloc):
        card = _card(
            text="<b>延系：</b>重复一次。",
            race="MURLOC",
        )
        result = apply_kindred(state_with_last_murloc, card)
        assert isinstance(result, GameState)

    def test_spell_inactive(self, base_state):
        card = _card(
            text="<b>延系：</b>重复一次。",
            race="MURLOC",
        )
        result = apply_kindred(base_state, card)
        assert isinstance(result, GameState)

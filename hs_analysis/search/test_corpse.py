"""Tests for corpse.py — 残骸 (Corpse) resource system."""

from __future__ import annotations

import pytest

from hs_analysis.search.game_state import GameState, Minion
from hs_analysis.search.corpse import (
    CorpseEffect,
    can_afford_corpses,
    gain_corpses,
    has_double_corpse_gen,
    parse_corpse_effects,
    parse_corpse_gain,
    resolve_corpse_effects,
    spend_corpses,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def state_with_corpses() -> GameState:
    return GameState(corpses=5)


@pytest.fixture
def state_empty_corpses() -> GameState:
    return GameState(corpses=0)


@pytest.fixture
def state_with_falric() -> GameState:
    state = GameState()
    state.board.append(Minion(name="法瑞克", attack=3, health=3))
    return state


def _dk_card(text: str = "", name: str = "DKCard", **kw) -> dict:
    return {"name": name, "text": text, "cardClass": "DEATHKNIGHT", **kw}


# ---------------------------------------------------------------------------
# Parsing tests
# ---------------------------------------------------------------------------

class TestParseCorpseEffects:
    def test_spend_2(self):
        effects = parse_corpse_effects("消耗2份残骸，使其获得黑暗之赐")
        assert len(effects) >= 1
        assert effects[0].cost == 2

    def test_spend_max_8(self):
        effects = parse_corpse_effects("消耗最多8份残骸，随机召唤一个随从")
        assert len(effects) >= 1
        assert effects[0].cost == 8
        assert effects[0].is_optional is True

    def test_no_corpse_text(self):
        effects = parse_corpse_effects("<b>战吼：</b>造成2点伤害")
        assert len(effects) == 0

    def test_empty_text(self):
        assert parse_corpse_effects("") == []
        assert parse_corpse_effects(None) == []

    def test_multiple_spend(self):
        text = "消耗2份残骸，效果A。消耗5份残骸，效果B"
        effects = parse_corpse_effects(text)
        assert len(effects) == 2
        assert effects[0].cost == 2
        assert effects[1].cost == 5


class TestParseCorpseGain:
    def test_gain_one(self):
        assert parse_corpse_gain("获得一份残骸") == 1

    def test_gain_specific(self):
        assert parse_corpse_gain("获得3份残骸") == 3

    def test_no_gain(self):
        assert parse_corpse_gain("消耗2份残骸") == 0

    def test_empty(self):
        assert parse_corpse_gain("") == 0
        assert parse_corpse_gain(None) == 0


# ---------------------------------------------------------------------------
# Resource management tests
# ---------------------------------------------------------------------------

class TestCanAfford:
    def test_affordable(self, state_with_corpses):
        assert can_afford_corpses(state_with_corpses, 3) is True

    def test_exact(self, state_with_corpses):
        assert can_afford_corpses(state_with_corpses, 5) is True

    def test_too_expensive(self, state_with_corpses):
        assert can_afford_corpses(state_with_corpses, 6) is False

    def test_zero_cost(self, state_empty_corpses):
        assert can_afford_corpses(state_empty_corpses, 0) is True


class TestSpendCorpses:
    def test_spend(self, state_with_corpses):
        result = spend_corpses(state_with_corpses, 3)
        assert result.corpses == 2

    def test_spend_all(self, state_with_corpses):
        result = spend_corpses(state_with_corpses, 5)
        assert result.corpses == 0

    def test_spend_more_than_available(self, state_with_corpses):
        # Should not go negative
        result = spend_corpses(state_with_corpses, 10)
        assert result.corpses == 0

    def test_does_not_mutate_original(self, state_with_corpses):
        original_corpses = state_with_corpses.corpses
        spend_corpses(state_with_corpses, 3)
        assert state_with_corpses.corpses == original_corpses


class TestGainCorpses:
    def test_gain(self, state_empty_corpses):
        result = gain_corpses(state_empty_corpses, 3)
        assert result.corpses == 3

    def test_gain_adds(self, state_with_corpses):
        result = gain_corpses(state_with_corpses, 2)
        assert result.corpses == 7

    def test_does_not_mutate_original(self, state_with_corpses):
        original_corpses = state_with_corpses.corpses
        gain_corpses(state_with_corpses, 2)
        assert state_with_corpses.corpses == original_corpses


# ---------------------------------------------------------------------------
# Double generation tests
# ---------------------------------------------------------------------------

class TestDoubleCorpseGen:
    def test_falric_on_board(self, state_with_falric):
        assert has_double_corpse_gen(state_with_falric) is True

    def test_no_falric(self):
        state = GameState()
        state.board.append(Minion(name="Other Minion", attack=2, health=2))
        assert has_double_corpse_gen(state) is False

    def test_empty_board(self):
        assert has_double_corpse_gen(GameState()) is False


# ---------------------------------------------------------------------------
# Resolution tests
# ---------------------------------------------------------------------------

class TestResolveCorpseEffects:
    def test_gain_card(self, state_empty_corpses):
        card = _dk_card(text="战吼：获得一份残骸。")
        result = resolve_corpse_effects(state_empty_corpses, card)
        assert result.corpses == 1

    def test_spend_if_affordable(self, state_with_corpses):
        card = _dk_card(text="消耗2份残骸，使其获得黑暗之赐")
        result = resolve_corpse_effects(state_with_corpses, card)
        assert result.corpses == 3  # 5 - 2

    def test_skip_if_not_affordable(self, state_empty_corpses):
        card = _dk_card(text="消耗2份残骸，使其获得黑暗之赐")
        result = resolve_corpse_effects(state_empty_corpses, card)
        assert result.corpses == 0  # no spend, no change

    def test_no_corpse_card(self, state_with_corpses):
        card = _dk_card(text="<b>战吼：</b>造成2点伤害")
        result = resolve_corpse_effects(state_with_corpses, card)
        assert result.corpses == 5  # unchanged

    def test_gain_plus_spend(self, state_with_corpses):
        card = _dk_card(text="获得一份残骸。消耗2份残骸，造成4点伤害。")
        result = resolve_corpse_effects(state_with_corpses, card)
        # 5 + 1 (gain) - 2 (spend) = 4
        assert result.corpses == 4

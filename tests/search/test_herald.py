import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)
"""Tests for herald mechanic."""


from analysis.card.models.card import Card
from analysis.card.engine.state import GameState, Minion
from analysis.card.engine.mechanics._data import (
    check_herald,
    apply_herald,
    HERALD_SOLDIERS,
)


def _make_herald_card(card_class="DEMONHUNTER"):
    """Helper: create a herald card."""
    return Card(
        dbf_id=8888,
        name="末世特使",
        cost=4,
        card_type="MINION",
        attack=3,
        health=3,
        text="<b>嘲讽</b>。<b>战吼：</b><b>兆示你的巨型随从</b>。",
        card_class=card_class,
        mechanics=["BATTLECRY", "COLOSSAL", "TAUNT"],
    )


def _make_non_herald_card():
    """Helper: create a non-herald card."""
    return Card(
        dbf_id=7777,
        name="普通随从",
        cost=2,
        card_type="MINION",
        attack=2,
        health=3,
        text="一个普通的随从。",
        mechanics=[],
    )


class TestCheckHerald:
    """Tests for check_herald."""

    def test_herald_text_returns_true(self):
        """Card with '兆示' in text returns True."""
        card = _make_herald_card()
        assert check_herald(card) is True

    def test_herald_mechanic_returns_true(self):
        """Card with HERALD in mechanics returns True."""
        card = Card(
            name="Herald Card",
            text="",
            mechanics=["HERALD"],
        )
        assert check_herald(card) is True

    def test_non_herald_returns_false(self):
        """Non-herald card returns False."""
        card = _make_non_herald_card()
        assert check_herald(card) is False


class TestApplyHerald:
    """Tests for apply_herald."""

    def test_increments_herald_count(self):
        """apply_herald increments herald_count by 1."""
        state = GameState()
        card = _make_herald_card()
        assert state.herald_count == 0

        state = apply_herald(state, card)
        assert state.herald_count == 1

    def test_summons_soldier_minion(self):
        """apply_herald summons a soldier minion to the board."""
        state = GameState()
        card = _make_herald_card("DEMONHUNTER")

        state = apply_herald(state, card)

        assert len(state.board) == 1
        assert state.board[0].name == "伊利达雷士兵"
        assert state.board[0].attack == 2
        assert state.board[0].health == 2

    def test_no_summon_if_board_full(self):
        """No soldier summoned if board is full (7 minions)."""
        state = GameState()
        for i in range(7):
            state.board.append(Minion(name=f"随从{i}", attack=1, health=1, max_health=1))
        card = _make_herald_card()

        state = apply_herald(state, card)

        assert len(state.board) == 7  # no change
        assert state.herald_count == 1  # counter still increments

    def test_herald_count_stacks(self):
        """Herald count stacks across multiple plays."""
        state = GameState()
        card1 = _make_herald_card("DEMONHUNTER")
        card2 = _make_herald_card("DEMONHUNTER")

        state = apply_herald(state, card1)
        assert state.herald_count == 1

        state = apply_herald(state, card2)
        assert state.herald_count == 2
        assert len(state.board) == 2  # two soldiers

    def test_soldier_stats_match_class(self):
        """Soldier stats match class lookup."""
        state = GameState()
        card = Card(
            name="Paladin Herald",
            text="兆示",
            card_class="PALADIN",
        )

        state = apply_herald(state, card)

        assert state.board[0].name == "白银之手新兵"
        assert state.board[0].attack == 2
        assert state.board[0].health == 2

    def test_non_herald_card_no_change(self):
        """apply_herald on non-herald card makes no changes."""
        state = GameState()
        card = _make_non_herald_card()

        state = apply_herald(state, card)

        assert state.herald_count == 0
        assert len(state.board) == 0

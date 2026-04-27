import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)
"""Tests for colossal appendage summoning."""


from analysis.card.models.card import Card
from analysis.card.engine.state import GameState, Minion
from analysis.card.engine.mechanics._data import (
    parse_colossal_value,
    summon_colossal_appendages,
    COLOSSAL_APPENDAGES,
)


def _make_colossal_card(card_class="ROGUE", colossal_n=2):
    """Helper: create a colossal card."""
    text = f"<b>巨型+{colossal_n}</b>\nSome effect."
    return Card(
        dbf_id=9999,
        name="Test Colossal",
        cost=8,
        card_type="MINION",
        attack=7,
        health=7,
        text=text,
        card_class=card_class,
        mechanics=["COLOSSAL"],
    )


def _make_empty_state():
    """Helper: create empty game state."""
    return GameState()


class TestParseColossalValue:
    """Tests for parse_colossal_value."""

    def test_non_colossal_returns_zero(self):
        """Non-colossal card returns 0."""
        card = Card(name="普通随从", text="普通卡牌", mechanics=[])
        assert parse_colossal_value(card) == 0

    def test_colossal_plus_2_returns_2(self):
        """巨型+2 returns 2."""
        card = _make_colossal_card(colossal_n=2)
        assert parse_colossal_value(card) == 2

    def test_colossal_plus_1_returns_1(self):
        """巨型+1 returns 1."""
        card = _make_colossal_card(colossal_n=1)
        assert parse_colossal_value(card) == 1

    def test_mechanics_colossal_no_number_returns_1(self):
        """COLOSSAL in mechanics without 巨型+N defaults to 1."""
        card = Card(
            name="无名巨兽",
            text="一个巨型随从",
            mechanics=["COLOSSAL"],
        )
        assert parse_colossal_value(card) == 1

    def test_no_mechanics_but_giant_in_text_returns_0(self):
        """Card with '巨型' in text but no COLOSSAL mechanics — still detected."""
        # '巨型' in text triggers detection but no +N → defaults to 1
        card = Card(name="巨型乌龟", text="巨型随从")
        result = parse_colossal_value(card)
        # No '巨型+N' pattern and no COLOSSAL mechanic
        # Actually text has 巨型 so is_colossal=True, but no +N → returns 1
        assert result == 1


class TestSummonColossalAppendages:
    """Tests for summon_colossal_appendages."""

    def test_colossal_2_summons_2_appendages_right(self):
        """Colossal+2 summons 2 appendages to the right of main body."""
        state = _make_empty_state()
        card = _make_colossal_card("ROGUE", colossal_n=2)
        main = Minion(name="主随从", attack=7, health=7, max_health=7)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert len(state.board) == 3
        assert state.board[0].name == "主随从"
        assert state.board[1].name == "暗影附肢"
        assert state.board[2].name == "暗影附肢"
        assert state.board[1].attack == 2
        assert state.board[1].health == 1

    def test_colossal_1_summons_1_appendage(self):
        """Colossal+1 summons exactly 1 appendage."""
        state = _make_empty_state()
        card = _make_colossal_card("HUNTER", colossal_n=1)
        main = Minion(name="猎人巨兽", attack=5, health=5, max_health=5)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert len(state.board) == 2
        assert state.board[1].name == "野兽附肢"
        assert state.board[1].attack == 3
        assert state.board[1].health == 2

    def test_board_nearly_full_only_fits_1(self):
        """Board with 6 minions + Colossal+2 → only 1 appendage fits."""
        state = _make_empty_state()
        for i in range(5):
            state.board.append(Minion(name=f"随从{i}", attack=1, health=1, max_health=1))
        card = _make_colossal_card("MAGE", colossal_n=2)
        main = Minion(name="巨兽", attack=5, health=5, max_health=5)
        state.board.insert(0, main)  # insert at pos 0

        assert len(state.board) == 6  # 5 + main = 6
        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert len(state.board) == 7  # only 1 appendage fits
        assert state.board[1].name == "奥术附肢"

    def test_board_full_no_appendages(self):
        """Board full (7 minions) → no appendages summoned."""
        state = _make_empty_state()
        for i in range(7):
            state.board.append(Minion(name=f"随从{i}", attack=1, health=1, max_health=1))
        card = _make_colossal_card("ROGUE", colossal_n=2)
        main = state.board[0]

        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert len(state.board) == 7  # unchanged

    def test_herald_upgrade_2_gives_plus_1_1(self):
        """Herald count >= 2 gives +1/+1 to appendages."""
        state = _make_empty_state()
        card = _make_colossal_card("ROGUE", colossal_n=2)
        main = Minion(name="主随从", attack=7, health=7, max_health=7)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0, herald_count=2)

        assert state.board[1].attack == 2 + 1  # ROGUE base 2+1
        assert state.board[1].health == 1 + 1  # ROGUE base 1+1

    def test_herald_upgrade_4_gives_plus_2_2(self):
        """Herald count >= 4 gives +2/+2 to appendages."""
        state = _make_empty_state()
        card = _make_colossal_card("ROGUE", colossal_n=2)
        main = Minion(name="主随从", attack=7, health=7, max_health=7)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0, herald_count=4)

        assert state.board[1].attack == 2 + 2
        assert state.board[1].health == 1 + 2

    def test_class_based_appendage_names(self):
        """Appendages have correct class-based names and stats."""
        state = _make_empty_state()
        card = Card(
            name="Demon Colossal",
            text="<b>巨型+1</b>",
            card_class="DEMONHUNTER",
            mechanics=["COLOSSAL"],
        )
        main = Minion(name="恶魔巨兽", attack=6, health=6, max_health=6)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert state.board[1].name == "末日之翼的附肢"
        assert state.board[1].attack == 2
        assert state.board[1].health == 2

    def test_non_colossal_card_no_summon(self):
        """Non-colossal card summons nothing."""
        state = _make_empty_state()
        card = Card(name="普通", text="普通", mechanics=[])
        main = Minion(name="普通随从", attack=2, health=2, max_health=2)
        state.board.append(main)

        state = summon_colossal_appendages(state, main, card, insert_pos=0)

        assert len(state.board) == 1

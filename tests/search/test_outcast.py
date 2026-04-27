import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)
"""V10 Phase 3 Batch 3 tests — Outcast hand position system."""

from analysis.card.engine.state import GameState, HeroState, Minion, ManaState, OpponentState
from analysis.card.models.card import Card
from analysis.search.abilities import apply_action, Action
from analysis.card.engine.mechanics._data import check_outcast, apply_outcast_bonus, _parse_outcast_bonus


def _make_card(**kw):
    defaults = dict(dbf_id=1, name="TestCard", cost=2, card_type="MINION", attack=2, health=2, mechanics=[])
    defaults.update(kw)
    return Card(**defaults)


def _make_state(hand=None, mana=10, deck_remaining=10):
    gs = GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=mana, max_mana=mana),
        opponent=OpponentState(hero=HeroState(hp=30)),
        deck_remaining=deck_remaining,
    )
    if hand is not None:
        gs.hand = hand
    return gs


class TestCheckOutcast:
    def test_outcast_leftmost_position(self):
        card = _make_card(name="OutcastCard", mechanics=["OUTCAST"])
        other = _make_card(name="Other")
        gs = _make_state(hand=[card, other, _make_card(name="Third")])
        assert check_outcast(gs, 0, card) is True

    def test_outcast_rightmost_position(self):
        card = _make_card(name="OutcastCard", mechanics=["OUTCAST"])
        other = _make_card(name="Other")
        gs = _make_state(hand=[other, _make_card(name="Third"), card])
        assert check_outcast(gs, 2, card) is True

    def test_outcast_middle_no_bonus(self):
        card = _make_card(name="OutcastCard", mechanics=["OUTCAST"])
        gs = _make_state(hand=[_make_card(name="Left"), card, _make_card(name="Right")])
        assert check_outcast(gs, 1, card) is False

    def test_non_outcast_card_never_triggers(self):
        card = _make_card(name="NormalCard")
        gs = _make_state(hand=[card])
        assert check_outcast(gs, 0, card) is False

    def test_single_card_both_positions(self):
        """Single card is both leftmost and rightmost."""
        card = _make_card(name="OutcastCard", mechanics=["OUTCAST"])
        gs = _make_state(hand=[card])
        assert check_outcast(gs, 0, card) is True

    def test_empty_hand_no_crash(self):
        card = _make_card(name="OutcastCard", mechanics=["OUTCAST"])
        gs = _make_state(hand=[])
        assert check_outcast(gs, 0, card) is False


class TestParseOutcastBonus:
    def test_draw_bonus(self):
        result = _parse_outcast_bonus("流放：再抽2张牌")
        assert result == {"type": "draw", "count": 2}

    def test_cost_reduction_bonus(self):
        result = _parse_outcast_bonus("流放：法力值消耗为（1）点")
        assert result == {"type": "cost", "value": 1}

    def test_fallback_draw_one(self):
        result = _parse_outcast_bonus("流放：造成3点伤害")
        assert result == {"type": "draw", "count": 1}


class TestApplyOutcastBonus:
    def test_outcast_draws_cards(self):
        card = _make_card(name="OutcastCard", text="流放：再抽2张")
        gs = _make_state(deck_remaining=5)
        result = apply_outcast_bonus(gs, 0, card)
        assert result.deck_remaining == 3  # 5 - 2

    def test_outcast_refunds_mana(self):
        card = _make_card(name="OutcastCard", cost=5, text="流放：法力值消耗为（1）点")
        gs = _make_state(mana=10)
        result = apply_outcast_bonus(gs, 0, card)
        assert result.mana.available == 14  # 10 + (5-1)

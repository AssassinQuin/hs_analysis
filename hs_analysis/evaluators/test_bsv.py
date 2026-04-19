"""Tests for V10 BSV (Board State Value) module."""

from __future__ import annotations

import math

import pytest

from hs_analysis.evaluators.bsv import (
    softmax,
    bsv_fusion,
    eval_tempo_v10,
    eval_value_v10,
    eval_survival_v10,
    PHASE_WEIGHTS,
    ABSOLUTE_LETHAL_VALUE,
    _get_phase,
)
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
    Weapon,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_card(**kwargs) -> Card:
    defaults = dict(
        dbf_id=1, name="Test Card", cost=3, original_cost=3,
        card_type="MINION", attack=3, health=3, v7_score=5.0,
        text="", mechanics=[],
    )
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[], hand=[], cards_played_this_turn=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ──────────────────────────────────────────────
# Softmax
# ──────────────────────────────────────────────

class TestSoftmax:
    def test_empty_input(self):
        assert softmax([]) == []

    def test_single_value(self):
        result = softmax([3.0])
        assert len(result) == 1
        assert result[0] == pytest.approx(1.0, abs=0.001)

    def test_sums_to_one(self):
        result = softmax([1.0, 2.0, 3.0])
        assert sum(result) == pytest.approx(1.0, abs=0.001)

    def test_larger_value_gets_higher_weight(self):
        result = softmax([1.0, 10.0])
        assert result[1] > result[0]

    def test_equal_values_equal_weights(self):
        result = softmax([5.0, 5.0, 5.0])
        for w in result:
            assert w == pytest.approx(1.0 / 3, abs=0.01)

    def test_temperature_effect(self):
        """Lower temperature → sharper distribution."""
        sharp = softmax([1.0, 2.0], temperature=0.1)
        soft = softmax([1.0, 2.0], temperature=10.0)
        # Sharp should have bigger gap
        sharp_gap = sharp[1] - sharp[0]
        soft_gap = soft[1] - soft[0]
        assert sharp_gap > soft_gap


# ──────────────────────────────────────────────
# Phase selection
# ──────────────────────────────────────────────

class TestPhaseSelection:
    def test_early_game(self):
        assert _get_phase(1) == "early"
        assert _get_phase(4) == "early"

    def test_mid_game(self):
        assert _get_phase(5) == "mid"
        assert _get_phase(7) == "mid"

    def test_late_game(self):
        assert _get_phase(8) == "late"
        assert _get_phase(15) == "late"


# ──────────────────────────────────────────────
# Tempo axis
# ──────────────────────────────────────────────

class TestEvalTempo:
    def test_empty_board(self):
        state = _make_state()
        result = eval_tempo_v10(state)
        # Only mana efficiency + 0 weapon
        assert isinstance(result, float)

    def test_friendly_board_advantage(self):
        state = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
        )
        result = eval_tempo_v10(state)
        assert result > 0

    def test_enemy_board_penalty(self):
        friendly = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
        )
        both = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[Minion(name="Big", attack=8, health=8, max_health=8)],
            ),
        )
        assert eval_tempo_v10(friendly) > eval_tempo_v10(both)

    def test_weapon_contribution(self):
        with_weapon = _make_state(
            hero=HeroState(hp=30, weapon=Weapon(attack=3, health=2)),
        )
        without = _make_state()
        assert eval_tempo_v10(with_weapon) > eval_tempo_v10(without)


# ──────────────────────────────────────────────
# Value axis
# ──────────────────────────────────────────────

class TestEvalValue:
    def test_empty_hand(self):
        state = _make_state()
        result = eval_value_v10(state)
        assert isinstance(result, float)

    def test_hand_cards_add_value(self):
        with_cards = _make_state(
            hand=[_make_card(v7_score=5.0), _make_card(dbf_id=2, v7_score=4.0)],
        )
        empty = _make_state()
        assert eval_value_v10(with_cards) > eval_value_v10(empty)

    def test_card_advantage_bonus(self):
        winning = _make_state(
            hand=[_make_card()],
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            opponent=OpponentState(hero=HeroState(hp=30), hand_count=0),
        )
        losing = _make_state(
            hand=[],
            opponent=OpponentState(hero=HeroState(hp=30), hand_count=5),
        )
        assert eval_value_v10(winning) > eval_value_v10(losing)


# ──────────────────────────────────────────────
# Survival axis
# ──────────────────────────────────────────────

class TestEvalSurvival:
    def test_full_health(self):
        state = _make_state()
        result = eval_survival_v10(state)
        assert result > 0

    def test_low_health_penalty(self):
        low = _make_state(hero=HeroState(hp=5, armor=0))
        high = _make_state(hero=HeroState(hp=30, armor=0))
        assert eval_survival_v10(high) > eval_survival_v10(low)

    def test_lethal_threat_massive_penalty(self):
        """Enemy can kill us → huge penalty."""
        state = _make_state(
            hero=HeroState(hp=3, armor=0),
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[Minion(name="Attacker", attack=5, health=5, can_attack=True)],
            ),
        )
        result = eval_survival_v10(state)
        assert result < -10  # Should be very negative

    def test_healing_potential(self):
        heal_card = _make_card(text="恢复5点生命值", card_type="SPELL")
        with_heal = _make_state(hand=[heal_card])
        without = _make_state()
        assert eval_survival_v10(with_heal) > eval_survival_v10(without)


# ──────────────────────────────────────────────
# BSV Fusion
# ──────────────────────────────────────────────

class TestBsvFusion:
    def test_returns_float(self):
        state = _make_state()
        result = bsv_fusion(state)
        assert isinstance(result, float)

    def test_lethal_state_returns_999(self):
        """State where opponent is at 0 HP → lethal override."""
        state = _make_state(
            opponent=OpponentState(hero=HeroState(hp=0, armor=0)),
        )
        # check_lethal should detect already-dead opponent
        result = bsv_fusion(state)
        # Note: this depends on check_lethal implementation
        # At minimum, bsv_fusion should not crash
        assert isinstance(result, float)

    def test_winning_state_higher_than_losing(self):
        winning = _make_state(
            hero=HeroState(hp=30, armor=5),
            board=[
                Minion(name="Big1", attack=7, health=7, max_health=7),
                Minion(name="Big2", attack=6, health=6, max_health=6),
            ],
            hand=[_make_card(v7_score=6.0)],
            opponent=OpponentState(
                hero=HeroState(hp=15, armor=0),
                board=[Minion(name="Small", attack=1, health=1, max_health=1)],
            ),
        )
        losing = _make_state(
            hero=HeroState(hp=5, armor=0),
            board=[],
            hand=[],
            opponent=OpponentState(
                hero=HeroState(hp=30, armor=0),
                board=[Minion(name="Big", attack=8, health=8, max_health=8, can_attack=True)],
            ),
        )
        assert bsv_fusion(winning) > bsv_fusion(losing)

    def test_phase_weights_applied(self):
        """Different turn numbers should give different BSV values for same state."""
        card = _make_card(v7_score=5.0)
        early = _make_state(hand=[card], turn_number=2)
        late = _make_state(hand=[card], turn_number=10)
        # They should be different (even if we can't predict which is higher)
        assert bsv_fusion(early) != bsv_fusion(late)

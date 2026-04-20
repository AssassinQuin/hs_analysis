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
from hs_analysis.search.game_state import HeroState, ManaState, Minion, OpponentState, Weapon


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
        assert sum(softmax([1.0, 2.0, 3.0])) == pytest.approx(1.0, abs=0.001)

    def test_larger_value_gets_higher_weight(self):
        result = softmax([1.0, 10.0])
        assert result[1] > result[0]

    def test_equal_values_equal_weights(self):
        for w in softmax([5.0, 5.0, 5.0]):
            assert w == pytest.approx(1.0 / 3, abs=0.01)

    def test_temperature_effect(self):
        sharp = softmax([1.0, 2.0], temperature=0.1)
        soft = softmax([1.0, 2.0], temperature=10.0)
        assert (sharp[1] - sharp[0]) > (soft[1] - soft[0])


# ──────────────────────────────────────────────
# Phase selection
# ──────────────────────────────────────────────

class TestPhaseSelection:
    @pytest.mark.parametrize("turn,phase", [(1, "early"), (4, "early"), (5, "mid"), (7, "mid"), (8, "late"), (15, "late")])
    def test_phase_mapping(self, turn, phase):
        assert _get_phase(turn) == phase


# ──────────────────────────────────────────────
# Tempo axis
# ──────────────────────────────────────────────

class TestEvalTempo:
    def test_empty_board(self, make_state):
        assert isinstance(eval_tempo_v10(make_state()), float)

    def test_friendly_board_advantage(self, make_state):
        state = make_state(board=[Minion(name="Yeti", attack=4, health=5, max_health=5)])
        assert eval_tempo_v10(state) > 0

    def test_enemy_board_penalty(self, make_state):
        friendly = make_state(board=[Minion(name="Yeti", attack=4, health=5, max_health=5)])
        both = make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            opponent=OpponentState(hero=HeroState(hp=30), board=[Minion(name="Big", attack=8, health=8, max_health=8)]),
        )
        assert eval_tempo_v10(friendly) > eval_tempo_v10(both)

    def test_weapon_contribution(self, make_state):
        with_weapon = make_state(hero=HeroState(hp=30, weapon=Weapon(attack=3, health=2)))
        assert eval_tempo_v10(with_weapon) > eval_tempo_v10(make_state())


# ──────────────────────────────────────────────
# Value axis
# ──────────────────────────────────────────────

class TestEvalValue:
    def test_empty_hand(self, make_state):
        assert isinstance(eval_value_v10(make_state()), float)

    def test_hand_cards_add_value(self, make_card, make_state):
        with_cards = make_state(hand=[make_card(v7_score=5.0), make_card(dbf_id=2, v7_score=4.0)])
        assert eval_value_v10(with_cards) > eval_value_v10(make_state())

    def test_card_advantage_bonus(self, make_card, make_state):
        winning = make_state(
            hand=[make_card()],
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            opponent=OpponentState(hero=HeroState(hp=30), hand_count=0),
        )
        losing = make_state(hand=[], opponent=OpponentState(hero=HeroState(hp=30), hand_count=5))
        assert eval_value_v10(winning) > eval_value_v10(losing)


# ──────────────────────────────────────────────
# Survival axis
# ──────────────────────────────────────────────

class TestEvalSurvival:
    def test_full_health(self, make_state):
        assert eval_survival_v10(make_state()) > 0

    def test_low_health_penalty(self, make_state):
        assert eval_survival_v10(make_state(hero=HeroState(hp=30, armor=0))) > \
               eval_survival_v10(make_state(hero=HeroState(hp=5, armor=0)))

    def test_lethal_threat_massive_penalty(self, make_state):
        state = make_state(
            hero=HeroState(hp=3, armor=0),
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[Minion(name="Attacker", attack=5, health=5, can_attack=True)],
            ),
        )
        assert eval_survival_v10(state) < -10

    def test_healing_potential(self, make_card, make_state):
        heal_card = make_card(text="恢复5点生命值", card_type="SPELL")
        assert eval_survival_v10(make_state(hand=[heal_card])) > eval_survival_v10(make_state())


# ──────────────────────────────────────────────
# BSV Fusion
# ──────────────────────────────────────────────

class TestBsvFusion:
    def test_returns_float(self, make_state):
        assert isinstance(bsv_fusion(make_state()), float)

    def test_lethal_state(self, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=0, armor=0)))
        assert isinstance(bsv_fusion(state), float)

    def test_winning_state_higher_than_losing(self, make_card, make_state):
        winning = make_state(
            hero=HeroState(hp=30, armor=5),
            board=[Minion(name="Big1", attack=7, health=7, max_health=7),
                   Minion(name="Big2", attack=6, health=6, max_health=6)],
            hand=[make_card(v7_score=6.0)],
            opponent=OpponentState(hero=HeroState(hp=15, armor=0),
                                   board=[Minion(name="Small", attack=1, health=1, max_health=1)]),
        )
        losing = make_state(
            hero=HeroState(hp=5, armor=0),
            board=[], hand=[],
            opponent=OpponentState(hero=HeroState(hp=30, armor=0),
                                   board=[Minion(name="Big", attack=8, health=8, max_health=8, can_attack=True)]),
        )
        assert bsv_fusion(winning) > bsv_fusion(losing)

    def test_phase_weights_applied(self, make_card, make_state):
        card = make_card(v7_score=5.0)
        assert bsv_fusion(make_state(hand=[card], turn_number=2)) != bsv_fusion(make_state(hand=[card], turn_number=10))

#!/usr/bin/env python3
"""Tests for v8_contextual_scorer.py

Run: python -m pytest scripts/test_v8_contextual_scorer.py -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_state import Card, GameState, HeroState, ManaState, OpponentState, Minion
from v8_contextual_scorer import V8ContextualScorer, get_scorer, reset_scorer


def _make_card(**kwargs) -> Card:
    defaults = dict(dbf_id=0, name="", cost=3, card_type="MINION",
                    attack=2, health=2, v7_score=5.0, text="")
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        hand=[],
        board=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0), board=[]),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ------------------------------------------------------------------
# Test 1: V7 fallback when no V8 data
# ------------------------------------------------------------------

def test_v7_fallback_no_data():
    """Pure V7 fallback when no V8 data files exist."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=5.0)
        state = _make_state(hand=[card])
        # With no data files, all contextual modifiers should be identity
        # turn_factor=1.0 (optimal=cost+1=4, turn=5, delta=1, 1-0.08=0.92)
        # type_factor=1.0 (MINION mid=1.0)
        # pool_ev=0, deathrattle=0, lethal_boost=1.0, rewind=0
        score = scorer.contextual_score(card, state)
        assert score > 0, f"Score should be > 0, got {score}"


# ------------------------------------------------------------------
# Test 2: Turn factor variance
# ------------------------------------------------------------------

def test_turn_factor_variance():
    """Same card at turn 3 vs turn 8 gives different values."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(cost=3, v7_score=10.0)
        state_early = _make_state(turn_number=3, hand=[card])
        state_late = _make_state(turn_number=10, hand=[card])
        score_early = scorer.contextual_score(card, state_early)
        score_late = scorer.contextual_score(card, state_late)
        assert score_early != score_late, (
            f"Turn 3 ({score_early:.3f}) should differ from turn 10 ({score_late:.3f})"
        )


# ------------------------------------------------------------------
# Test 3: Turn factor clamped
# ------------------------------------------------------------------

def test_turn_factor_clamped():
    """Turn factor is clamped to [0.5, 1.2]."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(cost=1, v7_score=10.0)
        # Very late turn: delta = |20 - 2| = 18, factor = 1 - 0.08*18 = -0.44 -> clamped to 0.5
        state = _make_state(turn_number=20, hand=[card])
        factor = scorer._turn_factor(card, state)
        assert 0.5 <= factor <= 1.2, f"Factor {factor} outside [0.5, 1.2]"


# ------------------------------------------------------------------
# Test 4: Type factor early vs late
# ------------------------------------------------------------------

def test_type_factor_early_late():
    """Minion valued higher early, spell higher late."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        minion = _make_card(card_type="MINION", v7_score=10.0)
        spell = _make_card(card_type="SPELL", v7_score=10.0)

        # Early: minion factor=1.1, spell factor=0.8
        state_early = _make_state(turn_number=2)
        mf_early = scorer._type_factor(minion, state_early)
        sf_early = scorer._type_factor(spell, state_early)
        assert mf_early > sf_early, (
            f"Early: minion factor ({mf_early}) should > spell ({sf_early})"
        )

        # Late: minion factor=0.85, spell factor=1.2
        state_late = _make_state(turn_number=10)
        mf_late = scorer._type_factor(minion, state_late)
        sf_late = scorer._type_factor(spell, state_late)
        assert sf_late > mf_late, (
            f"Late: spell factor ({sf_late}) should > minion ({mf_late})"
        )


# ------------------------------------------------------------------
# Test 5: Board saturation reduces minion factor
# ------------------------------------------------------------------

def test_type_factor_board_saturation():
    """Board saturation reduces minion factor."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        minion = _make_card(card_type="MINION", v7_score=10.0)
        state_normal = _make_state(turn_number=5, board=[Minion() for _ in range(3)])
        state_full = _make_state(turn_number=5, board=[Minion() for _ in range(6)])

        f_normal = scorer._type_factor(minion, state_normal)
        f_full = scorer._type_factor(minion, state_full)
        assert f_full < f_normal, (
            f"Board full factor ({f_full}) should < normal ({f_normal})"
        )


# ------------------------------------------------------------------
# Test 6: Pool EV discover bonus
# ------------------------------------------------------------------

def test_pool_ev_discover_bonus():
    """Discover dragon card gets bonus when pool_quality exists."""
    with tempfile.TemporaryDirectory() as td:
        # Write pool quality data
        pool_data = {"race_龙": {"avg_v7": 10.0, "top_10_pct_v7": 30.0, "pool_size": 73, "quality_std": 8.5}}
        with open(os.path.join(td, "pool_quality_report.json"), "w", encoding="utf-8") as f:
            json.dump(pool_data, f)

        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=5.0, text="发现一张龙牌")
        bonus = scorer._pool_ev_bonus(card)
        assert bonus > 0, f"Dragon discover should get positive bonus, got {bonus}"
        # Expected: (30 - 10) * 0.15 = 3.0


# ------------------------------------------------------------------
# Test 7: Non-discover gets zero pool bonus
# ------------------------------------------------------------------

def test_pool_ev_non_discover_zero():
    """Non-discover card gets zero pool bonus."""
    with tempfile.TemporaryDirectory() as td:
        pool_data = {"race_龙": {"avg_v7": 10.0, "top_10_pct_v7": 30.0, "pool_size": 73, "quality_std": 8.5}}
        with open(os.path.join(td, "pool_quality_report.json"), "w", encoding="utf-8") as f:
            json.dump(pool_data, f)

        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=5.0, text="一个普通的随从")
        bonus = scorer._pool_ev_bonus(card)
        assert bonus == 0.0, f"Non-discover card should get 0 bonus, got {bonus}"


# ------------------------------------------------------------------
# Test 8: Deathrattle parsing
# ------------------------------------------------------------------

def test_deathrattle_parsing():
    """Card with '亡语：召唤 3/3' parsed correctly."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=5.0, text="亡语：召唤一个3/3的随从")
        state = _make_state(board=[Minion() for _ in range(3)])
        bonus = scorer._deathrattle_ev_bonus(card, state)
        assert bonus > 0, f"Deathrattle with board should get bonus, got {bonus}"
        # (3+3)*0.15 * 0.7 = 0.63


# ------------------------------------------------------------------
# Test 9: Non-deathrattle gets zero
# ------------------------------------------------------------------

def test_deathrattle_non_deathrattle_zero():
    """Non-deathrattle card gets zero bonus."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=5.0, text="战吼：造成3点伤害")
        state = _make_state()
        bonus = scorer._deathrattle_ev_bonus(card, state)
        assert bonus == 0.0, f"Non-deathrattle should get 0, got {bonus}"


# ------------------------------------------------------------------
# Test 10: Lethal boost low HP
# ------------------------------------------------------------------

def test_lethal_boost_low_hp():
    """Damage card boosted when opponent low HP."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=10.0, text="造成6点伤害")
        state = _make_state(
            board=[Minion(attack=4)],
            opponent=OpponentState(hero=HeroState(hp=6, armor=0), board=[]),
        )
        boost = scorer._lethal_boost(card, state)
        assert boost > 1.0, f"Damage card with opponent at 6HP should be boosted, got {boost}"


# ------------------------------------------------------------------
# Test 11: Non-damage card not boosted
# ------------------------------------------------------------------

def test_lethal_boost_non_damage_not_boosted():
    """Non-damage card not boosted."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=10.0, text="抽两张牌")
        state = _make_state(
            opponent=OpponentState(hero=HeroState(hp=5, armor=0), board=[]),
        )
        boost = scorer._lethal_boost(card, state)
        assert boost == 1.0, f"Non-damage card should not be boosted, got {boost}"


# ------------------------------------------------------------------
# Test 12: No boost when opponent full HP
# ------------------------------------------------------------------

def test_lethal_boost_full_hp():
    """No boost when opponent full HP."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(v7_score=10.0, text="造成6点伤害")
        state = _make_state(
            opponent=OpponentState(hero=HeroState(hp=30, armor=0), board=[]),
        )
        boost = scorer._lethal_boost(card, state)
        assert boost == 1.0, f"No boost at full HP, got {boost}"


# ------------------------------------------------------------------
# Test 13: Rewind card with positive delta
# ------------------------------------------------------------------

def test_rewind_positive_delta():
    """Rewind card with positive delta gets bonus."""
    with tempfile.TemporaryDirectory() as td:
        rewind_data = {"99999": {"name": "Test Rewind", "delta": 2.5, "paired": True}}
        with open(os.path.join(td, "rewind_delta_report.json"), "w", encoding="utf-8") as f:
            json.dump(rewind_data, f)

        scorer = V8ContextualScorer(data_dir=td)
        card = _make_card(dbf_id=99999, v7_score=10.0, text="回溯。发现一张法术牌")
        state = _make_state()
        delta = scorer._rewind_ev_delta(card, state)
        assert delta > 0, f"Rewind card with positive delta should get bonus, got {delta}"


# ------------------------------------------------------------------
# Test 14: Synergy with race mentions
# ------------------------------------------------------------------

def test_synergy_three_same_race():
    """3+ same race card texts trigger bonus."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        cards = [
            _make_card(v7_score=5.0, text="发现一张龙牌"),
            _make_card(v7_score=5.0, text="召唤一条龙"),
            _make_card(v7_score=5.0, text="龙获得+2攻击力"),
            _make_card(v7_score=5.0, text="普通卡牌"),
        ]
        state = _make_state(hand=cards)
        bonus = scorer._synergy_bonus(state)
        assert bonus > 0, f"3+ dragon mentions should get synergy bonus, got {bonus}"


# ------------------------------------------------------------------
# Test 15: No synergy with diverse hand
# ------------------------------------------------------------------

def test_synergy_diverse_no_bonus():
    """No synergy bonus with diverse hand."""
    with tempfile.TemporaryDirectory() as td:
        scorer = V8ContextualScorer(data_dir=td)
        cards = [
            _make_card(v7_score=5.0, cost=1, text="造成1点伤害"),
            _make_card(v7_score=5.0, cost=2, text="抽一张牌"),
        ]
        state = _make_state(hand=cards)
        bonus = scorer._synergy_bonus(state)
        # Only curve completeness bonus (2 distinct costs * 0.2 = 0.4)
        # No race synergy, no spell+trigger combo
        assert bonus < 1.0, f"Diverse hand should have minimal synergy, got {bonus}"


# ------------------------------------------------------------------
# Test 16: Integration — contextual differs from V7
# ------------------------------------------------------------------

def test_integration_contextual_differs_from_v7():
    """contextual_score != raw v7_score for a real card+state."""
    reset_scorer()
    scorer = get_scorer()
    card = _make_card(
        dbf_id=123146,
        name="Alexstrasza",
        cost=7,
        card_type="MINION",
        v7_score=32.0,
        text="战吼：造成5点伤害",
    )
    state = _make_state(
        turn_number=3,
        hand=[card],
        board=[Minion() for _ in range(5)],
        opponent=OpponentState(hero=HeroState(hp=8, armor=0), board=[]),
    )
    ctx = scorer.contextual_score(card, state)
    raw = card.v7_score
    assert ctx != raw, f"Contextual ({ctx:.2f}) should differ from raw ({raw:.2f})"

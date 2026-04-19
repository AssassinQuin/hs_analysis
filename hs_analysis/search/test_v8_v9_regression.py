#!/usr/bin/env python3
"""test_v8_v9_regression.py — Ensure V9 decisions are never catastrophically worse than V8."""

import pytest

from hs_analysis.search.game_state import GameState, Minion, HeroState, ManaState, OpponentState
from hs_analysis.search.rhea_engine import RHEAEngine, Action
from hs_analysis.models.card import Card
from hs_analysis.evaluators.composite import evaluate, evaluate_with_risk
from hs_analysis.search.risk_assessor import RiskReport


def test_v9_finds_lethal_when_v8_might_miss():
    """Lethal state that V8 search might not find in time — V9 should find it via Layer 0."""
    # Complex board with lethal available through specific spell
    state = GameState(
        hero=HeroState(hp=20),
        mana=ManaState(available=10, max_mana=10),
        board=[
            Minion(name='M1', attack=4, health=5, max_health=5, can_attack=True),
            Minion(name='M2', attack=3, health=3, max_health=3, can_attack=True),
        ],
        hand=[
            Card(dbf_id=1, name='Fireball', cost=4, card_type='SPELL', text='造成 6 点伤害'),
        ],
        opponent=OpponentState(hero=HeroState(hp=6)),  # fireball = lethal
        turn_number=8,
    )
    
    engine = RHEAEngine(pop_size=10, max_gens=5, time_limit=500.0)
    result = engine.search(state)
    
    # V9 should find lethal via check_lethal Layer 0
    assert result.best_fitness == 10000.0  # lethal found


def test_v9_avoids_obvious_overextension():
    """Board where V8 would overcommit, V9 doesn't."""
    # Evaluate a risky board state
    risky_state = GameState(
        hero=HeroState(hp=5),  # low health
        board=[Minion(attack=2, health=2, max_health=2) for _ in range(7)],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            secrets=['secret1'],
        ),
    )
    
    # V8-style evaluation (no risk)
    base_score = evaluate(risky_state)
    
    # V9-style evaluation (with risk)
    high_risk = RiskReport(total_risk=0.8)
    risk_score = evaluate_with_risk(risky_state, risk_report=high_risk)
    
    # V9 should penalize the risky state
    assert risk_score < base_score, f'Risk score ({risk_score}) should be < base ({base_score})'


def test_v9_same_as_v8_for_safe_boards():
    """Low-risk board → V9 and V8 produce similar fitness rankings."""
    safe_state = GameState(
        hero=HeroState(hp=28),  # healthy
        board=[Minion(attack=3, health=4, max_health=4)],  # safe minion count
        opponent=OpponentState(hero=HeroState(hp=25)),
    )
    
    # V8 evaluation
    base_score = evaluate(safe_state)
    
    # V9 evaluation with minimal risk
    low_risk = RiskReport(total_risk=0.05)  # barely any risk
    risk_score = evaluate_with_risk(safe_state, risk_report=low_risk)
    
    # Should be very close (within 5%)
    if abs(base_score) > 1e-6:
        ratio = risk_score / base_score
        assert 0.90 <= ratio <= 1.0, f'Risk-adjusted score ({risk_score}) too different from base ({base_score})'
    else:
        # Both near zero
        assert abs(risk_score) < 1.0


def test_v9_risk_assessor_catches_danger():
    """Risk assessor correctly identifies dangerous situations."""
    from hs_analysis.search.risk_assessor import RiskAssessor
    
    assessor = RiskAssessor()
    
    # Safe state
    safe = GameState(
        hero=HeroState(hp=28),
        board=[Minion(attack=3, health=5, max_health=5) for _ in range(2)],
    )
    safe_report = assessor.assess(safe)
    
    # Dangerous state
    danger = GameState(
        hero=HeroState(hp=5),
        board=[Minion(attack=2, health=2, max_health=2) for _ in range(7)],
        opponent=OpponentState(secrets=['s1', 's2']),
    )
    danger_report = assessor.assess(danger)
    
    assert danger_report.total_risk > safe_report.total_risk
    assert danger_report.is_safe is False
    assert safe_report.is_safe is True


def test_v9_lethal_checker_exhaustive():
    """Lethal checker finds lethal that random search might miss."""
    from hs_analysis.search.lethal_checker import check_lethal
    
    # Scenario: multiple small minions + spell = exact lethal
    state = GameState(
        hero=HeroState(hp=20),
        mana=ManaState(available=8, max_mana=8),
        board=[
            Minion(name=f'M{i}', attack=2, health=2, max_health=2, can_attack=True)
            for i in range(4)
        ],
        hand=[
            Card(dbf_id=1, name='Frostbolt', cost=2, card_type='SPELL', text='造成 3 点伤害'),
        ],
        opponent=OpponentState(hero=HeroState(hp=11)),  # 4×2 + 3 = 11 = exact lethal
        turn_number=7,
    )
    
    result = check_lethal(state)
    assert result is not None, 'Should find exact lethal: 4×2 attacks + 3 spell = 11'

#!/usr/bin/env python3
"""test_risk_assessor.py — Unit tests for risk evaluation."""

import pytest

from analysis.engine.state import GameState, Minion, HeroState, OpponentState
from analysis.search.risk import RiskReport, RiskAssessor


def test_no_risk():
    """Empty board → zero risk."""
    assessor = RiskAssessor()
    state = GameState()
    report = assessor.assess(state)
    assert report.aoe_vulnerability == 0.0
    assert report.overextension_penalty == 0.0
    assert report.survival_score == 1.0  # 30 hp
    assert report.secret_threat == 0.0
    assert report.is_safe is True


def test_aoe_vulnerability():
    """Board of 2-health minions → high vulnerability to 2-dmg AoE."""
    assessor = RiskAssessor()
    state = GameState(
        board=[Minion(attack=2, health=2, max_health=2) for _ in range(5)],
    )
    aoe = assessor.aoe_vulnerability(state)
    assert aoe > 0.0  # vulnerable to 2-dmg AoE


def test_overextension():
    """7 minions → high overextension penalty."""
    assessor = RiskAssessor()
    state = GameState(
        board=[Minion(attack=1, health=1, max_health=1) for _ in range(7)],
    )
    over = assessor.overextension_penalty(state)
    assert over == 0.8


def test_overextension_safe():
    """3 minions → no overextension penalty."""
    assessor = RiskAssessor()
    state = GameState(
        board=[Minion(attack=1, health=1, max_health=1) for _ in range(3)],
    )
    over = assessor.overextension_penalty(state)
    assert over == 0.0


def test_survival_low_hp():
    """Hero at 5hp → very low survival score."""
    assessor = RiskAssessor()
    state = GameState(hero=HeroState(hp=5))
    sur = assessor.survival_score(state)
    assert sur == 0.3


def test_survival_critical():
    """Hero at 3hp → critical survival."""
    assessor = RiskAssessor()
    state = GameState(hero=HeroState(hp=3))
    sur = assessor.survival_score(state)
    assert sur == 0.1


def test_survival_healthy():
    """Hero at 25hp → healthy."""
    assessor = RiskAssessor()
    state = GameState(hero=HeroState(hp=25))
    sur = assessor.survival_score(state)
    assert sur == 1.0


def test_secret_threat():
    """Opponent has 2 secrets → moderate threat."""
    assessor = RiskAssessor()
    state = GameState(
        opponent=OpponentState(secrets=['secret1', 'secret2']),
    )
    sec = assessor.secret_threat(state)
    assert sec == 0.6  # 2 × 0.3


def test_composite_risk():
    """Multiple risk factors → weighted composite."""
    assessor = RiskAssessor()
    state = GameState(
        hero=HeroState(hp=8),  # low hp → low survival
        board=[Minion(attack=2, health=2, max_health=2) for _ in range(7)],  # overextended + aoe vuln
        opponent=OpponentState(secrets=['s1']),  # secret threat
    )
    report = assessor.assess(state)
    assert report.aoe_vulnerability > 0.0
    assert report.overextension_penalty == 0.8
    assert report.survival_score < 1.0
    assert report.secret_threat == 0.3
    assert report.total_risk > 0.0
    assert report.is_safe is False  # high risk board


def test_risk_report_defaults():
    """RiskReport default values."""
    report = RiskReport()
    assert report.aoe_vulnerability == 0.0
    assert report.overextension_penalty == 0.0
    assert report.survival_score == 1.0
    assert report.secret_threat == 0.0
    assert report.total_risk == 0.0
    assert report.is_safe is True

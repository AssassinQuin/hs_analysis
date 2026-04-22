#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import List

from analysis.search.game_state import GameState, Minion, HeroState, OpponentState, ManaState
from analysis.models.card import Card
from analysis.scorers.v8_contextual import get_scorer as _get_v8_scorer

try:
    from analysis.search.risk_assessor import RiskReport
except ImportError:
    RiskReport = None

try:
    from analysis.evaluators.bsv import bsv_fusion
except ImportError:
    bsv_fusion = None

try:
    from analysis.evaluators.submodel import (
        eval_board,
        eval_threat,
        eval_lingering,
        eval_trigger,
    )
except ImportError:
    def eval_board(state) -> float:
        friend = sum(m.attack + m.health for m in state.board)
        enemy = sum(m.attack + m.health for m in state.opponent.board)
        return friend - enemy

    def eval_threat(state) -> float:
        opp = state.opponent
        threat_to_opp = -max(0, opp.hero.hp + opp.hero.armor)
        threat_to_me = max(0, 30 - state.hero.hp - state.hero.armor) * 0.5
        return threat_to_opp - threat_to_me

    def eval_lingering(state) -> float:
        return 0.0

    def eval_trigger(state) -> float:
        return 0.0


DEFAULT_WEIGHTS = {
    "w_hand":      1.0,
    "w_board":     1.0,
    "w_threat":    1.5,
    "w_lingering": 0.8,
    "w_trigger":   0.5,
}


def evaluate(state: GameState, weights: dict | None = None) -> float:
    if bsv_fusion is not None:
        return bsv_fusion(state)

    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    v8_scorer = _get_v8_scorer()
    hand_score = v8_scorer.hand_contextual_value(state)

    board_score     = eval_board(state)
    threat_score    = eval_threat(state)
    lingering_score = eval_lingering(state)
    trigger_score   = eval_trigger(state)

    V = (
        w["w_hand"]      * hand_score
      + w["w_board"]     * board_score
      + w["w_threat"]    * threat_score
      + w["w_lingering"] * lingering_score
      + w["w_trigger"]   * trigger_score
    )
    return V


def evaluate_delta(state_before: GameState, state_after: GameState,
                   weights: dict | None = None) -> float:
    return evaluate(state_after, weights) - evaluate(state_before, weights)


def quick_eval(state: GameState) -> float:
    v8_scorer = _get_v8_scorer()
    v7_adj = v8_scorer.hand_contextual_value(state)
    threat = -(max(0, 30 - state.hero.hp - state.hero.armor) * 0.5)
    return v7_adj + 1.5 * threat


def evaluate_with_risk(state: GameState, weights: dict | None = None, risk_report=None) -> float:
    base_score = evaluate(state, weights)

    if risk_report is None:
        return base_score

    risk_penalty = getattr(risk_report, 'total_risk', 0.0) * 0.3
    risk_penalty = min(risk_penalty, 0.9)

    return base_score * (1.0 - risk_penalty)


def evaluate_delta_with_risk(initial: GameState, current: GameState,
                              weights: dict | None = None, risk_report=None) -> float:
    return evaluate_with_risk(current, weights, risk_report) - evaluate(initial, weights)

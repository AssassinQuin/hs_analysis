#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import List

from analysis.card.engine.state import GameState, Minion, HeroState, OpponentState, ManaState
from analysis.card.models.card import Card

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
        eval_mana_efficiency,
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
        total = 0.0
        for m in state.board:
            ench = m.enchantments or []
            if ench:
                total += 2.0
                if any("deathrattle" in str(e).lower() for e in ench):
                    total += 1.5
            if getattr(m, 'trigger_type', None):
                total += 1.5
        herald_count = getattr(state, 'herald_count', 0)
        if herald_count > 0:
            total += herald_count * 2.0
        imbue_level = getattr(state.hero, 'imbue_level', 0)
        if imbue_level > 0:
            total += 1.0 + imbue_level * 0.5
        for card in state.hand:
            ct = getattr(card, "card_type", "").upper()
            if ct == "SPELL":
                total += 0.5
            elif ct == "WEAPON":
                total += 0.3
        return total

    def eval_mana_efficiency(state) -> float:
        wasted = state.mana.available
        # Unused mana modifiers represent potential future value
        # e.g. "next spell costs 2 less" with a spell still in hand
        modifier_potential = 0.0
        for mod in state.mana.modifiers:
            if mod.used:
                continue
            # Check if hand has a matching card for this modifier
            for card in state.hand:
                if mod.scope == "next_spell" and getattr(card, 'card_type', '').upper() == "SPELL":
                    modifier_potential += mod.value * 0.5
                    break
                elif mod.scope == "next_minion" and getattr(card, 'card_type', '').upper() == "MINION":
                    modifier_potential += mod.value * 0.5
                    break
                elif mod.scope == "next_combo_card" and "COMBO" in (getattr(card, 'mechanics', None) or []):
                    modifier_potential += mod.value * 0.5
                    break
                elif mod.scope == "this_turn":
                    modifier_potential += mod.value * 0.3
                    break
        return -wasted + modifier_potential


DEFAULT_WEIGHTS = {
    "w_hand":      1.0,
    "w_board":     1.0,
    "w_threat":    1.5,
    "w_lingering": 0.8,
    "w_trigger":   0.5,
    "w_mana":      0.3,
}


def target_selection_eval(state: GameState) -> float:
    """Lightweight state evaluation for target/option selection.

    Uses board power difference + hero HP delta + kill bonuses.
    Intentionally simple — no scorer, no sub-models, no BSV.
    """
    friendly_power = sum(m.attack + m.health for m in state.board if m.health > 0)
    enemy_power = 0
    dead_enemies = 0
    for m in state.opponent.board:
        if m.health <= 0:
            dead_enemies += 1
        else:
            enemy_power += m.attack + m.health
    if state.opponent.hero.hp <= 0:
        return 1000.0
    hero_delta = state.hero.hp - state.opponent.hero.hp
    return friendly_power - enemy_power + hero_delta + dead_enemies * 10


def evaluate(state: GameState, weights: dict | None = None) -> float:
    if bsv_fusion is not None:
        return bsv_fusion(state)

    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    hand_score = sum(getattr(c, "score", 0.0) for c in state.hand)

    board_score     = eval_board(state)
    threat_score    = eval_threat(state)
    lingering_score = eval_lingering(state)
    trigger_score   = eval_trigger(state)
    mana_score      = eval_mana_efficiency(state)

    V = (
        w["w_hand"]      * hand_score
      + w["w_board"]     * board_score
      + w["w_threat"]    * threat_score
      + w["w_lingering"] * lingering_score
      + w["w_trigger"]   * trigger_score
      + w["w_mana"]      * mana_score
    )
    return V


def evaluate_delta(state_before: GameState, state_after: GameState,
                   weights: dict | None = None) -> float:
    return evaluate(state_after, weights) - evaluate(state_before, weights)


def quick_eval(state: GameState) -> float:
    v7_adj = sum(getattr(c, "score", 0.0) for c in state.hand)
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

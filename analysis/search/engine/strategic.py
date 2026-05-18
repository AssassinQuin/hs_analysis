"""Strategic layer — determines which tactical mode to use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.search.game_state import GameState


@dataclass
class StrategicMode:
    mode: str  # "LETHAL", "DEFENSIVE", "DEVELOPMENT", "CONTROL"
    confidence: float = 1.0
    reason: str = ""


def strategic_decision(state: GameState) -> StrategicMode:
    lethal_result = _check_lethal_possible(state)
    if lethal_result:
        return StrategicMode(
            mode="LETHAL",
            confidence=lethal_result,
            reason="致命检测：可以击杀对手",
        )

    defensive_result = _check_defensive_needed(state)
    if defensive_result > 0.7:
        return StrategicMode(
            mode="DEFENSIVE",
            confidence=defensive_result,
            reason=f"防御模式：对手威胁过高 (danger={defensive_result:.2f})",
        )

    control_result = _check_control_needed(state)
    if control_result > 0.6:
        return StrategicMode(
            mode="CONTROL",
            confidence=control_result,
            reason=f"控场模式：敌方关键威胁优先处理 (threat={control_result:.2f})",
        )

    return StrategicMode(
        mode="DEVELOPMENT",
        confidence=0.8,
        reason="发展模式：寻找最优资源利用",
    )


def _check_lethal_possible(state: GameState) -> float:
    try:
        from analysis.search.lethal_checker import check_lethal
        result = check_lethal(state, time_budget_ms=5.0)
        if result is not None:
            return 1.0
    except Exception:
        pass

    max_dmg = _max_damage_bound(state)
    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor
    if opp_hp <= 0:
        return 1.0
    ratio = max_dmg / opp_hp
    if ratio >= 1.0:
        return 0.9
    if ratio >= 0.8:
        return 0.5
    return 0.0


def _check_defensive_needed(state: GameState) -> float:
    hero_hp = state.hero.hp + state.hero.armor
    if hero_hp <= 0:
        return 1.0

    enemy_damage = _enemy_damage_bound(state)
    if enemy_damage >= hero_hp:
        return 0.95

    danger_ratio = enemy_damage / hero_hp
    if danger_ratio > 0.5:
        return min(1.0, danger_ratio)

    if len(state.opponent.board) >= 4 and hero_hp < 15:
        return 0.6

    return danger_ratio * 0.5


def _max_damage_bound(state: GameState) -> int:
    dmg = 0
    for m in state.board:
        if m.can_attack and not m.frozen_until_next_turn and not m.is_dormant:
            dmg += m.attack
            if m.has_windfury:
                dmg += m.attack
    if state.hero.weapon is not None:
        dmg += state.hero.weapon.attack
    try:
        for card in state.hand:
            if card.cost <= state.mana.available:
                dmg += card.total_damage() if hasattr(card, "total_damage") else 0
    except Exception:
        pass
    return dmg


def _enemy_damage_bound(state: GameState) -> int:
    dmg = 0
    for m in state.opponent.board:
        dmg += m.attack
        if m.has_windfury:
            dmg += m.attack
    if state.opponent.hero.weapon is not None:
        dmg += state.opponent.hero.weapon.attack
    return dmg


def _check_control_needed(state: GameState) -> float:
    if not state.opponent.board:
        return 0.0

    hero_hp = state.hero.hp + state.hero.armor
    if _check_defensive_needed(state) > 0.7:
        return 0.0

    threat = 0.0
    for m in state.opponent.board:
        unit = 0.0
        if m.attack >= 4:
            unit += 0.35
        if m.has_windfury:
            unit += 0.25
        if m.has_divine_shield:
            unit += 0.2
        if m.has_stealth:
            unit += 0.1
        if m.has_taunt:
            unit += 0.1
        threat += unit

    if len(state.opponent.board) >= 3:
        threat += 0.2
    if hero_hp <= 18:
        threat += 0.15

    return min(1.0, threat)

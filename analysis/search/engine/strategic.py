"""Strategic layer — determines which tactical mode to use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analysis.search.game_state import GameState


@dataclass
class StrategicMode:
    mode: str  # "LETHAL", "DEFENSIVE", "DEVELOPMENT"
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
        import re
        for card in state.hand:
            text = getattr(card, "text", "") or ""
            m = re.search(r'Deal\s*(\d+)\s*damage', text, re.IGNORECASE)
            if not m:
                m = re.search(r'造成\s*(\d+)\s*点伤害', text)
            if m and card.cost <= state.mana.available:
                dmg += int(m.group(1))
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

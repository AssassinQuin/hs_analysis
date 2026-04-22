"""Risk assessment for Hearthstone AI decision engine.

Evaluates board vulnerability, overextension, survival, and secret threats
to produce a RiskReport used during search-tree pruning.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from analysis.search.game_state import GameState


@dataclass
class RiskReport:
    """Aggregated risk assessment for a given game state."""

    aoe_vulnerability: float = 0.0
    overextension_penalty: float = 0.0
    survival_score: float = 1.0
    secret_threat: float = 0.0
    total_risk: float = 0.0
    is_safe: bool = True


# Hard-coded AoE damage thresholds per opponent class.
_DEFAULT_AOE: List[int] = [2, 3, 4]

_CLASS_AOE: Dict[str, List[int]] = {
    "mage": [2, 3, 6],
    "warlock": [2, 3],
    "paladin": [2],
    "priest": [2, 3],
    "hunter": [1, 3],
}


class RiskAssessor:
    """Fast, heuristic-based risk evaluation for a GameState."""

    def __init__(self) -> None:
        self.class_aoe = _CLASS_AOE

    # ------------------------------------------------------------------
    # Individual risk dimensions
    # ------------------------------------------------------------------

    def aoe_vulnerability(self, state: GameState) -> float:
        """Fraction of the friendly board vulnerable to common AoE."""
        opponent_class = state.opponent.hero.hero_class.lower() if state.opponent.hero.hero_class else ""
        thresholds = self.class_aoe.get(opponent_class, _DEFAULT_AOE)
        if not thresholds or not state.board:
            return 0.0

        weight = 1.0 / len(thresholds)
        vulnerability = 0.0
        for minion in state.board:
            for t in thresholds:
                if minion.health <= t:
                    vulnerability += weight
        # Normalise: max possible is len(board) * 1.0, capped at 7.
        return vulnerability / 7.0

    def overextension_penalty(self, state: GameState) -> float:
        """Penalty for having too many minions (vulnerable to AoE)."""
        count = len(state.board)
        if count <= 3:
            return 0.0
        if count == 4:
            return 0.1
        if count == 5:
            return 0.3
        if count == 6:
            return 0.5
        return 0.8

    def survival_score(self, state: GameState) -> float:
        """Hero survivability based on effective HP (health + armor)."""
        hp = state.hero.hp + state.hero.armor
        if hp >= 20:
            return 1.0
        if hp >= 15:
            return 0.8
        if hp >= 10:
            return 0.5
        if hp >= 5:
            return 0.3
        return 0.1

    def secret_threat(self, state: GameState) -> float:
        """Threat posed by opponent secrets."""
        return len(state.opponent.secrets) * 0.3

    # ------------------------------------------------------------------
    # Combined assessment
    # ------------------------------------------------------------------

    def assess(self, state: GameState) -> RiskReport:
        """Produce a full RiskReport for the given game state."""
        aoe = self.aoe_vulnerability(state)
        over = self.overextension_penalty(state)
        sec = self.secret_threat(state)
        sur = self.survival_score(state)
        total = 0.3 * aoe + 0.2 * over + 0.2 * sec + 0.3 * (1.0 - sur)
        return RiskReport(
            aoe_vulnerability=aoe,
            overextension_penalty=over,
            survival_score=sur,
            secret_threat=sec,
            total_risk=total,
            is_safe=total < 0.5,
        )

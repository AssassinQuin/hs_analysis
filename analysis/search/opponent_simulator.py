"""opponent_simulator.py — 1-turn greedy opponent simulation.

Simulates the opponent's best-response turn using a greedy heuristic:
favorable trades first, then face damage. Runs within a configurable
time budget (default < 10 ms) and degrades gracefully on any error.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from analysis.search.game_state import GameState


# ===================================================================
# Data structures
# ===================================================================

@dataclass
class SimulatedOpponentTurn:
    """Result of simulating the opponent's greedy best response."""

    board_resilience_delta: float = 0.0  # fraction of our board value surviving
    friendly_deaths: int = 0             # how many of our minions die
    lethal_exposure: bool = False        # can opponent kill us
    worst_case_damage: int = 0           # max damage to our hero
    spell_threat: float = 0.0

    def estimated_opp_damage(self) -> float:
        return float(self.worst_case_damage) + float(self.spell_threat)


# ===================================================================
# OpponentSimulator
# ===================================================================

class OpponentSimulator:
    """Greedy 1-turn opponent simulator.

    Given the current game state, simulates what a rational opponent
    would do on their next turn and returns a summary of the outcome
    from the friendly player's perspective.
    """

    def __init__(self, eval_fn: Optional[Callable[[GameState], float]] = None):
        self.eval_fn = eval_fn

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def simulate_best_response(
        self,
        state: GameState,
        time_budget_ms: float = 10.0,
    ) -> SimulatedOpponentTurn:
        """Simulate opponent's greedy best response within *time_budget_ms*."""
        deadline = time.perf_counter() + (time_budget_ms / 1000.0)
        try:
            # Fast-path: no opponent board → nothing to simulate
            if not state.opponent.board:
                return SimulatedOpponentTurn(
                    board_resilience_delta=1.0,
                    friendly_deaths=0,
                    lethal_exposure=False,
                    worst_case_damage=0,
                    spell_threat=self._estimate_spell_threat(state),
                )

            our_health = state.hero.hp + state.hero.armor

            # Snapshot our board as mutable tuples (atk, hp, taunt, name)
            our_board: list[tuple[int, int, bool, str]] = [
                (m.attack, m.health, m.has_taunt, m.name) for m in state.board
            ]

            # Snapshot opponent board sorted by attack descending (greedy)
            opp_board: list[tuple[int, int, str]] = sorted(
                [(m.attack, m.health, m.name) for m in state.opponent.board],
                key=lambda t: t[0],
                reverse=True,
            )

            has_taunt = any(t[2] for t in our_board)

            friendly_deaths = 0
            remaining_opp_attack = 0

            for opp_atk, opp_hp, opp_name in opp_board:
                if time.perf_counter() > deadline:
                    break

                traded = False

                # 1) Look for a favorable trade: kill our minion, survive
                for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                    if has_taunt and not our_taunt:
                        continue  # must go through taunt first
                    if opp_atk >= our_hp and our_atk < opp_hp:
                        # Opponent kills our minion and survives
                        our_board.pop(i)
                        friendly_deaths += 1
                        traded = True
                        break

                if traded:
                    continue

                # 2) Look for an even trade: kill our minion, also dies
                for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                    if has_taunt and not our_taunt:
                        continue
                    if opp_atk >= our_hp:
                        # Opponent trades into our minion (may or may not survive)
                        our_board.pop(i)
                        friendly_deaths += 1
                        traded = True
                        break

                if traded:
                    continue

                # 3) If we have taunt, must attack a taunt minion
                if has_taunt:
                    for i, (our_atk, our_hp, our_taunt, our_name) in enumerate(our_board):
                        if our_taunt:
                            new_hp = our_hp - opp_atk
                            if new_hp <= 0:
                                our_board.pop(i)
                                friendly_deaths += 1
                            else:
                                our_board[i] = (our_atk, new_hp, our_taunt, our_name)
                            break
                    continue

                # 4) No favorable trade and no taunt → go face
                remaining_opp_attack += opp_atk

            weapon_attack = (
                state.opponent.hero.weapon.attack
                if state.opponent.hero.weapon is not None
                else 0
            )
            hero_power_damage = self._estimate_hero_power_damage(state)
            spell_threat = self._estimate_spell_threat(state)
            worst_case_damage = remaining_opp_attack + weapon_attack + hero_power_damage
            lethal_exposure = (our_health - worst_case_damage) <= 0

            # Board resilience delta
            our_value_before = sum(m.attack + m.health for m in state.board)
            our_value_after = sum(atk + hp for atk, hp, _, _ in our_board)
            board_resilience_delta = our_value_after / max(our_value_before, 1)

            return SimulatedOpponentTurn(
                board_resilience_delta=board_resilience_delta,
                friendly_deaths=friendly_deaths,
                lethal_exposure=lethal_exposure,
                worst_case_damage=worst_case_damage,
                spell_threat=spell_threat,
            )
        except Exception:
            return SimulatedOpponentTurn()  # safe default

    def _estimate_hero_power_damage(self, state: GameState) -> int:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls == "HUNTER":
            return 2
        if cls == "MAGE":
            return 1
        return 0

    def _estimate_spell_threat(self, state: GameState) -> float:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls in {"MAGE", "WARLOCK", "SHAMAN"}:
            return 2.0
        if cls in {"ROGUE", "HUNTER"}:
            return 1.0
        return 0.5

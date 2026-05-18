"""opponent_simulator.py — 1-turn greedy opponent simulation.

Simulates the opponent's best-response turn using either:
1. Full action simulation (swap_perspective + apply_action) — accurate
2. Fast heuristic estimation — for quick risk assessment

The full simulation mode:
- Uses swap_perspective to reuse the entire action system
- Actually plays cards from opponent's hand
- Handles effect chains, deathrattles, triggers
- Produces detailed logs for debugging

The fast estimation mode (legacy):
- Estimates damage potential from board + hero power + spell threat
- Runs in <10ms
- Used for quick risk assessment when full simulation isn't needed
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState


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
    cards_played: int = 0                # how many cards opponent played
    damage_to_our_hero: int = 0          # actual damage dealt to our hero
    our_hero_hp_after: int = 0           # our hero HP after simulation

    def estimated_opp_damage(self) -> float:
        return float(self.worst_case_damage) + float(self.spell_threat)


# ===================================================================
# OpponentSimulator
# ===================================================================

class OpponentSimulator:
    """Greedy 1-turn opponent simulator.

    Supports two modes:
    - full_simulation=True: Uses swap_perspective + apply_action for accurate
      simulation including effect chains, deathrattles, etc.
    - full_simulation=False: Fast heuristic estimation (legacy).

    Given the current game state, simulates what a rational opponent
    would do on their next turn and returns a summary of the outcome
    from the friendly player's perspective.
    """

    def __init__(
        self,
        eval_fn: Optional[Callable[['GameState'], float]] = None,
        full_simulation: bool = True,
    ):
        self.eval_fn = eval_fn
        self.full_simulation = full_simulation

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def simulate_best_response(
        self,
        state: 'GameState',
        time_budget_ms: float = 50.0,
    ) -> SimulatedOpponentTurn:
        """Simulate opponent's greedy best response within *time_budget_ms*.

        When full_simulation=True, uses the perspective swap mechanism
        to actually play opponent cards and resolve effects.

        When full_simulation=False, uses the legacy fast heuristic.
        """
        if self.full_simulation:
            return self._simulate_full(state, time_budget_ms)
        else:
            return self._simulate_fast(state, time_budget_ms)

    # ---------------------------------------------------------------
    # Full simulation mode
    # ---------------------------------------------------------------

    def _simulate_full(
        self,
        state: 'GameState',
        time_budget_ms: float,
    ) -> SimulatedOpponentTurn:
        """Full opponent simulation using swap_perspective + apply_action."""
        deadline = time.perf_counter() + (time_budget_ms / 1000.0)

        try:
            from analysis.search.perspective_swap import swap_perspective, swap_back
            from analysis.search.mcts.turn_advance import (
                _greedy_play_with_chains,
                _greedy_attacks,
                _try_hero_power,
            )
            from analysis.effects.types import Action, ActionKind as ActionType
            from analysis.effects.simulation.actions import apply_action
            from analysis.search.sim_logger import get_sim_logger

            sim_log = get_sim_logger()

            # Record our state before
            our_hp_before = state.hero.hp
            our_armor_before = state.hero.armor
            our_board_value_before = sum(m.attack + m.health for m in state.board)

            # Swap to opponent perspective
            opp_state, saved = swap_perspective(state)

            with sim_log.phase("opp_simulator", turn=state.turn_number):
                # Simulate opponent turn
                # 1. Play cards
                opp_state = _greedy_play_with_chains(
                    opp_state, max_plays=7, max_chain_depth=2,
                    perspective="opp_sim",
                )

                # 2. Attack
                opp_state = _greedy_attacks(
                    opp_state, max_attacks=7, perspective="opp_sim",
                )

                # 3. Hero power
                opp_state = _try_hero_power(opp_state, perspective="opp_sim")

                # 4. End turn
                opp_state = apply_action(
                    opp_state, Action(action_type=ActionType.END_TURN)
                )

            # Swap back
            result_state = swap_back(opp_state, saved)

            # Compute results
            our_hp_after = result_state.hero.hp
            our_armor_after = result_state.hero.armor
            our_board_value_after = sum(
                m.attack + m.health for m in result_state.board
            )

            damage_to_hero = (our_hp_before + our_armor_before) - (our_hp_after + our_armor_after)
            if damage_to_hero < 0:
                damage_to_hero = 0

            friendly_deaths = len([m for m in state.board if m.health > 0]) - len(result_state.board)
            if friendly_deaths < 0:
                friendly_deaths = 0

            our_total_health = our_hp_after + our_armor_after
            lethal_exposure = our_total_health <= 0

            board_resilience = (
                our_board_value_after / max(our_board_value_before, 1)
                if our_board_value_before > 0
                else 1.0
            )

            return SimulatedOpponentTurn(
                board_resilience_delta=board_resilience,
                friendly_deaths=friendly_deaths,
                lethal_exposure=lethal_exposure,
                worst_case_damage=damage_to_hero,
                spell_threat=self._estimate_spell_threat(state),
                cards_played=len(sim_log._current_phase.steps) if sim_log._current_phase else 0,
                damage_to_our_hero=damage_to_hero,
                our_hero_hp_after=our_hp_after,
            )

        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(
                "Full opponent simulation failed, falling back to fast: %s", exc
            )
            return self._simulate_fast(state, time_budget_ms)

    # ---------------------------------------------------------------
    # Fast estimation mode (legacy)
    # ---------------------------------------------------------------

    def _simulate_fast(
        self,
        state: 'GameState',
        time_budget_ms: float,
    ) -> SimulatedOpponentTurn:
        """Fast heuristic opponent estimation (legacy logic)."""
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

    def _estimate_hero_power_damage(self, state: 'GameState') -> int:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls == "HUNTER":
            return 2
        if cls == "MAGE":
            return 1
        return 0

    def _estimate_spell_threat(self, state: 'GameState') -> float:
        cls = (state.opponent.hero.hero_class or "").upper()
        if cls in {"MAGE", "WARLOCK", "SHAMAN"}:
            return 2.0
        if cls in {"ROGUE", "HUNTER"}:
            return 1.0
        return 0.5

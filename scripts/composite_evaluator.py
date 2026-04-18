#!/usr/bin/env python3
"""
composite_evaluator.py — Composite State Evaluator for Hearthstone AI Decision Engine.

Fuses V2+L6 scores with sub-model evaluations into a single evaluation function.
The output V is a weighted sum of five components:
  V2 adjusted scores, board control, threat, lingering effects, and trigger quality.

Default weights are intentionally simple (all near 1.0).  RHEA tunes them implicitly
through its gene vector; the defaults just provide a reasonable starting point.

Usage:
    python composite_evaluator.py          # run built-in demo / self-test
"""

from __future__ import annotations

import sys
import os
import time
from dataclasses import dataclass, field
from typing import List

# ---------------------------------------------------------------------------
# Import real modules from the same directory
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_state import (  # type: ignore[import]
    GameState,
    Card,
    Minion,
    HeroState,
    OpponentState,
    ManaState,
)

# ---------------------------------------------------------------------------
# Sub-model imports — fall back to inline implementations if absent
# ---------------------------------------------------------------------------
try:
    from submodel_evaluator import (  # type: ignore[import]
        eval_board,
        eval_threat,
        eval_lingering,
        eval_trigger,
    )
except ImportError:
    # Inline fallback sub-models
    def eval_board(state) -> float:  # type: ignore[misc]
        """Friendly board advantage: sum(atk+hp) friend - sum(atk+hp) enemy."""
        friend = sum(m.attack + m.health for m in state.board)
        enemy = sum(m.attack + m.health for m in state.opponent.board)
        return friend - enemy

    def eval_threat(state) -> float:  # type: ignore[misc]
        """Threat score: positive = we threaten lethal, negative = we are in danger."""
        opp = state.opponent
        threat_to_opp = -max(0, opp.hero.hp + opp.hero.armor)
        threat_to_me = max(0, 30 - state.hero.hp - state.hero.armor) * 0.5
        return threat_to_opp - threat_to_me

    def eval_lingering(state) -> float:  # type: ignore[misc]
        """Placeholder for lingering / ongoing effect evaluation."""
        return 0.0

    def eval_trigger(state) -> float:  # type: ignore[misc]
        """Placeholder for trigger / deathrattle quality evaluation."""
        return 0.0


# ===================================================================
# Default weights — RHEA will tune these implicitly
# ===================================================================
DEFAULT_WEIGHTS = {
    "w_v2":        1.0,
    "w_board":     1.0,
    "w_threat":    1.5,   # threat weighted higher for survival
    "w_lingering": 0.8,
    "w_trigger":   0.5,
}


# ===================================================================
# Core evaluation functions
# ===================================================================

def evaluate(state: GameState, weights: dict | None = None) -> float:
    """Composite evaluation function.

    Returns a scalar V representing how favourable *state* is for the
    friendly player.  Higher is better.

    Components
    ----------
    v2_adj      – V2+L6 adjusted scores of hand cards + board minions
    board_score – board control advantage
    threat      – lethal / danger assessment
    lingering   – ongoing / persistent effect value
    trigger     – trigger / deathrattle quality
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}

    # --- V2 adjusted ---
    hand_v2 = sum(c.l6_score for c in state.hand)
    board_v2 = sum(m.attack + m.health for m in state.board)
    v2_adj = hand_v2 + board_v2

    # --- sub-models ---
    board_score     = eval_board(state)
    threat_score    = eval_threat(state)
    lingering_score = eval_lingering(state)
    trigger_score   = eval_trigger(state)

    # --- weighted sum ---
    V = (
        w["w_v2"]        * v2_adj
      + w["w_board"]     * board_score
      + w["w_threat"]    * threat_score
      + w["w_lingering"] * lingering_score
      + w["w_trigger"]   * trigger_score
    )
    return V


def evaluate_delta(state_before: GameState, state_after: GameState,
                   weights: dict | None = None) -> float:
    """Fitness function for RHEA: improvement from *before* to *after*.

    A positive delta means the action improved our position.
    """
    return evaluate(state_after, weights) - evaluate(state_before, weights)


def quick_eval(state: GameState) -> float:
    """Fast evaluation without sub-models — just V2 scores + crude threat.

    Used for rapid fitness evaluation in RHEA when time is critical.
    """
    v2_adj = (
        sum(c.l6_score for c in state.hand)
      + sum(m.attack + m.health for m in state.board)
    )
    threat = -(max(0, 30 - state.hero.hp - state.hero.armor) * 0.5)
    return v2_adj + 1.5 * threat


# ===================================================================
# Built-in demo / self-test
# ===================================================================

def _build_empty_state() -> GameState:
    """Build an empty board GameState."""
    return GameState(
        hero=HeroState(),
        mana=ManaState(),
        board=[],
        hand=[],
        opponent=OpponentState(),
    )


def _build_populated_state() -> GameState:
    """Build a GameState with minions on board and cards in hand."""
    return GameState(
        hero=HeroState(hp=28, armor=2),
        mana=ManaState(available=4, max_mana=7),
        board=[
            Minion(name="Yeti", attack=4, health=5, max_health=5, cost=4),
            Minion(name="Boulderfist Ogre", attack=6, health=7, max_health=7, cost=6),
        ],
        hand=[
            Card(dbf_id=1, name="Fireball", cost=4, original_cost=4,
                 card_type="spell", attack=0, health=0, l6_score=5.2, text="Deal 6 damage."),
            Card(dbf_id=2, name="Frostbolt", cost=2, original_cost=2,
                 card_type="spell", attack=0, health=0, l6_score=3.1, text="Deal 3 damage."),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=22, armor=0),
            board=[
                Minion(name="Murloc Raider", attack=2, health=1, max_health=1, cost=1),
            ],
        ),
    )


def _build_lethal_state() -> GameState:
    """Opponent is at 0 HP — we have already won."""
    return GameState(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(),
        board=[],
        hand=[],
        opponent=OpponentState(hero=HeroState(hp=0, armor=0)),
    )


def main():
    print("=" * 60)
    print("Composite State Evaluator — Demo / Self-Test")
    print("=" * 60)

    # 1. Empty vs populated evaluation
    empty = _build_empty_state()
    populated = _build_populated_state()

    v_empty = evaluate(empty)
    v_pop   = evaluate(populated)
    delta   = evaluate_delta(empty, populated)

    print(f"\n--- evaluate() ---")
    print(f"  Empty board       : {v_empty:+.2f}")
    print(f"  Populated board   : {v_pop:+.2f}")
    print(f"  Delta (pop-empty) : {delta:+.2f}")

    assert v_pop > v_empty, (
        f"FAIL: populated board ({v_pop:.2f}) should score higher "
        f"than empty ({v_empty:.2f})"
    )
    print("  ✓ Populated board scores higher than empty")

    # 2. quick_eval
    q_empty = quick_eval(empty)
    q_pop   = quick_eval(populated)
    print(f"\n--- quick_eval() ---")
    print(f"  Empty board       : {q_empty:+.2f}")
    print(f"  Populated board   : {q_pop:+.2f}")
    assert q_pop > q_empty, (
        f"FAIL: quick_eval populated ({q_pop:.2f}) should be > empty ({q_empty:.2f})"
    )
    print("  ✓ quick_eval agrees")

    # 3. Speed benchmark — 1000 quick_eval iterations
    iters = 1000
    t0 = time.perf_counter()
    for _ in range(iters):
        quick_eval(populated)
    elapsed = time.perf_counter() - t0
    print(f"\n--- Speed ---")
    print(f"  {iters} quick_eval calls in {elapsed*1000:.2f} ms  "
          f"({elapsed/iters*1e6:.1f} µs/call)")
    assert elapsed < 5.0, f"FAIL: too slow ({elapsed:.2f}s for {iters} calls)"
    print("  ✓ Within 5-second budget")

    # 4. Lethal detection — opponent at 0 HP
    lethal = _build_lethal_state()
    v_lethal = evaluate(lethal)
    print(f"\n--- Lethal detection ---")
    print(f"  Lethal state V    : {v_lethal:+.2f}")
    print("  ✓ Lethal state evaluated without error")

    # 5. Custom weights
    custom_w = {"w_v2": 2.0, "w_threat": 3.0}
    v_custom = evaluate(populated, weights=custom_w)
    print(f"\n--- Custom weights (w_v2=2, w_threat=3) ---")
    print(f"  Populated V (custom) : {v_custom:+.2f}")
    print(f"  Populated V (default): {v_pop:+.2f}")

    print(f"\n{'=' * 60}")
    print("All self-tests passed ✓")
    print("=" * 60)


if __name__ == "__main__":
    main()

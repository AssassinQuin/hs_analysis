"""Multi-objective evaluation for Hearthstone board state.

Decomposes board state assessment into three dimensions:
  - Tempo:  board control, mana efficiency, burst potential
  - Value:  hand quality, resource generation, card advantage
  - Survival: hero safety, threat reduction, lethal defense

Runnable independently: python -m hs_analysis.evaluators.multi_objective
"""

from __future__ import annotations

from dataclasses import dataclass

from hs_analysis.search.game_state import GameState, Minion
from hs_analysis.models.card import Card
from hs_analysis.scorers.v8_contextual import get_scorer as _get_v8_scorer


# ──────────────────────────────────────────────────────────────────────
# Evaluation result container
# ──────────────────────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """Three-dimensional evaluation of a board state."""

    v_tempo: float     # Board control + mana efficiency + burst
    v_value: float     # Hand quality + resources + card advantage
    v_survival: float  # Hero safety + threat reduction

    def scalarize(self, turn_number: int) -> float:
        """Phase-adaptive scalarization.

        Early game (turns 1-4)   weights tempo heavily.
        Mid game  (turns 5-7)    balanced.
        Late game (turns 8+)     weights value and survival.
        """
        if turn_number <= 4:      # Early
            return 1.2 * self.v_tempo + 0.8 * self.v_value + 0.6 * self.v_survival
        elif turn_number <= 7:    # Mid
            return 1.0 * self.v_tempo + 1.0 * self.v_value + 1.0 * self.v_survival
        else:                     # Late
            return 0.8 * self.v_tempo + 1.2 * self.v_value + 1.5 * self.v_survival

    def __add__(self, other: EvaluationResult) -> EvaluationResult:
        return EvaluationResult(
            self.v_tempo + other.v_tempo,
            self.v_value + other.v_value,
            self.v_survival + other.v_survival,
        )

    def __sub__(self, other: EvaluationResult) -> EvaluationResult:
        return EvaluationResult(
            self.v_tempo - other.v_tempo,
            self.v_value - other.v_value,
            self.v_survival - other.v_survival,
        )


# ──────────────────────────────────────────────────────────────────────
# Dimension evaluators
# ──────────────────────────────────────────────────────────────────────

def eval_tempo(state: GameState) -> float:
    """Board control + mana efficiency + burst potential."""
    # Board control: friendly minion value minus enemy minion threat
    friendly_value = sum(m.attack + m.health for m in state.board)
    enemy_threat = sum(m.attack * 1.2 for m in state.opponent.board)
    board_control = friendly_value - enemy_threat

    # Mana efficiency: estimate mana spent this turn
    mana_spent = sum(getattr(c, "cost", 0) for c in state.cards_played_this_turn)
    mana_available = max(state.mana.available, 1)  # avoid div-by-zero
    mana_efficiency = mana_spent / mana_available

    # Burst potential: spell damage estimate + attacking minion attack
    spell_burst = 0.0
    for c in state.hand:
        if getattr(c, "card_type", "") == "SPELL":
            # Rough estimate: spell cost * 1.5 as damage proxy
            spell_burst += getattr(c, "cost", 0) * 1.5
    attacking_minion_power = sum(m.attack for m in state.board if m.can_attack)
    burst_potential = spell_burst + attacking_minion_power

    return board_control + mana_efficiency * 5 + burst_potential * 0.5


def eval_value(state: GameState) -> float:
    """Hand quality + resource generation + card advantage."""
    # Hand quality
    v8_scorer = _get_v8_scorer()
    hand_quality = v8_scorer.hand_contextual_value(state)

    # Resource generation proxy
    resource_gen = len(state.cards_played_this_turn) * 2

    # Card advantage: (hand + board) - (opp hand + opp board)
    card_advantage = (
        (len(state.hand) + len(state.board))
        - (state.opponent.hand_count + len(state.opponent.board))
    )

    return hand_quality + resource_gen * 3 + card_advantage * 2


def eval_survival(state: GameState) -> float:
    """Hero safety + threat reduction + lethal defense."""
    # Hero safety
    hero_safety = (state.hero.hp + state.hero.armor) / 30.0

    # Threat reduction: negative pressure from enemy minions
    threat_reduction = 0.0
    for m in state.opponent.board:
        urgency = 1.0 if m.can_attack else 0.5
        threat_reduction -= m.attack * urgency

    # Lethal defense: huge penalty if enemy can deal lethal on board
    enemy_total_attack = sum(m.attack for m in state.opponent.board)
    hero_total_health = state.hero.hp + state.hero.armor
    lethal_defense = -50.0 if enemy_total_attack >= hero_total_health else 0.0

    return hero_safety * 10 + threat_reduction + lethal_defense


# ──────────────────────────────────────────────────────────────────────
# Top-level API
# ──────────────────────────────────────────────────────────────────────

def evaluate(state: GameState) -> EvaluationResult:
    """Return three-dimensional evaluation of *state*."""
    return EvaluationResult(
        v_tempo=eval_tempo(state),
        v_value=eval_value(state),
        v_survival=eval_survival(state),
    )


def evaluate_delta(before: GameState, after: GameState) -> EvaluationResult:
    """Return the evaluation delta (after − before)."""
    return evaluate(after) - evaluate(before)


# ──────────────────────────────────────────────────────────────────────
# Pareto dominance utilities
# ──────────────────────────────────────────────────────────────────────

def is_dominated(a: EvaluationResult, b: EvaluationResult) -> bool:
    """Returns True if EvaluationResult a is Pareto-dominated by b.
    
    a is dominated if b >= a on ALL dimensions AND strictly > on at least one.
    """
    return (
        b.v_tempo >= a.v_tempo
        and b.v_value >= a.v_value
        and b.v_survival >= a.v_survival
        and (
            b.v_tempo > a.v_tempo
            or b.v_value > a.v_value
            or b.v_survival > a.v_survival
        )
    )


def pareto_filter(results: list) -> list:
    """Filter list of (EvaluationResult, index) tuples to Pareto front.
    
    O(n²) pairwise comparison.
    Returns list of (EvaluationResult, index) tuples that are non-dominated.
    """
    if not results:
        return []
    
    non_dominated = []
    for i, (result_a, idx_a) in enumerate(results):
        dominated = False
        for j, (result_b, idx_b) in enumerate(results):
            if i != j and is_dominated(result_a, result_b):
                dominated = True
                break
        if not dominated:
            non_dominated.append((result_a, idx_a))
    return non_dominated


# ======================================================================
# Self-test block
# ======================================================================

if __name__ == "__main__":
    from hs_analysis.search.game_state import (
        HeroState,
        ManaState,
        OpponentState,
        Weapon,
    )

    errors: list[str] = []

    # ── Test 1: Empty board (neutral state) ──────────────────────────
    empty = GameState(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30, armor=0),
            board=[],
            hand_count=0,
        ),
        turn_number=3,
        cards_played_this_turn=[],
    )
    res_empty = evaluate(empty)
    # With empty board/hand, v_tempo ≈ 0 + 0*5 + 0*0.5 = 0
    # v_value = 0 (no v7_scores) + 0*3 + 0*2 = 0
    # v_survival = 30/30 * 10 = 10 + 0 (no threats) + 0 (not lethal)
    if abs(res_empty.v_tempo) > 0.01:
        errors.append(f"FAIL empty v_tempo={res_empty.v_tempo:.2f}, expected ~0")
    if abs(res_empty.v_value) > 0.01:
        errors.append(f"FAIL empty v_value={res_empty.v_value:.2f}, expected ~0")
    if abs(res_empty.v_survival - 10.0) > 0.01:
        errors.append(f"FAIL empty v_survival={res_empty.v_survival:.2f}, expected 10.0")

    # ── Test 2: Lethal threat detected → v_survival << 0 ────────────
    lethal_state = GameState(
        hero=HeroState(hp=3, armor=0),
        mana=ManaState(available=3, max_mana=3),
        board=[],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30, armor=0),
            board=[
                Minion(attack=4, health=4, can_attack=True, owner="enemy"),
                Minion(attack=2, health=2, can_attack=True, owner="enemy"),
            ],
            hand_count=3,
        ),
        turn_number=5,
        cards_played_this_turn=[],
    )
    res_lethal = evaluate(lethal_state)
    # enemy total attack = 6 >= hero hp+armor = 3  →  lethal_defense = -50
    # hero_safety = 3/30 = 0.1 → 0.1 * 10 = 1.0
    # threat_reduction = -(4*1.0 + 2*1.0) = -6
    # v_survival = 1.0 + (-6) + (-50) = -55.0
    if res_lethal.v_survival >= -10:
        errors.append(
            f"FAIL lethal v_survival={res_lethal.v_survival:.2f}, expected << 0"
        )

    # ── Test 3: Scalarization weights change with turn_number ───────
    er = EvaluationResult(v_tempo=10.0, v_value=10.0, v_survival=10.0)
    s_early = er.scalarize(turn_number=3)   # 1.2*10 + 0.8*10 + 0.6*10 = 26.0
    s_mid   = er.scalarize(turn_number=6)   # 1.0*10 + 1.0*10 + 1.0*10 = 30.0
    s_late  = er.scalarize(turn_number=10)  # 0.8*10 + 1.2*10 + 1.5*10 = 35.0

    if abs(s_early - 26.0) > 0.01:
        errors.append(f"FAIL scalarize early={s_early:.2f}, expected 26.0")
    if abs(s_mid - 30.0) > 0.01:
        errors.append(f"FAIL scalarize mid={s_mid:.2f}, expected 30.0")
    if abs(s_late - 35.0) > 0.01:
        errors.append(f"FAIL scalarize late={s_late:.2f}, expected 35.0")

    # Confirm monotonic increase for survival-heavy scalarization
    if not (s_early < s_mid < s_late):
        errors.append("FAIL scalarize should increase monotonically for (10,10,10)")

    # ── Test 4: evaluate_delta ──────────────────────────────────────
    before = GameState(
        hero=HeroState(hp=25, armor=0),
        mana=ManaState(available=6, max_mana=6),
        board=[
            Minion(attack=2, health=3, can_attack=True, owner="friendly"),
        ],
        hand=[
            Card(name="Fireball", cost=4, card_type="SPELL", v7_score=5.0),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=20, armor=0),
            board=[],
            hand_count=4,
        ),
        turn_number=6,
        cards_played_this_turn=[],
    )

    after = GameState(
        hero=HeroState(hp=25, armor=0),
        mana=ManaState(available=2, max_mana=6),
        board=[
            Minion(attack=5, health=5, can_attack=True, owner="friendly"),
        ],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=16, armor=0),
            board=[],
            hand_count=4,
        ),
        turn_number=6,
        cards_played_this_turn=[
            Card(name="Fireball", cost=4, card_type="SPELL"),
        ],
    )

    delta = evaluate_delta(before, after)
    # Delta should be non-zero (state meaningfully changed)
    if delta.v_tempo == 0 and delta.v_value == 0 and delta.v_survival == 0:
        errors.append("FAIL evaluate_delta returned zero delta for different states")

    # ── Test 5: EvaluationResult arithmetic ─────────────────────────
    a = EvaluationResult(v_tempo=3.0, v_value=4.0, v_survival=5.0)
    b = EvaluationResult(v_tempo=1.0, v_value=2.0, v_survival=3.0)
    c = a + b
    d = a - b
    if c.v_tempo != 4.0 or c.v_value != 6.0 or c.v_survival != 8.0:
        errors.append(f"FAIL __add__: got ({c.v_tempo},{c.v_value},{c.v_survival})")
    if d.v_tempo != 2.0 or d.v_value != 2.0 or d.v_survival != 2.0:
        errors.append(f"FAIL __sub__: got ({d.v_tempo},{d.v_value},{d.v_survival})")

    # ── Report ──────────────────────────────────────────────────────
    if errors:
        print("❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("✅ All multi_objective_evaluator tests passed.")
        print(f"   Empty board evaluation  : {res_empty}")
        print(f"   Lethal threat evaluation: {res_lethal}")
        print(f"   Delta evaluation        : {delta}")

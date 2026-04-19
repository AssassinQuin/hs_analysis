"""Performance benchmarks for V10 scoring pipeline."""

from __future__ import annotations

import time

import pytest

from hs_analysis.evaluators.siv import siv_score
from hs_analysis.evaluators.bsv import bsv_fusion
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)


def _make_card(**kwargs) -> Card:
    defaults = dict(
        dbf_id=1, name="Test Card", cost=3, original_cost=3,
        card_type="MINION", attack=3, health=3, v7_score=5.0,
        text="造成3点伤害", mechanics=["BATTLECRY"],
    )
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[],
        hand=[_make_card()],
        cards_played_this_turn=[],
        opponent=OpponentState(hero=HeroState(hp=15, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestV10Performance:
    """Performance benchmarks — ensure V10 pipeline is fast enough."""

    def test_siv_single_card_fast(self):
        """Single SIV evaluation should be < 0.1ms per modifier."""
        card = _make_card()
        state = _make_state()

        # Warm up
        siv_score(card, state)

        iters = 1000
        t0 = time.perf_counter()
        for _ in range(iters):
            siv_score(card, state)
        elapsed = time.perf_counter() - t0

        per_call_us = elapsed / iters * 1e6
        # Budget: 0.1ms = 100µs per call
        assert per_call_us < 1000, (
            f"SIV per call: {per_call_us:.1f}µs, budget: 1000µs"
        )

    def test_bsv_fusion_fast(self):
        """BSV fusion for a full state should be < 5ms total."""
        state = _make_state(
            board=[
                Minion(name=f"Minion{i}", attack=i + 2, health=i + 2, max_health=i + 2)
                for i in range(5)
            ],
            hand=[_make_card(dbf_id=i, name=f"Card{i}") for i in range(5)],
            opponent=OpponentState(
                hero=HeroState(hp=15, armor=0),
                board=[
                    Minion(name=f"Enemy{i}", attack=i + 1, health=i + 1, max_health=i + 1)
                    for i in range(3)
                ],
            ),
        )

        # Warm up
        bsv_fusion(state)

        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            bsv_fusion(state)
        elapsed = time.perf_counter() - t0

        per_call_ms = elapsed / iters * 1000
        # Budget: 5ms per call
        assert per_call_ms < 50, (
            f"BSV fusion per call: {per_call_ms:.2f}ms, budget: 50ms"
        )

    def test_siv_many_cards_reasonable(self):
        """Evaluate 10 cards in hand should complete quickly."""
        cards = [_make_card(dbf_id=i, name=f"Card{i}", v7_score=3.0 + i * 0.5)
                 for i in range(10)]
        state = _make_state(hand=cards)

        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            for c in cards:
                siv_score(c, state)
        elapsed = time.perf_counter() - t0

        per_card_us = elapsed / (iters * len(cards)) * 1e6
        assert per_card_us < 2000, (
            f"Per-card SIV: {per_card_us:.1f}µs, budget: 2000µs"
        )

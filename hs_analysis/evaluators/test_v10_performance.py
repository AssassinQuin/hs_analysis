"""Performance benchmarks for V10 scoring pipeline."""

from __future__ import annotations

import time

import pytest

from hs_analysis.evaluators.siv import siv_score
from hs_analysis.evaluators.bsv import bsv_fusion
from hs_analysis.search.game_state import HeroState, Minion, OpponentState


class TestV10Performance:
    """Performance benchmarks — ensure V10 pipeline is fast enough."""

    def test_siv_single_card_fast(self, make_card, make_state):
        """Single SIV evaluation should be < 1ms per modifier."""
        card = make_card(text="造成3点伤害", mechanics=["BATTLECRY"])
        state = make_state()
        siv_score(card, state)  # warm up

        iters = 1000
        t0 = time.perf_counter()
        for _ in range(iters):
            siv_score(card, state)
        elapsed = time.perf_counter() - t0
        per_call_us = elapsed / iters * 1e6
        assert per_call_us < 1000, f"SIV per call: {per_call_us:.1f}µs, budget: 1000µs"

    def test_bsv_fusion_fast(self, make_card, make_state):
        """BSV fusion for a full state should be < 50ms total."""
        state = make_state(
            board=[Minion(name=f"Minion{i}", attack=i + 2, health=i + 2, max_health=i + 2) for i in range(5)],
            hand=[make_card(dbf_id=i, name=f"Card{i}") for i in range(5)],
            opponent=OpponentState(
                hero=HeroState(hp=15, armor=0),
                board=[Minion(name=f"Enemy{i}", attack=i + 1, health=i + 1, max_health=i + 1) for i in range(3)],
            ),
        )
        bsv_fusion(state)  # warm up

        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            bsv_fusion(state)
        elapsed = time.perf_counter() - t0
        per_call_ms = elapsed / iters * 1000
        assert per_call_ms < 50, f"BSV fusion per call: {per_call_ms:.2f}ms, budget: 50ms"

    def test_siv_many_cards_reasonable(self, make_card, make_state):
        """Evaluate 10 cards in hand should complete quickly."""
        cards = [make_card(dbf_id=i, name=f"Card{i}", score=3.0 + i * 0.5) for i in range(10)]
        state = make_state(hand=cards)

        iters = 100
        t0 = time.perf_counter()
        for _ in range(iters):
            for c in cards:
                siv_score(c, state)
        elapsed = time.perf_counter() - t0
        per_card_us = elapsed / (iters * len(cards)) * 1e6
        assert per_card_us < 2000, f"Per-card SIV: {per_card_us:.1f}µs, budget: 2000µs"

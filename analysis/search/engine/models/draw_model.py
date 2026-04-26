"""DrawModel — expected value of drawing cards from deck."""

from __future__ import annotations

import math
from typing import List, Optional

try:
    from analysis.data.card_roles import RoleTag, classify_card_roles
except ImportError:
    RoleTag = classify_card_roles = None
from analysis.engine.state import GameState


class DrawModel:

    def expected_draw_value(self, state: GameState, n_cards: int = 1) -> float:
        deck = state.deck_list
        if not deck or len(deck) == 0:
            return -1.0 if state.fatigue_damage > 0 else 0.0

        remaining = state.deck_remaining
        if remaining <= 0:
            return -1.0 * n_cards

        effective_n = min(n_cards, 10 - len(state.hand))
        if effective_n <= 0:
            return 0.0

        avg_value = self._avg_card_value(state, deck)
        return effective_n * avg_value

    def draw_variance(self, state: GameState) -> float:
        deck = state.deck_list
        if not deck or len(deck) <= 1:
            return 0.0
        scores = [self._card_value(c, state) for c in deck]
        n = len(scores)
        mean = sum(scores) / n
        return sum((s - mean) ** 2 for s in scores) / n

    def top_deck_probability(self, state: GameState,
                             threshold: float) -> float:
        deck = state.deck_list
        if not deck or len(deck) == 0:
            return 0.0
        above = sum(1 for c in deck if self._card_value(c, state) >= threshold)
        return above / len(deck)

    def draw_role_probability(
        self,
        state: GameState,
        role: RoleTag,
        n_draws: int = 1,
    ) -> float:
        deck = state.deck_list
        if not deck or n_draws <= 0:
            return 0.0

        deck_size = len(deck)
        draws = min(n_draws, deck_size)
        if draws <= 0:
            return 0.0

        role_hits = sum(1 for c in deck if role in classify_card_roles(c))
        if role_hits <= 0:
            return 0.0
        if role_hits >= deck_size:
            return 1.0

        # Hypergeometric: P(at least one hit) = 1 - C(N-K, n)/C(N, n)
        miss = math.comb(deck_size - role_hits, draws) / math.comb(deck_size, draws)
        return max(0.0, min(1.0, 1.0 - miss))

    def _avg_card_value(self, state: GameState, deck: list) -> float:
        if not deck:
            return 0.0
        total = sum(self._card_value(c, state) for c in deck)
        return total / len(deck)

    def _card_value(self, card, state: GameState) -> float:
        base = getattr(card, "score", 0.0) or 0.0
        if base > 0:
            return base
        cost = getattr(card, "cost", 0) or 0
        attack = getattr(card, "attack", 0) or 0
        health = getattr(card, "health", 0) or 0
        return (attack + health) * 0.5 + cost * 0.3

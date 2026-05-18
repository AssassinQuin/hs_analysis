"""DiscoverModel — optimal selection from discover pools."""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

try:
    from analysis.card.data.card_roles import RoleTag, classify_card_roles
except ImportError:
    RoleTag = classify_card_roles = None
from analysis.card.engine.state import GameState


class DiscoverModel:

    def best_discover(self, pool: list, state: GameState,
                      n_samples: int = 50) -> Tuple[Optional[object], float]:
        if not pool:
            return None, 0.0

        scored = [(card, self._score_card(card, state)) for card in pool]
        scored.sort(key=lambda x: -x[1])

        if len(scored) <= 3:
            return scored[0]

        total_picks = min(n_samples, 200)
        best_picks: list = []
        pool_size = len(scored)
        for _ in range(total_picks):
            sample_size = min(3, pool_size)
            sample = random.sample(scored, sample_size)
            best_in_sample = max(sample, key=lambda x: x[1])
            best_picks.append(best_in_sample)

        avg_value = sum(p[1] for p in best_picks) / len(best_picks)
        top_card = max(best_picks, key=lambda x: x[1])[0]
        return top_card, avg_value

    def discover_ev(self, pool: list, state: GameState) -> float:
        _, ev = self.best_discover(pool, state)
        return ev

    def discover_role_hit_prob(self, pool: list, role: RoleTag) -> float:
        """Raw pool ratio: P(card in pool has role)."""
        if not pool:
            return 0.0
        hits = sum(1 for card in pool if role in classify_card_roles(card))
        return hits / len(pool)

    def discover_role_offer_prob(
        self,
        pool: list,
        role: RoleTag,
        offer_size: int = 3,
    ) -> float:
        """3选1(不放回)出现至少一张该角色牌的概率。"""
        if not pool or offer_size <= 0:
            return 0.0

        n_total = len(pool)
        n_offer = min(offer_size, n_total)
        role_hits = sum(1 for card in pool if role in classify_card_roles(card))
        if role_hits <= 0:
            return 0.0
        if role_hits >= n_total:
            return 1.0

        miss = math.comb(n_total - role_hits, n_offer) / math.comb(n_total, n_offer)
        return max(0.0, min(1.0, 1.0 - miss))

    def _score_card(self, card, state: GameState) -> float:
        try:
            from analysis.evaluators.siv import siv_score
            return siv_score(card, state)
        except Exception:
            pass

        base = getattr(card, "score", 0.0) or 0.0
        if base > 0:
            return base

        cost = getattr(card, "cost", 0) or 0
        attack = getattr(card, "attack", 0) or 0
        health = getattr(card, "health", 0) or 0
        card_type = getattr(card, "card_type", "") or ""
        mechanics = getattr(card, "mechanics", []) or []

        score = (attack + health) * 0.5 + cost * 0.3
        if card_type.upper() == "SPELL":
            score = cost * 0.8

        keyword_bonus = len(mechanics) * 0.2
        return score + keyword_bonus

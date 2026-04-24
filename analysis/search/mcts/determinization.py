#!/usr/bin/env python3
"""determinization.py — DUCT determinized world sampling.

Converts incomplete information (hidden opponent hand, secrets, deck)
into complete-information worlds for MCTS search.

Sampling strategies:
- Bayesian: use BayesianOpponentModel to weight card probabilities
- Uniform: random sampling from card pool
"""

from __future__ import annotations

import random
import logging
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from analysis.search.game_state import GameState, OpponentState

if TYPE_CHECKING:
    from analysis.models.card import Card
    from analysis.search.mcts.config import MCTSConfig

log = logging.getLogger(__name__)


@dataclass
class DeterminizedWorld:
    """A single determinized world for DUCT.

    Contains a fully-specified game state where all hidden information
    has been filled in with sampled values.
    """
    world_id: int
    state: GameState                       # fully determinized game state
    weight: float = 1.0                    # world weight for aggregation
    sampled_hand: List = field(default_factory=list)
    sampled_secrets: List[str] = field(default_factory=list)


class Determinizer:
    """DUCT determinized world sampler."""

    def __init__(self, config: 'MCTSConfig', bayesian_model=None):
        self.config = config
        self._bayesian = bayesian_model  # 优先使用外部传入的模型（已有对局观察数据）

        if self._bayesian is None and config.sampling_method == "bayesian":
            try:
                from analysis.utils.bayesian_opponent import BayesianOpponentModel
                self._bayesian = BayesianOpponentModel()
            except Exception:
                log.warning("BayesianOpponentModel unavailable, falling back to uniform")
                self._bayesian = None

    def create_worlds(
        self,
        state: GameState,
        num_worlds: Optional[int] = None,
    ) -> List[DeterminizedWorld]:
        """Create a set of determinized worlds from an incomplete-information state.

        Args:
            state: Current game state (may have incomplete opponent info).
            num_worlds: Override config.num_worlds if provided.

        Returns:
            List of DeterminizedWorld instances.
        """
        n = num_worlds or self.config.num_worlds
        worlds = []

        for i in range(n):
            det_state = self._determinize(state)
            worlds.append(DeterminizedWorld(
                world_id=i,
                state=det_state,
                weight=1.0 / n,
            ))

        return worlds

    def select_world(
        self,
        worlds: List[DeterminizedWorld],
    ) -> DeterminizedWorld:
        """Select a world for the current MCTS iteration.

        Uses uniform random selection (simple and effective per Zhang [S3]).
        """
        return random.choice(worlds)

    def _determinize(self, state: GameState) -> GameState:
        """Sample a complete world from the information set."""
        det = state.copy()

        # 1. Sample opponent hand (if not already known)
        opp = det.opponent
        hand_count = getattr(opp, 'hand_count', 0)
        if hand_count > 0 and not getattr(opp, 'hand', None):
            sampled = self._sample_opponent_hand(opp, state, hand_count)
            if hasattr(opp, 'hand'):
                opp.hand = sampled
            self._store_sampled_hand = sampled

        # 2. Sample opponent secrets (if any are hidden)
        secrets = getattr(opp, 'secrets', [])
        if secrets:
            det = self._sample_secrets(det, secrets)

        # 3. Sample opponent deck order (if needed for deep search)
        deck_remaining = getattr(opp, 'deck_remaining', 0)
        if deck_remaining > 0 and not getattr(opp, 'deck_list', None):
            opp.deck_list = self._sample_opponent_deck(opp, deck_remaining)

        return det

    def _sample_opponent_hand(
        self,
        opp: OpponentState,
        state: GameState,
        count: int,
    ) -> List:
        """Sample opponent hand cards."""
        if self._bayesian is not None:
            try:
                candidates = self._bayesian.predict_hand(opp, state)
                if candidates:
                    return random.sample(
                        candidates,
                        min(count, len(candidates)),
                    )
            except Exception:
                log.debug("Bayesian hand prediction failed", exc_info=True)

        # Fallback: create placeholder cards
        from analysis.models.card import Card
        return [
            Card(dbf_id=0, name=f"OppCard_{i}", cost=random.randint(1, 5),
                 card_type="MINION")
            for i in range(count)
        ]

    def _sample_secrets(self, state: GameState, secrets: list) -> GameState:
        """Resolve hidden secrets (if applicable)."""
        # Secrets are typically already revealed or tracked
        # In future: sample from unknown secret pool
        return state

    def _sample_opponent_deck(
        self,
        opp: OpponentState,
        remaining: int,
    ) -> List:
        """Sample opponent deck order."""
        from analysis.models.card import Card

        # Use Bayesian model if available
        if self._bayesian is not None:
            try:
                pool = self._bayesian.get_remaining_cards(opp)
                if pool:
                    deck = list(pool)
                    random.shuffle(deck)
                    return deck[:remaining]
            except Exception:
                pass

        # Fallback: generic cards
        return [
            Card(dbf_id=0, name=f"OppDeck_{i}", cost=random.randint(1, 5),
                 card_type="MINION")
            for i in range(remaining)
        ]

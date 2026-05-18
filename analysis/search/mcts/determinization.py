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

        When Bayesian model is available and has posteriors, allocates worlds
        proportionally to archetype posterior probabilities. Each world group
        uses the corresponding archetype's card pool for sampling.

        Args:
            state: Current game state (may have incomplete opponent info).
            num_worlds: Override config.num_worlds if provided.

        Returns:
            List of DeterminizedWorld instances.
        """
        n = num_worlds or self.config.num_worlds
        worlds = []

        # Try posterior-weighted allocation
        archetype_alloc = self._allocate_worlds_by_posterior(n)

        if archetype_alloc is not None:
            # Weighted: create worlds per archetype
            world_id = 0
            for archetype_id, count in archetype_alloc.items():
                deck_cards = self._get_archetype_cards(archetype_id)
                for _ in range(count):
                    det_state = self._determinize(state, deck_cards=deck_cards)
                    weight = count / n
                    worlds.append(DeterminizedWorld(
                        world_id=world_id,
                        state=det_state,
                        weight=weight,
                    ))
                    world_id += 1
        else:
            # Uniform: original behavior
            for i in range(n):
                det_state = self._determinize(state)
                worlds.append(DeterminizedWorld(
                    world_id=i,
                    state=det_state,
                    weight=1.0 / n,
                ))

        return worlds

    def _allocate_worlds_by_posterior(self, num_worlds: int) -> Optional[dict]:
        """Allocate worlds proportionally to Bayesian posteriors.

        Returns dict[archetype_id → count] or None if no Bayesian model.
        """
        if self._bayesian is None:
            return None

        posteriors = getattr(self._bayesian, 'posteriors', {})
        if not posteriors:
            return None

        # Get top archetypes (> 5% posterior)
        ranked = sorted(posteriors.items(), key=lambda x: x[1], reverse=True)
        significant = [(aid, p) for aid, p in ranked if p > 0.05]
        if not significant:
            return None

        # Allocate proportionally
        alloc = {}
        remaining = num_worlds
        for i, (aid, prob) in enumerate(significant):
            if i == len(significant) - 1:
                alloc[aid] = remaining
            else:
                count = max(1, round(prob * num_worlds))
                count = min(count, remaining - (len(significant) - i - 1))
                alloc[aid] = count
                remaining -= count

        return alloc

    def _get_archetype_cards(self, archetype_id: int) -> Optional[list]:
        """Get card list for a specific archetype from Bayesian model."""
        if self._bayesian is None:
            return None
        for deck in self._bayesian.decks:
            if deck["archetype_id"] == archetype_id:
                return deck["cards"]
        return None

    def select_world(
        self,
        worlds: List[DeterminizedWorld],
    ) -> DeterminizedWorld:
        """Select a world for the current MCTS iteration.

        Uses uniform random selection (simple and effective per Zhang [S3]).
        """
        return random.choice(worlds)

    def _determinize(self, state: GameState, deck_cards: Optional[list] = None) -> GameState:
        """Sample a complete world from the information set.

        Args:
            state: Current incomplete-info state.
            deck_cards: Optional specific card list to use for sampling.
                       If provided, samples from this pool instead of
                       the generic Bayesian prediction.
        """
        det = state.copy()

        # 1. Sample opponent hand (if not already known)
        opp = det.opponent
        hand_count = getattr(opp, 'hand_count', 0)
        if hand_count > 0 and not getattr(opp, 'hand', None):
            sampled = self._sample_opponent_hand(opp, state, hand_count, deck_cards=deck_cards)
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
            opp.deck_list = self._sample_opponent_deck(opp, deck_remaining, deck_cards=deck_cards)

        return det

    def _sample_opponent_hand(
        self,
        opp: OpponentState,
        state: GameState,
        count: int,
        deck_cards: Optional[list] = None,
    ) -> List:
        """Sample opponent hand cards.

        Priority:
        1. Known hand cards (from reveal effects like Tracking) — definite
        2. Remaining from archetype pool with cost-bias weighting

        Args:
            deck_cards: If provided, sample from this specific card pool.
        """
        from analysis.models.card import Card

        result = []
        remaining_count = count

        # Step 1: Use known hand cards first (from reveal effects)
        if self._bayesian is not None:
            try:
                seen_dbfs = set(self._bayesian._seen_cards)
                known_hand = self._bayesian.get_known_hand_cards(exclude_dbfs=seen_dbfs)
                if known_hand:
                    # Take as many known cards as available (up to count)
                    take = min(remaining_count, len(known_hand))
                    result.extend(known_hand[:take])
                    remaining_count -= take
            except Exception:
                log.debug("Known hand card lookup failed", exc_info=True)

        if remaining_count <= 0:
            return result

        # Step 2: Sample remaining slots from archetype pool
        if deck_cards is not None and self._bayesian is not None:
            try:
                # Count-aware: deck_cards is a flat list with duplicates
                # _seen_cards_counter tracks how many of each card seen
                seen_counts = dict(self._bayesian._seen_cards_counter)
                # Add known cards (played/revealed)
                for kc in getattr(opp, 'opp_known_cards', []):
                    dbf = getattr(kc, 'dbf_id', None)
                    if dbf:
                        seen_counts[dbf] = seen_counts.get(dbf, 0) + 1
                # Add already-placed known hand cards
                for card in result:
                    dbf = getattr(card, 'dbf_id', 0)
                    if dbf:
                        seen_counts[dbf] = seen_counts.get(dbf, 0) + 1

                # Filter: consume seen copies, keep remaining
                candidates_dbf = list(deck_cards)
                filtered = []
                for dbf in candidates_dbf:
                    seen = seen_counts.get(dbf, 0)
                    if seen > 0:
                        seen_counts[dbf] = seen - 1
                    else:
                        filtered.append(dbf)

                candidates = self._bayesian._dbfs_to_cards(filtered)
                if candidates:
                    sampled = random.sample(candidates, min(remaining_count, len(candidates)))
                    result.extend(sampled)
                    remaining_count -= len(sampled)
            except Exception:
                log.debug("Targeted hand sampling failed", exc_info=True)

        # Step 2b: Bayesian prediction with cost-bias (original path)
        if remaining_count > 0 and self._bayesian is not None:
            try:
                current_turn = getattr(state, 'turn_number', 0)
                candidates = self._bayesian.predict_hand(opp, state, current_turn=current_turn)
                if candidates:
                    # Exclude cards already in result
                    existing_dbfs = {getattr(c, 'dbf_id', 0) for c in result}
                    filtered = [c for c in candidates if getattr(c, 'dbf_id', 0) not in existing_dbfs]
                    if filtered:
                        sampled = random.sample(filtered, min(remaining_count, len(filtered)))
                        result.extend(sampled)
                        remaining_count -= len(sampled)
            except Exception:
                log.debug("Bayesian hand prediction failed", exc_info=True)

        # Step 3: Fallback — create placeholder cards
        if remaining_count > 0:
            result.extend([
                Card(dbf_id=0, name=f"OppCard_{i}", cost=random.randint(1, 5),
                     card_type="MINION")
                for i in range(remaining_count)
            ])

        return result

    def _sample_secrets(self, state: GameState, secrets: list) -> GameState:
        """Resolve hidden secrets (if applicable)."""
        # Secrets are typically already revealed or tracked
        # In future: sample from unknown secret pool
        return state

    def _sample_opponent_deck(
        self,
        opp: OpponentState,
        remaining: int,
        deck_cards: Optional[list] = None,
    ) -> List:
        """Sample opponent deck order.

        Args:
            deck_cards: If provided, sample from this specific card pool.
        """
        from analysis.models.card import Card

        # Try specific archetype cards first
        if deck_cards is not None and self._bayesian is not None:
            try:
                seen = set(self._bayesian._seen_cards)
                known = set()
                for kc in getattr(opp, 'opp_known_cards', []):
                    dbf = getattr(kc, 'dbf_id', None)
                    if dbf:
                        known.add(dbf)
                exclude = seen | known
                pool_dbf = [dbf for dbf in deck_cards if dbf not in exclude]
                pool = self._bayesian._dbfs_to_cards(pool_dbf)
                if pool:
                    deck = list(pool)
                    random.shuffle(deck)
                    return deck[:remaining]
            except Exception:
                pass

        # Use Bayesian model if available (original path)
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

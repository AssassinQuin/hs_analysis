"""
Particle Filter: manages the set of weighted worlds (particles) and provides
resampling / pruning / evolution logic.

This module implements the Sequential Importance Resampling (SIR) algorithm
for the MCTS World Tracker system.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.state import GameState
from analysis.engine.world_branch import (
    BranchPrediction,
    ObservedEvent,
    World,
    WorldSnapshot,
)


@dataclass
class ParticleFilterConfig:
    """Configuration for the particle filter."""
    num_worlds: int = 30            # target number of particles
    min_worlds: int = 5             # never drop below this
    max_worlds: int = 100           # never exceed this
    resample_threshold: float = 0.5 # effective sample size ratio threshold
    weight_min: float = 1e-6        # minimum weight before pruning
    prune_ratio: float = 0.1        # prune bottom 10% each round
    top_k_match: int = 5            # keep top-k best matching worlds


class WorldManager:
    """
    Manages the lifecycle of world particles:
    - creation from root GameState
    - weight updates from observations
    - pruning low-weight worlds
    - resampling to maintain particle diversity
    - evolution via MCTS branch predictions
    """

    def __init__(self, config: Optional[ParticleFilterConfig] = None):
        self.config = config or ParticleFilterConfig()

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, game_state: GameState, turn: int) -> WorldSnapshot:
        """Create the initial set of worlds from a fresh GameState."""
        root = World.create_root(game_state, turn)
        # Seed with the root world plus clones for diversity
        worlds: List[World] = [root]

        # Add a few replicas with slightly different weights
        # to seed diversity from the start
        for i in range(self.config.num_worlds - 1):
            clone = World.create_root(game_state, turn)
            clone.world_id = f"init_{i}_t{turn}_{random.randrange(1000, 9999)}"
            clone.weight = random.uniform(0.5, 1.0)
            worlds.append(clone)

        # Normalize
        total = sum(w.weight for w in worlds)
        for w in worlds:
            w.weight /= total

        snapshot = WorldSnapshot(
            turn_number=turn,
            worlds=worlds,
            total_weight=1.0,
        )
        snapshot.entropy = self._compute_entropy(worlds)
        snapshot.dominant_world_id = snapshot.get_best_world().world_id if worlds else None
        return snapshot

    # ------------------------------------------------------------------
    # Weight update
    # ------------------------------------------------------------------

    def update_weights(self, snapshot: WorldSnapshot,
                       match_results: List[MatchResult]) -> WorldSnapshot:
        """Update world weights based on match results.

        Uses normalized likelihoods across worlds to create evidence-driven
        differentiation. Worlds that matched the observed event (e.g., their
        opponent.hand contained the played card) get higher likelihood and
        their weight is preserved. Worlds that didn't match get lower weights.

        Differentiation is now EVIDENCE-BASED rather than artificially injected
        via signatures. The observation_matcher produces different likelihoods
        per world because each world has a different hypothetical opponent hand.
        """
        # Build lookup
        world_map = {w.world_id: w for w in snapshot.worlds}
        result_map: Dict[str, MatchResult] = {}
        for mr in match_results:
            result_map[mr.world_id] = mr

        # ── Normalize likelihoods across worlds ──
        likelihoods = [
            mr.likelihood
            for mr in match_results
            if mr.likelihood > 0
        ]
        max_lh = max(likelihoods) if likelihoods else 1.0
        min_lh = min(likelihoods) if likelihoods else 0.0
        lh_range = max_lh - min_lh if max_lh > min_lh else 1.0

        for w in snapshot.worlds:
            mr = result_map.get(w.world_id)
            if mr:
                # ── Normalize to [0, 1] range across worlds ──
                normalized = (mr.likelihood - min_lh) / lh_range if lh_range > 0 else 0.5

                # ── Evidence-driven weight update ──
                # Worlds that matched the observed event (e.g., had the played card
                # in their opponent hand) get likelihood ~1.0 * weight. Worlds that
                # didn't match get ~0.3 * weight. This is genuine Bayesian belief
                # updating — no artificial signatures needed.
                effective_lh = max(normalized, 0.01)

                w.weight *= effective_lh

                # Track match/mismatch
                if mr.likelihood >= 0.5:
                    w.matched_observations.append(mr.event_id)
                w.metadata.setdefault("match_scores", []).append(mr.likelihood)
                w.metadata.setdefault("normalized_scores", []).append(normalized)
            else:
                # No observation = slight decay
                w.weight *= 0.9

        # Normalize
        snapshot = self._normalize(snapshot)
        snapshot.entropy = self._compute_entropy(snapshot.worlds)
        snapshot.dominant_world_id = (snapshot.get_best_world().world_id
                                      if snapshot.worlds else None)
        return snapshot

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def prune(self, snapshot: WorldSnapshot) -> WorldSnapshot:
        """Remove low-weight worlds."""
        if len(snapshot.worlds) <= self.config.min_worlds:
            return snapshot

        # Sort by weight
        sorted_worlds = sorted(snapshot.worlds, key=lambda w: w.weight,
                               reverse=True)

        # Keep top-k by weight, plus any with weight > threshold
        keep: List[World] = []
        kept_ids: set = set()

        # Always keep the best world
        best = sorted_worlds[0]
        keep.append(best)
        kept_ids.add(best.world_id)

        # Keep worlds with significant weight
        for w in sorted_worlds[1:]:
            if w.weight > self.config.weight_min:
                if w.world_id not in kept_ids:
                    keep.append(w)
                    kept_ids.add(w.world_id)

        # If still too many, keep only top N by weight
        if len(keep) > self.config.max_worlds:
            keep = keep[:self.config.max_worlds]

        # If too few, we'll resample in the next step
        snapshot.worlds = keep if len(keep) >= self.config.min_worlds else sorted_worlds
        snapshot = self._normalize(snapshot)
        return snapshot

    # ------------------------------------------------------------------
    # Resampling (SIR systematic resampling)
    # ------------------------------------------------------------------

    def resample(self, snapshot: WorldSnapshot) -> WorldSnapshot:
        """
        Systematic resampling: replace low-weight worlds with copies
        of high-weight worlds to maintain diversity.
        """
        N = len(snapshot.worlds)
        if N <= self.config.min_worlds:
            return snapshot

        # Weight array
        weights = [max(w.weight, self.config.weight_min) for w in snapshot.worlds]
        total_weight = sum(weights)
        if total_weight <= 0:
            return snapshot
        weights = [w / total_weight for w in weights]

        # Effective sample size
        ess = 1.0 / sum(w * w for w in weights)
        ess_ratio = ess / N

        # Only resample if effective sample size is too low
        if ess_ratio >= self.config.resample_threshold:
            return snapshot  # skip resampling, weights are still diverse

        # Systematic resampling
        new_worlds: List[World] = []
        cumsum = 0.0
        cumulative = []
        for w in weights:
            cumsum += w
            cumulative.append(cumsum)

        step = 1.0 / N
        offset = random.uniform(0, step)

        for i in range(N):
            u = offset + i * step
            idx = 0
            while idx < len(cumulative) - 1 and cumulative[idx] < u:
                idx += 1

            src = snapshot.worlds[idx]
            # Clone the selected world
            cloned_state = (src.game_state.copy() if hasattr(src.game_state, 'copy') and src.game_state else src.game_state)
            clone = World(
                world_id=f"resample_{i}_{random.randrange(10000, 99999)}",
                game_state=cloned_state,
                weight=1.0 / N,
                parent_world_id=src.world_id,
                depth=src.depth,
                action_history=list(src.action_history),
                matched_observations=list(src.matched_observations),
                metadata={**src.metadata, "resampled": True},
            )
            new_worlds.append(clone)

        # ── Inject diversity into cloned states ──
        # When entropy is low, perturb opponent hand for MCTS diversity
        if getattr(snapshot, 'entropy', 1.0) < 0.5:
            for clone_w in new_worlds:
                gs = getattr(clone_w, 'game_state', None)
                if gs is None:
                    continue
                opp = getattr(gs, 'opponent', None)
                if opp and hasattr(opp, 'hand_count'):
                    opp.hand_count = max(0, opp.hand_count + random.choice([-1, 0, 0, 1]))

        snapshot.worlds = new_worlds
        snapshot = self._normalize(snapshot)
        snapshot.entropy = self._compute_entropy(snapshot.worlds)
        return snapshot

    # ------------------------------------------------------------------
    # Evolution (from MCTS results)
    # ------------------------------------------------------------------

    def evolve(self, snapshot: WorldSnapshot,
               predictions: List[BranchPrediction]) -> WorldSnapshot:
        """
        Evolve worlds using MCTS branch predictions.
        Each prediction creates new child worlds from parent worlds.
        """
        if not predictions or not snapshot.worlds:
            return snapshot

        new_worlds: List[World] = []
        turn = snapshot.turn_number + 1

        for pred in predictions:
            if not pred.child_worlds:
                continue
            for cw in pred.child_worlds:
                cw.depth += 1
                new_worlds.append(cw)

        # If we have new worlds from MCTS, replace (not merge) snapshot
        if new_worlds:
            # Normalize weights
            total = sum(w.weight for w in new_worlds)
            for w in new_worlds:
                w.weight /= total if total > 0 else 1
            snapshot.worlds = new_worlds
        else:
            # No MCTS results — just advance existing worlds
            for w in snapshot.worlds:
                w.depth += 1

        snapshot.turn_number = turn
        snapshot.entropy = self._compute_entropy(snapshot.worlds)
        snapshot.dominant_world_id = (snapshot.get_best_world().world_id
                                      if snapshot.worlds else None)
        return snapshot

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_top_worlds(self, snapshot: WorldSnapshot,
                       k: int = 5) -> List[World]:
        """Return the top-k highest-weight worlds."""
        return sorted(snapshot.worlds, key=lambda w: w.weight,
                      reverse=True)[:k]

    def get_probability_distribution(self,
                                     snapshot: WorldSnapshot) -> Dict[str, float]:
        """Return {world_id: probability} for all worlds."""
        return {w.world_id: w.weight for w in snapshot.worlds}

    def get_belief_state(self, snapshot: WorldSnapshot) -> BeliefState:
        """Return a structured belief state from the current snapshot."""
        top = self.get_top_worlds(snapshot, self.config.top_k_match)
        return BeliefState(
            turn_number=snapshot.turn_number,
            entropy=snapshot.entropy,
            num_worlds=len(snapshot.worlds),
            top_worlds=[(w.world_id, w.weight) for w in top],
            dominant_world_id=snapshot.dominant_world_id,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _normalize(self, snapshot: WorldSnapshot) -> WorldSnapshot:
        """Normalize weights so they sum to 1.0."""
        if not snapshot.worlds:
            return snapshot
        total = sum(w.weight for w in snapshot.worlds)
        if total <= 0:
            n = len(snapshot.worlds)
            for w in snapshot.worlds:
                w.weight = 1.0 / n
        else:
            for w in snapshot.worlds:
                w.weight /= total
        snapshot.total_weight = 1.0
        return snapshot

    @staticmethod
    def _compute_entropy(worlds: List[World]) -> float:
        """Shannon entropy of the weight distribution."""
        total = sum(w.weight for w in worlds)
        if total <= 0:
            return 0.0
        entropy = 0.0
        for w in worlds:
            p = w.weight / total
            if p > 0:
                entropy -= p * math.log2(p)
        return entropy / max(1.0, math.log2(len(worlds)))  # normalized


@dataclass
class BeliefState:
    """Structured belief state for external consumption."""
    turn_number: int
    entropy: float
    num_worlds: int
    top_worlds: List[Tuple[str, float]]  # [(world_id, probability)]
    dominant_world_id: Optional[str] = None


# Re-export MatchResult for convenience
from analysis.engine.observation_matcher import MatchResult  # noqa: E402, F811

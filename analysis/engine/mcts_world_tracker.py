"""
MCTS World Tracker — Orchestrator.

Ties together the full pipeline:
  1. Receive GameState from tracker pipeline (turn start)
  2. Run MCTS UCT search on each world
  3. Match real observations against world predictions
  4. Particle filter: update weights, prune, resample
  5. Output belief state + probabilities

Usage (replay mode):
    tracker = MCTSWorldTracker()
    for line in powerlog_lines:
        event = game_tracker.feed_line(line)
        if event == "turn_start":
            game_state = state_bridge.convert(...)
            analysis = tracker.on_turn_start(game_state)
            print(analysis)
        elif event == "action":
            observed = build_observed_event(line)
            update = tracker.on_event(observed)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.state import GameState
from analysis.card.models.card import Card
from analysis.engine.mcts_uct import MCTSConfig, MCTSUCT, MCTSResult
from analysis.engine.observation_matcher import (
    MatchResult,
    MatchSummarizer,
    ObservationMatcher,
)
from analysis.engine.particle_filter import (
    BeliefState,
    ParticleFilterConfig,
    WorldManager,
)
from analysis.engine.world_branch import (
    BranchPrediction,
    ObservedEvent,
    SimulationRecord,
    World,
    WorldSnapshot,
)
from analysis.engine.world_tracker_output import WorldTrackerOutput


@dataclass
class TrackerConfig:
    """Top-level configuration for the World Tracker."""
    num_worlds: int = 30
    mcts_iterations: int = 300
    mcts_time_budget_ms: int = 1500
    mcts_rollout_depth: int = 15
    uct_exploration: float = 1.414
    prune_threshold: float = 0.01
    match_decay: float = 0.8  # exponential decay for older matches
    verbose: bool = False

    # Override to enable per-world MCTS (expensive)
    mcts_per_world: bool = True  # if False, only run on best world


@dataclass
class TurnAnalysis:
    """Complete analysis output for one turn."""
    turn_number: int
    snapshot: WorldSnapshot
    belief_state: BeliefState
    top_actions: List[str]

    # MCTS results
    total_mcts_nodes: int = 0
    mcts_time_s: float = 0.0
    mcts_best_action: Optional[Action] = None

    # Matching
    last_match_results: List[MatchResult] = field(default_factory=list)
    match_quality: float = 0.0  # average match likelihood across all worlds

    # World evolution
    worlds_created: int = 0
    worlds_pruned: int = 0
    worlds_after_resample: int = 0

    # Diagnostics
    elapsed_s: float = 0.0


# ---------------------------------------------------------------------------
# Main Tracker
# ---------------------------------------------------------------------------

class MCTSWorldTracker:
    """
    Real-time game state tracker using particle-filtered MCTS worlds.

    Call order:
        turn = tracker.on_turn_start(game_state)   # new turn
        for each event:
            tracker.on_event(observed_event)        # incremental update
        tracker.on_turn_end()                       # cleanup
    """

    def __init__(self, config: Optional[TrackerConfig] = None):
        self.config = config or TrackerConfig()
        self._current_snapshot: Optional[WorldSnapshot] = None
        self._current_turn: int = 0
        self._deck_library: Optional[dict] = None  # lazy-loaded

        # Sub-components
        self.world_manager = WorldManager(ParticleFilterConfig(
            num_worlds=self.config.num_worlds,
            weight_min=self.config.prune_threshold,
        ))
        self.mcts = MCTSUCT(MCTSConfig(
            exploration_constant=self.config.uct_exploration,
            iterations=self.config.mcts_iterations,
            time_budget_ms=self.config.mcts_time_budget_ms,
            rollout_depth=self.config.mcts_rollout_depth,
            verbose=self.config.verbose,
        ))
        self.matcher = ObservationMatcher()
        self.summarizer = MatchSummarizer(decay=self.config.match_decay)
        self.output = WorldTrackerOutput()

        # Event buffer for current turn
        self._current_turn_events: List[ObservedEvent] = []
        self._event_counter: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_turn_start(self, game_state: GameState, turn: int) -> TurnAnalysis:
        """
        Called at the start of a new turn.

        If we have a prior snapshot, first match any cached events, then
        evolve worlds. Then run MCTS on the (possibly evolved) worlds.
        """
        start = time.monotonic()
        self._current_turn = turn

        # 1. Initialize or evolve
        if self._current_snapshot is None:
            # Fresh start
            self._current_snapshot = self.world_manager.initialize(
                game_state, turn
            )
        else:
            # Advance existing worlds
            self._current_snapshot.turn_number = turn
            for w in self._current_snapshot.worlds:
                w.game_state = game_state
                w.depth += 1

        # 2. Run MCTS on worlds
        mcts_results = self._run_mcts(self._current_snapshot)

        # 3. Attach MCTS predictions to worlds
        if mcts_results:
            self._attach_predictions(self._current_snapshot, mcts_results)

        # 4. Build output
        analysis = self._build_analysis(start, mcts_results)
        return analysis

    def on_event(self, event: ObservedEvent) -> Optional[TurnAnalysis]:
        """
        Called for each observed game event.

        Matches against current worlds, updates weights, prunes/resamples.
        Returns updated analysis if significant change detected.
        """
        if self._current_snapshot is None:
            return None

        # Assign event ID
        self._event_counter += 1
        if not event.event_id:
            event.event_id = f"evt_{self._current_turn}_{self._event_counter}"
        event.turn_number = self._current_turn

        self._current_turn_events.append(event)

        # 1. Match event against all worlds
        match_results = self.matcher.match_snapshot(
            self._current_snapshot, event
        )

        # 2. Update weights
        self._current_snapshot = self.world_manager.update_weights(
            self._current_snapshot, match_results
        )

        # 2.5 Evolve world states from observation evidence
        # After matching, update each world's game_state so subsequent
        # events in this turn see differentiated states across worlds.
        # This is the core of Bayesian belief tracking: worlds that
        # correctly predicted the event evolve plausibly, worlds that
        # didn't show state inconsistency.
        self._evolve_worlds_from_event(event)

        # 3. Prune low-weight worlds
        worlds_before = len(self._current_snapshot.worlds)
        self._current_snapshot = self.world_manager.prune(
            self._current_snapshot
        )
        worlds_pruned = worlds_before - len(self._current_snapshot.worlds)

        # 4. Resample if needed
        worlds_before_resample = len(self._current_snapshot.worlds)
        self._current_snapshot = self.world_manager.resample(
            self._current_snapshot
        )

        # 4.5 Re-seed opponent hands after resample.
        # Resample clones surviving worlds — all clones share the same
        # opponent.hand from their parent. Re-seeding gives each clone
        # a DIFFERENT hand (per-world deterministic seed), restoring
        # hypothesis diversity for the next event's observation matching.
        self._reseed_worlds()

        return TurnAnalysis(
            turn_number=self._current_turn,
            snapshot=self._current_snapshot,
            belief_state=self.world_manager.get_belief_state(
                self._current_snapshot
            ),
            top_actions=[],
            last_match_results=match_results,
            match_quality=sum(mr.likelihood for mr in match_results) / max(len(match_results), 1),
            worlds_pruned=worlds_pruned,
            worlds_after_resample=len(self._current_snapshot.worlds),
            elapsed_s=0.0,
        )

    def on_turn_end(self) -> Optional[TurnAnalysis]:
        """Called at turn end. Flush pending events and prepare for next turn."""
        if self._current_snapshot is None:
            return None

        # Final cleanup
        self._current_snapshot = self.world_manager.prune(
            self._current_snapshot
        )
        self._current_snapshot = self.world_manager.resample(
            self._current_snapshot
        )
        self._reseed_worlds()

        # Reset event buffer
        self._current_turn_events = []

        belief = self.world_manager.get_belief_state(self._current_snapshot)
        return TurnAnalysis(
            turn_number=self._current_turn,
            snapshot=self._current_snapshot,
            belief_state=belief,
            top_actions=[],
            elapsed_s=0.0,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_current_belief(self) -> Optional[BeliefState]:
        """Get the current belief state without triggering computation."""
        if self._current_snapshot is None:
            return None
        return self.world_manager.get_belief_state(self._current_snapshot)

    def get_current_snapshot(self) -> Optional[WorldSnapshot]:
        """Get the raw world snapshot."""
        return self._current_snapshot

    def format_output(self, analysis: TurnAnalysis) -> str:
        """Format a TurnAnalysis as a human-readable report."""
        return self.output.format_turn(analysis)

    def reset(self) -> None:
        """Reset the tracker to initial state (new game)."""
        self._current_snapshot = None
        self._current_turn = 0
        self._current_turn_events = []
        self._event_counter = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_mcts(
        self, snapshot: WorldSnapshot
    ) -> Dict[str, MCTSResult]:
        """Run MCTS UCT on worlds. Returns {world_id: result}.

        Creates genuine prediction diversity per world by:
          1. Perturbing each world's game_state slightly (different hidden info
             assumptions: opponent hand size, mana noise) before search.
          2. Seeding random state per world so MCTS rollouts diverge.

        This ensures the ObservationMatcher can differentiate worlds even when
        all start from the same observed game state.
        """
        import random
        import copy as py_copy
        results: Dict[str, MCTSResult] = {}

        if self.config.mcts_per_world:
            worlds_to_search = snapshot.worlds
        else:
            best = snapshot.get_best_world()
            worlds_to_search = [best] if best else []

        for w in worlds_to_search:
            if w.game_state is None:
                continue
            try:
                # ── Seed opponent hand with observed cards ──
                # Each world gets a different random subset of observed card_ids.
                # When PLAY_CARD events fire, worlds that had the card in their
                # opponent.hand get higher match likelihood — GENUINE evidence-
                # based differentiation, not artificial signatures.
                self._populate_opponent_hand(w)

                saved_state = random.getstate()
                world_seed = (
                    hash(w.world_id + str(self._current_turn)) & 0xFFFFFFFF
                )
                random.seed(world_seed)

                # ── Perturb state for prediction diversity ──
                search_state = w.game_state.copy() if hasattr(w.game_state, 'copy') else w.game_state
                if search_state is not w.game_state:
                    # Perturb opponent hand count (simulates different hidden info)
                    if hasattr(search_state, 'opponent') and search_state.opponent:
                        opp = search_state.opponent
                        if hasattr(opp, 'hand_count'):
                            hand_noise = random.choice([-1, 0, 0, 1])
                            opp.hand_count = max(0, opp.hand_count + hand_noise)
                    # Slight mana noise (±1, keeps >= 0)
                    if hasattr(search_state, 'mana') and search_state.mana:
                        mana_noise = random.choice([-1, 0, 0, 1])
                        search_state.mana.available = max(
                            0, search_state.mana.available + mana_noise
                        )
                        if hasattr(search_state.mana, 'max_mana'):
                            search_state.mana.max_mana = max(
                                search_state.mana.available,
                                search_state.mana.max_mana,
                            )

                result = self.mcts.search(search_state)
                results[w.world_id] = result
                w.mcts_visit_count = result.root_node.visit_count
                w.mcts_value = (
                    result.root_node.q_value
                    if result.root_node.visit_count > 0
                    else 0.0
                )

                random.setstate(saved_state)
            except Exception as exc:
                if self.config.verbose:
                    print(f"[Tracker] MCTS failed for {w.world_id}: {exc}")

        return results

    def _attach_predictions(self, snapshot: WorldSnapshot,
                            mcts_results: Dict[str, MCTSResult]) -> None:
        """Attach MCTS branch predictions to worlds."""
        for w in snapshot.worlds:
            result = mcts_results.get(w.world_id)
            if result is None:
                continue

            w.predicted_branches = []
            for child in result.root_node.children:
                action = child.action
                if action is None:
                    continue
                bp = BranchPrediction(
                    action=action,
                    action_description=action.describe(),
                    visit_count=child.visit_count,
                    value=child.q_value,
                    confidence=(
                        child.visit_count / max(result.root_node.visit_count, 1)
                    ),
                )
                w.predicted_branches.append(bp)

    def _load_deck_library(self) -> dict:
        """Lazy-load deck_library.json for cold-start opponent hand seeding."""
        if self._deck_library is None:
            try:
                import json
                from pathlib import Path
                path = (
                    Path(__file__).resolve().parent.parent.parent
                    / "analysis" / "data" / "deck_library.json"
                )
                if path.exists():
                    self._deck_library = json.loads(
                        path.read_text(encoding="utf-8")
                    )
                else:
                    self._deck_library = {}
            except Exception as exc:
                if self.config.verbose:
                    print(f"[Tracker] Failed to load deck library: {exc}")
                self._deck_library = {}
        return self._deck_library

    def _cold_start_hand(
        self,
        hero_class: str,
        hand_size: int,
        rng: 'random.Random',
    ) -> List[str]:
        """Seed opponent hand from deck library when no observations exist.

        Uses cross-deck high-retention cards for the opponent's class.
        Each world gets a different subset, weighted by retention score,
        creating genuine diversity in early-game hypotheses.

        Returns:
            List of card_id strings to place in opponent hand.
        """
        lib = self._load_deck_library()
        class_data = lib.get(hero_class, {})
        if not class_data:
            return []

        # Build diversified candidate pool:
        # 1. High-retention + medium-retention cards from common pool
        # 2. Also pull from individual deck pools for variety
        candidate_ids: List[str] = []
        seen_ids: set = set()

        # Common high retention (appear in 50%+ decks of this class)
        for c in class_data.get('common_high_retention', []):
            cid = c.get('card_id', '')
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                # Insert multiple copies weighted by retention score
                weight = max(1, int(c.get('retention_score', 10) / 10))
                candidate_ids.extend([cid] * weight)

        # All-class cards (unique from union)
        for c in class_data.get('all_cards', []):
            cid = c.get('card_id', '')
            if cid and cid not in seen_ids:
                seen_ids.add(cid)
                weight = max(1, int(c.get('retention_score', 10) / 15))
                candidate_ids.extend([cid] * weight)

        if not candidate_ids:
            return []

        n_fill = min(hand_size, len(candidate_ids))
        if n_fill <= 0:
            return []

        # Sample without replacement, weighted by repetition in candidate_ids
        # (repeat count acts as weight)
        return rng.sample(candidate_ids, n_fill)

    def _populate_opponent_hand(self, world: World) -> None:
        """Seed opponent hand with observed card_ids or cold-start deck library.

        Two modes:
          1. Evidence-based (observed_opp_cards not empty):
             Each world gets a different random subset of observed cards.
             When PLAY_CARD events fire, worlds that had the card in their
             opponent hand get higher likelihood from _match_card.

          2. Cold-start (no observations yet, early game):
             Uses deck_library.json to seed from high-retention cards for
             the opponent's class. Each world gets a different subset.

        This is the core of evidence-driven belief tracking: instead of
        artificial signatures, worlds diverge because they hold different
        hypotheses about hidden information (the opponent's hand).
        """
        import random as _random
        gs = getattr(world, 'game_state', None)
        if gs is None or gs.opponent is None:
            return

        hand_count = getattr(gs.opponent, 'hand_count', 0)
        if hand_count <= 0:
            return

        observed = world.metadata.get('observed_opp_cards', set())
        rng = _random.Random(world.world_id + str(self._current_turn) + "_hand")

        if observed:
            # ── Evidence-based seeding ──
            n_fill = min(hand_count, len(observed))
            if n_fill <= 0:
                return
            selected = rng.sample(list(observed), n_fill)
        else:
            # ── Cold-start seeding from deck library ──
            # opponent.hero_class is at gs.opponent.hero.hero_class (HeroState)
            opp_hero = getattr(gs.opponent, 'hero', None)
            opp_class = getattr(opp_hero, 'hero_class', '') if opp_hero else ''
            if not opp_class:
                return
            selected = self._cold_start_hand(opp_class, hand_count, rng)
            if not selected:
                return

        # Resolve card data from DB
        try:
            from analysis.card.data.card_data import get_db
            db = get_db()
        except Exception:
            db = None

        hand_cards = []
        for cid in selected:
            raw = db.get_card(cid) if db else None
            if raw:
                hand_cards.append(Card(
                    card_id=cid,
                    name=raw.get('name', cid),
                    cost=raw.get('cost', 0),
                    card_type=raw.get('type', '').upper(),
                ))
            else:
                hand_cards.append(Card(card_id=cid, name=cid, card_type='UNKNOWN'))

        gs.opponent.hand = hand_cards

    def _evolve_worlds_from_event(self, event: ObservedEvent) -> None:
        """Evolve all world states to reflect an observed event.

        After an event is matched and weights updated, this method
        propagates the event's effect into each world's game_state.

        Key operations:
        1. Record observed card_ids in metadata (for next turn's hand seeding)
        2. Remove played cards from opponent.hand (for same-turn differentiation)
        3. Apply simple state changes (draws → increment hand_count)

        This makes subsequent events in the same turn see different states
        across worlds, producing genuine evidence-driven differentiation.
        """
        if self._current_snapshot is None:
            return

        # Record card_id in all worlds' metadata
        if event.card_id:
            for w in self._current_snapshot.worlds:
                observed = w.metadata.setdefault('observed_opp_cards', set())
                observed.add(event.card_id)

        # For PLAY_CARD: remove from opponent hand if present
        if event.event_type.upper() in ('PLAY_CARD', 'PLAY_MINION',
                                          'PLAY_SPELL', 'PLAY_WEAPON'):
            for w in self._current_snapshot.worlds:
                gs = getattr(w, 'game_state', None)
                if gs is None or gs.opponent is None:
                    continue
                opp_hand = getattr(gs.opponent, 'hand', None)
                if opp_hand and event.card_id:
                    gs.opponent.hand = [
                        c for c in opp_hand
                        if getattr(c, 'card_id', None) != event.card_id
                    ]

    def _reseed_worlds(self) -> None:
        """Re-seed opponent.hand for all worlds after resample.

        After resample clones surviving worlds, all clones share identical
        opponent.hand. This method gives each clone a fresh, unique hand
        using per-world deterministic seeds, restoring genuine hypothesis
        diversity for the next event's observation matching.

        Called after each resample step (both mid-turn and turn-end).
        """
        if self._current_snapshot is None:
            return
        for w in self._current_snapshot.worlds:
            gs = getattr(w, 'game_state', None)
            if gs is None or gs.opponent is None:
                continue
            # Clear existing hand so _populate_opponent_hand re-generates
            gs.opponent.hand = []
            self._populate_opponent_hand(w)

    def _build_analysis(self, start_time: float,
                        mcts_results: Dict[str, MCTSResult]) -> TurnAnalysis:
        """Assemble the TurnAnalysis from current state."""
        elapsed = time.monotonic() - start_time

        total_nodes = sum(
            r.num_nodes for r in mcts_results.values()
        )
        mcts_time = sum(
            r.search_stats.get("time_s", 0.0) for r in mcts_results.values()
        )

        # Top actions across all worlds
        all_top_actions: List[str] = []
        top_action_scores: Dict[str, float] = {}
        for w in self._current_snapshot.worlds if self._current_snapshot else []:
            for bp in w.predicted_branches:
                score = w.weight * bp.confidence
                top_action_scores[bp.action_description] = (
                    top_action_scores.get(bp.action_description, 0.0) + score
                )
        all_top_actions = sorted(top_action_scores, key=top_action_scores.get,
                                 reverse=True)[:10]

        # Best MCTS action
        best_action = None
        if mcts_results:
            best_result = max(
                mcts_results.values(),
                key=lambda r: r.root_node.visit_count,
                default=None,
            )
            if best_result:
                best_action = best_result.best_action

        belief = self.world_manager.get_belief_state(
            self._current_snapshot
        ) if self._current_snapshot else BeliefState(
            turn_number=self._current_turn, entropy=0.0,
            num_worlds=0, top_worlds=[]
        )

        return TurnAnalysis(
            turn_number=self._current_turn,
            snapshot=self._current_snapshot,
            belief_state=belief,
            top_actions=all_top_actions,
            total_mcts_nodes=total_nodes,
            mcts_time_s=mcts_time,
            mcts_best_action=best_action,
            match_quality=0.0,
            elapsed_s=elapsed,
        )

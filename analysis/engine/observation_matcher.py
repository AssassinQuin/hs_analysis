"""
Observation Matcher: compares real game events against world predictions
to determine likelihood that a given World produced the observed event.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from analysis.card.abilities.definition import Action, ActionKind
from analysis.card.engine.state import GameState
from analysis.engine.world_branch import (
    BranchPrediction,
    ObservedEvent,
    World,
    WorldSnapshot,
)


@dataclass
class MatchResult:
    """Result of matching one observed event against one world."""
    world_id: str
    event_id: str
    likelihood: float          # P(observation | world) in [0, 1]
    matched_type: bool
    matched_card: bool
    matched_target: bool
    matched_mana: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Main Matcher
# ---------------------------------------------------------------------------

class ObservationMatcher:
    """
    Computes P(observed_event | world) by evaluating how well the world's
    predicted actions and state match what was actually observed.
    """

    # Weight for each matching dimension
    TYPE_WEIGHT = 0.30
    CARD_WEIGHT = 0.30
    TARGET_WEIGHT = 0.20
    MANA_WEIGHT = 0.10
    STATE_DELTA_WEIGHT = 0.10

    def match(self, world: World, event: ObservedEvent) -> MatchResult:
        """
        Compute likelihood that `world` produced `event`.
        Returns P(event | world) ∈ [0, 1].
        """
        score = 0.0
        matched_type = matched_card = matched_target = matched_mana = False
        details: List[str] = []

        # 1. Action type match — can the world produce this event type?
        type_score, matched_type = self._match_action_type(world, event)
        score += type_score * self.TYPE_WEIGHT
        if matched_type:
            details.append(f"type={event.event_type}")

        # 2. Card match — does the world have this card?
        card_score, matched_card = self._match_card(world, event)
        score += card_score * self.CARD_WEIGHT
        if matched_card:
            details.append(f"card={event.card_id}")

        # 3. Target match — does the world's state support this target?
        target_score, matched_target = self._match_target(world, event)
        score += target_score * self.TARGET_WEIGHT
        if matched_target:
            details.append("target_ok")

        # 4. Mana match — can the world afford this action?
        mana_score, matched_mana = self._match_mana(world, event)
        score += mana_score * self.MANA_WEIGHT
        if matched_mana:
            details.append("mana_ok")

        # 5. State delta — has the world state diverged significantly?
        state_score = self._match_state_delta(world, event)
        score += state_score * self.STATE_DELTA_WEIGHT

        return MatchResult(
            world_id=world.world_id,
            event_id=event.event_id,
            likelihood=max(0.0, min(1.0, score)),
            matched_type=matched_type,
            matched_card=matched_card,
            matched_target=matched_target,
            matched_mana=matched_mana,
            detail=" | ".join(details) if details else "no_match",
        )

    def match_snapshot(self, snapshot: WorldSnapshot,
                       event: ObservedEvent) -> List[MatchResult]:
        """Match one event against all worlds in a snapshot."""
        return [
            self.match(w, event)
            for w in snapshot.worlds
        ]

    def match_batch(self, snapshot: WorldSnapshot,
                    events: List[ObservedEvent]) -> Dict[str, List[MatchResult]]:
        """Match multiple events, returning {event_id: [results]}."""
        return {
            ev.event_id: self.match_snapshot(snapshot, ev)
            for ev in events
        }

    # ------------------------------------------------------------------
    # Dimension scoring
    # ------------------------------------------------------------------

    def _match_action_type(self, world: World,
                           event: ObservedEvent) -> tuple[float, bool]:
        """Score [0,1] whether the world predicts this action type.

        Uses world predictions first (differentiates worlds), falls back
        to legal actions from game_state if no predictions available.
        """
        event_type = event.event_type.upper()

        # Map observed events to action kinds
        event_to_kind = {
            "PLAY_CARD": ActionKind.PLAY,
            "ATTACK": ActionKind.ATTACK,
            "HERO_POWER": ActionKind.HERO_POWER,
            "END_TURN": ActionKind.END_TURN,
            "PLAY_MINION": ActionKind.PLAY,
            "PLAY_SPELL": ActionKind.PLAY,
            "PLAY_WEAPON": ActionKind.PLAY,
            "PLAY_HERO": ActionKind.PLAY,
        }

        expected_kind = event_to_kind.get(event_type)
        if expected_kind is None:
            return 0.5, True  # unknown type = neutral

        # ── Try world predictions first (world-specific) ──
        predictions = world.predicted_branches
        if predictions:
            # Sum confidence of branches matching this action type
            matching_confidence = sum(
                bp.confidence for bp in predictions
                if bp.action and bp.action.action_type == expected_kind
            )
            if matching_confidence > 0:
                # Scale: higher confidence prediction → higher score
                # 0.5 base + up to 0.5 bonus from confidence
                score = min(1.0, 0.5 + matching_confidence)
                return score, True

        # ── Fall back to legal actions from game_state ──
        state = world.game_state
        if state is None:
            return 0.0, False

        try:
            from analysis.card.engine.rules import enumerate_legal
            for a in enumerate_legal(state):
                if a.action_type == expected_kind:
                    return 1.0, True
        except Exception:
            pass

        return 0.0, False

    def _match_card(self, world: World,
                    event: ObservedEvent) -> tuple[float, bool]:
        """Score [0,1] whether the world contains/predicts the observed card."""
        if not event.card_id:
            return 0.5, True  # no card info = neutral

        state = world.game_state

        # 1. Check if card is in the world's hand or board (strong signal)
        if state is not None:
            for card in state.hand:
                if hasattr(card, 'card_id') and card.card_id == event.card_id:
                    return 1.0, True
            for m in state.board:
                if hasattr(m, 'card_id') and m.card_id == event.card_id:
                    return 1.0, True

        # 1b. Check opponent hand (world-specific — evidence-driven!)
        # Each world may have different hypothetical opponent hand content,
        # so this creates genuine evidence-based differentiation:
        #   World A had card in opponent.hand → match = 1.0
        #   World B didn't → match = 0.3
        if state is not None and state.opponent is not None:
            for card in state.opponent.hand:
                if hasattr(card, 'card_id') and card.card_id == event.card_id:
                    return 1.0, True

        # 2. Check if any predicted branch involves this card (world-specific)
        predictions = world.predicted_branches
        if predictions:
            for bp in predictions:
                if bp.action and bp.action.card_id == event.card_id:
                    # World predicted this card! Confidence-weighted score
                    score = min(1.0, 0.5 + bp.confidence)
                    return score, True

        # Not seen or predicted — could be in opponent's hidden hand
        return 0.3, False

    def _match_target(self, world: World,
                      event: ObservedEvent) -> tuple[float, bool]:
        """Score [0,1] whether the world supports the observed target."""
        if event.target_id is None or event.event_type.upper() == "END_TURN":
            return 1.0, True  # no target needed or turn end

        state = world.game_state
        if state is None:
            return 0.0, False

        # Check if target exists in the world's board
        target_exists = False
        for m in state.board:
            if getattr(m, 'dbf_id', None) == event.target_id:
                target_exists = True
                break
            if id(m) == event.target_id:
                target_exists = True
                break

        if target_exists:
            return 1.0, True
        return 0.2, False  # target might be somewhere else

    def _match_mana(self, world: World,
                    event: ObservedEvent) -> tuple[float, bool]:
        """Score [0,1] whether the world can afford this action."""
        mana_spent = event.mana_spent
        if mana_spent <= 0:
            return 1.0, True  # no mana info

        state = world.game_state
        if state is None:
            return 0.0, False

        available = state.mana.available if state.mana else 0
        if available >= mana_spent:
            return 1.0, True
        # Was close?
        ratio = available / max(mana_spent, 1)
        return max(0.0, ratio), False

    def _match_state_delta(self, world: World,
                           event: ObservedEvent) -> float:
        """Score [0,1] based on how plausible the world state is."""
        state = world.game_state
        if state is None:
            return 0.0

        # Health sanity check
        hp = state.hero.hp if state.hero else 30
        if hp <= 0:
            return 0.0  # world is dead

        opp_hp = state.opponent.hero.hp if (state.opponent and state.opponent.hero) else 30
        if opp_hp <= 0:
            return 1.0  # world expects opponent dead

        # Mana sanity
        mana = state.mana.available if state.mana else 0
        if mana < 0:
            return 0.0

        return 1.0  # state looks plausible


# ---------------------------------------------------------------------------
# Batch match summarizer
# ---------------------------------------------------------------------------

class MatchSummarizer:
    """Aggregate per-world match scores across a sequence of events."""

    def __init__(self, decay: float = 0.8):
        """
        Args:
            decay: Exponential moving average factor for time-decaying match scores.
                   Higher = recent events matter more.
        """
        self.decay = decay

    def compute_world_weights(self, snapshot: WorldSnapshot,
                              match_results: List[List[MatchResult]],
                              events: List[ObservedEvent]) -> List[World]:
        """
        Given a snapshot and match results from a batch of events,
        return updated worlds with new weights.

        Each world's weight is updated by: w *= ∏ match_likelihood^(decay^age)
        """
        if not snapshot.worlds:
            return []

        worlds = {w.world_id: w for w in snapshot.worlds}
        update_counts: Dict[str, int] = {}

        for i, results_for_event in enumerate(match_results):
            age = len(events) - i - 1  # 0 = most recent
            factor = self.decay ** age

            for mr in results_for_event:
                if mr.world_id in worlds:
                    worlds[mr.world_id].weight *= (
                        1.0 - factor + factor * mr.likelihood
                    )
                    update_counts[mr.world_id] = (
                        update_counts.get(mr.world_id, 0) + 1
                    )

        # Normalize
        result = list(worlds.values())
        total = sum(w.weight for w in result)
        if total > 0:
            for w in result:
                w.weight /= total
        return result

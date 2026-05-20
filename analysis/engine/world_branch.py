"""
World / particle data structures for the MCTS particle-filter hybrid.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analysis.card.abilities.definition import Action
from analysis.card.engine.state import GameState


@dataclass
class ObservedEvent:
    """
    An observed game event from the Power.log / tracker pipeline.

    Used by the observation matcher to compare real events against world predictions.
    """
    event_type: str  # PLAY_CARD | ATTACK | HERO_POWER | END_TURN | SECRET_TRIGGER | etc
    card_id: Optional[str] = None
    target_id: Optional[int] = None
    turn_number: int = 0
    event_id: str = ""
    player_controller: int = 0
    mana_spent: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimulationRecord:
    """One simulated trajectory from a World."""
    world_id: str
    turn_number: int
    actions: List[Action]
    final_state: Optional[GameState]
    cumulative_reward: float
    depth: int
    is_complete: bool  # game ended during rollout


@dataclass
class BranchPrediction:
    """A predicted future branch from a World at a decision point."""
    action: Action
    action_description: str
    visit_count: int
    value: float  # Q-value from MCTS
    confidence: float  # visit_count / total_visits
    child_worlds: List[World] = field(default_factory=list)


@dataclass
class WorldMetadata:
    """Metadata about a world's lifecycle."""
    created_turn: int
    last_active_turn: int
    match_events: List[ObservedEvent] = field(default_factory=list)
    mismatch_events: List[ObservedEvent] = field(default_factory=list)
    parent_world_id: Optional[str] = None
    ancestry: List[str] = field(default_factory=list)  # world_ids from root
    simulation_records: List[SimulationRecord] = field(default_factory=list)
    best_child_action: Optional[Action] = None
    entropy: float = 0.0


@dataclass
class World:
    """
    One particle / hypothesis about the true game state.

    Each World represents a possible future branch of the game. The particle
    filter maintains a set of Worlds, each weighted by how well it matches
    the observed game events.
    """
    world_id: str
    game_state: GameState
    weight: float = 1.0

    # branching
    parent_world_id: Optional[str] = None
    branch_action: Optional[Action] = None  # what action created this world
    depth: int = 0  # how many turns simulated

    # tracking
    action_history: List[Action] = field(default_factory=list)
    matched_observations: List[str] = field(default_factory=list)  # event_ids
    predicted_branches: List[BranchPrediction] = field(default_factory=list)

    # search results from MCTS
    mcts_visit_count: int = 0
    mcts_value: float = 0.0

    metadata: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create_root(game_state: GameState, turn: int) -> World:
        """Create the first World from an initial GameState."""
        return World(
            world_id=f"root_t{turn}_{uuid.uuid4().hex[:8]}",
            game_state=game_state,
            weight=1.0,
            depth=0,
            metadata={"created_turn": turn, "is_root": True},
        )

    def create_child(self, game_state: GameState, action: Action,
                     turn: int) -> World:
        """Branch a new World from this one by applying an action."""
        child_id = (f"w_{uuid.uuid4().hex[:12]}"
                    f"_t{turn}_d{self.depth + 1}")
        child = World(
            world_id=child_id,
            game_state=game_state,
            weight=self.weight,
            parent_world_id=self.world_id,
            branch_action=action,
            depth=self.depth + 1,
            action_history=self.action_history + [action],
            metadata={
                "created_turn": turn,
                "parent_weight": self.weight,
                "ancestry": self.metadata.get("ancestry", []) + [self.world_id],
            },
        )
        return child

    def normalize_weights(self, worlds: List[World]) -> List[World]:
        """Normalize weights so they sum to 1.0."""
        total = sum(w.weight for w in worlds)
        if total <= 0:
            n = len(worlds)
            for w in worlds:
                w.weight = 1.0 / n
        else:
            for w in worlds:
                w.weight /= total
        return worlds


@dataclass
class WorldSnapshot:
    """
    A point-in-time snapshot of the entire particle set.
    Carried across turns for continuity.
    """
    turn_number: int
    worlds: List[World]
    total_weight: float = 1.0
    entropy: float = 0.0
    dominant_world_id: Optional[str] = None

    def get_best_world(self) -> Optional[World]:
        """Return the world with the highest weight."""
        if not self.worlds:
            return None
        return max(self.worlds, key=lambda w: w.weight)

    def get_world_by_id(self, world_id: str) -> Optional[World]:
        """Find a world by ID."""
        for w in self.worlds:
            if w.world_id == world_id:
                return w
            for bp in w.predicted_branches:
                for cw in bp.child_worlds:
                    if cw.world_id == world_id:
                        return cw
        return None

    def top_worlds(self, k: int = 5) -> List[World]:
        """Return the top-k worlds by weight."""
        return sorted(self.worlds, key=lambda w: w.weight, reverse=True)[:k]

    def probability_distribution(self) -> Dict[str, float]:
        """Return {world_id: probability} for all worlds."""
        return {w.world_id: w.weight for w in self.worlds}

    def action_probabilities(self) -> Dict[str, float]:
        """Aggregate action-level probabilities across all worlds.

        Returns {action_key: probability} by summing weights of worlds
        that predict/lead to each action.
        """
        action_probs: Dict[str, float] = {}
        for w in self.worlds:
            for bp in w.predicted_branches:
                key = bp.action_description
                action_probs[key] = action_probs.get(key, 0.0) + (
                    w.weight * bp.confidence
                )
        return action_probs

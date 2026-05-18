#!/usr/bin/env python3
"""sim_logger.py — Detailed simulation logging for MCTS and opponent turn simulation.

Records every step of the simulation process:
- Actions taken (PLAY, ATTACK, HERO_POWER, etc.)
- Card effects triggered (damage, summon, draw, buff, etc.)
- Effect chains (card A generates card B → card B played)
- Death resolution (deathrattle, reborn, corpse gain)
- State snapshots (board, hand, HP, mana)

Usage:
    from analysis.search.sim_logger import SimLogger, get_sim_logger

    logger = get_sim_logger()
    with logger.phase("opponent_turn", turn=5):
        logger.log_action("PLAY", card="Fireball", cost=4, target="enemy_hero")
        logger.log_effect("DAMAGE", value=6, target="enemy_hero")
        logger.log_state_snapshot(state)
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
# Data structures
# ──────────────────────────────────────────────────────────────────

@dataclass
class SimStep:
    """A single simulation step record."""
    step_type: str          # "action", "effect", "death", "state", "chain_start", "chain_end"
    detail: str             # Human-readable description
    timestamp: float = 0.0  # Relative time from phase start
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SimPhase:
    """A simulation phase (e.g., one opponent turn)."""
    phase_name: str
    turn: int = 0
    steps: List[SimStep] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    summary: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class SimRecord:
    """Complete simulation record for one MCTS search or turn advance."""
    phases: List[SimPhase] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────
# SimLogger — main logging interface
# ──────────────────────────────────────────────────────────────────

class SimLogger:
    """Detailed simulation logger for debugging MCTS and opponent simulation.

    Features:
    - Phase-based logging (opponent_turn, our_turn, effect_chain, etc.)
    - Step-by-step action/effect recording
    - State snapshot capture
    - JSON export for post-analysis
    - Performance tracking (step count, duration)
    """

    def __init__(self, enabled: bool = True, max_phases: int = 100, max_steps_per_phase: int = 500):
        self.enabled = enabled
        self.max_phases = max_phases
        self.max_steps_per_phase = max_steps_per_phase
        self._record = SimRecord()
        self._current_phase: Optional[SimPhase] = None
        self._phase_start: float = 0.0

    @property
    def record(self) -> SimRecord:
        return self._record

    def reset(self) -> None:
        """Clear all recorded data."""
        self._record = SimRecord()
        self._current_phase = None

    # ── Phase management ────────────────────────────────────────

    @contextmanager
    def phase(self, name: str, **kwargs):
        """Context manager for a simulation phase.

        Usage:
            with logger.phase("opponent_turn", turn=5):
                logger.log_action(...)
        """
        if not self.enabled:
            yield
            return

        phase = SimPhase(phase_name=name, **kwargs)
        phase.start_time = time.perf_counter()
        self._current_phase = phase
        self._phase_start = time.perf_counter()
        try:
            yield
        finally:
            phase.end_time = time.perf_counter()
            self._current_phase = None
            if len(self._record.phases) < self.max_phases:
                self._record.phases.append(phase)

    # ── Step logging ────────────────────────────────────────────

    def _add_step(self, step_type: str, detail: str, **data) -> None:
        """Add a step to the current phase."""
        if not self.enabled or self._current_phase is None:
            return
        if len(self._current_phase.steps) >= self.max_steps_per_phase:
            return

        step = SimStep(
            step_type=step_type,
            detail=detail,
            timestamp=time.perf_counter() - self._phase_start,
            data=data,
        )
        self._current_phase.steps.append(step)

    def log_action(self, action_type: str, **data) -> None:
        """Log an action taken during simulation.

        Args:
            action_type: PLAY, ATTACK, HERO_POWER, END_TURN, etc.
            **data: card, cost, target, damage, etc.
        """
        card_name = data.get('card', '')
        cost = data.get('cost', '')
        target = data.get('target', '')
        detail = f"{action_type}"
        if card_name:
            detail += f" {card_name}"
        if cost != '':
            detail += f" (cost={cost})"
        if target:
            detail += f" -> {target}"
        self._add_step("action", detail, **data)

        # Also log to Python logging at DEBUG level
        log.debug("[SimLog] %s", detail)

    def log_effect(self, effect_kind: str, **data) -> None:
        """Log an effect triggered during simulation.

        Args:
            effect_kind: DAMAGE, SUMMON, DRAW, BUFF, etc.
            **data: value, target, source, etc.
        """
        value = data.get('value', '')
        target = data.get('target', '')
        source = data.get('source', '')
        detail = f"  EFFECT {effect_kind}"
        if source:
            detail += f" from {source}"
        if value != '':
            detail += f" value={value}"
        if target:
            detail += f" -> {target}"
        self._add_step("effect", detail, **data)

    def log_death(self, minion_name: str, **data) -> None:
        """Log a minion death and its deathrattle resolution."""
        detail = f"  DEATH {minion_name}"
        deathrattle = data.get('deathrattle', '')
        if deathrattle:
            detail += f" deathrattle={deathrattle}"
        reborn = data.get('reborn', False)
        if reborn:
            detail += " [REBORN]"
        self._add_step("death", detail, **data)

    def log_chain_start(self, source_card: str, **data) -> None:
        """Start logging an effect chain (card A → generates card B)."""
        detail = f"  CHAIN_START {source_card} generated new cards"
        generated = data.get('generated', [])
        if generated:
            detail += f" {generated}"
        self._add_step("chain_start", detail, **data)

    def log_chain_play(self, chain_depth: int, card_name: str, **data) -> None:
        """Log playing a generated card from an effect chain."""
        detail = f"  CHAIN_PLAY depth={chain_depth} {card_name}"
        cost = data.get('cost', '')
        if cost != '':
            detail += f" (cost={cost})"
        self._add_step("chain_play", detail, **data)

    def log_chain_end(self, source_card: str, chain_depth: int, **data) -> None:
        """End logging an effect chain."""
        detail = f"  CHAIN_END {source_card} depth={chain_depth}"
        self._add_step("chain_end", detail, **data)

    def log_state_snapshot(self, state: 'GameState', label: str = "") -> None:
        """Capture a compact state snapshot for debugging."""
        if not self.enabled or self._current_phase is None:
            return

        snap = _compact_state(state)
        detail = f"  SNAPSHOT {label}" if label else "  SNAPSHOT"
        detail += (
            f" our_hp={snap['our_hp']} opp_hp={snap['opp_hp']}"
            f" our_board={snap['our_board_count']} opp_board={snap['opp_board_count']}"
            f" our_hand={snap['our_hand_count']} opp_hand={snap['opp_hand_count']}"
            f" mana={snap['mana']}"
        )
        self._add_step("state", detail, **snap)

    def log_warning(self, message: str, **data) -> None:
        """Log a warning during simulation."""
        self._add_step("warning", f"  WARNING: {message}", **data)
        log.warning("[SimLog] %s", message)

    # ── Summary ─────────────────────────────────────────────────

    def summarize_phase(self) -> Dict[str, Any]:
        """Compute summary statistics for the current phase."""
        if self._current_phase is None:
            return {}

        phase = self._current_phase
        action_count = sum(1 for s in phase.steps if s.step_type == "action")
        effect_count = sum(1 for s in phase.steps if s.step_type == "effect")
        chain_count = sum(1 for s in phase.steps if s.step_type == "chain_start")
        death_count = sum(1 for s in phase.steps if s.step_type == "death")

        summary = {
            "phase_name": phase.phase_name,
            "turn": phase.turn,
            "duration_ms": phase.duration_ms,
            "action_count": action_count,
            "effect_count": effect_count,
            "chain_count": chain_count,
            "death_count": death_count,
            "total_steps": len(phase.steps),
        }
        phase.summary = summary
        return summary

    # ── Export ───────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Export the full simulation record as a dict."""
        result = {"metadata": self._record.metadata, "phases": []}
        for phase in self._record.phases:
            phase_dict = {
                "phase_name": phase.phase_name,
                "turn": phase.turn,
                "duration_ms": phase.duration_ms,
                "summary": phase.summary,
                "steps": [
                    {
                        "type": s.step_type,
                        "detail": s.detail,
                        "time": round(s.timestamp, 4),
                        "data": s.data,
                    }
                    for s in phase.steps
                ],
            }
            result["phases"].append(phase_dict)
        return result

    def to_json(self, path: str) -> None:
        """Export the simulation record as a JSON file."""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False, default=str)
        log.info("SimLogger: exported %d phases to %s", len(self._record.phases), path)

    def print_summary(self) -> str:
        """Print a human-readable summary of all phases."""
        lines = []
        for i, phase in enumerate(self._record.phases):
            lines.append(f"=== Phase {i}: {phase.phase_name} (turn={phase.turn}) ===")
            lines.append(f"  Duration: {phase.duration_ms:.1f}ms")
            if phase.summary:
                lines.append(f"  Actions: {phase.summary.get('action_count', 0)}")
                lines.append(f"  Effects: {phase.summary.get('effect_count', 0)}")
                lines.append(f"  Chains:  {phase.summary.get('chain_count', 0)}")
                lines.append(f"  Deaths:  {phase.summary.get('death_count', 0)}")
            # Print last state snapshot
            for step in reversed(phase.steps):
                if step.step_type == "state":
                    lines.append(f"  Final: {step.detail.strip()}")
                    break
            lines.append("")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────
# Global instance
# ──────────────────────────────────────────────────────────────────

_global_logger: Optional[SimLogger] = None


def get_sim_logger() -> SimLogger:
    """Get the global SimLogger instance."""
    global _global_logger
    if _global_logger is None:
        _global_logger = SimLogger(enabled=True)
    return _global_logger


def set_sim_logger(logger: SimLogger) -> None:
    """Set the global SimLogger instance."""
    global _global_logger
    _global_logger = logger


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _compact_state(state: 'GameState') -> Dict[str, Any]:
    """Create a compact dict representation of a GameState for logging."""
    our_board = ", ".join(
        f"{m.name}({m.attack}/{m.health})" for m in state.board[:7]
    ) if state.board else "empty"
    opp_board = ", ".join(
        f"{m.name}({m.attack}/{m.health})" for m in state.opponent.board[:7]
    ) if state.opponent.board else "empty"

    our_hand = ", ".join(
        getattr(c, 'name', str(c)) for c in state.hand[:10]
    ) if state.hand else "empty"
    opp_hand_names = ", ".join(
        getattr(c, 'name', str(c)) for c in state.opponent.hand[:10]
    ) if state.opponent.hand else f"count={state.opponent.hand_count}"

    return {
        "our_hp": state.hero.hp + state.hero.armor,
        "opp_hp": state.opponent.hero.hp + state.opponent.hero.armor,
        "our_board_count": len(state.board),
        "opp_board_count": len(state.opponent.board),
        "our_hand_count": len(state.hand),
        "opp_hand_count": state.opponent.hand_count,
        "mana": f"{state.mana.available}/{state.mana.max_mana}",
        "our_board": our_board,
        "opp_board": opp_board,
        "our_hand": our_hand,
        "opp_hand": opp_hand_names,
    }

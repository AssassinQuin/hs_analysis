"""
World Tracker Output — formats belief state and analysis results
for human-readable display and machine-readable data export.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from analysis.engine.particle_filter import BeliefState
from analysis.engine.world_branch import WorldSnapshot

if TYPE_CHECKING:
    from analysis.engine.mcts_world_tracker import TurnAnalysis


@dataclass
class FormattedReport:
    """Structured report containing both display and data."""
    display_text: str
    turn_number: int
    top_worlds: List[Dict[str, Any]]
    top_actions: List[Dict[str, Any]]
    diagnostics: Dict[str, Any]
    machine_data: Dict[str, Any]


class WorldTrackerOutput:
    """
    Format world tracker analysis for:
    - Terminal display (colored, tabular)
    - Machine consumption (JSON)
    """

    def __init__(self, compact: bool = False):
        self.compact = compact

    # ------------------------------------------------------------------
    # Main formatting
    # ------------------------------------------------------------------

    def format_turn(self, analysis: TurnAnalysis) -> str:
        """Format a full TurnAnalysis as a display string."""
        lines: List[str] = []
        sep = "─" * 68

        lines.append("")
        lines.append(f"┌─ World Tracker Report ── Turn {analysis.turn_number} "
                     f"{'─' * (40 - len(str(analysis.turn_number)))}┐")
        lines.append(f"│ {sep} │")

        # Header
        bs = analysis.belief_state
        lines.append(f"│  Worlds: {bs.num_worlds} | "
                      f"Entropy: {bs.entropy:.3f} | "
                      f"Confidence: {1.0 - bs.entropy:.2f} "
                      f"{'│'.rjust(10)}")
        lines.append(f"│ {sep} │")

        # Top worlds
        lines.append(f"│  Top Worlds:")
        for i, (wid, prob) in enumerate(bs.top_worlds[:5], 1):
            short_id = wid.split("_")[-1] if "_" in wid else wid[:8]
            bar = self._bar(prob, 20)
            lines.append(f"│    W{i:02d}: {prob:5.1%} {bar}  {short_id}")

        # Remaining worlds count
        remaining = bs.num_worlds - len(bs.top_worlds)
        if remaining > 0:
            lines.append(f"│    ─── {remaining} more worlds "
                         f"({sum(w[1] for w in bs.top_worlds[5:]):.0%}) ───")

        # MCTS results
        if analysis.mcts_best_action:
            lines.append(f"│ {sep} │")
            desc = analysis.mcts_best_action.describe()[:50]
            lines.append(f"│  MCTS Best: {desc}")
            lines.append(f"│  Nodes: {analysis.total_mcts_nodes} | "
                          f"Time: {analysis.mcts_time_s:.1f}s")

        # Top predicted actions
        if analysis.top_actions:
            lines.append(f"│ {sep} │")
            lines.append(f"│  Predicted Actions (weighted):")
            for i, desc in enumerate(analysis.top_actions[:8], 1):
                lines.append(f"│    {i:02d}. {desc[:55]}")

        # Match quality
        if analysis.last_match_results:
            lines.append(f"│ {sep} │")
            lines.append(f"│  Match Quality: {analysis.match_quality:.2%}")

        # Diagnostics
        if analysis.worlds_pruned > 0 or analysis.worlds_after_resample > 0:
            lines.append(f"│ {sep} │")
            diag = []
            if analysis.worlds_pruned:
                diag.append(f"Pruned: {analysis.worlds_pruned}")
            if analysis.worlds_after_resample:
                diag.append(f"After resample: {analysis.worlds_after_resample}")
            lines.append(f"│  {' | '.join(diag)}")

        # Footer
        lines.append(f"│ {sep} │")
        lines.append(f"└{'─' * 66}┘")
        lines.append("")

        return "\n".join(lines)

    def format_compact(self, analysis: TurnAnalysis) -> str:
        """One-line compact format."""
        bs = analysis.belief_state
        top = bs.top_worlds[:3] if bs.top_worlds else []
        top_str = " ".join(f"{w[1]:.0%}" for w in top)
        return (f"T{analysis.turn_number} | {bs.num_worlds}w "
                f"E={bs.entropy:.2f} | "
                f"top={top_str} | "
                f"MCTS={analysis.total_mcts_nodes}n "
                f"{analysis.mcts_time_s:.1f}s")

    def format_json(self, analysis: TurnAnalysis) -> str:
        """Format as a JSON string."""
        data = self._to_dict(analysis)
        return json.dumps(data, indent=2, default=str)

    # ------------------------------------------------------------------
    # Structured output
    # ------------------------------------------------------------------

    def as_report(self, analysis: TurnAnalysis) -> FormattedReport:
        """Return a structured report object."""
        return FormattedReport(
            display_text=self.format_turn(analysis),
            turn_number=analysis.turn_number,
            top_worlds=[
                {"world_id": w[0], "probability": w[1]}
                for w in analysis.belief_state.top_worlds
            ],
            top_actions=[
                {"description": desc, "score": 0.0}
                for desc in analysis.top_actions[:10]
            ],
            diagnostics={
                "num_worlds": analysis.belief_state.num_worlds,
                "entropy": analysis.belief_state.entropy,
                "match_quality": analysis.match_quality,
                "mcts_nodes": analysis.total_mcts_nodes,
                "mcts_time_s": round(analysis.mcts_time_s, 3),
                "worlds_pruned": analysis.worlds_pruned,
                "worlds_after_resample": analysis.worlds_after_resample,
                "elapsed_s": round(analysis.elapsed_s, 3),
            },
            machine_data=self._to_dict(analysis),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _bar(self, value: float, width: int = 20) -> str:
        """Simple text bar visualization."""
        filled = int(value * width)
        return "█" * filled + "░" * (width - filled)

    def _to_dict(self, analysis: TurnAnalysis) -> Dict[str, Any]:
        """Convert analysis to a plain dict for JSON serialization."""
        return {
            "turn": analysis.turn_number,
            "belief": {
                "num_worlds": analysis.belief_state.num_worlds,
                "entropy": analysis.belief_state.entropy,
                "top_worlds": [
                    {"id": w[0], "probability": w[1]}
                    for w in analysis.belief_state.top_worlds
                ],
                "dominant_world": analysis.belief_state.dominant_world_id,
            },
            "mcts": {
                "best_action": (
                    analysis.mcts_best_action.describe()
                    if analysis.mcts_best_action else None
                ),
                "num_nodes": analysis.total_mcts_nodes,
                "time_s": round(analysis.mcts_time_s, 3),
            },
            "matching": {
                "quality": analysis.match_quality,
                "results_count": len(analysis.last_match_results),
            },
            "diagnostics": {
                "worlds_pruned": analysis.worlds_pruned,
                "worlds_after_resample": analysis.worlds_after_resample,
                "elapsed_s": round(analysis.elapsed_s, 3),
            },
        }

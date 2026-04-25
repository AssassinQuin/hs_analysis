"""TurnPlan structures for explicit cross-turn planning output."""

from __future__ import annotations

from dataclasses import dataclass, field

from analysis.search.engine.models.probability_panel import ProbabilityPanel
from analysis.search.rhea import Action


@dataclass
class NextTurnOuts:
    clear_prob: float = 0.0
    heal_prob: float = 0.0
    board_prob: float = 0.0
    burst_prob: float = 0.0


@dataclass
class TurnPlan:
    objective: str
    primary_line: list[Action]
    backup_lines: list[list[Action]] = field(default_factory=list)
    reserve_resources: list[str] = field(default_factory=list)
    next_turn_outs: NextTurnOuts = field(default_factory=NextTurnOuts)
    probability_panel: ProbabilityPanel | None = None
    confidence: float = 0.0
    reasoning: str = ""

    def describe(self) -> str:
        lines = [f"目标: {self.objective} | 置信度: {self.confidence:.2f}"]
        lines.append("主线动作:")
        if self.primary_line:
            for i, act in enumerate(self.primary_line):
                lines.append(f"  {i + 1}. {act.action_type.name}")
        else:
            lines.append("  (无)")
        lines.append("抉择期望(命中率>=5%):")
        if self.probability_panel is not None:
            panel_lines = self.probability_panel.format_category_lines(min_prob=0.05)
            if panel_lines:
                for line in panel_lines:
                    lines.append(f"  {line}")
            else:
                lines.append("  (无显著分类概率)")
        else:
            lines.append(
                "  下回合概率: "
                f"解场={self.next_turn_outs.clear_prob:.2f}, "
                f"回血={self.next_turn_outs.heal_prob:.2f}, "
                f"战场={self.next_turn_outs.board_prob:.2f}, "
                f"直伤={self.next_turn_outs.burst_prob:.2f}"
            )
        if self.reasoning:
            lines.append(f"说明: {self.reasoning}")
        return "\n".join(lines)

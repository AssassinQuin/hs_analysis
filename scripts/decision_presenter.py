#!/usr/bin/env python3
"""decision_presenter.py — Format RHEA search results into readable Chinese recommendations.

Presents the evolutionary search output as a structured, human-friendly decision
report with confidence levels, alternative strategies, and step-by-step action
sequences in Chinese.

Usage:
    python3 scripts/decision_presenter.py          # run built-in demo
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Import sibling modules
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from rhea_engine import Action, SearchResult  # type: ignore[import]


# ===================================================================
# 1. DecisionPresenter
# ===================================================================

class DecisionPresenter:
    """Format RHEA search results into readable Chinese decision reports."""

    def __init__(self, card_names: Optional[Dict[int, str]] = None):
        """Initialize the presenter.

        Args:
            card_names: dict mapping dbfId → Chinese card name.
                        If None, attempts to load from hs_cards/unified_standard.json.
        """
        if card_names is not None:
            self.card_names: Dict[int, str] = card_names
        else:
            self.card_names = self._load_card_names()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format_result(self, result: SearchResult) -> str:
        """Format the RHEA search result into a readable Chinese report.

        Includes:
          - Header with timestamp
          - Main recommendation (best chromosome)
          - Alternative strategies (top 2)
          - Summary line

        Args:
            result: The SearchResult from RHEA engine.

        Returns:
            Formatted multi-line string report.
        """
        lines: List[str] = []

        # -- Header --
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines.append("=" * 40)
        lines.append(f"  RHEA 决策报告  {timestamp}")
        lines.append("=" * 40)

        # -- Main recommendation --
        confidence_label = self.get_confidence_label(result.confidence)
        diversity_tag = "高" if result.population_diversity > 0.5 else "低"

        lines.append("")
        lines.append("【推荐方案 #1】")
        lines.append(f"  期望收益(EV): {result.best_fitness:+.2f}")
        lines.append(f"  置信度: {confidence_label} ({result.confidence:.1%})")
        lines.append(f"  种群多样性: {diversity_tag} ({result.population_diversity:.4f})")
        lines.append(f"  搜索代数: {result.generations_run}  耗时: {result.time_elapsed:.2f} ms")
        lines.append("")
        lines.append("  动作序列:")

        for step, action in enumerate(result.best_chromosome, start=1):
            lines.append(f"    {self.format_action(action, step)}")

        # -- Alternative strategies --
        if result.alternatives:
            lines.append("")
            lines.append("【备选方案】")
            # Show top 2 alternatives at most
            for rank, (chromosome, fitness) in enumerate(result.alternatives[:2], start=2):
                action_desc = " → ".join(
                    self._brief_action(a) for a in chromosome
                )
                lines.append(f"  方案#{rank} (EV={fitness:+.2f}): {action_desc}")

        # -- Summary --
        lines.append("")
        lines.append("-" * 40)
        lines.append(f"  建议执行方案#1，置信度{confidence_label}")
        lines.append("-" * 40)

        return "\n".join(lines)

    def format_action(self, action: Action, step: int) -> str:
        """Format a single action for display.

        Args:
            action: The Action to format.
            step: The 1-based step number in the sequence.

        Returns:
            Formatted Chinese string describing the action.
        """
        atype = action.action_type

        if atype == "PLAY":
            card_name = self.get_card_name(action.card_index)
            return f"步骤{step}: 打出 {card_name} (费用:{action.data})"

        elif atype == "ATTACK":
            source_name = f"随从#{action.source_index}"
            target_name = "敌方英雄" if action.target_index == 0 else f"敌方随从#{action.target_index}"
            return f"步骤{step}: {source_name} 攻击 {target_name}"

        elif atype == "HERO_POWER":
            return f"步骤{step}: 使用英雄技能"

        elif atype == "END_TURN":
            return f"步骤{step}: 结束回合"

        return f"步骤{step}: 未知动作({atype})"

    def get_confidence_label(self, confidence: float) -> str:
        """Return a Chinese confidence label.

        Args:
            confidence: Confidence value between 0.0 and 1.0.

        Returns:
            "高" for >0.7, "中" for 0.4–0.7, "低" for <0.4.
        """
        if confidence > 0.7:
            return "高"
        elif confidence >= 0.4:
            return "中"
        else:
            return "低"

    def get_card_name(self, dbf_id: int) -> str:
        """Look up a card name by its dbfId.

        Args:
            dbf_id: The dbfId of the card.

        Returns:
            Chinese card name, or "未知卡牌" if not found.
        """
        return self.card_names.get(dbf_id, "未知卡牌")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _brief_action(self, action: Action) -> str:
        """Return a brief one-line description of an action (for alternatives)."""
        atype = action.action_type
        if atype == "PLAY":
            card_name = self.get_card_name(action.card_index)
            return f"打出{card_name}"
        elif atype == "ATTACK":
            source = f"随从#{action.source_index}"
            target = "英雄" if action.target_index == 0 else f"随从#{action.target_index}"
            return f"{source}→{target}"
        elif atype == "HERO_POWER":
            return "英雄技能"
        elif atype == "END_TURN":
            return "结束回合"
        return atype

    @staticmethod
    def _load_card_names() -> Dict[int, str]:
        """Load card names from hs_cards/unified_standard.json.

        Returns:
            Dict mapping dbfId → Chinese card name.
        """
        # Resolve path relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        json_path = os.path.join(project_root, "hs_cards", "unified_standard.json")

        if not os.path.exists(json_path):
            return {}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                cards = json.load(f)

            names: Dict[int, str] = {}
            for card in cards:
                dbf_id = card.get("dbfId")
                name = card.get("name", "")
                if dbf_id is not None and name:
                    names[dbf_id] = name
            return names
        except (json.JSONDecodeError, OSError):
            return {}


# ===================================================================
# 2. Standalone convenience function
# ===================================================================

def format_search_result(result: SearchResult, card_names: Optional[Dict[int, str]] = None) -> str:
    """Convenience function: create a presenter and format the result.

    Args:
        result: The SearchResult to format.
        card_names: Optional dict mapping dbfId → Chinese card name.

    Returns:
        Formatted Chinese report string.
    """
    presenter = DecisionPresenter(card_names=card_names)
    return presenter.format_result(result)


# ===================================================================
# 3. __main__ demo
# ===================================================================

if __name__ == "__main__":
    # Build mock SearchResult objects with different confidence levels
    demo_results: List[Tuple[SearchResult, str]] = []

    # --- High confidence scenario ---
    high_result = SearchResult(
        best_chromosome=[
            Action(action_type="PLAY", card_index=69623, data=0),      # 伺机待发
            Action(action_type="PLAY", card_index=69550, data=1),      # 激活
            Action(action_type="ATTACK", source_index=2, target_index=0),
            Action(action_type="END_TURN"),
        ],
        best_fitness=3.75,
        alternatives=[
            (
                [
                    Action(action_type="PLAY", card_index=69550, data=1),
                    Action(action_type="ATTACK", source_index=1, target_index=1),
                    Action(action_type="END_TURN"),
                ],
                2.10,
            ),
            (
                [
                    Action(action_type="HERO_POWER"),
                    Action(action_type="ATTACK", source_index=0, target_index=0),
                    Action(action_type="END_TURN"),
                ],
                1.50,
            ),
        ],
        generations_run=120,
        time_elapsed=45.3,
        population_diversity=0.62,
        confidence=0.85,
    )
    demo_results.append((high_result, "高置信度场景"))

    # --- Medium confidence scenario ---
    medium_result = SearchResult(
        best_chromosome=[
            Action(action_type="PLAY", card_index=130790, data=1),     # 女巫的学徒
            Action(action_type="ATTACK", source_index=0, target_index=1),
            Action(action_type="END_TURN"),
        ],
        best_fitness=1.20,
        alternatives=[
            (
                [
                    Action(action_type="PLAY", card_index=130790, data=1),
                    Action(action_type="END_TURN"),
                ],
                0.80,
            ),
        ],
        generations_run=80,
        time_elapsed=30.2,
        population_diversity=0.35,
        confidence=0.55,
    )
    demo_results.append((medium_result, "中置信度场景"))

    # --- Low confidence scenario ---
    low_result = SearchResult(
        best_chromosome=[
            Action(action_type="HERO_POWER"),
            Action(action_type="END_TURN"),
        ],
        best_fitness=0.30,
        alternatives=[],
        generations_run=50,
        time_elapsed=18.7,
        population_diversity=0.12,
        confidence=0.20,
    )
    demo_results.append((low_result, "低置信度场景"))

    # Display each demo
    for result, scenario_name in demo_results:
        print(f"\n{'#' * 50}")
        print(f"# 演示: {scenario_name}")
        print(f"{'#' * 50}")
        print(format_search_result(result))
        print()

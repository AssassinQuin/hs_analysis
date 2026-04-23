#!/usr/bin/env python3
"""result.py — SearchResult dataclass for the RHEA search engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from analysis.search.rhea.actions import Action


@dataclass
class SearchResult:
    """Result of an RHEA search."""

    best_chromosome: List[Action]
    best_fitness: float
    alternatives: List[Tuple[List[Action], float]]  # top 3 (chromosome, fitness)
    generations_run: int
    time_elapsed: float
    population_diversity: float  # std of fitnesses
    confidence: float  # gap between best and 2nd-best, normalised
    pareto_front: List[Tuple[List[Action], float]] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    def describe(self) -> str:
        """Return a formatted Chinese description of the search result."""
        lines = [
            "====== RHEA 搜索结果 ======",
            f"  运行代数  : {self.generations_run}",
            f"  耗时      : {self.time_elapsed:.2f} ms",
            f"  最佳适应度: {self.best_fitness:+.2f}",
            f"  种群多样性: {self.population_diversity:.4f}",
            f"  置信度    : {self.confidence:.4f}",
        ]
        if self.timings:
            lines.append("  --- 各阶段耗时 ---")
            for k, v in self.timings.items():
                lines.append(f"    {k}: {v:.1f}ms")
        lines.append("")
        lines.append("  --- 最佳动作序列 ---")
        for i, act in enumerate(self.best_chromosome):
            lines.append(f"    {i + 1}. {act.describe()}")
        if self.alternatives:
            lines.append("")
            lines.append("  --- 备选方案 ---")
            for rank, (chromo, fit) in enumerate(self.alternatives, 1):
                desc = " → ".join(a.describe() for a in chromo)
                lines.append(f"    方案{rank} (适应度={fit:+.2f}): {desc}")
        lines.append("=" * 30)
        return "\n".join(lines)

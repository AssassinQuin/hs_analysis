"""RNGModel — expected value of random effects via Monte Carlo sampling."""

from __future__ import annotations

import random
import re
from typing import Optional

from hs_analysis.search.game_state import GameState


class RNGModel:

    def expected_value(self, effect: str, state: GameState,
                       n_samples: int = 8) -> float:
        if not effect:
            return 0.0

        results = []
        for _ in range(n_samples):
            outcome = self._resolve_random(effect, state)
            results.append(outcome)
        return sum(results) / len(results) if results else 0.0

    def _resolve_random(self, effect: str, state: GameState) -> float:
        effect_lower = effect.lower()

        dmg_match = re.search(r'damage.*?(\d+)\s*[-~]\s*(\d+)', effect_lower)
        if not dmg_match:
            dmg_match = re.search(r'damage.*?(\d+)\s*[到至]\s*(\d+)', effect_lower)
        if dmg_match:
            lo, hi = int(dmg_match.group(1)), int(dmg_match.group(2))
            return random.randint(lo, hi)

        dmg_single = re.search(r'damage.*?(\d+)', effect_lower)
        if dmg_single:
            return float(dmg_single.group(1))

        heal_match = re.search(r'heal|restore.*?(\d+)', effect_lower)
        if not heal_match:
            heal_match = re.search(r'恢复.*?(\d+)', effect_lower)
        if heal_match:
            return float(heal_match.group(1)) * 0.8

        summon_match = re.search(r'summon.*?(\d+)/(\d+)', effect_lower)
        if summon_match:
            atk, hp = int(summon_match.group(1)), int(summon_match.group(2))
            return (atk + hp) * 0.3

        buff_atk = re.search(r'\+(\d+)\s*attack', effect_lower)
        if not buff_atk:
            buff_atk = re.search(r'\+(\d+)\s*攻击力', effect_lower)
        if buff_atk:
            return float(buff_atk.group(1)) * 0.4

        draw_match = re.search(r'draw.*?(\d+)', effect_lower)
        if not draw_match:
            draw_match = re.search(r'抽.*?(\d+)', effect_lower)
        if draw_match:
            n = int(draw_match.group(1))
            return n * 0.5

        random_targets = ["随机", "random"]
        if any(t in effect_lower for t in random_targets):
            return 1.0

        return 0.5

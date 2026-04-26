"""RNGModel — expected value of random effects via Monte Carlo sampling."""

from __future__ import annotations

import random
import re
from typing import Optional

from analysis.data.card_effects import (
    _DAMAGE_CN, _DAMAGE_EN, _HEAL_CN, _HEAL_EN,
    _DRAW_CN, _DRAW_EN, _BUFF_ATK_CN, _BUFF_ATK_EN,
    _SUMMON_STATS_CN, _SUMMON_STATS_EN,
)
from analysis.search.game_state import GameState


class RNGModel:

    _DMG_RANGE_EN = re.compile(r'(\d+)\s*(?:to|-)\s*(\d+)\s*damage', re.IGNORECASE)
    _DMG_RANGE_CN = re.compile(r'(\d+)\s*[到至]\s*(\d+)\s*点?伤害')
    _DMG_RANGE_FALLBACK = re.compile(r'damage.*?(\d+)\s*[-~]\s*(\d+)', re.IGNORECASE)
    _DMG_SIMPLE = re.compile(r'damage.*?(\d+)', re.IGNORECASE)

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

        # EN-first: "3 to 5 damage" or "3-5 damage"
        dmg_match = self._DMG_RANGE_EN.search(effect_lower)
        # CN fallback: "3到5点伤害" or "3至5伤害"
        if not dmg_match:
            dmg_match = self._DMG_RANGE_CN.search(effect)
        # Generic fallback: "damage 3-5"
        if not dmg_match:
            dmg_match = self._DMG_RANGE_FALLBACK.search(effect_lower)
        if dmg_match:
            lo, hi = int(dmg_match.group(1)), int(dmg_match.group(2))
            return random.randint(lo, hi)

        m = _DAMAGE_EN.search(effect) or _DAMAGE_CN.search(effect)
        if m:
            return float(m.group(1))

        m = self._DMG_SIMPLE.search(effect_lower)
        if m:
            return float(m.group(1))

        m = _HEAL_EN.search(effect) or _HEAL_CN.search(effect)
        if m:
            return float(m.group(1)) * 0.8

        m = _SUMMON_STATS_EN.search(effect) or _SUMMON_STATS_CN.search(effect)
        if m:
            atk, hp = int(m.group(1)), int(m.group(2))
            return (atk + hp) * 0.3

        m = _BUFF_ATK_EN.search(effect) or _BUFF_ATK_CN.search(effect)
        if m:
            return float(m.group(1)) * 0.4

        m = _DRAW_EN.search(effect) or _DRAW_CN.search(effect)
        if m:
            n = int(m.group(1))
            return n * 0.5

        random_targets = ["随机", "random"]
        if any(t in effect_lower for t in random_targets):
            return 1.0

        return 0.5

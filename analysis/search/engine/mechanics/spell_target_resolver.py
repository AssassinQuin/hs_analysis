from __future__ import annotations

import re
from typing import List

from analysis.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, _AOE_CN, _AOE_EN
from analysis.search.game_state import GameState
from analysis.models.card import Card


class SpellTargetResolver:
    _ENEMY_MINION_PATTERNS = [
        re.compile(r"enemy\s+minion", re.IGNORECASE),
        re.compile(r"敌方随从"),
    ]
    _FRIENDLY_MINION_PATTERNS = [
        re.compile(r"friendly\s+minion", re.IGNORECASE),
        re.compile(r"友方随从"),
    ]
    _ANY_MINION_PATTERNS = [
        re.compile(r"(?:a|an|one)\s+minion", re.IGNORECASE),
        re.compile(r"一个?随从"),
    ]
    _ENEMY_HERO_PATTERNS = [
        re.compile(r"enemy\s+hero", re.IGNORECASE),
        re.compile(r"敌方英雄"),
    ]
    _ALL_ENEMY_PATTERNS = [
        re.compile(r"all\s+enemies", re.IGNORECASE),
        re.compile(r"所有敌人"),
        re.compile(r"对所有(?:敌方)?(?:随从|角色)"),
    ]
    _ALL_MINION_PATTERNS = [
        re.compile(r"all\s+minion", re.IGNORECASE),
        re.compile(r"所有随从"),
    ]
    _HERO_PATTERNS = [
        re.compile(r"the\s+enemy\s+hero", re.IGNORECASE),
        re.compile(r"(?:对|造成).*?英雄"),
    ]

    def resolve_targets(self, state: GameState, card: Card) -> List[int]:
        text = getattr(card, "text", "") or ""
        if not text:
            return []

        card_type = getattr(card, "card_type", "").upper()

        if self._is_aoe(text):
            return []

        if self._is_no_target(text):
            return []

        targets: List[int] = []

        if self._matches_enemy_minion(text):
            for i in range(len(state.opponent.board)):
                targets.append(i + 1)
            if not targets:
                return []
            return targets

        if self._matches_friendly_minion(text):
            for i in range(len(state.board)):
                targets.append(-(i + 1))
            return targets

        if self._matches_any_minion(text):
            for i in range(len(state.opponent.board)):
                targets.append(i + 1)
            for i in range(len(state.board)):
                targets.append(-(i + 1))
            if not targets:
                return []
            return targets

        if self._matches_enemy_hero(text):
            targets.append(0)
            for i in range(len(state.opponent.board)):
                targets.append(i + 1)
            return targets

        if card_type == "SPELL" and self._has_damage(text):
            targets.append(0)
            for i in range(len(state.opponent.board)):
                targets.append(i + 1)
            return targets

        return []

    def _is_aoe(self, text: str) -> bool:
        for p in self._ALL_ENEMY_PATTERNS + self._ALL_MINION_PATTERNS:
            if p.search(text):
                return True
        if _AOE_EN.search(text) or _AOE_CN.search(text):
            return True
        if re.search(r"对所有.*?造成", text):
            return True
        return False

    def _is_no_target(self, text: str) -> bool:
        no_target_keywords = [
            "draw",
            "抽牌",
            "summon",
            "召唤",
            "discover",
            "发现",
            "armor",
            "护甲",
            "heal.*?hero",
            "恢复.*?英雄",
            "secret",
            "奥秘",
            "quest",
            "任务",
            "shuffle",
            "洗入",
            "discard",
            "弃牌",
            "cost",
            "法力值",
            "mana",
            "freeze\s+all",
            "give",
            "获得",
            "buff",
            "增益",
        ]
        tl = text.lower()
        for kw in no_target_keywords:
            if re.search(kw, tl):
                return True
        return False

    def _matches_enemy_minion(self, text: str) -> bool:
        return any(p.search(text) for p in self._ENEMY_MINION_PATTERNS)

    def _matches_friendly_minion(self, text: str) -> bool:
        return any(p.search(text) for p in self._FRIENDLY_MINION_PATTERNS)

    def _matches_any_minion(self, text: str) -> bool:
        return any(p.search(text) for p in self._ANY_MINION_PATTERNS)

    def _matches_enemy_hero(self, text: str) -> bool:
        return any(p.search(text) for p in self._HERO_PATTERNS)

    def _has_damage(self, text: str) -> bool:
        return bool(_DAMAGE_EN.search(text) or _DAMAGE_CN.search(text))

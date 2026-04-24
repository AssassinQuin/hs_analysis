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

    # ── Target condition patterns (restrict WHO can be targeted) ──
    _DAMAGED_CONDITION = [
        re.compile(r"受伤(?:的)?(?:随从|角色|友方)"),
        re.compile(r"damaged\s+(?:minion|character|friendly)", re.IGNORECASE),
    ]
    _DAMAGED_MINION_ONLY = [
        re.compile(r"受伤(?:的)?随从"),
        re.compile(r"damaged\s+minion", re.IGNORECASE),
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

        # Detect target condition restrictions
        damaged_only = self._is_damaged_condition(text)
        minion_only = self._is_minion_only_target(text)

        targets: List[int] = []

        if self._matches_enemy_minion(text):
            for i, m in enumerate(state.opponent.board):
                if damaged_only and not self._is_minion_damaged(m):
                    continue
                targets.append(i + 1)
            if not targets:
                return []
            return targets

        if self._matches_friendly_minion(text):
            for i, m in enumerate(state.board):
                if damaged_only and not self._is_minion_damaged(m):
                    continue
                targets.append(-(i + 1))
            return targets

        if self._matches_any_minion(text):
            for i, m in enumerate(state.opponent.board):
                if damaged_only and not self._is_minion_damaged(m):
                    continue
                targets.append(i + 1)
            for i, m in enumerate(state.board):
                if damaged_only and not self._is_minion_damaged(m):
                    continue
                targets.append(-(i + 1))
            if not targets:
                return []
            return targets

        if self._matches_enemy_hero(text):
            if not damaged_only:  # 英雄不受"受伤"条件限制（除非文本明确排除英雄）
                targets.append(0)
            for i, m in enumerate(state.opponent.board):
                if damaged_only and not self._is_minion_damaged(m):
                    continue
                targets.append(i + 1)
            return targets

        # Default: SPELL with damage text
        if card_type == "SPELL" and self._has_damage(text):
            # "受伤的随从" — minion-only, damaged only
            if damaged_only and minion_only:
                for i, m in enumerate(state.opponent.board):
                    if self._is_minion_damaged(m):
                        targets.append(i + 1)
                for i, m in enumerate(state.board):
                    if self._is_minion_damaged(m):
                        targets.append(-(i + 1))
                return targets
            # "受伤的角色" — any damaged character (hero + minions)
            if damaged_only:
                if state.hero.hp < 30:
                    targets.append(0)
                for i, m in enumerate(state.opponent.board):
                    if self._is_minion_damaged(m):
                        targets.append(i + 1)
                return targets
            # Normal damage spell: enemy hero + all enemy minions
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

    def _is_damaged_condition(self, text: str) -> bool:
        """Check if card text requires target to be damaged (受伤)."""
        return any(p.search(text) for p in self._DAMAGED_CONDITION)

    def _is_minion_only_target(self, text: str) -> bool:
        """Check if card text restricts target to minions only (随从, not 英雄)."""
        return any(p.search(text) for p in self._DAMAGED_MINION_ONLY)

    @staticmethod
    def _is_minion_damaged(minion) -> bool:
        """Check if a minion has taken damage (health < max_health)."""
        max_hp = getattr(minion, 'max_health', getattr(minion, 'health', 0))
        cur_hp = getattr(minion, 'health', 0)
        return cur_hp < max_hp

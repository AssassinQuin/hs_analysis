"""Spell/minion/location target resolution from card text.

Resolves legal targets for spells, minions, and locations based on card text
parsing and current game state.

Target encoding: 0=enemy hero, 1..N=enemy minion, -1..-M=friendly minion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional

try:
    from analysis.card.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, _AOE_CN, _AOE_EN
except ImportError:
    _DAMAGE_EN = re.compile(r"[Dd]eal\s+(\d+)\s*damage")
    _DAMAGE_CN = re.compile(r"造成\s*(\d+)\s*点伤害")
    _AOE_EN = re.compile(r"[Aa]ll")
    _AOE_CN = re.compile(r"(?:所有|全部)")

from analysis.card.engine.state import GameState, Minion


# ── Enums ──────────────────────────────────────────────────────────


class TargetSide(Enum):
    ENEMY = auto()
    FRIENDLY = auto()
    ANY = auto()


class TargetEntityType(Enum):
    CHARACTER = auto()
    MINION = auto()
    HERO = auto()
    WEAPON = auto()
    LOCATION = auto()


# ── Condition predicates ───────────────────────────────────────────


def _is_damaged(minion: Minion) -> bool:
    return minion.health < minion.max_health


def _is_undamaged(minion: Minion) -> bool:
    return minion.health >= minion.max_health


def _is_frozen(minion: Minion) -> bool:
    return minion.frozen_until_next_turn


def _has_taunt(minion: Minion) -> bool:
    return minion.has_taunt


def _has_stealth(minion: Minion) -> bool:
    return minion.has_stealth


def _is_race(race: str) -> Callable[[Minion], bool]:
    race_lower = race.lower()

    def check(m: Minion) -> bool:
        m_race = getattr(m, "race", "") or ""
        if m_race.lower() == race_lower:
            return True
        card_ref = getattr(m, "card_ref", None)
        if card_ref:
            cr_race = getattr(card_ref, "race", "") or ""
            if cr_race.lower() == race_lower:
                return True
        races = getattr(m, "races", []) or []
        if any(r.lower() == race_lower for r in races):
            return True
        return False

    return check


def _attack_leq(threshold: int) -> Callable[[Minion], bool]:
    return lambda m: m.attack <= threshold


def _attack_geq(threshold: int) -> Callable[[Minion], bool]:
    return lambda m: m.attack >= threshold


def _cost_geq(threshold: int) -> Callable[[Minion], bool]:
    return lambda m: m.cost >= threshold


def _health_leq(threshold: int) -> Callable[[Minion], bool]:
    return lambda m: m.health <= threshold


def _has_race_tag(minion: Minion) -> bool:
    race = getattr(minion, "race", "") or ""
    return bool(race) and race.upper() not in ("", "NONE", "ALL")


def _is_location(minion: Minion) -> bool:
    card_ref = getattr(minion, "card_ref", None)
    if card_ref:
        return getattr(card_ref, "card_type", "").upper() == "LOCATION"
    return False


class _SelfHPThreshold:
    def __init__(self, source_health: int):
        self.threshold = source_health

    def __call__(self, minion: Minion) -> bool:
        return minion.health <= self.threshold


# ── TargetSpec ─────────────────────────────────────────────────────


@dataclass
class TargetSpec:
    side: TargetSide = TargetSide.ENEMY
    entity_type: TargetEntityType = TargetEntityType.CHARACTER
    conditions: List[Callable[[Minion], bool]] = field(default_factory=list)
    is_aoe: bool = False
    needs_target: bool = True


# ── Regex patterns for text parsing ────────────────────────────────

_SIDE_ENEMY_MINION = [
    re.compile(r"enemy\s+minion", re.IGNORECASE),
]
_SIDE_FRIENDLY_MINION = [
    re.compile(r"friendly\s+minion", re.IGNORECASE),
]
_SIDE_ANY_MINION = [
    re.compile(r"(?:a|an|one)\s+minion", re.IGNORECASE),
]
_SIDE_ENEMY_HERO = [
    re.compile(r"enemy\s+hero", re.IGNORECASE),
]
_SIDE_FRIENDLY_CHARACTER = [
    re.compile(r"friendly\s+character", re.IGNORECASE),
]
_SIDE_ENEMY_CHARACTER = [
    re.compile(r"enemy\s+character", re.IGNORECASE),
]
_SIDE_ANY_CHARACTER = [
    re.compile(r"(?:any|a)\s+character", re.IGNORECASE),
]
_SIDE_ENEMY_LOCATION = [
    re.compile(r"enemy\s+location", re.IGNORECASE),
]

_AOE_PATTERNS = [
    re.compile(r"all\s+enemies", re.IGNORECASE),
    re.compile(r"all\s+minion", re.IGNORECASE),
]

_COND_DAMAGED = [
    re.compile(r"(?<!un)damaged\s+(?:minion|character)", re.IGNORECASE),
]
_COND_UNDAMAGED = [
    re.compile(r"undamaged|full.health", re.IGNORECASE),
]
_COND_FROZEN = [
    re.compile(r"frozen\s+(?:minion|character)", re.IGNORECASE),
]
_COND_TAUNT = [
    re.compile(r"(?:minion|character)\s+with\s+taunt", re.IGNORECASE),
]
_COND_RACE_EN = re.compile(
    r"friendly\s+(Dragon|Undead|Beast|Demon|Mechanical"
    r"|Elemental|Murloc|Pirate|Totem|Elf|Treant)",
    re.IGNORECASE,
)

_COND_ATK_LE_EN = re.compile(
    r"(?:attack|attack.*?)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE
)
_COND_ATK_GE_EN = re.compile(
    r"(?:attack|attack.*?)(?:more|at least|≥)\s*(\d+)", re.IGNORECASE
)
_COND_COST_GE_EN = re.compile(
    r"costs?\s*(?:at least|≥|more)\s*(\d+)", re.IGNORECASE
)
_COND_HP_LE_EN = re.compile(
    r"(?:health|hp)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE
)

_COND_ENEMY_LOCATION = [
    re.compile(r"enemy\s+location", re.IGNORECASE),
]

_COND_HAS_RACE_TAG = [
    re.compile(r"minion\s+with\s+a\s+race\s+tag", re.IGNORECASE),
]

_COND_LEGENDARY = [
    re.compile(r"legendary\s+(?:minion|character)", re.IGNORECASE),
]

_NO_TARGET_KEYWORDS = [
    "draw",
    "summon",
    "discover",
    "armor",
    r"heal.*?hero",
    "secret",
    "quest",
    "shuffle",
    "discard",
    r"freeze\s+all",
]

_TARGETING_KEYWORDS = [
    "enemy",
    "friendly",
    r"a\s+minion",
    r"an?\s+minion",
    r"a\s+character",
    r"an?\s+character",
    r"enemy\s+hero",
    r"friendly\s+hero",
    # Chinese targeting keywords
    "敌方",
    "敌方随从",
    "敌方英雄",
    "友方",
    "友方随从",
    "友方角色",
    "一个随从",
    "一个角色",
]


# ── Utility ────────────────────────────────────────────────────────


def _any_match(patterns: list, text: str) -> bool:
    return any(p.search(text) for p in patterns)


# ── Resolver class ────────────────────────────────────────────────


class SpellTargetResolver:
    """Resolve legal spell/minion/location targets from card text and game state.

    Flow: parse card text -> TargetSpec -> generate target indices from GameState.
    """

    def resolve_targets(self, state: GameState, card) -> List[int]:
        text = getattr(card, "text", "") or ""
        if not text:
            return []

        card_type = getattr(card, "card_type", "").upper()

        spec = self._parse_spec(text, card_type)
        if spec is None:
            return []
        if spec.is_aoe or not spec.needs_target:
            return []

        return self._generate_targets(state, spec)

    # ── Spec parsing ─────────────────────────────────────

    def _parse_spec(self, text: str, card_type: str) -> Optional[TargetSpec]:
        spec = TargetSpec()

        if self._is_aoe(text):
            spec.is_aoe = True
            return spec

        target_clause = self._extract_target_clause(text)

        has_damage = bool(_DAMAGE_EN.search(target_clause))
        if not has_damage:
            has_damage = bool(_DAMAGE_CN.search(target_clause))
        has_targeting_keyword = any(
            re.search(kw, target_clause, re.IGNORECASE)
            for kw in _TARGETING_KEYWORDS
        )

        if not has_damage and not has_targeting_keyword and self._is_no_target(text):
            spec.needs_target = False
            return spec

        if not has_damage and not has_targeting_keyword:
            spec.needs_target = False
            return spec

        conditions = self._parse_conditions(target_clause)
        spec.conditions = conditions

        side, etype = self._parse_side_and_type(
            target_clause, card_type, has_damage
        )
        spec.side = side
        spec.entity_type = etype

        return spec

    @staticmethod
    def _extract_target_clause(text: str) -> str:
        clause = text.split("。")[0].split("；")[0].split(";")[0]
        for sep in ["。", "，"]:
            if sep in clause:
                clause = clause.split(sep)[0]
        return clause.strip()

    def _parse_side_and_type(
        self, text: str, card_type: str, has_damage: bool
    ) -> tuple[TargetSide, TargetEntityType]:
        if _any_match(_SIDE_ENEMY_MINION, text):
            return TargetSide.ENEMY, TargetEntityType.MINION

        if _any_match(_SIDE_ENEMY_LOCATION, text):
            return TargetSide.ENEMY, TargetEntityType.LOCATION

        if _any_match(_SIDE_FRIENDLY_MINION, text):
            return TargetSide.FRIENDLY, TargetEntityType.MINION

        if _any_match(_SIDE_ENEMY_CHARACTER, text):
            return TargetSide.ENEMY, TargetEntityType.CHARACTER

        if _any_match(_SIDE_FRIENDLY_CHARACTER, text):
            return TargetSide.FRIENDLY, TargetEntityType.CHARACTER

        if _any_match(_SIDE_ANY_CHARACTER, text):
            return TargetSide.ANY, TargetEntityType.CHARACTER

        if _any_match(_SIDE_ANY_MINION, text):
            return TargetSide.ANY, TargetEntityType.MINION

        if _any_match(_SIDE_ENEMY_HERO, text):
            return TargetSide.ENEMY, TargetEntityType.CHARACTER

        if re.search(r"your\s+weapon", text, re.IGNORECASE):
            return TargetSide.FRIENDLY, TargetEntityType.WEAPON

        m = _COND_RACE_EN.search(text)
        if m:
            return TargetSide.FRIENDLY, TargetEntityType.MINION

        if card_type == "SPELL" and has_damage:
            return TargetSide.ENEMY, TargetEntityType.CHARACTER

        if card_type == "LOCATION" and has_damage:
            return TargetSide.ANY, TargetEntityType.MINION

        if card_type == "MINION" and has_damage:
            return TargetSide.ANY, TargetEntityType.CHARACTER

        return TargetSide.ENEMY, TargetEntityType.CHARACTER

    def _parse_conditions(self, text: str) -> List[Callable[[Minion], bool]]:
        conditions: List[Callable[[Minion], bool]] = []

        if _any_match(_COND_DAMAGED, text):
            conditions.append(_is_damaged)

        if _any_match(_COND_UNDAMAGED, text):
            conditions.append(_is_undamaged)

        if _any_match(_COND_FROZEN, text):
            conditions.append(_is_frozen)

        if _any_match(_COND_TAUNT, text):
            conditions.append(_has_taunt)

        m = _COND_ATK_LE_EN.search(text)
        if m:
            conditions.append(_attack_leq(int(m.group(1))))

        m = _COND_ATK_GE_EN.search(text)
        if m:
            conditions.append(_attack_geq(int(m.group(1))))

        m = _COND_COST_GE_EN.search(text)
        if m:
            conditions.append(_cost_geq(int(m.group(1))))

        if _any_match(_COND_LEGENDARY, text):
            conditions.append(self._is_legendary)

        if _any_match(_COND_ENEMY_LOCATION, text):
            conditions.append(_is_location)

        if _any_match(_COND_HAS_RACE_TAG, text):
            conditions.append(_has_race_tag)

        m = _COND_HP_LE_EN.search(text)
        if m:
            conditions.append(_health_leq(int(m.group(1))))

        m = _COND_RACE_EN.search(text)
        if m:
            race_en = m.group(1).upper()
            conditions.append(_is_race(race_en))

        return conditions

    # ── Target generation ────────────────────────────────

    def _generate_targets(
        self, state: GameState, spec: TargetSpec
    ) -> List[int]:
        targets: List[int] = []

        def _minion_passes(m: Minion) -> bool:
            return all(cond(m) for cond in spec.conditions)

        if spec.entity_type == TargetEntityType.WEAPON:
            if state.hero.weapon is not None:
                targets.append(-99)
            return targets

        if spec.entity_type == TargetEntityType.LOCATION:
            if spec.side in (TargetSide.ENEMY, TargetSide.ANY):
                for i, m in enumerate(state.opponent.board):
                    if _is_location(m) and _minion_passes(m):
                        targets.append(i + 1)
            if spec.side in (TargetSide.FRIENDLY, TargetSide.ANY):
                for i, m in enumerate(state.board):
                    if _is_location(m) and _minion_passes(m):
                        targets.append(-(i + 1))
            return targets

        include_enemy_hero = spec.entity_type == TargetEntityType.CHARACTER
        include_friendly_hero = (
            spec.entity_type == TargetEntityType.CHARACTER
            and spec.side in (TargetSide.FRIENDLY, TargetSide.ANY)
        )

        if spec.side in (TargetSide.ENEMY, TargetSide.ANY):
            if include_enemy_hero:
                hero_ok = True
                opp_hero_hp = (
                    state.opponent.hero.hp
                    if hasattr(state, "opponent")
                    else 30
                )
                if spec.conditions:
                    for cond in spec.conditions:
                        if cond is _is_damaged:
                            if opp_hero_hp >= 30:
                                hero_ok = False
                        elif cond is _is_undamaged:
                            if opp_hero_hp < 30:
                                hero_ok = False
                        else:
                            hero_ok = False
                            break
                if hero_ok:
                    targets.append(0)

            for i, m in enumerate(state.opponent.board):
                if _minion_passes(m):
                    targets.append(i + 1)

        if spec.side in (TargetSide.FRIENDLY, TargetSide.ANY):
            for i, m in enumerate(state.board):
                if _minion_passes(m):
                    targets.append(-(i + 1))

        return targets

    # ── Helper methods ───────────────────────────────────

    @staticmethod
    def _is_legendary(minion: Minion) -> bool:
        card_ref = getattr(minion, "card_ref", None)
        if card_ref and getattr(card_ref, "rarity", "") == "LEGENDARY":
            return True
        card_id = getattr(minion, "card_id", "")
        if card_id:
            try:
                from analysis.card.data.card_data import get_db

                db = get_db()
                card_data = db.get_card(card_id)
                if card_data and card_data.get("rarity") == "LEGENDARY":
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _is_aoe(text: str) -> bool:
        for p in _AOE_PATTERNS:
            if p.search(text):
                return True
        if _AOE_EN.search(text):
            return True
        if _AOE_CN.search(text):
            return True
        if re.search(r"all.*?damage", text, re.IGNORECASE):
            return True
        return False

    @staticmethod
    def has_targeting_keyword(text: str) -> bool:
        return any(
            re.search(kw, text, re.IGNORECASE) for kw in _TARGETING_KEYWORDS
        )

    @staticmethod
    def _is_no_target(text: str) -> bool:
        if SpellTargetResolver.has_targeting_keyword(text):
            return False
        tl = text.lower()
        return any(re.search(kw, tl) for kw in _NO_TARGET_KEYWORDS)

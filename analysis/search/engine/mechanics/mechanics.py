"""Mechanics handlers for the search engine.

HeroCardHandler: applies hero card state transitions.
SpellTargetResolver: resolves legal spell/minion/location targets from card text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional

try:
    from analysis.card.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, _AOE_CN, _AOE_EN, get_card_armor
except ImportError:
    _DAMAGE_CN = _DAMAGE_EN = _AOE_CN = _AOE_EN = None
    _DAMAGE_CN = re.compile(r'造成\s*(\d+)\s*点?伤害')
    _DAMAGE_EN = re.compile(r'[Dd]eal\s+(\d+)\s*damage')
    _AOE_CN = re.compile(r'所有|全部')
    _AOE_EN = re.compile(r'[Aa]ll')

    def get_card_armor(card) -> int:
        text = getattr(card, 'text', '') or ''
        en = getattr(card, 'english_text', '') or ''
        m = re.search(r'(\d+)\s*(?:点)?(?:护甲|Armor)', text) or \
            re.search(r'(\d+)\s*(?:点)?(?:护甲|Armor)', en)
        if m:
            return int(m.group(1))
        return 0

from analysis.card.engine.state import GameState, HeroState, Minion
from analysis.card.models.card import Card


# ===================================================================
# HeroCardHandler
# ===================================================================

class HeroCardHandler:
    def apply_hero_card(self, state: GameState, card: Card) -> GameState:
        s = state

        armor = self._parse_armor(card)
        s.hero.armor += armor

        hero_class = getattr(card, "card_class", "") or ""
        if hero_class:
            s.hero.hero_class = hero_class

        s.hero.hero_power_used = False
        s.hero.is_hero_card = True
        s.hero.imbue_level = 0

        self._update_hero_power(s, card)

        self._apply_hero_card_effects(s, card)

        return s

    def _parse_armor(self, card: Card) -> int:
        armor = get_card_armor(card)
        return armor if armor > 0 else 5

    def _update_hero_power(self, state: GameState, card: Card) -> None:
        text = getattr(card, "text", "") or ""

        m = _DAMAGE_CN.search(text) or _DAMAGE_EN.search(text)
        if m:
            state.hero.hero_power_damage = int(m.group(1))

        if "hero_power_cost" in text.lower() or "技能消耗" in text:
            cost_match = re.search(r"(?:cost|消耗)\s*(\d+)", text)
            if cost_match:
                state.hero.hero_power_cost = int(cost_match.group(1))

    def _apply_hero_card_effects(self, state: GameState, card: Card) -> None:
        text = getattr(card, "text", "") or ""

        if "Battlecry" in text or "战吼" in text:
            try:
                from analysis.card.abilities.loader import load_abilities
                from analysis.card.engine.target import orchestrate

                abilities = load_abilities(card.card_id) if card.card_id else []
                state = orchestrate(state, card, abilities, {'source_minion': None})
            except Exception:
                pass

        try:
            from analysis.card.abilities.loader import load_abilities
            from analysis.card.engine.target import orchestrate

            card_copy_id = getattr(card_copy, 'card_id', '')
            abilities = load_abilities(card_copy_id) if card_copy_id else []
            state = orchestrate(state, card_copy, abilities, {'source_minion': None})
        except Exception:
            pass


# ===================================================================
# SpellTargetResolver — data-driven target resolution for all card types
# ===================================================================

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
        m_race = getattr(m, 'race', '') or ''
        if m_race.lower() == race_lower:
            return True
        card_ref = getattr(m, 'card_ref', None)
        if card_ref:
            cr_race = getattr(card_ref, 'race', '') or ''
            if cr_race.lower() == race_lower:
                return True
        races = getattr(m, 'races', []) or []
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
    race = getattr(minion, 'race', '') or ''
    return race != '' and race.upper() not in ('', 'NONE', 'ALL')


def _is_location(minion: Minion) -> bool:
    card_ref = getattr(minion, 'card_ref', None)
    if card_ref:
        return getattr(card_ref, 'card_type', '').upper() == 'LOCATION'
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

# Side patterns
_SIDE_ENEMY_MINION = [
    re.compile(r"enemy\s+minion", re.IGNORECASE),
    re.compile(r"敌方随从"),
]
_SIDE_FRIENDLY_MINION = [
    re.compile(r"friendly\s+minion", re.IGNORECASE),
    re.compile(r"友方随从"),
]
_SIDE_ANY_MINION = [
    re.compile(r"(?:a|an|one)\s+minion", re.IGNORECASE),
    re.compile(r"一个.{0,20}?随从"),
]
_SIDE_ENEMY_HERO = [
    re.compile(r"enemy\s+hero", re.IGNORECASE),
    re.compile(r"敌方英雄"),
]
_SIDE_FRIENDLY_CHARACTER = [
    re.compile(r"friendly\s+character", re.IGNORECASE),
    re.compile(r"友方角色"),
]
_SIDE_ENEMY_CHARACTER = [
    re.compile(r"enemy\s+character", re.IGNORECASE),
    re.compile(r"敌方角色"),
]
_SIDE_ANY_CHARACTER = [
    re.compile(r"(?:any|a)\s+character", re.IGNORECASE),
    re.compile(r"一个?角色"),
]
_SIDE_ENEMY_LOCATION = [
    re.compile(r"敌方地标"),
    re.compile(r"enemy\s+location", re.IGNORECASE),
]

# AOE patterns
_AOE_PATTERNS = [
    re.compile(r"all\s+enemies", re.IGNORECASE),
    re.compile(r"所有敌人"),
    re.compile(r"对所有(?:敌方)?(?:随从|角色)"),
    re.compile(r"all\s+minion", re.IGNORECASE),
    re.compile(r"所有随从"),
]

# Condition patterns
_COND_DAMAGED = [
    re.compile(r"(?<!未)受伤(?:的)?(?:随从|角色|友方)"),
    re.compile(r"(?<!un)damaged\s+(?:minion|character)", re.IGNORECASE),
]
_COND_DAMAGED_MINION_ONLY = [
    re.compile(r"受伤(?:的)?随从"),
    re.compile(r"damaged\s+minion", re.IGNORECASE),
]
_COND_UNDAMAGED = [
    re.compile(r"未受伤(?:的)?(?:随从|角色)"),
    re.compile(r"undamaged|full.health", re.IGNORECASE),
]
_COND_FROZEN = [
    re.compile(r"被冰冻(?:的)?(?:随从|角色)"),
    re.compile(r"frozen\s+(?:minion|character)", re.IGNORECASE),
]
_COND_TAUNT = [
    re.compile(r"嘲讽"),
    re.compile(r"(?:minion|character)\s+with\s+taunt", re.IGNORECASE),
]
_COND_RACE_CN = re.compile(r"友方(龙|亡灵|野兽|恶魔|机械|元素|鱼人|海盗|图腾|精灵|树人)")
_COND_RACE_EN = re.compile(r"friendly\s+(Dragon|Undead|Beast|Demon|Mechanical|Elemental|Murloc|Pirate|Totem|Elf|Treant)", re.IGNORECASE)

from analysis.card.constants.hs_enums import RACE_ZH_MAP

_RACE_MAP_CN_EN = dict(RACE_ZH_MAP)
_RACE_MAP_CN_EN.update({
    "精灵": "ELF",
    "树人": "TREANT",
})

_COND_ATK_LE = re.compile(r"攻击力(?:小于等于?|≤|不超过)(\d+)")
_COND_ATK_LE_EN = re.compile(r"(?:attack|attack.*?)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE)
_COND_ATK_GE = re.compile(r"攻击力(?:大于(?:或)?等于?|≥|不小于|至少)(\d+)")
_COND_ATK_GE_EN = re.compile(r"(?:attack|attack.*?)(?:more|at least|≥)\s*(\d+)", re.IGNORECASE)
_COND_COST_GE = re.compile(r"法力值消耗(?:大于等于?|≥|不小于|至少)(\d+)")
_COND_COST_GE_EN = re.compile(r"costs?\s*(?:at least|≥|more)\s*(\d+)", re.IGNORECASE)
_COND_HP_LE = re.compile(r"(?:生命值|血量)(?:小于等于?|≤|不超过)(\d+)")
_COND_HP_LE_EN = re.compile(r"(?:health|hp)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE)

_COND_ENEMY_LOCATION = [
    re.compile(r"敌方地标"),
    re.compile(r"enemy\s+location", re.IGNORECASE),
]

_COND_HAS_RACE_TAG = [
    re.compile(r"有种族标签(?:的)?(?:敌方)?(?:随从|角色)"),
    re.compile(r"minion\s+with\s+a\s+race\s+tag", re.IGNORECASE),
]

_COND_SELF_HP = re.compile(r"生命值(?:小于等于?|≤|不超过)本(?:随从|角色)")

_COND_LEGENDARY = [
    re.compile(r"传说(?:的)?(?:随从|角色)"),
    re.compile(r"legendary\s+(?:minion|character)", re.IGNORECASE),
]

_NO_TARGET_KEYWORDS = [
    "draw", "抽牌", "summon", "召唤", "discover", "发现",
    "armor", "护甲", "heal.*?hero", "恢复.*?英雄",
    "secret", "奥秘", "quest", "任务", "shuffle", "洗入",
    "discard", "弃牌", r"freeze\s+all",
]

_TARGETING_KEYWORDS = [
    "敌方", "友方", "enemy", "friendly",
    "一个.{0,20}随从", r"a\s+minion", r"an?\s+minion",
    "一个.{0,20}角色", r"a\s+character", r"an?\s+character",
    "一个.{0,20}英雄", r"enemy\s+hero", r"friendly\s+hero",
    "敌方地标",
]


# ── Resolver class ────────────────────────────────────────────────

class SpellTargetResolver:
    """Resolve legal spell targets from card text and game state.

    Flow: parse card text → TargetSpec → generate target indices from GameState.
    Target encoding: 0=enemy hero, 1..N=enemy minion, -1..-M=friendly minion.
    """

    def resolve_targets(self, state: GameState, card: Card) -> List[int]:
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

        has_damage = False
        if _DAMAGE_EN is not None:
            has_damage = bool(_DAMAGE_EN.search(target_clause))
        if not has_damage and _DAMAGE_CN is not None:
            has_damage = bool(_DAMAGE_CN.search(target_clause))
        has_targeting_keyword = any(
            re.search(kw, target_clause, re.IGNORECASE) for kw in _TARGETING_KEYWORDS
        )

        if not has_damage and not has_targeting_keyword and self._is_no_target(text):
            spec.needs_target = False
            return spec

        if not has_damage and not has_targeting_keyword:
            spec.needs_target = False
            return spec

        conditions = self._parse_conditions(target_clause)
        spec.conditions = conditions

        side, etype = self._parse_side_and_type(target_clause, card_type, has_damage)
        spec.side = side
        spec.entity_type = etype

        return spec

    @staticmethod
    def _extract_target_clause(text: str) -> str:
        clause = text.split('。')[0].split('；')[0].split(';')[0]
        for sep in ['。', '，', '，']:
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

        if re.search(r"友方武器|your\s+weapon", text, re.IGNORECASE):
            return TargetSide.FRIENDLY, TargetEntityType.WEAPON

        m = _COND_RACE_CN.search(text)
        if m:
            return TargetSide.FRIENDLY, TargetEntityType.MINION
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
            if _any_match(_COND_DAMAGED_MINION_ONLY, text):
                pass
            conditions.append(_is_damaged)

        if _any_match(_COND_UNDAMAGED, text):
            conditions.append(_is_undamaged)

        if _any_match(_COND_FROZEN, text):
            conditions.append(_is_frozen)

        if _any_match(_COND_TAUNT, text):
            conditions.append(_has_taunt)

        m = _COND_ATK_LE.search(text) or _COND_ATK_LE_EN.search(text)
        if m:
            conditions.append(_attack_leq(int(m.group(1))))

        m = _COND_ATK_GE.search(text) or _COND_ATK_GE_EN.search(text)
        if m:
            conditions.append(_attack_geq(int(m.group(1))))

        m = _COND_COST_GE.search(text) or _COND_COST_GE_EN.search(text)
        if m:
            conditions.append(_cost_geq(int(m.group(1))))

        if _any_match(_COND_LEGENDARY, text):
            conditions.append(self._is_legendary)

        if _any_match(_COND_ENEMY_LOCATION, text):
            conditions.append(_is_location)

        if _any_match(_COND_HAS_RACE_TAG, text):
            conditions.append(_has_race_tag)

        m = _COND_HP_LE.search(text) or _COND_HP_LE_EN.search(text)
        if m:
            conditions.append(_health_leq(int(m.group(1))))

        m = _COND_RACE_CN.search(text)
        if m:
            race_cn = m.group(1)
            race_en = _RACE_MAP_CN_EN.get(race_cn, race_cn)
            conditions.append(_is_race(race_en))
        else:
            m = _COND_RACE_EN.search(text)
            if m:
                race_en = m.group(1).upper()
                conditions.append(_is_race(race_en))

        return conditions

    # ── Target generation ────────────────────────────────

    def _generate_targets(self, state: GameState, spec: TargetSpec) -> List[int]:
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
                opp_hero_hp = state.opponent.hero.hp if hasattr(state, 'opponent') else 30
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
        card_ref = getattr(minion, 'card_ref', None)
        if card_ref and getattr(card_ref, 'rarity', '') == 'LEGENDARY':
            return True
        card_id = getattr(minion, 'card_id', '')
        if card_id:
            try:
                from analysis.card.data.hsdb import get_db
                db = get_db()
                card_data = db.get_card(card_id)
                if card_data and card_data.get('rarity') == 'LEGENDARY':
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _is_aoe(text: str) -> bool:
        for p in _AOE_PATTERNS:
            if p.search(text):
                return True
        if _AOE_EN is not None and _AOE_EN.search(text):
            return True
        if _AOE_CN is not None and _AOE_CN.search(text):
            return True
        if re.search(r"对所有.*?造成", text):
            return True
        return False

    @staticmethod
    def has_targeting_keyword(text: str) -> bool:
        return any(re.search(kw, text, re.IGNORECASE) for kw in _TARGETING_KEYWORDS)

    @staticmethod
    def _is_no_target(text: str) -> bool:
        if SpellTargetResolver.has_targeting_keyword(text):
            return False
        tl = text.lower()
        return any(re.search(kw, tl) for kw in _NO_TARGET_KEYWORDS)


# ── Utility ────────────────────────────────────────────────────────

def _any_match(patterns: list, text: str) -> bool:
    return any(p.search(text) for p in patterns)

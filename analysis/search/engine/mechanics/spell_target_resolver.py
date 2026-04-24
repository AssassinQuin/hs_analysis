"""TargetResolver — data-driven target resolution for ALL card types.

Architecture:
  1. Parse card text → TargetSpec (side + entity_type + conditions)
  2. Apply TargetSpec to GameState → list of target indices
  3. Target encoding: 0=enemy hero, 1..N=enemy minion, -1..-M=friendly minion

Supports: SPELL, MINION (battlecry), LOCATION, HERO_POWER, WEAPON, HERO
All Standard (Year of the Hydra) targeting conditions are covered.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Callable

from analysis.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, _AOE_CN, _AOE_EN
from analysis.search.game_state import GameState, Minion
from analysis.models.card import Card


# ── Enums ──────────────────────────────────────────────────────────

class TargetSide(Enum):
    """Which side of the board can be targeted."""
    ENEMY = auto()       # 敌方
    FRIENDLY = auto()    # 友方
    ANY = auto()         # 任意一侧


class TargetEntityType(Enum):
    """What type of entity can be targeted."""
    CHARACTER = auto()   # 英雄 + 随从
    MINION = auto()      # 随从 only
    HERO = auto()        # 英雄 only
    WEAPON = auto()      # 武器 (encoded as hero target)
    LOCATION = auto()    # 地标


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
    """Create a predicate that checks for a specific race."""
    race_lower = race.lower()

    def check(m: Minion) -> bool:
        m_race = getattr(m, 'race', '') or ''
        if m_race.lower() == race_lower:
            return True
        # Also check via card_id lookup for multi-race minions
        card_ref = getattr(m, 'card_ref', None)
        if card_ref:
            cr_race = getattr(card_ref, 'race', '') or ''
            if cr_race.lower() == race_lower:
                return True
        # Check races list (for multi-race minions)
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
    """Check if minion has any race (not blank)."""
    race = getattr(minion, 'race', '') or ''
    return race != '' and race.upper() not in ('', 'NONE', 'ALL')


def _is_location(minion: Minion) -> bool:
    """Check if entity is a Location (by card_ref type or special check)."""
    card_ref = getattr(minion, 'card_ref', None)
    if card_ref:
        return getattr(card_ref, 'card_type', '').upper() == 'LOCATION'
    return False


class _SelfHPThreshold:
    """Dynamic threshold: minion HP ≤ source card's health attribute."""
    def __init__(self, source_health: int):
        self.threshold = source_health

    def __call__(self, minion: Minion) -> bool:
        return minion.health <= self.threshold


# ── TargetSpec ─────────────────────────────────────────────────────

@dataclass
class TargetSpec:
    """Parsed target specification from card text."""
    side: TargetSide = TargetSide.ENEMY
    entity_type: TargetEntityType = TargetEntityType.CHARACTER
    conditions: List[Callable[[Minion], bool]] = field(default_factory=list)
    is_aoe: bool = False
    needs_target: bool = True


# ── Regex patterns for text parsing ────────────────────────────────

# --- Side patterns ---
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
    re.compile(r"一个.{0,20}?随从"),  # "一个攻击力≥7的随从" — allow longer conditions
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

# --- AOE patterns ---
_AOE_PATTERNS = [
    re.compile(r"all\s+enemies", re.IGNORECASE),
    re.compile(r"所有敌人"),
    re.compile(r"对所有(?:敌方)?(?:随从|角色)"),
    re.compile(r"all\s+minion", re.IGNORECASE),
    re.compile(r"所有随从"),
]

# --- Condition patterns ---
_COND_DAMAGED = [
    re.compile(r"(?<!未)受伤(?:的)?(?:随从|角色|友方)"),  # Negative lookbehind: NOT "未受伤"
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

# Race name mapping (CN → English race tag)
_RACE_MAP_CN_EN = {
    "龙": "DRAGON", "亡灵": "UNDEAD", "野兽": "BEAST", "恶魔": "DEMON",
    "机械": "MECHANICAL", "元素": "ELEMENTAL", "鱼人": "MURLOC", "海盗": "PIRATE",
    "图腾": "TOTEM", "精灵": "ELF", "树人": "TREANT",
}

# --- Stat comparison patterns ---
_COND_ATK_LE = re.compile(r"攻击力(?:小于等于?|≤|不超过)(\d+)")
_COND_ATK_LE_EN = re.compile(r"(?:attack|attack.*?)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE)
_COND_ATK_GE = re.compile(r"攻击力(?:大于(?:或)?等于?|≥|不小于|至少)(\d+)")
_COND_ATK_GE_EN = re.compile(r"(?:attack|attack.*?)(?:more|at least|≥)\s*(\d+)", re.IGNORECASE)
_COND_COST_GE = re.compile(r"法力值消耗(?:大于等于?|≥|不小于|至少)(\d+)")
_COND_COST_GE_EN = re.compile(r"costs?\s*(?:at least|≥|more)\s*(\d+)", re.IGNORECASE)
_COND_HP_LE = re.compile(r"(?:生命值|血量)(?:小于等于?|≤|不超过)(\d+)")
_COND_HP_LE_EN = re.compile(r"(?:health|hp)(?:less|at most|≤)\s*(\d+)", re.IGNORECASE)

# --- Location condition ---
_COND_ENEMY_LOCATION = [
    re.compile(r"敌方地标"),
    re.compile(r"enemy\s+location", re.IGNORECASE),
]

# --- Race tag condition ("有种族标签的敌方随从" = pest control) ---
_COND_HAS_RACE_TAG = [
    re.compile(r"有种族标签(?:的)?(?:敌方)?(?:随从|角色)"),
    re.compile(r"minion\s+with\s+a\s+race\s+tag", re.IGNORECASE),
]

# --- Self HP threshold ("HP ≤ 本随从攻击力/生命值") ---
_COND_SELF_HP = re.compile(r"生命值(?:小于等于?|≤|不超过)本(?:随从|角色)")

# --- Rarity patterns ---
_COND_LEGENDARY = [
    re.compile(r"传说(?:的)?(?:随从|角色)"),
    re.compile(r"legendary\s+(?:minion|character)", re.IGNORECASE),
]

# --- No-target keywords ---
_NO_TARGET_KEYWORDS = [
    "draw", "抽牌", "summon", "召唤", "discover", "发现",
    "armor", "护甲", "heal.*?hero", "恢复.*?英雄",
    "secret", "奥秘", "quest", "任务", "shuffle", "洗入",
    "discard", "弃牌", "freeze\s+all",
]

# If ANY of these appear in text, the spell definitely needs a target
_TARGETING_KEYWORDS = [
    "敌方", "友方", "enemy", "friendly",
    "一个.{0,20}随从", "a\s+minion", "an?\s+minion",
    "一个.{0,20}角色", "a\s+character", "an?\s+character",
    "一个.{0,20}英雄", "enemy\s+hero", "friendly\s+hero",
    "敌方地标",
]


# ── Resolver ───────────────────────────────────────────────────────

class SpellTargetResolver:
    """Resolve legal spell targets from card text and game state.

    Flow: parse card text → TargetSpec → generate target indices from GameState.
    Target encoding: 0=enemy hero, 1..N=enemy minion, -1..-M=friendly minion.
    """

    def resolve_targets(self, state: GameState, card: Card) -> List[int]:
        """Return list of valid target indices for playing *card* in *state*."""
        text = getattr(card, "text", "") or ""
        if not text:
            return []

        card_type = getattr(card, "card_type", "").upper()

        # Step 1: Parse text into TargetSpec
        spec = self._parse_spec(text, card_type)
        if spec is None:
            return []
        if spec.is_aoe or not spec.needs_target:
            return []

        # Step 2: Generate target indices from state
        return self._generate_targets(state, spec)

    # ── Spec parsing ─────────────────────────────────────

    def _parse_spec(self, text: str, card_type: str) -> Optional[TargetSpec]:
        """Parse card text into a TargetSpec."""
        spec = TargetSpec()

        # AOE → no player-chosen targets
        if self._is_aoe(text):
            spec.is_aoe = True
            return spec

        # Extract only the TARGETING clause (before first period/effect keyword)
        # e.g., "对一个受伤的随从造成8点伤害。如果XXX" → "对一个受伤的随从造成8点伤害"
        target_clause = self._extract_target_clause(text)

        # Has damage in target clause → must need a target
        has_damage = bool(_DAMAGE_EN.search(target_clause) or _DAMAGE_CN.search(target_clause))
        has_targeting_keyword = any(
            re.search(kw, target_clause, re.IGNORECASE) for kw in _TARGETING_KEYWORDS
        )

        if not has_damage and not has_targeting_keyword and self._is_no_target(text):
            spec.needs_target = False
            return spec

        # No targeting keywords and no damage → not a targeted spell
        if not has_damage and not has_targeting_keyword:
            spec.needs_target = False
            return spec

        # Parse conditions from TARGET CLAUSE only (not from effect/condition clauses)
        conditions = self._parse_conditions(target_clause)
        spec.conditions = conditions

        # Parse side + entity_type from TARGET CLAUSE
        side, etype = self._parse_side_and_type(target_clause, card_type, has_damage)
        spec.side = side
        spec.entity_type = etype

        return spec

    @staticmethod
    def _extract_target_clause(text: str) -> str:
        """Extract the targeting clause from card text.

        Targeting info appears BEFORE the first effect keyword or period.
        e.g., "对一个受伤的随从造成8点伤害。溢出回手。" → "对一个受伤的随从造成8点伤害"
        e.g., "造成3点伤害。如果手牌中有5费随从，抽牌。" → "造成3点伤害"
        """
        # Split at first Chinese period or semicolon
        clause = text.split('。')[0].split('；')[0].split(';')[0]
        # Also trim at common effect separators
        for sep in ['。', '，', '，']:
            if sep in clause:
                clause = clause.split(sep)[0]
        return clause.strip()

    def _parse_side_and_type(
        self, text: str, card_type: str, has_damage: bool
    ) -> tuple[TargetSide, TargetEntityType]:
        """Determine target side and entity type from text patterns."""
        # Check specific patterns first (most specific → least specific)

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

        # "友方武器" / "your weapon"
        if re.search(r"友方武器|your\s+weapon", text, re.IGNORECASE):
            return TargetSide.FRIENDLY, TargetEntityType.WEAPON

        # Race-specific friendly (e.g., "友方龙" / "friendly Dragon")
        m = _COND_RACE_CN.search(text)
        if m:
            return TargetSide.FRIENDLY, TargetEntityType.MINION
        m = _COND_RACE_EN.search(text)
        if m:
            return TargetSide.FRIENDLY, TargetEntityType.MINION

        # Default for damage spells: enemy characters
        if card_type == "SPELL" and has_damage:
            return TargetSide.ENEMY, TargetEntityType.CHARACTER

        # Default for locations with targeting text: any minion
        # (locations like 赤红深渊 "对一个随从造成..." target any minion)
        if card_type == "LOCATION" and has_damage:
            return TargetSide.ANY, TargetEntityType.MINION

        # Default for minion battlecry with targeting text: depends on keywords
        # If we got here with damage + minion, likely targets any character
        if card_type == "MINION" and has_damage:
            return TargetSide.ANY, TargetEntityType.CHARACTER

        # Unknown → no target
        return TargetSide.ENEMY, TargetEntityType.CHARACTER

    def _parse_conditions(self, text: str) -> List[Callable[[Minion], bool]]:
        """Parse all target conditions from card text."""
        conditions: List[Callable[[Minion], bool]] = []

        # Damaged
        if _any_match(_COND_DAMAGED, text):
            if _any_match(_COND_DAMAGED_MINION_ONLY, text):
                pass  # minion-only handled by entity_type
            conditions.append(_is_damaged)

        # Undamaged (e.g., Backstab: "未受伤的随从")
        if _any_match(_COND_UNDAMAGED, text):
            conditions.append(_is_undamaged)

        # Frozen
        if _any_match(_COND_FROZEN, text):
            conditions.append(_is_frozen)

        # Taunt
        if _any_match(_COND_TAUNT, text):
            conditions.append(_has_taunt)

        # Attack ≤ N
        m = _COND_ATK_LE.search(text) or _COND_ATK_LE_EN.search(text)
        if m:
            conditions.append(_attack_leq(int(m.group(1))))

        # Attack ≥ N
        m = _COND_ATK_GE.search(text) or _COND_ATK_GE_EN.search(text)
        if m:
            conditions.append(_attack_geq(int(m.group(1))))

        # Cost ≥ N
        m = _COND_COST_GE.search(text) or _COND_COST_GE_EN.search(text)
        if m:
            conditions.append(_cost_geq(int(m.group(1))))

        # Legendary
        if _any_match(_COND_LEGENDARY, text):
            conditions.append(self._is_legendary)

        # Location (敌方地标)
        if _any_match(_COND_ENEMY_LOCATION, text):
            conditions.append(_is_location)

        # Has race tag (有种族标签的敌方随从 — Pest Control)
        if _any_match(_COND_HAS_RACE_TAG, text):
            conditions.append(_has_race_tag)

        # HP ≤ N
        m = _COND_HP_LE.search(text) or _COND_HP_LE_EN.search(text)
        if m:
            conditions.append(_health_leq(int(m.group(1))))

        # Race (from "友方X" patterns)
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
        """Generate target indices from state based on spec."""
        targets: List[int] = []

        def _minion_passes(m: Minion) -> bool:
            """Check if a minion satisfies all conditions."""
            return all(cond(m) for cond in spec.conditions)

        if spec.entity_type == TargetEntityType.WEAPON:
            # Weapon target → encoded as friendly hero (0 is enemy hero, no standard encoding)
            # For now, return special negative index
            if state.hero.weapon is not None:
                targets.append(-99)  # Convention: weapon = index -99
            return targets

        if spec.entity_type == TargetEntityType.LOCATION:
            # Location targets: search enemy board for location-type entities
            if spec.side in (TargetSide.ENEMY, TargetSide.ANY):
                for i, m in enumerate(state.opponent.board):
                    if _is_location(m) and _minion_passes(m):
                        targets.append(i + 1)
            if spec.side in (TargetSide.FRIENDLY, TargetSide.ANY):
                for i, m in enumerate(state.board):
                    if _is_location(m) and _minion_passes(m):
                        targets.append(-(i + 1))
            return targets

        # Include hero targets?
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

            # Enemy minions
            for i, m in enumerate(state.opponent.board):
                if _minion_passes(m):
                    targets.append(i + 1)

        if spec.side in (TargetSide.FRIENDLY, TargetSide.ANY):
            # Friendly minions
            for i, m in enumerate(state.board):
                if _minion_passes(m):
                    targets.append(-(i + 1))

        return targets

    # ── Helper methods ───────────────────────────────────

    @staticmethod
    def _is_legendary(minion: Minion) -> bool:
        """Check if a minion is legendary via card_ref or db lookup."""
        card_ref = getattr(minion, 'card_ref', None)
        if card_ref and getattr(card_ref, 'rarity', '') == 'LEGENDARY':
            return True
        # Fallback: check via card_id
        card_id = getattr(minion, 'card_id', '')
        if card_id:
            try:
                from analysis.data.hsdb import get_db
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
        if _AOE_EN.search(text) or _AOE_CN.search(text):
            return True
        if re.search(r"对所有.*?造成", text):
            return True
        return False

    @staticmethod
    def _is_no_target(text: str) -> bool:
        """Check if spell text indicates no player-chosen target is needed.

        Returns False (i.e., spell DOES need a target) if any targeting keyword
        is present in the text, regardless of other no-target keywords.
        """
        # If text contains targeting keywords, it definitely needs a target
        for kw in _TARGETING_KEYWORDS:
            if re.search(kw, text, re.IGNORECASE):
                return False

        # Otherwise, check for no-target keywords
        tl = text.lower()
        return any(re.search(kw, tl) for kw in _NO_TARGET_KEYWORDS)


# ── Utility ────────────────────────────────────────────────────────

def _any_match(patterns: list, text: str) -> bool:
    """Check if any pattern in the list matches text."""
    return any(p.search(text) for p in patterns)

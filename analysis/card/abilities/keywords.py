# -*- coding: utf-8 -*-
"""KeywordSet – an immutable, frozen-set-backed keyword container for Hearthstone entities.

Replaces the 30+ boolean ``has_X`` / ``is_X`` fields on ``Minion`` with a single
``KeywordSet`` that is cheap to copy (frozenset is hashable and shared across
RHEA search-tree nodes via structural sharing).

This module intentionally does **not** import ``game_state`` to avoid circular deps.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:  # pragma: no cover – avoid circular import at runtime
    from analysis.card.models.card import Card

__all__ = [
    "CANONICAL_KEYWORDS",
    "KEYWORD_CN_MAP",
    "KEYWORD_EN_MAP",
    "KeywordSet",
    "keyword_to_cn",
]

# ═══════════════════════════════════════════════════════════════════
# Canonical keyword registry (all lowercase)
# ═══════════════════════════════════════════════════════════════════

CANONICAL_KEYWORDS: frozenset[str] = frozenset({
    # ── Core combat keywords ──────────────────────────────────────
    "taunt", "divine_shield", "stealth", "windfury", "rush", "charge",
    "poisonous", "lifesteal", "reborn", "immune",
    # ── Status ────────────────────────────────────────────────────
    "frozen", "dormant", "cant_attack",
    # ── Trigger keywords ──────────────────────────────────────────
    "spellburst", "frenzy", "deathrattle", "battlecry", "inspire",
    "overkill", "honorable_kill",
    # ── Modifiers ─────────────────────────────────────────────────
    "magnetic", "corrupt", "outcast", "invoke", "colossal",
    "mega_windfury", "ward",
    # ── Mechanic keywords ─────────────────────────────────────────
    "discover", "choose_one", "echo", "twinspell", "tradeable",
    "dredge", "overheat", "titan", "forge", "overheal",
    "miniaturize", "excavate", "imbue",
})

# ═══════════════════════════════════════════════════════════════════
# Mapping: lowercase keyword → Chinese display name
# ═══════════════════════════════════════════════════════════════════

KEYWORD_CN_MAP: dict[str, str] = {
    # Core
    "taunt":         "嘲讽",
    "divine_shield": "圣盾",
    "charge":        "冲锋",
    "rush":          "突袭",
    "windfury":      "风怒",
    "stealth":       "潜行",
    "poisonous":     "剧毒",
    "lifesteal":     "吸血",
    "reborn":        "复生",
    "immune":        "免疫",
    # Status
    "frozen":        "冻结",
    "dormant":       "休眠",
    "cant_attack":   "不可攻击",
    # Trigger
    "deathrattle":   "亡语",
    "battlecry":     "战吼",
    "discover":      "发现",
    "spellburst":    "法术迸发",
    "frenzy":        "暴怒",
    "inspire":       "激励",
    "overkill":      "过量击杀",
    "honorable_kill": "荣誉消灭",
    # Modifiers
    "corrupt":       "腐化",
    "outcast":       "流放",
    "magnetic":      "磁力",
    "invoke":        "祈求",
    "colossal":      "巨型",
    "mega_windfury": "超级风怒",
    "ward":          "护盾",
    # Mechanics
    "choose_one":    "抉择",
    "echo":          "回响",
    "twinspell":     "双职业法术",
    "tradeable":     "可交易",
    "dredge":        "探底",
    "overheat":      "过热",
    "titan":         "泰坦",
    "forge":         "锻造",
    "overheal":      "过量治疗",
    "miniaturize":   "微型化",
    "excavate":      "发掘",
    "imbue":         "灌注",
}

# ═══════════════════════════════════════════════════════════════════
# Mapping: lowercase keyword → uppercase mechanic string
#           (as found in Card.mechanics / Hearthstone API)
# ═══════════════════════════════════════════════════════════════════

KEYWORD_EN_MAP: dict[str, str] = {
    "taunt":         "TAUNT",
    "divine_shield": "DIVINE_SHIELD",
    "charge":        "CHARGE",
    "rush":          "RUSH",
    "windfury":      "WINDFURY",
    "stealth":       "STEALTH",
    "poisonous":     "POISONOUS",
    "lifesteal":     "LIFESTEAL",
    "reborn":        "REBORN",
    "immune":        "IMMUNE",
    "frozen":        "FROZEN",
    "dormant":       "DORMANT",
    "cant_attack":   "CANT_ATTACK",
    "deathrattle":   "DEATHRATTLE",
    "battlecry":     "BATTLECRY",
    "discover":      "DISCOVER",
    "spellburst":    "SPELLBURST",
    "frenzy":        "FRENZY",
    "inspire":       "INSPIRE",
    "overkill":      "OVERKILL",
    "honorable_kill": "HONORABLE_KILL",
    "corrupt":       "CORRUPT",
    "outcast":       "OUTCAST",
    "magnetic":      "MAGNETIC",
    "invoke":        "INVOKE",
    "colossal":      "COLOSSAL",
    "mega_windfury": "MEGA_WINDFURY",
    "ward":          "WARD",
    "choose_one":    "CHOOSE_ONE",
    "echo":          "ECHO",
    "twinspell":     "TWINSPELL",
    "tradeable":     "TRADEABLE",
    "dredge":        "DREDGE",
    "overheat":      "OVERHEAT",
    "titan":         "TITAN",
    "forge":         "FORGE",
    "overheal":      "OVERHEAL",
    "miniaturize":   "MINIATURIZE",
    "excavate":      "EXCAVATE",
    "imbue":         "IMBUE",
}

# Reverse lookup: uppercase mechanic → lowercase canonical name
_REVERSE_EN_MAP: dict[str, str] = {v: k for k, v in KEYWORD_EN_MAP.items()}


# ═══════════════════════════════════════════════════════════════════
# Module-level helper
# ═══════════════════════════════════════════════════════════════════

def keyword_to_cn(keyword: str) -> str:
    """Return the Chinese display name for *keyword*, falling back to the
    keyword itself when no mapping exists."""
    return KEYWORD_CN_MAP.get(keyword.lower(), keyword)


# ═══════════════════════════════════════════════════════════════════
# KeywordSet
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class KeywordSet:
    """Immutable keyword container backed by a ``frozenset``.

    Designed for cheap structural sharing across RHEA search-tree copies:
    adding or removing a keyword produces a *new* ``KeywordSet`` while the
    underlying ``frozenset`` shares memory with the original via Python's
    frozenset copy-on-write semantics.
    """

    _kw: frozenset = frozenset()

    # ── Query ────────────────────────────────────────────────────

    def has(self, keyword: str) -> bool:
        """Return ``True`` if *keyword* is present (case-insensitive)."""
        return keyword.lower() in self._kw

    # ── Functional update (return new KeywordSet) ────────────────

    def add(self, keyword: str) -> KeywordSet:
        """Return a new ``KeywordSet`` with *keyword* added."""
        kw = keyword.lower()
        return KeywordSet(self._kw | {kw})

    def remove(self, keyword: str) -> KeywordSet:
        """Return a new ``KeywordSet`` with *keyword* removed."""
        kw = keyword.lower()
        return KeywordSet(self._kw - {kw})

    # ── Set operations ───────────────────────────────────────────

    def union(self, other: KeywordSet) -> KeywordSet:
        """Merge *other* into a new ``KeywordSet``."""
        return KeywordSet(self._kw | other._kw)

    def difference(self, other: KeywordSet) -> KeywordSet:
        """Keywords present in *self* but not in *other*."""
        return KeywordSet(self._kw - other._kw)

    # ── Dunder protocol ──────────────────────────────────────────

    def __contains__(self, keyword: object) -> bool:  # type: ignore[override]
        if isinstance(keyword, str):
            return self.has(keyword)
        return False

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._kw))

    def __len__(self) -> int:
        return len(self._kw)

    def __bool__(self) -> bool:
        return bool(self._kw)

    def __repr__(self) -> str:
        return f"KeywordSet({sorted(self._kw)})"

    # ── Display ──────────────────────────────────────────────────

    def to_cn(self) -> str:
        """Comma-joined Chinese keyword names for UI display."""
        return ", ".join(keyword_to_cn(kw) for kw in sorted(self._kw))

    # ── Construction helpers ─────────────────────────────────────

    @classmethod
    def from_mechanics(cls, mechanics: list[str]) -> KeywordSet:
        """Build from a ``Card.mechanics``-style list of uppercase strings."""
        kw: set[str] = set()
        for m in mechanics:
            lower = m.lower()
            # Direct reverse-map hit
            if lower in _REVERSE_EN_MAP:
                kw.add(_REVERSE_EN_MAP[lower])
            elif lower in CANONICAL_KEYWORDS:
                kw.add(lower)
        return cls(frozenset(kw))

    @classmethod
    def from_card(cls, card: Card) -> KeywordSet:  # type: ignore[name-defined]
        """Build a ``KeywordSet`` from a ``Card`` object.

        Inspects ``card.mechanics`` (uppercase strings) and maps them to
        canonical lowercase keyword names.  Also checks boolean ``has_X``
        attributes when present on the card object.
        """
        kw: set[str] = set()

        # 1. Parse mechanics list (uppercase → lowercase canonical)
        for m in getattr(card, "mechanics", None) or []:
            lower = m.lower()
            if lower in _REVERSE_EN_MAP:
                kw.add(_REVERSE_EN_MAP[lower])
            elif lower in CANONICAL_KEYWORDS:
                kw.add(lower)

        # 2. Scan boolean has_X / is_X attributes for extra coverage
        _bool_prefixes = ("has_", "is_")
        for attr in dir(card):
            if attr.startswith(_bool_prefixes):
                val = getattr(card, attr, False)
                if val is True:
                    name = attr[4:]  # strip has_/is__ → both give substring after prefix
                    # Actually: has_taunt → taunt, is_dormant → dormant
                    if attr.startswith("has_"):
                        name = attr[4:]
                    else:  # is_
                        name = attr[3:]
                    name = name.lower()
                    if name in CANONICAL_KEYWORDS:
                        kw.add(name)

        return cls(frozenset(kw))

    @classmethod
    def from_minion(cls, minion: object) -> KeywordSet:
        """Build a ``KeywordSet`` from a ``Minion`` dataclass instance.

        Reads the boolean ``has_X`` / ``is_X`` / ``cant_attack`` fields and
        maps them to canonical keywords.  Accepts any object with these
        attributes; missing attributes are treated as ``False``.
        """
        _FIELD_MAP: list[tuple[str, str]] = [
            ("has_taunt", "taunt"),
            ("has_divine_shield", "divine_shield"),
            ("has_stealth", "stealth"),
            ("has_windfury", "windfury"),
            ("has_rush", "rush"),
            ("has_charge", "charge"),
            ("has_poisonous", "poisonous"),
            ("has_lifesteal", "lifesteal"),
            ("has_reborn", "reborn"),
            ("has_immune", "immune"),
            ("cant_attack", "cant_attack"),
            ("is_dormant", "dormant"),
            ("has_spellburst", "spellburst"),
            ("has_ward", "ward"),
            ("has_mega_windfury", "mega_windfury"),
            ("has_magnetic", "magnetic"),
            ("has_invoke", "invoke"),
            ("has_corrupt", "corrupt"),
            ("is_outcast", "outcast"),
        ]
        kw: set[str] = set()
        for attr, keyword in _FIELD_MAP:
            if getattr(minion, attr, False):
                kw.add(keyword)
        return cls(frozenset(kw))

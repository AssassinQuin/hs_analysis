"""interface.py — Parser protocol and top-level parse() entry point.

The Parser is the central abstraction of the effects system:

    parse(card_id, text) → ParsedCard | None

Resolution order:
  1. Look up card_id in the card DB for metadata.
  2. Attempt structured JSON parse (card_abilities.json).
  3. Fall back to English text parse.
  4. Return None if neither succeeds.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Protocol

from analysis.effects.types import ParsedCard, Ability, Effect, Trigger, TargetSpec
from analysis.effects.parser.registry import CardLookup

log = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════
# Parser Protocol
# ════════════════════════════════════════════════════════════════

class CardParser(Protocol):
    """Protocol for card-to-ParsedCard parsers."""

    def parse(self, card_id: str, text: str = "") -> ParsedCard | None:
        """Parse a card by ID, optionally with fallback text."""
        ...


class BaseParser(ABC):
    """Abstract base for parsers with common utilities."""

    @abstractmethod
    def parse(self, card_id: str, text: str = "") -> ParsedCard | None:
        ...


# ════════════════════════════════════════════════════════════════
# Chaining Parser — JSON first, text fallback
# ════════════════════════════════════════════════════════════════

class ChainingParser(BaseParser):
    """Composite parser: JSON first, text fallback.

    Resolution:
      1. Look up card_id in CardLookup for metadata.
      2. Build ParsedCard skeleton from metadata.
      3. Try JSON parser to fill in abilities.
      4. If JSON yields no abilities (or all TODO), run text parser.
      5. Return the merged result.
    """

    def __init__(self) -> None:
        from analysis.effects.parser.json_parser import JsonAbilityParser
        from analysis.effects.parser.text_parser import TextAbilityParser
        self._lookup = CardLookup()
        self._json_parser = JsonAbilityParser()
        self._text_parser = TextAbilityParser()
        self._cache: dict[str, ParsedCard | None] = {}

    def parse(self, card_id: str, text: str = "") -> ParsedCard | None:
        """Parse card_id → ParsedCard using JSON first, text fallback.

        Args:
            card_id: Primary key (e.g. "CORE_EX1_012").
            text: English card text fallback.

        Returns:
            ParsedCard or None if card cannot be resolved.
        """
        # Cache check
        if card_id in self._cache:
            return self._cache[card_id]

        # 1. Look up card metadata
        meta = self._lookup.get_metadata(card_id)
        if meta is None:
            log.debug("CardLookup: no metadata for %s", card_id)
            self._cache[card_id] = None
            return None

        text = text or meta.get("text", "")

        # 2. Build skeleton ParsedCard from metadata
        card = self._build_skeleton(card_id, meta, text)

        # 3. Try JSON parser
        abilities = self._json_parser.parse_abilities(card_id, meta)
        if abilities:
            card.abilities = abilities

        # 4. If no abilities from JSON, try text parser
        if not card.abilities and text:
            log.debug("Text fallback for %s", card_id)
            text_abilities = self._text_parser.parse_abilities(card_id, text, meta)
            card.abilities = text_abilities or []

        self._cache[card_id] = card
        return card

    def parse_text_only(self, card_id: str, text: str,
                        meta: dict | None = None) -> ParsedCard:
        """Force text-only parse (for testing / fallback)."""
        if meta is None:
            meta = self._lookup.get_metadata(card_id) or {}
        card = self._build_skeleton(card_id, meta, text)
        card.abilities = self._text_parser.parse_abilities(card_id, text, meta) or []
        return card

    # ── helpers ──────────────────────────────────────────────

    def _build_skeleton(self, card_id: str, meta: dict,
                        text: str) -> ParsedCard:
        return ParsedCard(
            card_id=card_id,
            name=meta.get("name", ""),
            cost=meta.get("cost", 0),
            original_cost=meta.get("cost", 0),
            card_type=meta.get("type", ""),
            card_class=meta.get("cardClass", ""),
            attack=meta.get("attack", 0),
            health=meta.get("health", 0),
            durability=meta.get("durability", 0),
            race=meta.get("race", ""),
            spell_school=meta.get("spellSchool", ""),
            mechanics=meta.get("mechanics", []),
            text_raw=text,
        )

    def invalidate(self, card_id: str) -> None:
        """Clear cache entry (useful for hot-reload)."""
        self._cache.pop(card_id, None)


# ── Module-level singleton & convenience ─────────────────────

_PARSER: ChainingParser | None = None


def get_parser() -> ChainingParser:
    global _PARSER
    if _PARSER is None:
        _PARSER = ChainingParser()
    return _PARSER


def parse(card_id: str, text: str = "") -> ParsedCard | None:
    """Convenience: parse a single card by ID.

    Example:
        pc = parse("CORE_EX1_012")
        if pc:
            for ab in pc.abilities:
                print(ab.trigger, ab.effects)
    """
    return get_parser().parse(card_id, text)

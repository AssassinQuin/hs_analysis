# -*- coding: utf-8 -*-
"""deck_provider.py — Reads Decks.log to extract deck codes for game sessions.

Hearthstone's Power.log doesn't provide card_id for our own starting hand cards
(FULL_ENTITY with CardID= empty). But the game log directory contains Decks.log
which has deck codes that can be decoded to get the full card list.

Decks.log format:
    I 08:45:19.2938010 Finding Game With Deck:
    I 08:45:19.2938010 ### 龙战
    I 08:45:19.2938010 # Deck ID: 9380525315
    I 08:45:19.2938010 AAECAYwWAougBNCyBw7j5gaq/Aar/AbohwfSlwe3rQePsQfssgeEvQe1wAeVwgebwgecwgf5wwcAAA==

Each "Finding Game With Deck:" block contains deck name, ID, and Base64 deck code.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from analysis.card.models.card import Card
from analysis.models.game_record import DeckInfo

log = logging.getLogger(__name__)

# Regex to extract timestamp from log lines: "I 08:45:19.2938010 ..."
_RE_TIMESTAMP = re.compile(r"^\w\s+(\d{2}:\d{2}:\d{2})")

# Regex to extract content after timestamp prefix: "I 08:45:19.2938010 <content>"
_RE_CONTENT = re.compile(r"^\w\s+\d{2}:\d{2}:\d{2}\.\d+\s+(.*)")

# "Finding Game With Deck:" marker
_RE_FINDING_GAME = re.compile(r"Finding Game With Deck:")

# Deck name line: "### <name>"
_RE_DECK_NAME = re.compile(r"^###\s+(.+)")

# Deck ID line: "# Deck ID: <id>"
_RE_DECK_ID = re.compile(r"# Deck ID:\s*(\d+)")

# Deck code: Base64 string (may contain +, /, =)
_RE_DECK_CODE = re.compile(r"^([A-Za-z0-9+/]+=*)$")


@dataclass
class _DeckEntry:
    """A parsed deck entry from Decks.log."""
    timestamp: str  # HH:MM:SS
    name: str = ""
    deck_id: str = ""
    code: str = ""
    deck_info: Optional[DeckInfo] = None


class DeckProvider:
    """Reads Decks.log and provides deck information matched to game start times.

    Usage:
        provider = DeckProvider("/path/to/Hearthstone/Logs/Decks.log")
        deck = provider.get_deck_for_game("08:38:49")
        if deck:
            print(deck.name, deck.cards)
    """

    def __init__(self, decks_log_path: str = None):
        self._entries: List[_DeckEntry] = []
        if decks_log_path:
            self._parse(decks_log_path)

    def _parse(self, path: str) -> None:
        """Parse Decks.log and populate _entries."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
        except FileNotFoundError:
            log.warning("Decks.log not found: %s", path)
            return
        except Exception as e:
            log.warning("Error reading Decks.log: %s", e)
            return

        current: Optional[_DeckEntry] = None

        for raw_line in lines:
            line = raw_line.rstrip("\n")

            # Extract timestamp
            ts_match = _RE_TIMESTAMP.search(line)
            timestamp = ts_match.group(1) if ts_match else ""

            # Extract content after timestamp prefix
            content_match = _RE_CONTENT.match(line)
            content = content_match.group(1).strip() if content_match else line.strip()

            # Detect "Finding Game With Deck:" — start of a new block
            if _RE_FINDING_GAME.search(content):
                # Finalize any previous entry
                if current is not None:
                    self._finalize_entry(current)
                current = _DeckEntry(timestamp=timestamp)
                continue

            if current is None:
                continue

            # Deck name: "### <name>"
            name_m = _RE_DECK_NAME.match(content)
            if name_m:
                current.name = name_m.group(1).strip()
                continue

            # Deck ID: "# Deck ID: <id>"
            id_m = _RE_DECK_ID.search(content)
            if id_m:
                current.deck_id = id_m.group(1).strip()
                continue

            # Deck code: pure Base64 line (may have = padding)
            code_m = _RE_DECK_CODE.match(content)
            if code_m and len(content) > 20:  # deck codes are long
                current.code = content
                continue

        # Finalize last entry
        if current is not None:
            self._finalize_entry(current)

        log.info("DeckProvider: parsed %d deck entries from %s",
                 len(self._entries), path)

    def _finalize_entry(self, entry: _DeckEntry) -> None:
        """Decode deck code and store the entry."""
        if not entry.code:
            log.debug("Skipping deck entry without code: %s", entry.name)
            return

        try:
            deck_info = DeckInfo.from_deck_code(
                name=entry.name,
                deck_id=entry.deck_id,
                code=entry.code,
            )
            entry.deck_info = deck_info
        except Exception as e:
            log.warning("Failed to decode deck '%s': %s", entry.name, e)
            return

        self._entries.append(entry)

    def get_deck_for_game(self, game_start_timestamp: str) -> Optional[DeckInfo]:
        """Get deck info for a game by matching timestamps.

        Finds the "Finding Game With Deck" entry with the closest timestamp
        BEFORE the game start.

        Args:
            game_start_timestamp: HH:MM:SS format timestamp from Power.log

        Returns:
            DeckInfo if a matching deck is found, None otherwise.
        """
        if not self._entries:
            return None

        game_seconds = self._to_seconds(game_start_timestamp)

        # Find the closest entry with timestamp <= game_start
        best: Optional[_DeckEntry] = None
        best_diff = float("inf")

        for entry in self._entries:
            entry_seconds = self._to_seconds(entry.timestamp)
            diff = game_seconds - entry_seconds

            # Entry must be before (or at) game start
            if diff >= 0 and diff < best_diff:
                best_diff = diff
                best = entry

        if best is not None:
            return best.deck_info
        return None

    def get_deck_cards(self, game_start_timestamp: str) -> List[Card]:
        """Get expanded list of Card objects for a game's deck.

        Returns a flat list with each card appearing count times (30 total
        for a standard deck).
        """
        deck_info = self.get_deck_for_game(game_start_timestamp)
        if deck_info is None:
            return []

        from analysis.card.data.hsdb import get_db
        db = get_db(load_xml=False, build_indexes=False)

        cards: List[Card] = []
        for deck_card in deck_info.cards:
            # Try to get full card data from hsdb
            if deck_card.card_id and not deck_card.card_id.startswith("dbf:"):
                raw = db.get_card(deck_card.card_id)
                if raw:
                    card = Card.from_hsdb_dict(raw)
                else:
                    card = Card(
                        card_id=deck_card.card_id,
                        name=deck_card.name,
                        cost=deck_card.cost,
                        card_type=deck_card.card_type,
                        card_class=deck_card.cardClass,
                    )
            else:
                card = Card(
                    card_id=deck_card.card_id,
                    name=deck_card.name,
                    cost=deck_card.cost,
                    card_type=deck_card.card_type,
                    card_class=deck_card.cardClass,
                )
            # Expand by count
            for _ in range(deck_card.count):
                cards.append(card)

        return cards

    def make_card_lookup(self, game_start_timestamp: str = None) -> Callable[[str], Optional[Card]]:
        """Create a card_lookup callable for StateBridge.

        The returned callable first tries HSCardDB lookup, then falls back
        to deck card data if available.

        Args:
            game_start_timestamp: HH:MM:SS to match deck for current game.
                If None, only HSCardDB lookup is used.
        """
        from analysis.card.data.hsdb import get_db
        _db = get_db(load_xml=False, build_indexes=False)

        # Build deck card map: card_id → Card for fast lookup
        deck_card_map = {}
        if game_start_timestamp:
            deck_cards = self.get_deck_cards(game_start_timestamp)
            for card in deck_cards:
                if card.card_id:
                    deck_card_map[card.card_id] = card

        # Build cost-based index for anonymous card matching
        # cost → list of Card (for cards with no card_id match)
        deck_cost_map: dict[int, List[Card]] = {}
        if game_start_timestamp:
            deck_cards = self.get_deck_cards(game_start_timestamp)
            for card in deck_cards:
                cost = card.cost
                deck_cost_map.setdefault(cost, []).append(card)

        def _lookup(card_id: str) -> Optional[Card]:
            if not card_id:
                return None

            # Try HSCardDB first
            raw = _db.get_card(card_id)
            if raw:
                return Card.from_hsdb_dict(raw)

            # Try deck card map
            if card_id in deck_card_map:
                return deck_card_map[card_id]

            return None

        return _lookup

    @staticmethod
    def _to_seconds(timestamp: str) -> int:
        """Convert HH:MM:SS to total seconds."""
        try:
            parts = timestamp.split(":")
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            return 0

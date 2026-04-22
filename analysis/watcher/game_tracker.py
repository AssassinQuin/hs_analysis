"""game_tracker.py — Incremental Power.log parser using hslog."""

from __future__ import annotations

from typing import Optional, List
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter
from hearthstone.enums import GameTag, Zone, CardType, Step, State


class _SafeEntityTreeExporter(EntityTreeExporter):
    """EntityTreeExporter that handles None entities gracefully."""
    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


class GameTracker:
    """Tracks Hearthstone game state by incrementally parsing Power.log lines.

    Feed lines via feed_line(). Query current state via properties.
    Detects game start/end transitions.
    """

    def __init__(self):
        self._parser = LogParser()
        self._game_count = 0
        self._in_game = False
        self._current_game_entities = None  # exported entity tree
        self._last_event_type = None

    def feed_line(self, line: str) -> Optional[str]:
        """Feed a single Power.log line. Returns event type or None.

        Returns:
            "game_start" — a new game began
            "game_end" — current game ended
            "turn_start" — new turn started
            "action" — game action processed
            None — line ignored/empty
        """
        if not line or not line.strip():
            self._last_event_type = None
            return None

        try:
            self._parser.read_line(line)

            # Check for game transitions
            current_game_count = len(self._parser.games)

            if not self._in_game and current_game_count > self._game_count:
                # New game started
                self._in_game = True
                self._game_count = current_game_count
                self._last_event_type = "game_start"
                return "game_start"

            # Check for game end
            if self._in_game:
                if self._parser.games and self._parser.games[-1].tags.get(GameTag.STATE) == State.COMPLETE:
                    self._in_game = False
                    self._last_event_type = "game_end"
                    return "game_end"

                # Check for new turn
                if self._parser.games and self._parser.games[-1].tags.get(GameTag.STEP) != self._current_step():
                    new_step = self._current_step()
                    if new_step != self._current_step():
                        self._last_event_type = "turn_start"
                        return "turn_start"

            self._last_event_type = "action"
            return "action"

        except Exception:
            # Silently ignore malformed lines or exceptions from hslog
            self._last_event_type = None
            return None

    def feed_lines(self, lines: List[str]) -> List[str]:
        """Feed multiple lines. Returns list of event types."""
        events = []
        for line in lines:
            event = self.feed_line(line)
            if event is not None:
                events.append(event)
        return events

    def load_file(self, path: str) -> List[str]:
        """Load and parse an entire Power.log file. Returns event types."""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            return self.feed_lines([line.rstrip("\n") for line in lines])
        except Exception as e:
            # Silently ignore file read errors
            return []

    @property
    def in_game(self) -> bool:
        """True if currently tracking an active game."""
        return self._in_game

    @property
    def game_count(self) -> int:
        """Number of games parsed so far."""
        return self._game_count

    @property
    def current_game(self):
        """The hslog Game object for the current game, or None."""
        if not self._in_game or not self._parser.games:
            return None
        return self._parser.games[-1]

    @property
    def current_player(self):
        """The hslog Player object for the first (friendly) player."""
        game = self.current_game
        if game is None or not game.players:
            return None
        return game.players[0]

    @property
    def current_opponent(self):
        """The hslog Player object for the opponent."""
        game = self.current_game
        if game is None or len(game.players) < 2:
            return None
        return game.players[1]

    def export_entities(self):
        """Export current game's entity tree. Returns game object with full entity access."""
        game = self.current_game
        if game is None:
            return None

        # Create a safe exporter with the game's packet tree
        packet_tree = self._parser.games[0] if self._parser.games else None
        if packet_tree is None:
            return None
        exporter = _SafeEntityTreeExporter(packet_tree)
        exporter.export()
        self._current_game_entities = exporter.game

        return self._current_game_entities

        return self._current_game_entities

    def get_current_turn(self) -> int:
        """Get current turn number from game state."""
        game = self.current_game
        if game is None:
            return 0
        return game.tags.get(GameTag.TURN, 0)

    def get_step(self) -> str:
        """Get current game step (BEGIN_MULLIGAN, MAIN_READY, MAIN_ACTION, etc)."""
        game = self.current_game
        if game is None:
            return "NOT_STARTED"
        step = game.tags.get(GameTag.STEP)
        return Step(step).name if step is not None else "UNKNOWN"

    def _current_step(self) -> Optional[int]:
        """Get current step tag value."""
        game = self.current_game
        if game is None:
            return None
        return game.tags.get(GameTag.STEP)

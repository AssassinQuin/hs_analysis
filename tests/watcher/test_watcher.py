"""Tests for analysis.watcher — Power.log parsing pipeline."""

import os
import tempfile
import time
from pathlib import Path

import pytest

# Skip all tests if hslog not available
pytest.importorskip("hslog")
pytest.importorskip("hearthstone")


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
POWER_LOG = PROJECT_ROOT / "Power.log"


@pytest.fixture
def power_log_path():
    if not POWER_LOG.exists():
        pytest.skip("Power.log not found in project root")
    return str(POWER_LOG)


class TestLogWatcher:
    """Test LogWatcher file tailing."""

    def test_read_existing_file(self, tmp_path):
        """Can read all lines from an existing file."""
        from analysis.watcher.log_watcher import LogWatcher

        f = tmp_path / "test.log"
        f.write_text("line1\nline2\nline3\n")

        watcher = LogWatcher(str(f), poll_interval=0.01)
        # Read initial content (non-blocking)
        lines = watcher.read_existing_content()
        assert len(lines) == 3
        assert lines[0] == "line1"

    def test_rotation_detection(self, tmp_path):
        """Detects file rotation when file shrinks."""
        from analysis.watcher.log_watcher import LogWatcher

        f = tmp_path / "test.log"
        f.write_text("long line 1\nlong line 2\n")

        rotations = []
        watcher = LogWatcher(str(f), poll_interval=0.01, on_rotation=lambda: rotations.append(1))

        # Read initial content
        watcher.read_existing_content()

        # Simulate rotation: truncate and write new content
        f.write_text("new\n")
        watcher.read_existing_content()

        assert len(rotations) >= 1

    def test_nonexistent_file(self, tmp_path):
        """Handles non-existent file gracefully."""
        from analysis.watcher.log_watcher import LogWatcher

        watcher = LogWatcher(str(tmp_path / "nonexistent.log"))
        lines = list(watcher.lines())
        assert lines == []


class TestGameTracker:
    """Test GameTracker incremental parsing."""

    def test_load_power_log(self, power_log_path):
        """Can load and parse Power.log."""
        from analysis.watcher.game_tracker import GameTracker

        tracker = GameTracker()
        events = tracker.load_file(power_log_path)

        assert len(events) > 0
        assert tracker.game_count >= 1
        assert tracker.in_game

    def test_export_entities(self, power_log_path):
        """Exports entity tree from parsed game."""
        from analysis.watcher.game_tracker import GameTracker

        tracker = GameTracker()
        tracker.load_file(power_log_path)
        game = tracker.export_entities()

        assert game is not None
        assert len(list(game.players)) >= 2

    def test_feed_line_incremental(self):
        """Feeds lines one at a time."""
        from analysis.watcher.game_tracker import GameTracker

        tracker = GameTracker()
        result = tracker.feed_line("D 08:49:52.691723 - GameState.DebugPrintPower() - CREATE_GAME\n")
        assert result is not None


class TestStateBridge:
    """Test StateBridge entity → GameState conversion."""

    def test_convert_power_log(self, power_log_path):
        """Full conversion from Power.log to GameState."""
        from analysis.watcher.game_tracker import GameTracker
        from analysis.watcher.state_bridge import StateBridge

        tracker = GameTracker()
        tracker.load_file(power_log_path)
        game = tracker.export_entities()

        bridge = StateBridge()
        state = bridge.convert(game, player_index=0)

        # Should have reasonable values
        assert state.hero.hp > 0
        assert state.mana.max_mana >= 0
        assert state.turn_number >= 1

    def test_convert_both_players(self, power_log_path):
        """Can convert state for both players."""
        from analysis.watcher.game_tracker import GameTracker
        from analysis.watcher.state_bridge import StateBridge

        tracker = GameTracker()
        tracker.load_file(power_log_path)
        game = tracker.export_entities()

        bridge = StateBridge()
        s0 = bridge.convert(game, player_index=0)
        s1 = bridge.convert(game, player_index=1)

        assert s0.hero.hp > 0
        assert s1.hero.hp > 0

    def test_convert_none_game(self):
        """Handles None game gracefully."""
        from analysis.watcher.state_bridge import StateBridge

        bridge = StateBridge()
        state = bridge.convert(None)

        assert state.hero.hp == 30  # default


class TestDecisionLoop:
    """Test DecisionLoop and DecisionPresenter."""

    def test_analyze_file(self, power_log_path, capsys):
        """analyze_file runs without errors on test Power.log."""
        from analysis.watcher.decision_loop import DecisionLoop

        DecisionLoop.analyze_file(power_log_path, pop_size=5, max_gens=5, time_limit=100.0)

        # Should have produced some output
        captured = capsys.readouterr()
        # Just verify it doesn't crash — output content depends on game state

    def test_presenter_format(self, capsys):
        """DecisionPresenter formats output correctly."""
        from analysis.watcher.decision_loop import DecisionPresenter
        from analysis.search.rhea_engine import SearchResult

        # Use StringIO for output to avoid "closed file" error in tests
        from io import StringIO
        output = StringIO()
        presenter = DecisionPresenter(output=output, verbose=True)

        # Create a minimal SearchResult for testing
        result = SearchResult(
            best_chromosome=[],
            best_fitness=0.0,
            alternatives=[],
            generations_run=10,
            time_elapsed=50.0,
            population_diversity=0.1,
            confidence=0.95,
        )

        from analysis.search.game_state import GameState
        state = GameState()
        presenter.present(result, state, 50.0)

        captured = capsys.readouterr()
        output_content = output.getvalue()
        assert "50" in output_content or "ms" in output_content

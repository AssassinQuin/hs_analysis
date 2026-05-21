"""Shared fixtures for Game 7 (Rogue vs Priest) integration tests.

Game 7 info:
  - Source: Hearthstone_2026_04_23_08_43_35/Power.log, lines 227382–283760
  - Player 1 (湫然#51704): Rogue (HERO_03az), goes SECOND
  - Player 2 (UNKNOWN HUMAN PLAYER): Priest (HERO_09a), goes FIRST
  - player_index=0 for 湫然 (PlayerID=1)
  - Our turns = even game turns (2, 4, 6, ..., 26)
  - 26 total turns, longest game in the log

Fixture file: tests/fixtures/game7_rogue_vs_priest_26t.log
"""

import os
import pytest

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge

_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
FIXTURE_PATH = os.path.join(
    _PROJECT_ROOT, 'tests', 'fixtures', 'game7_rogue_vs_priest_26t.log'
)
PLAYER_INDEX = 0  # 湫然#51704 is PlayerID=1


@pytest.fixture(scope="module")
def game7_states():
    """Extract GameState at each turn from Game 7 fixture.

    Returns dict {turn_number: GameState}.
    """
    if not os.path.exists(FIXTURE_PATH):
        pytest.skip("Game 7 fixture not found")

    with open(FIXTURE_PATH, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line.rstrip("\n") for line in f]

    tracker = GameTracker()
    bridge = StateBridge()
    current_game = 0
    states = {}

    for line in lines:
        event = tracker.feed_line(line)
        if event == "game_start":
            current_game += 1
        elif event == "turn_start" and current_game == 1:
            turn = tracker.get_current_turn()
            if turn is not None and turn not in states:
                game = tracker.export_entities()
                if game is not None:
                    state = bridge.convert(game, player_index=PLAYER_INDEX)
                    if state and state.hero and state.hero.hp > 0:
                        states[turn] = state

    if not states:
        pytest.skip("No states extracted from Game 7 fixture")
    return states

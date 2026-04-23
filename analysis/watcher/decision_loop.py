"""decision_loop.py — Main loop: Power.log → parse → decide → output.

Usage:
    from analysis.watcher.decision_loop import DecisionLoop

    loop = DecisionLoop("/path/to/Power.log")
    loop.run()  # blocking

    # Or one-shot from existing log file:
    DecisionLoop.analyze_file("/path/to/Power.log")
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional, TextIO

from analysis.watcher.log_watcher import LogWatcher
from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.search.rhea_engine import RHEAEngine, SearchResult, Action
from analysis.utils.score_provider import load_scores_into_hand

log = logging.getLogger(__name__)


class DecisionPresenter:
    """Formats and outputs decision suggestions."""

    def __init__(self, output: TextIO = sys.stdout, verbose: bool = False):
        self.output = output
        self.verbose = verbose

    def present(self, result: SearchResult, state, elapsed_ms: float) -> None:
        """Print decision result to output."""
        self.output.write(f"Turn {state.turn_number}:\n")
        for i, action in enumerate(result.best_chromosome):
            self.output.write(f"  {i + 1}. {action.describe(state)}\n")
        self.output.write(f"Score: {result.best_fitness:+.2f} | Time: {elapsed_ms:.2f} ms\n")
        self.output.write(
            f"Decision: conf={result.confidence:.2f} | "
            f"div={result.population_diversity:.2f} | "
            f"gens={result.generations_run}\n"
        )

        if result.timings:
            self.output.write(
                "Timing: "
                f"utp={result.timings.get('utp', 0):.1f}ms, "
                f"rhea={result.timings.get('rhea', 0):.1f}ms, "
                f"phaseB={result.timings.get('phase_b', 0):.1f}ms, "
                f"oppSim={result.timings.get('opp_sim', 0):.1f}ms, "
                f"crossTurn={result.timings.get('cross_turn', 0):.1f}ms\n"
            )

        if result.alternatives:
            self.output.write("Alternatives:\n")
            for rank, (chromo, fitness) in enumerate(result.alternatives, 1):
                line = " -> ".join(action.describe(state) for action in chromo)
                self.output.write(f"  {rank}. {line} | score={fitness:+.2f}\n")

        self.output.write("\n")


class DecisionLoop:
    """Main decision loop: watches Power.log and outputs turn decisions.

    Flow:
        1. LogWatcher detects new lines in Power.log
        2. GameTracker parses lines incrementally
        3. On turn start (MAIN_READY/MAIN_ACTION):
           a. StateBridge converts to GameState
           b. load_scores_into_hand() populates card scores
           c. RHEAEngine.search() finds best action sequence
           d. DecisionPresenter outputs the recommendation
    """

    def __init__(
        self,
        log_path: str | Path,
        *,
        engine_params: Optional[dict] = None,
        poll_interval: float = 0.05,
        on_decision: Optional[Callable] = None,
        output: TextIO = sys.stdout,
        verbose: bool = False,
    ):
        """
        Args:
            log_path: Path to Hearthstone Power.log
            engine_params: Override RHEAEngine params (pop_size, max_gens, time_limit, etc.)
            poll_interval: File polling interval in seconds (default 50ms)
            on_decision: Callback(search_result, game_state) after each decision
            output: Where to print decisions
            verbose: Extra logging output
        """
        self.log_path = Path(log_path)
        self.engine_params = engine_params or {
            "pop_size": 30,
            "max_gens": 80,
            "max_chromosome_length": 8,
            "cross_turn": True,
        }
        self.poll_interval = poll_interval
        self.on_decision = on_decision
        self.presenter = DecisionPresenter(output, verbose)

        self._tracker = GameTracker()
        self._bridge = StateBridge()
        self._running = False
        self._last_turn = 0
        self._last_decision_signature: tuple | None = None
        self._last_replan_at = 0.0
        self._replan_cooldown_s = float(self.engine_params.get("replan_cooldown_s", 0.8))

    @staticmethod
    def _latest_unfinished_game_lines(lines: list[str]) -> list[str]:
        """Return only lines belonging to the latest unfinished game."""
        if not lines:
            return []

        probe = GameTracker()
        current_game_start = 0

        for idx, line in enumerate(lines):
            event = probe.feed_line(line)
            if event == "game_start":
                current_game_start = idx

        if not probe.in_game:
            return []
        return lines[current_game_start:]

    def run(self) -> None:
        """Start the blocking decision loop. Runs until interrupted."""
        self._running = True

        def on_rotation():
            log.info("Log rotation detected, resetting tracker")
            self._tracker = GameTracker()

        watcher = LogWatcher(self.log_path, poll_interval=self.poll_interval, on_rotation=on_rotation)

        try:
            log.info(f"Starting decision loop for {self.log_path}")

            # On startup, skip completed historical games and replay only the latest unfinished one.
            existing_lines = watcher.read_existing_content()
            bootstrap_lines = self._latest_unfinished_game_lines(existing_lines)
            for line in bootstrap_lines:
                if not self._running:
                    break
                self._on_line(line)

            for line in watcher:
                if not self._running:
                    break
                self._on_line(line)
        except KeyboardInterrupt:
            log.info("Decision loop interrupted")
        except Exception as e:
            log.error(f"Error in decision loop: {e}", exc_info=True)
        finally:
            self.stop()
            watcher.close()

    def stop(self) -> None:
        """Signal the loop to stop."""
        self._running = False

    def _on_line(self, line: str) -> None:
        """Process a single new line from the log."""
        event = self._tracker.feed_line(line)
        if event is None:
            return

        if event == "game_start":
            log.info("New game detected")
            self._last_turn = 0
            self._last_decision_signature = None
        elif event == "game_end":
            log.info("Game ended")
            # Keep watcher alive so we can detect subsequent games in the same log stream.
            self._last_turn = 0
            self._last_decision_signature = None
        elif event == "turn_start":
            current_turn = self._tracker.get_current_turn()
            if current_turn != self._last_turn and current_turn > 0:
                log.debug(f"Turn {current_turn} started")
                self._make_decision()
                self._last_turn = current_turn
        elif event == "action":
            self._maybe_replan_on_action()

    @staticmethod
    def _state_signature(state) -> tuple:
        """Build a compact signature used to skip duplicate replans."""
        our_board = tuple(
            (
                m.card_id,
                m.attack,
                m.health,
                bool(m.can_attack),
                bool(m.has_taunt),
                bool(m.has_divine_shield),
            )
            for m in state.board
        )
        opp_board = tuple(
            (
                m.card_id,
                m.attack,
                m.health,
                bool(m.can_attack),
                bool(m.has_taunt),
                bool(m.has_divine_shield),
            )
            for m in state.opponent.board
        )
        hand_cards = tuple((c.name, c.cost) for c in state.hand)
        return (
            state.turn_number,
            state.mana.available,
            state.mana.max_mana,
            state.hero.hp,
            state.hero.armor,
            state.opponent.hero.hp,
            state.opponent.hero.armor,
            state.opponent.hand_count,
            hand_cards,
            our_board,
            opp_board,
        )

    def _build_state(self):
        game = self._tracker.export_entities()
        if game is None:
            return None
        state = self._bridge.convert(game, player_index=0)
        if state.turn_number == 0:
            return None
        return state

    def _maybe_replan_on_action(self) -> None:
        """Replan during our action phase when board/hand state changes."""
        current_turn = self._tracker.get_current_turn()
        if current_turn <= 0:
            return
        if current_turn != self._last_turn:
            # New turn decisions are handled by the turn_start event.
            return

        step = self._tracker.get_step()
        if step not in ("MAIN_ACTION", "MAIN_READY"):
            return

        now = time.perf_counter()
        if (now - self._last_replan_at) < self._replan_cooldown_s:
            return

        state = self._build_state()
        if state is None:
            return

        sig = self._state_signature(state)
        if sig == self._last_decision_signature:
            return

        log.debug("State changed in-turn, replanning decision")
        self._run_search_and_present(state, sig)
        self._last_replan_at = time.perf_counter()

    def _make_decision(self) -> None:
        """Convert current state → run RHEA → output decision."""
        state = self._build_state()
        if state is None:
            log.warning("Cannot export game state, skipping decision")
            return

        sig = self._state_signature(state)
        self._run_search_and_present(state, sig)
        self._last_replan_at = time.perf_counter()

    def _run_search_and_present(self, state, signature: tuple | None = None) -> None:
        """Run RHEA search on a prepared state and print result."""

        load_scores_into_hand(state)

        engine = RHEAEngine(
            pop_size=self.engine_params.get("pop_size", 30),
            max_gens=self.engine_params.get("max_gens", 80),
            time_limit=self.engine_params.get("time_limit", 75.0),
            max_chromosome_length=self.engine_params.get("max_chromosome_length", 8),
            cross_turn=self.engine_params.get("cross_turn", True),
        )

        start_time = time.perf_counter()
        result = engine.search(state)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        self.presenter.present(result, state, elapsed_ms)
        if signature is not None:
            self._last_decision_signature = signature

        if self.on_decision:
            try:
                self.on_decision(result, state)
            except Exception as e:
                log.error(f"Error in decision callback: {e}", exc_info=True)

    @staticmethod
    def analyze_file(path: str | Path, output: TextIO = sys.stdout, **engine_kwargs) -> None:
        """One-shot: analyze an entire Power.log file and output decisions for each turn."""
        log_path = Path(path)
        if not log_path.exists():
            log.error(f"Log file not found: {log_path}")
            return

        log.info(f"Analyzing log file: {log_path}")

        tracker = GameTracker()
        bridge = StateBridge()

        events = tracker.load_file(log_path)
        log.info(f"Parsed {len(events)} events")

        last_turn = 0
        for event in events:
            if event == "game_start":
                last_turn = 0
            elif event == "game_end":
                break
            elif event == "turn_start":
                current_turn = tracker.get_current_turn()
                if current_turn > 0 and current_turn != last_turn:
                    game = tracker.export_entities()
                    if game is None:
                        last_turn = current_turn
                        continue

                    state = bridge.convert(game, player_index=0)
                    if state.turn_number == 0:
                        last_turn = current_turn
                        continue

                    load_scores_into_hand(state)

                    engine = RHEAEngine(
                        pop_size=engine_kwargs.get("pop_size", 30),
                        max_gens=engine_kwargs.get("max_gens", 80),
                        time_limit=engine_kwargs.get("time_limit", 75.0),
                        max_chromosome_length=engine_kwargs.get("max_chromosome_length", 8),
                        cross_turn=engine_kwargs.get("cross_turn", True),
                    )

                    start_time = time.perf_counter()
                    result = engine.search(state)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    presenter = DecisionPresenter(output=output)
                    presenter.present(result, state, elapsed_ms)

                    last_turn = current_turn

        log.info("File analysis complete")

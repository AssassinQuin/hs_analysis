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
from analysis.search.rhea.actions import Action
from analysis.search.engine_adapter import UnifiedSearchResult, create_engine
from analysis.utils.score_provider import load_scores_into_hand

log = logging.getLogger(__name__)


class DecisionPresenter:
    """Formats and outputs decision suggestions with rich terminal display."""

    def __init__(
        self,
        output: TextIO = sys.stdout,
        verbose: bool = False,
        show_board: bool = True,
        show_probabilities: bool = True,
        show_mcts_detail: bool = True,
    ):
        self.output = output
        self.verbose = verbose
        self.show_board = show_board
        self.show_probabilities = show_probabilities
        self.show_mcts_detail = show_mcts_detail

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _card_display(card) -> str:
        """Format card as 'name(cost)'."""
        name = card.name or getattr(card, "card_id", None) or "未知"
        return f"{name}({card.cost})"

    @staticmethod
    def _minion_display(m) -> str:
        """Format minion as 'name(atk/hp)'."""
        name = m.name or getattr(m, "card_id", None) or "?"
        return f"{name}({m.attack}/{m.health})"

    @staticmethod
    def _progress_bar(ratio: float, width: int = 20) -> str:
        """Return a progress bar string."""
        filled = int(ratio * width)
        return "█" * filled + "░" * (width - filled)

    def _line(self, text: str = "") -> None:
        self.output.write(f"│ {text}\n")

    # ── board state ──────────────────────────────────────────────────

    def _write_board(self, state) -> None:
        hero = state.hero
        mana = state.mana
        hand = state.hand
        board = state.board
        opp = state.opponent

        hero_str = f"英雄: {hero.hp}HP"
        if getattr(hero, "armor", 0):
            hero_str += f"/{hero.armor}A"
        self._line(f"[场面] {hero_str}  法力: {mana.available}/{mana.max_mana}  手牌: {len(hand)}  场面: {len(board)}")

        # Hand cards
        if hand:
            cards = " ".join(f"[{self._card_display(c)}]" for c in hand)
            self._line(f"[手牌] {cards}")

        # Our board
        if board:
            minions = " ".join(f"[{self._minion_display(m)}]" for m in board)
            self._line(f"[我方] {minions}")

        # Opponent
        opp_hero = opp.hero
        opp_board = opp.board
        opp_parts = [f"对手英雄: {opp_hero.hp}HP"]
        if getattr(opp_hero, "armor", 0):
            opp_parts[0] += f"/{opp_hero.armor}A"
        opp_parts.append(f"手牌: {opp.hand_count}")
        secrets = getattr(opp, "secrets", None)
        if secrets:
            opp_parts.append(f"奥秘: {len(secrets)}")
        if opp_board:
            opp_minions = " ".join(f"[{self._minion_display(m)}]" for m in opp_board)
            self._line(f"[敌方] {opp_minions}")
        self._line(opp_parts[0] + "  " + "  ".join(opp_parts[1:]))

    # ── main present ─────────────────────────────────────────────────

    def present(self, result: UnifiedSearchResult, state, elapsed_ms: float) -> None:
        """Print decision result to output."""
        turn = getattr(state, "turn_number", "?")
        self.output.write(f"┌─ Turn {turn} ─────────────────────────────\n")

        # Board state
        if self.show_board:
            self._write_board(state)

        self._line()

        # Optimal decision
        conf_str = f"  conf={result.confidence:.2f}" if result.confidence > 0 else ""
        self._line(f"★ 最优抉择 (Score: {result.best_fitness:+.2f} | {elapsed_ms:.0f}ms):{conf_str}")
        for i, action in enumerate(result.best_chromosome):
            prefix = ">>> " if i == 0 else "   "
            self._line(f"{prefix}{i + 1}. {action.describe(state)}")

        # Sub-optimal alternatives
        if result.alternatives:
            self._line()
            self._line("○ 次优抉择:")
            for rank, (chromo, fitness) in enumerate(result.alternatives, 1):
                for i, action in enumerate(chromo):
                    prefix = ">>> " if i == 0 else "   "
                    self._line(f"{prefix}{i + 1}. {action.describe(state)}")
                gap = result.best_fitness - fitness
                self._line(f"   (score: {fitness:+.2f} | 差距: {gap:.2f})")
                if rank < len(result.alternatives):
                    self._line()

        # Probability distribution (MCTS action_probs)
        if self.show_probabilities and result.action_probs:
            self._line()
            self._line("[概率分布]")
            for ap in result.action_probs:
                desc = ap.action.describe(state)
                if len(desc) > 20:
                    desc = desc[:20]
                bar = self._progress_bar(ap.probability, 20)
                self._line(
                    f"{desc:<20s} {bar} {ap.probability * 100:5.1f}%  "
                    f"胜率: {ap.win_rate * 100:.1f}%  (visits: {ap.visit_count})"
                )

        # MCTS detail
        if self.show_mcts_detail and result.mcts_stats is not None:
            ms = result.mcts_stats
            iters = getattr(ms, "iterations", 0)
            nodes = getattr(ms, "nodes_created", 0)
            evals = getattr(ms, "evaluations", iters)
            worlds = getattr(ms, "world_count", 0)
            time_ms = getattr(ms, "time_used_ms", elapsed_ms)
            iter_per_s = int(iters / (time_ms / 1000.0)) if time_ms > 0 else 0
            self._line()
            self._line(
                f"[MCTS] iters: {iters}  nodes: {nodes}  "
                f"evals: {evals}  worlds: {worlds}  {iter_per_s} iter/s"
            )

            # Detailed log
            detailed_log = result.mcts_detailed_log
            if detailed_log and detailed_log.entries:
                entries = detailed_log.entries
                n = len(entries)
                step = max(1, n // 10)
                sampled = entries[::step][:10]
                self._line(
                    f"[MCTS Log] iter={sampled[0].get('iter', '?')} "
                    f"nodes={sampled[0].get('nodes', '?')} "
                    f"evals={sampled[0].get('evals', '?')} "
                    f"best_q={sampled[0].get('best_q', 0):.4f} "
                    f"depth={sampled[0].get('depth', '?')}"
                )
                for entry in sampled[1:]:
                    self._line(
                        f"{'':13s}iter={entry.get('iter', '?')} "
                        f"nodes={entry.get('nodes', '?')} "
                        f"evals={entry.get('evals', '?')} "
                        f"best_q={entry.get('best_q', 0):.4f} "
                        f"depth={entry.get('depth', '?')}"
                    )

        # RHEA-specific output (when no MCTS stats)
        if result.mcts_stats is None:
            if result.timings:
                self._line()
                parts = []
                for key, label in [
                    ("utp", "utp"),
                    ("rhea", "rhea"),
                    ("phase_b", "phaseB"),
                    ("opp_sim", "oppSim"),
                    ("cross_turn", "crossTurn"),
                ]:
                    v = result.timings.get(key, 0)
                    if v:
                        parts.append(f"{label}={v:.1f}ms")
                if parts:
                    self._line(f"[Timing] {', '.join(parts)}")
            self._line(
                f"[RHEA] conf={result.confidence:.2f}  "
                f"div={result.population_diversity:.2f}  "
                f"gens={result.generations_run}"
            )

        self.output.write("└──────────────────────────────────────\n")


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
        engine: str = "rhea",
        engine_params: Optional[dict] = None,
        poll_interval: float = 0.05,
        on_decision: Optional[Callable] = None,
        output: TextIO = sys.stdout,
        verbose: bool = False,
        show_board: bool = True,
        show_probabilities: bool = True,
        show_mcts_detail: bool = True,
    ):
        """
        Args:
            log_path: Path to Hearthstone Power.log
            engine: Search engine to use ("rhea" or "mcts").
            engine_params: Override engine params (pop_size, max_gens, time_limit, etc.)
            poll_interval: File polling interval in seconds (default 50ms)
            on_decision: Callback(search_result, game_state) after each decision
            output: Where to print decisions
            verbose: Extra logging output
            show_board: Show board state in output
            show_probabilities: Show action probability distribution
            show_mcts_detail: Show MCTS detailed search log
        """
        self.log_path = Path(log_path)
        self._engine_name = engine
        self.engine_params = engine_params or {
            "pop_size": 30,
            "max_gens": 80,
            "max_chromosome_length": 8,
            "cross_turn": True,
        }
        self._engine_factory = create_engine(self._engine_name, self.engine_params)
        self.poll_interval = poll_interval
        self.on_decision = on_decision
        self.presenter = DecisionPresenter(
            output, verbose,
            show_board=show_board,
            show_probabilities=show_probabilities,
            show_mcts_detail=show_mcts_detail,
        )

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
        """Run search on a prepared state and print result."""

        load_scores_into_hand(state)

        engine = self._engine_factory()

        start_time = time.perf_counter()
        raw_result = engine.search(state)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        result = UnifiedSearchResult(raw_result)
        self.presenter.present(result, state, elapsed_ms)
        if signature is not None:
            self._last_decision_signature = signature

        if self.on_decision:
            try:
                self.on_decision(result, state)
            except Exception as e:
                log.error(f"Error in decision callback: {e}", exc_info=True)

    @staticmethod
    def analyze_file(path: str | Path, output: TextIO = sys.stdout, *, engine: str = "rhea", **engine_kwargs) -> None:
        """One-shot: analyze an entire Power.log file and output decisions for each turn."""
        log_path = Path(path)
        if not log_path.exists():
            log.error(f"Log file not found: {log_path}")
            return

        log.info(f"Analyzing log file: {log_path}")

        tracker = GameTracker()
        bridge = StateBridge()
        engine_factory = create_engine(engine, engine_kwargs)

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

                    eng = engine_factory()
                    start_time = time.perf_counter()
                    raw_result = eng.search(state)
                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    result = UnifiedSearchResult(raw_result)
                    presenter = DecisionPresenter(output=output)
                    presenter.present(result, state, elapsed_ms)

                    last_turn = current_turn

        log.info("File analysis complete")

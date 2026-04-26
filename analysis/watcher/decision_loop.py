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
from analysis.abilities.definition import Action
from analysis.search.adapter import UnifiedSearchResult, create_engine
from analysis.utils.score_provider import load_scores_into_hand

log = logging.getLogger(__name__)


_AGGRO_KEYWORDS = frozenset({
    "FACE", "AGGRO", "RUSH", "ZOO", "PIRATE", "MECH", "MURLOC", "DEMON",
    "BURN", "SMORC", "TEMPO",
})
_CONTROL_KEYWORDS = frozenset({
    "CONTROL", "SLOW", "WALL", "HEAL", "ARMOR", "REMOVE", "CLEAR",
    "GRIND", "FATIGUE", "COMBO", "OTK", "MIRACLE",
})


def _infer_opp_playstyle(state) -> str:
    opp = state.opponent
    known = opp.opp_known_cards
    if not known:
        turn = state.turn_number
        if turn <= 3:
            return "unknown"
        board_size = len(opp.board)
        if board_size >= 3:
            return "aggro"
        return "unknown"

    costs: list[int] = []
    spell_count = 0
    minion_count = 0
    for card in known:
        c = card if isinstance(card, dict) else {"card_id": str(card)}
        cid = c.get("card_id", "")
        cost = c.get("cost", 0)
        if isinstance(cost, int) and cost >= 0:
            costs.append(cost)
        cid_upper = cid.upper()
        if "MINION" in str(c.get("card_type", "")):
            minion_count += 1
        else:
            spell_count += 1
        for kw in _AGGRO_KEYWORDS:
            if kw in cid_upper:
                return "aggro"
        for kw in _CONTROL_KEYWORDS:
            if kw in cid_upper:
                return "control"

    if not costs:
        return "unknown"

    avg_cost = sum(costs) / len(costs)

    if avg_cost <= 2.5 and len(known) >= 3:
        return "aggro"
    if avg_cost >= 4.5 and spell_count > minion_count:
        return "combo"
    if avg_cost >= 4.0:
        return "control"
    return "midrange"


class TerminalDisplay:
    """Overwrite-based terminal display — keeps content in-place, refreshes on change.

    Terminal output is concise and efficient: overwrites previous content
    using ANSI escape codes. A separate file logger captures full detail.
    """

    def __init__(self, terminal: TextIO = sys.stdout, file_log: Optional[TextIO] = None):
        self._terminal = terminal
        self._file_log = file_log
        self._last_lines: int = 0
        self._is_tty = hasattr(terminal, 'isatty') and terminal.isatty()

    def _clear_previous(self) -> None:
        if not self._is_tty or self._last_lines <= 0:
            return
        for _ in range(self._last_lines):
            self._terminal.write("\033[A\033[K")
        self._terminal.flush()

    def _write_term(self, text: str) -> None:
        self._terminal.write(text)
        self._terminal.flush()

    def _write_file(self, text: str) -> None:
        if self._file_log is not None:
            self._file_log.write(text)
            self._file_log.flush()

    def present(self, result: UnifiedSearchResult, state, elapsed_ms: float, *,
                show_board: bool = True, show_probabilities: bool = True,
                show_mcts_detail: bool = True) -> None:
        term_lines: list[str] = []
        file_lines: list[str] = []

        turn = getattr(state, "turn_number", "?")

        file_lines.append(f"┌─ Turn {turn} ─────────────────────────────")

        if show_board:
            self._build_board(state, term_lines, file_lines)

        file_lines.append("│")

        conf_str = f"  conf={result.confidence:.2f}" if result.confidence > 0 else ""
        decision_text = f"★ 最优操作 (Score: {result.best_fitness:+.2f} | {elapsed_ms:.0f}ms):{conf_str}"
        term_lines.append(decision_text)
        file_lines.append(f"│ {decision_text}")

        if result.best_chromosome:
            action_desc = result.best_chromosome[0].describe(state)
            term_lines.append(f">>> {action_desc}")
            file_lines.append(f"│ >>> {action_desc}")

        if result.alternatives:
            file_lines.append("│")
            file_lines.append("│ ○ 次优操作:")
            for rank, (chromo, fitness) in enumerate(result.alternatives, 1):
                if chromo:
                    gap = result.best_fitness - fitness
                    alt_desc = chromo[0].describe(state)
                    file_lines.append(f"│    {rank}. {alt_desc}  (score: {fitness:+.2f} | 差距: {gap:.2f})")
                    if rank <= 2:
                        term_lines.append(f"  {rank}. {alt_desc[:40]}")

        if show_probabilities and getattr(result, 'action_probs', None):
            file_lines.append("│")
            file_lines.append("│ [概率分布]")
            for ap in result.action_probs:
                desc = ap.action.describe(state)
                if len(desc) > 20:
                    desc = desc[:20]
                bar = self._progress_bar(ap.probability, 20)
                file_lines.append(
                    f"│ {desc:<20s} {bar} {ap.probability * 100:5.1f}%  "
                    f"胜率: {ap.win_rate * 100:.1f}%  (visits: {ap.visit_count})"
                )

            probs = getattr(result, 'action_probs', None)
            if probs:
                top3 = probs[:3]
                prob_parts = " | ".join(
                    f"{ap.action.describe(state)[:15]}:{ap.probability * 100:.0f}%"
                    for ap in top3
                )
                term_lines.append(f"[概率] {prob_parts}")

        if show_mcts_detail and getattr(result, 'mcts_stats', None) is not None:
            ms = result.mcts_stats
            iters = getattr(ms, "iterations", 0)
            nodes = getattr(ms, "nodes_created", 0)
            evals = getattr(ms, "evaluations", iters)
            worlds = getattr(ms, "world_count", 0)
            time_ms = getattr(ms, "time_used_ms", elapsed_ms)
            iter_per_s = int(iters / (time_ms / 1000.0)) if time_ms > 0 else 0

            mcts_summary = f"[MCTS] {iters}iters {nodes}nodes {worlds}worlds {iter_per_s}it/s"
            term_lines.append(mcts_summary)
            file_lines.append("│")
            file_lines.append(f"│ {mcts_summary}")

            detailed_log = result.mcts_detailed_log
            if detailed_log and detailed_log.entries:
                entries = detailed_log.entries
                n = len(entries)
                step = max(1, n // 10)
                sampled = entries[::step][:10]
                file_lines.append(
                    f"│ [MCTS Log] iter={sampled[0].get('iter', '?')} "
                    f"nodes={sampled[0].get('nodes', '?')} "
                    f"evals={sampled[0].get('evals', '?')} "
                    f"best_q={sampled[0].get('best_q', 0):.4f} "
                    f"depth={sampled[0].get('depth', '?')}"
                )
                for entry in sampled[1:]:
                    file_lines.append(
                        f"{'':13s}iter={entry.get('iter', '?')} "
                        f"nodes={entry.get('nodes', '?')} "
                        f"evals={entry.get('evals', '?')} "
                        f"best_q={entry.get('best_q', 0):.4f} "
                        f"depth={entry.get('depth', '?')}"
                    )

        file_lines.append("└──────────────────────────────────────")

        self._clear_previous()

        if self._is_tty:
            self._write_term("\n".join(term_lines) + "\n")
            self._last_lines = len(term_lines)
        else:
            for line in file_lines:
                self._write_term(line + "\n")
            self._last_lines = len(file_lines)

        for line in file_lines:
            self._write_file(line + "\n")

    def present_status(self, text: str) -> None:
        if self._is_tty:
            self._clear_previous()
            self._write_term(text + "\n")
            self._last_lines = text.count("\n") + 1
        else:
            self._write_term(text + "\n")
        self._write_file(text + "\n")

    def _build_board(self, state, term_lines: list[str], file_lines: list[str]) -> None:
        hero = state.hero
        mana = state.mana
        hand = state.hand
        board = state.board
        opp = state.opponent

        hero_str = f"英雄: {hero.hp}HP"
        if getattr(hero, "armor", 0):
            hero_str += f"/{hero.armor}A"

        board_summary = f"Turn{getattr(state, 'turn_number', '?')} {hero_str} 法力:{mana.available}/{mana.max_mana} 手牌:{len(hand)} 场面:{len(board)}"
        term_lines.append(board_summary)
        file_lines.append(f"│ [场面] {hero_str}  法力: {mana.available}/{mana.max_mana}  手牌: {len(hand)}  场面: {len(board)}")

        if hand:
            cards = " ".join(f"[{self._card_display(c)}]" for c in hand)
            file_lines.append(f"│ [手牌] {cards}")
            hand_names = " ".join(c.name or "?" for c in hand[:7])
            term_lines.append(f"[手牌] {hand_names}")

        if board:
            minions = " ".join(f"[{self._minion_display(m)}]" for m in board)
            file_lines.append(f"│ [我方] {minions}")
            board_names = " ".join(f"{m.name}({m.attack}/{m.health})" for m in board)
            term_lines.append(f"[我方] {board_names}")

        opp_hero = opp.hero
        opp_board = opp.board
        opp_class = getattr(opp_hero, "hero_class", "") or ""
        if opp_class and opp_class != "UNKNOWN":
            opp_parts = [f"对手[{opp_class}]: {opp_hero.hp}HP"]
        else:
            opp_parts = [f"对手英雄: {opp_hero.hp}HP"]
        if getattr(opp_hero, "armor", 0):
            opp_parts[0] += f"/{opp_hero.armor}A"
        opp_parts.append(f"手牌:{opp.hand_count}")
        secrets = getattr(opp, "secrets", None)
        if secrets:
            opp_parts.append(f"奥秘:{len(secrets)}")
        if opp_board:
            opp_minions = " ".join(f"[{self._minion_display(m)}]" for m in opp_board)
            file_lines.append(f"│ [敌方] {opp_minions}")
            opp_board_names = " ".join(f"{m.name}({m.attack}/{m.health})" for m in opp_board)
            term_lines.append(f"[敌方] {opp_board_names}")
        file_lines.append(f"│ {'  '.join(opp_parts)}")
        term_lines.append("  ".join(opp_parts))

    @staticmethod
    def _card_display(card) -> str:
        name = card.name or getattr(card, "card_id", None) or "未知"
        return f"{name}({card.cost})"

    @staticmethod
    def _minion_display(m) -> str:
        name = m.name or getattr(m, "card_id", None) or "?"
        return f"{name}({m.attack}/{m.health})"

    @staticmethod
    def _progress_bar(ratio: float, width: int = 20) -> str:
        filled = int(ratio * width)
        return "█" * filled + "░" * (width - filled)


class DecisionPresenter:
    """Formats and outputs decision suggestions with rich terminal display.

    Delegates to TerminalDisplay for overwrite-based terminal output.
    """

    def __init__(
        self,
        output: TextIO = sys.stdout,
        verbose: bool = False,
        show_board: bool = True,
        show_probabilities: bool = True,
        show_mcts_detail: bool = True,
        file_log: Optional[TextIO] = None,
    ):
        self.output = output
        self.verbose = verbose
        self.show_board = show_board
        self.show_probabilities = show_probabilities
        self.show_mcts_detail = show_mcts_detail
        self._display = TerminalDisplay(terminal=output, file_log=file_log)

    def present(self, result: UnifiedSearchResult, state, elapsed_ms: float) -> None:
        self._display.present(
            result, state, elapsed_ms,
            show_board=self.show_board,
            show_probabilities=self.show_probabilities,
            show_mcts_detail=self.show_mcts_detail,
        )


class DecisionLoop:
    """Main decision loop: watches Power.log and outputs turn decisions.

    Flow:
        1. LogWatcher detects new lines in Power.log
        2. GameTracker parses lines incrementally
        3. On turn start (MAIN_READY/MAIN_ACTION):
           a. StateBridge converts to GameState
           b. load_scores_into_hand() populates card scores
           c. MCTSEngine.search() finds best action sequence
           d. DecisionPresenter outputs the recommendation
    """

    def __init__(
        self,
        log_path: str | Path,
        *,
        engine: str = "mcts",
        engine_params: Optional[dict] = None,
        poll_interval: float = 0.05,
        on_decision: Optional[Callable] = None,
        output: TextIO = sys.stdout,
        verbose: bool = False,
        show_board: bool = True,
        show_probabilities: bool = True,
        show_mcts_detail: bool = True,
        file_log: Optional[TextIO] = None,
    ):
        self.log_path = Path(log_path)
        self.engine_params = engine_params or {
            "time_budget_ms": 8000.0,
            "num_worlds": 7,
            "uct_constant": 0.5,
            "time_decay_gamma": 0.6,
            "max_actions_per_turn": 10,
        }
        self._engine_factory = create_engine("mcts", self.engine_params)
        self.poll_interval = poll_interval
        self.on_decision = on_decision
        self.presenter = DecisionPresenter(
            output, verbose,
            show_board=show_board,
            show_probabilities=show_probabilities,
            show_mcts_detail=show_mcts_detail,
            file_log=file_log,
        )
        self._display = TerminalDisplay(terminal=output, file_log=file_log)

        self._tracker = GameTracker()
        self._bridge = StateBridge()
        self._running = False
        self._last_turn = 0
        self._last_decision_signature: tuple | None = None
        self._last_replan_at = 0.0
        self._replan_cooldown_s = float(self.engine_params.get("replan_cooldown_s", 0.8))

        self._deck_reloader = None
        deck_codes_path = Path(log_path).parent.parent / "deck_codes.txt"
        if not deck_codes_path.exists():
            deck_codes_path = Path(__file__).resolve().parents[2] / "deck_codes.txt"
        if deck_codes_path.exists():
            from analysis.watcher.deck_hot_reloader import DeckHotReloader
            self._deck_reloader = DeckHotReloader(deck_codes_path)
            log.info(f"Deck hot-reloader watching: {deck_codes_path}")

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

            existing_lines = watcher.read_existing_content()
            bootstrap_lines = self._latest_unfinished_game_lines(existing_lines)
            log.info(f"Bootstrapping: {len(existing_lines)} total lines, {len(bootstrap_lines)} lines for latest game")

            if not bootstrap_lines and existing_lines:
                self._display.present_status("等待新游戏开始...")
            else:
                self._display.present_status(f"加载已有对局 ({len(bootstrap_lines)} 行)...")

            for line in bootstrap_lines:
                if not self._running:
                    break
                self._on_line(line, simulate=False)

            current_turn = self._tracker.get_current_turn()
            if current_turn > 0 and self._tracker.in_game:
                self._display.present_status(f"已加载至 Turn {current_turn}，等待实时更新...")
                self._last_turn = current_turn

            for line in watcher:
                if not self._running:
                    break
                self._on_line(line, simulate=True)
        except KeyboardInterrupt:
            log.info("Decision loop interrupted")
        except Exception as e:
            log.error(f"Error in decision loop: {e}", exc_info=True)
        finally:
            self.stop()
            watcher.close()

    def stop(self) -> None:
        self._running = False

    def _on_line(self, line: str, simulate: bool = True) -> None:
        """Process a single new line from the log.

        Args:
            line: Log line text
            simulate: If True, run search on turn_start. If False (bootstrap),
                      only collect state info without running search.
        """
        if self._deck_reloader is not None:
            self._deck_reloader.check_and_reload()

        event = self._tracker.feed_line(line)
        if event is None:
            return

        if event == "game_start":
            log.info("New game detected")
            self._last_turn = 0
            self._last_decision_signature = None
            self._display.present_status("新游戏开始!")
        elif event == "game_end":
            log.info("Game ended")
            self._last_turn = 0
            self._last_decision_signature = None
            self._display.present_status("游戏结束")
        elif event == "turn_start":
            current_turn = self._tracker.get_current_turn()
            if current_turn != self._last_turn and current_turn > 0:
                log.debug(f"Turn {current_turn} started")
                if simulate:
                    self._make_decision()
                else:
                    log.info(f"Bootstrap: loaded turn {current_turn} state")
                self._last_turn = current_turn
        elif event == "action":
            if simulate:
                self._maybe_replan_on_action()

    @staticmethod
    def _state_signature(state) -> tuple:
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
            log.warning("_build_state: export_entities returned None")
            return None
        player_index = self._detect_friendly_idx(game)
        state = self._bridge.convert(game, player_index=player_index)
        if state.turn_number == 0:
            log.warning(f"_build_state: turn_number=0, hero={state.hero}, hand={len(state.hand)}, board={len(state.board)}")
            return None
        log.debug(
            f"_build_state: turn={state.turn_number} hero_hp={state.hero.hp} "
            f"mana={state.mana.available}/{state.mana.max_mana} "
            f"hand={len(state.hand)} board={len(state.board)} "
            f"opp_hp={state.opponent.hero.hp} opp_board={len(state.opponent.board)}"
        )
        return state

    @staticmethod
    def _detect_friendly_idx(game) -> int:
        from hearthstone.enums import GameTag as HGameTag, Zone as HZone

        if not hasattr(game, 'players') or len(game.players) < 2:
            return 0

        visible = []
        for p in game.players:
            count = sum(
                1 for e in getattr(p, 'entities', [])
                if getattr(e, 'card_id', '') and
                   getattr(e, 'tags', {}).get(HGameTag.ZONE) == HZone.HAND
            )
            visible.append(count)

        return 1 if visible[1] > visible[0] else 0

    def _maybe_replan_on_action(self) -> None:
        current_turn = self._tracker.get_current_turn()
        if current_turn <= 0:
            return
        if current_turn != self._last_turn:
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
        state = self._build_state()
        if state is None:
            log.warning("Cannot export game state, skipping decision")
            return

        sig = self._state_signature(state)
        self._run_search_and_present(state, sig)
        self._last_replan_at = time.perf_counter()

    def _run_search_and_present(self, state, signature: tuple | None = None) -> None:
        load_scores_into_hand(state)

        opp_playstyle = _infer_opp_playstyle(state)
        state.opp_playstyle = opp_playstyle

        engine = self._engine_factory()

        start_time = time.perf_counter()
        raw_result = engine.search(state, opp_playstyle=opp_playstyle)
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        result = UnifiedSearchResult(raw_result)
        self.presenter.present(result, state, elapsed_ms)
        if signature is not None:
            self._last_decision_signature = signature

        self._log_evaluation_detail(result, state, elapsed_ms)

        if self.on_decision:
            try:
                self.on_decision(result, state)
            except Exception as e:
                log.error(f"Error in decision callback: {e}", exc_info=True)

    def _log_evaluation_detail(self, result, state, elapsed_ms: float) -> None:
        """Log structured evaluation details to file_log for research."""
        file_log = self._display._file_log
        if file_log is None:
            return

        try:
            from analysis.evaluators.bsv import (
                eval_tempo_v10, eval_value_v10, eval_survival_v10, _get_weights,
            )
            from analysis.evaluators.eval_logger import log_evaluation

            tempo = eval_tempo_v10(state)
            value = eval_value_v10(state)
            survival = eval_survival_v10(state)
            weights = _get_weights(state)
            final_score = result.best_fitness

            action_desc = ""
            if result.best_chromosome:
                action_desc = result.best_chromosome[0].describe(state)

            log_evaluation(
                file_log,
                state=state,
                action_desc=action_desc,
                tempo=tempo,
                value=value,
                survival=survival,
                final_score=final_score,
                axis_weights=weights,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            log.debug(f"Eval logging failed: {e}")

    @staticmethod
    def analyze_file(path: str | Path, output: TextIO = sys.stdout, *, engine: str = "mcts", **engine_kwargs) -> None:
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

                    state = bridge.convert(game, player_index=DecisionLoop._detect_friendly_idx(game))
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

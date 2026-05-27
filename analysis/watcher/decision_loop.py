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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, TextIO, Tuple

from analysis.watcher.log_watcher import LogWatcher
from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.card.abilities.definition import Action
from analysis.utils.bayesian_opponent import classify_card_playstyle

# ── 新引擎导入（替代已删除的 analysis.search.engine_adapter） ──
from analysis.engine.mcts_uct import MCTSUCT, MCTSConfig, MCTSResult
from analysis.engine.mcts_world_tracker import MCTSWorldTracker, TrackerConfig, TurnAnalysis
from analysis.engine.opponent_hand_mcts import OpponentHandMCTS, ObservedBehavior

log = logging.getLogger(__name__)


# ── SearchResult 兼容层 ──────────────────────────────────────
# TerminalDisplay / DecisionPresenter 期望的 SearchResult 接口，
# 将 MCTSResult + TurnAnalysis 包装成兼容对象。

@dataclass
class _ActionStat:
    """TerminalDisplay.present() 期望的动作统计条目。"""
    action: Action
    probability: float = 0.0
    visit_probability: float = 0.0
    win_rate: float = 0.0
    visit_count: int = 0


@dataclass
class _MCTSStats:
    """TerminalDisplay.present() 期望的 MCTS 统计信息。"""
    iterations: int = 0
    nodes_created: int = 0
    evaluations_done: int = 0
    world_count: int = 0
    time_used_ms: float = 0.0


@dataclass
class _DetailedLogEntry:
    """MCTS 详细日志条目。"""
    iter: int = 0
    nodes: int = 0
    evals: int = 0
    best_q: float = 0.0
    depth: int = 0

    def get(self, key: str, default=None):
        return getattr(self, key, default)


@dataclass
class _DetailedLog:
    """MCTS 详细日志容器。"""
    entries: List[_DetailedLogEntry] = field(default_factory=list)


@dataclass
class SearchResult:
    """兼容旧 SearchResult 接口的包装类。

    TerminalDisplay.present() 读取的属性：
      - best_fitness / fitness
      - best_sequence / best_chromosome
      - alternatives
      - action_probs
      - mcts_stats
      - mcts_detailed_log / detailed_log
    """

    best_fitness: float = 0.0
    fitness: float = 0.0
    best_sequence: List[Action] = field(default_factory=list)
    best_chromosome: List[Action] = field(default_factory=list)
    alternatives: List[Tuple[List[Action], float]] = field(default_factory=list)
    action_probs: List[_ActionStat] = field(default_factory=list)
    mcts_stats: Optional[_MCTSStats] = None
    mcts_detailed_log: Optional[_DetailedLog] = None
    detailed_log: Optional[_DetailedLog] = None

    # 对手手牌概率（新增）
    opponent_hand_probs: Dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mcts_result(
        cls,
        mcts_result: MCTSResult,
        turn_analysis: Optional[TurnAnalysis] = None,
        opponent_hand_probs: Optional[Dict[str, float]] = None,
    ) -> "SearchResult":
        """从 MCTSResult + TurnAnalysis 构建 SearchResult。"""

        # ── best_fitness / fitness ──
        root_q = 0.0
        root = mcts_result.root_node
        if root.visit_count > 0:
            root_q = root.total_reward / root.visit_count
        best_fitness = root_q
        if mcts_result.best_node and mcts_result.best_node.visit_count > 0:
            best_fitness = mcts_result.best_node.total_reward / mcts_result.best_node.visit_count

        # ── best_sequence / best_chromosome ──
        best_sequence = mcts_result.best_sequence
        if not best_sequence and mcts_result.best_action:
            best_sequence = [mcts_result.best_action]

        # ── alternatives ──
        alternatives: List[Tuple[List[Action], float]] = []
        if root.children:
            sorted_children = sorted(
                root.children,
                key=lambda c: c.visit_count,
                reverse=True,
            )
            for child in sorted_children[1:4]:  # 跳过第一名，取2-4名
                if child.action is not None and child.visit_count > 0:
                    child_fitness = child.total_reward / child.visit_count
                    child_seq = [child.action]
                    # 继续沿最高访问子节点提取动作
                    cur = child
                    for _ in range(4):
                        if not cur.children:
                            break
                        best_sub = max(cur.children, key=lambda c: c.visit_count)
                        if best_sub.action is not None:
                            child_seq.append(best_sub.action)
                        cur = best_sub
                    alternatives.append((child_seq, child_fitness))

        # ── action_probs ──
        action_probs: List[_ActionStat] = []
        if root.children:
            total_visits = sum(c.visit_count for c in root.children) or 1
            sorted_by_visits = sorted(
                root.children,
                key=lambda c: c.visit_count,
                reverse=True,
            )
            for child in sorted_by_visits[:10]:
                if child.action is None:
                    continue
                prob = child.visit_count / total_visits
                win_rate = (child.total_reward / child.visit_count) if child.visit_count > 0 else 0.0
                action_probs.append(_ActionStat(
                    action=child.action,
                    probability=prob,
                    visit_probability=prob,
                    win_rate=win_rate,
                    visit_count=child.visit_count,
                ))

        # ── mcts_stats ──
        stats = mcts_result.search_stats
        iterations = stats.get("iterations", 0) if isinstance(stats, dict) else 0
        nodes_created = mcts_result.num_nodes
        world_count = 0
        time_used_ms = 0.0
        if turn_analysis is not None:
            world_count = getattr(turn_analysis, "worlds_after_resample", 0) or len(
                getattr(getattr(turn_analysis, "snapshot", None), "worlds", [])
            )
            time_used_ms = turn_analysis.elapsed_s * 1000.0
        if isinstance(stats, dict):
            time_s = stats.get("time_s", 0.0)
            if time_s > 0:
                time_used_ms = time_s * 1000.0

        mcts_stats = _MCTSStats(
            iterations=iterations,
            nodes_created=nodes_created,
            evaluations_done=iterations,
            world_count=world_count,
            time_used_ms=time_used_ms,
        )

        # ── detailed_log ──
        detailed_log = None
        if isinstance(stats, dict) and stats.get("iterations", 0) > 0:
            entry = _DetailedLogEntry(
                iter=stats.get("iterations", 0),
                nodes=nodes_created,
                evals=stats.get("iterations", 0),
                best_q=best_fitness,
                depth=mcts_result.tree_depth,
            )
            detailed_log = _DetailedLog(entries=[entry])

        return cls(
            best_fitness=best_fitness,
            fitness=best_fitness,
            best_sequence=best_sequence,
            best_chromosome=best_sequence,
            alternatives=alternatives,
            action_probs=action_probs,
            mcts_stats=mcts_stats,
            mcts_detailed_log=detailed_log,
            detailed_log=detailed_log,
            opponent_hand_probs=opponent_hand_probs or {},
        )


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
        if "MINION" in str(c.get("card_type", "")):
            minion_count += 1
        else:
            spell_count += 1
        # Use centralized classify_card_playstyle instead of local keywords
        hint = classify_card_playstyle(cid)
        if hint is not None:
            return hint

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

    def present(self, result: SearchResult, state, elapsed_ms: float, *,
                show_board: bool = True, show_probabilities: bool = True,
                show_mcts_detail: bool = True) -> None:
        term_lines: list[str] = []
        file_lines: list[str] = []

        turn = getattr(state, "turn_number", "?")

        file_lines.append(f"┌─ Turn {turn} ─────────────────────────────")

        if show_board:
            self._build_board(state, term_lines, file_lines)

        file_lines.append("│")

        score = getattr(result, "best_fitness", getattr(result, "fitness", 0.0))
        decision_text = f"★ 最优操作 (Score: {score:+.2f} | {elapsed_ms:.0f}ms)"
        term_lines.append(decision_text)
        file_lines.append(f"│ {decision_text}")

        best_seq = getattr(result, "best_chromosome", getattr(result, "best_sequence", None))
        if best_seq:
            action_desc = best_seq[0].describe(state)
            term_lines.append(f">>> {action_desc}")
            file_lines.append(f"│ >>> {action_desc}")

        if result.alternatives:
            file_lines.append("│")
            file_lines.append("│ ○ 次优操作:")
            for rank, (alt_seq, fitness) in enumerate(result.alternatives, 1):
                if alt_seq:
                    gap = (getattr(result, 'best_fitness', 0) or getattr(result, 'fitness', 0)) - fitness
                    alt_desc = alt_seq[0].describe(state)
                    file_lines.append(f"│    {rank}. {alt_desc}  (score: {fitness:+.2f} | 差距: {gap:.2f})")
                    if rank <= 2:
                        term_lines.append(f"  {rank}. {alt_desc[:40]}")

        if show_probabilities and getattr(result, 'action_probs', None):
            file_lines.append("│")
            file_lines.append("│ [动作统计]")
            for stat in result.action_probs:
                desc = stat.action.describe(state)
                if len(desc) > 20:
                    desc = desc[:20]
                prob = getattr(stat, 'probability', getattr(stat, 'visit_probability', 0))
                bar = self._progress_bar(prob, 20)
                file_lines.append(
                    f"│ {desc:<20s} {bar} {prob * 100:5.1f}%  "
                    f"胜率: {stat.win_rate * 100:.1f}%  (visits: {stat.visit_count})"
                )

            stats = result.action_probs
            if stats:
                top3 = stats[:3]
                prob_parts = " | ".join(
                    f"{s.action.describe(state)[:15]}:{getattr(s, 'probability', getattr(s, 'visit_probability', 0)) * 100:.0f}%"
                    for s in top3
                )
                term_lines.append(f"[概率] {prob_parts}")

        if show_mcts_detail and getattr(result, 'mcts_stats', None) is not None:
            ms = result.mcts_stats
            iters = getattr(ms, "iterations", 0)
            nodes = getattr(ms, "nodes_created", 0)
            evals = getattr(ms, "evaluations_done", iters)
            worlds = getattr(ms, "world_count", 0)
            time_ms = getattr(ms, "time_used_ms", elapsed_ms)
            iter_per_s = int(iters / (time_ms / 1000.0)) if time_ms > 0 else 0

            mcts_summary = f"[MCTS] {iters}iters {nodes}nodes {worlds}worlds {iter_per_s}it/s"
            term_lines.append(mcts_summary)
            file_lines.append("│")
            file_lines.append(f"│ {mcts_summary}")

            detailed_log = getattr(result, 'mcts_detailed_log', None) or getattr(result, 'detailed_log', None)
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

        # ── 对手手牌概率展示（新增） ──
        opp_probs = getattr(result, 'opponent_hand_probs', None)
        if opp_probs:
            self._display_opponent_hand_probs(opp_probs, term_lines, file_lines)

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

    def _display_opponent_hand_probs(
        self,
        probs: Dict[str, float],
        term_lines: list[str],
        file_lines: list[str],
    ) -> None:
        """显示对手手牌概率预测结果。"""
        if not probs:
            return

        sorted_probs = sorted(probs.items(), key=lambda x: -x[1])[:8]

        file_lines.append("│")
        file_lines.append("│ [对手手牌推断]")

        # 尝试获取卡牌名
        card_names: Dict[str, str] = {}
        try:
            from analysis.card.data.card_data import get_db
            db = get_db()
            if db:
                for cid, _ in sorted_probs:
                    data = db.get_card(cid)
                    if data:
                        card_names[cid] = data.get("name", cid)
        except Exception:
            pass

        top_term_parts = []
        for cid, prob in sorted_probs[:5]:
            name = card_names.get(cid, cid[:12])
            bar = self._progress_bar(prob, 10)
            file_lines.append(f"│   {name:<16s} {bar} {prob * 100:5.1f}%")
            top_term_parts.append(f"{name}:{prob * 100:.0f}%")

        if top_term_parts:
            term_lines.append(f"[对手手牌] {' | '.join(top_term_parts)}")

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

    def present(self, result: SearchResult, state, elapsed_ms: float) -> None:
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
           b. MCTSUCT.search() finds best action sequence
           c. OpponentHandMCTS infers opponent hand probabilities
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
        latest_game_only: bool = False,
    ):
        self.log_path = Path(log_path)
        self.engine_params = engine_params or {
            "time_budget_ms": 1500.0,
            "num_worlds": 7,
            "uct_constant": 0.5,
            "time_decay_gamma": 0.6,
            "max_actions_per_turn": 10,
        }

        # ── MCTSUCT 搜索引擎（替代 GameEngine） ──
        mcts_config = MCTSConfig(
            exploration_constant=self.engine_params.get("uct_constant", 1.414),
            iterations=self.engine_params.get("iterations", 300),
            time_budget_ms=int(self.engine_params.get("time_budget_ms", 1500.0)),
            rollout_depth=self.engine_params.get("rollout_depth", 15),
            use_heuristic_rollout=True,
            verbose=verbose,
        )
        self._mcts = MCTSUCT(mcts_config)

        # ── MCTSWorldTracker（世界粒子滤波器） ──
        tracker_config = TrackerConfig(
            num_worlds=self.engine_params.get("num_worlds", 7),
            mcts_iterations=self.engine_params.get("iterations", 300),
            mcts_time_budget_ms=int(self.engine_params.get("time_budget_ms", 1500.0)),
            uct_exploration=self.engine_params.get("uct_constant", 1.414),
        )
        self._world_tracker = MCTSWorldTracker(tracker_config)

        # ── OpponentHandMCTS（对手手牌概率推断） ──
        opp_hand_budget = min(500.0, self.engine_params.get("time_budget_ms", 1500.0) * 0.15)
        self._opp_hand_mcts = OpponentHandMCTS(time_budget_ms=opp_hand_budget)

        # 对手手牌推断结果缓存
        self._last_opp_hand_probs: Dict[str, float] = {}

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
        self._last_mcts_turn: int | None = None  # last turn MCTS actually ran on
        self._last_decision_signature: tuple | None = None
        self._last_replan_at = 0.0
        self._replan_cooldown_s = float(self.engine_params.get("replan_cooldown_s", 0.8))
        self._latest_game_only = latest_game_only

        # GlobalTracker for cross-turn state (used when latest_game_only=True)
        self._global_tracker = None
        if latest_game_only:
            from analysis.watcher.global_tracker import GlobalTracker
            self._global_tracker = GlobalTracker()
            log.info("latest_game_only=True: GlobalTracker enabled for auto-reset on new game")

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
            self._last_mcts_turn = None
            self._last_decision_signature = None
            self._last_opp_hand_probs = {}
            # 重置 MCTSUCT（无状态，无需操作）和 WorldTracker + OpponentHandMCTS
            self._world_tracker.reset()
            self._opp_hand_mcts = OpponentHandMCTS(
                time_budget_ms=min(500.0, self.engine_params.get("time_budget_ms", 1500.0) * 0.15)
            )
            # Auto-reset GlobalTracker when latest_game_only=True
            if self._global_tracker is not None:
                self._global_tracker.on_game_start()
                log.debug("latest_game_only: GlobalTracker auto-reset on game_start")
            self._display.present_status("新游戏开始!")
        elif event == "game_end":
            log.info("Game ended")
            self._last_turn = 0
            self._last_mcts_turn = None
            self._last_decision_signature = None
            self._last_opp_hand_probs = {}
            # 重置状态
            self._world_tracker.reset()
            self._opp_hand_mcts = OpponentHandMCTS(
                time_budget_ms=min(500.0, self.engine_params.get("time_budget_ms", 1500.0) * 0.15)
            )
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

        current_turn = state.turn_number

        # Skip MCTS on opponent's turn — save compute for our turns only.
        # Hearthstone turns alternate: 1→Us, 2→Opp, 3→Us, 4→Opp...
        # If last MCTS was on turn N, the next *our* turn is N+2.
        if self._last_mcts_turn is not None:
            if current_turn <= self._last_mcts_turn:
                log.debug("Turn %d: already processed, skipping", current_turn)
                return
            if current_turn == self._last_mcts_turn + 1:
                log.debug("Turn %d: opponent turn, skipping MCTS", current_turn)
                return

        sig = self._state_signature(state)
        self._run_search_and_present(state, sig)
        self._last_mcts_turn = current_turn
        self._last_replan_at = time.perf_counter()

    def _run_search_and_present(self, state, signature: tuple | None = None) -> None:
        opp_playstyle = _infer_opp_playstyle(state)
        state.opp_playstyle = opp_playstyle

        # ── 1. MCTSUCT 搜索 ──
        start_time = time.perf_counter()
        mcts_result = self._mcts.search(state)
        mcts_elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        # ── 2. MCTSWorldTracker 回合分析（可选，增强世界多样性） ──
        turn_analysis: Optional[TurnAnalysis] = None
        try:
            turn_analysis = self._world_tracker.on_turn_start(state, state.turn_number)
        except Exception as e:
            log.debug(f"WorldTracker on_turn_start failed: {e}")

        # ── 3. OpponentHandMCTS 对手手牌推断 ──
        opp_hand_probs: Dict[str, float] = {}
        try:
            opp_hand_probs = self._run_opponent_hand_inference(state)
        except Exception as e:
            log.debug(f"Opponent hand inference failed: {e}")

        # ── 4. 组装 SearchResult 并展示 ──
        total_elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        result = SearchResult.from_mcts_result(
            mcts_result,
            turn_analysis=turn_analysis,
            opponent_hand_probs=opp_hand_probs if opp_hand_probs else None,
        )

        self.presenter.present(result, state, total_elapsed_ms)
        if signature is not None:
            self._last_decision_signature = signature

        self._log_evaluation_detail(result, state, total_elapsed_ms)

        if self.on_decision:
            try:
                self.on_decision(result, state)
            except Exception as e:
                log.error(f"Error in decision callback: {e}", exc_info=True)

    def _run_opponent_hand_inference(self, state) -> Dict[str, float]:
        """运行对手手牌概率推断（每回合执行一次）。

        策略：
        1. 从 state 中提取对手已知信息（手牌数、已打出卡牌等）
        2. 构建 ObservedBehavior
        3. 调用 OpponentHandMCTS.infer_hand_probabilities()
        4. 返回 {card_id: probability}
        """
        opp = state.opponent
        hand_size = opp.hand_count
        if hand_size <= 0:
            return {}

        # 构建贝叶斯状态（从 GlobalTracker 或简化推断获取）
        bayesian_state = self._get_bayesian_state(state)

        # 构建对手观测行为
        # 在回合开始时，我们还没有看到对手的出牌行为
        # 使用上一回合的信息作为参考
        observed = ObservedBehavior(
            played_cards=[],
            mana_spent=0,
            available_mana=getattr(state, 'mana', None) and getattr(state.mana, 'max_mana', 0) or 0,
            passed=False,
            turn=state.turn_number,
        )

        # 已打出的卡牌
        seen_cards: Dict[str, int] = {}
        known = getattr(opp, 'opp_known_cards', None) or []
        for card in known:
            c = card if isinstance(card, dict) else {"card_id": str(card)}
            cid = c.get("card_id", "")
            if cid:
                seen_cards[cid] = seen_cards.get(cid, 0) + 1

        # 衍生牌
        generated_cards: set = set()
        try:
            if self._global_tracker is not None:
                generated_cards = getattr(self._global_tracker, 'generated_cards', set()) or set()
        except Exception:
            pass

        deck_remaining = getattr(state, 'deck_remaining', 0)
        if deck_remaining == 0:
            # 估计：标准卡组30张，粗略估计对手剩余牌库
            deck_remaining = max(0, 30 - hand_size - sum(seen_cards.values()))

        # 时间预算：取总预算的一小部分，避免影响主搜索
        opp_hand_budget = min(500.0, self.engine_params.get("time_budget_ms", 1500.0) * 0.15)

        try:
            probs = self._opp_hand_mcts.infer_hand_probabilities(
                bayesian_state=bayesian_state,
                observed=observed,
                opponent_state=opp,
                our_board=state.board,
                our_hero=state.hero,
                seen_cards=seen_cards,
                generated_cards=generated_cards,
                hand_size=hand_size,
                time_budget_ms=opp_hand_budget,
            )
            self._last_opp_hand_probs = probs
            return probs
        except Exception as e:
            log.debug(f"OpponentHandMCTS inference failed: {e}")
            return self._last_opp_hand_probs

    def _get_bayesian_state(self, state) -> dict:
        """从当前状态获取贝叶斯卡组推断状态。

        优先使用 GlobalTracker 的数据，回退到简化推断。
        """
        if self._global_tracker is not None:
            try:
                bayesian = getattr(self._global_tracker, 'bayesian_state', None)
                if bayesian and isinstance(bayesian, dict) and bayesian.get("top_decks"):
                    return bayesian
            except Exception:
                pass

        # 简化回退：使用对手职业信息构建基本贝叶斯状态
        opp_class = ""
        try:
            opp_class = getattr(state.opponent.hero, 'hero_class', '') or ''
        except Exception:
            pass

        return {
            "top_decks": [],
            "opp_class": opp_class,
            "playstyle": getattr(state, 'opp_playstyle', 'unknown') or 'unknown',
        }

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
            final_score = result.fitness

            action_desc = ""
            if result.best_sequence:
                action_desc = result.best_sequence[0].describe(state)

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
    def analyze_file(path: str | Path, output: TextIO = sys.stdout, *, engine: str = "mcts", time_budget_ms: float = 1500.0, num_worlds: int = 7, **engine_kwargs) -> None:
        """One-shot: analyze an entire Power.log file and output decisions for each turn."""
        log_path = Path(path)
        if not log_path.exists():
            log.error(f"Log file not found: {log_path}")
            return

        log.info(f"Analyzing log file: {log_path}")

        tracker = GameTracker()
        bridge = StateBridge()

        # 使用 MCTSUCT 替代 GameEngine
        mcts_config = MCTSConfig(
            exploration_constant=engine_kwargs.get("uct_constant", 1.414),
            iterations=engine_kwargs.get("iterations", 300),
            time_budget_ms=int(time_budget_ms),
            rollout_depth=engine_kwargs.get("rollout_depth", 15),
            use_heuristic_rollout=True,
        )
        mcts_engine = MCTSUCT(mcts_config)

        # 对手手牌推断引擎
        opp_hand_mcts = OpponentHandMCTS(time_budget_ms=min(500.0, time_budget_ms * 0.15))

        # 世界追踪器
        tracker_config = TrackerConfig(
            num_worlds=num_worlds,
            mcts_time_budget_ms=int(time_budget_ms),
        )
        world_tracker = MCTSWorldTracker(tracker_config)

        events = tracker.load_file(log_path)
        log.info(f"Parsed {len(events)} events")

        last_turn = 0
        for event in events:
            if event == "game_start":
                last_turn = 0
                world_tracker.reset()
                opp_hand_mcts = OpponentHandMCTS(time_budget_ms=min(500.0, time_budget_ms * 0.15))
            elif event == "game_end":
                world_tracker.reset()
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

                    # MCTS 搜索
                    start_time = time.perf_counter()
                    mcts_result = mcts_engine.search(state)

                    # World tracker
                    turn_analysis = None
                    try:
                        turn_analysis = world_tracker.on_turn_start(state, state.turn_number)
                    except Exception:
                        pass

                    # 对手手牌推断
                    opp_hand_probs = {}
                    try:
                        bayesian_state = {"top_decks": [], "opp_class": ""}
                        seen_cards: Dict[str, int] = {}
                        opp = state.opponent
                        known = getattr(opp, 'opp_known_cards', None) or []
                        for card in known:
                            c = card if isinstance(card, dict) else {"card_id": str(card)}
                            cid = c.get("card_id", "")
                            if cid:
                                seen_cards[cid] = seen_cards.get(cid, 0) + 1

                        opp_hand_probs = opp_hand_mcts.infer_hand_probabilities(
                            bayesian_state=bayesian_state,
                            observed=ObservedBehavior(
                                turn=state.turn_number,
                                available_mana=getattr(state, 'mana', None) and getattr(state.mana, 'max_mana', 0) or 0,
                            ),
                            opponent_state=opp,
                            our_board=state.board,
                            our_hero=state.hero,
                            seen_cards=seen_cards,
                            hand_size=opp.hand_count,
                            time_budget_ms=min(500.0, time_budget_ms * 0.15),
                        )
                    except Exception:
                        pass

                    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                    result = SearchResult.from_mcts_result(
                        mcts_result,
                        turn_analysis=turn_analysis,
                        opponent_hand_probs=opp_hand_probs if opp_hand_probs else None,
                    )
                    presenter = DecisionPresenter(output=output)
                    presenter.present(result, state, elapsed_ms)

                    last_turn = current_turn

        log.info("File analysis complete")

"""game_replayer.py — Replay Power.log with RHEA decision analysis."""

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.search.rhea_engine import RHEAEngine, enumerate_legal_actions, Action


@dataclass
class TurnDecision:
    turn_number: int = 0
    player: str = ""
    player_turn: int = 0  # this player's Nth turn
    hero_hp: int = 0
    hero_armor: int = 0
    mana_available: int = 0
    mana_max: int = 0
    board_count: int = 0
    hand_count: int = 0
    opp_hero_hp: int = 0
    opp_board_count: int = 0
    legal_actions_count: int = 0
    action_breakdown: dict = field(default_factory=dict)  # {"PLAY": 5, "ATTACK": 12, ...}
    rhea_best_score: float = 0.0
    rhea_best_actions: list = field(default_factory=list)  # ["打出 xxx", "攻击 yyy"]
    rhea_generations: int = 0
    rhea_time_ms: float = 0.0
    error: str = ""


class GameReplayer:
    def __init__(
        self,
        log_dir: str = "logs",
        player_name: str = "湫然#51704",  # our player
        engine_params: dict = None,
    ):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)
        self.player_name = player_name
        self.engine_params = engine_params or {
            "pop_size": 20,
            "max_gens": 40,
            "time_limit": 200.0,
            "max_chromosome_length": 6,
        }

        self.tracker = GameTracker()
        self.bridge = StateBridge()
        self.decisions: list[TurnDecision] = []

        # Trackers for decision detection
        self._current_game_turn = 0
        self._current_step = None
        self._our_turn_count = 0
        self._first_player = 1  # 1 = 湫然, 2 = opponent
        self._processed_turns = set()  # Track which game turns we've analyzed

        # Setup loggers
        self._setup_loggers()

    def _setup_loggers(self):
        """Create separate log files for different concerns."""
        ts = time.strftime("%Y%m%d_%H%M%S")

        # Main replay log — everything
        self.log_main = logging.getLogger(f"replay.main.{ts}")
        fh = logging.FileHandler(self.log_dir / f"replay_{ts}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self.log_main.addHandler(fh)
        self.log_main.setLevel(logging.DEBUG)

        # Decisions log — per-turn analysis
        self.log_decisions = logging.getLogger(f"replay.decisions.{ts}")
        fh2 = logging.FileHandler(self.log_dir / f"decisions_{ts}.log", encoding="utf-8")
        fh2.setFormatter(logging.Formatter("%(message)s"))
        self.log_decisions.addHandler(fh2)
        self.log_decisions.setLevel(logging.INFO)

        # Errors log
        self.log_errors = logging.getLogger(f"replay.errors.{ts}")
        fh3 = logging.FileHandler(self.log_dir / f"errors_{ts}.log", encoding="utf-8")
        fh3.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        self.log_errors.addHandler(fh3)
        self.log_errors.setLevel(logging.WARNING)

    def replay_file(self, path: str) -> list[TurnDecision]:
        """Replay entire Power.log file, returning decisions for each of our turns."""
        self.log_main.info("=" * 70)
        self.log_main.info("🎮 开始回放 Power.log")
        self.log_main.info("=" * 70)
        self.log_main.info(f"📁 文件: {path}")
        self.log_main.info(f"🎮 我方: {self.player_name}")
        self.log_main.info(f"⚙️ RHEA: pop={self.engine_params['pop_size']}, "
                          f"gens={self.engine_params['max_gens']}, "
                          f"budget={self.engine_params['time_limit']}ms")
        self.log_main.info("=" * 70)

        self._first_player = 1  # reset
        self._current_game_turn = 0
        self._current_step = None
        self._our_turn_count = 0

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            self.log_main.info(f"📖 总行数: {len(lines)}")

            for line_num, raw_line in enumerate(lines, 1):
                line = raw_line.rstrip("\n")

                # Feed to tracker
                event_type = self.tracker.feed_line(line)

                # Parse TAG_CHANGE lines for decision detection
                turn_info = self._detect_turn_change(line)

                if event_type == "game_start":
                    self.log_main.info("🎮 游戏开始")
                    # Read a few more lines to get FIRST_PLAYER
                    for i in range(min(20, len(lines) - line_num)):
                        extra_line = lines[line_num + i].rstrip("\n")
                        self.tracker.feed_line(extra_line)
                        extra_turn_info = self._detect_turn_change(extra_line)
                        if extra_turn_info and extra_turn_info.get("tag") == "FIRST_PLAYER":
                            self._first_player = int(extra_turn_info.get("value", 1))
                            self.log_main.info(f"🏆 先手: {'湫然#51704' if self._first_player == 1 else 'UNKNOWN HUMAN PLAYER'}")
                            break

                elif event_type == "game_end":
                    self.log_main.info("🏁 游戏结束")

                # Check for turn/step changes
                if turn_info:
                    if turn_info.get("tag") == "TURN" and turn_info["entity"] == "GameEntity":
                        self._current_game_turn = int(turn_info["value"])
                        self.log_main.debug(f"📊 回合 {self._current_game_turn} 开始")

                    if turn_info.get("tag") == "STEP":
                        old_step = self._current_step
                        self._current_step = turn_info["value"]
                        if old_step != self._current_step:
                            self.log_main.debug(f"🔄 步骤变更: {old_step} → {self._current_step}")
                        # Store old_step for next iteration
                        old_step_for_detection = old_step

                # Detect MAIN_ACTION decision point - only when step transitions TO MAIN_ACTION
                if turn_info and turn_info.get("tag") == "STEP" and turn_info["value"] == "MAIN_ACTION":
                    # Check if we just transitioned to MAIN_ACTION (old_step was something else)
                    # This prevents detecting the duplicate MAIN_ACTION from PowerTaskList
                    if old_step_for_detection is not None and old_step_for_detection != "MAIN_ACTION":
                        # Check if we've already processed this turn
                        if self._current_game_turn not in self._processed_turns:
                            self._analyze_decision_point(self._current_game_turn, turn_info)
                            self._processed_turns.add(self._current_game_turn)

            self.log_main.info("=" * 70)
            self.log_main.info(f"✅ 回放完成: {len(self.decisions)} 个决策点")
            self.log_main.info("=" * 70)

        except Exception as e:
            self.log_errors.error(f"回放失败: {e}", exc_info=True)
            raise

        return self.decisions

    def _detect_turn_change(self, line: str) -> Optional[dict]:
        """Detect turn/step changes from a Power.log line.
        Returns dict with turn info or None."""
        # Match patterns like:
        # TAG_CHANGE Entity=GameEntity tag=TURN value=5
        # TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION
        # TAG_CHANGE Entity=湫然#51704 tag=TURN value=3
        match = re.match(
            r".*TAG_CHANGE\s+Entity=(\S+)\s+tag=(\w+)\s+value=(\S+)", line
        )
        if match:
            return {
                "entity": match.group(1),
                "tag": match.group(2),
                "value": match.group(3),
            }
        return None

    def _is_our_turn(self, game_turn: int) -> bool:
        """Check if this turn belongs to our player."""
        # Player 1 (湫然) goes on odd game turns: 1, 3, 5, 7, 9, 11, ...
        # Player 2 plays on even game turns: 2, 4, 6, 8, 10, ...
        # first_player tag tells us who is Player 1
        our_turn = False

        if self._first_player == 1:
            # Player 1 is 湫然 (our player)
            our_turn = (game_turn % 2 == 1)
        else:
            # Player 1 is opponent
            our_turn = (game_turn % 2 == 0)

        return our_turn

    def _analyze_decision_point(self, game_turn: int, step_info: dict):
        """At a decision point, extract state and run RHEA."""
        try:
            if not self._is_our_turn(game_turn):
                self.log_main.debug(f"⏭️ 跳过对手回合 {game_turn}")
                return

            self._our_turn_count += 1
            self.log_main.info("-" * 70)
            self.log_main.info(f"🎯 决策点: 回合 {game_turn} (湫然#51704 第{self._our_turn_count}回合)")
            self.log_main.info("-" * 70)

            # Export current state
            entities = self.tracker.export_entities()
            if entities is None:
                self.log_errors.error(f"无法导出实体 (回合 {game_turn})")
                return

            # Convert to game state
            game_state = self.bridge.convert(entities, player_index=0)

            # Get basic stats
            hero_hp = game_state.hero.hp
            hero_armor = game_state.hero.armor
            mana_available = game_state.mana.available
            mana_max = game_state.mana.max_mana
            board_count = len(game_state.board)
            hand_count = len(game_state.hand)
            opp_hero_hp = game_state.opponent.hero.hp
            opp_board_count = len(game_state.opponent.board)

            self.log_main.info(f"📊 状态: 英雄 HP={hero_hp}/{30} 护甲={hero_armor} | "
                             f"法力 {mana_available}/{mana_max} | "
                             f"场面 {board_count}随从 | 手牌 {hand_count}张")
            self.log_main.info(f"📊 对手: HP={opp_hero_hp} | 场面 {opp_board_count}随从")

            # Enumerate legal actions
            legal_actions = enumerate_legal_actions(game_state)

            # Count action types
            action_breakdown = {}
            for action in legal_actions:
                action_breakdown[action.action_type] = action_breakdown.get(action.action_type, 0) + 1

            self.log_main.info(f"⚖️ 合法动作: {len(legal_actions)} 个 {action_breakdown}")

            # Build action descriptions
            action_descriptions = []
            for i, action in enumerate(legal_actions[:20]):  # limit to first 20
                desc = action.describe(game_state)
                action_descriptions.append(f"  {i+1:2d}. {desc}")

            # Show RHEA search result
            self.log_main.info("")
            self.log_main.info("🔍 运行 RHEA 分析...")
            t0 = time.perf_counter()

            try:
                rhea_engine = RHEAEngine(**self.engine_params)
                search_result = rhea_engine.search(game_state)

                t1 = time.perf_counter()
                rhea_time_ms = (t1 - t0) * 1000.0

                # Log decision details
                self.log_decisions.info("=" * 70)
                self.log_decisions.info(f"回合 {game_turn} (湫然#51704 第{self._our_turn_count}回合)")
                self.log_decisions.info("=" * 70)
                self.log_decisions.info(f"状态: 英雄 HP={hero_hp}/{30} 护甲={hero_armor} | "
                                      f"法力 {mana_available}/{mana_max} | "
                                      f"场面 {board_count}随从 | 手牌 {hand_count}张")
                self.log_decisions.info(f"对手: HP={opp_hero_hp} | 场面 {opp_board_count}随从")
                self.log_decisions.info(f"合法动作: {len(legal_actions)} 个 {action_breakdown}")

                for desc in action_descriptions:
                    self.log_decisions.info(desc)

                self.log_decisions.info("")
                self.log_decisions.info(f"RHEA 搜索: {rhea_time_ms:.1f}ms, {search_result.generations_run} 代")
                self.log_decisions.info(f"最佳适应度: {search_result.best_fitness:+.2f}")

                # Show best actions
                self.log_decisions.info("")
                self.log_decisions.info("最佳序列:")
                for i, action in enumerate(search_result.best_chromosome):
                    self.log_decisions.info(f"  {i+1}. {action.describe(game_state)}")

                self.log_decisions.info("=" * 70)

                # Store decision
                decision = TurnDecision(
                    turn_number=game_turn,
                    player=self.player_name,
                    player_turn=self._our_turn_count,
                    hero_hp=hero_hp,
                    hero_armor=hero_armor,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    board_count=board_count,
                    hand_count=hand_count,
                    opp_hero_hp=opp_hero_hp,
                    opp_board_count=opp_board_count,
                    legal_actions_count=len(legal_actions),
                    action_breakdown=action_breakdown,
                    rhea_best_score=search_result.best_fitness,
                    rhea_best_actions=[action.describe(game_state) for action in search_result.best_chromosome],
                    rhea_generations=search_result.generations_run,
                    rhea_time_ms=rhea_time_ms,
                    error="",
                )
                self.decisions.append(decision)

            except Exception as e:
                self.log_errors.error(f"RHEA 搜索失败: {e}", exc_info=True)
                self.decisions.append(TurnDecision(
                    turn_number=game_turn,
                    player=self.player_name,
                    player_turn=self._our_turn_count,
                    hero_hp=hero_hp,
                    hero_armor=hero_armor,
                    mana_available=mana_available,
                    mana_max=mana_max,
                    board_count=board_count,
                    hand_count=hand_count,
                    opp_hero_hp=opp_hero_hp,
                    opp_board_count=opp_board_count,
                    legal_actions_count=len(legal_actions),
                    action_breakdown=action_breakdown,
                    rhea_best_score=0.0,
                    rhea_best_actions=[],
                    rhea_generations=0,
                    rhea_time_ms=0.0,
                    error=str(e),
                ))

        except Exception as e:
            self.log_errors.error(f"分析回合 {game_turn} 时出错: {e}", exc_info=True)

    def _save_summary(self):
        """Save game_summary.json with all decisions."""
        ts = time.strftime("%Y%m%d_%H%M%S")
        summary_path = self.log_dir / f"game_summary_{ts}.json"

        summary = {
            "player_name": self.player_name,
            "num_decisions": len(self.decisions),
            "decisions": [asdict(d) for d in self.decisions],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        self.log_main.info(f"💾 保存摘要: {summary_path}")
        return summary_path

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_with_tracker.py — 使用 LogMonitor 路径逐行回放 Power.log

基于 CoreLogMonitor.load_existing_log() 的逐行处理机制，
在每回合结束后捕获游戏状态快照并输出回放报告。

两种模式:
  1. 基本模式: 每回合输出手牌/牌库/场面/已知卡牌的摘要
  2. --predict 模式: 每回合额外运行 HandPredictor（MCTS 手牌推断）

用法:
    python scripts/replay_with_tracker.py /path/to/Power.log
    python scripts/replay_with_tracker.py /path/to/Power.log --predict
    python scripts/replay_with_tracker.py /path/to/Power.log --verbose
"""

from __future__ import annotations

import argparse
import io
import logging
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Optional, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)


def _resolve_power_log_path(raw_path: str) -> Path:
    """解析 Power.log 路径（支持文件、目录、模糊匹配）。"""
    p = Path(raw_path).expanduser().resolve()
    if p.is_file():
        return p
    if p.is_dir():
        direct = p / "Power.log"
        if direct.is_file():
            return direct
        candidates = sorted(
            c for c in p.glob("*.log") if "power" in c.name.lower() and c.is_file()
        )
        if candidates:
            return candidates[0]
        raise FileNotFoundError(f"目录中未找到 Power.log: {p}")
    raise FileNotFoundError(f"路径不存在: {p}")


class TurnSnapshot:
    """单回合游戏状态快照。"""

    def __init__(self, turn: int, state: dict):
        self.turn = turn
        self.player_class = state.get("player_class", "?")
        self.opp_class = state.get("opp_class", "?")
        self.is_first = state.get("is_first_player")
        self.available_mana = state.get("available_mana", 0)

        # 计数
        self.opp_hand_count = state.get("opp_hand_count", 0)
        self.opp_deck_count = state.get("opp_deck_count", 0)
        self.opp_initial_deck = state.get("opp_initial_deck_size", 30)
        self.player_hand_count = state.get("player_hand_count", 0)
        self.player_deck_count = state.get("player_deck_count", 0)

        # 场面
        self.opp_board_count = len(state.get("opp_board_minions", []))
        self.player_board_count = len(state.get("player_board_minions", []))
        self.opp_weapon = state.get("opp_weapon", "")
        self.opp_secrets = list(state.get("opp_secrets", []))

        # 已知信息
        known = state.get("known_cards", [])
        self.known_card_ids = [k["card_id"] for k in known]
        self.known_card_details = known

        hand = state.get("known_hand", [])
        self.known_hand_ids = [h[1] for h in hand if len(h) > 1]

        self.graveyard = [g["card_id"] for g in state.get("graveyard", [])]
        self.player_hand = state.get("player_hand_cards", [])

        # 神秘/武器
        self.opp_locations = list(state.get("opp_locations", []))

        # 贝叶斯摘要
        bayesian = state.get("bayesian", {})
        top_archetypes = bayesian.get("top_archetypes", [])
        self.top_archetypes = top_archetypes[:3] if top_archetypes else []

        # 牌组分类统计
        breakdown = state.get("card_breakdown", {})
        self.deck_cards = breakdown.get("deck_cards", 0)
        self.generated_cards = breakdown.get("generated_cards", 0)
        self.uncertain_cards = breakdown.get("uncertain_cards", 0)

        # 手牌预测（由 ReplayEngine._capture_snapshot 注入）
        self.prediction_result = None

    def __repr__(self) -> str:
        parts = [
            f"回合 {self.turn:2d}",
            f"对手 手牌={self.opp_hand_count} 牌库={self.opp_deck_count} 场面={self.opp_board_count}",
            f"我方 手牌={self.player_hand_count} 牌库={self.player_deck_count} 场面={self.player_board_count}",
            f"已知={len(self.known_card_ids)}",
        ]
        # 如果有预测结果，追加推理摘要
        if self.prediction_result is not None:
            high = [
                f"{p.name}({p.probability:.0%})"
                for p in self.prediction_result.hand_predictions
                if p.probability >= 0.7 and p.source != "possible"
            ][:4]
            if high:
                parts.append(f"推测={', '.join(high)}")
        return " | ".join(parts)

    def format_predictions(self) -> str:
        """格式化的推测手牌信息。"""
        if self.prediction_result is None:
            return ""
        pred = self.prediction_result
        lines = []

        # 卡组推断
        if pred.archetype_name:
            arch_conf = pred.archetype_confidence
            lines.append(
                f"  卡组推断: {pred.archetype_name} (confidence={arch_conf:.0%})"
            )

        # 按概率排序的手牌预测
        hps = sorted(
            [p for p in pred.hand_predictions if p.probability > 0.01],
            key=lambda p: (-p.probability, p.cost),
        )

        if hps:
            # 分层展示
            confirmed = [p for p in hps if p.probability >= 1.0]
            likely = [p for p in hps if 0.5 <= p.probability < 1.0]
            possible = [p for p in hps if 0.1 <= p.probability < 0.5]
            fringe = [p for p in hps if 0.01 < p.probability < 0.1]

            if confirmed:
                names = [f"{p.name}" for p in confirmed[:6]]
                lines.append(f"  确认手牌({len(confirmed)}): {', '.join(names)}")

            if likely:
                names = [
                    f"{p.name}({p.probability:.0%})" for p in likely[:8]
                ]
                lines.append(f"  很可能在手牌({len(likely)}): {', '.join(names)}")

            if possible:
                names = [
                    f"{p.name}({p.probability:.0%})" for p in possible[:6]
                ]
                lines.append(f"  可能在手牌({len(possible)}): {', '.join(names)}")

            if fringe and self.turn >= 0:
                # fringe 只在 verbose 或晚期回合展示
                names = [f"{p.name}({p.probability:.0%})" for p in fringe[:4]]
                lines.append(f"  低概率({len(fringe)}): {', '.join(names)}")

        # MCTS 预测（如果有）
        if pred.mcts_applied and pred.mcts_top_predictions:
            mcts_strs = [
                f"{cid}({prob:.0%})"
                for cid, prob in pred.mcts_top_predictions[:5]
            ]
            lines.append(f"  MCTS推测: {', '.join(mcts_strs)}")

        # 多卡组加权预测摘要
        if pred.multi_deck_predictions:
            arch_summary = " | ".join(
                f"{name}({wt:.0%})"
                for name, wt, _ in pred.multi_deck_predictions[:3]
            )
            lines.append(f"  多卡组加权: {arch_summary}")

        return "\n".join(lines)

    def format_detailed(self) -> str:
        """返回详细的多行字符串。"""
        lines = []
        lines.append(f"── 回合 {self.turn} ──")
        lines.append(f"  职业: {self.player_class} vs {self.opp_class}")
        lines.append(f"  法力: {self.available_mana}")
        lines.append(
            f"  对手: 手牌{self.opp_hand_count} 牌库{self.opp_deck_count}/{self.opp_initial_deck}"
            f" 场面{self.opp_board_count}"
        )
        lines.append(
            f"  我方: 手牌{self.player_hand_count} 牌库{self.player_deck_count}"
            f" 场面{self.player_board_count}"
        )

        if self.opp_weapon:
            lines.append(f"  对手武器: {self.opp_weapon}")
        if self.opp_secrets:
            lines.append(f"  对手秘笈: {', '.join(self.opp_secrets)}")
        if self.opp_locations:
            lines.append(f"  对手地标: {', '.join(self.opp_locations)}")

        if self.known_hand_ids:
            lines.append(f"  对手已知手牌({len(self.known_hand_ids)}): {', '.join(self.known_hand_ids[:8])}")
            if len(self.known_hand_ids) > 8:
                lines[-1] += " ..."

        if self.known_card_ids:
            lines.append(f"  对手已知卡牌({len(self.known_card_ids)}): {', '.join(self.known_card_ids[:10])}")
            if len(self.known_card_ids) > 10:
                lines[-1] += " ..."

        if self.graveyard:
            lines.append(f"  对手墓地({len(self.graveyard)}): {', '.join(self.graveyard[:8])}")
            if len(self.graveyard) > 8:
                lines[-1] += " ..."

        if self.player_hand:
            lines.append(f"  我方手牌({len(self.player_hand)}): {', '.join(self.player_hand[:8])}")
            if len(self.player_hand) > 8:
                lines[-1] += " ..."

        if self.top_archetypes:
            arch_strs = [f"{a.get('name','?')}({a.get('probability',0)*100:.0f}%)" for a in self.top_archetypes]
            lines.append(f"  最可能卡组: {' | '.join(arch_strs)}")

        if self.deck_cards or self.generated_cards:
            lines.append(f"  对手牌组构成: 牌库卡{self.deck_cards} 衍生卡{self.generated_cards} 不确定{self.uncertain_cards}")

        return "\n".join(lines)


class ReplayEngine:
    """回放引擎：使用 CoreLogMonitor 逐行处理 Power.log。"""

    def __init__(
        self,
        verbose: bool = False,
        use_predictor: bool = False,
    ):
        self.verbose = verbose
        self.use_predictor = use_predictor
        self.snapshots: List[TurnSnapshot] = []
        self.monitor: Optional[CoreLogMonitor] = None
        self._predictor = None
        self._game_count = 0
        self._current_turn = 0
        self._had_turn_zero = False  # 标记是否已捕获 turn 0

        if use_predictor:
            try:
                from tracker.hand_predictor import HandPredictor
                self._predictor = HandPredictor()
            except Exception as e:
                logger.warning("HandPredictor 初始化失败: %s", e)
                self.use_predictor = False

    def _on_game_started(self, info: dict):
        self._game_count += 1
        self._current_turn = 0
        self._had_turn_zero = False
        print(f"\n{'='*60}")
        print(f"游戏 #{self._game_count}: {info.get('player_class','?')} vs {info.get('opp_class','?')}")
        print(f"  我方 controller={info.get('our_controller')} 对手 controller={info.get('opp_controller')}")
        print(f"{'='*60}")

    def _on_turn_changed(self, turn: int):
        self._current_turn = turn
        # 在 turn=0 时不捕获（还在 mulligan 阶段，状态不完整）
        # 首次 game_start 后捕获 turn=0 的快照作为初始状态
        if turn == 0 and not self._had_turn_zero:
            self._had_turn_zero = True
            self._capture_snapshot()
        elif turn > 0:
            self._capture_snapshot()

    def _capture_snapshot(self):
        """捕获当前游戏状态快照。"""
        if self.monitor is None:
            return
        state = self.monitor.build_state_dict()
        snapshot = TurnSnapshot(self._current_turn, state)

        # 可选：运行 HandPredictor
        # 注意：抑制 library 代码中的 print() debug 输出（如 simulation._validate）
        if self.use_predictor and self._predictor:
            try:
                _buf = io.StringIO()
                with redirect_stdout(_buf):
                    prediction = self._predictor.predict(state)
                snapshot.prediction_result = prediction
            except Exception as e:
                logger.debug("预测失败: %s", e)

        self.snapshots.append(snapshot)

        # 输出
        if self.verbose:
            print(snapshot.format_detailed())
            pred_str = snapshot.format_predictions()
            if pred_str:
                print(pred_str)
            print()  # 空行分隔
        else:
            print(str(snapshot))

    def _on_game_ended(self):
        print(f"  游戏结束")

    def replay(self, log_path: Path) -> List[TurnSnapshot]:
        """执行回放。

        Args:
            log_path: Power.log 文件路径

        Returns:
            每回合状态快照列表
        """
        from tracker.log_monitor import CoreLogMonitor

        print(f"回放文件: {log_path}")
        file_size = log_path.stat().st_size
        print(f"文件大小: {file_size:,} bytes")
        print()

        self.monitor = CoreLogMonitor()

        # 挂载回调
        self.monitor.on_game_started = self._on_game_started
        self.monitor.on_turn_changed = self._on_turn_changed
        self.monitor.on_game_ended = self._on_game_ended

        # 逐行处理
        start = time.time()
        try:
            self.monitor.load_existing_log(str(log_path))
        except Exception as e:
            logger.error("回放失败: %s", e)
            raise

        elapsed = time.time() - start
        print(f"\n处理耗时: {elapsed:.2f}s")

        # 如果处理速度特别慢，提示
        lines_estimate = file_size / 80  # 每行约80字节
        if elapsed > 0:
            rate = lines_estimate / elapsed
            print(f"处理速度: ~{rate:.0f} 行/秒")

        return self.snapshots

    def print_summary(self):
        """输出全局回放摘要。"""
        if not self.snapshots:
            print("无回放数据。")
            return

        total_games = self._game_count
        print(f"\n{'='*60}")
        print(f"回放摘要")
        print(f"{'='*60}")
        print(f"  对局数: {total_games}")
        print(f"  回合快照: {len(self.snapshots)}")

        if total_games > 0:
            # 最后一局的最终状态
            final = self.snapshots[-1]
            print(f"  最终回合: {final.turn}")
            print(f"  最终对手手牌: {final.opp_hand_count}")
            print(f"  已知对手卡牌总数: {len(final.known_card_ids)}")

            # 如果使用了预测，输出推测手牌数量排名变化
            if self.use_predictor:
                # 第一回合和最后一回合的高概率推测对比
                first_with_pred = next(
                    (s for s in self.snapshots if s.prediction_result is not None),
                    None,
                )
                if first_with_pred and final.prediction_result:
                    f_pred = first_with_pred.prediction_result
                    l_pred = final.prediction_result
                    print(f"  推测高质量(≥70%): 第{first_with_pred.turn}回合 {sum(1 for p in f_pred.hand_predictions if p.probability >= 0.7)}张"
                          f" → 第{final.turn}回合 {sum(1 for p in l_pred.hand_predictions if p.probability >= 0.7)}张")


def main():
    ap = argparse.ArgumentParser(
        description="炉石对局离线回放 (LogMonitor 逐行路径)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s Power.log
  %(prog)s Power.log --verbose
  %(prog)s Power.log --predict
  %(prog)s Hearthstone_2025-01-01_12-00-00/
        """,
    )
    ap.add_argument("path", nargs="?", help="Power.log 文件路径或目录")
    ap.add_argument("--analyze", metavar="PATH", help="同 path（兼容）")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细模式：每回合输出完整状态")
    ap.add_argument("--predict", "-p", action="store_true", help="每回合运行 HandPredictor (MCTS 手牌推断)")
    ap.add_argument("--quiet", "-q", action="store_true", help="静默模式：只输出摘要")

    args = ap.parse_args()
    path_str = args.analyze or args.path
    if not path_str:
        ap.error("请指定 Power.log 路径")

    try:
        log_path = _resolve_power_log_path(path_str)
    except FileNotFoundError as e:
        ap.error(str(e))

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    engine = ReplayEngine(
        verbose=args.verbose,
        use_predictor=args.predict,
    )

    snapshots = engine.replay(log_path)
    engine.print_summary()

    return 0


if __name__ == "__main__":
    sys.exit(main())

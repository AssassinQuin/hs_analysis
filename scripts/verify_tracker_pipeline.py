#!/usr/bin/env python3
"""verify_tracker_pipeline.py — 逐行验证 tracker 日志处理流水线

读取 Power.log，逐行喂入 CoreLogMonitor，驱动 GameStateManager +
HandPredictor，验证完整追踪流水线是否正常。

功能:
  - 逐行/批处理 Power.log
  - 检测并报告: game_start / game_end / turn_change
  - 在每局结束后输出完整状态摘要
  - 验证手牌预测引擎可运行
  - 报告任何处理错误

用法:
  python scripts/verify_tracker_pipeline.py
  python scripts/verify_tracker_pipeline.py --log /path/to/Power.log
  python scripts/verify_tracker_pipeline.py --delay 0.001
  python scripts/verify_tracker_pipeline.py --verbose
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional, List

# 确保项目根在 sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tracker.log_monitor import CoreLogMonitor
from tracker.game_state import GameStateManager
from tracker.hand_predictor import HandPredictor


# ── 验证结果追踪 ──────────────────────────────────────────────

class VerificationState:
    """追踪验证过程中的事件和状态。"""

    def __init__(self):
        self.game_count = 0
        self.turn_count = 0
        self.action_count = 0
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.line_count = 0
        self.total_bytes = 0
        self.start_time = 0.0
        self.games: list[dict] = []  # 每局汇总

        # 当前局状态（跨回调累积）
        self._cur_game: Optional[dict] = None

    def start_game(self, info: dict):
        self.game_count += 1
        self._cur_game = {
            "num": self.game_count,
            "player_class": info.get("player_class", "?"),
            "opp_class": info.get("opp_class", "?"),
            "turns": 0,
            "actions": 0,
            "final_state": None,
            "errors": [],
        }
        print(f"\n{'='*60}")
        print(f"🎮 游戏 #{self.game_count} 开始 — 我方:{self._cur_game['player_class']}  vs  "
              f"对方:{self._cur_game['opp_class']}")
        print(f"{'='*60}")

    def end_game(self):
        if self._cur_game:
            print(f"\n{'='*60}")
            print(f"🏁 游戏 #{self._cur_game['num']} 结束"
                  f" ({self._cur_game['turns']} 回合)")
            print(f"{'='*60}")
            self.games.append(self._cur_game)
            self._cur_game = None

    def turn_change(self, turn: int):
        self.turn_count += 1
        if self._cur_game:
            self._cur_game["turns"] += 1
        print(f"\n--- 回合 {turn} ---")

    def state_update(self, state_dict: dict):
        self.action_count += 1
        if self._cur_game:
            self._cur_game["actions"] += 1

    def add_error(self, msg: str):
        self.errors.append(msg)
        if self._cur_game:
            self._cur_game["errors"].append(msg)
        print(f"  ❌ {msg}")

    def add_warning(self, msg: str):
        self.warnings.append(msg)
        print(f"  ⚠ {msg}")

    def set_final_state(self, state_dict: dict):
        if self._cur_game:
            self._cur_game["final_state"] = state_dict


# ── 状态打印 ──────────────────────────────────────────────────

def print_state_summary(state_dict: dict):
    """打印一行游戏状态摘要。"""
    turn = state_dict.get("turn", "?")
    p_class = state_dict.get("player_class_en", "?")
    o_class = state_dict.get("opp_class_en", "?")
    p_hand = state_dict.get("player_hand_count", "?")
    p_deck = state_dict.get("player_deck_count", "?")
    o_hand = state_dict.get("opp_hand_count", "?")
    o_deck = state_dict.get("opp_deck_count", "?")
    p_board = len(state_dict.get("player_board_minions", []))
    o_board = len(state_dict.get("opp_board_minions", []))
    known = len(state_dict.get("known_cards", []))
    bayes = "B" if state_dict.get("bayesian") else " "

    print(f"  T{turn:>2} [{p_class:>4} vs {o_class:<4}]  "
          f"我方 H:{p_hand} D:{p_deck} B:{p_board}  "
          f"对方 H:{o_hand} D:{o_deck} B:{o_board}  "
          f"已知{known}张 [{bayes}]")


def print_final_state(state_dict: dict):
    """打印最终游戏状态详情。"""
    if not state_dict:
        print("    (空状态)")
        return

    keys = [
        "in_game", "turn", "step",
        "player_class_en", "opp_class_en",
        "player_hand_count", "player_deck_count", "player_initial_deck_size",
        "opp_hand_count", "opp_deck_count", "opp_initial_deck_size",
        "available_mana", "is_first_player", "coin_used",
    ]
    for k in keys:
        print(f"    {k}: {state_dict.get(k, 'N/A')}")

    print(f"    player_board_minions: {len(state_dict.get('player_board_minions', []))} 个")
    print(f"    opp_board_minions:    {len(state_dict.get('opp_board_minions', []))} 个")
    print(f"    known_cards:          {len(state_dict.get('known_cards', []))} 张已知")
    print(f"    revealed_hand_cards:  {len(state_dict.get('reveal_info', {}).get('revealed_hand_cards', []))} 张揭示")
    print(f"    opp_secrets:          {len(state_dict.get('opp_secrets', []))} 个奥秘")
    print(f"    opp_weapon:           {state_dict.get('opp_weapon', '无')}")
    print(f"    player_weapon:        {state_dict.get('player_weapon', '无')}")

    bayes = state_dict.get("bayesian") or {}
    if bayes:
        print(f"    archetype: {bayes.get('archetype_name', '?')} "
              f"(置信度 {bayes.get('deck_confidence', 0):.1%})")
        top = bayes.get("top_decks", [])
        for i, (deck_id, name, prob) in enumerate(top[:3]):
            print(f"      #{i+1}: {name} ({prob:.1%})")


# ── 调试补丁（在 --verbose 下启用） ──────────────────────────

_INSTRUMENTED: List[int] = []

def _patch_monitor(monitor, verbose: bool = False):
    """给 CoreLogMonitor 打补丁，注入详细的调试日志（仅 --verbose 时输出）。"""
    if not verbose:
        return
    global _INSTRUMENTED
    gid = id(monitor)
    if gid in _INSTRUMENTED:
        return
    _INSTRUMENTED.append(gid)

    _orig_detect = monitor._detect_my_idx
    _detect_call_count = [0]

    def _instrumented_detect(self, players, saved_our_controller=0):
        _detect_call_count[0] += 1
        result = _orig_detect(players, saved_our_controller)
        if _detect_call_count[0] <= 5:
            names = [getattr(p, 'name', '?') for p in players[:2]]
            pids = []
            for p in players[:2]:
                try:
                    pids.append(p.tags.get(GameTag.PLAYER_ID, 0))
                except:
                    pids.append(-1)
            ctrls = []
            for p in players[:2]:
                try:
                    ctrls.append(p.tags.get(GameTag.CONTROLLER, 0))
                except:
                    ctrls.append(-1)
            print(f"  🔍 _detect_my_idx #{_detect_call_count[0]} → idx={result}, "
                  f"players=[({names[0]}, pid={pids[0]}, ctrl={ctrls[0]}), "
                  f"({names[1]}, pid={pids[1]}, ctrl={ctrls[1]})], "
                  f"saved_ctrl={saved_our_controller}, known_name={self._our_known_name!r}")
        return result

    import types
    monitor._detect_my_idx = types.MethodType(_instrumented_detect, monitor)


# ── 处理管线 ──────────────────────────────────────────────────

def verify(log_path: Path, delay: float = 0, verbose: bool = False):
    """运行验证。"""
    vs = VerificationState()
    vs.total_bytes = log_path.stat().st_size
    vs.start_time = time.time()

    # ── 创建组件 ──────────────────────────────────────────────
    monitor = CoreLogMonitor(log_path=str(log_path))
    _patch_monitor(monitor, verbose=verbose)
    gsm = GameStateManager()
    hp = HandPredictor()

    # ── 设置回调 ──────────────────────────────────────────────
    def on_game_started(info):
        vs.start_game(info)
        gsm.reset()

    def on_game_ended():
        vs.end_game()

    def on_turn_changed(turn):
        vs.turn_change(turn)

    def on_state_updated(state_dict):
        vs.state_update(state_dict)
        try:
            prediction = hp.predict(state_dict)
            gsm.update(state_dict, prediction)
            final_state = gsm.state

            if vs._cur_game:
                vs._cur_game["final_state"] = state_dict

            # 每局只输出有限次数的状态摘要（避免刷屏）
            if vs._cur_game and vs._cur_game["actions"] <= 3:
                print_state_summary(state_dict)
            elif verbose and delay > 0:
                print_state_summary(state_dict)

        except Exception as e:
            vs.add_error(f"状态更新/预测处理异常: {e}")
            import traceback
            traceback.print_exc()

    def on_log_error(msg):
        vs.add_warning(f"日志解析: {msg}")

    monitor.on_game_started = on_game_started
    monitor.on_game_ended = on_game_ended
    monitor.on_turn_changed = on_turn_changed
    monitor.on_state_updated = on_state_updated
    monitor.on_log_error = on_log_error

    # ── 逐行处理 ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"🚀 开始验证: {log_path}")
    print(f"   大小: {log_path.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"   延迟: {'无 (批处理)' if delay <= 0 else f'{delay*1000:.1f}ms/行'}")
    print(f"{'='*60}\n")

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            if delay > 0:
                # 逐行模式
                for line in f:
                    stripped = line.rstrip("\n").rstrip("\r")
                    vs.line_count += 1
                    monitor._process_lines([stripped])
                    if delay > 0:
                        time.sleep(delay)
                    if verbose and vs.line_count % 5000 == 0:
                        print(f"  ... 已处理 {vs.line_count} 行")
            else:
                # 批处理模式（使用 load_existing_log）
                monitor.load_existing_log(str(log_path))
                vs.line_count = sum(1 for _ in open(log_path, "rb"))

    except KeyboardInterrupt:
        print("\n\n⚠ 用户中断")
    except Exception as e:
        vs.add_error(f"处理异常: {e}")
        import traceback
        traceback.print_exc()

    elapsed = time.time() - vs.start_time

    # ── 最终状态 ──────────────────────────────────────────────
    try:
        final_dict = monitor.build_state_dict()
    except Exception as e:
        vs.add_error(f"build_state_dict 失败: {e}")
        final_dict = {}

    # ── 报告 ──────────────────────────────────────────────────
    print(f"\n\n{'='*60}")
    print("📊 验证报告")
    print(f"{'='*60}")
    print(f"  日志文件:     {log_path}")
    print(f"  处理行数:     {vs.line_count:,}")
    print(f"  文件大小:     {vs.total_bytes / 1024 / 1024:.1f} MB")
    print(f"  耗时:         {elapsed:.2f}s"
          + (f" ({vs.line_count/elapsed:.0f} 行/秒)" if elapsed > 1 else ""))

    print(f"  ──────────────────────────────────")
    print(f"  游戏场次:     {vs.game_count}")
    print(f"  回合切换:     {vs.turn_count}")
    print(f"  状态更新:     {vs.action_count}")
    print(f"  错误数:       {len(vs.errors)}")
    print(f"  警告数:       {len(vs.warnings)}")

    # 每局详情
    for g in vs.games:
        turns = g["turns"]
        errs = len(g["errors"])
        status = "✅" if errs == 0 else "⚠"
        print(f"  {status} 游戏 #{g['num']}: "
              f"{g['player_class']} vs {g['opp_class']}, "
              f"{turns} 回合, {g['actions']} 次状态更新"
              + (f", {errs} 个错误" if errs else ""))

    # 警告详情
    if vs.warnings:
        print(f"\n  ⚠ 警告列表:")
        for w in vs.warnings:
            print(f"    - {w}")

    # 错误详情
    if vs.errors:
        print(f"\n  ❌ 错误列表:")
        for e in vs.errors:
            print(f"    - {e}")

    # 最终状态
    print(f"\n  ── 最终游戏状态 ──")
    print_final_state(final_dict)

    # 结论
    print(f"\n{'='*60}")
    if vs.errors:
        print(f"⚠ 验证完成: {len(vs.errors)} 个错误, {len(vs.warnings)} 个警告")
    elif vs.warnings:
        print(f"✅ 验证通过: {len(vs.warnings)} 个非致命警告")
    elif vs.game_count > 0:
        print(f"✅ 验证通过: {vs.game_count} 局处理正常，无错误")
    else:
        print("⚠ 未检测到游戏（日志格式不符或无游戏数据）")

    return len(vs.errors)


def main():
    parser = argparse.ArgumentParser(
        description="逐行验证 tracker 日志处理流水线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python scripts/verify_tracker_pipeline.py
  python scripts/verify_tracker_pipeline.py --log /path/to/Power.log
  python scripts/verify_tracker_pipeline.py --delay 0.001
  python scripts/verify_tracker_pipeline.py --verbose
""",
    )
    parser.add_argument("--log", type=str, default=None,
                        help="Power.log 路径（默认项目根目录下的 Power.log）")
    parser.add_argument("--delay", type=float, default=0,
                        help="每行处理后的延时（秒），如 0.001 = 1ms")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="输出更详细信息")
    args = parser.parse_args()

    # 日志路径
    if args.log:
        log_path = Path(args.log)
    else:
        log_path = project_root / "Power.log"

    if not log_path.exists():
        print(f"❌ 错误: 未找到日志文件 {log_path}")
        print("   请指定 --log /path/to/Power.log")
        sys.exit(1)

    # 配置日志（仅警告以上，简化输出）
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s: %(message)s")

    exit_code = verify(log_path, delay=args.delay, verbose=args.verbose)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

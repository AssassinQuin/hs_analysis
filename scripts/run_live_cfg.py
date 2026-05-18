#!/usr/bin/env python3
"""run_live_cfg.py - Start live decision loop from cfg file."""

from __future__ import annotations

import argparse
import configparser
import logging
import re
import sys
from datetime import datetime
from pathlib import Path


def _split_paths(raw: str) -> list[str]:
    items: list[str] = []
    for chunk in raw.replace(";", "\n").replace(",", "\n").splitlines():
        value = chunk.strip()
        if value:
            items.append(value)
    return items


def _resolve_paths(paths: list[str]) -> list[Path]:
    resolved: list[Path] = []
    for p in paths:
        resolved.append(Path(p).expanduser())
    return resolved


def _parse_session_datetime(path: Path) -> datetime | None:
    m = re.match(r"^Hearthstone_(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})", path.name)
    if not m:
        return None
    try:
        y, mo, d, h, mi, s = (int(x) for x in m.groups())
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _resolve_candidate_to_log(candidate: Path) -> Path | None:
    if not candidate.exists():
        return None

    if candidate.is_file():
        return candidate if candidate.name.lower() == "power.log" else None

    if not candidate.is_dir():
        return None

    direct_power = candidate / "Power.log"
    if direct_power.exists() and direct_power.is_file():
        return direct_power

    scored: list[tuple[datetime, Path]] = []
    for child in candidate.iterdir():
        if not child.is_dir():
            continue
        p = child / "Power.log"
        if not p.exists() or not p.is_file():
            continue
        ts = _parse_session_datetime(child)
        if ts is None:
            ts = datetime.fromtimestamp(p.stat().st_mtime)
        scored.append((ts, p))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _has_unfinished_game(log_path: Path) -> bool:
    try:
        from analysis.watcher.game_tracker import GameTracker
    except Exception:
        return False

    try:
        tracker = GameTracker()
        tracker.load_file(str(log_path))
        return tracker.in_game
    except Exception:
        return False


def _pick_recent_unfinished_log(candidate: Path) -> Path | None:
    if not candidate.exists() or not candidate.is_dir():
        return None

    scored: list[tuple[datetime, Path]] = []
    for child in candidate.iterdir():
        if not child.is_dir():
            continue
        p = child / "Power.log"
        if not p.exists() or not p.is_file():
            continue
        ts = _parse_session_datetime(child)
        if ts is None:
            ts = datetime.fromtimestamp(p.stat().st_mtime)
        scored.append((ts, p))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    for _, p in scored:
        if _has_unfinished_game(p):
            return p
    return None


def _pick_log_path(candidates: list[Path]) -> Path:
    for p in candidates:
        unfinished = _pick_recent_unfinished_log(p)
        if unfinished is not None:
            return unfinished
        resolved = _resolve_candidate_to_log(p)
        if resolved is not None:
            return resolved
    if candidates:
        return _resolve_candidate_to_log(candidates[0]) or candidates[0]
    raise ValueError("cfg 中未配置 log.paths")


def _load_cfg(cfg_path: Path) -> dict:
    cp = configparser.ConfigParser(interpolation=None)
    with cfg_path.open("r", encoding="utf-8") as f:
        cp.read_file(f)

    paths_raw = cp.get("log", "paths", fallback="").strip()
    path_items = _split_paths(paths_raw)
    candidates = _resolve_paths(path_items)

    return {
        "mode": cp.get("run", "mode", fallback="live").strip().lower(),
        "analyze_path": cp.get("run", "analyze_path", fallback="").strip(),
        "log_paths": candidates,
        "poll_interval": cp.getfloat("log", "poll_interval", fallback=0.05),
        "verbose": cp.getboolean("output", "verbose", fallback=False),
        "save_to_file": cp.getboolean("output", "save_to_file", fallback=True),
        "file_path": cp.get("output", "file_path", fallback="").strip(),
        "show_board": cp.getboolean("output", "show_board", fallback=True),
        "show_probabilities": cp.getboolean("output", "show_probabilities", fallback=True),
        "show_mcts_detail": cp.getboolean("output", "show_mcts_detail", fallback=True),
        "engine_params": {
            "time_budget_ms": cp.getfloat("engine", "time_budget_ms", fallback=8000.0),
            "num_worlds": cp.getint("engine", "num_worlds", fallback=7),
            "uct_constant": cp.getfloat("engine", "uct_constant", fallback=0.5),
            "time_decay_gamma": cp.getfloat("engine", "time_decay_gamma", fallback=0.6),
            "min_step_budget_ms": cp.getfloat("engine", "min_step_budget_ms", fallback=300.0),
            "max_actions_per_turn": cp.getint("engine", "max_actions_per_turn", fallback=10),
            "replan_cooldown_s": cp.getfloat("engine", "replan_cooldown_s", fallback=0.8),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="通过 cfg 启动 Hearthstone 实时决策")
    ap.add_argument("--cfg", default="cfg/live.cfg", help="配置文件路径 (default: cfg/live.cfg)")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    cfg_path = Path(args.cfg).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = (repo_root / cfg_path).resolve()

    if not cfg_path.exists():
        print(f"[ERROR] 配置文件不存在: {cfg_path}")
        return 1

    cfg = _load_cfg(cfg_path)
    level = logging.DEBUG if cfg["verbose"] else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from analysis.watcher.decision_loop import DecisionLoop

    mode = cfg["mode"]
    engine_params = cfg["engine_params"]
    poll_interval = cfg["poll_interval"]
    save_to_file = cfg["save_to_file"]
    configured_file_path = cfg["file_path"]

    output_file = None
    output_stream = sys.stdout

    if save_to_file:
        if configured_file_path:
            live_log_path = Path(configured_file_path).expanduser()
            if not live_log_path.is_absolute():
                live_log_path = (repo_root / live_log_path).resolve()
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            live_log_path = (repo_root / "logs" / f"live_{ts}.log").resolve()

        live_log_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = live_log_path.open("a", encoding="utf-8", buffering=1)
        print(f"[INFO] 日志落盘: {live_log_path}")

    if mode == "analyze":
        analyze_path = cfg["analyze_path"]
        if not analyze_path:
            print("[ERROR] mode=analyze 时必须配置 run.analyze_path")
            if output_file is not None:
                output_file.close()
            return 1
        print(f"[INFO] 离线分析: {analyze_path}")
        DecisionLoop.analyze_file(analyze_path, output=output_stream, **engine_params)
        if output_file is not None:
            output_file.close()
        return 0

    if mode != "live":
        print(f"[ERROR] 不支持的 run.mode: {mode} (支持 live/analyze)")
        if output_file is not None:
            output_file.close()
        return 1

    log_path = _pick_log_path(cfg["log_paths"])
    if (not log_path.exists()) or (not log_path.is_file()) or (log_path.name.lower() != "power.log"):
        print(f"[ERROR] 未解析到可用的 Power.log: {log_path}")
        print("[ERROR] 请在 cfg 的 log.paths 填写 Power.log 文件路径，或填写包含会话目录的 Logs 根目录")
        if output_file is not None:
            output_file.close()
        return 1

    mcts_info = (f"budget={engine_params.get('time_budget_ms', 8000)}ms, "
                 f"worlds={engine_params.get('num_worlds', 7)}, "
                 f"uct_c={engine_params.get('uct_constant', 0.5)}")
    print(f"[INFO] 配置: {cfg_path}")
    print(f"[INFO] 监听: {log_path}")
    print(f"[INFO] MCTS: {mcts_info}")
    print("[INFO] 按 Ctrl+C 停止\n")

    loop = DecisionLoop(
        log_path,
        engine_params=engine_params,
        poll_interval=poll_interval,
        output=output_stream,
        verbose=cfg["verbose"],
        show_board=cfg["show_board"],
        show_probabilities=cfg["show_probabilities"],
        show_mcts_detail=cfg["show_mcts_detail"],
        file_log=output_file,
    )
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n[INFO] 已停止")
    finally:
        if output_file is not None:
            output_file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

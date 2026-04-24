#!/usr/bin/env python3
"""run_live.py — Start the Hearthstone live decision assistant.

Usage:
    # Read from cfg/live.cfg (default):
    python scripts/run_live.py

    # Watch specific log file (overrides cfg):
    python scripts/run_live.py /path/to/Power.log

    # Analyze existing log file (offline mode):
    python scripts/run_live.py --analyze /path/to/Power.log

    # With verbose output:
    python scripts/run_live.py -v

    # Custom engine parameters (override cfg):
    python scripts/run_live.py --pop-size 50 --gens 100 --time-limit 500
"""

import argparse
import configparser
import logging
import sys
from pathlib import Path


def _load_cfg_paths(cfg_path: Path) -> list[Path]:
    cp = configparser.ConfigParser(interpolation=None)
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            cp.read_file(f)
    except FileNotFoundError:
        return []

    raw = cp.get("log", "paths", fallback="").strip()
    paths: list[Path] = []
    for chunk in raw.replace(";", "\n").replace(",", "\n").splitlines():
        v = chunk.strip()
        if v:
            paths.append(Path(v).expanduser())
    return paths


def _resolve_log_path(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if not p.exists():
            continue
        if p.is_file() and p.name.lower() == "power.log":
            return p
        if p.is_dir():
            direct = p / "Power.log"
            if direct.exists() and direct.is_file():
                return direct
            import re
            from datetime import datetime
            scored: list[tuple[datetime, Path]] = []
            for child in p.iterdir():
                if not child.is_dir():
                    continue
                pf = child / "Power.log"
                if not pf.exists() or not pf.is_file():
                    continue
                m = re.match(r"^Hearthstone_(\d{4})_(\d{2})_(\d{2})_(\d{2})_(\d{2})_(\d{2})", child.name)
                ts = None
                if m:
                    try:
                        y, mo, d, h, mi, s = (int(x) for x in m.groups())
                        ts = datetime(y, mo, d, h, mi, s)
                    except ValueError:
                        pass
                if ts is None:
                    ts = datetime.fromtimestamp(pf.stat().st_mtime)
                scored.append((ts, pf))
            if scored:
                scored.sort(key=lambda item: item[0], reverse=True)
                return scored[0][1]
    return None


def main():
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    parser = argparse.ArgumentParser(
        description="Hearthstone 实时决策助手 — Live decision assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "log_path", nargs="?",
        help="Power.log 文件路径 (默认从 cfg/live.cfg 读取)",
    )
    parser.add_argument(
        "--cfg", default="cfg/live.cfg",
        help="配置文件路径 (default: cfg/live.cfg)",
    )
    parser.add_argument(
        "--analyze", "-a",
        help="离线分析模式：分析指定的完整 Power.log 文件",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )
    parser.add_argument(
        "--pop-size", type=int, default=None,
        help="RHEA 种群大小 (default: from cfg or 30)",
    )
    parser.add_argument(
        "--gens", type=int, default=None,
        help="RHEA 最大迭代 (default: from cfg or 80)",
    )
    parser.add_argument(
        "--time-limit", type=float, default=None,
        help="RHEA 时间预算 ms (default: from cfg or 300)",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=None,
        help="文件轮询间隔秒 (default: from cfg or 0.05)",
    )
    parser.add_argument(
        "--engine", choices=["rhea", "mcts"], default="rhea",
        help="搜索引擎 (default: rhea)",
    )

    args = parser.parse_args()

    cfg_path = Path(args.cfg).expanduser()
    if not cfg_path.is_absolute():
        cfg_path = (repo_root / cfg_path).resolve()

    cp = configparser.ConfigParser(interpolation=None)
    cfg_loaded = False
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                cp.read_file(f)
            cfg_loaded = True
        except Exception:
            pass

    poll_interval = args.poll_interval
    if poll_interval is None:
        poll_interval = cp.getfloat("log", "poll_interval", fallback=0.05) if cfg_loaded else 0.05

    pop_size = args.pop_size
    if pop_size is None:
        pop_size = cp.getint("engine", "pop_size", fallback=30) if cfg_loaded else 30

    max_gens = args.gens
    if max_gens is None:
        max_gens = cp.getint("engine", "max_gens", fallback=80) if cfg_loaded else 80

    time_limit = args.time_limit
    if time_limit is None:
        time_limit = cp.getfloat("engine", "time_limit", fallback=300.0) if cfg_loaded else 300.0

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from analysis.watcher.decision_loop import DecisionLoop

    engine_params = {
        "pop_size": pop_size,
        "max_gens": max_gens,
        "time_limit": time_limit,
        "max_chromosome_length": cp.getint("engine", "max_chromosome_length", fallback=8) if cfg_loaded else 8,
        "cross_turn": cp.getboolean("engine", "cross_turn", fallback=True) if cfg_loaded else True,
    }

    # Merge MCTS-specific config when engine is mcts
    if args.engine == "mcts":
        engine_params.update({
            "time_budget_ms": cp.getfloat("engine", "time_budget_ms", fallback=8000.0) if cfg_loaded else 8000.0,
            "num_worlds": cp.getint("engine", "num_worlds", fallback=7) if cfg_loaded else 7,
        })

    if args.analyze:
        print(f"离线分析模式: {args.analyze} (engine={args.engine})")
        DecisionLoop.analyze_file(
            args.analyze,
            engine=args.engine,
            **engine_params,
        )
    else:
        log_path = None
        if args.log_path:
            log_path = Path(args.log_path).expanduser()
        elif cfg_loaded:
            cfg_paths = _load_cfg_paths(cfg_path)
            log_path = _resolve_log_path(cfg_paths)

        if log_path is None:
            print("未找到 Power.log，请在 cfg/live.cfg 的 log.paths 中配置路径，或手动指定")
            print("   用法: python scripts/run_live.py /path/to/Power.log")
            sys.exit(1)

        engine_label = args.engine.upper()
        print(f"监听 Power.log: {log_path}")
        print(f"{engine_label} 参数: pop={pop_size}, gens={max_gens}, budget={time_limit}ms")
        if cfg_loaded:
            print(f"使用配置: {cfg_path}")
        print("按 Ctrl+C 停止\n")

        loop = DecisionLoop(
            log_path,
            engine=args.engine,
            engine_params=engine_params,
            poll_interval=poll_interval,
            verbose=args.verbose,
        )

        try:
            loop.run()
        except KeyboardInterrupt:
            print("\n已停止")


if __name__ == "__main__":
    main()

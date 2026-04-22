#!/usr/bin/env python3
"""run_live.py — Start the Hearthstone live decision assistant.

Usage:
    # Watch default Power.log location (macOS):
    python scripts/run_live.py

    # Watch specific log file:
    python scripts/run_live.py /path/to/Power.log

    # Analyze existing log file (offline mode):
    python scripts/run_live.py --analyze /path/to/Power.log

    # With verbose output:
    python scripts/run_live.py -v

    # Custom engine parameters:
    python scripts/run_live.py --pop-size 50 --gens 100 --time-limit 500
"""

import argparse
import logging
import sys
from pathlib import Path


# Default Power.log locations by platform
DEFAULT_PATHS = {
    "darwin": "~/Library/Logs/Unity/Player.log",  # macOS (not real HS log)
    "win32": "~/AppData/Local/Blizzard/Hearthstone/Logs/Power.log",
    "linux": "~/.local/share/Steam/steamapps/compatdata/2346580/pfx/drive_c/users/steamuser/AppData/Local/Blizzard/Hearthstone/Logs/Power.log",
}


def find_default_log() -> Path:
    """Try to find Power.log at platform-default location."""
    import platform
    system = platform.system().lower()
    # Map platform.system() to our keys
    key = {"darwin": "darwin", "windows": "win32", "linux": "linux"}.get(system, "linux")
    path = Path(DEFAULT_PATHS.get(key, "")).expanduser()
    if path.exists():
        return path

    # Also check common Windows paths via Wine/Proton
    candidates = [
        Path("/Users") / "/*/AppData/Local/Blizzard/Hearthstone/Logs/Power.log",
        Path("C:/Users/*/AppData/Local/Blizzard/Hearthstone/Logs/Power.log"),
    ]
    for pattern in candidates:
        matches = list(Path("/").glob(str(pattern))) if "/" in str(pattern) else []
        if matches:
            return matches[0]

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Hearthstone 实时决策助手 — Live decision assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "log_path", nargs="?",
        help="Power.log 文件路径 (默认自动检测)",
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
        "--pop-size", type=int, default=30,
        help="RHEA 种群大小 (default: 30)",
    )
    parser.add_argument(
        "--gens", type=int, default=80,
        help="RHEA 最大迭代 (default: 80)",
    )
    parser.add_argument(
        "--time-limit", type=float, default=300.0,
        help="RHEA 时间预算 ms (default: 300)",
    )
    parser.add_argument(
        "--poll-interval", type=float, default=0.05,
        help="文件轮询间隔秒 (default: 0.05)",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from analysis.watcher.decision_loop import DecisionLoop

    engine_params = {
        "pop_size": args.pop_size,
        "max_gens": args.gens,
        "time_limit": args.time_limit,
        "max_chromosome_length": 8,
    }

    if args.analyze:
        # Offline mode
        print(f"📂 离线分析模式: {args.analyze}")
        DecisionLoop.analyze_file(
            args.analyze,
            **engine_params,
        )
    else:
        # Live mode
        log_path = args.log_path or find_default_log()
        if log_path is None:
            print("❌ 未找到 Power.log，请手动指定路径")
            print("   用法: python scripts/run_live.py /path/to/Power.log")
            sys.exit(1)

        print(f"🔍 监听 Power.log: {log_path}")
        print(f"⚙️  RHEA 参数: pop={args.pop_size}, gens={args.gens}, budget={args.time_limit}ms")
        print("按 Ctrl+C 停止\n")

        loop = DecisionLoop(
            log_path,
            engine_params=engine_params,
            poll_interval=args.poll_interval,
            verbose=args.verbose,
        )

        try:
            loop.run()
        except KeyboardInterrupt:
            print("\n👋 已停止")


if __name__ == "__main__":
    main()

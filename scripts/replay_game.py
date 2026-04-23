#!/usr/bin/env python3
"""replay_game.py — Replay Power.log and analyze decisions.

Usage:
    python scripts/replay_game.py Power.log
    python scripts/replay_game.py Power.log --player "湫然#51704"
    python scripts/replay_game.py Power.log --pop-size 30 --gens 50
"""
import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Power.log 回放分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s Power.log
  %(prog)s Power.log --player "湫然#51704"
  %(prog)s Power.log --pop-size 30 --gens 50 --time-limit 300
        """
    )
    parser.add_argument("log_path", help="Power.log 文件路径")
    parser.add_argument("--player", default="", help="我方玩家名（留空则自动检测）")
    parser.add_argument("--log-dir", default="logs", help="日志输出目录")
    parser.add_argument("--pop-size", type=int, default=20,
                       help="RHEA 种群大小 (默认: 20)")
    parser.add_argument("--gens", type=int, default=40,
                       help="RHEA 最大代数 (默认: 40)")
    parser.add_argument("--time-limit", type=float, default=200.0,
                       help="RHEA 时间限制 (ms) (默认: 200)")
    args = parser.parse_args()

    if not Path(args.log_path).exists():
        print(f"❌ 文件不存在: {args.log_path}")
        sys.exit(1)

    from analysis.watcher.game_replayer import GameReplayer

    print()
    print("=" * 70)
    print("🎮 Power.log 回放分析")
    print("=" * 70)
    print(f"📂 文件: {args.log_path}")
    print(f"🎮 我方: {args.player}")
    print(f"⚙️ RHEA 参数:")
    print(f"   种群大小: {args.pop_size}")
    print(f"   最大代数: {args.gens}")
    print(f"   时间预算: {args.time_limit}ms")
    print(f"📝 日志目录: {args.log_dir}/")
    print("=" * 70)
    print()

    replayer = GameReplayer(
        log_dir=args.log_dir,
        player_name=args.player,
        engine_params={
            "pop_size": args.pop_size,
            "max_gens": args.gens,
            "time_limit": args.time_limit,
            "max_chromosome_length": 6,
        },
    )

    decisions = replayer.replay_file(args.log_path)

    print()
    print("=" * 70)
    print("📊 回放结果汇总")
    print("=" * 70)
    print(f"✅ 总计决策点: {len(decisions)}")

    for d in decisions:
        status = "✓" if not d.error else f"✗ {d.error}"
        p = d.player_name[:10] if d.player_name else "?"
        print(f"  回合{d.turn_number:2d} ({p:>10}): "
              f"HP={d.hero_hp} mana={d.mana_available}/{d.mana_max} "
              f"board={d.board_count} hand={d.hand_count} | "
              f"actions={d.legal_actions_count} "
              f"RHEA={d.rhea_time_ms:5.0f}ms → {status}")

    # Save summary
    summary_path = replayer._save_summary()
    print()
    print(f"💾 完整结果已保存到: {summary_path}")

    print()
    print("=" * 70)
    print("🎉 回放完成!")
    print("=" * 70)


if __name__ == "__main__":
    main()

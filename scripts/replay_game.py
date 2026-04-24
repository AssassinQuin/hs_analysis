#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_game.py — 离线回放入口脚本

使用 hslog 库解析 Power.log，逐包回放并分析每回合决策。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is importable when executing as `python scripts/replay_game.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _resolve_power_log_path(raw_path: str) -> str:
    p = Path(raw_path).expanduser().resolve()
    if p.is_file():
        return str(p)
    if p.is_dir():
        direct = p / "Power.log"
        if direct.is_file():
            return str(direct)
        # Fallback: tolerate non-standard naming like `power_*.log`.
        candidates = sorted(
            c for c in p.glob("*.log") if "power" in c.name.lower() and c.is_file()
        )
        if candidates:
            return str(candidates[0])
        raise FileNotFoundError(f"目录中未找到 Power.log: {p}")
    raise FileNotFoundError(f"路径不存在或不可读: {p}")


def main():
    from analysis.watcher.packet_replayer import PacketReplayer

    ap = argparse.ArgumentParser(description="炉石对局离线回放分析 (hslog)")
    ap.add_argument("path", nargs="?", help="Power.log 文件路径")
    ap.add_argument("--analyze", metavar="PATH", help="分析指定 Power.log 文件")
    ap.add_argument(
        "--rhea-time", type=int, default=300, help="RHEA 搜索时间预算 (ms), 默认 300"
    )
    ap.add_argument("--rhea-pop", type=int, default=30, help="RHEA 种群大小, 默认 30")
    ap.add_argument("--dir", default="logs", help="日志输出目录, 默认 logs/")
    ap.add_argument("--verbose", "-v", action="store_true", help="在终端显示详细输出")
    args = ap.parse_args()

    path = args.analyze or args.path
    if not path:
        ap.error("请指定 Power.log 路径 (位置参数或 --analyze)")
    try:
        path = _resolve_power_log_path(path)
    except FileNotFoundError as exc:
        ap.error(str(exc))

    replayer = PacketReplayer(
        log_dir=args.dir,
        engine_params={
            "time_limit": args.rhea_time / 1000.0,
            "pop_size": args.rhea_pop,
        },
    )

    print(f"正在回放: {path}")
    print(f"RHEA参数: 时间={args.rhea_time}ms 种群={args.rhea_pop}")
    print("=" * 60)

    decisions = replayer.replay_file(path)

    if not decisions:
        print("未找到决策点。")
        return

    our_decisions = [d for d in decisions if d.is_our_turn]
    print(f"\n共 {len(decisions)} 个决策点 (我方 {len(our_decisions)} 回合)")
    print("=" * 60)

    if args.verbose:
        for d in decisions:
            side = "我方" if d.is_our_turn else "对手"
            print(f"\n--- 回合 {d.turn_number} [{side}] ({d.hero_class}) ---")
            print(f"  英雄: {d.hero_hp}HP + {d.hero_armor}甲")
            if d.is_our_turn:
                print(f"  法力: {d.mana_available}/{d.mana_max}")
                print(
                    f"  手牌({d.hand_count}): {', '.join(d.hand_cards[:5])}{'...' if len(d.hand_cards) > 5 else ''}"
                )
                if d.rhea_best_actions:
                    print(f"  RHEA建议: {' → '.join(d.rhea_best_actions[:5])}")
            else:
                print(
                    f"  对手: 手牌{d.opp_hand_count} 场面{d.opp_board_count} 牌库{d.opp_deck_remaining}"
                )
            if d.summary_lines:
                for line in d.summary_lines:
                    print(f"  {line}")
            if d.effect_pool_reports:
                print("  效果池分析:")
                for rep in d.effect_pool_reports:
                    print(
                        f"    [{rep.get('effect_kind', '未知')}] {rep.get('card_name', '未知')} | "
                        f"池大小={rep.get('pool_size', 0)} | 约束={rep.get('constraint', '')}"
                    )
                    for line in rep.get("probability_lines", []):
                        print(f"      {line}")
                    pool_cards = rep.get("pool_cards", [])
                    if pool_cards:
                        print(f"      完整池: {', '.join(pool_cards)}")

    total = len(our_decisions)
    lethal = sum(1 for d in our_decisions if d.lethal_available)
    avg_score = sum(d.rhea_best_score for d in our_decisions) / max(total, 1)

    print(f"\n{'=' * 60}")
    print("回放统计:")
    print(f"  总决策: {total}")
    print(f"  致命可用: {lethal}")
    print(f"  RHEA 平均分: {avg_score:.2f}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()

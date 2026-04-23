# -*- coding: utf-8 -*-
"""
炉石传说游戏日志解析入口脚本

Usage:
    python -m scripts.parse_game_log <log_dir>
    python -m scripts.parse_game_log  # 默认使用最新的日志目录
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.config import PROJECT_ROOT
from analysis.models.game_record import DeckInfo
from analysis.watcher.game_log_parser import parse_log_dir, parse_decks_log
from analysis.utils.hero_class import class_to_cn


def print_deck_info(deck: DeckInfo, indent: str = "  ") -> None:
    print(f"{indent}[{deck.name}] (ID: {deck.deck_id})")
    print(f"{indent}  职业: {deck.hero_class_cn} ({deck.hero_class})")
    print(f"{indent}  卡牌数: {deck.card_count}")
    print(f"{indent}  --- 卡组列表 ---")
    for c in deck.cards_sorted_by_cost:
        cnt = f"x{c.count}" if c.count > 1 else "  "
        cls = ""
        if c.cardClass and c.cardClass not in ("NEUTRAL", deck.hero_class, ""):
            cls = f" [{c.cardClass}]"
        print(f"{indent}  {c.cost:>2}费 {cnt} {c.name}{cls}")


def print_player_cards(player, indent: str = "  ") -> None:
    cards = player.played_cards
    if not cards:
        print(f"{indent}无卡牌记录")
        return

    class_cards = player.class_played
    neutral_cards = player.neutral_played
    non_collectible = sorted(
        [c for c in cards if not c.collectible and c.is_class_card],
        key=lambda c: (c.cost, c.card_name),
    )

    print(f"{indent}打出卡牌 ({len(cards)} 张):")

    if class_cards:
        print(f"{indent}  职业牌 ({len(class_cards)}):")
        for c in class_cards:
            mark = "★" if c.collectible else "☆"
            print(f"{indent}    {c.cost:>2}费 {mark} {c.card_name}")

    if neutral_cards:
        print(f"{indent}  中立牌 ({len(neutral_cards)}):")
        for c in neutral_cards:
            mark = "★" if c.collectible else "☆"
            print(f"{indent}    {c.cost:>2}费 {mark} {c.card_name}")

    if non_collectible:
        print(f"{indent}  衍生/非收集牌 ({len(non_collectible)}):")
        for c in non_collectible:
            print(f"{indent}    {c.card_name} [{c.card_id}]")


def main():
    log_dir = sys.argv[1] if len(sys.argv) > 1 else None
    if log_dir is None:
        hs_dirs = sorted(PROJECT_ROOT.glob("Hearthstone_*"))
        if hs_dirs:
            log_dir = str(hs_dirs[-1])
        else:
            print("未找到日志目录，请指定路径")
            return

    result = parse_log_dir(log_dir)
    games = result["games"]
    deck_entries = result["deck_entries"]

    print("=" * 70)
    print("  炉石传说日志解析器 (hslog)")
    print(f"  日志目录: {result['log_dir']}")
    print("=" * 70)

    unique_decks = {}
    for d in deck_entries:
        did = d.get("deck_id", "?")
        if did not in unique_decks:
            unique_decks[did] = d

    if unique_decks:
        print(f"\n{'='*70}")
        print(f"  我的卡组 ({len(unique_decks)} 套)")
        print(f"{'='*70}")
        for did, d in unique_decks.items():
            deck_info = DeckInfo.from_deck_code(d["name"], did, d["code"])
            print()
            print_deck_info(deck_info)

    if not games:
        print("\n未找到对局数据")
        return

    print(f"\n{'='*70}")
    print(f"  对局记录 ({len(games)} 场)")
    print(f"{'='*70}")

    for game in games:
        me = game.me
        opp = game.opponent
        icon = "✓ 胜利" if game.won else "✗ 失败" if game.result == "LOST" else "? 未知"
        deck_label = me.deck.name if me.deck else "未知"

        print(f"\n  ┌─ 对局 #{game.game_index + 1} {icon}")
        print(f"  │ 我: {me.hero_class_cn} [{deck_label}]")
        print(f"  │ 对手: {opp.hero_class_cn}")
        print(f"  │")
        print(f"  │ 对手卡牌:")
        print_player_cards(opp, indent="  │")
        print(f"  └─")

    wins = sum(1 for g in games if g.won)
    losses = sum(1 for g in games if g.result == "LOST")
    unknown = len(games) - wins - losses
    print(f"\n{'='*70}")
    print(f"  战绩汇总")
    print(f"{'='*70}")
    print(f"  总场次: {len(games)}  胜: {wins}  负: {losses}  未知: {unknown}")

    class_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
    for g in games:
        cls = g.opponent.hero_class_cn or g.opponent.hero_class
        if g.won:
            class_stats[cls]["wins"] += 1
        elif g.result == "LOST":
            class_stats[cls]["losses"] += 1

    if class_stats:
        print(f"\n  对手职业分布:")
        for cls_name, stats in sorted(class_stats.items()):
            total = stats["wins"] + stats["losses"]
            wr = stats["wins"] / total * 100 if total else 0
            print(f"    vs {cls_name}: {stats['wins']}胜 {stats['losses']}负 (胜率 {wr:.0f}%)")

    print(f"\n{'='*70}")
    print(f"  对手卡组推断（可收集卡牌汇总）")
    print(f"{'='*70}")
    for game in games:
        opp = game.opponent
        coll = opp.collectible_played
        if not coll:
            continue
        print(f"\n  对局 #{game.game_index + 1} vs {opp.hero_class_cn}:")
        class_c = sorted(
            [c for c in coll if c.is_class_card],
            key=lambda c: (c.cost, c.card_name),
        )
        neutral_c = sorted(
            [c for c in coll if c.is_neutral],
            key=lambda c: (c.cost, c.card_name),
        )
        if class_c:
            print(f"    职业牌 ({len(class_c)}):")
            for c in class_c:
                print(f"      {c.cost:>2}费 {c.card_name} [{c.card_id}]")
        if neutral_c:
            print(f"    中立牌 ({len(neutral_c)}):")
            for c in neutral_c:
                print(f"      {c.cost:>2}费 {c.card_name} [{c.card_id}]")

    print(f"\n{'='*70}")
    print(f"  解析完成")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

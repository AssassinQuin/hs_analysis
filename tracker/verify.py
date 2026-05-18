# -*- coding: utf-8 -*-
"""verify.py — 追踪器验证脚本

加载现有 Power.log，运行完整管线（解析 → 追踪 → 预测 → 展示），
验证对手职业检测、手牌预测生成等功能是否正常工作。

用法:
    python -m tracker.verify
    python tracker/verify.py
    python tracker/verify.py /path/to/Power.log
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def verify(log_path: str | None = None):
    """运行验证。

    Args:
        log_path: Power.log 文件路径。为 None 时自动查找。
    """
    # 确保项目根目录在 sys.path 中
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print("=" * 60)
    print("炉石传说追踪器 — 验证脚本")
    print("=" * 60)

    # ── 1. 查找 Power.log ───────────────────────────────────
    if log_path is None:
        from tracker.log_monitor import find_power_log_path
        log_path_obj = find_power_log_path()
        if log_path_obj is None:
            # 回退到项目根目录的 Power.log
            fallback = project_root / "Power.log"
            if fallback.exists():
                log_path = str(fallback)
            else:
                print("❌ 未找到 Power.log 文件")
                print("   请指定路径: python tracker/verify.py /path/to/Power.log")
                return False
        else:
            log_path = str(log_path_obj)

    print(f"\n📄 Power.log: {log_path}")

    if not Path(log_path).exists():
        print(f"❌ 文件不存在: {log_path}")
        return False

    # ── 2. 加载卡牌数据库 ───────────────────────────────────
    print("\n📚 加载卡牌数据库…")
    try:
        from analysis.card.data.card_data import get_db
        db = get_db()
        print(f"   ✅ 卡牌数据库加载成功: {len(db._cards)} 张卡牌")
    except Exception as e:
        print(f"   ❌ 卡牌数据库加载失败: {e}")
        return False

    # ── 3. 解析 Power.log（使用 load_existing_log 逐行桥接） ──
    print("\n📋 解析 Power.log…")
    try:
        from tracker.log_monitor import CoreLogMonitor
        monitor = CoreLogMonitor()
        monitor.load_existing_log(log_path)

        # 事件统计
        gt = monitor.game_tracker
        events = []
        for line in open(log_path, "r", encoding="utf-8", errors="replace"):
            evt = gt.feed_line(line.rstrip("\n"))
            if evt:
                events.append(evt)
        from collections import Counter
        event_counts = Counter(events)
        total = sum(event_counts.values())
        print(f"   ✅ 解析完成: {total} 个事件")
        for evt, count in event_counts.most_common():
            print(f"      {evt}: {count}")
    except Exception as e:
        print(f"   ❌ 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    # ── 3.5. 使用 game_log_parser 获取完整游戏记录 ────────────
    print("\n📋 提取完整游戏记录…")
    game_records = []
    try:
        from analysis.watcher.game_log_parser import parse_games, assign_decks, parse_decks_log
        game_records = parse_games(log_path)
        if game_records:
            # 分配卡组
            log_dir_path = Path(log_path).parent
            log_dir = str(log_dir_path)
            from analysis.watcher.game_log_parser import parse_log_dir
            dir_result = parse_log_dir(log_dir)
            print(f"   ✅ 解析到 {len(game_records)} 场游戏")
            for i, gr in enumerate(game_records):
                opp = gr.opponent
                print(f"   游戏 {i+1}: {opp.hero_class_cn}({opp.hero_class}) — 打出 {len(opp.played_cards)} 张牌")
                for j, card in enumerate(opp.played_cards[:8]):
                    src = "衍生" if not card.collectible else "牌库"
                    print(f"      {card.card_name} (费{card.cost}, {card.card_type}, {src})")
                if len(opp.played_cards) > 8:
                    print(f"      ... 还有 {len(opp.played_cards) - 8} 张")
        else:
            print(f"   ⚠️ 未解析到游戏记录")
    except Exception as e:
        print(f"   ⚠️ 完整记录提取失败: {e}")

    # ── 4. 构建游戏状态 ─────────────────────────────────────
    print("\n🎮 构建游戏状态…")
    try:
        state_dict = monitor.build_state_dict()

        in_game = state_dict.get("in_game", False)
        turn = state_dict.get("turn", 0)
        player_class = state_dict.get("player_class", "未知")
        opp_class = state_dict.get("opp_class", "未知")
        opp_hand = state_dict.get("opp_hand_count", 0)
        opp_deck = state_dict.get("opp_deck_count", 0)

        print(f"   游戏中: {in_game}")
        print(f"   回合: {turn}")
        print(f"   我方职业: {player_class}")
        print(f"   对手职业: {opp_class}")
        print(f"   对手手牌: {opp_hand}")
        print(f"   对手牌库: {opp_deck}")

        if opp_class != "未知":
            print(f"   ✅ 对手职业检测正常")
        else:
            print(f"   ⚠️ 对手职业未检测到")
    except Exception as e:
        print(f"   ❌ 构建游戏状态失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    # ── 5. 手牌预测 ─────────────────────────────────────────
    print("\n🔮 对手手牌预测…")
    try:
        from tracker.hand_predictor import HandPredictor
        predictor = HandPredictor()
        result = predictor.predict(state_dict)

        print(f"   原型: {result.archetype_name or '未知'} ({result.archetype_confidence:.1%})")
        print(f"   打法: {result.playstyle}")

        if result.top_archetypes:
            print(f"   Top 3 原型:")
            for name, prob in result.top_archetypes[:3]:
                print(f"      {name}: {prob:.1%}")

        print(f"   手牌预测 ({len(result.hand_predictions)} 项):")
        for hp in result.hand_predictions[:8]:
            src = hp.source
            prob_str = f"{hp.probability:.0%}" if hp.probability >= 0.5 else "?"
            print(f"      {hp.name} (费{hp.cost}, {prob_str}, {src})")

        print(f"   卡组预测 ({len(result.deck_predictions)} 项):")
        for dp in result.deck_predictions[:10]:
            status = "已打" if dp.played else ("手牌" if dp.in_hand else "牌库")
            print(f"      {dp.name} (费{dp.cost}, ×{dp.quantity}, {status})")

        if result.hand_predictions:
            print(f"   ✅ 手牌预测生成正常")
        else:
            print(f"   ⚠️ 未生成手牌预测（可能缺少 HSReplay 数据）")

    except Exception as e:
        print(f"   ❌ 手牌预测失败: {e}")
        import traceback
        traceback.print_exc()

    # ── 6. 游戏状态管理器 ───────────────────────────────────
    print("\n📊 完整游戏状态…")
    try:
        from tracker.game_state import GameStateManager
        manager = GameStateManager()
        manager.update(state_dict, result)

        gs = manager.state
        print(f"   对手英雄: {gs.opponent.hero.hero_class_cn} ({gs.opponent.hero.hero_class})")
        print(f"   对手手牌数: {gs.opponent.hand_count}")
        print(f"   对手牌库: {gs.opponent.deck_remaining}/{gs.opponent.initial_deck_size}")
        print(f"   对手奥秘: {len(gs.opponent.secrets)}")
        print(f"   对手残骸: {gs.opponent.corpses}")
        print(f"   攻击风险: {gs.attack_risk:.0%}")
        print(f"   施法风险: {gs.spell_risk:.0%}")

        print(f"   ✅ 游戏状态管理器正常")
    except Exception as e:
        print(f"   ❌ 游戏状态管理器失败: {e}")
        import traceback
        traceback.print_exc()

    # ── 7. 贝叶斯推断 ───────────────────────────────────────
    print("\n🧠 贝叶斯推断…")
    try:
        bayesian = state_dict.get("bayesian", {})
        archetype = bayesian.get("archetype_name")
        confidence = bayesian.get("deck_confidence", 0.0)
        top_decks = bayesian.get("top_decks", [])

        if archetype:
            print(f"   锁定原型: {archetype} ({confidence:.1%})")
        else:
            print(f"   原型未锁定 (最高置信度: {confidence:.1%})")

        if top_decks:
            print(f"   Top 原型:")
            for aid, name, prob in top_decks[:5]:
                print(f"      #{aid} {name}: {prob:.1%}")
        else:
            print(f"   ⚠️ 无原型数据（可能 HSReplay 缓存为空）")

    except Exception as e:
        print(f"   ❌ 贝叶斯推断检查失败: {e}")

    # ── 8. 奥秘概率 ─────────────────────────────────────────
    print("\n🔒 奥秘概率…")
    try:
        secret_report = state_dict.get("secret_report", {})
        active = secret_report.get("active_secrets", 0)
        summary = secret_report.get("summary", "无奥秘")
        most_likely = secret_report.get("most_likely", [])

        print(f"   活跃奥秘: {active}")
        print(f"   {summary}")

        if most_likely:
            print(f"   最可能:")
            for cid, name, prob in most_likely[:5]:
                print(f"      {name}: {prob:.1%}")

    except Exception as e:
        print(f"   ❌ 奥秘概率检查失败: {e}")

    # ── 9. 卡牌图像 ─────────────────────────────────────────
    print("\n🖼️  卡牌图像缓存…")
    try:
        from tracker.card_images import CardImageManager
        img_mgr = CardImageManager()
        stats = img_mgr.get_cache_stats()
        print(f"   全图缓存: {stats['full_images_cached']} 张")
        print(f"   贴片缓存: {stats['tile_images_cached']} 张")
        print(f"   内存缓存: {stats['memory_cache_size']} 张")
    except Exception as e:
        print(f"   ⚠️ 卡牌图像检查失败: {e}")

    # ── 总结 ─────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("验证完成 ✅")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="炉石追踪器验证脚本")
    parser.add_argument("log_path", nargs="?", help="Power.log 文件路径")
    args = parser.parse_args()

    success = verify(args.log_path)
    sys.exit(0 if success else 1)

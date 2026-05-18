#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mcts_accuracy.py — MCTS对手手牌推断精度测试（v2）

使用两场真实游戏数据测试MCTS手牌推断系统。

核心问题：对手手牌在Power.log中是隐藏的（CardID为空），
只有在打出时才通过SHOW_ENTITY揭示。
因此我们的测试策略是：

1. **已打出卡牌预测准确率**：对手实际打出的卡牌，MCTS是否预测到了？
2. **概率排序质量**：MCTS给已打出卡牌的概率是否高于未打出的？
3. **行为匹配质量**：MCTS模拟的行为与对手实际行为是否一致？

使用 hslog + EntityTreeExporter 完整解析游戏，获取每回合的完整状态。
"""

import sys
import os
import json
import logging
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("mcts_test")
logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════
# 工具函数：使用 hslog 解析完整游戏
# ═══════════════════════════════════════════════════════════════════

from hearthstone.enums import GameTag, Zone, CardType, PlayState, Step
from hslog.parser import LogParser
from hslog.export import EntityTreeExporter


class _SafeExporter(EntityTreeExporter):
    def handle_full_entity(self, packet):
        if packet.entity is None:
            return None
        return super().handle_full_entity(packet)


def parse_game_fully(log_path: str):
    """完整解析 Power.log，返回 (parser, game, friendly_idx)"""
    parser = LogParser()
    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                parser.read_line(line)
            except Exception:
                pass

    if not parser.games:
        return None, None, 0

    packet_tree = parser.games[-1]
    try:
        exporter = _SafeExporter(packet_tree)
        exporter.export()
        game = exporter.game
    except Exception:
        return parser, None, 0

    if not game or len(game.players) < 2:
        return parser, game, 0

    # 检测友方玩家（能看到手牌的一方）
    vis = []
    for p in game.players:
        count = sum(
            1 for e in getattr(p, "entities", [])
            if getattr(e, "card_id", "") and e.tags.get(GameTag.ZONE) == Zone.HAND
        )
        vis.append(count)
    friendly_idx = 1 if vis[1] > vis[0] else 0

    return parser, game, friendly_idx


# ═══════════════════════════════════════════════════════════════════
# 对手回合数据提取
# ═══════════════════════════════════════════════════════════════════

def extract_opponent_turns(log_path: str) -> List[Dict]:
    """逐行解析 Power.log，在每个对手回合结束时提取数据。

    返回每个对手回合的快照列表，包含：
    - 对手本回合打出的卡牌
    - 对手法力消耗
    - 对手可用法力
    - 对手当前手牌数（从TAG变化推断）
    - 对手已打出的所有卡牌（历史）
    - 对手英雄技能是否使用
    """
    from analysis.watcher.game_tracker import GameTracker
    from analysis.watcher.global_tracker import GlobalTracker
    from analysis.constants.hs_enums import ZONE_HAND, ZONE_DECK, ZONE_PLAY

    # 先检测 controller
    _, game, friendly_idx = parse_game_fully(log_path)
    if game is None:
        return []

    # 从game对象获取controller
    opp_idx = 1 - friendly_idx
    our_controller = game.players[friendly_idx].tags.get(GameTag.CONTROLLER, friendly_idx + 1)
    opp_controller = game.players[opp_idx].tags.get(GameTag.CONTROLLER, opp_idx + 1)

    logger.info("我方 controller=%d, 对手 controller=%d", our_controller, opp_controller)

    # 使用 GameTracker 解析
    tracker = GameTracker()
    events = tracker.load_file(log_path)

    # 使用 GlobalTracker 维护对手状态
    gt = GlobalTracker(our_controller=our_controller, opp_controller=opp_controller)
    gt.on_game_start()

    # 重新逐行喂入 GlobalTracker
    current_turn = 0
    opp_turn_snapshots = []
    opp_played_this_turn = []
    opp_mana_spent_this_turn = 0
    opp_mana_available = 0
    opp_hero_power_used = False

    # 卡牌数据库
    try:
        from analysis.data.hsdb import get_db
        db = get_db()
    except Exception:
        db = None

    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            # 检测回合变化
            if "tag=TURN" in stripped and "GameEntity" in stripped:
                import re
                m = re.search(r"tag=TURN value=(\d+)", stripped)
                if m:
                    new_turn = int(m.group(1))
                    if new_turn != current_turn and current_turn > 0:
                        # 在回合切换时拍快照
                        # Player 1: 奇数回合, Player 2: 偶数回合
                        is_opp_turn = False
                        if opp_controller == 1:
                            is_opp_turn = (current_turn % 2 == 1)
                        elif opp_controller == 2:
                            is_opp_turn = (current_turn % 2 == 0)

                        if is_opp_turn and opp_played_this_turn:
                            snap = {
                                "turn": current_turn,
                                "played_cards": list(opp_played_this_turn),
                                "mana_spent": opp_mana_spent_this_turn,
                                "mana_available": opp_mana_available,
                                "hero_power_used": opp_hero_power_used,
                                "hand_count": gt.state.opp_hand_count,
                                "all_played": [kc.card_id for kc in gt.state.opp_known_cards
                                               if kc.card_id],
                                "generated": set(gt.state.opp_generated_seen),
                                "opp_class": gt.state.opp_hero_class,
                                "opp_board_size": len(gt.state.opp_board_minions),
                            }
                            opp_turn_snapshots.append(snap)
                            logger.info(
                                "Turn %d 快照: 打出=%s, 法力=%d/%d, 手牌=%d",
                                current_turn, opp_played_this_turn,
                                opp_mana_spent_this_turn, opp_mana_available,
                                gt.state.opp_hand_count,
                            )

                    current_turn = new_turn
                    opp_played_this_turn = []
                    opp_mana_spent_this_turn = 0
                    opp_hero_power_used = False

            # 检测对手打出卡牌（SHOW_ENTITY 到 PLAY/SECRET/GRAVEYARD）
            if "SHOW_ENTITY" in stripped:
                m_id = re.search(r"id=(\d+)", stripped)
                m_cid = re.search(r"CardID=(\S+)", stripped)
                if m_id and m_cid:
                    eid = int(m_id.group(1))
                    card_id = m_cid.group(1)

                    # 检查controller（需要从entity_cache获取）
                    ent = tracker.entity_cache.get_entity(eid)
                    if ent:
                        ctrl = ent.get("tags", {}).get(GameTag.CONTROLLER, 0)
                        zone = ent.get("tags", {}).get(GameTag.ZONE, 0)
                        cost = ent.get("tags", {}).get(GameTag.COST, 0)
                        card_type = ent.get("tags", {}).get(GameTag.CARDTYPE, 0)

                        if ctrl == opp_controller:
                            if zone in (Zone.PLAY.value, Zone.SECRET.value, Zone.GRAVEYARD.value):
                                if card_type not in (CardType.ENCHANTMENT.value, CardType.HERO_POWER.value):
                                    if card_id not in opp_played_this_turn:
                                        opp_played_this_turn.append(card_id)
                                        opp_mana_spent_this_turn += (cost or 0)

            # 喂入 GlobalTracker
            # （简化：通过 entity_cache 的变化来触发）
            # 实际上 GlobalTracker 需要通过 on_show_entity / on_zone_change 调用
            # 我们通过 tracker 的事件间接驱动

    return opp_turn_snapshots


def extract_opponent_turns_v2(log_path: str) -> List[Dict]:
    """简化版：只通过 hslog 完整解析后提取对手出牌信息。

    优点：不需要手动解析，直接用 hslog 的完整实体树。
    缺点：只有游戏结束后的状态，没有逐回合快照。

    策略：重新逐行解析，在每个对手回合结束时，用 hslog 的包数据
    来重建对手的实际行为。
    """
    import re

    # 先完整解析一次，获取 controller 信息
    _, game, friendly_idx = parse_game_fully(log_path)
    if game is None:
        return []

    opp_idx = 1 - friendly_idx
    our_ctrl = game.players[friendly_idx].tags.get(GameTag.CONTROLLER, friendly_idx + 1)
    opp_ctrl = game.players[opp_idx].tags.get(GameTag.CONTROLLER, opp_idx + 1)

    logger.info("Controller: 我方=%d, 对手=%d", our_ctrl, opp_ctrl)

    # 加载卡牌数据库
    try:
        from analysis.data.card_data import get_db
        card_db = get_db()
    except Exception:
        card_db = None

    def get_card_name(card_id):
        if not card_db or not card_id:
            return card_id or "?"
        data = card_db.get_card(card_id)
        if data:
            return data.get("name", card_id)
        return card_id

    # 使用 GameTracker + GlobalTracker 完整追踪
    from analysis.watcher.game_tracker import GameTracker
    from analysis.watcher.global_tracker import GlobalTracker

    gt = GlobalTracker(our_controller=our_ctrl, opp_controller=opp_ctrl)
    gt.on_game_start()

    tracker = GameTracker()

    current_turn = 0
    opp_turn_data = []
    opp_played_this_turn = []
    opp_mana_spent = 0

    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")
            stripped = line.strip()

            # 喂入 tracker
            tracker.feed_line(line)

            # 回合变化
            if "tag=TURN" in stripped and "GameEntity" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    new_turn = int(m.group(1))
                    if new_turn != current_turn:
                        if current_turn > 0:
                            # 判断是否是对手回合
                            is_opp = False
                            if opp_ctrl == 1:
                                is_opp = (current_turn % 2 == 1)
                            elif opp_ctrl == 2:
                                is_opp = (current_turn % 2 == 0)

                            if is_opp:
                                snap = {
                                    "turn": current_turn,
                                    "played_cards": list(opp_played_this_turn),
                                    "played_card_names": [get_card_name(c) for c in opp_played_this_turn],
                                    "mana_spent": opp_mana_spent,
                                    "mana_available": min(10, (current_turn + 1) // 2),
                                    "hand_count": gt.state.opp_hand_count,
                                    "all_played_cards": [kc.card_id for kc in gt.state.opp_known_cards if kc.card_id],
                                    "all_played_names": [get_card_name(kc.card_id) for kc in gt.state.opp_known_cards if kc.card_id],
                                    "opp_class": gt.state.opp_hero_class,
                                    "opp_board_size": len(gt.state.opp_board_minions),
                                    "generated_cards": set(gt.state.opp_generated_seen),
                                    "opp_secrets": list(gt.state.opp_secrets),
                                }
                                opp_turn_data.append(snap)

                        current_turn = new_turn
                        opp_played_this_turn = []
                        opp_mana_spent = 0

            # 检测对手打出卡牌
            if "SHOW_ENTITY" in stripped:
                m_id = re.search(r"id=(\d+)", stripped)
                m_cid = re.search(r"CardID=(\S+)", stripped)
                if m_id and m_cid:
                    eid = int(m_id.group(1))
                    card_id = m_cid.group(1)

                    # 检查是否是对手的卡牌且打到场上
                    ent = tracker.entity_cache.get_entity(eid)
                    if ent:
                        ctrl = ent.get("tags", {}).get(GameTag.CONTROLLER, 0)
                        zone = ent.get("tags", {}).get(GameTag.ZONE, 0)
                        cost = ent.get("tags", {}).get(GameTag.COST, 0)
                        ctype = ent.get("tags", {}).get(GameTag.CARDTYPE, 0)

                        # 对手的卡牌，且出现在 PLAY/SECRET/GRAVEYARD
                        if ctrl == opp_ctrl and card_id and \
                           ctype not in (CardType.ENCHANTMENT.value, CardType.HERO_POWER.value):
                            if zone in (Zone.PLAY.value, Zone.SECRET.value, Zone.GRAVEYARD.value):
                                if card_id not in opp_played_this_turn:
                                    opp_played_this_turn.append(card_id)
                                    opp_mana_spent += (cost or 0)

            # 喂入 GlobalTracker（通过 entity_cache 变化触发）
            # 由于 GlobalTracker 需要明确的事件调用，我们直接使用它的状态

    return opp_turn_data


# ═══════════════════════════════════════════════════════════════════
# MCTS 推断测试
# ═══════════════════════════════════════════════════════════════════

def test_mcts_on_snapshots(snapshots: List[Dict], game_name: str) -> Dict:
    """对每个对手回合快照运行 MCTS 推断，对比实际打出卡牌。"""
    from analysis.engine.opponent_hand_mcts import (
        OpponentHandMCTS, ObservedBehavior,
    )

    results = {
        "game_name": game_name,
        "per_turn": [],
        "overall": {},
    }

    total_played = 0
    total_played_in_pred = 0
    total_pred_cards = 0
    total_pred_in_played = 0
    sum_avg_prob_played = 0.0
    sum_avg_prob_unplayed = 0.0
    count_prob = 0

    for snap in snapshots:
        turn = snap["turn"]
        played = snap["played_cards"]
        played_names = snap.get("played_card_names", played)
        mana_spent = snap["mana_spent"]
        mana_available = snap["mana_available"]
        hand_count = snap["hand_count"]
        opp_class = snap.get("opp_class", "")
        all_played = snap.get("all_played_cards", [])

        is_pass = len(played) == 0 and mana_spent == 0

        observed = ObservedBehavior(
            played_cards=played,
            mana_spent=mana_spent,
            available_mana=mana_available,
            hero_power_used=False,
            passed=is_pass,
            turn=turn,
        )

        # 构建贝叶斯状态
        bayesian_state = {"top_decks": [], "opp_class": opp_class}

        seen_cards = dict(Counter(all_played))
        generated = snap.get("generated_cards", set())

        mcts = OpponentHandMCTS(time_budget_ms=1000.0)
        try:
            preds = mcts.infer_hand_probabilities(
                bayesian_state=bayesian_state,
                observed=observed,
                seen_cards=seen_cards,
                generated_cards=generated,
                hand_size=hand_count,
                time_budget_ms=1000.0,
            )
        except Exception as e:
            logger.warning("T%d MCTS失败: %s", turn, e)
            preds = {}

        # ── 分析预测结果 ──
        # 1. 对手实际打出的卡牌是否在预测中
        played_in_pred = sum(1 for c in played if c in preds)
        total_played += len(played)
        total_played_in_pred += played_in_pred

        # 2. 预测的卡牌中有多少是实际打出的
        pred_cards = set(preds.keys())
        pred_in_played = len(pred_cards & set(played))
        total_pred_cards += len(pred_cards)
        total_pred_in_played += pred_in_played

        # 3. 概率分析：已打出卡牌 vs 未打出卡牌的平均预测概率
        if played and preds:
            prob_played = [preds.get(c, 0.0) for c in played if c in preds]
            prob_unplayed = [p for c, p in preds.items() if c not in set(played)]
            avg_prob_played = sum(prob_played) / len(prob_played) if prob_played else 0.0
            avg_prob_unplayed = sum(prob_unplayed) / len(prob_unplayed) if prob_unplayed else 0.0
            sum_avg_prob_played += avg_prob_played
            sum_avg_prob_unplayed += avg_prob_unplayed
            count_prob += 1
        else:
            avg_prob_played = 0.0
            avg_prob_unplayed = 0.0

        # 4. Top-K 命中率（K=hand_count）
        if preds:
            sorted_preds = sorted(preds.items(), key=lambda x: -x[1])
            top_k = [c for c, _ in sorted_preds[:max(hand_count, 3)]]
        else:
            top_k = []

        top_k_hits = len(set(played) & set(top_k))

        turn_result = {
            "turn": turn,
            "played_cards": played,
            "played_card_names": played_names,
            "hand_count": hand_count,
            "mana_spent": mana_spent,
            "mana_available": mana_available,
            "is_pass": is_pass,
            "num_predictions": len(preds),
            "played_in_pred": played_in_pred,
            "played_total": len(played),
            "top_k": top_k[:10],
            "top_k_hits": top_k_hits,
            "avg_prob_played": round(avg_prob_played, 4),
            "avg_prob_unplayed": round(avg_prob_unplayed, 4),
            "prob_separation": round(avg_prob_played - avg_prob_unplayed, 4),
        }
        results["per_turn"].append(turn_result)

        # 打印详情
        pred_display = []
        if preds:
            for c, p in sorted(preds.items(), key=lambda x: -x[1])[:5]:
                from analysis.data.card_data import get_db
                try:
                    db = get_db()
                    name = db.get_card(c).get("name", c) if db and db.get_card(c) else c
                except Exception:
                    name = c
                pred_display.append(f"{name}={p:.1%}")

        logger.info(
            "T%d: 打出=%s, 预测=%s, 命中=%d/%d, Top-K命中=%d, 概率差=%.4f",
            turn, played_names, pred_display,
            played_in_pred, len(played), top_k_hits,
            avg_prob_played - avg_prob_unplayed,
        )

    # 总体指标
    results["overall"] = {
        "total_played": total_played,
        "total_played_in_pred": total_played_in_pred,
        "played_recall": total_played_in_pred / max(total_played, 1),
        "total_pred_cards": total_pred_cards,
        "total_pred_in_played": total_pred_in_played,
        "pred_precision": total_pred_in_played / max(total_pred_cards, 1),
        "avg_prob_played": sum_avg_prob_played / max(count_prob, 1),
        "avg_prob_unplayed": sum_avg_prob_unplayed / max(count_prob, 1),
        "prob_separation": (sum_avg_prob_played - sum_avg_prob_unplayed) / max(count_prob, 1),
        "num_turns": len(snapshots),
    }

    return results


def print_report(results: Dict):
    """打印测试报告"""
    game_name = results["game_name"]
    overall = results["overall"]

    print(f"\n{'='*80}")
    print(f"  游戏报告: {game_name}")
    print(f"{'='*80}")

    print(f"\n【总体指标】")
    print(f"  对手回合数:          {overall['num_turns']}")
    print(f"  对手打出总卡牌数:    {overall['total_played']}")
    print(f"  打出卡牌预测召回率:  {overall['played_recall']:.1%} ({overall['total_played_in_pred']}/{overall['total_played']})")
    print(f"  预测卡牌精确率:      {overall['pred_precision']:.1%} ({overall['total_pred_in_played']}/{overall['total_pred_cards']})")
    print(f"  已打出牌平均概率:    {overall['avg_prob_played']:.4f}")
    print(f"  未打出牌平均概率:    {overall['avg_prob_unplayed']:.4f}")
    print(f"  概率区分度(差值):    {overall['prob_separation']:.4f}")

    print(f"\n【逐回合详情】")
    print(f"  {'回合':>4} | {'打出':>12} | {'手牌':>4} | {'法力':>4} | {'预测数':>5} | {'命中':>4} | {'Top-K命中':>8} | {'打出概率':>8} | {'未打出概率':>8} | {'区分度':>6}")
    print(f"  {'----':>4} | {'----':>12} | {'----':>4} | {'----':>4} | {'------':>5} | {'----':>4} | {'--------':>8} | {'--------':>8} | {'----------':>8} | {'------':>6}")

    for tr in results["per_turn"]:
        played_str = ",".join(tr.get("played_card_names", tr["played_cards"])[:3])
        if len(tr["played_cards"]) > 3:
            played_str += f"...+{len(tr['played_cards'])-3}"
        print(
            f"  T{tr['turn']:>3} | {played_str:>12} | "
            f"{tr['hand_count']:>4} | {tr['mana_spent']:>2}/{tr['mana_available']:<2} | "
            f"{tr['num_predictions']:>5} | "
            f"{tr['played_in_pred']:>2}/{tr['played_total']:<2} | "
            f"{tr['top_k_hits']:>8} | "
            f"{tr['avg_prob_played']:>8.4f} | "
            f"{tr['avg_prob_unplayed']:>8.4f} | "
            f"{tr['prob_separation']:>6.4f}"
        )


# ═══════════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════════

def main():
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"

    games = [
        ("game1_warrior_vs_warrior_8t.log", "战士 vs 战士 (8回合)"),
        ("game3_dk_vs_rogue_21t.log", "死亡骑士 vs 盗贼 (21回合)"),
    ]

    all_results = {}

    for filename, game_name in games:
        log_path = str(fixtures_dir / filename)
        if not os.path.exists(log_path):
            print(f"⚠️  文件不存在: {log_path}")
            continue

        print(f"\n{'#'*80}")
        print(f"#  测试游戏: {game_name}")
        print(f"#  文件: {filename}")
        print(f"{'#'*80}")

        try:
            # 提取对手回合数据
            snapshots = extract_opponent_turns_v2(log_path)
            if not snapshots:
                print("⚠️  未提取到对手回合数据")
                continue

            logger.info("提取到 %d 个对手回合快照", len(snapshots))

            # 运行 MCTS 推断
            results = test_mcts_on_snapshots(snapshots, game_name)

            # 打印报告
            print_report(results)

            all_results[game_name] = results
        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()

    # ── 综合分析 ──
    print(f"\n{'='*80}")
    print(f"  综合分析总结")
    print(f"{'='*80}")

    for game_name, results in all_results.items():
        overall = results.get("overall", {})
        recall = overall.get("played_recall", 0)
        precision = overall.get("pred_precision", 0)
        separation = overall.get("prob_separation", 0)
        num_preds = overall.get("total_pred_cards", 0)

        print(f"\n  {game_name}:")
        print(f"    打出卡牌召回率: {recall:.1%}")
        print(f"    预测精确率:     {precision:.1%}")
        print(f"    概率区分度:     {separation:.4f}")
        print(f"    总预测卡牌数:   {num_preds}")

        # 实用性评估
        if num_preds == 0:
            level = "❌ 系统无法预测（缺少候选卡组数据，bayesian_state.top_decks 为空）"
            diagnosis = "核心问题：HandSampler.sample_worlds() 需要 top_decks 数据，但当前测试环境没有 hsreplay 卡组库。MCTS推断依赖贝叶斯卡组推断提供的候选卡组，没有候选卡组就无法采样世界。"
        elif separation > 0.1:
            level = "✅ 有实际参考价值 — MCTS能给已打出卡牌更高概率"
        elif separation > 0:
            level = "⚠️ 有一定区分能力，但区分度不足"
        else:
            level = "❌ 无区分能力 — 预测概率无意义"

        print(f"    实用性: {level}")
        if num_preds == 0:
            print(f"    诊断: {diagnosis}")

    # ── 关键发现 ──
    print(f"\n{'='*80}")
    print(f"  关键发现与建议")
    print(f"{'='*80}")

    has_any_pred = any(
        r.get("overall", {}).get("total_pred_cards", 0) > 0
        for r in all_results.values()
    )

    if not has_any_pred:
        print("""
  🔴 核心问题：MCTS 手牌推断系统当前无法产出预测结果

  原因分析：
  1. HandSampler.sample_worlds() 依赖 bayesian_state["top_decks"]
     但在离线测试中，没有 hsreplay 卡组库数据
  2. 候选卡组来源于 BayesianOpponent 的推断结果
     BayesianOpponent 需要：(a) 对手职业 (b) 对手打出卡牌 (c) hsreplay元数据
  3. 缺少候选卡组 → 无法采样手牌世界 → 无法模拟对手决策 → 无法推断概率

  修复建议：
  1. 短期：在测试中注入模拟的 top_decks 数据（使用已知卡组代码）
  2. 中期：使用 hsreplay 缓存数据库提供候选卡组
  3. 长期：当没有候选卡组时，使用回退策略：
     - 基于对手职业的所有标准卡牌池采样
     - 基于已打出卡牌推断卡组构成
     - 使用简化概率模型（超几何分布）作为基线
""")
    else:
        print("  系统产出了一些预测结果，详情见上方报告。")

    # 保存结果
    output_path = str(PROJECT_ROOT / "download" / "mcts_accuracy_report.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def convert_sets(obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, dict):
            return {k: convert_sets(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_sets(i) for i in obj]
        return obj

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(convert_sets(all_results), f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至: {output_path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_mcts_accuracy_v3.py — MCTS对手手牌推断精度测试（完整版）

完整流程：
1. 使用 hslog 解析获取对手实际打出的卡牌（ground truth）
2. 使用 GlobalTracker 追踪游戏状态
3. 使用 BayesianOpponent 进行卡组推断
4. 运行 MCTS 手牌推断
5. 对比分析

关键改进：
- 使用 hsreplay 缓存数据库提供候选卡组
- 使用 BayesianOpponent 进行卡组推断
- 逐回合运行 MCTS 并对比
"""

import sys
import os
import re
import json
import logging
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s: %(message)s")
logger = logging.getLogger("mcts_v3")

# ═══════════════════════════════════════════════════════════════════
# Step 1: 使用 hslog 解析对手实际打出的卡牌
# ═══════════════════════════════════════════════════════════════════

def get_opponent_played_cards(log_path: str) -> Tuple[Dict, List[Dict]]:
    """解析 Power.log，获取对手逐回合打出的卡牌。

    Returns: (game_info, opponent_turns)
    """
    from hearthstone.enums import GameTag, Zone, CardType
    from hslog.parser import LogParser
    from hslog.export import EntityTreeExporter

    class SafeExporter(EntityTreeExporter):
        def handle_full_entity(self, packet):
            if packet.entity is None:
                return None
            return super().handle_full_entity(packet)

    parser = LogParser()
    with open(log_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                parser.read_line(line)
            except Exception:
                pass

    if not parser.games:
        return {}, []

    exporter = SafeExporter(parser.games[-1])
    exporter.export()
    game = exporter.game
    if not game or len(game.players) < 2:
        return {}, []

    # 检测友方（手牌可见的一方）
    vis = []
    for p in game.players:
        count = sum(1 for e in getattr(p, "entities", [])
                    if getattr(e, "card_id", "") and e.tags.get(GameTag.ZONE) == Zone.HAND)
        vis.append(count)
    friendly_idx = 1 if vis[1] > vis[0] else 0
    opp_idx = 1 - friendly_idx

    our_ctrl = game.players[friendly_idx].tags.get(GameTag.CONTROLLER, friendly_idx + 1)
    opp_ctrl = game.players[opp_idx].tags.get(GameTag.CONTROLLER, opp_idx + 1)

    # 获取对手英雄职业
    opp_hero_class = ""
    for e in getattr(game.players[opp_idx], "entities", []):
        cid = getattr(e, "card_id", "")
        if cid and cid.startswith("HERO_") and e.tags.get(GameTag.ZONE) == Zone.PLAY:
            try:
                from analysis.data.card_data import get_db
                db = get_db()
                if db:
                    data = db.get_card(cid)
                    if data:
                        opp_hero_class = data.get("cardClass", "")
            except Exception:
                pass
            break

    game_info = {
        "our_controller": our_ctrl,
        "opp_controller": opp_ctrl,
        "opp_hero_class": opp_hero_class,
        "friendly_idx": friendly_idx,
    }

    # 收集对手所有打出/揭示过的卡牌（最终状态在 PLAY/GRAVEYARD/SECRET）
    opp_all_cards = []
    for e in getattr(game.players[opp_idx], "entities", []):
        cid = getattr(e, "card_id", "")
        if not cid or cid.startswith("HERO_"):
            continue
        ct = e.tags.get(GameTag.CARDTYPE, 0)
        zone = e.tags.get(GameTag.ZONE, 0)
        if ct in (CardType.HERO.value, CardType.ENCHANTMENT.value,
                  CardType.HERO_POWER.value, CardType.GAME.value, CardType.PLAYER.value):
            continue
        if zone in (Zone.PLAY.value, Zone.GRAVEYARD.value, Zone.SECRET.value,
                    Zone.REMOVEDFROMGAME.value):
            opp_all_cards.append({
                "card_id": cid,
                "cost": e.tags.get(GameTag.COST, 0),
                "type": ct,
                "zone": zone,
            })

    # 逐行重新解析，获取每回合对手打出的卡牌
    # 使用简化的方法：通过 TAG_CHANGE ZONE + SHOW_ENTITY 追踪
    tracker2 = LogParser()
    current_turn = 0
    opp_turn_plays = defaultdict(list)  # turn → [card_ids]

    with open(log_path, encoding="utf-8", errors="ignore") as f:
        current_show_entity = None
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            # 回合追踪
            if "tag=TURN" in stripped and "GameEntity" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    current_turn = int(m.group(1))

            # SHOW_ENTITY 检测对手打出
            if "SHOW_ENTITY" in stripped:
                m_id = re.search(r"id=(\d+)", stripped)
                m_cid = re.search(r"CardID=(\S+)", stripped)
                if m_id and m_cid:
                    current_show_entity = {
                        "eid": int(m_id.group(1)),
                        "card_id": m_cid.group(1),
                    }

            # 检测 SHOW_ENTITY 块内的 CONTROLLER 和 ZONE
            if current_show_entity and "tag=CONTROLLER" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    current_show_entity["controller"] = int(m.group(1))

            if current_show_entity and "tag=ZONE" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if not m:
                    m = re.search(r"value=(\w+)", stripped)
                    zone_map = {"PLAY": 1, "DECK": 2, "HAND": 3, "GRAVEYARD": 4,
                                "SETASIDE": 6, "SECRET": 7}
                    if m:
                        val = m.group(1)
                        current_show_entity["zone"] = zone_map.get(val, 0)
                else:
                    current_show_entity["zone"] = int(m.group(1))

            if current_show_entity and "tag=CARDTYPE" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    current_show_entity["card_type"] = int(m.group(1))

            if current_show_entity and "tag=COST" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    current_show_entity["cost"] = int(m.group(1))

            # SHOW_ENTITY 块结束
            if current_show_entity and ("BLOCK_START" in stripped or "BLOCK_END" in stripped
                                        or "TAG_CHANGE" in stripped or "FULL_ENTITY" in stripped):
                se = current_show_entity
                ctrl = se.get("controller", 0)
                zone = se.get("zone", 0)
                ctype = se.get("card_type", 0)
                cid = se.get("card_id", "")

                # 对手打出卡牌
                if ctrl == opp_ctrl and cid and \
                   zone in (Zone.PLAY.value, Zone.GRAVEYARD.value, Zone.SECRET.value) and \
                   ctype not in (CardType.ENCHANTMENT.value, CardType.HERO_POWER.value):
                    # 排除硬币
                    if cid not in ("MUDAN_COIN1", "MUDAN_COIN2", "GAME_005", "TLC_COIN2"):
                        opp_turn_plays[current_turn].append(cid)

                current_show_entity = None

    # 构建对手回合数据
    # 改进：不再使用奇偶回合规则判断对手回合，
    # 因为 opp_turn_plays 已经通过 controller 精确过滤（ctrl == opp_ctrl），
    # 所有记录的牌都是对手打出的，无需再做奇偶过滤。
    # 奇偶规则在以下情况不可靠：
    #   - 先手/后手与controller编号不是固定对应
    #   - 某些游戏模式下回合编号不严格递增
    #   - TAG_CHANGE STEP 阶段标记延迟
    opponent_turns = []
    all_played_so_far = []

    for turn in sorted(opp_turn_plays.keys()):
        played = opp_turn_plays[turn]
        all_played_so_far.extend(played)

        if played:
            # 对手法力 = 对手在游戏中的回合数 = ceil(turn / 2)
            # turn 1,2 → mana 1; turn 3,4 → mana 2; ...
            mana_available = min(10, (turn + 1) // 2)
            opponent_turns.append({
                "turn": turn,
                "played_cards": played,
                "all_played_so_far": list(all_played_so_far),
                "mana_available": mana_available,
                "opp_class": opp_hero_class,
            })

    return game_info, opponent_turns


# ═══════════════════════════════════════════════════════════════════
# Step 2: 使用 BayesianOpponent + MCTS 推断
# ═══════════════════════════════════════════════════════════════════

def run_bayesian_and_mcts(game_info: Dict, opponent_turns: List[Dict]) -> List[Dict]:
    """对每个对手回合运行贝叶斯推断 + MCTS 手牌推断。"""
    from analysis.utils.bayesian_opponent import BayesianOpponentModel
    from analysis.engine.opponent_hand_mcts import OpponentHandMCTS, ObservedBehavior
    from analysis.data.card_data import get_db

    opp_class = game_info.get("opp_hero_class", "")
    db = get_db()

    # 初始化贝叶斯模型
    bayesian = BayesianOpponentModel(player_class=opp_class)

    results = []
    seen_card_ids = Counter()  # 修复：使用Counter跟踪每张牌的已打出次数，而非set
    generated_cards = set()

    for snap in opponent_turns:
        turn = snap["turn"]
        played = snap["played_cards"]

        # 更新贝叶斯模型
        for cid in played:
            if cid not in generated_cards:
                # 获取 dbfId
                dbf_id = 0
                if db:
                    data = db.get_card(cid)
                    if data:
                        dbf_id = data.get("dbfId", 0)
                if dbf_id:
                    try:
                        bayesian.update(dbf_id)
                    except Exception:
                        pass
            seen_card_ids[cid] += 1  # 修复：计数而非简单add

        # 获取贝叶斯推断结果
        top_decks = bayesian.get_top_decks(n=3)
        bayesian_state = {
            "top_decks": top_decks,
            "opp_class": opp_class,
        }

        # 构建观测行为
        mana_spent = 0
        for cid in played:
            if db:
                data = db.get_card(cid)
                if data:
                    mana_spent += data.get("cost", 0)

        observed = ObservedBehavior(
            played_cards=played,
            mana_spent=mana_spent,
            available_mana=snap["mana_available"],
            hero_power_used=False,
            passed=False,
            turn=turn,
        )

        # 运行 MCTS 推断
        mcts = OpponentHandMCTS(time_budget_ms=1500.0)
        try:
            preds = mcts.infer_hand_probabilities(
                bayesian_state=bayesian_state,
                observed=observed,
                seen_cards=dict(seen_card_ids),  # 修复：传递实际计数，而非全是1
                generated_cards=generated_cards,
                hand_size=max(1, 5 - turn // 4),  # 估算手牌数
                time_budget_ms=1500.0,
            )
        except Exception as e:
            logger.warning("T%d MCTS失败: %s", turn, e)
            preds = {}

        # 获取卡牌名称
        def card_name(cid):
            if db:
                data = db.get_card(cid)
                if data:
                    return data.get("name", cid)
            return cid

        # 分析
        played_set = set(played)
        played_in_pred = sum(1 for c in played if c in preds)

        if preds and played:
            prob_played = [preds.get(c, 0.0) for c in played if c in preds]
            prob_unplayed = [p for c, p in preds.items() if c not in played_set]
            avg_prob_played = sum(prob_played) / len(prob_played) if prob_played else 0.0
            avg_prob_unplayed = sum(prob_unplayed) / len(prob_unplayed) if prob_unplayed else 0.0
        else:
            avg_prob_played = 0.0
            avg_prob_unplayed = 0.0

        # Top-K 命中
        hand_size = max(1, 5 - turn // 4)
        if preds:
            sorted_preds = sorted(preds.items(), key=lambda x: -x[1])
            top_k = [c for c, _ in sorted_preds[:max(hand_size, 3)]]
        else:
            top_k = []

        top_k_hits = len(played_set & set(top_k))

        result = {
            "turn": turn,
            "played_cards": played,
            "played_card_names": [card_name(c) for c in played],
            "top_decks_count": len(top_decks),
            "num_predictions": len(preds),
            "played_in_pred": played_in_pred,
            "played_total": len(played),
            "top_k": [(card_name(c), round(p, 3)) for c, p in sorted(preds.items(), key=lambda x: -x[1])[:10]] if preds else [],
            "top_k_hits": top_k_hits,
            "avg_prob_played": round(avg_prob_played, 4),
            "avg_prob_unplayed": round(avg_prob_unplayed, 4),
            "prob_separation": round(avg_prob_played - avg_prob_unplayed, 4),
        }
        results.append(result)

        # 打印
        top3_str = ", ".join(f"{n}={p:.1%}" for n, p in result["top_k"][:5])
        logger.info(
            "T%d: 打出=%s, 预测Top5=[%s], 命中=%d/%d, Top-K命中=%d, 区分度=%.4f",
            turn, result["played_card_names"], top3_str,
            played_in_pred, len(played), top_k_hits,
            avg_prob_played - avg_prob_unplayed,
        )

    return results


# ═══════════════════════════════════════════════════════════════════
# 报告
# ═══════════════════════════════════════════════════════════════════

def print_report(game_name: str, game_info: Dict, results: List[Dict]):
    """打印测试报告"""
    print(f"\n{'='*90}")
    print(f"  游戏报告: {game_name}")
    print(f"  对手职业: {game_info.get('opp_hero_class', '?')}")
    print(f"  对手Controller: {game_info.get('opp_controller', '?')}")
    print(f"{'='*90}")

    if not results:
        print("  ⚠️ 无对手回合数据")
        return

    # 总体指标
    total_played = sum(r["played_total"] for r in results)
    total_played_in_pred = sum(r["played_in_pred"] for r in results)
    total_top_k_hits = sum(r["top_k_hits"] for r in results)
    total_num_preds = sum(r["num_predictions"] for r in results)
    prob_seps = [r["prob_separation"] for r in results if r["prob_separation"] != 0]
    avg_sep = sum(prob_seps) / len(prob_seps) if prob_seps else 0

    print(f"\n【总体指标】")
    print(f"  对手回合数（有打出卡牌的）: {len(results)}")
    print(f"  对手打出总卡牌数:          {total_played}")
    print(f"  MCTS预测覆盖的打出卡牌:    {total_played_in_pred}/{total_played} ({total_played_in_pred/max(total_played,1):.1%})")
    print(f"  Top-K命中:                 {total_top_k_hits}")
    print(f"  总预测卡牌数:              {total_num_preds}")
    print(f"  平均概率区分度:            {avg_sep:.4f}")

    # 逐回合详情
    print(f"\n【逐回合详情】")
    print(f"  {'T':>3} | {'打出卡牌':>30} | {'预测数':>5} | {'覆盖':>4} | {'Top-K命中':>8} | {'打出概率':>8} | {'未打出概率':>8} | {'区分度':>6}")
    print(f"  {'---':>3} | {'---':>30} | {'-----':>5} | {'----':>4} | {'--------':>8} | {'--------':>8} | {'----------':>8} | {'------':>6}")

    for r in results:
        played_str = ",".join(r["played_card_names"][:4])
        if len(r["played_cards"]) > 4:
            played_str += f"...+{len(r['played_cards'])-4}"
        print(
            f"  T{r['turn']:>2} | {played_str:>30} | "
            f"{r['num_predictions']:>5} | "
            f"{r['played_in_pred']:>2}/{r['played_total']:<2} | "
            f"{r['top_k_hits']:>8} | "
            f"{r['avg_prob_played']:>8.4f} | "
            f"{r['avg_prob_unplayed']:>8.4f} | "
            f"{r['prob_separation']:>6.4f}"
        )

    # 详细预测对比
    print(f"\n【预测Top-5 vs 实际打出】")
    for r in results:
        print(f"\n  回合 T{r['turn']}:")
        print(f"    实际打出: {r['played_card_names']}")
        if r["top_k"]:
            for i, (name, prob) in enumerate(r["top_k"][:5], 1):
                in_played = "✅" if any(name == pn for pn in r["played_card_names"]) else "  "
                print(f"    {in_played} #{i}: {name} = {prob:.1%}")
        else:
            print(f"    预测: 无（可能缺少候选卡组）")


def main():
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures"

    games = [
        ("game1_warrior_vs_warrior_8t.log", "战士 vs 战士 (8回合)"),
        ("game3_dk_vs_rogue_21t.log", "死亡骑士 vs 盗贼 (21回合)"),
    ]

    all_game_results = {}

    for filename, game_name in games:
        log_path = str(fixtures_dir / filename)
        if not os.path.exists(log_path):
            print(f"⚠️  文件不存在: {log_path}")
            continue

        print(f"\n{'#'*90}")
        print(f"#  测试游戏: {game_name}")
        print(f"#  文件: {filename}")
        print(f"{'#'*90}")

        try:
            # Step 1: 解析对手实际行为
            game_info, opponent_turns = get_opponent_played_cards(log_path)
            logger.info("游戏信息: %s", game_info)
            logger.info("对手有打出卡牌的回合数: %d", len(opponent_turns))

            if not opponent_turns:
                print("  ⚠️ 未提取到对手打出卡牌数据")
                continue

            # Step 2: 运行贝叶斯 + MCTS
            results = run_bayesian_and_mcts(game_info, opponent_turns)

            # Step 3: 打印报告
            print_report(game_name, game_info, results)

            all_game_results[game_name] = {
                "game_info": game_info,
                "results": results,
            }

        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()

    # ══ 综合分析 ══
    print(f"\n{'='*90}")
    print(f"  综合分析总结")
    print(f"{'='*90}")

    for game_name, data in all_game_results.items():
        results = data["results"]
        game_info = data["game_info"]

        total_played = sum(r["played_total"] for r in results)
        total_covered = sum(r["played_in_pred"] for r in results)
        total_pred_cards = sum(r["num_predictions"] for r in results)
        no_pred_turns = sum(1 for r in results if r["num_predictions"] == 0)
        seps = [r["prob_separation"] for r in results if r["prob_separation"] != 0]

        recall = total_covered / max(total_played, 1)
        avg_sep = sum(seps) / len(seps) if seps else 0

        print(f"\n  {game_name} (对手={game_info.get('opp_hero_class', '?')}):")
        print(f"    打出卡牌覆盖: {recall:.1%} ({total_covered}/{total_played})")
        print(f"    总预测卡牌数: {total_pred_cards}")
        print(f"    无预测回合:   {no_pred_turns}/{len(results)}")
        print(f"    概率区分度:   {avg_sep:.4f}")

        if total_pred_cards == 0:
            print(f"    🔴 问题：MCTS无预测输出")
            print(f"       原因：HandSampler依赖bayesian_state['top_decks']，")
            print(f"       BayesianOpponent可能无法获取候选卡组（对手职业未识别或数据库为空）")
        elif avg_sep > 0.05:
            print(f"    ✅ 有区分度：MCTS给已打出卡牌更高概率")
        elif avg_sep > 0:
            print(f"    ⚠️ 区分度弱：MCTS概率分布过于平坦")
        else:
            print(f"    ❌ 无区分度")

    # ══ 关键发现 ══
    print(f"\n{'='*90}")
    print(f"  关键发现与改进建议")
    print(f"{'='*90}")

    has_pred = any(
        sum(r["num_predictions"] for r in d["results"]) > 0
        for d in all_game_results.values()
    )

    if has_pred:
        print("""
  系统已能产出预测结果。下一步优化方向：
  1. 提高概率区分度：增加MCTS模拟次数，优化行为匹配权重
  2. 跨回合验证：利用对手多回合的行为一致性提升推断精度
  3. 卡牌效果引擎精确化：更精确的合法动作枚举和状态评估
  4. 实时数据驱动：接入Power.log实时GameState构建
""")
    else:
        print("""
  🔴 核心问题：MCTS 手牌推断系统当前无法产出预测结果

  根因分析：
  1. HandSampler.sample_worlds() 依赖 bayesian_state["top_decks"]
  2. BayesianOpponent 需要：(a) 对手职业 (b) hsreplay元数据缓存
  3. 当前测试环境中 BayesianOpponent.get_top_decks() 返回空列表
     可能原因：
     - 对手职业未正确识别
     - hsreplay缓存数据库中没有匹配的卡组
     - 对手打出卡牌数量不足以推断卡组

  修复路径：
  1. 确认 BayesianOpponent 的对手职业识别是否正确
  2. 确认 hsreplay_cache.db 中是否有对应职业的卡组
  3. 添加回退策略：当无候选卡组时，使用对手职业的标准卡牌池
""")

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
        json.dump(convert_sets(all_game_results), f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至: {output_path}")


if __name__ == "__main__":
    main()

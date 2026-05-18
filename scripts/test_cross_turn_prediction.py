#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_cross_turn_prediction.py — 跨回合预测验证

核心验证问题：当前回合的预测能否预测对手后续回合打出的牌？

这才是MCTS手牌推断的真正价值：
- 不是"对手刚打出X，我们预测了X"（已经知道了）
- 而是"对手未来会打出什么牌？我们的预测是否覆盖？"

测试流程：
1. 在对手回合T，使用当前已知信息运行MCTS预测
2. 对比预测结果与对手在T+1, T+2, ... 回合实际打出的牌
3. 计算：预测Top-K中包含对手后续打出牌的命中率

这比"当前回合区分度"更有意义，因为：
- 当前回合的打出牌已经被seen_cards过滤，不可能出现在预测中
- 但对手手中的其他牌（未打出），应该在预测Top-K中出现
- 如果对手在下回合打出某牌，且该牌在我们上回合的预测Top-K中，说明预测有效
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
logger = logging.getLogger("cross_turn")


def get_opponent_turn_data(log_path: str) -> Tuple[Dict, List[Dict]]:
    """解析Power.log，获取对手逐回合打出的卡牌。"""
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

    # 检测对手
    vis = []
    for p in game.players:
        count = sum(1 for e in getattr(p, "entities", [])
                    if getattr(e, "card_id", "") and e.tags.get(GameTag.ZONE) == Zone.HAND)
        vis.append(count)
    friendly_idx = 1 if vis[1] > vis[0] else 0
    opp_idx = 1 - friendly_idx

    our_ctrl = game.players[friendly_idx].tags.get(GameTag.CONTROLLER, friendly_idx + 1)
    opp_ctrl = game.players[opp_idx].tags.get(GameTag.CONTROLLER, opp_idx + 1)

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
    }

    # 逐行解析获取每回合对手打出的卡牌
    tracker2 = LogParser()
    current_turn = 0
    opp_turn_plays = defaultdict(list)

    with open(log_path, encoding="utf-8", errors="ignore") as f:
        current_show_entity = None
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            if "tag=TURN" in stripped and "GameEntity" in stripped:
                m = re.search(r"value=(\d+)", stripped)
                if m:
                    current_turn = int(m.group(1))

            if "SHOW_ENTITY" in stripped:
                m_id = re.search(r"id=(\d+)", stripped)
                m_cid = re.search(r"CardID=(\S+)", stripped)
                if m_id and m_cid:
                    current_show_entity = {
                        "eid": int(m_id.group(1)),
                        "card_id": m_cid.group(1),
                    }

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

            if current_show_entity and ("BLOCK_START" in stripped or "BLOCK_END" in stripped
                                        or "TAG_CHANGE" in stripped or "FULL_ENTITY" in stripped):
                se = current_show_entity
                ctrl = se.get("controller", 0)
                zone = se.get("zone", 0)
                ctype = se.get("card_type", 0)
                cid = se.get("card_id", "")

                if ctrl == opp_ctrl and cid and \
                   zone in (Zone.PLAY.value, Zone.GRAVEYARD.value, Zone.SECRET.value) and \
                   ctype not in (CardType.ENCHANTMENT.value, CardType.HERO_POWER.value):
                    if cid not in ("MUDAN_COIN1", "MUDAN_COIN2", "GAME_005", "TLC_COIN2"):
                        opp_turn_plays[current_turn].append(cid)

                current_show_entity = None

    # 构建对手回合数据（不再使用奇偶回合过滤）
    opponent_turns = []
    all_played_so_far = []

    for turn in sorted(opp_turn_plays.keys()):
        played = opp_turn_plays[turn]
        all_played_so_far.extend(played)

        if played:
            mana_available = min(10, (turn + 1) // 2)
            opponent_turns.append({
                "turn": turn,
                "played_cards": played,
                "all_played_so_far": list(all_played_so_far),
                "mana_available": mana_available,
                "opp_class": opp_hero_class,
            })

    return game_info, opponent_turns


def run_cross_turn_validation(game_info: Dict, opponent_turns: List[Dict]) -> List[Dict]:
    """跨回合预测验证。

    在对手回合T运行MCTS预测，对比对手在T+1回合实际打出的牌。
    """
    from analysis.utils.bayesian_opponent import BayesianOpponentModel
    from analysis.engine.opponent_hand_mcts import OpponentHandMCTS, ObservedBehavior
    from analysis.data.card_data import get_db

    opp_class = game_info.get("opp_hero_class", "")
    db = get_db()

    bayesian = BayesianOpponentModel(player_class=opp_class)

    results = []
    seen_card_ids = Counter()
    generated_cards = set()

    for idx, snap in enumerate(opponent_turns):
        turn = snap["turn"]
        played = snap["played_cards"]

        # 更新贝叶斯模型
        for cid in played:
            if cid not in generated_cards:
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
            seen_card_ids[cid] += 1

        top_decks = bayesian.get_top_decks(n=3)
        bayesian_state = {
            "top_decks": top_decks,
            "opp_class": opp_class,
        }

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

        # 运行MCTS预测
        mcts = OpponentHandMCTS(time_budget_ms=1500.0)
        try:
            preds = mcts.infer_hand_probabilities(
                bayesian_state=bayesian_state,
                observed=observed,
                seen_cards=dict(seen_card_ids),
                generated_cards=generated_cards,
                hand_size=max(1, 5 - turn // 4),
                time_budget_ms=1500.0,
            )
        except Exception as e:
            logger.warning("T%d MCTS失败: %s", turn, e)
            preds = {}

        # 收集对手后续回合打出的牌
        future_played = set()
        future_range = min(idx + 3, len(opponent_turns))  # 后续1-2回合
        for future_idx in range(idx + 1, future_range):
            future_played.update(opponent_turns[future_idx]["played_cards"])

        # 验证：预测Top-K是否包含对手后续打出的牌
        if preds:
            sorted_preds = sorted(preds.items(), key=lambda x: -x[1])
            top_k_cards = set(c for c, _ in sorted_preds[:10])
            top_k_hit = len(future_played & top_k_cards)
            top_k_total = len(future_played)

            # 贝叶斯Top-5预测（不含MCTS）
            bayesian_top5 = set()
            for deck_id, deck_name, prob in top_decks[:1]:
                deck_cards = mcts._sampler._get_deck_cards(deck_id)
                if deck_cards:
                    remaining = []
                    card_counts = Counter(deck_cards)
                    for dbf_id, count in card_counts.items():
                        cid = mcts._sampler._dbf_to_card_id(dbf_id)
                        if cid:
                            played_n = seen_card_ids.get(cid, 0)
                            rem = count - played_n
                            if rem > 0:
                                remaining.extend([cid] * rem)
                    # 取出现频率最高的10张
                    remaining_counter = Counter(remaining)
                    bayesian_top5 = set(c for c, _ in remaining_counter.most_common(10))
        else:
            top_k_hit = 0
            top_k_total = len(future_played)
            bayesian_top5 = set()

        bayesian_hit = len(future_played & bayesian_top5) if bayesian_top5 else 0

        result = {
            "turn": turn,
            "played_cards": played,
            "future_played": list(future_played),
            "num_predictions": len(preds),
            "top_k_hit": top_k_hit,
            "top_k_total": top_k_total,
            "bayesian_hit": bayesian_hit,
            "bayesian_total": top_k_total,
            "top_10": [(c, round(p, 3)) for c, p in sorted(preds.items(), key=lambda x: -x[1])[:10]] if preds else [],
        }
        results.append(result)

        # 打印
        def cname(cid):
            if db:
                data = db.get_card(cid)
                if data:
                    return data.get("name", cid)
            return cid

        future_names = [cname(c) for c in future_played]
        top10_str = ", ".join(f"{cname(c)}={p:.0%}" for c, p in result["top_10"][:5])
        logger.info(
            "T%d: 后续会出=%s, MCTS-Top10命中=%d/%d, 贝叶斯Top10命中=%d/%d, 预测=[%s]",
            turn, ",".join(future_names[:5]),
            top_k_hit, top_k_total,
            bayesian_hit, top_k_total,
            top10_str,
        )

    return results


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

        print(f"\n{'#'*90}")
        print(f"#  跨回合预测验证: {game_name}")
        print(f"{'#'*90}")

        try:
            game_info, opponent_turns = get_opponent_turn_data(log_path)
            logger.info("游戏信息: %s", game_info)
            logger.info("对手有打出卡牌的回合数: %d", len(opponent_turns))

            if not opponent_turns:
                print("  ⚠️ 未提取到对手打出卡牌数据")
                continue

            results = run_cross_turn_validation(game_info, opponent_turns)

            # 打印汇总
            total_future = sum(r["top_k_total"] for r in results)
            total_mcts_hits = sum(r["top_k_hit"] for r in results)
            total_bayesian_hits = sum(r["bayesian_hit"] for r in results)

            print(f"\n{'='*70}")
            print(f"  跨回合预测汇总: {game_name}")
            print(f"{'='*70}")
            print(f"  MCTS Top-10 命中后续出牌: {total_mcts_hits}/{total_future} ({total_mcts_hits/max(total_future,1):.1%})")
            print(f"  贝叶斯 Top-10 命中后续出牌: {total_bayesian_hits}/{total_future} ({total_bayesian_hits/max(total_future,1):.1%})")
            print(f"  MCTS 相对贝叶斯提升: {'+' if total_mcts_hits >= total_bayesian_hits else ''}{total_mcts_hits - total_bayesian_hits} 牌")
            print(f"\n  逐回合详情:")
            print(f"  {'T':>3} | {'后续出牌':>25} | {'MCTS命中':>8} | {'贝叶斯命中':>9}")
            print(f"  {'---':>3} | {'---':>25} | {'--------':>8} | {'---------':>9}")

            def cname(cid, db=None):
                if db is None:
                    from analysis.data.card_data import get_db as _get_db
                    db = _get_db()
                if db:
                    data = db.get_card(cid)
                    if data:
                        return data.get("name", cid)
                return cid

            for r in results:
                future_str = ",".join(cname(c) for c in r["future_played"][:4])
                print(
                    f"  T{r['turn']:>2} | {future_str:>25} | "
                    f"{r['top_k_hit']:>2}/{r['top_k_total']:<2} | "
                    f"{r['bayesian_hit']:>2}/{r['bayesian_total']:<2}"
                )

            all_results[game_name] = {
                "game_info": game_info,
                "results": results,
                "total_mcts_hits": total_mcts_hits,
                "total_bayesian_hits": total_bayesian_hits,
                "total_future": total_future,
            }

        except Exception as e:
            print(f"❌ 测试失败: {e}")
            import traceback
            traceback.print_exc()

    # 保存结果
    output_path = str(PROJECT_ROOT / "download" / "cross_turn_prediction_report.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    def convert_sets(obj):
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, Counter):
            return dict(obj)
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

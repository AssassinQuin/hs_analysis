#!/usr/bin/env python3
"""full_flow_sim.py — 全流程模拟验证脚本

使用 tracker + power.log 逐行解析模拟真实游戏进程，
验证 GameEngine 单例 + MCTS + 贝叶斯推断的全链路正确性。

核心验证点:
1. GameEngine 单例 — MCTSEngine 和 BayesianOpponentModel 只有一份
2. 逐行解析 — CoreLogMonitor 模拟真实 Power.log 输入
3. 对手出牌追踪 — 观测对手实际打出什么牌
4. 概率推断验证 — 对比贝叶斯预测与实际出牌的差异
5. 全流程正确性 — 从 Power.log 到 MCTS 决策的完整路径

Usage:
    python scripts/full_flow_sim.py
    python scripts/full_flow_sim.py --budget 3000 --max-turns 5
    python scripts/full_flow_sim.py --log-dir Hearthstone_2026_04_23_08_43_35
"""

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.search.engine_adapter import GameEngine, UnifiedSearchResult
from analysis.search.abilities.enumeration import enumerate_legal_actions
from analysis.search.abilities.actions import ActionType
from analysis.utils.score_provider import load_scores_into_hand
from hearthstone.enums import GameTag, Zone as HZone, CardType as HCardType


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class OppCardPlay:
    """对手出牌记录"""
    turn: int
    card_id: str
    card_name: str
    zone_from: str  # HAND, DECK, SETASIDE
    card_type: str
    source: str  # DECK, GENERATED, UNKNOWN

@dataclass
class PredictionRecord:
    """每回合的概率预测记录"""
    turn: int
    opp_hand_count: int
    bayesian_top_deck: str
    bayesian_top_prob: float
    bayesian_locked: bool
    predicted_hand_types: List[dict]
    known_hand_cards: List[str]
    actual_opp_plays: List[OppCardPlay] = field(default_factory=list)

@dataclass
class FlowReport:
    """全流程模拟报告"""
    log_file: str
    game_turns: int = 0
    our_decisions: int = 0
    opp_plays_total: int = 0
    opp_plays_from_deck: int = 0
    opp_plays_generated: int = 0
    predictions: List[PredictionRecord] = field(default_factory=list)
    opp_plays: List[OppCardPlay] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    total_mcts_time_ms: float = 0.0
    # 引擎单例验证
    engine_id: int = 0
    mcts_engine_id: int = 0
    bayesian_model_id: int = 0


# ── 显示辅助 ──────────────────────────────────────────────

def _card_display(card) -> str:
    name = getattr(card, 'display_name', '') or getattr(card, 'name', '') or '???'
    cost = getattr(card, 'cost', '?')
    return f"{name}({cost})"

def _minion_display(m) -> str:
    name = getattr(m, 'name', '') or getattr(m, 'display_name', '') or '???'
    return f"{name}({m.attack}/{m.health})"


# ── 全流程模拟核心 ─────────────────────────────────────────

def run_full_flow_simulation(
    log_path: str,
    budget_ms: float = 3000.0,
    max_turns: int = 0,
    log_dir: str = None,
) -> FlowReport:
    """运行全流程模拟验证。

    架构:
    Power.log → 逐行读取 → GameTracker → StateBridge → GameEngine(单例).search()

    Returns:
        FlowReport 包含完整的模拟结果和验证数据
    """
    report = FlowReport(log_file=str(log_path))

    log_path = Path(log_path)
    if not log_path.exists():
        report.errors.append(f"File not found: {log_path}")
        return report

    # ── 1. 创建单例引擎 ──
    game_engine = GameEngine(params={
        "time_budget_ms": budget_ms,
        "num_worlds": 5,
        "uct_constant": 0.5,
        "time_decay_gamma": 0.4,
        "max_actions_per_turn": 8,
    })
    report.engine_id = id(game_engine)
    report.mcts_engine_id = id(game_engine.mcts_engine)
    report.bayesian_model_id = id(game_engine.bayesian_model)

    print(f"[引擎单例] GameEngine={report.engine_id}  MCTS={report.mcts_engine_id}  Bayesian={report.bayesian_model_id}")

    # ── 2. 创建解析器 ──
    tracker = GameTracker()
    bridge = StateBridge(entity_cache=tracker.entity_cache)

    # ── 3. 逐行解析 Power.log ──
    last_turn = -1
    prev_opp_dbf_ids: Set[int] = set()
    turn_opponent_plays: List[OppCardPlay] = []

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            event = tracker.feed_line(line.strip())

            if event == 'game_start':
                print(f"\n{'='*60}")
                print(f"新游戏开始")
                print(f"{'='*60}")
                last_turn = -1
                prev_opp_dbf_ids = set()
                turn_opponent_plays = []

                # 检测对手职业
                opp_class = None
                game = tracker.export_entities()
                if game and hasattr(game, 'players') and len(game.players) >= 2:
                    _friendly_idx = DecisionLoop_detect_friendly(game)
                    opp_player = game.players[1 - _friendly_idx]
                    for ent in getattr(opp_player, 'entities', []):
                        tags = getattr(ent, 'tags', {})
                        if (tags.get(GameTag.ZONE) == HZone.PLAY and
                                tags.get(GameTag.CARDTYPE) == HCardType.HERO):
                            cls_val = tags.get(GameTag.CLASS, 0)
                            if hasattr(cls_val, 'name'):
                                opp_class = cls_val.name
                            elif isinstance(cls_val, int):
                                try:
                                    from hearthstone.enums import CardClass
                                    opp_class = CardClass(cls_val).name
                                except ValueError:
                                    pass
                            break

                game_engine.on_game_start(opp_class=opp_class)
                # 验证单例: game_start 后引擎 ID 不应改变
                assert id(game_engine.mcts_engine) == report.mcts_engine_id, \
                    f"MCTS engine singleton violated! {id(game_engine.mcts_engine)} != {report.mcts_engine_id}"
                print(f"  对手职业: {opp_class or '未知'}  |  贝叶斯原型: {len(game_engine.bayesian_model.decks)}")

            elif event == 'game_end':
                print(f"\n游戏结束 — {report.our_decisions} 次决策, "
                      f"对手出牌 {report.opp_plays_total} (牌库={report.opp_plays_from_deck}, "
                      f"衍生={report.opp_plays_generated})")
                game_engine.on_game_end()
                break

            elif event == 'turn_start':
                game = tracker.export_entities()
                if not game:
                    continue

                _friendly_idx = DecisionLoop_detect_friendly(game)
                state = bridge.convert(game, player_index=_friendly_idx)
                if not state or state.turn_number <= 0:
                    continue
                current_turn = state.turn_number
                if current_turn == last_turn:
                    continue

                report.game_turns = max(report.game_turns, current_turn)

                # 判断是谁的回合
                is_our_turn = (current_turn % 2 != _friendly_idx)

                # ── 收集对手出牌信息 ──
                _opp_idx = 1 - _friendly_idx
                opp_player = game.players[_opp_idx]
                current_opp_dbf_ids = set()
                card_id_to_dbf = {}
                bayesian = game_engine.bayesian_model

                # 构建卡牌ID映射
                try:
                    for dbf, info in bayesian.cards_by_dbf.items():
                        cid = info.get("id", "")
                        if cid:
                            card_id_to_dbf[cid] = dbf
                except Exception:
                    pass
                try:
                    from analysis.data.hsdb import get_db as _get_hsdb
                    _hsdb = _get_hsdb()
                    _hsdb_lookup = _hsdb.card_id_to_dbf
                except Exception:
                    _hsdb_lookup = None

                # 从对手的实体中收集已打出的卡牌
                turn_plays = []
                for ent in getattr(opp_player, 'entities', []):
                    cid = getattr(ent, 'card_id', '') or ''
                    if not cid:
                        continue
                    zone = ent.tags.get(GameTag.ZONE, 0) if hasattr(ent, 'tags') else 0
                    ctype = ent.tags.get(GameTag.CARDTYPE, 0)
                    if zone in (HZone.PLAY, HZone.SECRET):
                        if ctype in (HCardType.HERO, HCardType.HERO_POWER, HCardType.ENCHANTMENT):
                            continue
                        dbf_id = card_id_to_dbf.get(cid, 0)
                        if not dbf_id and _hsdb_lookup:
                            dbf_id = _hsdb_lookup(cid) or 0
                        if dbf_id:
                            current_opp_dbf_ids.add(dbf_id)

                        # 查卡牌元数据获取来源分类
                        try:
                            card_meta = _hsdb.get_card(cid) if _hsdb else {}
                        except Exception:
                            card_meta = {}
                        source = "UNKNOWN"
                        if card_meta:
                            if not card_meta.get("collectible", False):
                                source = "GENERATED"
                            else:
                                source = "DECK"

                        play = OppCardPlay(
                            turn=current_turn,
                            card_id=cid,
                            card_name=card_meta.get("name", cid),
                            zone_from="HAND",
                            card_type=str(ctype),
                            source=source,
                        )
                        turn_plays.append(play)

                # 更新贝叶斯
                bayesian_updates = game_engine.update_bayesian(current_opp_dbf_ids)
                for update in bayesian_updates:
                    print(f"  [贝叶斯] 对手打出: {update['name']} → 推断: "
                          f"{update['top_deck']}@{update['top_prob']:.0%}"
                          f"{' [LOCKED]' if update['locked'] else ''}")

                # 记录对手出牌
                for play in turn_plays:
                    report.opp_plays.append(play)
                    report.opp_plays_total += 1
                    if play.source == "DECK":
                        report.opp_plays_from_deck += 1
                    elif play.source == "GENERATED":
                        report.opp_plays_generated += 1

                # ── 收集预测记录 ──
                top_decks = bayesian.get_top_decks(3)
                top_deck_name = top_decks[0][1] if top_decks else "?"
                top_deck_prob = top_decks[0][2] if top_decks else 0.0
                known_hand = []
                if hasattr(state.opponent, 'opp_known_cards'):
                    for kc in state.opponent.opp_known_cards:
                        cid = kc.get("card_id", "") if isinstance(kc, dict) else getattr(kc, "card_id", "")
                        if cid:
                            known_hand.append(cid)

                pred = PredictionRecord(
                    turn=current_turn,
                    opp_hand_count=state.opponent.hand_count,
                    bayesian_top_deck=top_deck_name,
                    bayesian_top_prob=top_deck_prob,
                    bayesian_locked=bayesian.locked,
                    predicted_hand_types=[],
                    known_hand_cards=known_hand,
                    actual_opp_plays=turn_plays,
                )
                report.predictions.append(pred)

                # ── 对手回合：只显示推断 ──
                if not is_our_turn:
                    print(f"\n┌─ Turn {current_turn} (对手回合) ────────────")
                    print(f"│ 对手手牌: {state.opponent.hand_count}")
                    if top_decks:
                        for rank, (dbf, name, prob) in enumerate(top_decks[:3], 1):
                            print(f"│ 推断#{rank}: {name} ({prob:.0%})")
                    if turn_plays:
                        for p in turn_plays:
                            print(f"│ 实际出牌: {p.card_name} (来源={p.source})")
                    print(f"└──────────────────────────")
                    last_turn = current_turn
                    continue

                # ── 我们的回合：MCTS 决策 ──
                try:
                    legal = enumerate_legal_actions(state)
                    non_end = [a for a in legal if a.action_type != ActionType.END_TURN]
                except Exception:
                    non_end = []

                print(f"\n┌─ Turn {current_turn} (你的回合) ────────────")
                print(f"│ Hero: {state.hero.hp}HP/{state.hero.armor}A  "
                      f"Mana: {state.mana.available}/{state.mana.max_mana}  "
                      f"Hand: {len(state.hand)}  Board: {len(state.board)}  "
                      f"Legal: {len(non_end)} actions")
                if state.hand:
                    hand_str = " ".join(f"[{_card_display(c)}]" for c in state.hand)
                    print(f"│ Hand: {hand_str}")
                if state.board:
                    board_str = " ".join(f"[{_minion_display(m)}]" for m in state.board)
                    print(f"│ Board: {board_str}")
                if state.opponent.board:
                    opp_str = " ".join(f"[{_minion_display(m)}]" for m in state.opponent.board)
                    print(f"│ Opp Board: {opp_str}")

                # 显示推断
                print(f"│ 对手手牌: {state.opponent.hand_count}")
                if top_decks:
                    for rank, (dbf, name, prob) in enumerate(top_decks[:3], 1):
                        print(f"│ 推断#{rank}: {name} ({prob:.0%})"
                              f"{' [LOCKED]' if bayesian.locked else ''}")
                if turn_plays:
                    for p in turn_plays:
                        print(f"│ 对手上回合出牌: {p.card_name} (来源={p.source})")

                # MCTS 搜索
                if len(non_end) <= 1:
                    if non_end:
                        print(f"│ Quick play → {non_end[0].describe(state)}")
                    else:
                        print(f"│ No actions available")
                    print(f"└──────────────────────────")
                    last_turn = current_turn
                    report.our_decisions += 1
                    continue

                # 验证单例: 每次搜索后引擎 ID 不变
                pre_mcts_id = id(game_engine.mcts_engine)
                pre_bayes_id = id(game_engine.bayesian_model)

                t0 = time.time()
                try:
                    result = game_engine.search(state, time_budget_ms=budget_ms)
                    elapsed = (time.time() - t0) * 1000
                    report.total_mcts_time_ms += elapsed

                    # 验证单例
                    assert id(game_engine.mcts_engine) == pre_mcts_id, \
                        f"MCTS engine replaced after search! {id(game_engine.mcts_engine)} != {pre_mcts_id}"
                    assert id(game_engine.bayesian_model) == pre_bayes_id, \
                        f"Bayesian model replaced after search! {id(game_engine.bayesian_model)} != {pre_bayes_id}"

                    s = result.mcts_stats
                    print(f"│")
                    print(f"│ MCTS Plan ({len(result.best_sequence)} steps):")
                    for i, a in enumerate(result.best_sequence):
                        marker = ">>>" if i == 0 else "   "
                        print(f"│ {marker} {i+1}. {a.describe(state)}")
                    print(f"│ Fitness: {result.fitness:+.4f}")
                    print(f"│ Iters: {s.iterations}  Nodes: {s.nodes_created}  "
                          f"Evals: {s.evaluations_done}  Worlds: {s.world_count}")
                    print(f"│ Time: {s.time_used_ms:.0f}ms")

                    report.our_decisions += 1
                except Exception as e:
                    import traceback
                    print(f"│ Error: {e}")
                    print(f"│ {traceback.format_exc()[:200]}")
                    report.errors.append(f"Turn {current_turn}: {e}")

                print(f"└──────────────────────────")
                last_turn = current_turn

                if max_turns > 0 and report.our_decisions >= max_turns:
                    print(f"\n达到最大决策数 ({max_turns})")
                    break

    return report


def DecisionLoop_detect_friendly(game) -> int:
    """检测友方玩家索引"""
    if not hasattr(game, 'players') or len(game.players) < 2:
        return 0
    visible = []
    for p in game.players:
        count = sum(
            1 for e in getattr(p, 'entities', [])
            if getattr(e, 'card_id', '') and
               getattr(e, 'tags', {}).get(GameTag.ZONE) == HZone.HAND
        )
        visible.append(count)
    return 1 if visible[1] > visible[0] else 0


# ── 分析报告 ──────────────────────────────────────────────

def analyze_report(report: FlowReport) -> str:
    """分析全流程模拟报告，输出概率推断问题诊断。"""
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"全流程模拟分析报告")
    lines.append(f"{'='*70}")
    lines.append(f"日志文件: {report.log_file}")
    lines.append(f"游戏回合: {report.game_turns}")
    lines.append(f"我方决策: {report.our_decisions}")
    lines.append(f"对手出牌: {report.opp_plays_total} (牌库={report.opp_plays_from_deck}, 衍生={report.opp_plays_generated})")
    lines.append(f"MCTS总耗时: {report.total_mcts_time_ms:.0f}ms")
    lines.append(f"")

    # ── 引擎单例验证 ──
    lines.append(f"── 引擎单例验证 ──")
    lines.append(f"  GameEngine ID: {report.engine_id}")
    lines.append(f"  MCTSEngine ID: {report.mcts_engine_id} (应始终一致)")
    lines.append(f"  BayesianModel ID: {report.bayesian_model_id} (应始终一致)")
    lines.append(f"")

    # ── 概率推断准确性分析 ──
    lines.append(f"── 概率推断准确性 ──")
    if not report.predictions:
        lines.append(f"  无预测记录")
    else:
        locked_count = sum(1 for p in report.predictions if p.bayesian_locked)
        total_preds = len(report.predictions)
        lines.append(f"  预测回合数: {total_preds}")
        lines.append(f"  锁定卡组: {locked_count}/{total_preds} ({locked_count/max(total_preds,1):.0%})")

        # 对比: 对手实际出牌 vs 贝叶斯推断的卡组
        actual_deck_cards = set()
        actual_generated_cards = set()
        for play in report.opp_plays:
            if play.source == "DECK":
                actual_deck_cards.add(play.card_id)
            elif play.source == "GENERATED":
                actual_generated_cards.add(play.card_id)

        lines.append(f"  对手实际牌库牌: {len(actual_deck_cards)} 张唯一")
        lines.append(f"  对手衍生牌: {len(actual_generated_cards)} 张唯一")
        lines.append(f"")

        # ── 逐回合推断 vs 实际 ──
        lines.append(f"── 逐回合推断 vs 实际 ──")
        for pred in report.predictions:
            lines.append(f"  Turn {pred.turn}:")
            lines.append(f"    对手手牌: {pred.opp_hand_count}")
            lines.append(f"    贝叶斯推断: {pred.bayesian_top_deck} ({pred.bayesian_top_prob:.0%})"
                         f"{' [LOCKED]' if pred.bayesian_locked else ''}")
            if pred.known_hand_cards:
                lines.append(f"    已知手牌: {', '.join(pred.known_hand_cards[:5])}")
            if pred.actual_opp_plays:
                for play in pred.actual_opp_plays:
                    lines.append(f"    实际出牌: {play.card_name} (来源={play.source})")

    # ── 错误汇总 ──
    if report.errors:
        lines.append(f"")
        lines.append(f"── 错误汇总 ──")
        for err in report.errors[:20]:
            lines.append(f"  {err}")

    return "\n".join(lines)


# ── 主入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="全流程模拟验证 — Tracker + Power.log 逐行解析 + MCTS 单例引擎")
    parser.add_argument("log_path", nargs="?", default="Power.log",
                        help="Power.log path")
    parser.add_argument("--budget", "-b", type=float, default=3000.0,
                        help="MCTS 单步预算 ms (default: 3000)")
    parser.add_argument("--max-turns", type=int, default=0,
                        help="最大决策回合数 (0=全部)")
    parser.add_argument("--log-dir", type=str, default=None,
                        help="游戏日志目录 (含 Decks.log)")
    parser.add_argument("--output-report", type=str, default=None,
                        help="报告输出路径 (default: logs/full_flow_report.txt)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

    # 解析路径
    log_path = args.log_path
    if args.log_dir:
        log_dir_path = Path(args.log_dir)
        power_log = log_dir_path / "Power.log"
        if power_log.exists():
            log_path = str(power_log)

    # 如果是 tests/fixtures 下的测试日志
    if not Path(log_path).exists():
        fixture_paths = [
            Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "game1_warrior_vs_warrior_8t.log",
            Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "game3_dk_vs_rogue_21t.log",
            Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "game7_rogue_vs_priest_26t.log",
        ]
        for fp in fixture_paths:
            if fp.exists():
                log_path = str(fp)
                print(f"使用测试日志: {fp.name}")
                break

    print(f"{'='*60}")
    print(f"全流程模拟验证")
    print(f"文件: {log_path}")
    print(f"预算: {args.budget}ms")
    print(f"{'='*60}")

    # 运行模拟
    report = run_full_flow_simulation(
        log_path=log_path,
        budget_ms=args.budget,
        max_turns=args.max_turns,
        log_dir=args.log_dir,
    )

    # 生成分析报告
    analysis = analyze_report(report)
    print(analysis)

    # 保存报告
    report_path = args.output_report
    if not report_path:
        report_dir = Path(__file__).resolve().parent.parent / "logs"
        report_dir.mkdir(exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        report_path = str(report_dir / f"full_flow_{ts}.txt")

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(analysis)
        f.write(f"\n\n--- 原始数据 ---\n")
        # 保存预测记录的 JSON
        pred_data = []
        for p in report.predictions:
            pred_data.append({
                "turn": p.turn,
                "opp_hand_count": p.opp_hand_count,
                "bayesian_top_deck": p.bayesian_top_deck,
                "bayesian_top_prob": p.bayesian_top_prob,
                "bayesian_locked": p.bayesian_locked,
                "known_hand_cards": p.known_hand_cards,
                "actual_opp_plays": [
                    {"card_id": play.card_id, "name": play.card_name, "source": play.source}
                    for play in p.actual_opp_plays
                ],
            })
        f.write(json.dumps(pred_data, ensure_ascii=False, indent=2))

    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()

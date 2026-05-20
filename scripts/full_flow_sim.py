#!/usr/bin/env python3
"""full_flow_sim.py — 全流程模拟验证脚本

使用 CoreLogMonitor（含 GlobalTracker 桥接）+ power.log 逐行解析模拟真实游戏进程，
验证 GameEngine 单例 + MCTS + 贝叶斯推断的全链路正确性。

核心验证点:
1. GameEngine 单例 — MCTSEngine 和 BayesianOpponentModel 只有一份
2. CoreLogMonitor 集成 — 完整的实体桥接到 GlobalTracker
3. 贝叶斯延迟初始化 — 直到对手职业被检测到才创建 BayesianOpponentModel
4. 对手出牌追踪 — 观测对手实际打出什么牌，GlobalTracker 驱动贝叶斯更新
5. 概率推断验证 — 对比贝叶斯预测与实际出牌的差异
6. 全流程正确性 — 从 Power.log 到 MCTS 决策的完整路径

架构:
    Power.log → 逐行读取 → CoreLogMonitor
        ├── GameTracker.feed_line() → entity_cache 更新
        ├── _detect_zone_changes_from_cache() → GlobalTracker.on_zone_change()
        ├── _bridge_new_entities() → GlobalTracker.on_full_entity/on_show_entity()
        └── 事件分发 → game_start / turn_start / game_end
            ├── game_start → GameEngine.on_game_start(opp_class) [延迟贝叶斯]
            ├── turn_start → StateBridge.convert(global_state) → GameEngine.search()
            └── game_end → GameEngine.on_game_end()

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

from tracker.log_monitor import CoreLogMonitor
from analysis.watcher.state_bridge import StateBridge
from analysis.search.engine_adapter import GameEngine, UnifiedSearchResult
from analysis.effects.rules.enumeration import enumerate_legal_actions
from analysis.effects.types import ActionKind as ActionType
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
    bayesian_initialized: bool
    predicted_hand_types: List[dict]
    known_hand_cards: List[str]
    opp_secrets: List[str]
    opp_known_cards_count: int
    opp_deck_remaining: int
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
    # CoreLogMonitor 集成状态
    monitor_entities_bridged: int = 0
    global_tracker_opp_class: str = ""
    bayesian_lazy_init_turn: int = 0  # 贝叶斯延迟初始化的回合数


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
    Power.log → 逐行读取 → CoreLogMonitor(GameTracker + GlobalTracker)
        → StateBridge(global_state) → GameEngine(单例).search()

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
        "debug_mode": True,
        "log_interval": 200,
    })
    report.engine_id = id(game_engine)
    report.mcts_engine_id = id(game_engine.mcts_engine)
    # 注意: bayesian_model 此时是默认实例（无职业过滤），on_game_start 后会被延迟初始化

    print(f"[引擎单例] GameEngine={report.engine_id}  MCTS={report.mcts_engine_id}")

    # ── 2. 创建 CoreLogMonitor（含 GlobalTracker 桥接）──
    monitor = CoreLogMonitor()
    # StateBridge 使用 CoreLogMonitor 的 GameTracker 的 entity_cache
    bridge = StateBridge(entity_cache=monitor.game_tracker.entity_cache)

    # ── 3. 逐行解析 Power.log ──
    last_turn = -1
    bayesian_initialized_in_turn = 0  # 记录贝叶斯何时被初始化
    opp_class_detected = False

    # 追踪对手出牌（从 GlobalTracker 的状态中提取）
    prev_opp_known_card_ids: Set[str] = set()

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # ── 解析 PlayerName 行（CoreLogMonitor 内部也会做，但我们先喂行） ──
            # 先喂入 CoreLogMonitor 的 _process_lines 逻辑
            event = monitor.game_tracker.feed_line(line)
            monitor._parse_player_name_line(line)

            if event == 'game_start':
                print(f"\n{'='*60}")
                print(f"新游戏开始")
                print(f"{'='*60}")
                last_turn = -1
                prev_opp_known_card_ids = set()
                bayesian_initialized_in_turn = 0
                opp_class_detected = False

                # 触发 CoreLogMonitor 的游戏开始流程
                monitor._bridged_entities.clear()
                monitor._last_known_zones.clear()
                monitor._last_known_card_ids.clear()
                monitor._first_player_detected = False
                monitor._on_game_start()

                # 从 GlobalTracker 获取对手职业
                gt_state = monitor.global_tracker.state
                opp_class = gt_state.opp_hero_class or None
                if opp_class and opp_class != "UNKNOWN":
                    opp_class_detected = True
                    report.global_tracker_opp_class = opp_class

                # GameEngine 延迟初始化贝叶斯模型
                # 只有在对手职业已知时才传入 opp_class
                game_engine.on_game_start(opp_class=opp_class if opp_class_detected else None)

                # 验证单例: game_start 后 MCTS 引擎 ID 不应改变
                assert id(game_engine.mcts_engine) == report.mcts_engine_id, \
                    f"MCTS engine singleton violated! {id(game_engine.mcts_engine)} != {report.mcts_engine_id}"

                # 记录贝叶斯模型状态
                report.bayesian_model_id = id(game_engine.bayesian_model) if game_engine.bayesian_model else 0
                bayesian_decks = len(game_engine.bayesian_model.decks) if game_engine.bayesian_model else 0
                print(f"  对手职业: {opp_class or '未知'}  |  贝叶斯原型: {bayesian_decks}")
                print(f"  GlobalTracker opp_class: {gt_state.opp_hero_class}")
                print(f"  贝叶斯延迟初始化: {'已初始化' if opp_class_detected else '等待职业检测'}")

            elif event == 'game_end':
                print(f"\n游戏结束 — {report.our_decisions} 次决策, "
                      f"对手出牌 {report.opp_plays_total} (牌库={report.opp_plays_from_deck}, "
                      f"衍生={report.opp_plays_generated})")
                game_engine.on_game_end()
                monitor._on_game_end()
                break

            elif event == 'turn_start':
                # 先桥接新实体和区域变化到 GlobalTracker
                monitor._detect_zone_changes_from_cache()
                monitor._detect_first_player_from_cache()
                monitor._bridge_new_entities()
                monitor._try_enrich_player_info()

                game = monitor.game_tracker.export_entities()
                if not game:
                    continue

                # 使用 CoreLogMonitor 的 _detect_my_idx（更可靠的玩家检测）
                players = list(game.players)
                _friendly_idx = monitor._detect_my_idx(
                    players,
                    saved_our_controller=monitor.global_tracker.our_controller,
                )

                # 获取 GlobalTracker 的状态用于 enrich
                global_state = monitor.global_tracker.state

                # 检查对手职业是否刚刚被检测到（延迟初始化贝叶斯）
                if not opp_class_detected and global_state.opp_hero_class and global_state.opp_hero_class != "UNKNOWN":
                    opp_class_detected = True
                    report.global_tracker_opp_class = global_state.opp_hero_class
                    # 通知 GameEngine 对手职业已检测到
                    game_engine.on_opp_class_detected(global_state.opp_hero_class)
                    bayesian_initialized_in_turn = global_state.current_turn or 0
                    report.bayesian_lazy_init_turn = bayesian_initialized_in_turn
                    bayesian_decks = len(game_engine.bayesian_model.decks) if game_engine.bayesian_model else 0
                    print(f"  [延迟初始化] Turn {bayesian_initialized_in_turn}: "
                          f"对手职业={global_state.opp_hero_class}, 贝叶斯原型={bayesian_decks}")

                # 用 global_state 富集 GameState
                state = bridge.convert(game, player_index=_friendly_idx, global_state=global_state)
                if not state or state.turn_number <= 0:
                    continue
                current_turn = state.turn_number
                if current_turn == last_turn:
                    continue

                # 通知 GlobalTracker 回合切换
                monitor.global_tracker.on_turn_change(current_turn)

                report.game_turns = max(report.game_turns, current_turn)

                # 判断是谁的回合
                is_our_turn = (current_turn % 2 != _friendly_idx)

                # ── 从 GlobalTracker 获取对手追踪信息 ──
                gt = monitor.global_tracker
                gt_state = global_state
                bayesian_state = gt.get_bayesian_state()
                known_hand = gt.get_opp_known_hand()
                card_breakdown = gt.get_opp_card_breakdown()

                # ── 收集对手出牌信息（从 GlobalTracker 的已知卡牌 diff） ──
                current_opp_known: Set[str] = set()
                for kc in gt_state.opp_known_cards:
                    cid = kc.card_id
                    if cid:
                        current_opp_known.add(cid)

                new_opp_cards = current_opp_known - prev_opp_known_card_ids
                turn_plays = []
                for cid in new_opp_cards:
                    # 查卡牌元数据
                    try:
                        from analysis.card.data.card_data import get_db as _get_db
                        _hsdb = _get_db()
                        card_meta = _hsdb.get_card(cid) or {}
                    except Exception:
                        card_meta = {}

                    source = "UNKNOWN"
                    if card_meta:
                        if not card_meta.get("collectible", False):
                            source = "GENERATED"
                        else:
                            source = "DECK"

                    # 尝试从 GlobalTracker 的已知卡牌中获取来源
                    for kc in gt_state.opp_known_cards:
                        if kc.card_id == cid:
                            source = kc.source.value if hasattr(kc.source, 'value') else str(kc.source)
                            break

                    play = OppCardPlay(
                        turn=current_turn,
                        card_id=cid,
                        card_name=card_meta.get("name", cid),
                        zone_from="HAND",
                        card_type=str(card_meta.get("type", "")),
                        source=source,
                    )
                    turn_plays.append(play)

                prev_opp_known_card_ids = current_opp_known

                # 记录对手出牌
                for play in turn_plays:
                    report.opp_plays.append(play)
                    report.opp_plays_total += 1
                    if play.source == "DECK":
                        report.opp_plays_from_deck += 1
                    elif play.source == "GENERATED":
                        report.opp_plays_generated += 1

                # ── 收集预测记录 ──
                top_decks = bayesian_state.get("top_decks", [])
                top_deck_name = top_decks[0][1] if top_decks else "?"
                top_deck_prob = top_decks[0][2] if top_decks else 0.0
                locked_deck = bayesian_state.get("locked_deck_id")
                known_hand_cards = [kc.get("card_id", "") if isinstance(kc, dict) else getattr(kc, "card_id", "") for kc in (known_hand or [])]

                pred = PredictionRecord(
                    turn=current_turn,
                    opp_hand_count=state.opponent.hand_count,
                    bayesian_top_deck=top_deck_name,
                    bayesian_top_prob=top_deck_prob,
                    bayesian_locked=locked_deck is not None,
                    bayesian_initialized=bayesian_state.get("archetype_name") is not None,
                    predicted_hand_types=card_breakdown or [],
                    known_hand_cards=known_hand_cards,
                    opp_secrets=list(gt_state.opp_secrets),
                    opp_known_cards_count=len(gt_state.opp_known_cards),
                    opp_deck_remaining=gt_state.opp_deck_remaining,
                    actual_opp_plays=turn_plays,
                )
                report.predictions.append(pred)

                # 记录桥接实体数量
                report.monitor_entities_bridged = len(monitor._bridged_entities)

                # ── 对手回合：只显示推断 ──
                if not is_our_turn:
                    print(f"\n┌─ Turn {current_turn} (对手回合) ────────────")
                    print(f"│ 对手手牌: {state.opponent.hand_count}  牌库: {gt_state.opp_deck_remaining}")
                    print(f"│ 已桥接实体: {len(monitor._bridged_entities)}  已知卡牌: {len(gt_state.opp_known_cards)}")
                    if gt_state.opp_secrets:
                        print(f"│ 奥秘: {', '.join(gt_state.opp_secrets)}")
                    if top_decks:
                        for rank, (dbf, name, prob) in enumerate(top_decks[:3], 1):
                            print(f"│ 推断#{rank}: {name} ({prob:.0%})"
                                  f"{' [LOCKED]' if locked_deck else ''}")
                    if turn_plays:
                        for p in turn_plays:
                            print(f"│ 实际出牌: {p.card_name} (来源={p.source})")
                    if known_hand_cards:
                        print(f"│ 已知手牌: {', '.join(known_hand_cards[:5])}")
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
                print(f"│ 已桥接实体: {len(monitor._bridged_entities)}  "
                      f"对手已知卡牌: {len(gt_state.opp_known_cards)}")
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
                print(f"│ 对手手牌: {state.opponent.hand_count}  牌库: {gt_state.opp_deck_remaining}")
                if gt_state.opp_secrets:
                    print(f"│ 奥秘: {', '.join(gt_state.opp_secrets)}")
                if top_decks:
                    for rank, (dbf, name, prob) in enumerate(top_decks[:3], 1):
                        print(f"│ 推断#{rank}: {name} ({prob:.0%})"
                              f"{' [LOCKED]' if locked_deck else ''}")
                if turn_plays:
                    for p in turn_plays:
                        print(f"│ 对手上回合出牌: {p.card_name} (来源={p.source})")
                if known_hand_cards:
                    print(f"│ 已知手牌: {', '.join(known_hand_cards[:5])}")
                if bayesian_state.get("playstyle") and bayesian_state["playstyle"] != "unknown":
                    print(f"│ 对手风格: {bayesian_state['playstyle']}")

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
                pre_bayes_id = id(game_engine.bayesian_model) if game_engine.bayesian_model else 0

                t0 = time.time()
                try:
                    # 获取对手风格
                    opp_playstyle = bayesian_state.get("playstyle", "unknown")
                    result = game_engine.search(state, time_budget_ms=budget_ms,
                                                opp_playstyle=opp_playstyle)
                    elapsed = (time.time() - t0) * 1000
                    report.total_mcts_time_ms += elapsed

                    # 验证单例
                    assert id(game_engine.mcts_engine) == pre_mcts_id, \
                        f"MCTS engine replaced after search! {id(game_engine.mcts_engine)} != {pre_mcts_id}"
                    if game_engine.bayesian_model:
                        assert id(game_engine.bayesian_model) == pre_bayes_id, \
                            f"Bayesian model replaced after search! {id(game_engine.bayesian_model)} != {pre_bayes_id}"

                    s = result.mcts_stats
                    print(f"│")
                    print(f"│ MCTS Plan ({len(result.best_sequence)} steps):")
                    for i, a in enumerate(result.best_sequence):
                        marker = ">>>" if i == 0 else "   "
                        print(f"│ {marker} {i+1}. {a.describe(state)}")
                    print(f"│ Fitness: {result.fitness:+.4f}")

                    # Print detailed MCTS debug info
                    print_mcts_search_detail(result, state)

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

    # ── 最终桥接统计 ──
    report.monitor_entities_bridged = len(monitor._bridged_entities)

    return report


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
    lines.append(f"  BayesianModel ID: {report.bayesian_model_id}")
    lines.append(f"")

    # ── CoreLogMonitor 集成验证 ──
    lines.append(f"── CoreLogMonitor 集成验证 ──")
    lines.append(f"  已桥接实体数: {report.monitor_entities_bridged}")
    lines.append(f"  GlobalTracker 对手职业: {report.global_tracker_opp_class or '未检测到'}")
    lines.append(f"  贝叶斯延迟初始化回合: {f'Turn {report.bayesian_lazy_init_turn}' if report.bayesian_lazy_init_turn > 0 else '游戏开始时即初始化'}")
    lines.append(f"")

    # ── 概率推断准确性分析 ──
    lines.append(f"── 概率推断准确性 ──")
    if not report.predictions:
        lines.append(f"  无预测记录")
    else:
        locked_count = sum(1 for p in report.predictions if p.bayesian_locked)
        initialized_count = sum(1 for p in report.predictions if p.bayesian_initialized)
        total_preds = len(report.predictions)
        lines.append(f"  预测回合数: {total_preds}")
        lines.append(f"  贝叶斯已初始化: {initialized_count}/{total_preds} ({initialized_count/max(total_preds,1):.0%})")
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

        # ── 全局追踪数据统计 ──
        avg_known = sum(p.opp_known_cards_count for p in report.predictions) / max(total_preds, 1)
        avg_secrets = sum(len(p.opp_secrets) for p in report.predictions) / max(total_preds, 1)
        avg_deck_remaining = sum(p.opp_deck_remaining for p in report.predictions) / max(total_preds, 1)
        lines.append(f"  平均已知卡牌数: {avg_known:.1f}")
        lines.append(f"  平均奥秘数: {avg_secrets:.1f}")
        lines.append(f"  平均牌库剩余: {avg_deck_remaining:.1f}")
        lines.append(f"")

        # ── 逐回合推断 vs 实际 ──
        lines.append(f"── 逐回合推断 vs 实际 ──")
        for pred in report.predictions:
            lines.append(f"  Turn {pred.turn}:")
            lines.append(f"    对手手牌: {pred.opp_hand_count}  牌库: {pred.opp_deck_remaining}")
            lines.append(f"    贝叶斯推断: {pred.bayesian_top_deck} ({pred.bayesian_top_prob:.0%})"
                         f"{' [LOCKED]' if pred.bayesian_locked else ''}"
                         f"{' [已初始化]' if pred.bayesian_initialized else ' [未初始化]'}")
            if pred.opp_secrets:
                lines.append(f"    奥秘: {', '.join(pred.opp_secrets)}")
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

def setup_logging(verbose: bool = False):
    """Configure logging for MCTS engine (more verbose than default)."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(name)s: %(levelname)s %(message)s"
    logging.basicConfig(level=level, format=fmt, force=True)
    # Quiet down noisy libraries
    logging.getLogger("hearthstone").setLevel(logging.WARNING)
    logging.getLogger("hslog").setLevel(logging.WARNING)
    # Enable sim_logger output at INFO level
    logging.getLogger("analysis.search.sim_logger").setLevel(logging.DEBUG)
    logging.getLogger("analysis.card.engine.simulation").setLevel(logging.DEBUG)
    logging.getLogger("analysis.search.mcts.engine").setLevel(logging.DEBUG if verbose else logging.INFO)
    logging.getLogger("analysis.search.mcts.simulation").setLevel(logging.DEBUG)


def print_mcts_search_detail(result, state):
    """Print detailed MCTS search debug info including root children and rollout traces."""
    from analysis.search.sim_logger import get_sim_logger, set_sim_logger

    sim_log = get_sim_logger()
    sim_log.enabled = True

    s = result.mcts_stats
    print(f"│ ├─ MCTS 搜索统计:")
    print(f"│ │   Iterations: {s.iterations}")
    print(f"│ │   Nodes:      {s.nodes_created}")
    print(f"│ │   Evals:      {s.evaluations_done}")
    print(f"│ │   Worlds:     {s.world_count}")
    print(f"│ │   Time:       {s.time_used_ms:.0f}ms")
    print(f"│ │   Iters/sec:  {s.iterations / max(s.time_used_ms, 1) * 1000:.0f}")
    if s.world_count > 0:
        avg_eval_per_world = s.evaluations_done / s.world_count
        print(f"│ │   Avg evals/world: {avg_eval_per_world:.0f}")

    # Action stats from root
    if hasattr(result, 'action_stats') and result.action_stats:
        print(f"│ ├─ 根节点动作统计(Top 8):")
        for ast in sorted(result.action_stats, key=lambda x: x.visit_count, reverse=True)[:8]:
            desc = ast.action.describe(state) if hasattr(ast.action, 'describe') else str(ast.action)
            print(f"│ │   visits={ast.visit_count:3d}  "
                  f"q={ast.q_value:+.4f}  wr={ast.win_rate:.0%}  "
                  f"{desc[:60]}")

    # Detailed log entries
    detailed = getattr(result, 'detailed_log', None)
    if detailed and detailed.entries:
        print(f"│ ├─ MCTS 迭代进度日志:")
        for e in detailed.entries[::max(1, len(detailed.entries) // 5)]:
            print(f"│ │   iter={e['iter']:5d}  "
                  f"nodes={e['nodes']:5d}  "
                  f"evals={e['evals']:5d}  "
                  f"best_q={e['best_q']:+.4f}  "
                  f"depth={e['depth']}")

    # Simulation log
    sim_export = sim_log.to_dict()
    if sim_export.get("phases"):
        print(f"│ ├─ 模拟效果链路(Top phases):")
        for phase in sim_export["phases"][:3]:
            s = phase.get("summary", {})
            print(f"│ │   Phase: {phase['phase_name']} turn={phase['turn']} "
                  f"actions={s.get('action_count',0)} "
                  f"effects={s.get('effect_count',0)} "
                  f"deaths={s.get('death_count',0)} "
                  f"dur={phase.get('duration_ms',0):.0f}ms")
            # Show first few steps
            for step in phase.get("steps", [])[:5]:
                print(f"│ │     [{step['type']}] {step['detail'][:80]}")
            if len(phase.get("steps", [])) > 5:
                print(f"│ │     ... ({len(phase['steps']) - 5} more steps)")
            print(f"│ │")
    sim_log.reset()


def main():
    parser = argparse.ArgumentParser(description="全流程模拟验证 — CoreLogMonitor + Power.log 逐行解析 + MCTS 单例引擎")
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
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="打印详细 MCTS 调试日志")

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

    setup_logging(verbose=args.verbose)

    print(f"{'='*60}")
    print(f"全流程模拟验证")
    print(f"文件: {log_path}")
    print(f"预算: {args.budget}ms")
    print(f"CoreLogMonitor 集成: 是")
    print(f"贝叶斯延迟初始化: 是")
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
                "bayesian_initialized": p.bayesian_initialized,
                "known_hand_cards": p.known_hand_cards,
                "opp_secrets": p.opp_secrets,
                "opp_known_cards_count": p.opp_known_cards_count,
                "opp_deck_remaining": p.opp_deck_remaining,
                "actual_opp_plays": [
                    {"card_id": play.card_id, "name": play.card_name, "source": play.source}
                    for play in p.actual_opp_plays
                ],
            })
        f.write(json.dumps(pred_data, ensure_ascii=False, indent=2))

    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()

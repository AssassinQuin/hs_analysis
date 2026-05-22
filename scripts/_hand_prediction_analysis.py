#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_hand_prediction_analysis.py — 逐回合手牌预测差距分析

用法:
  python scripts/_hand_prediction_analysis.py Power.log --ground-truth gt.json
  python scripts/_hand_prediction_analysis.py Power.log --ground-truth gt.json --turn 5
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.CRITICAL)


# ── 卡牌名称工具 ──────────────────────────────────────────────

def card_id_to_name(card_id: str) -> str:
    try:
        from analysis.card.constants.i18n import card_name_lookup
        return card_name_lookup(card_id, "zh_CN")
    except Exception:
        return card_id


def name_to_card_id(name: str) -> str:
    try:
        from analysis.card.data.card_data import get_db
        db = get_db()
        card = db.get_card_by_name(name, lang="zh_CN")
        return card.get("id", "") if card else ""
    except Exception:
        return ""


# ── Ground Truth ──────────────────────────────────────────────

class GroundTruth:
    def __init__(self, data: dict):
        self.turn_hand: Dict[int, List[str]] = {}
        self.total_turns = data.get("meta", {}).get("total_turns", 30)
        self.opp_class = data.get("meta", {}).get("opp_class", "?")
        self._parse(data)

    def _parse(self, data: dict):
        if "turns" in data:
            for t_str, cards in data["turns"].items():
                self.turn_hand[int(t_str)] = cards
            return
        if "cards" in data:
            hand_state: Dict[int, List[str]] = {}
            for c in data["cards"]:
                name = c["name"]
                dt = c.get("drawn_turn")
                pt = c.get("played_turn")
                if dt is not None:
                    end = pt if pt is not None else self.total_turns + 1
                    for t in range(dt, end):
                        hand_state.setdefault(t, []).append(name)
            self.turn_hand = dict(sorted(hand_state.items()))

    def get_hand(self, turn: int) -> List[str]:
        return self.turn_hand.get(turn, [])


# ── 分析引擎 ──────────────────────────────────────────────────

class AnalysisEngine:
    def __init__(self, gt: GroundTruth):
        self.gt = gt
        self.turn_data: List[dict] = []
        self.archetype_log: List[dict] = []

    def replay(self, log_path: Path):
        from tracker.log_monitor import CoreLogMonitor
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        monitor = CoreLogMonitor()
        seen_turns: set = set()

        def _on_turn(turn):
            if turn in seen_turns or turn <= 0:
                return
            seen_turns.add(turn)
            try:
                state = monitor.build_state_dict()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    result = predictor.predict(state)

                preds = sorted(
                    [p for p in result.hand_predictions if p.probability > 0.005],
                    key=lambda p: (-p.probability, p.cost),
                )

                gt_hand = set(self.gt.get_hand(turn))
                pred_names = set(p.name for p in preds)

                hits = gt_hand & pred_names
                misses = pred_names - gt_hand  # 误报
                missed = gt_hand - pred_names   # 漏报

                # 按 source 分类
                by_source = defaultdict(list)
                for p in preds:
                    by_source[p.source].append(p)

                # Top-5 / Top-10
                top5 = set(p.name for p in preds[:5])
                top10 = set(p.name for p in preds[:10])
                gt_in_top5 = len(gt_hand & top5)
                gt_in_top10 = len(gt_hand & top10)

                entry = {
                    "turn": turn,
                    "opp_hand_count": state.get("opp_hand_count", 0),
                    "opp_deck_count": state.get("opp_deck_count", 0),
                    "gt_cards": sorted(gt_hand),
                    "gt_count": len(gt_hand),
                    "pred_count": len(preds),
                    "hits": sorted(hits),
                    "misses_top10": sorted(misses & top10),
                    "missed": sorted(missed),
                    "gt_in_top5": gt_in_top5,
                    "gt_in_top10": gt_in_top10,
                    "by_source": {
                        src: [(p.name, f"{p.probability:.1%}") for p in ps[:10]]
                        for src, ps in by_source.items()
                    },
                    "archetype": result.archetype_name,
                    "archetype_conf": f"{result.archetype_confidence:.0%}",
                    "top_archetypes": result.top_archetypes[:3],
                    "top5_preds": [(p.name, f"{p.probability:.1%}", p.source) for p in preds[:5]],
                    "top10_preds": [(p.name, f"{p.probability:.1%}", p.source) for p in preds[:10]],
                    "generated_count": len(state.get("generated_cards", set())),
                    "known_cards_count": len(state.get("known_cards", [])),
                    "revealed_hand": list(state.get("known_hand", [])),
                    "available_mana": state.get("available_mana", 0),
                }
                self.turn_data.append(entry)

                # Archetype log
                if result.top_archetypes:
                    self.archetype_log.append({
                        "turn": turn,
                        "archetypes": result.top_archetypes[:5],
                    })

            except Exception as e:
                self.turn_data.append({
                    "turn": turn,
                    "error": str(e),
                })

        monitor.on_turn_changed = _on_turn
        monitor.load_existing_log(str(log_path))

    def print_analysis(self, focus_turn: int = 0):
        """Print detailed analysis report."""
        print("=" * 72)
        print("对手手牌预测差距分析报告")
        print("=" * 72)
        print(f"对手职业: {self.gt.opp_class}")
        print(f"游戏总回合: {self.gt.total_turns}")
        print()

        # ── 1. 卡组推断分析 ──
        self._print_archetype_analysis()

        # ── 2. 逐回合分析 ──
        for entry in self.turn_data:
            if "error" in entry:
                print(f"  回合 {entry['turn']}: ERROR - {entry['error']}")
                continue
            if not entry["gt_cards"]:
                continue
            if focus_turn > 0 and entry["turn"] != focus_turn:
                continue
            self._print_turn_detail(entry)

        # ── 3. 汇总统计 ──
        self._print_summary()

        # ── 4. 问题诊断与优化建议 ──
        self._print_diagnosis()

    def _print_archetype_analysis(self):
        print("── 1. 卡组推断追踪 ──")
        if not self.archetype_log:
            print("  (无卡组推断数据)")
        for alog in self.archetype_log[:5]:
            arch_strs = [f"{name}({prob:.0%})" for name, prob in alog["archetypes"]]
            print(f"  回合 {alog['turn']:>2}: {', '.join(arch_strs)}")
        if len(self.archetype_log) > 5:
            print(f"  ... (共 {len(self.archetype_log)} 回合)")
        print()

    def _print_turn_detail(self, entry: dict):
        turn = entry["turn"]
        print(f"── 回合 {turn} ──")
        print(f"  对手手牌: {entry['opp_hand_count']}张  牌库: {entry['opp_deck_count']}张  法力: {entry['available_mana']}")
        print(f"  Ground Truth ({entry['gt_count']}张): {', '.join(entry['gt_cards'])}")

        if entry["top5_preds"]:
            strs = []
            for name, prob, src in entry["top5_preds"]:
                marker = "✓" if name in set(entry["gt_cards"]) else "✗"
                strs.append(f"{name}({prob}){marker}")
            print(f"  Top-5 预测:   {' | '.join(strs)}")

        if entry["missed"]:
            print(f"  漏报 (真相中但未预测): {', '.join(entry['missed'])}")

        if entry["misses_top10"]:
            print(f"  误报 (预测中但不在真相 Top-10): {', '.join(entry['misses_top10'])}")

        print(f"  Top-5 命中: {entry['gt_in_top5']}/{entry['gt_count']}  "
              f"Top-10 命中: {entry['gt_in_top10']}/{entry['gt_count']}")
        print(f"  预测总数: {entry['pred_count']}  "
              f"Source分布: {', '.join(f'{src}={len(ps)}' for src, ps in entry['by_source'].items())}")
        print(f"  卡组: {entry['archetype']} ({entry['archetype_conf']})")
        print()

    def _print_summary(self):
        valid = [e for e in self.turn_data if "error" not in e and e.get("gt_cards")]
        if not valid:
            return

        total_gt = sum(e["gt_count"] for e in valid)
        total_top5 = sum(e["gt_in_top5"] for e in valid)
        total_top10 = sum(e["gt_in_top10"] for e in valid)
        total_preds = sum(e["pred_count"] for e in valid)

        # 统计漏报
        missed_counter = Counter()
        miss_turns = defaultdict(list)
        for e in valid:
            for m in e.get("missed", []):
                missed_counter[m] += 1
                miss_turns[m].append(e["turn"])

        # 统计高频误报
        false_positive_counter = Counter()
        for e in valid:
            gt_set = set(e["gt_cards"])
            for name, prob, src in e.get("top5_preds", []):
                if name not in gt_set:
                    false_positive_counter[name] += 1

        print("── 3. 汇总统计 ──")
        print(f"  有效回合: {len(valid)}")
        print(f"  总预测条目: {total_preds}  平均每回合: {total_preds / len(valid):.0f}")
        print(f"  Top-5 命中率: {total_top5}/{total_gt} = {total_top5 / total_gt:.1%}")
        print(f"  Top-10 命中率: {total_top10}/{total_gt} = {total_top10 / total_gt:.1%}")
        print()

        if missed_counter:
            print("  高频漏报卡牌 (真相中但未预测):")
            for name, count in missed_counter.most_common(10):
                print(f"    {name}: {count} 次 (回合 {', '.join(map(str, miss_turns[name]))})")
            print()

        if false_positive_counter:
            print("  高频误报卡牌 (Top-5 预测但不在真相中):")
            for name, count in false_positive_counter.most_common(10):
                print(f"    {name}: {count} 次")
            print()

    def _print_diagnosis(self):
        """Diagnose root causes and propose optimizations."""
        print("── 4. 问题诊断与优化建议 ──")
        print()

        valid = [e for e in self.turn_data if "error" not in e and e.get("gt_cards")]

        # Issue 1: High prediction count (low precision)
        avg_preds = sum(e["pred_count"] for e in valid) / len(valid) if valid else 0
        if avg_preds > 15:
            print(f"  问题 1: 预测条目过多 (平均 {avg_preds:.0f}/回合)")
            print(f"    原因: revealed/inferred source 的卡牌即使已打出仍被标记为 100%")
            print(f"    建议: 已打出的卡牌应从 revealed 集合中移除。检查 _seen_cards")
            print(f"          是否正确地从 _revealed_hand 中排除已打出卡牌。")
            print()

        # Issue 2: Check if archetype is locked
        archetypes = [e.get("archetype", "") for e in valid]
        locked_count = sum(1 for a in archetypes if a)
        if locked_count < len(valid) * 0.5:
            print(f"  问题 2: 卡组未锁定 (仅 {locked_count}/{len(valid)} 回合有卡组名)")
            print(f"    原因: 贝叶斯推断可能未获得足够的卡组签名数据")
            print(f"    建议: 检查 BayesianOpponent 的初始化和 HSReplay 数据加载")
            print()

        # Issue 3: Specific card analysis — 焚火林地
        fenhuo_missed = 0
        fenhuo_total = 0
        for e in valid:
            gt = set(e.get("gt_cards", []))
            if "焚火林地" in gt:
                fenhuo_total += 1
                top10_names = set(n for n, _, _ in e.get("top10_preds", []))
                if "焚火林地" not in top10_names:
                    fenhuo_missed += 1
        if fenhuo_total > 3:
            print(f"  问题 3: 焚火林地漏报 {fenhuo_missed}/{fenhuo_total} 回合")
            print(f"    原因: 此卡在对手手牌中持续多回合未被打出。")
            print(f"          当对手持续不打出某张低费卡时，应降低其概率。")
            print(f"    建议: WorldModelEvidence.analyze_unplayed_cards() 应对")
            print(f"          对手有法力但持续不出的卡施加更强的负似然比。")
            print()

        # Issue 4: Revealed cards staying too long
        revealed_counts = Counter()
        for e in valid:
            for name, prob, src in e.get("top5_preds", []):
                if src == "revealed" and prob == "100%":
                    revealed_counts[name] += 1
        always_revealed = {n for n, c in revealed_counts.items() if c > 5}
        if always_revealed:
            print(f"  问题 4: 部分卡牌持续被标记为 revealed (100%)")
            print(f"    持续高置信度卡牌: {', '.join(sorted(always_revealed))}")
            print(f"    原因: 这些卡可能通过 SHOW_ENTITY 揭示后又被打出，")
            print(f"          但 revealed_hand 未更新。")
            print(f"    建议: 当卡牌离开 HAND 区域时，应从 revealed_hand 移除。")
            print()

        print("── 5. 优化方案优先级 ──")
        print()
        print("  P0 (Critical) — 修复 revealed 手牌生命周期")
        print("    当对手打出卡牌时 (HAND→PLAY)，需从 known_hand 集合中移除。")
        print("    当前 known_hand 包含已打出的卡牌，导致 100% 误报。")
        print("    文件: tracker/log_monitor.py build_state_dict() 或 GlobalTracker")
        print()
        print("  P1 (High) — 改进打出时机推断 (Unplayed Card Bias)")
        print("    对手有足够法力但多回合不打出的卡，应显著降低其概率。")
        print("    已移除: 启发式证据回退 (world_model.py) 已删除，使用 MCTS/UCT 模拟替代。")
        print()
        print("  P2 (Medium) — 衍生牌过滤改进")
        print("    检查 opp_generated_seen 的覆盖率。漏掉的衍生牌会污染概率池。")
        print("    文件: analysis/watcher/global_tracker.py")
        print()
        print("  P3 (Medium) — 卡组推断置信度利用")
        print("    当贝叶斯卡组置信度 >80% 时，应严格使用卡组卡牌池，")
        print("    排除不在卡组中的卡牌。当前似乎对所有卡牌等概率计算。")
        print("    文件: analysis/engine/dynamic_probability.py")
        print()


# ── 主入口 ──────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="对手手牌预测差距分析")
    ap.add_argument("path", help="Power.log 文件路径")
    ap.add_argument("--ground-truth", "-g", required=True, help="地面真相 JSON")
    ap.add_argument("--turn", "-t", type=int, default=0, help="只分析指定回合")
    args = ap.parse_args()

    log_path = Path(args.path).resolve()
    gt_path = Path(args.ground_truth).resolve()

    with gt_path.open("r", encoding="utf-8") as f:
        gt = GroundTruth(json.load(f))

    engine = AnalysisEngine(gt)
    engine.replay(log_path)
    engine.print_analysis(focus_turn=args.turn)
    return 0


if __name__ == "__main__":
    sys.exit(main())

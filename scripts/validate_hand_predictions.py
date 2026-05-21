#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_hand_predictions.py — 验证手牌预测准确率

工作流程:
  1. 用户观看回放，记录对手每回合的已知手牌（抽到但未打出的牌）
  2. 将记录写入 ground_truth JSON 文件
  3. 运行此脚本对比预测结果 vs 地面真相
  4. 输出准确率指标

地面真相 JSON 格式 (turn_hand 方式, 推荐):
  每回合对手手牌中已知内容（已抽到且未打出的牌）。

  {
    "turns": {
      "2": ["凶恶的滑矛纳迦", "深海融合怪"],
      "3": ["深海融合怪", "学校教师"],
      "4": ["学校教师"]
    }
  }

地面真相 JSON 格式 (cards 方式):
  记录对手每张牌的信息，脚本自动推导每回合手牌。

  {
    "cards": [
      {"name": "凶恶的滑矛纳迦", "drawn_turn": 1, "played_turn": 3},
      {"name": "深海融合怪", "drawn_turn": 2, "played_turn": 5},
      {"name": "学校教师", "drawn_turn": 3, "played_turn": null},
      {"name": "艾萨拉的沉没者", "drawn_turn": 1, "played_turn": 4}
    ]
  }

  其中:
    drawn_turn:  抽到该牌的回合
    played_turn: 打出该牌的回合 (null 表示未打出/游戏结束时还在手牌)

用法:
  # 使用 turn_hand 方式验证
  python scripts/validate_hand_predictions.py Power.log --ground-truth gt.json

  # 使用 cards 方式验证
  python scripts/validate_hand_predictions.py Power.log --ground-truth gt.json

  # 创建地面真相模板 (从日志自动提取空壳)
  python scripts/validate_hand_predictions.py Power.log --create-template template.json

  # 只看预测输出 (不验证)
  python scripts/validate_hand_predictions.py Power.log
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logger = logging.getLogger(__name__)


# ── 卡片名称工具 ──────────────────────────────────────────────


def card_id_to_name(card_id: str) -> str:
    """将 card_id 转为中文名称。"""
    try:
        from analysis.card.constants.i18n import card_name_lookup
        return card_name_lookup(card_id, "zh_CN")
    except Exception:
        return card_id


# ── 地面真相处理 ──────────────────────────────────────────────


class GroundTruth:
    """地面真相：记录对手每回合的手牌已知内容。"""

    def __init__(self, data: dict):
        self._raw = data
        self.turn_hand: Dict[int, List[str]] = {}
        self._parse(data)

    def _parse(self, data: dict):
        """解析地面真相，支持两种格式（turn_hand / cards）。"""
        if "turns" in data:
            # turn_hand 格式: { "2": ["卡名1", "卡名2"], ... }
            for t_str, cards in data["turns"].items():
                turn = int(t_str)
                self.turn_hand[turn] = cards
            return

        if "cards" in data:
            # cards 格式: 逐张记录 drawn_turn / played_turn
            # 自动推导每回合手牌
            hand_state: Dict[int, List[str]] = {}
            cards_list = data["cards"]

            for c in cards_list:
                name = c["name"]
                dt = c.get("drawn_turn")
                pt = c.get("played_turn")

                # 抽到那张牌时加入手牌
                if dt is not None:
                    # 这张牌从 drawn_turn 开始在手牌
                    for t in range(dt, pt if pt is not None else 999):
                        hand_state.setdefault(t, []).append(name)

            self.turn_hand = dict(sorted(hand_state.items()))
            return

        logger.warning("地面真相格式无法识别: 需要 'turns' 或 'cards' 键")

    def get_hand(self, turn: int) -> List[str]:
        """获取指定回合的已知手牌（空列表表示无数据）。"""
        return self.turn_hand.get(turn, [])

    def has_turn(self, turn: int) -> bool:
        return turn in self.turn_hand

    @property
    def turns_available(self) -> List[int]:
        return sorted(self.turn_hand.keys())


# ── 预测匹配分析 ──────────────────────────────────────────────


class PredictionMatchAnalysis:
    """单回合预测 vs 真相的对比结果。"""

    def __init__(self, turn: int, ground_truth: List[str]):
        self.turn = turn
        self.ground_truth = sorted(set(ground_truth))  # 去重
        self.top_predictions: List[Tuple[str, float]] = []  # [(name, prob)]
        self.hits: List[Tuple[str, float]] = []  # 命中: (name, prob)
        self.misses: List[Tuple[str, float]] = []  # 误报: (name, prob)
        self.missed_gt: List[str] = []  # 漏报: 真实在手但未在预测列表中
        self.gt_in_top5 = 0  # 真相牌出现在 top-5 预测中的数量
        self.gt_in_top10 = 0  # 真相牌出现在 top-10 预测中的数量

    def set_predictions(self, predictions: List[Tuple[str, float]]):
        """设置预测结果（按概率降序排列）。"""
        self.top_predictions = predictions
        pred_names = set(p[0] for p in predictions)
        gt_set = set(self.ground_truth)

        # 逐级计算命中
        for name, prob in predictions:
            if name in gt_set:
                self.hits.append((name, prob))
            else:
                self.misses.append((name, prob))

        # 漏报
        predicted_names = set(p[0] for p in predictions)
        self.missed_gt = [c for c in self.ground_truth if c not in predicted_names]

        # top-k 指标
        top5_names = set(p[0] for p in predictions[:5])
        top10_names = set(p[0] for p in predictions[:10])
        self.gt_in_top5 = sum(1 for c in self.ground_truth if c in top5_names)
        self.gt_in_top10 = sum(1 for c in self.ground_truth if c in top10_names)

    @property
    def precision(self) -> float:
        """精确率: 预测命中数 / 预测总数。"""
        total = len(self.hits) + len(self.misses)
        return len(self.hits) / total if total > 0 else 0.0

    @property
    def recall(self) -> float:
        """召回率: 预测命中数 / 真相牌总数。"""
        return len(self.hits) / len(self.ground_truth) if self.ground_truth else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def has_data(self) -> bool:
        return len(self.ground_truth) > 0


class ValidationReport:
    """全对局验证报告。"""

    def __init__(self):
        self.turns: List[PredictionMatchAnalysis] = []
        self.total_turns = 0
        self.validated_turns = 0

    def add_turn(self, analysis: PredictionMatchAnalysis):
        self.turns.append(analysis)
        self.total_turns += 1
        if analysis.has_data:
            self.validated_turns += 1

    @property
    def overall_precision(self) -> float:
        vals = [a.precision for a in self.turns if a.has_data]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def overall_recall(self) -> float:
        vals = [a.recall for a in self.turns if a.has_data]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def overall_f1(self) -> float:
        vals = [a.f1 for a in self.turns if a.has_data]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def top5_accuracy(self) -> float:
        """Top-5 准确率: 真相牌出现在 top-5 预测的比例。"""
        total_gt = 0
        total_in_top5 = 0
        for a in self.turns:
            if a.has_data:
                total_gt += len(a.ground_truth)
                total_in_top5 += a.gt_in_top5
        return total_in_top5 / total_gt if total_gt > 0 else 0.0

    @property
    def top10_accuracy(self) -> float:
        total_gt = 0
        total_in_top10 = 0
        for a in self.turns:
            if a.has_data:
                total_gt += len(a.ground_truth)
                total_in_top10 += a.gt_in_top10
        return total_in_top10 / total_gt if total_gt > 0 else 0.0

    def summary_text(self) -> str:
        lines = [
            "=" * 60,
            "预测准确性验证报告",
            "=" * 60,
            f"  验证回合: {self.validated_turns} / {self.total_turns}",
            f"  整体精确率 (Precision):  {self.overall_precision:.1%}",
            f"  整体召回率 (Recall):     {self.overall_recall:.1%}",
            f"  整体 F1 值:              {self.overall_f1:.1%}",
            f"  Top-5 包含率:            {self.top5_accuracy:.1%}",
            f"  Top-10 包含率:           {self.top10_accuracy:.1%}",
            "=" * 60,
        ]
        return "\n".join(lines)

    def per_turn_text(self, max_turns: int = 20) -> str:
        """输出每回合的详细对比。"""
        lines = []
        for a in self.turns:
            if not a.has_data:
                continue
            if len([x for x in self.turns[:self.turns.index(a)+1] if x.has_data]) > max_turns:
                lines.append("  ... (后续回合已截断)")
                break

            lines.append(f"  回合 {a.turn}:")
            lines.append(f"    真相 ({len(a.ground_truth)}张): {', '.join(a.ground_truth)}")

            # Top-5 预测
            top5_strs = []
            for name, prob in a.top_predictions[:5]:
                marker = "✓" if name in a.ground_truth else "✗"
                top5_strs.append(f"{name}({prob:.0%}){marker}")
            lines.append(f"    Top-5 预测:   {' | '.join(top5_strs)}")

            if a.missed_gt:
                lines.append(f"    漏报: {', '.join(a.missed_gt)}")

            # 回合指标
            lines.append(f"    P={a.precision:.0%} R={a.recall:.0%} F1={a.f1:.0%} "
                         f"Top5命中={a.gt_in_top5}/{len(a.ground_truth)}")
            lines.append("")

        return "\n".join(lines)


# ── 验证引擎 ──────────────────────────────────────────────────


class ValidationEngine:
    """验证引擎：回放日志 + 对比预测 vs 地面真相。"""

    def __init__(self, ground_truth: Optional[GroundTruth] = None):
        self.gt = ground_truth
        self.snapshots: List[dict] = []  # [(turn, pred_names_with_probs)]

    def replay_and_predict(self, log_path: Path):
        """回放日志并运行手牌预测，记录每回合结果。"""
        from tracker.log_monitor import CoreLogMonitor
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        monitor = CoreLogMonitor()
        snapshots = []

        def _on_turn(mon, turn: int, predictor_obj):
            try:
                state = mon.build_state_dict()
                _buf = io.StringIO()
                with redirect_stdout(_buf):
                    result = predictor_obj.predict(state)

                # 提取按概率排序的手牌预测
                preds = sorted(
                    [p for p in result.hand_predictions if p.probability > 0.01],
                    key=lambda p: (-p.probability, p.cost),
                )
                pred_list = [(p.name, p.probability) for p in preds]
                snapshots.append({"turn": turn, "predictions": pred_list})
            except Exception as e:
                logger.debug("回合 %d 预测失败: %s", turn, e)
                snapshots.append({"turn": turn, "predictions": []})

        # 挂载回调
        monitor.on_game_started = lambda info: print(f"\n游戏开始: {info.get('player_class','?')} vs {info.get('opp_class','?')}")
        monitor.on_turn_changed = lambda turn: _on_turn(monitor, turn, predictor)
        monitor.on_game_ended = lambda: None

        print(f"回放文件: {log_path}")
        monitor.load_existing_log(str(log_path))
        self.snapshots = snapshots
        return snapshots

    def validate(self) -> ValidationReport:
        """与地面真相对比，生成验证报告。"""
        report = ValidationReport()
        if self.gt is None:
            logger.warning("无地面真相数据，无法验证")
            return report

        for snap in self.snapshots:
            turn = snap["turn"]
            gt_hand = self.gt.get_hand(turn)
            analysis = PredictionMatchAnalysis(turn, gt_hand)
            analysis.set_predictions(snap.get("predictions", []))
            report.add_turn(analysis)

        return report


# ── 模板生成 ──────────────────────────────────────────────────


def create_template(log_path: Path) -> dict:
    """从日志生成地面真相模板（空壳，供用户填写）。"""
    # 先回放获取回合信息
    from tracker.log_monitor import CoreLogMonitor
    from tracker.hand_predictor import HandPredictor

    predictor = HandPredictor()
    monitor = CoreLogMonitor()
    turn_predictions = []
    player_class = "?"
    opp_class = "?"

    def _on_game_start(info):
        nonlocal player_class, opp_class
        player_class = info.get("player_class", "?")
        opp_class = info.get("opp_class", "?")

    def _on_turn(turn):
        try:
            state = monitor.build_state_dict()
            _buf = io.StringIO()
            with redirect_stdout(_buf):
                result = predictor.predict(state)
            preds = sorted(
                [p for p in result.hand_predictions if p.probability > 0.01],
                key=lambda p: (-p.probability, p.cost),
            )
            pred_names = [p.name for p in preds[:8]]
            turn_predictions.append({
                "turn": turn,
                "hand_count": state.get("opp_hand_count", 0),
                "top_predictions": pred_names,
            })
        except Exception:
            turn_predictions.append({
                "turn": turn,
                "hand_count": 0,
                "top_predictions": [],
            })

    monitor.on_game_started = _on_game_start
    monitor.on_turn_changed = _on_turn
    monitor.load_existing_log(str(log_path))

    template = {
        "meta": {
            "log_file": str(log_path),
            "player_class": player_class,
            "opp_class": opp_class,
        },
        "turns": {},
        "_说明": "在 turns 中按回合填入对手手牌的已知卡牌名称。"
                 "例如: {\"2\": [\"凶恶的滑矛纳迦\", \"深海融合怪\"]}",
    }

    for tp in turn_predictions:
        if tp["turn"] > 0:  # 跳过 turn 0
            template["turns"][str(tp["turn"])] = []  # 用户填写

    return template


# ── 主入口 ────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(
        description="炉石手牌预测准确性验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s Power.log --ground-truth gt.json
  %(prog)s Power.log --create-template template.json
  %(prog)s Power.log --verbose
        """,
    )
    ap.add_argument("path", help="Power.log 文件路径")
    ap.add_argument("--ground-truth", "-g", metavar="FILE", help="地面真相 JSON 文件")
    ap.add_argument("--create-template", "-t", metavar="FILE", help="创建地面真相模板文件")
    ap.add_argument("--verbose", "-v", action="store_true", help="详细输出每回合对比")
    ap.add_argument("--top-k", type=int, default=5, help="Top-K 评估 (默认: 5)")

    args = ap.parse_args()
    log_path = Path(args.path).expanduser().resolve()

    if not log_path.is_file():
        ap.error(f"文件不存在: {log_path}")

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # ── 创建模板模式 ──
    if args.create_template:
        template_path = Path(args.create_template)
        template = create_template(log_path)
        with template_path.open("w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"地面真相模板已创建: {template_path}")
        print("请填入对手每回合的已知手牌后重新运行验证。")
        return 0

    # ── 加载地面真相 ──
    gt = None
    if args.ground_truth:
        gt_path = Path(args.ground_truth)
        if not gt_path.is_file():
            ap.error(f"地面真相文件不存在: {gt_path}")
        with gt_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        gt = GroundTruth(data)
        print(f"已加载地面真相: {args.ground_truth}")
        print(f"  包含回合: {gt.turns_available}")
        print()

    # ── 回放 + 验证 ──
    engine = ValidationEngine(ground_truth=gt)
    engine.replay_and_predict(log_path)

    if gt:
        report = engine.validate()
        print()
        print(report.summary_text())
        print()
        if args.verbose:
            print(report.per_turn_text())
    else:
        print("\n提示: 使用 --ground-truth 指定地面真相文件来验证准确性。")
        print("      使用 --create-template 先生成模板。")

    return 0


if __name__ == "__main__":
    sys.exit(main())

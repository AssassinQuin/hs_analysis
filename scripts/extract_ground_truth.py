#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_ground_truth.py — 从 Power.log 自动提取对手手牌 ground truth

工作原理：
  1. 重放 Power.log，拦截对手卡牌的 zone 转换事件
  2. 记录每张对手卡牌的：card_id, drawn_turn（DECK→HAND）, played_turn（HAND→PLAY/GRAVEYARD）
  3. 过滤衍生牌，输出 ground truth JSON

用法：
  python scripts/extract_ground_truth.py Power.log -o gt.json
  python scripts/extract_ground_truth.py Power.log -o gt.json --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)


def card_id_to_name(card_id: str) -> str:
    """将 card_id 转为中文名称。"""
    try:
        from analysis.card.constants.i18n import card_name_lookup
        return card_name_lookup(card_id, "zh_CN")
    except Exception:
        return card_id


def extract_ground_truth(log_path: Path) -> dict:
    """从 Power.log 提取对手手牌 ground truth。

    Returns:
        {"cards": [{"name": ..., "drawn_turn": ..., "played_turn": ...}, ...]}
    """
    from tracker.log_monitor import CoreLogMonitor

    # ── 追踪容器 ──
    # entity_id -> {"card_id": str, "drawn_turn": int|None, "played_turn": int|None}
    opp_cards: Dict[int, dict] = {}
    # 记录 entity_id 曾经到过的 zone
    entity_in_opp_hand: Dict[int, bool] = {}

    last_turn = 0
    current_turn = 0

    monitor = CoreLogMonitor()

    # ── 独立追踪 zone 变化, 不受 GlobalTracker cleanup 影响 ──
    # 问题: opp_hand_hold_since 在 game end 后被清除
    # 解决: 在 on_zone_change 被调用时自己记录一份副本

    orig_zone_change = monitor.global_tracker.on_zone_change

    def on_zone_change(entity_id, controller, old_zone, new_zone,
                       card_id="", card_type=0):
        nonlocal current_turn
        is_opp = (controller == monitor.global_tracker.opp_controller)

        if is_opp:
            # 初始化实体记录
            if entity_id not in opp_cards:
                opp_cards[entity_id] = {
                    "card_id": card_id,
                    "drawn_turn": None,
                    "played_turn": None,
                }

            # 更新 card_id
            if card_id and opp_cards[entity_id]["card_id"] != card_id:
                opp_cards[entity_id]["card_id"] = card_id

            zh = monitor.global_tracker.ZONE_HAND
            zd = monitor.global_tracker.ZONE_DECK
            zp = monitor.global_tracker.ZONE_PLAY

            # DECK → HAND: 抽牌
            if old_zone == zd and new_zone == zh:
                if current_turn > 0 and opp_cards[entity_id]["drawn_turn"] is None:
                    opp_cards[entity_id]["drawn_turn"] = current_turn
                    logger.debug("  DECK→HAND e=%d card=%s turn=%d",
                                 entity_id, card_id or "?", current_turn)

            # HAND → PLAY/GRAVEYARD/SECRET: 打出
            elif old_zone == zh and new_zone in (
                zp,
                monitor.global_tracker.ZONE_GRAVEYARD,
                monitor.global_tracker.ZONE_SECRET,
            ):
                if current_turn > 0 and opp_cards[entity_id]["played_turn"] is None:
                    opp_cards[entity_id]["played_turn"] = current_turn
                    logger.debug("  HAND→PLAY e=%d card=%s turn=%d",
                                 entity_id, card_id or "?", current_turn)

        # 调用原始处理
        return orig_zone_change(entity_id, controller, old_zone, new_zone,
                                card_id, card_type)

    monitor.global_tracker.on_zone_change = on_zone_change

    # ── 钩子：追踪当前回合 ──
    orig_turn = monitor.on_turn_changed

    def on_turn_changed(turn):
        nonlocal current_turn, last_turn
        current_turn = turn
        if turn > last_turn:
            last_turn = turn
        if orig_turn:
            orig_turn(turn)

    monitor.on_turn_changed = on_turn_changed

    # ── 钩子：SHOW_ENTITY 补全 card_id ──
    orig_show = monitor.global_tracker.on_show_entity

    def on_show_entity(entity_id, card_id, controller, zone,
                       card_type=0, cost=0, is_coin_tag=False):
        if controller == monitor.global_tracker.opp_controller and card_id:
            if entity_id not in opp_cards:
                opp_cards[entity_id] = {
                    "card_id": card_id,
                    "drawn_turn": None,
                    "played_turn": None,
                }
            else:
                opp_cards[entity_id]["card_id"] = card_id
        return orig_show(entity_id, card_id, controller, zone,
                         card_type, cost, is_coin_tag)

    monitor.global_tracker.on_show_entity = on_show_entity

    # ── 重放日志 ──
    logger.info("重放 %s ...", log_path)
    monitor.load_existing_log(str(log_path))
    logger.info("共 %d 个对手实体, last_turn=%d", len(opp_cards), last_turn)

    gt_state = monitor.global_tracker.state
    generated = set(gt_state.opp_generated_seen)

    # ── 过滤 + 输出 ──
    # 策略:
    #   A) 有 drawn_turn (DECK→HAND) → 确定是牌库牌
    #   B) 在 opp_hand_card_ids 中(游戏结束时在手中) → 初始手牌或未检测到 DECK→HAND
    #   C) 有 played_turn 但无 drawn_turn (HAND→PLAY) → 仅当 card 属于当前职业才纳入
    #
    # 关键过滤:
    #   - 不使用 graveyard_seen: opp_generated_seen 不完整, 衍生牌检测有 gap
    #   - 允许每张卡最多 2 张 (标准构筑上限)
    #   - 对于无 drawn_turn 仅有 played_turn 的卡牌, 检查其职业归属
    #     (对手是 Mage, 所以 Druid/DK/Hunter 等职业的卡牌几乎确定是衍生)

    def _is_card_in_class(card_id: str, opp_class: str) -> bool:
        """检查卡牌是否属于对手职业或中立。"""
        try:
            from analysis.card.data.card_data import get_db
            db = get_db()
            card = db.get_card(card_id)
            if card is None:
                return True  # 未知卡牌, 保守保留
            card_class = card.get("cardClass", "")
            if not card_class:
                return True
            if card_class == "NEUTRAL":
                return True
            return card_class.upper() == opp_class.upper()
        except Exception:
            return True  # 保守: 出错时保留

    # 获取对手职业
    opp_hero_class = getattr(gt_state, 'opp_hero_class', None) or '?'

    # 统计每张卡在 ground truth 中的出现次数 (用于 2-of 限制)
    name_count: Dict[str, int] = {}

    real_cards = []

    # 1. 来源 A: 有 drawn_turn 的卡牌 (确定是牌库牌)
    for eid, info in sorted(opp_cards.items()):
        cid = info["card_id"]
        if not cid:
            continue
        if cid in generated:
            continue

        drawn_turn = info["drawn_turn"]
        if drawn_turn is None:
            continue

        name = card_id_to_name(cid)
        # 最多 2 张
        if name_count.get(name, 0) >= 2:
            continue

        name_count[name] = name_count.get(name, 0) + 1
        real_cards.append({
            "name": name,
            "drawn_turn": drawn_turn,
            "played_turn": info["played_turn"],
        })

    # 2. 来源 B + C: 有 played_turn 但无 drawn_turn (初始手牌/衍生入手的牌)
    # 只保留属于 Mage 或 中立的卡牌
    for eid, info in sorted(opp_cards.items()):
        cid = info["card_id"]
        if not cid:
            continue
        if cid in generated:
            continue

        drawn_turn = info["drawn_turn"]
        played_turn = info["played_turn"]
        if drawn_turn is not None:
            continue  # 已经在来源 A 中添加
        if played_turn is None:
            continue  # 无追踪数据

        # 检查职业归属
        if not _is_card_in_class(cid, opp_hero_class):
            logger.debug("  过滤掉其他职业卡牌: %s (%s)", card_id_to_name(cid), cid)
            continue

        name = card_id_to_name(cid)
        if name_count.get(name, 0) >= 2:
            continue

        name_count[name] = name_count.get(name, 0) + 1
        real_cards.append({
            "name": name,
            "drawn_turn": None,  # 由后续逻辑估算
            "played_turn": played_turn,
        })

    # 排序: drawn_turn 为主
    real_cards.sort(key=lambda c: (c["drawn_turn"] or 99, c["played_turn"] or 99))

    # ── 对 drawn_turn 为 None 但 played_turn 有值的卡牌设定合理 drawn_turn ──
    for c in real_cards:
        if c["drawn_turn"] is None and c["played_turn"] is not None:
            c["drawn_turn"] = max(1, c["played_turn"] - 1)

    return {
        "meta": {
            "log_file": str(log_path),
            "player_class": gt_state.player_hero_class or "?",
            "opp_class": gt_state.opp_hero_class or "?",
            "total_turns": last_turn,
            "cards_found": len(real_cards),
            "from_zone_tracking": len([c for c in real_cards if c["drawn_turn"] is not None or c["played_turn"] is not None]),
            "from_hand_cards": len([c for c in real_cards if c["drawn_turn"] == 1 and c["played_turn"] is None]),
        },
        "cards": real_cards,
    }


def main():
    ap = argparse.ArgumentParser(description="从 Power.log 自动提取对手手牌 ground truth")
    ap.add_argument("path", help="Power.log 文件路径")
    ap.add_argument("-o", "--output", default="gt.json", help="输出 JSON 路径")
    ap.add_argument("-v", "--verbose", action="store_true", help="详细输出")

    args = ap.parse_args()
    log_path = Path(args.path).expanduser().resolve()

    if not log_path.is_file():
        ap.error(f"文件不存在: {log_path}")

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(message)s")

    gt = extract_ground_truth(log_path)

    output_path = Path(args.output)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(gt, f, ensure_ascii=False, indent=2)

    cards_count = len(gt["cards"])
    print(f"\n提取完成: {output_path}")
    print(f"  对手卡牌: {cards_count} 张")
    print(f"  其中已打出: {sum(1 for c in gt['cards'] if c['played_turn'] is not None)} 张")
    print(f"  未打出: {sum(1 for c in gt['cards'] if c['played_turn'] is None)} 张")
    print(f"  有 drawn_turn: {sum(1 for c in gt['cards'] if c['drawn_turn'] is not None)} 张")

    if cards_count == 0:
        print("\n⚠️ 没有提取到对手卡牌。可能原因：")
        print("  - Power.log 不完整")
        print("  - 对手 controller ID 检测异常")
        print("  尝试用 --verbose 查看详细日志")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""deep_powerlog_analysis.py — 深度分析 Power.log 实际游戏对局

分析维度:
1. 卡牌效果推断 vs 实际游戏行为
2. 随机效果追踪
3. 对手手牌预测 (卡组 vs 随机)
4. 卡组牌 vs 衍生牌区分
5. MCTS 模拟 vs 实际行为匹配度
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

from tracker.log_monitor import CoreLogMonitor
from tracker.hand_predictor import HandPredictor
from analysis.watcher.tracker_types import CardSource
from analysis.card.data.card_data import get_db
from analysis.card.constants.hs_enums import (
    RACE_ZH_MAP, SCHOOL_ZH_MAP,
)


def analyze_game(log_path: Path):
    """Run the full pipeline and dump detailed analysis."""
    
    card_db = get_db()
    
    # ── 运行 Pipeline ──
    monitor = CoreLogMonitor(log_path=str(log_path))
    
    all_states: List[dict] = []
    all_predictions: list = []
    game_events: List[dict] = []
    
    def on_game_started(info):
        game_events.append({"type": "game_start", "info": info})
    
    def on_game_ended():
        game_events.append({"type": "game_end"})
    
    def on_turn_changed(turn):
        game_events.append({"type": "turn_change", "turn": turn})
    
    def on_state_updated(state_dict):
        all_states.append(dict(state_dict))
        try:
            hp = HandPredictor()
            pred = hp.predict(state_dict)
            all_predictions.append(pred)
        except Exception as e:
            pass
    
    def on_log_error(msg):
        pass
    
    monitor.on_game_started = on_game_started
    monitor.on_game_ended = on_game_ended
    monitor.on_turn_changed = on_turn_changed
    monitor.on_state_updated = on_state_updated
    monitor.on_log_error = on_log_error
    
    monitor.load_existing_log(str(log_path))
    
    final_state = monitor.build_state_dict()
    
    # ── 分析维度 1: 卡牌效果推断 (CardEffectInference) ──
    print("=" * 70)
    print("维度 1: 卡牌效果推断分析 (CardEffectInference)")
    print("=" * 70)
    
    all_known_cards = []
    for st in all_states:
        for kc in st.get("known_cards", []):
            all_known_cards.append(kc)
    
    # Deduplicate by card_id
    seen_card_ids = set()
    unique_cards = []
    for kc in all_known_cards:
        cid = kc.get("card_id", "")
        if cid and cid not in seen_card_ids:
            seen_card_ids.add(cid)
            unique_cards.append(kc)
    
    print(f"\n本局共打出的唯一卡牌数: {len(unique_cards)}")
    print(f"总 known_cards 记录数: {len(all_known_cards)}")
    
    # Classify cards by their effect patterns
    has_discover = []
    has_generate = []
    has_random = []
    has_conditional = []
    has_random_target = []
    has_random_summon = []
    
    for kc in unique_cards:
        cid = kc.get("card_id", "")
        card = card_db.get_card(cid) if card_db and cid else {}
        if not card:
            continue
        
        text = (card.get("text", "") or "") + (card.get("englishText", "") or "")
        text_lower = text.lower()
        mechanics = [m.upper() for m in (card.get("mechanics", []) or [])]
        
        if "DISCOVER" in mechanics:
            has_discover.append(cid)
        if any(kw in text_lower for kw in ["召唤", "summon", "生成", "create", "发现", "discover", "add to your hand"]):
            has_generate.append(cid)
        if "random" in text_lower:
            has_random.append(cid)
        if any(kw in text_lower for kw in ["if you", "如果你", "holding", "手持"]):
            has_conditional.append(cid)
        if "random enemy" in text_lower or "random minion" in text_lower or "random opponent" in text_lower:
            has_random_target.append(cid)
        if "summon a random" in text_lower or "随机召唤" in text_lower or "random minion" in text_lower:
            has_random_summon.append(cid)
    
    print(f"\n  【随机效果卡牌】({len(has_random)} 张):")
    for cid in has_random:
        card = card_db.get_card(cid)
        name = card.get("name", cid) if card else cid
        text = (card.get("text", "") or card.get("englishText", "") or "")[:80]
        print(f"    {name} ({cid}): {text}...")
    
    print(f"\n  【发现/生成类卡牌】- DISCOVER mechanics ({len(has_discover)} 张):")
    for cid in has_discover:
        card = card_db.get_card(cid)
        name = card.get("name", cid) if card else cid
        print(f"    {name} ({cid})")
    
    print(f"\n  【文本生成类卡牌】({len(has_generate)} 张):")
    for cid in has_generate[:10]:
        card = card_db.get_card(cid)
        name = card.get("name", cid) if card else cid
        print(f"    {name} ({cid})")
    if len(has_generate) > 10:
        print(f"    ... 还有 {len(has_generate) - 10} 张")
    
    print(f"\n  【条件持有类卡牌】({len(has_conditional)} 张):")
    for cid in has_conditional:
        card = card_db.get_card(cid)
        name = card.get("name", cid) if card else cid
        print(f"    {name} ({cid})")
    
    # ── 分析维度 2: 随机效果追踪 ──
    print("\n" + "=" * 70)
    print("维度 2: 随机效果追踪分析")
    print("=" * 70)
    
    print(f"\n  CardEffectInferenceEngine 当前仅追踪:")
    print(f"    ✅ DISCOVER (mechanics 检查)")
    print(f"    ✅ Summon/Create/Discover 文本关键词")
    print(f"    ❌ 随机伤害 (未检测)")
    print(f"    ❌ 随机目标 (未检测)")
    print(f"    ❌ 随机召唤 (未检测)")
    print(f"    ❌ 随机从牌库/手牌 (未检测)")
    print(f"    ❌ 随机给对手 (未检测)")
    print(f"\n  本局 {{random}} 卡牌计数: {len(has_random)} 张 — 均未被追踪！")
    
    # ── 分析维度 3: 对手手牌预测深度分析 ──
    print("\n" + "=" * 70)
    print("维度 3: 对手手牌预测分析")
    print("=" * 70)
    
    print(f"\n  最终贝叶斯状态:")
    bayesian = final_state.get("bayesian", {})
    print(f"    卡组名称: {bayesian.get('archetype_name', '无')}")
    print(f"    置信度: {bayesian.get('deck_confidence', 0.0):.1%}")
    
    top_decks = bayesian.get("top_decks", [])
    print(f"    Top 卡组 ({len(top_decks)} 个):")
    for deck_id, name, prob in top_decks[:5]:
        print(f"      #{name} (id={deck_id}): {prob:.1%}")
    
    print(f"\n  最终对手数据:")
    print(f"    手牌数: {final_state.get('opp_hand_count', 0)}")
    print(f"    牌库剩余: {final_state.get('opp_deck_count', '?')}")
    print(f"    初始牌库: {final_state.get('opp_initial_deck_size', 0)}")
    print(f"    已知卡牌数: {len(final_state.get('known_cards', []))}")
    print(f"    揭示手牌: {len(final_state.get('reveal_info', {}).get('revealed_hand_cards', []))}")
    
    # Analyze known cards by source
    source_counter = Counter()
    for kc in all_known_cards:
        src = kc.get("source", "unknown")
        source_counter[src] += 1
    print(f"\n  己知卡牌来源分布:")
    for src, cnt in source_counter.most_common():
        pct = cnt / len(all_known_cards) * 100
        print(f"    {src}: {cnt} ({pct:.1f}%)")
    
    # Check the last few state_dicts for hand predictions
    if all_predictions:
        last_pred = all_predictions[-1]
        print(f"\n  最后一次手牌预测结果:")
        print(f"    archetype: {last_pred.archetype_name} ({last_pred.archetype_confidence:.1%})")
        print(f"    playstyle: {last_pred.playstyle}")
        print(f"    手牌预测条目: {len(last_pred.hand_predictions)}")
        print(f"    卡组预测条目: {len(last_pred.deck_predictions)}")
        print(f"    MCTS applied: {last_pred.mcts_applied}")
        
        # Top hand predictions
        print(f"\n    Top 手牌预测 (概率 > 5%):")
        sorted_hp = sorted(last_pred.hand_predictions, key=lambda x: -x.probability)
        for hp in sorted_hp[:15]:
            if hp.probability > 0.05 or hp.source == "revealed":
                src = hp.source
                prob = hp.probability
                print(f"      {hp.name:20s} ({hp.card_id:20s}) {prob:5.1%} [{src}]")
        
        # Multi-deck predictions
        if last_pred.multi_deck_predictions:
            print(f"\n    Multi-Deck Predictions:")
            for name, prob, cards in last_pred.multi_deck_predictions[:3]:
                print(f"      {name} ({prob:.1%}): {len(cards)} cards")
                deck_source = Counter(c.source for c in cards)
                for s, c in deck_source.most_common():
                    print(f"        {s}: {c}")
        
        # Derived cards
        if last_pred.derived_cards:
            print(f"\n    衍生牌追踪:")
            for dc in last_pred.derived_cards:
                src = dc.get("source_card_id", "?")
                derived = dc.get("derived_cards", [])
                print(f"      {src} → {len(derived)} 衍生牌")
                for d in derived[:5]:
                    print(f"        {d['card_id']} ({d['derive_type']})")
    
    # ── 分析维度 4: 卡组 vs 衍生牌区分 ──
    print("\n" + "=" * 70)
    print("维度 4: 卡组牌 vs 衍生牌区分")
    print("=" * 70)
    
    # Check generated_cards tracking at final state
    generated = final_state.get("generated_cards", set())
    shuffled = final_state.get("opp_shuffled_into_deck", [])
    
    print(f"\n  衍生牌集合大小: {len(generated)}")
    
    # Show all generated cards with names
    for cid in list(generated)[:20]:
        card = card_db.get_card(cid) if card_db else None
        name = card.get("name", cid) if card else cid
        print(f"    {name} ({cid})")
    if len(generated) > 20:
        print(f"    ... 共 {len(generated)} 张衍生牌")
    
    print(f"\n  洗入牌库的衍生牌: {len(shuffled)}")
    for cid in shuffled[:10]:
        card = card_db.get_card(cid) if card_db else None
        name = card.get("name", cid) if card else cid
        print(f"    {name} ({cid})")
    
    # Check opp_graveyard breakdown
    graveyard = final_state.get("graveyard", [])
    print(f"\n  对手墓地: {len(graveyard)} 张牌")
    gv_source = Counter()
    for g in graveyard:
        src = g.get("source", "unknown") if isinstance(g, dict) else "unknown"
        gv_source[src] += 1
    for src, cnt in gv_source.most_common():
        print(f"    {src}: {cnt}")
    
    # ── 分析维度 5: MCTS 模拟 vs 实际行为 ──
    print("\n" + "=" * 70)
    print("维度 5: MCTS 行为匹配分析")
    print("=" * 70)
    
    mcts_final = all_predictions[-1] if all_predictions else None
    if mcts_final:
        print(f"\n  MCTS 状态: {'✅ 已应用' if mcts_final.mcts_applied else '❌ 未应用'}")
        print(f"  MCTS Top 预测:")
        for cid, prob in mcts_final.mcts_top_predictions[:10]:
            card = card_db.get_card(cid) if card_db else None
            name = card.get("name", cid) if card else cid
            print(f"    {name:20s} ({cid:20s}) {prob:.1%}")
    
    # ── 关键发现报告 ──
    print("\n" + "=" * 70)
    print("📋 关键发现报告")
    print("=" * 70)
    
    issues = []
    
    # Issue 1: 随机效果未被追踪
    if has_random:
        issues.append((
            "随机效果静默丢弃",
            f"本局有 {len(has_random)} 张带 'random' 的卡牌效果未被 CardEffectInferenceEngine 追踪",
            "高"
        ))
    
    # Issue 2: 贝叶斯模型未匹配
    if not bayesian.get("archetype_name"):
        issues.append((
            "贝叶斯卡组推断失效",
            "MAGE 职业未匹配到任何卡组 (hsreplay 数据缺失或卡组代码过期)",
            "高"
        ))
    
    # Issue 3: 衍生牌追踪
    # Check if generated cards appear in deck predictions
    if all_predictions:
        last_pred = all_predictions[-1]
        for dp in last_pred.deck_predictions:
            if dp.source == "deck" and dp.card_id in generated:
                issues.append((
                    "衍生牌被误标为卡组牌",
                    f"{dp.name} ({dp.card_id}) 是衍生牌但被标记为 deck 来源",
                    "中"
                ))
                break
    
    # Issue 4: Initial deck size issue
    if final_state.get("opp_initial_deck_size", 30) == 0:
        issues.append((
            "初始牌库大小未知",
            "opp_initial_deck_size=0，卡组剩余推算基准缺失",
            "中"
        ))
    
    # Issue 5: 已知卡牌数异常
    if len(all_known_cards) > 60:
        issues.append((
            "已知卡牌数异常偏高",
            f"本局 known_cards 共 {len(all_known_cards)} 条记录 (含重复日志条目)，实际唯一卡牌 {len(unique_cards)} 张",
            "低"
        ))
    
    for title, detail, severity in issues:
        print(f"\n  [{'🔴' if severity=='高' else '🟡' if severity=='中' else '🟢'}] {title}")
        print(f"     {detail}")
        print(f"     严重程度: {severity}")
    
    print(f"\n  总计 {len(issues)} 个发现")


if __name__ == "__main__":
    log_path = project_root / "Power.log"
    if not log_path.exists():
        print(f"Error: {log_path} not found")
        sys.exit(1)
    analyze_game(log_path)

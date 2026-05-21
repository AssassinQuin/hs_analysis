#!/usr/bin/env python3
"""diagnostic_engine.py — Power.log 诊断分析引擎

逐行解析 Power.log → 游戏状态重建 → MCTS 诊断 → 手牌概率 → 模拟对比

输出: 结构化 dict 供 Flask Web App 展示
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── 确保项目根在 sys.path ──────────────────────────────────
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


@dataclass
class TurnSnapshot:
    """单回合快照 — 诊断用结构化数据"""
    turn_number: int = 0
    step: str = ""
    player: Dict = field(default_factory=dict)
    opponent: Dict = field(default_factory=dict)

    # 实际出牌
    player_plays: List[Dict] = field(default_factory=list)
    opp_plays: List[Dict] = field(default_factory=list)

    # MCTS
    mcts_action_stats: List[Dict] = field(default_factory=list)
    mcts_best_seq: List[str] = field(default_factory=list)
    mcts_iterations: int = 0
    mcts_nodes: int = 0
    mcts_elapsed_ms: float = 0.0

    # 手牌预测
    hand_predictions: List[Dict] = field(default_factory=list)
    archetype_name: str = ""
    archetype_confidence: float = 0.0
    mcts_top_predictions: List[tuple] = field(default_factory=list)

    # 卡牌执行对比
    simulation_checks: List[Dict] = field(default_factory=list)

    # 滑动窗口推断手牌
    sampled_hand: List[str] = field(default_factory=list)

    # 原始状态 dict
    raw_state: Dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """完整分析结果"""
    log_path: str = ""
    game_info: Dict = field(default_factory=dict)
    turns: List[TurnSnapshot] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    raw_lines_by_turn: Dict[int, List[str]] = field(default_factory=dict)
    total_turns: int = 0
    total_errors: int = 0


# ═══════════════════════════════════════════════════════════
# Phase 1: Power.log 逐行解析 — 重建游戏事件
# ═══════════════════════════════════════════════════════════

def _parse_card_play(text: str) -> Optional[Dict]:
    """从 raw line 检测卡牌打出事件。
    
    示例:
      TAG_CHANGE Entity=卡牌实体 tag=ZONE value=PLAY  ← 卡牌从手牌进入战场
      FULL_ENTITY - Creating ID=XX CardID=XXX           ← 卡牌揭示
    """
    import re
    # TAG_CHANGE → ZONE=PLAY 检测
    m = re.search(r'TAG_CHANGE.*Entity=(\d+).*tag=ZONE value=PLAY', text)
    if m:
        return {"type": "zone_to_play", "entity_id": int(m.group(1))}
    # FULL_ENTITY 创建（揭示 card_id）
    m = re.search(r'FULL_ENTITY - Creating ID=(\d+) CardID=(\S+)', text)
    if m:
        return {"type": "full_entity", "entity_id": int(m.group(1)), "card_id": m.group(2)}
    return None


def parse_raw_lines_by_turn(lines: List[str]) -> Dict[int, List[str]]:
    """将 Power.log 行按回合分组（逐行读取）。

    使用 TAG_CHANGE Entity=GameEntity tag=TURN value=N 作为回合边界，
    Entity=GameEntity 唯一标识全局回合数，不会重复计数。
    """
    grouped: Dict[int, List[str]] = defaultdict(list)
    current_turn = 0
    for line in lines:
        grouped[current_turn].append(line)
        # 仅 Entity=GameEntity 的 turn 变化标识真实回合边界
        if "TAG_CHANGE" in line and "Entity=GameEntity" in line and "tag=TURN" in line:
            m = __import__('re').search(r'value=(\d+)', line)
            if m:
                current_turn = int(m.group(1))
    return grouped


# ═══════════════════════════════════════════════════════════
# Phase 2: MCTS 诊断
# ═══════════════════════════════════════════════════════════

def _get_bayesian_top_deck_cards(monitor) -> Optional[list]:
    """从 Bayesian 模型获取 top-1 卡组的 card_id 列表。"""
    try:
        bayesian = getattr(monitor.global_tracker, '_bayesian_model', None)
        if bayesian is None:
            return None
        top = bayesian.get_top_decks(1)
        if not top:
            return None
        aid, name, prob = top[0]
        deck = bayesian._find_deck(aid)
        if not deck:
            return None
        card_ids = []
        for dbf in deck["cards"]:
            info = bayesian.cards_by_dbf.get(dbf)
            if info and info.get("cardId"):
                card_ids.append(info["cardId"])
        if card_ids:
            logger.info(
                "Bayesian top-1 deck [%s] (prob=%.0f%%): %d 张卡牌作为采样池",
                name, prob * 100, len(card_ids),
            )
        return card_ids
    except Exception as e:
        logger.debug("Bayesian top deck lookup failed: %s", e)
        return None


def run_mcts_diagnostic(
    state_dict: Dict,
    game_state,
    opp_class: str,
    time_budget_ms: float = 3000.0,
) -> Dict:
    """对当前游戏状态运行 MCTS 搜索，返回诊断用结构化数据。"""
    result: Dict = {
        "action_stats": [],
        "best_seq": [],
        "iterations": 0,
        "nodes": 0,
        "elapsed_ms": 0.0,
    }

    try:
        from analysis.card.engine.state import GameState
        from analysis.card.abilities.definition import Action, ActionType

        # 构建 GameState
        state = _build_game_state(state_dict, game_state)
        if state is None:
            return result

        # MCTS 搜索
        from analysis.search.mcts.engine import MCTSEngine
        from analysis.search.mcts.config import MCTSConfig

        config = MCTSConfig(time_budget_ms=time_budget_ms)
        engine = MCTSEngine(config)

        bayesian_model = _get_bayesian(state_dict)
        start = time.time()
        search_result = engine.search(
            state,
            time_budget_ms=time_budget_ms,
            bayesian_model=bayesian_model,
            opp_playstyle=_get_playstyle(state_dict),
        )
        elapsed = time.time() - start

        result["elapsed_ms"] = round(elapsed * 1000, 1)
        if search_result.mcts_stats:
            result["iterations"] = search_result.mcts_stats.iterations
            result["nodes"] = search_result.mcts_stats.nodes_created

        # Action stats (root children)
        for as_ in search_result.action_stats:
            result["action_stats"].append({
                "action": str(as_.action),
                "action_type": str(as_.action.action_type),
                "visit_count": as_.visit_count,
                "total_reward": round(as_.total_reward, 4),
                "q_value": round(as_.q_value, 4),
                "visit_probability": round(as_.visit_probability, 4),
                "win_rate": round(as_.win_rate, 4),
            })

        # Best sequence
        result["best_seq"] = [str(a) for a in search_result.best_sequence]

    except Exception as e:
        logger.warning("MCTS diagnostic failed: %s", e)

    return result


def _build_game_state(state_dict: Dict, game_state) -> Optional[object]:
    """从 state_dict 构建 GameState (复用现有逻辑)。"""
    try:
        from analysis.card.engine.state import GameState, HeroState, ManaState
        from analysis.card.data.card_data import get_db

        db = get_db()
        gs = GameState()

        # 我方英雄 + 水晶
        gs.hero = _build_hero(state_dict, "player")
        # 读取 mana: state_dict 可能是 turn_state (nested) 或原始 state_dict (flat)
        player_info = state_dict.get("player", {})
        gs.mana.available = player_info.get("mana", state_dict.get("player_mana", 0))
        gs.mana.max_mana = player_info.get("max_mana", state_dict.get("player_max_mana", 0))

        # 对手
        gs.opponent.hero = _build_hero(state_dict, "opp")
        gs.opponent.hand_count = state_dict.get("opp_hand_count", 0)
        gs.opponent.deck_remaining = state_dict.get("opp_deck_count", 0)

        # 手牌 (优先 sampled_hand_cards，否则用 player_hand_cards)
        hand_src = state_dict.get("sampled_hand_cards") or state_dict.get("player_hand_cards", [])
        hand_cards = []
        hand_count = len(hand_src) or state_dict.get("player_hand_count", 0)
        for cid in hand_src:
            card_data = db.get_card(cid)
            if card_data:
                from analysis.card.models.card import Card
                try:
                    hand_cards.append(Card.from_hsdb_dict(card_data))
                    continue
                except Exception:
                    pass
            # card_id 不在 DB 中或构造失败 → 用 None 占位
            hand_cards.append(None)
        # 填充到正确数量（已知卡牌少于手牌数时补 None）
        while len(hand_cards) < hand_count:
            hand_cards.append(None)
        gs.hand = hand_cards

        # 我方场
        for bm in state_dict.get("player_board_minions", []):
            m = _build_minion(bm)
            if m:
                gs.board.append(m)

        # 对手场
        for bm in state_dict.get("opp_board_minions", []):
            m = _build_minion(bm)
            if m:
                gs.opponent.board.append(m)

        gs.turn_number = state_dict.get("turn", 0)

        if game_state is not None:
            try:
                gs.deck_list = list(getattr(game_state, '_deck', []))
                gs.deck_remaining = len(gs.deck_list) if gs.deck_list else 0
            except Exception:
                pass

        return gs
    except Exception as e:
        logger.warning("GameState build failed: %s", e)
        return None


def _build_hero(state_dict: Dict, side: str) -> HeroState:
    """构建 HeroState。"""
    from analysis.card.engine.state import HeroState
    h = HeroState()
    key = "player" if side == "player" else "opp"
    h.hp = state_dict.get(f"{key}_health", 30)
    h.max_hp = 30
    h.armor = state_dict.get(f"{key}_armor", 0)
    return h


def _build_minion(bm: Dict) -> Optional[object]:
    """构建 Minion (使用 GameState 的 Minion 类)。"""
    try:
        from analysis.card.engine.state import Minion
        m = Minion()
        m.card_id = bm.get("card_id", "")
        m.attack = bm.get("attack", 0)
        health = bm.get("health", 1)
        m.health = health
        m.max_health = health
        return m
    except Exception:
        return None


def _get_bayesian(state_dict: Dict) -> Optional[object]:
    """获取贝叶斯模型。"""
    try:
        bayesian_data = state_dict.get("bayesian", {})
        if bayesian_data.get("deck_confidence", 0) > 0.3:
            from analysis.engine.bayesian_model import BayesianOpponentModel
            model = BayesianOpponentModel()
            # Fill from available data
            deck_ids = []
            for _, _, prob in bayesian_data.get("top_decks", []):
                deck_ids.append((_, prob))
            return model
    except Exception:
        pass
    return None


def _get_playstyle(state_dict: Dict) -> str:
    return state_dict.get("bayesian", {}).get("playstyle", "unknown")


# ═══════════════════════════════════════════════════════════
# Phase 3: 手牌概率诊断
# ═══════════════════════════════════════════════════════════

def run_hand_prediction(state_dict: Dict) -> Dict:
    """运行手牌预测，返回诊断用数据。"""
    result: Dict = {
        "hand_predictions": [],
        "archetype_name": "",
        "archetype_confidence": 0.0,
        "top_archetypes": [],
        "mcts_top": [],
        "playstyle": "",
        "errors": [],
    }

    try:
        from tracker.hand_predictor import HandPredictor

        predictor = HandPredictor()
        prediction = predictor.predict(state_dict)

        result["archetype_name"] = prediction.archetype_name or ""
        result["archetype_confidence"] = prediction.archetype_confidence
        result["playstyle"] = prediction.playstyle

        # Top archetypes
        result["top_archetypes"] = [
            {"name": name, "probability": round(prob, 4)}
            for name, prob in prediction.top_archetypes[:5]
        ]

        # Hand predictions (per-card)
        for hp in prediction.hand_predictions[:20]:
            result["hand_predictions"].append({
                "card_id": hp.card_id,
                "name": hp.name,
                "cost": hp.cost,
                "probability": round(hp.probability, 4),
                "source": hp.source,
                "card_type": hp.card_type,
            })

        # MCTS top predictions
        mcts_top = getattr(prediction, 'mcts_top_predictions', [])
        result["mcts_top"] = [
            {"card_id": cid, "probability": round(prob, 4)}
            for cid, prob in mcts_top[:10]
        ]

    except Exception as e:
        result["errors"].append(str(e))
        logger.warning("Hand prediction diagnostic failed: %s", e)

    return result


# ═══════════════════════════════════════════════════════════
# Phase 4: 卡牌执行对比
# ═══════════════════════════════════════════════════════════

def check_card_execution(
    actual_plays: List[Dict],
    state_dict: Dict,
) -> List[Dict]:
    """对比实际卡牌执行 vs 模拟器预测效果。"""
    checks = []
    for play in actual_plays:
        check = {
            "card_id": play.get("card_id", ""),
            "name": play.get("name", play.get("card_id", "")),
            "actual_effect": play.get("effect", "unknown"),
            "simulated_effect": "N/A",
            "match": None,  # True/False/None=unknown
            "detail": "",
        }
        try:
            sim = _simulate_card_effect(play.get("card_id", ""), state_dict)
            check["simulated_effect"] = sim.get("effect", "unknown")
            check["detail"] = sim.get("detail", "")
            check["match"] = sim.get("match", None)
        except Exception as e:
            check["detail"] = f"Simulation failed: {e}"
            check["match"] = None
        checks.append(check)
    return checks


def _simulate_card_effect(card_id: str, state_dict: Dict) -> Dict:
    """对一张卡牌运行模拟器，返回预期效果。"""
    result = {"effect": "unknown", "detail": "", "match": None}

    try:
        from analysis.card.data.card_data import get_db
        from analysis.card.engine.simulation import apply_action
        from analysis.card.abilities.definition import Action, ActionType

        db = get_db()
        card = db.get_card(card_id)
        if not card:
            result["effect"] = "card_not_found"
            result["detail"] = f"Card {card_id} not in DB"
            return result

        effect = _describe_card_effect(card)
        result["effect"] = effect.get("description", "unknown")
        result["detail"] = json.dumps(effect, ensure_ascii=False)

    except Exception as e:
        result["detail"] = str(e)

    return result


def _describe_card_effect(card: Dict) -> Dict:
    """描述一张卡牌的模拟效果。"""
    desc = {
        "description": "",
        "type": card.get("type", ""),
        "cost": card.get("cost", 0),
        "attack": card.get("attack", 0),
        "health": card.get("health", 0),
        "mechanics": [],
    }

    # 从 v2 CardAbility 获取
    try:
        from analysis.card.abilities.model import SpellDesc
        from analysis.card.abilities.registry import get_ability

        ability = get_ability(card.get("id", ""))
        if ability:
            if ability.on_play:
                desc["mechanics"].append(f"ON_PLAY: {ability.on_play.spell_class}")
            if ability.triggers:
                for t in ability.triggers:
                    desc["mechanics"].append(f"TRIGGER({t.event_type}): {t.spell.spell_class}")
    except Exception:
        pass

    # 从 card_abilities_v2.json 获取
    try:
        v2_path = _project_root / "analysis" / "card" / "data" / "card_abilities_v2.json"
        if v2_path.exists():
            data = json.loads(v2_path.read_text(encoding="utf-8"))
            card_data = data.get(card.get("id", ""), {})
            if card_data:
                desc["v2_ability"] = card_data
    except Exception:
        pass

    # 文本描述
    text = card.get("text", "") or card.get("english_text", "") or ""
    if text:
        desc["text"] = text

    if not desc["mechanics"] and not desc.get("v2_ability"):
        desc["description"] = f"{card.get('type','')} (费{card.get('cost',0)}/{card.get('attack','?')}/{card.get('health','?')})"
        if card.get("type") == "SPELL" and text:
            desc["description"] = f"法术: {text}"
        elif card.get("type") == "MINION":
            desc["description"] = f"随从 {card.get('attack',0)}/{card.get('health',0)}"
        elif card.get("type") == "WEAPON":
            desc["description"] = f"武器 {card.get('attack',0)}/{card.get('durability',0)}"

    return desc


# ═══════════════════════════════════════════════════════════
# Phase 5: 完整分析管线
# ═══════════════════════════════════════════════════════════

def analyze_power_log(
    log_path: str,
    run_mcts: bool = True,
    mcts_budget_ms: float = 2000.0,
    progress_callback=None,
) -> AnalysisResult:
    """运行完整的 Power.log 诊断分析。

    Args:
        log_path: Power.log 文件路径
        run_mcts: 是否运行 MCTS 搜索（耗时操作）
        mcts_budget_ms: 每次 MCTS 搜索预算（毫秒）
        progress_callback: 可选回调函数(status, current, total)

    Returns:
        AnalysisResult
    """
    result = AnalysisResult(log_path=log_path)
    log_file = Path(log_path)

    if not log_file.exists():
        result.errors.append(f"文件不存在: {log_path}")
        return result

    # ── 1. 读取原始行 ────────────────────────────────────
    if progress_callback:
        progress_callback("reading", 0, 1)

    with log_file.open("r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    # ── 2. 解析 Power.log ────────────────────────────────
    if progress_callback:
        progress_callback("parsing", 0, 1)

    # 按回合分组 raw lines
    result.raw_lines_by_turn = parse_raw_lines_by_turn(raw_lines)

    try:
        from tracker.log_monitor import CoreLogMonitor
        monitor = CoreLogMonitor()
        monitor._log_path = Path(log_path)

        # 逐回合增量 feed，收集每回合状态快照
        per_turn_states: Dict[int, dict] = {}
        for turn_num in sorted(result.raw_lines_by_turn.keys()):
            batch = [
                l.rstrip("\n").rstrip("\r")
                for l in result.raw_lines_by_turn[turn_num]
                if l.strip()
            ]
            if batch:
                monitor._process_lines(batch)
            if turn_num > 0:
                per_turn_states[turn_num] = monitor.build_state_dict()

        # 最后补齐玩家信息（同 load_existing_log）
        monitor._enrich_player_info_core(re_bridge=True, re_emit=False)

    except Exception as e:
        result.errors.append(f"Power.log 解析失败: {e}")
        return result

    # ── 3. 构建总览信息 ──────────────────────────────────
    if progress_callback:
        progress_callback("analyzing", 0, 1)

    try:
        # 使用最后一回合的状态构建 game_info（最完整）
        final_state = per_turn_states.get(max(per_turn_states.keys() or [0]), {})
        game_state = getattr(monitor, 'game_tracker', None)

        result.game_info = {
            "in_game": final_state.get("in_game", False),
            "turn": final_state.get("turn", 0),
            "player_class": final_state.get("player_class", "未知"),
            "opp_class": final_state.get("opp_class", "未知"),
            "player_class_en": final_state.get("player_class_en", ""),
            "opp_class_en": final_state.get("opp_class_en", ""),
        }

        # ── 4. 初始化 DeckPoolTracker（滑动窗口手牌推断）─
        pool_tracker = None
        try:
            player_class_en = result.game_info.get("player_class_en", "")
            if player_class_en:
                from analysis.utils.deck_pool_tracker import DeckPoolTracker

                # 从 Bayesian 模型获取 top-1 卡组作为初始采样池
                bayesian_pool = _get_bayesian_top_deck_cards(monitor)
                if bayesian_pool:
                    pool_tracker = DeckPoolTracker(
                        player_class_en, initial_pool=set(bayesian_pool))
                else:
                    pool_tracker = DeckPoolTracker(player_class_en)

                # 填入所有已知卡牌数据
                # a) 玩家已打出的牌
                for play in final_state.get("player_cards_played_history", []):
                    pid = play.get("card_id") if isinstance(play, dict) else None
                    if pid:
                        pool_tracker.register_player_played(pid)
                # b) 对手已打出的牌 (非衍生 vs 衍生)
                for play in final_state.get("opp_play_history", []):
                    pid = play.get("card_id") if isinstance(play, dict) else None
                    if pid:
                        is_derived = play.get("card_type", "") in (
                            "TOKEN", "GENERATED"
                        ) if isinstance(play, dict) else False
                        pool_tracker.register_opp_played(pid, is_derived)
                logger.info(
                    "DeckPoolTracker[%s]: pool=%d available=%d",
                    player_class_en, pool_tracker.pool_size, pool_tracker.available_size,
                )
        except Exception as e:
            logger.warning("DeckPoolTracker init failed: %s", e)
            pool_tracker = None

        # ── 5. 逐回合分析 ─────────────────────────────────
        total_turns = result.game_info.get("turn", 1)
        for turn in range(1, total_turns + 1):
            if progress_callback:
                progress_callback(f"turn_{turn}", turn, total_turns)

            snapshot = TurnSnapshot(turn_number=turn)

            try:
                # 使用该回合的增量状态快照
                turn_state_dict = per_turn_states.get(turn, final_state)
                turn_state = _extract_turn_state(turn_state_dict, turn)
                snapshot.raw_state = turn_state
                snapshot.player = turn_state.get("player", {})
                snapshot.opponent = turn_state.get("opponent", {})
                snapshot.player_plays = turn_state.get("player_plays", [])
                snapshot.opp_plays = turn_state.get("opp_plays", [])

                # 用 DeckPoolTracker 填充未知手牌
                if pool_tracker is not None:
                    try:
                        known = turn_state.get("player_hand_cards", [])
                        hcount = turn_state.get("player", {}).get("hand_count", 0)
                        filled = pool_tracker.fill_unknown_hand(
                            known, hcount, seed=turn,
                        )
                        turn_state["sampled_hand_cards"] = filled
                        snapshot.sampled_hand = filled
                    except Exception as e:
                        logger.warning("Turn %d hand sampling failed: %s", turn, e)
                        turn_state["sampled_hand_cards"] = (
                            turn_state.get("player_hand_cards", [])
                        )

                # 手牌预测
                hp = run_hand_prediction(turn_state)
                snapshot.hand_predictions = hp["hand_predictions"]
                snapshot.archetype_name = hp["archetype_name"]
                snapshot.archetype_confidence = hp["archetype_confidence"]
                snapshot.mcts_top_predictions = hp["mcts_top"]

                # 卡牌执行对比
                snapshot.simulation_checks = check_card_execution(
                    snapshot.opp_plays + snapshot.player_plays,
                    turn_state,
                )

                # MCTS 搜索（可选, 只在对手回合运行）
                if run_mcts and turn_state.get("is_opponent_turn", False):
                    mcts_data = run_mcts_diagnostic(
                        turn_state, game_state,
                        result.game_info.get("opp_class_en", ""),
                        time_budget_ms=mcts_budget_ms,
                    )
                    snapshot.mcts_action_stats = mcts_data["action_stats"]
                    snapshot.mcts_best_seq = mcts_data["best_seq"]
                    snapshot.mcts_iterations = mcts_data["iterations"]
                    snapshot.mcts_nodes = mcts_data["nodes"]
                    snapshot.mcts_elapsed_ms = mcts_data["elapsed_ms"]

            except Exception as e:
                result.errors.append(f"Turn {turn} analysis failed: {e}")

            result.turns.append(snapshot)
            result.total_turns = turn

    except Exception as e:
        result.errors.append(f"Analysis pipeline failed: {e}")
        traceback.print_exc()

    result.total_errors = len(result.errors)
    if progress_callback:
        progress_callback("done", 0, 0)

    return result


def _extract_turn_state(state_dict: Dict, turn: int) -> Dict:
    """从完整 state_dict 中提取单回合状态。

    Gauge: mana 估算 — Power.log 解析器不包含每回合法力值，
    这里从回合数估算（标准对局每回合+1水晶，上限10）。
    """
    estimated_mana = min(turn, 10)
    return {
        "turn": turn,
        "player": {
            "hand_count": state_dict.get("player_hand_count", 0),
            "deck_count": state_dict.get("player_deck_count", 0),
            "health": state_dict.get("player_health", 30),
            "armor": state_dict.get("player_armor", 0),
            "mana": state_dict.get("player_mana", estimated_mana),
            "max_mana": state_dict.get("player_max_mana", estimated_mana),
        },
        "opponent": {
            "hand_count": state_dict.get("opp_hand_count", 0),
            "deck_count": state_dict.get("opp_deck_count", 0),
            "health": state_dict.get("opp_health", 30),
            "armor": state_dict.get("opp_armor", 0),
        },
        # 顶层字段用于 hand_predictor 兼容
        "opp_hand_count": state_dict.get("opp_hand_count", 0),
        "opp_deck_count": state_dict.get("opp_deck_count", 0),
        "opp_class_en": state_dict.get("opp_class_en", ""),
        "player_hand_cards": state_dict.get("player_hand_cards", []),
        "known_hand": [
            {"card_id": c[1], "entity_id": c[0]}
            for c in state_dict.get("known_hand", [])
        ],
        "player_plays": state_dict.get("player_play_history", []),
        "opp_plays": state_dict.get("opp_play_history", []),
        "is_opponent_turn": turn % 2 == 1,  # rough heuristic
        "bayesian": state_dict.get("bayesian", {}),
        "reveal_info": state_dict.get("reveal_info", {}),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = sys.argv[1] if len(sys.argv) > 1 else str(_project_root / "Power.log")
    print(f"Analyzing {log} ...")

    def _progress(s, c, t):
        print(f"  [{s}] {c}/{t}")

    result = analyze_power_log(log, run_mcts=False)
    print(f"\nGame: {result.game_info}")
    print(f"Turns: {result.total_turns}")
    print(f"Errors: {result.total_errors}")

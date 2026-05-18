#!/usr/bin/env python3
"""run_mcts.py — Replay Power.log through MCTS engine to see decisions.

Architecture:
- Internal: all card references use card_id (e.g. "TLC_460")
- Display: card_id → localized name only at output layer (i18n ready)

Usage:
    python scripts/run_mcts.py
    python scripts/run_mcts.py --budget 25000 --single-budget 5000
    python scripts/run_mcts.py --max-turns 5 --log-file logs/mcts.log
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from datetime import datetime

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.watcher.deck_provider import DeckProvider
from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.search.abilities.enumeration import enumerate_legal_actions
from analysis.search.abilities.actions import ActionType
from analysis.search.abilities.simulation import apply_action as _apply_sim_action
from analysis.utils.bayesian_opponent import BayesianOpponentModel
from hearthstone.enums import GameTag, Zone as HZone, CardType as HCardType


# ── Display Layer (i18n-ready) ──────────────────────────────

def _card_display(card) -> str:
    """Format a card for display output. Uses display_name + cost."""
    name = getattr(card, 'display_name', '') or getattr(card, 'name', '') or '???'
    cost = getattr(card, 'cost', '?')
    return f"{name}({cost})"


def _minion_display(m) -> str:
    """Format a minion for display output."""
    name = getattr(m, 'name', '') or getattr(m, 'display_name', '') or '???'
    return f"{name}({m.attack}/{m.health})"


def _action_display(action, state) -> str:
    """Format an action for display, using card_id → name resolution."""
    desc = action.describe(state)

    # Replace card_id references with display names in description
    if state.hand:
        for i, card in enumerate(state.hand):
            card_id = getattr(card, 'card_id', '')
            display = _card_display(card)
            if card_id and card_id in desc:
                desc = desc.replace(card_id, display)
            # Also replace generic placeholders like [卡牌#0]
            placeholder = f"卡牌#{i}"
            if placeholder in desc:
                desc = desc.replace(placeholder, display)

    return desc


# ── MCTS Analysis ───────────────────────────────────────────

def run_mcts_analysis(
    log_path: str,
    budget_ms: float = 25000.0,
    single_budget_ms: float = 5000.0,
    max_turns: int = 0,
    log_file_path: str = None,
    log_dir: str = None,
) -> None:
    """Analyze Power.log with MCTS engine."""
    log_path = Path(log_path)
    if not log_path.exists():
        print(f"File not found: {log_path}")
        return

    # If log_dir is provided, resolve Power.log and Decks.log from it
    log_dir_path = Path(log_dir) if log_dir else None

    # Ensure logs directory exists
    if log_file_path:
        Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)
        log_f = open(log_file_path, 'w', encoding='utf-8')
    else:
        log_dir_out = Path(__file__).resolve().parent.parent / "logs"
        log_dir_out.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file_path = str(log_dir_out / f"mcts_{ts}.log")
        log_f = open(log_file_path, 'w', encoding='utf-8')

    def out(s=''):
        print(s, flush=True)
        log_f.write(s + '\n')
        log_f.flush()

    # Setup DeckProvider if log_dir contains Decks.log
    deck_provider = None
    deck_cards_list = []
    if log_dir_path:
        decks_log = log_dir_path / "Decks.log"
        if decks_log.exists():
            deck_provider = DeckProvider(str(decks_log))
            out(f"DeckProvider loaded from: {decks_log}")
        else:
            out(f"No Decks.log found in {log_dir_path}")

    # StateBridge with entity cache from GameTracker
    tracker = GameTracker(deck_provider=deck_provider)
    bridge = StateBridge(entity_cache=tracker.entity_cache)

    config = MCTSConfig(
        time_budget_ms=single_budget_ms,
        num_worlds=5,
        time_decay_gamma=0.4,
        min_step_budget_ms=max(300, single_budget_ms * 0.1),
        max_actions_per_turn=8,
    )
    engine = MCTSEngine(config)

    # 贝叶斯对手推断模型
    bayesian_model = BayesianOpponentModel()
    _prev_opp_known: set = set()  # 上回合已知的对手 dbfId 集合
    out(f"Bayesian model: {len(bayesian_model.decks)} meta archetypes loaded")

    out(f"{'='*60}")
    out(f"MCTS Analysis | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out(f"File: {log_path}")
    out(f"Config: total_budget={budget_ms}ms, single={single_budget_ms}ms, "
        f"worlds={config.num_worlds}, uct_c={config.uct_constant}, gamma={config.time_decay_gamma}")
    out(f"Log: {log_file_path}")
    out(f"{'='*60}")
    out()

    last_turn = -1
    decision_count = 0
    total_time = 0.0
    turn_start_time = None

    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            event = tracker.feed_line(line.strip())

            if event == 'game_start':
                out(f"\n{'─'*60}")
                out(f"New Game Started")
                # Update bridge with deck cards for this game
                if deck_provider and tracker.game_start_timestamp:
                    deck_cards_list = tracker.deck_cards
                    bridge = StateBridge(
                        entity_cache=tracker.entity_cache,
                        deck_cards=deck_cards_list,
                    )
                    current_deck = tracker.current_deck
                    if current_deck:
                        out(f"Deck: {current_deck.name} ({current_deck.card_count} cards, "
                            f"{current_deck.hero_class})")
                else:
                    bridge = StateBridge(entity_cache=tracker.entity_cache)
                out(f"{'─'*60}")
                last_turn = -1
                decision_count = 0
                total_time = 0.0
                # 重置贝叶斯模型（Turn 1 时根据对手职业重建）
                bayesian_model = BayesianOpponentModel()
                _prev_opp_known = set()

            elif event == 'game_end':
                out(f"\nGame Over — {decision_count} decisions, "
                    f"{total_time:.0f}ms total")
                break

            elif event == 'turn_start':
                game = tracker.export_entities()
                if not game:
                    continue

                # 动态检测友方玩家索引：
                # hslog game.players 按 CREATE_GAME 顺序排列，
                # players[0]=Player1（先手）, players[1]=Player2（后手）。
                # logging player 的手牌可见（mulligan 阶段 SHOW_ENTITY），
                # 对手手牌始终隐藏（card_id 为空）。
                _friendly_idx = 0
                if len(game.players) >= 2:
                    visible_0 = sum(
                        1 for e in getattr(game.players[0], 'entities', [])
                        if getattr(e, 'card_id', '') and
                           getattr(e, 'tags', {}).get(GameTag.ZONE) == HZone.HAND
                    )
                    visible_1 = sum(
                        1 for e in getattr(game.players[1], 'entities', [])
                        if getattr(e, 'card_id', '') and
                           getattr(e, 'tags', {}).get(GameTag.ZONE) == HZone.HAND
                    )
                    if visible_1 > visible_0:
                        _friendly_idx = 1

                state = bridge.convert(game, player_index=_friendly_idx)
                if not state or state.turn_number <= 0:
                    continue
                current_turn = state.turn_number
                if current_turn == last_turn:
                    continue

                # 只分析自己的回合：
                # Player 1 (先手, idx=0) 的回合: Turn 1,3,5... (奇数)
                # Player 2 (后手, idx=1) 的回合: Turn 2,4,6... (偶数)
                is_our_turn = (current_turn % 2 != _friendly_idx)

                # ── 贝叶斯对手推断（每回合都更新） ──
                # Turn 1: 检测对手职业，重建带职业过滤的 Bayesian 模型
                if current_turn == 1:
                    opp_player = game.players[1 - _friendly_idx]
                    opp_class = None
                    from hearthstone.enums import CardClass as HCardClass
                    for ent in getattr(opp_player, 'entities', []):
                        tags = getattr(ent, 'tags', {})
                        if (tags.get(GameTag.ZONE) == HZone.PLAY and
                                tags.get(GameTag.CARDTYPE) == HCardType.HERO):
                            cls_val = tags.get(GameTag.CLASS, 0)
                            if isinstance(cls_val, HCardClass):
                                opp_class = cls_val.name
                            elif isinstance(cls_val, int):
                                try:
                                    opp_class = HCardClass(cls_val).name
                                except ValueError:
                                    opp_class = None
                            break
                    if opp_class:
                        bayesian_model = BayesianOpponentModel(player_class=opp_class)
                        out(f"│ Opponent class: {opp_class} — {len(bayesian_model.decks)} archetypes")
                    else:
                        bayesian_model = BayesianOpponentModel()
                    _prev_opp_known = set()

                # 收集新对手卡牌 → 贝叶斯更新
                current_opp_known = set()
                if game and len(game.players) >= 2:
                    _opp_idx = 1 - _friendly_idx
                    opp_player = game.players[_opp_idx]
                    card_id_to_dbf = {}
                    for dbf, info in bayesian_model.cards_by_dbf.items():
                        cid = info.get("id", "")
                        if cid:
                            card_id_to_dbf[cid] = dbf
                    try:
                        from analysis.card.data.hsdb import get_db as _get_hsdb
                        _hsdb = _get_hsdb()
                        _hsdb_lookup = _hsdb.card_id_to_dbf
                    except Exception:
                        _hsdb_lookup = None
                    for ent in getattr(opp_player, 'entities', []):
                        cid = getattr(ent, 'card_id', '') or ''
                        if not cid:
                            continue
                        zone = ent.tags.get(GameTag.ZONE, 0) if hasattr(ent, 'tags') else 0
                        if zone in (HZone.PLAY, HZone.SECRET):
                            ctype = ent.tags.get(GameTag.CARDTYPE, 0)
                            if ctype in (HCardType.HERO, HCardType.HERO_POWER):
                                continue
                            dbf_id = card_id_to_dbf.get(cid, 0)
                            if not dbf_id and _hsdb_lookup:
                                dbf_id = _hsdb_lookup(cid) or 0
                            if dbf_id:
                                current_opp_known.add(dbf_id)

                new_cards = current_opp_known - _prev_opp_known
                for dbf in new_cards:
                    bayesian_model.update(dbf)
                    card_name = bayesian_model.card_name(dbf)
                    top = bayesian_model.get_top_decks(1)
                    top_str = f"{top[0][1]}@{top[0][2]:.0%}" if top else "?"
                    out(f"│ 🔍 对手打出: {card_name} → 推断: {top_str}"
                        f"{' [LOCKED]' if bayesian_model.locked else ''}")
                _prev_opp_known = current_opp_known

                # 对手回合：只显示推断，不做 MCTS
                if not is_our_turn:
                    top = bayesian_model.get_top_decks(1)
                    if top:
                        out(f"\n┌─ Turn {current_turn} (对手回合) ────────────")
                        out(f"│ Opp推断: {top[0][1]} ({top[0][2]:.0%})"
                            f"{' [LOCKED]' if bayesian_model.locked else ''}")
                        out(f"└──────────────────────────")
                    last_turn = current_turn
                    continue

                # ── 我们的回合：MCTS 分析 ──
                turn_start_time = time.time()
                remaining_turn_budget = budget_ms / 1000.0

                try:
                    legal = enumerate_legal_actions(state)
                    non_end = [a for a in legal if a.action_type != ActionType.END_TURN]
                except Exception:
                    non_end = []

                out(f"\n┌─ Turn {current_turn} (你的回合) ────────────")
                out(f"│ Hero: {state.hero.hp}HP/{state.hero.armor}A  "
                    f"Mana: {state.mana.available}/{state.mana.max_mana}  "
                    f"Hand: {len(state.hand)}  Board: {len(state.board)}  "
                    f"Legal: {len(non_end)} actions")

                if state.hand:
                    hand_str = " ".join(f"[{_card_display(c)}]" for c in state.hand)
                    out(f"│ Hand: {hand_str}")

                if state.board:
                    board_str = " ".join(f"[{_minion_display(m)}]" for m in state.board)
                    out(f"│ Board: {board_str}")

                if state.opponent.board:
                    opp_str = " ".join(f"[{_minion_display(m)}]" for m in state.opponent.board)
                    out(f"│ Opp Board: {opp_str}")

                # 显示当前推断状态
                if state.opponent.hand_count > 0:
                    top = bayesian_model.get_top_decks(1)
                    if top:
                        out(f"│ Opp推断: {top[0][1]} ({top[0][2]:.0%})"
                            f"{' [LOCKED]' if bayesian_model.locked else ''}"
                            f" | 手牌数={state.opponent.hand_count}"
                            f" | 候选池={len(bayesian_model.predict_hand(state.opponent, state))}")

                if len(non_end) <= 1:
                    if non_end:
                        out(f"│ Quick play → {_action_display(non_end[0], state)}")
                    else:
                        out(f"│ No actions available")
                    out(f"└──────────────────────────")
                    last_turn = current_turn
                    continue

                # Run MCTS with capped budget
                step_budget = min(single_budget_ms, remaining_turn_budget * 1000 * 0.4)
                t0 = time.time()
                try:
                    result = engine.search(
                        state,
                        time_budget_ms=step_budget,
                        bayesian_model=bayesian_model,
                    )
                    elapsed = (time.time() - t0) * 1000
                    s = result.mcts_stats

                    out(f"│")
                    out(f"│ MCTS Plan ({len(result.best_sequence)} steps):")
                    # 逐步应用 action，用正确的状态显示每步
                    plan_state = state
                    for i, a in enumerate(result.best_sequence):
                        marker = ">>>" if i == 0 else "   "
                        out(f"│ {marker} {i+1}. {_action_display(a, plan_state)}")
                        # 应用当前 action 得到下一步的状态（用于显示正确的手牌索引）
                        if a.action_type != ActionType.END_TURN:
                            try:
                                plan_state = _apply_sim_action(plan_state, a)
                            except Exception:
                                break

                    out(f"│")
                    out(f"│ Fitness: {result.fitness:+.4f}")
                    out(f"│ Iters: {s.iterations}  Nodes: {s.nodes_created}  "
                        f"Evals: {s.evaluations_done}  Worlds: {s.world_count}")
                    out(f"│ Time: {s.time_used_ms:.0f}ms  "
                        f"({s.iterations/max(s.time_used_ms,1)*1000:.0f} iter/s)")
                    out(f"└──────────────────────────")

                    total_time += elapsed
                except Exception as e:
                    import traceback
                    out(f"│ Error: {e}")
                    if '--verbose' in sys.argv:
                        out(f"│ {traceback.format_exc()}")
                    out(f"└──────────────────────────")

                decision_count += 1
                last_turn = current_turn

                if max_turns > 0 and decision_count >= max_turns:
                    out(f"\nReached max decisions ({max_turns})")
                    break

    out(f"\n{'='*60}")
    out(f"Analysis complete: {decision_count} decisions, "
        f"{total_time:.0f}ms total, "
        f"avg {total_time/max(decision_count,1):.0f}ms/decision")
    out(f"Log: {log_file_path}")
    out(f"{'='*60}")

    log_f.close()


def main():
    parser = argparse.ArgumentParser(description="MCTS Hearthstone Decision Engine — Power.log Offline Analysis")
    parser.add_argument("log_path", nargs="?", default="Power.log",
                        help="Power.log path (default: Power.log)")
    parser.add_argument("--budget", "-b", type=float, default=25000.0,
                        help="Per-turn total budget ms (default: 25000)")
    parser.add_argument("--single-budget", type=float, default=5000.0,
                        help="Per-step MCTS budget ms (default: 5000)")
    parser.add_argument("--max-turns", type=int, default=0,
                        help="Max decision turns to analyze (0=all)")
    parser.add_argument("--log-file", type=str, default=None,
                        help="Log file path (default: logs/mcts_<ts>.log)")
    parser.add_argument("--log-dir", type=str, default=None,
                        help="Game log directory containing Decks.log and Power.log")
    parser.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(name)s: %(message)s")

    # Resolve Power.log path: --log-dir takes precedence
    log_path = args.log_path
    if args.log_dir:
        log_dir_path = Path(args.log_dir)
        power_log = log_dir_path / "Power.log"
        if power_log.exists():
            log_path = str(power_log)

    run_mcts_analysis(
        log_path=log_path,
        budget_ms=args.budget,
        single_budget_ms=args.single_budget,
        max_turns=args.max_turns,
        log_file_path=args.log_file,
        log_dir=args.log_dir,
    )


if __name__ == "__main__":
    main()

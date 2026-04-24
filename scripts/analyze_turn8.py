#!/usr/bin/env python3
"""analyze_turn8.py — Extract Turn 8 decision states from 5 sampled games and run MCTS + RHEA.

Usage:
    python scripts/analyze_turn8.py

Design:
    - Reuses GameTracker + StateBridge from the existing codebase
    - Feeds ALL lines through a single GameTracker (hslog requires sequential parsing)
    - Tracks game index and captures Turn 8 state for each target game
    - Runs MCTS (cross-turn) and RHEA for comparison
    - Outputs formatted analysis per game
"""

import logging
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple, Dict

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.watcher.deck_provider import DeckProvider
from analysis.search.mcts import MCTSEngine, MCTSConfig
from analysis.search.rhea.engine import RHEAEngine
from analysis.search.rhea.actions import ActionType
from analysis.search.rhea.enumeration import enumerate_legal_actions
from analysis.search.rhea.simulation import apply_action as _apply_sim_action
from hearthstone.enums import GameTag, Zone as HZone, CardType as HCardType

# ── Configuration ──────────────────────────────────────────

LOG_DIR = Path("/Users/ganjie/code/personal/hs_analysis/Hearthstone_2026_04_23_08_43_35")
POWER_LOG = LOG_DIR / "Power.log"
DECKS_LOG = LOG_DIR / "Decks.log"

# Target games in task indexing (CREATE_GAME line pairs): 3, 5, 7, 9, 11
# hslog groups each pair into 1 game → hslog games: 1, 2, 3, 4, 5
# Mapping: hslog_game = (task_game - 1) // 2
TASK_GAMES = [3, 5, 7, 9, 11]
HSLOG_GAMES = [(tg - 1) // 2 for tg in TASK_GAMES]  # [1, 2, 3, 4, 5]
TARGET_TURN = 8

# Search budgets
MCTS_TIME_BUDGET_MS = 5000
RHEA_TIME_BUDGET_MS = 5000  # RHEA uses internal adaptive timing


# ── Display helpers ────────────────────────────────────────

def _card_display(card) -> str:
    name = getattr(card, 'display_name', '') or getattr(card, 'name', '') or '???'
    cost = getattr(card, 'cost', '?')
    return f"{name}({cost})"


def _minion_display(m) -> str:
    name = getattr(m, 'name', '') or getattr(m, 'display_name', '') or '???'
    return f"{name}({m.attack}/{m.health})"


def _action_display(action, state) -> str:
    """Format an action for display, resolving card references."""
    desc = action.describe(state)
    if state.hand:
        for i, card in enumerate(state.hand):
            card_id = getattr(card, 'card_id', '')
            display = _card_display(card)
            if card_id and card_id in desc:
                desc = desc.replace(card_id, display)
            placeholder = f"卡牌#{i}"
            if placeholder in desc:
                desc = desc.replace(placeholder, display)
    return desc


def _detect_friendly_idx(game) -> int:
    """Detect friendly player index based on visible hand cards."""
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
    return _friendly_idx


def _is_our_turn(turn_number: int, friendly_idx: int) -> bool:
    """Check if a given turn number is our turn."""
    return (turn_number % 2 != friendly_idx)


# ── Analysis ───────────────────────────────────────────────

def analyze_turn8_states(
    log_path: Path,
    deck_provider: Optional[DeckProvider],
) -> Tuple[Dict[int, tuple], Dict[int, bool], Dict[int, str]]:
    """Parse the entire Power.log and extract Turn 8 state for target games.

    Returns:
        results: game_idx → (state, friendly_idx)
        opp_turn8_games: game_idx → True for games where T8 is opponent's turn
        deck_names: game_idx → deck_name
    """
    tracker = GameTracker(deck_provider=deck_provider)
    bridge = StateBridge(entity_cache=tracker.entity_cache)

    current_game_idx = -1
    results = {}
    opp_turn8_games = {}  # games where turn 8 exists but is opponent's turn
    deck_names = {}  # game_idx → deck name
    target_set = set(HSLOG_GAMES)
    # Track which games we've already captured turn 8 for
    captured = set()
    # Per-game: whether we've seen the turn_start for target turn
    game_friendly_idx = {}
    game_max_turn = {}  # game_idx → max turn seen

    print(f"Reading {log_path} ...")
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, raw_line in enumerate(f):
            line = raw_line.rstrip('\n')
            event = tracker.feed_line(line)

            if event == 'game_start':
                current_game_idx += 1
                # Update bridge for new game
                if deck_provider and tracker.game_start_timestamp:
                    deck_cards_list = tracker.deck_cards
                    bridge = StateBridge(
                        entity_cache=tracker.entity_cache,
                        deck_cards=deck_cards_list,
                    )
                    current_deck = tracker.current_deck
                    if current_deck:
                        deck_names[current_game_idx] = current_deck.name
                else:
                    bridge = StateBridge(entity_cache=tracker.entity_cache)

            elif event == 'game_end':
                pass  # game over

            elif event == 'turn_start':
                # Only process target games
                if current_game_idx not in target_set:
                    continue
                if current_game_idx in captured:
                    continue

                game = tracker.export_entities()
                if not game:
                    continue

                friendly_idx = _detect_friendly_idx(game)
                game_friendly_idx[current_game_idx] = friendly_idx
                state = bridge.convert(game, player_index=friendly_idx)
                if not state or state.turn_number <= 0:
                    continue

                current_turn = state.turn_number
                is_our_turn = _is_our_turn(current_turn, friendly_idx)

                # Track max turn for this game
                game_max_turn[current_game_idx] = max(
                    game_max_turn.get(current_game_idx, 0), current_turn
                )

                if current_turn == TARGET_TURN:
                    if is_our_turn:
                        results[current_game_idx] = (state, friendly_idx)
                        captured.add(current_game_idx)
                    else:
                        opp_turn8_games[current_game_idx] = True

                # Early exit: only stop after we've passed all target games
                if current_game_idx > max(HSLOG_GAMES):
                    print(f"  All target games processed by line {line_num}")
                    break

    print(f"  Parsed through game index {current_game_idx}")
    print(f"  Captured Turn {TARGET_TURN} for games: {sorted(results.keys())}")
    if captured != target_set:
        missing = target_set - captured
        for g in sorted(missing):
            if g in opp_turn8_games:
                print(f"  Game {g}: Turn {TARGET_TURN} is opponent's turn (not our decision)")
            elif g in game_max_turn:
                print(f"  Game {g}: max turn seen={game_max_turn[g]}, Turn {TARGET_TURN} not found as our turn")
            else:
                print(f"  Game {g}: no turn_start events detected")
    return results, opp_turn8_games, deck_names


def run_analysis(state, hslog_game_idx: int, deck_name: str = "") -> None:
    """Run MCTS + RHEA on a captured Turn 8 state and print results."""
    # Map back to task game number
    task_game = HSLOG_GAMES.index(hslog_game_idx) if hslog_game_idx in HSLOG_GAMES else hslog_game_idx
    task_game_num = TASK_GAMES[task_game] if task_game < len(TASK_GAMES) else hslog_game_idx
    print(f"\n{'═' * 55}")
    title = f"Game {task_game_num} (hslog:{hslog_game_idx}) — Turn {TARGET_TURN} Decision"
    if deck_name:
        title += f" [{deck_name}]"
    print(title)
    print(f"{'═' * 55}")

    # Display board state
    board_str = ", ".join(_minion_display(m) for m in state.board) if state.board else "empty"
    opp_board_str = ", ".join(_minion_display(m) for m in state.opponent.board) if state.opponent.board else "empty"

    opp_hero = state.opponent.hero
    opp_hp_str = f"{opp_hero.hp}hp"
    if opp_hero.armor > 0:
        opp_hp_str += f"/{opp_hero.armor}armor"

    print(f"Board: [{board_str}]")
    print(f"Opp Board: [{opp_board_str}]")
    print(f"Hero: {state.hero.hp}hp/{state.hero.armor}armor vs {opp_hp_str}")
    print(f"Mana: {state.mana.available}/{state.mana.max_mana}")

    if state.hand:
        hand_str = ", ".join(_card_display(c) for c in state.hand)
        print(f"Hand: [{hand_str}]")
    else:
        print(f"Hand: empty")

    # Enumerate legal actions
    try:
        legal = enumerate_legal_actions(state)
        non_end = [a for a in legal if a.action_type != ActionType.END_TURN]
    except Exception as e:
        print(f"  ⚠ Could not enumerate actions: {e}")
        non_end = []

    print(f"Legal actions: {len(non_end)} (+ END_TURN)")

    if len(non_end) <= 1:
        if non_end:
            print(f"\n  Quick play → {_action_display(non_end[0], state)}")
        else:
            print(f"\n  No actions available — END_TURN")
        return

    # ── Run MCTS ────────────────────────────────────────────
    print(f"\n── MCTS (cross-turn 3+2 lookahead, {MCTS_TIME_BUDGET_MS}ms) ──")
    mcts_config = MCTSConfig(
        time_budget_ms=MCTS_TIME_BUDGET_MS,
        num_worlds=5,
        time_decay_gamma=0.4,
        min_step_budget_ms=max(300, MCTS_TIME_BUDGET_MS * 0.1),
        max_actions_per_turn=8,
        max_turns_ahead=3,
        cross_turn_rollout_depth=2,
    )
    mcts_engine = MCTSEngine(mcts_config)

    t0 = time.time()
    mcts_result = None
    try:
        mcts_result = mcts_engine.search(state, time_budget_ms=MCTS_TIME_BUDGET_MS)
        mcts_elapsed = (time.time() - t0) * 1000
        s = mcts_result.mcts_stats

        plan_state = state
        for i, a in enumerate(mcts_result.best_sequence):
            marker = ">>>" if i == 0 else "   "
            step_desc = _action_display(a, plan_state)
            print(f"  {marker} {i+1}. {step_desc}")
            if a.action_type != ActionType.END_TURN:
                try:
                    plan_state = _apply_sim_action(plan_state, a)
                except Exception:
                    break

        print(f"  Fitness: {mcts_result.fitness:+.4f}")
        print(f"  Stats: {s.iterations} iters, {s.nodes_created} nodes, "
              f"{mcts_elapsed:.0f}ms")
    except Exception as e:
        print(f"  ⚠ MCTS error: {e}")

    # ── Run RHEA ────────────────────────────────────────────
    print(f"\n── RHEA (baseline, ~{RHEA_TIME_BUDGET_MS}ms) ──")
    rhea_engine = RHEAEngine(
        pop_size=50,
        tournament_size=5,
        crossover_rate=0.8,
        elite_count=2,
        max_gens=200,
        time_limit=RHEA_TIME_BUDGET_MS / 1000.0,
        max_chromosome_length=6,
        cross_turn=True,
    )

    t0 = time.time()
    rhea_result = None
    try:
        rhea_result = rhea_engine.search(state)
        rhea_elapsed = (time.time() - t0) * 1000

        plan_state = state
        for i, a in enumerate(rhea_result.best_chromosome):
            marker = ">>>" if i == 0 else "   "
            step_desc = _action_display(a, plan_state)
            print(f"  {marker} {i+1}. {step_desc}")
            if a.action_type != ActionType.END_TURN:
                try:
                    plan_state = _apply_sim_action(plan_state, a)
                except Exception:
                    break

        print(f"  Fitness: {rhea_result.best_fitness:+.4f}")
        print(f"  Stats: {rhea_result.generations_run} gens, "
              f"{rhea_elapsed:.0f}ms, "
              f"confidence={rhea_result.confidence:.3f}")
    except Exception as e:
        print(f"  ⚠ RHEA error: {e}")

    # ── Comparison ──────────────────────────────────────────
    print(f"\n── Comparison ──")
    if mcts_result and rhea_result:
        mcts_fit = mcts_result.fitness
        rhea_fit = rhea_result.best_fitness
        if mcts_fit > rhea_fit:
            diff = mcts_fit - rhea_fit
            print(f"  MCTS leads by +{diff:.4f}")
        elif rhea_fit > mcts_fit:
            diff = rhea_fit - mcts_fit
            print(f"  RHEA leads by +{diff:.4f}")
        else:
            print(f"  Identical fitness")

        mcts_first = mcts_result.best_sequence[0] if mcts_result.best_sequence else None
        rhea_first = rhea_result.best_chromosome[0] if rhea_result.best_chromosome else None

        if mcts_first and rhea_first:
            mcts_desc = _action_display(mcts_first, state)
            rhea_desc = _action_display(rhea_first, state)
            if mcts_desc == rhea_desc:
                print(f"  Both agree on first action: {mcts_desc}")
            else:
                print(f"  MCTS first: {mcts_desc}")
                print(f"  RHEA first: {rhea_desc}")
    elif mcts_result:
        print(f"  MCTS only (RHEA failed)")
    elif rhea_result:
        print(f"  RHEA only (MCTS failed)")
    else:
        print(f"  Both engines failed")


def main():
    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

    if not POWER_LOG.exists():
        print(f"Power.log not found: {POWER_LOG}")
        sys.exit(1)

    # Load deck provider
    deck_provider = None
    if DECKS_LOG.exists():
        deck_provider = DeckProvider(str(DECKS_LOG))
        print(f"DeckProvider loaded from: {DECKS_LOG}")
    else:
        print(f"No Decks.log found, running without deck info")

    # Phase 1: Parse Power.log and extract Turn 8 states
    results, opp_turn8_games, deck_names = analyze_turn8_states(POWER_LOG, deck_provider)

    # Phase 2: Run analysis on each captured state
    if not results:
        print(f"\nNo Turn {TARGET_TURN} states captured from target games.")
        return

    for i, hslog_idx in enumerate(HSLOG_GAMES):
        task_num = TASK_GAMES[i]
        if hslog_idx in results:
            state, fidx = results[hslog_idx]
            deck_name = deck_names.get(hslog_idx, "")
            run_analysis(state, hslog_idx, deck_name)
        elif hslog_idx in opp_turn8_games:
            print(f"\n{'═' * 55}")
            print(f"Game {task_num} (hslog:{hslog_idx}) — Turn {TARGET_TURN} is opponent's turn")
            print(f"  (Our turns in this game: odd-numbered turns 1,3,5,7,9...)")
            print(f"{'═' * 55}")
        else:
            print(f"\n{'═' * 55}")
            print(f"Game {task_num} (hslog:{hslog_idx}) — Turn {TARGET_TURN} not available")
            print(f"{'═' * 55}")

    print(f"\n{'═' * 55}")
    print(f"Analysis complete — {len(results)}/{len(HSLOG_GAMES)} games analyzed")
    print(f"{'═' * 55}")


if __name__ == "__main__":
    main()

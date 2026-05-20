#!/usr/bin/env python3
"""
World Tracker — Full Integration with GameTracker + StateBridge.

Reads Power.log through the real tracker pipeline, builds GameState
at each turn boundary, and runs particle-filtered MCTS world tracking.

Two output modes:
  1. Turn-by-turn MCTS analysis (on_turn_start) — shows predicted branches
  2. Event-driven world matching (on_event) — shows how observations match worlds

Usage:
    python scripts/run_world_tracker.py Power.log
    python scripts/run_world_tracker.py Power.log --compact
    python scripts/run_world_tracker.py Power.log --worlds 10 --mcts-iter 200
    python scripts/run_world_tracker.py Power.log --json > output.json
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Suppress noisy third-party output during import
logging.disable(logging.WARNING)
import warnings
warnings.filterwarnings("ignore")
from analysis.engine.mcts_world_tracker import MCTSWorldTracker, TrackerConfig, TurnAnalysis
from analysis.engine.world_branch import ObservedEvent
from analysis.engine.world_tracker_output import WorldTrackerOutput
from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
logging.disable(logging.NOTSET)
logging.basicConfig(level=logging.ERROR, format="%(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MCTS World Tracker — integrated Power.log pipeline",
    )
    parser.add_argument("log_file", type=str, help="Path to Power.log")
    parser.add_argument("--compact", action="store_true",
                        help="Compact one-line output")
    parser.add_argument("--json", action="store_true",
                        help="JSON output mode")
    parser.add_argument("--player-index", type=int, default=0,
                        help="Player index (0=first player, 1=second, default=0)")
    parser.add_argument("--worlds", type=int, default=10,
                        help="Number of worlds (default: 10)")
    parser.add_argument("--mcts-iter", type=int, default=300,
                        help="MCTS iterations per world (default: 300)")
    parser.add_argument("--mcts-time", type=int, default=300,
                        help="MCTS time budget per world in ms (default: 300)")
    parser.add_argument("--mcts-depth", type=int, default=10,
                        help="MCTS rollout depth (default: 10)")
    parser.add_argument("--uct-c", type=float, default=1.414,
                        help="UCT exploration constant (default: 1.414)")
    parser.add_argument("--no-per-world-mcts", action="store_true",
                        help="Only run MCTS on best world (faster)")
    parser.add_argument("--max-turns", type=int, default=0,
                        help="Stop after N turns (0=unlimited)")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose output")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Event Observation — Parse meaningful game events from Power.log lines
# ---------------------------------------------------------------------------

class EventObserver:
    """Detects meaningful game events using GameTracker's entity_cache.

    Watches for:
      - PLAY_CARD: TAG_CHANGE with ZONE→PLAY (a card enters play)
      - ATTACK:    BLOCK_START BlockType=ATTACK
      - DAMAGE:    TAG_CHANGE with tag=DAMAGE
      - DRAW:      ZONE→HAND from DECK
      - DEATH:     ZONE→GRAVEYARD
      - HERO_POWER: BLOCK_START BlockType=POWER on hero power entity
    """

    # TAG_CHANGE with entity info
    _re_tc_zone = re.compile(
        r"TAG_CHANGE\s+Entity=\[.*?id=(\d+).*?\]\s+tag=ZONE\s+value=(\S+)"
    )
    _re_tc_damage = re.compile(
        r"TAG_CHANGE\s+Entity=\[.*?id=(\d+).*?\]\s+tag=DAMAGE\s+value=(\d+)"
    )
    # BLOCK_START lines
    _re_block_attack = re.compile(r"BLOCK_START\s+BlockType=ATTACK")
    _re_block_power = re.compile(
        r"BLOCK_START\s+BlockType=POWER\s+Entity=.*?id=(\d+)"
    )
    # ZONE→HAND detection (for draws)
    _re_tc_zone_hand = re.compile(
        r"TAG_CHANGE\s+Entity=\[.*?id=(\d+).*?\]\s+tag=ZONE\s+value=HAND"
    )

    def __init__(self, entity_cache, card_lookup=None):
        self._cache = entity_cache
        self._card_lookup = card_lookup  # callable(card_id) → Card with .name
        self._event_id = 0

    def next_id(self, turn: int) -> str:
        self._event_id += 1
        return f"evt_t{turn}_{self._event_id}"

    def _resolve_name(self, entity_id: int, card_id: str) -> str:
        """Resolve a human-readable name for an entity."""
        if not card_id:
            return ""
        if self._card_lookup:
            try:
                card = self._card_lookup(card_id)
                if card and getattr(card, 'name', None):
                    return card.name
            except Exception:
                pass
        # Fall back to card_id
        return card_id

    def observe(self, line: str, turn: int) -> Optional[ObservedEvent]:
        """Try to extract a meaningful event from a Power.log line."""
        # ── BLOCK_START BlockType=ATTACK ──
        if self._re_block_attack.search(line):
            return ObservedEvent(
                event_type="ATTACK",
                turn_number=turn,
                event_id=self.next_id(turn),
            )

        # ── ZONE changes ──
        zm = self._re_tc_zone.search(line)
        if zm:
            entity_id = int(zm.group(1))
            new_zone = zm.group(2)
            card_id = self._cache.get_card_id(entity_id) or ""
            name = self._resolve_name(entity_id, card_id)

            if new_zone == "PLAY":
                # Card played
                return ObservedEvent(
                    event_type="PLAY_CARD",
                    card_id=card_id,
                    turn_number=turn,
                    event_id=self.next_id(turn),
                    metadata={
                        "entity_id": entity_id,
                        "name": name,
                        "zone": "PLAY",
                    },
                )
            elif new_zone == "GRAVEYARD":
                # Card died/destroyed
                return ObservedEvent(
                    event_type="DEATH",
                    card_id=card_id,
                    turn_number=turn,
                    event_id=self.next_id(turn),
                    metadata={
                        "entity_id": entity_id,
                        "name": name,
                        "zone": "GRAVEYARD",
                    },
                )

        # ── ZONE→HAND (card draw/return) ──
        hm = self._re_tc_zone_hand.search(line)
        if hm:
            entity_id = int(hm.group(1))
            card_id = self._cache.get_card_id(entity_id) or ""
            name = self._resolve_name(entity_id, card_id)
            return ObservedEvent(
                event_type="DRAW_CARD",
                card_id=card_id,
                turn_number=turn,
                event_id=self.next_id(turn),
                metadata={
                    "entity_id": entity_id,
                    "name": name,
                    "zone": "HAND",
                },
            )

        # ── DAMAGE ──
        dm = self._re_tc_damage.search(line)
        if dm:
            entity_id = int(dm.group(1))
            damage = int(dm.group(2))
            card_id = self._cache.get_card_id(entity_id) or ""
            return ObservedEvent(
                event_type="DAMAGE",
                card_id=card_id,
                turn_number=turn,
                event_id=self.next_id(turn),
                metadata={
                    "entity_id": entity_id,
                    "damage": damage,
                },
            )

        return None


# ---------------------------------------------------------------------------
# Game Tracker — manages per-game state across resets
# ---------------------------------------------------------------------------

class GameSession:
    """Tracks state for one game session."""

    def __init__(self, tracker: MCTSWorldTracker,
                 output: WorldTrackerOutput,
                 observer: EventObserver,
                 game_number: int,
                 player_index: int = 0):
        self.tracker = tracker
        self.output = output
        self.observer = observer
        self.game_number = game_number
        self.player_index = player_index
        self.turn_count = 0
        self.game_state_bridge: Optional[StateBridge] = None
        self._event_log: List[str] = []  # raw event descriptions for debugging

    def on_turn_start(self, game_state_bridge: StateBridge,
                      turn: int) -> Optional[str]:
        """Process a turn start with a ready StateBridge."""
        self.game_state_bridge = game_state_bridge
        self.turn_count += 1

        try:
            # Export hslog entities → Game object
            game = game_state_bridge.entity_cache  # Not how this works!

            # Build GameState from hslog entity tree
            # We need the actual GameTracker here for export_entities
            return None  # handled by main loop
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    log_path = Path(args.log_file)
    if not log_path.exists():
        print(f"Error: file not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    # ── Setup pipeline ──
    tracker_config = TrackerConfig(
        num_worlds=args.worlds,
        mcts_iterations=args.mcts_iter,
        mcts_time_budget_ms=args.mcts_time,
        mcts_rollout_depth=args.mcts_depth,
        uct_exploration=args.uct_c,
        mcts_per_world=not args.no_per_world_mcts,
        verbose=args.verbose,
    )

    game_tracker = GameTracker()
    tracker = MCTSWorldTracker(tracker_config)
    output = WorldTrackerOutput(compact=args.compact or args.json)
    observer = EventObserver(game_tracker.entity_cache)

    # StateBridge — created per game (entity_cache may be reset)
    bridge: Optional[StateBridge] = None

    # ── Stats ──
    lines_processed = 0
    game_count = 0
    total_turn_events = 0
    total_observed_events = 0
    total_mcts_nodes = 0
    total_mcts_time_s = 0.0
    start_wall = time.monotonic()

    print(f"Reading {log_path}...", file=sys.stderr if args.json else sys.stdout)

    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line:
                continue

            lines_processed += 1

            # ── Feed to GameTracker ──
            try:
                event_type = game_tracker.feed_line(line)
            except Exception as exc:
                if args.verbose:
                    print(f"[ParseError] line {lines_processed}: {exc}", file=sys.stderr)
                continue

            # ── Handle event types ──

            if event_type == "game_start":
                game_count += 1
                # Reset tracker and create fresh StateBridge
                tracker.reset()

                # Build entity_cache-backed StateBridge
                try:
                    card_lookup = StateBridge._default_card_lookup()
                except Exception:
                    card_lookup = None

                bridge = StateBridge(
                    entity_cache=game_tracker.entity_cache,
                    card_lookup=card_lookup,
                )

                if args.verbose:
                    print(f"\n{'='*60}", file=sys.stderr)
                    print(f"Game {game_count} START", file=sys.stderr)

            elif event_type == "turn_start":
                turn = game_tracker.get_current_turn()
                total_turn_events += 1

                if args.max_turns > 0 and turn > args.max_turns:
                    continue

                # ── Build state via StateBridge ──
                analysis = None
                game_state = None
                try:
                    # Export hslog entity tree
                    game = game_tracker.export_entities()
                    if game is not None and bridge is not None:
                        game_state = bridge.convert(game, player_index=args.player_index)
                except Exception as exc:
                    if args.verbose:
                        print(f"[StateBridge] Turn {turn}: {exc}", file=sys.stderr)

                # ── Run MCTS World Tracker ──
                if game_state is not None:
                    try:
                        analysis = tracker.on_turn_start(game_state, turn)
                    except Exception as exc:
                        if args.verbose:
                            print(f"[Tracker] Turn {turn}: {exc}", file=sys.stderr)

                # ── Output ──
                if analysis is not None:
                    total_mcts_nodes += analysis.total_mcts_nodes
                    total_mcts_time_s += analysis.mcts_time_s

                    output_text = output.format_turn(analysis)
                    if args.json:
                        print(output_text)
                    else:
                        # Show game number and turn
                        prefix = f"[G{game_count}T{turn}]"
                        for line_out in output_text.split("\n"):
                            if line_out.strip():
                                print(f"{prefix} {line_out}")

                elif args.verbose:
                    print(f"[G{game_count}T{turn}] (no analysis — state unavailable)", file=sys.stderr)

            elif event_type == "action":
                # Try to detect meaningful game events
                if bridge is not None:
                    turn = game_tracker.get_current_turn()
                    try:
                        observed = observer.observe(line, turn)
                        if observed is not None:
                            total_observed_events += 1
                            update = tracker.on_event(observed)
                            if update:
                                total_mcts_nodes += update.total_mcts_nodes
                                if args.verbose:
                                    # Print match quality
                                    mq = update.match_quality
                                    if update.last_match_results:
                                        mq_detail = ", ".join(
                                            f"{observed.event_type}={mr.likelihood:.2f}"
                                            for mr in update.last_match_results[:5]
                                        )
                                    else:
                                        mq_detail = ""
                                    print(
                                        f"[G{game_count}T{turn}] EVENT "
                                        f"{observed.event_type} "
                                        f"{observed.card_id or ''} "
                                        f"| match_quality={mq:.3f}",
                                        file=sys.stderr,
                                    )
                    except Exception as exc:
                        if args.verbose:
                            print(f"[Observer] {exc}", file=sys.stderr)

            elif event_type == "game_end":
                # Finalize
                try:
                    tracker.on_turn_end()
                except Exception:
                    pass

                if args.verbose:
                    print(f"Game {game_count} END", file=sys.stderr)

    # ── Summary ──
    wall_elapsed = time.monotonic() - start_wall
    summary = (
        f"\n{'='*60}\n"
        f"Summary: {game_count} games, {total_turn_events} turns, "
        f"{lines_processed} lines\n"
        f"  Observed events: {total_observed_events}\n"
        f"  Total MCTS nodes explored: {total_mcts_nodes}\n"
        f"  Total MCTS time: {total_mcts_time_s:.2f}s\n"
        f"  Wall clock: {wall_elapsed:.2f}s\n"
    )
    print(summary, file=sys.stderr if args.json else sys.stdout)


if __name__ == "__main__":
    main()

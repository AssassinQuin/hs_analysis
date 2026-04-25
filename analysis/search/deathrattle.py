#!/usr/bin/env python3
"""deathrattle.py — Deathrattle queue for Hearthstone AI.

Handles minion death resolution: collects dead minions, queues deathrattle
effects in board-position order, executes effects, and cascades up to a
configurable limit.

Replaces the inline death-removal in rhea_engine.py with a proper queue.

Usage:
    python3 -m hs_analysis.search.deathrattle          # run self-test
"""

from __future__ import annotations

import re
import logging
from typing import List, Optional, Tuple

from analysis.search.game_state import GameState, Minion
from analysis.search.enchantment import Enchantment

logger = logging.getLogger(__name__)


# ===================================================================
# Deathrattle effect patterns (Chinese card text)
# ===================================================================

_DEATHRATTLE_PATTERNS = [
    (re.compile(r"Deal\s*(\d+)\s*damage\s*to\s*a\s*random\s*enemy", re.IGNORECASE), 'random_damage'),
    (re.compile(r'对随机.*?(?:敌方|敌人).*?造成\s*(\d+)\s*点伤害'), 'random_damage'),
    (re.compile(r"Deal\s*(\d+)\s*damage\s*to\s*all\s*enemies", re.IGNORECASE), 'aoe_damage'),
    (re.compile(r'对所有.*?[敌对]方.*?造成\s*(\d+)\s*点伤害'), 'aoe_damage'),
    (re.compile(r"Summon\s*a?\s*(\d+)/(\d+)", re.IGNORECASE), 'summon'),
    (re.compile(r'召唤.*?(\d+)/(\d+)'), 'summon'),
    (re.compile(r"Draw\s*(\d+)\s*(?:cards?)", re.IGNORECASE), 'draw'),
    (re.compile(r'抽\s*(\d+)\s*张牌'), 'draw'),
    (re.compile(r'\+\s*(\d+)\s*/\s*\+\s*(\d+)'), 'buff'),
    (re.compile(r"Gain\s*(\d+)\s*(?:Armor|armor)", re.IGNORECASE), 'armor'),
    (re.compile(r'获得\s*(\d+)\s*点护甲'), 'armor'),
    (re.compile(r"Restore\s*(\d+)\s*(?:Health|health)", re.IGNORECASE), 'heal'),
    (re.compile(r'恢复\s*(\d+)\s*点'), 'heal'),
]


# ===================================================================
# resolve_deaths — main entry point
# ===================================================================

def resolve_deaths(state: GameState, max_cascade: int = 5) -> GameState:
    """Resolve all dead minions on both boards with deathrattle effects.

    Process:
    1. Collect all minions with health <= 0 from both boards
    2. Queue deathrattle effects in board-position order (left to right)
    3. Execute each deathrattle effect
    4. Re-check for new deaths (cascade), up to max_cascade times
    5. Remove all dead minions from boards

    Args:
        state: Current game state.
        max_cascade: Maximum cascade depth to prevent infinite loops.

    Returns:
        GameState with all deaths resolved.
    """
    s = state

    for cascade in range(max_cascade):
        # Collect dead minions from both boards with their positions
        dead_queue = _collect_dead(s)

        if not dead_queue:
            break  # no more deaths to process

        # Execute deathrattles in board-position order
        for minion, board_type, position in dead_queue:
            s = _execute_deathrattle(s, minion, board_type, position)

        # Remove dead minions from boards
        s.board = [m for m in s.board if m.health > 0]
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        # Cascade: loop will re-check for new deaths

    return s


# ===================================================================
# Internal helpers
# ===================================================================

def _collect_dead(state: GameState) -> List[Tuple[Minion, str, int]]:
    """Collect all dead minions (health <= 0) from both boards.

    Returns list of (minion, board_type, position) tuples.
    board_type: 'friendly' or 'enemy'.
    Sorted by board position (left to right).
    """
    dead = []

    for i, m in enumerate(state.board):
        if m.health <= 0:
            dead.append((m, 'friendly', i))

    for i, m in enumerate(state.opponent.board):
        if m.health <= 0:
            dead.append((m, 'enemy', i))

    # Sort: friendly first (by position), then enemy (by position)
    dead.sort(key=lambda x: (0 if x[1] == 'friendly' else 1, x[2]))
    return dead


def _execute_deathrattle(
    state: GameState,
    minion: Minion,
    board_type: str,
    position: int,
) -> GameState:
    """Execute deathrattle effects for a single dying minion.

    Checks for deathrattle in:
    1. Enchantments with trigger_type="deathrattle"
    2. Card text parsed via parse_deathrattle_text
    """
    s = state

    # Source 1: Enchantment-based deathrattles
    for ench in list(getattr(minion, 'enchantments', [])):
        if ench.trigger_type == "deathrattle" and ench.trigger_effect:
            try:
                s = _apply_deathrattle_effect(s, ench.trigger_effect, board_type, position)
            except Exception as exc:
                logger.warning("Deathrattle enchantment failed: %s — %s", ench.trigger_effect, exc)

    # Source 2: Text-based deathrattles (parse from minion name/text)
    minion_text = getattr(minion, 'text', '') or ''
    if not minion_text:
        card_ref = getattr(minion, 'card_ref', None)
        if card_ref is not None:
            minion_text = getattr(card_ref, 'text', '') or ''
    if minion_text:
        dr_effect = parse_deathrattle_text(minion_text)
        if dr_effect:
            try:
                s = _apply_deathrattle_effect(s, dr_effect, board_type, position)
            except Exception as exc:
                logger.warning("Text deathrattle failed: %s — %s", dr_effect, exc)

    # Source 3: Mechanics tag based (DEATHRATTLE tag but no parsed text)
    if not minion_text:
        mechanics = getattr(minion, 'mechanics', []) or []
        if 'DEATHRATTLE' in mechanics:
            name = getattr(minion, 'name', '')
            logger.debug("Deathrattle minion with no text parsed: %s", name)

    return s


def _apply_deathrattle_effect(
    state: GameState,
    effect: str,
    board_type: str,
    position: int,
) -> GameState:
    """Apply a single deathrattle effect string.

    Delegates to the unified effects dispatcher.  Falls back to the
    old inline logic for effects that could not be parsed.
    """
    from analysis.search.effects import dispatch, parse_effect

    spec = parse_effect(effect)
    if spec is not None:
        return dispatch(state, spec, board_type=board_type, position=position)

    # Fallback: unparseable effect — log and skip
    logger.debug("Unparseable deathrattle effect: %s", effect)
    return state


def parse_deathrattle_text(text: str) -> Optional[str]:
    """Parse deathrattle text from card description to effect string.

    Used when a card has "亡语：..." in its text but no enchantment.
    Returns effect string or None if not parseable.
    """
    if not text:
        return None

    # Extract deathrattle portion
    dr_match = re.search(r"Deathrattle[：:]\s*(.+?)(?:[,.]|$)", text, re.IGNORECASE)
    if not dr_match:
        dr_match = re.search(r'亡语[：:]\s*(.+?)(?:，|$)', text)
    if not dr_match:
        return None

    dr_text = dr_match.group(1).strip()

    for pattern, effect_type in _DEATHRATTLE_PATTERNS:
        match = pattern.search(dr_text)
        if match:
            if effect_type == 'random_damage':
                return f"damage:random_enemy:{match.group(1)}"
            elif effect_type == 'aoe_damage':
                return f"damage:all_enemy:{match.group(1)}"
            elif effect_type == 'summon':
                return f"summon:{match.group(1)}:{match.group(2)}"
            elif effect_type == 'draw':
                return f"draw:{match.group(1)}"
            elif effect_type == 'buff':
                return f"buff:friendly:{match.group(1)}:{match.group(2)}"
            elif effect_type == 'armor':
                return f"armor:{match.group(1)}"
            elif effect_type == 'heal':
                return f"heal:hero:{match.group(1)}"

    return None


# ===================================================================
# Self-test
# ===================================================================

if __name__ == "__main__":
    from analysis.search.game_state import GameState, Minion, HeroState, OpponentState
    from analysis.search.enchantment import Enchantment, apply_enchantment

    # Test 1: Deathrattle summon
    state = GameState()
    dying = Minion(name="Haunted Creeper", attack=1, health=0, max_health=2)
    ench = Enchantment(
        enchantment_id="haunt",
        trigger_type="deathrattle",
        trigger_effect="summon:1:1",
    )
    apply_enchantment(dying, ench)
    state.board.append(dying)

    state = resolve_deaths(state)
    assert len(state.board) == 1  # summoned token replaces dead minion
    assert state.board[0].attack == 1
    print(f"Test 1 PASS: {len(state.board)} token(s) on board")

    # Test 2: Deathrattle draw
    state2 = GameState()
    state2.deck_remaining = 5
    dying2 = Minion(name="Loot Hoarder", attack=2, health=0, max_health=2)
    ench2 = Enchantment(
        enchantment_id="loot",
        trigger_type="deathrattle",
        trigger_effect="draw:1",
    )
    apply_enchantment(dying2, ench2)
    state2.board.append(dying2)

    state2 = resolve_deaths(state2)
    assert state2.deck_remaining == 4
    print("Test 2 PASS: drew 1 card from deathrattle")

    # Test 3: Cascade (deathrattle kills another minion)
    state3 = GameState()
    state3.opponent.hero.hp = 30
    # Enemy minion with 1 health
    enemy = Minion(name="Fragile", attack=1, health=1, max_health=1, owner="enemy")
    state3.opponent.board.append(enemy)
    # Friendly dying minion deals 1 random damage
    dying3 = Minion(name="Boom", attack=1, health=0, max_health=1)
    ench3 = Enchantment(
        enchantment_id="boom",
        trigger_type="deathrattle",
        trigger_effect="damage:random_enemy:1",
    )
    apply_enchantment(dying3, ench3)
    state3.board.append(dying3)

    state3 = resolve_deaths(state3)
    assert len(state3.opponent.board) == 0  # enemy died from deathrattle
    print("Test 3 PASS: cascade death resolved")

    print("All self-tests passed!")

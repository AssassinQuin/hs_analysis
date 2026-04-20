"""dormant.py — Dormant (休眠) mechanic for Hearthstone AI.

Minions with Dormant enter play unable to attack for N turns.
After N turns, they awaken and gain full capabilities.
"""

from __future__ import annotations

import re
from hs_analysis.search.game_state import GameState, Minion


def parse_dormant_turns(text: str) -> int:
    if not text:
        return 0
    m = re.search(r'休眠\s*(\d+)\s*个?回合', text)
    if m:
        return int(m.group(1))
    m = re.search(r'Dormant\s*(?:for\s*)?(\d+)', text)
    if m:
        return int(m.group(1))
    if '休眠' in text or 'DORMANT' in text.upper():
        return 2
    return 0


def is_dormant_card(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    return 'DORMANT' in mechanics or '休眠' in text


def apply_dormant(minion: Minion, card) -> Minion:
    text = getattr(card, 'text', '') or ''
    turns = parse_dormant_turns(text)
    if turns > 0:
        minion.is_dormant = True
        minion.dormant_turns_remaining = turns
        minion.can_attack = False
    return minion


def tick_dormant(state: GameState) -> GameState:
    for m in state.board:
        if m.is_dormant and m.dormant_turns_remaining > 0:
            m.dormant_turns_remaining -= 1
            if m.dormant_turns_remaining <= 0:
                m.is_dormant = False
                m.can_attack = False  # wakes with summoning sickness unless charge
    return state

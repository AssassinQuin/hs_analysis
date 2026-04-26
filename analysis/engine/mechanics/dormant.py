# [从 analysis/search/dormant.py 迁移而来]
# 原文件仍保留，后续 Phase 统一 import 路径后删除原文件。
from __future__ import annotations

"""dormant.py — Dormant (休眠) mechanic for Hearthstone AI.

Minions with Dormant enter play unable to attack for N turns.
After N turns, they awaken and gain full capabilities.
"""

import re
from analysis.engine.state import GameState, Minion


def parse_dormant_turns(text: str, english_text: str = '') -> int:
    # Try English text first (more reliable), then Chinese fallback
    if english_text:
        m = re.search(r'Dormant\s*(?:for\s*)?(\d+)', english_text)
        if m:
            return int(m.group(1))
    if text:
        m = re.search(r'休眠\s*(\d+)\s*个?回合', text)
        if m:
            return int(m.group(1))
    if 'Dormant' in english_text or '休眠' in text:
        return 2
    return 0


def is_dormant_card(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    english_text = getattr(card, 'english_text', '') or ''
    return 'DORMANT' in mechanics or 'Dormant' in english_text or '休眠' in text


def apply_dormant(minion: Minion, card) -> Minion:
    text = getattr(card, 'text', '') or ''
    english_text = getattr(card, 'english_text', '') or ''
    turns = parse_dormant_turns(text, english_text)
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

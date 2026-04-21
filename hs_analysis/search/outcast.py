"""outcast.py — Outcast hand position mechanic.

V10 Phase 3: Implements the Outcast mechanic where cards at the
leftmost or rightmost position in hand gain bonus effects.
"""

from __future__ import annotations

import re
from hs_analysis.search.game_state import GameState


# ===================================================================
# check_outcast
# ===================================================================

def check_outcast(state: GameState, card_index: int, card) -> bool:
    """Return True if the card has OUTCAST mechanic AND is at position 0 or len(hand)-1.

    A single card in hand is at both leftmost and rightmost, so it triggers.
    """
    hand = getattr(state, 'hand', []) or []
    if not hand:
        return False

    # Check if card has OUTCAST mechanic
    mechanics = getattr(card, 'mechanics', None) or []
    text = getattr(card, 'text', '') or ''

    has_outcast = 'OUTCAST' in mechanics or '流放' in text
    if not has_outcast:
        return False

    # Card must be at leftmost (0) or rightmost (len-1)
    if card_index == 0 or card_index == len(hand) - 1:
        return True

    return False


# ===================================================================
# apply_outcast_bonus
# ===================================================================

def apply_outcast_bonus(state: GameState, card_index: int, card) -> GameState:
    """Apply the outcast bonus effect based on card text.

    Parses Chinese text patterns to determine bonus type.
    Returns modified state.
    """
    bonus = _parse_outcast_bonus(getattr(card, 'text', '') or '')
    bonus_type = bonus.get('type', 'draw')

    if bonus_type == 'draw':
        count = bonus.get('count', 1)
        for _ in range(count):
            if state.deck_remaining > 0:
                state.deck_remaining -= 1
            else:
                state.fatigue_damage += 1
                state.hero.hp -= state.fatigue_damage

    elif bonus_type == 'cost':
        target_cost = bonus.get('value', 0)
        original_cost = getattr(card, 'cost', 0)
        refund = max(0, original_cost - target_cost)
        state.mana.available += refund

    elif bonus_type == 'buff':
        atk = bonus.get('attack', 0)
        hp = bonus.get('health', 0)
        # Buff the last played minion (most recently added to board)
        if state.board:
            last_minion = state.board[-1]
            last_minion.attack += atk
            last_minion.health += hp
            last_minion.max_health += hp

    return state


# ===================================================================
# _parse_outcast_bonus
# ===================================================================

def _parse_outcast_bonus(text: str) -> dict:
    """Parse Chinese outcast bonus text and return bonus descriptor.

    Patterns:
        '流放：再抽N张'     → {"type": "draw", "count": N}
        '流放：+N/+N'       → {"type": "buff", "attack": N, "health": N}
        '流放：法力值消耗为（N）点' → {"type": "cost", "value": N}
        Fallback if '流放' present: {"type": "draw", "count": 1}
    """
    m = re.search(r'Outcast[：:]\s*Draw\s*(\d+)', text)
    if m:
        return {"type": "draw", "count": int(m.group(1))}

    m = re.search(r'流放[：:]\s*再抽(\d+)张', text)
    if m:
        return {"type": "draw", "count": int(m.group(1))}

    m = re.search(r'Outcast[：:]\s*\+(\d+)/\+(\d+)', text)
    if m:
        return {"type": "buff", "attack": int(m.group(1)), "health": int(m.group(2))}

    m = re.search(r'流放[：:]\s*\+(\d+)/\+(\d+)', text)
    if m:
        return {"type": "buff", "attack": int(m.group(1)), "health": int(m.group(2))}

    m = re.search(r'Outcast[：:]\s*(?:costs?|Cost)\s*\(?(\d+)\)?', text)
    if m:
        return {"type": "cost", "value": int(m.group(1))}

    m = re.search(r'流放[：:]\s*法力值消耗为[（(]\s*(\d+)\s*[）)]点', text)
    if m:
        return {"type": "cost", "value": int(m.group(1))}

    if 'Outcast' in text or '流放' in text:
        return {"type": "draw", "count": 1}

    return {"type": "draw", "count": 1}

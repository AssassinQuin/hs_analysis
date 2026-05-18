"""corrupt.py — Corrupt (腐蚀) mechanic for Hearthstone AI.

Cards with Corrupt in hand upgrade when the player plays a card with
higher cost. The upgraded card replaces the original in hand.
"""

from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.models.card import Card


def has_corrupt(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    return 'CORRUPT' in mechanics or '腐蚀' in text


def check_corrupt_upgrade(state: GameState, played_card) -> GameState:
    played_cost = getattr(played_card, 'cost', 0)
    for i, card in enumerate(state.hand):
        if not has_corrupt(card):
            continue
        card_cost = getattr(card, 'cost', 0)
        if played_cost > card_cost:
            state.hand[i] = _upgrade_card(card)
    return state


def _upgrade_card(card: Card) -> Card:
    old_cost = getattr(card, 'cost', 0)
    new_cost = old_cost + 1
    old_name = getattr(card, 'name', '')
    new_name = old_name.replace('腐蚀', '腐蚀（升级）') if '腐蚀' not in old_name else old_name

    return Card(
        dbf_id=getattr(card, 'dbf_id', 0),
        name=new_name,
        cost=new_cost,
        original_cost=new_cost,
        card_type=getattr(card, 'card_type', ''),
        attack=getattr(card, 'attack', 0) + 1,
        health=getattr(card, 'health', 0) + 1,
        text=getattr(card, 'text', ''),
        rarity=getattr(card, 'rarity', ''),
        card_class=getattr(card, 'card_class', ''),
        race=getattr(card, 'race', ''),
        mechanics=[m for m in (getattr(card, 'mechanics', []) or []) if m != 'CORRUPT'],
    )

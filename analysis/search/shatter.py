"""shatter.py — Shatter (裂变) mechanic for Hearthstone AI.

2026 Standard mechanic: when a card with Shatter is drawn, it splits into
two copies with halved stats/effects. The player gets both copies in hand.
"""

from __future__ import annotations

from analysis.search.game_state import GameState
from analysis.models.card import Card


def is_shatter_card(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    return 'SHATTER' in mechanics or '裂变' in text


def apply_shatter_on_draw(state: GameState, card_index: int) -> GameState:
    if card_index < 0 or card_index >= len(state.hand):
        return state

    original = state.hand[card_index]

    half_cost = max(1, getattr(original, 'cost', 1) // 2)
    half_attack = getattr(original, 'attack', 0) // 2
    half_health = getattr(original, 'health', 0) // 2

    state.hand.pop(card_index)

    copy1 = Card(
        dbf_id=getattr(original, 'dbf_id', 0),
        name=f"{getattr(original, 'name', '')} (裂变1)",
        cost=half_cost,
        original_cost=half_cost,
        card_type=getattr(original, 'card_type', ''),
        attack=half_attack,
        health=half_health,
        text=getattr(original, 'text', ''),
        rarity=getattr(original, 'rarity', ''),
        card_class=getattr(original, 'card_class', ''),
        race=getattr(original, 'race', ''),
        mechanics=[m for m in (getattr(original, 'mechanics', []) or []) if m != 'SHATTER'],
    )

    copy2 = Card(
        dbf_id=getattr(original, 'dbf_id', 0) + 1,
        name=f"{getattr(original, 'name', '')} (裂变2)",
        cost=half_cost,
        original_cost=half_cost,
        card_type=getattr(original, 'card_type', ''),
        attack=half_attack,
        health=half_health,
        text=getattr(original, 'text', ''),
        rarity=getattr(original, 'rarity', ''),
        card_class=getattr(original, 'card_class', ''),
        race=getattr(original, 'race', ''),
        mechanics=[m for m in (getattr(original, 'mechanics', []) or []) if m != 'SHATTER'],
    )

    state.hand.append(copy1)
    if len(state.hand) < 10:
        state.hand.append(copy2)

    return state


def check_shatter_on_draw(state: GameState, drawn_card_index: int) -> GameState:
    if drawn_card_index < 0 or drawn_card_index >= len(state.hand):
        return state
    card = state.hand[drawn_card_index]
    if is_shatter_card(card):
        return apply_shatter_on_draw(state, drawn_card_index)
    return state

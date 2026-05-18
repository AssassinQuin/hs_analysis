"""modify.py — Buff, debuff, transform, destroy, silence primitives."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def apply_buff(state: GameState, target_id: str | int,
               attack: int = 0, health: int = 0, **kwargs: Any) -> None:
    """Buff a minion: +atk/+hp."""
    minion = _resolve_minion(state, target_id)
    if minion is None:
        return
    minion.attack += attack
    minion.health += health
    minion.max_health = max(minion.max_health, minion.health)


def apply_hand_buff(state: GameState, attack: int = 0, health: int = 0,
                    **kwargs: Any) -> None:
    """Buff minions in hand."""
    for card in state.hand:
        if card.is_minion:
            card.attack += attack
            card.health += health


def apply_destroy(state: GameState, target_id: str | int,
                  **kwargs: Any) -> None:
    """Destroy a minion."""
    minion = _resolve_minion(state, target_id)
    if minion is None:
        return
    minion.health = 0  # mark for death


def apply_silence(state: GameState, target_id: str | int,
                  **kwargs: Any) -> None:
    """Silence a minion (remove all keyword tags)."""
    minion = _resolve_minion(state, target_id)
    if minion is None:
        return
    minion.tags.clear()


def apply_transform(state: GameState, target_id: str | int,
                    **kwargs: Any) -> None:
    """Transform a minion (e.g. Hex: into 0/1 Frog).

    Currently sets stats to 0/1 and clears tags.
    """
    minion = _resolve_minion(state, target_id)
    if minion is None:
        return
    minion.attack = 0
    minion.health = 1
    minion.max_health = 1
    minion.tags.clear()


# ── Helpers ──────────────────────────────────────────────────

_KEYWORD_MAPPING: dict[str, str] = {
    'TAUNT': 'has_taunt',
    'DIVINE_SHIELD': 'has_divine_shield',
    'RUSH': 'has_rush',
    'CHARGE': 'has_charge',
    'WINDFURY': 'has_windfury',
    'STEALTH': 'has_stealth',
    'LIFESTEAL': 'has_lifesteal',
    'POISONOUS': 'has_poisonous',
    'REBORN': 'has_reborn',
    'IMMUNE': 'has_immune',
    'WARD': 'has_ward',
    'MEGA_WINDFURY': 'has_mega_windfury',
    'MAGNETIC': 'has_magnetic',
}


def apply_keyword(minion, keyword: str) -> None:
    """Apply a keyword string to a minion's boolean flags."""
    if not keyword:
        return
    kw = keyword.upper().strip()
    field = _KEYWORD_MAPPING.get(kw)
    if field and hasattr(minion, field):
        setattr(minion, field, True)


def apply_silence_to_minion(minion) -> None:
    """Strip all keywords and enchantments from a minion."""
    bool_fields = [
        'has_divine_shield', 'has_taunt', 'has_stealth', 'has_windfury',
        'has_rush', 'has_charge', 'has_poisonous', 'has_lifesteal',
        'has_reborn', 'has_immune', 'cant_attack', 'has_magnetic',
        'has_invoke', 'has_corrupt', 'has_spellburst', 'is_outcast',
        'frozen_until_next_turn', 'has_ward', 'has_mega_windfury',
    ]
    for f in bool_fields:
        if hasattr(minion, f):
            setattr(minion, f, False)
    minion.enchantments = []
    minion.abilities = []


def _resolve_minion(state: GameState,
                    target_id: str | int) -> object | None:
    """Resolve a target_id to a Minion object.

    Accepts "friendly:N", "enemy:N", or plain int.
    """
    if isinstance(target_id, str):
        if target_id.startswith("friendly:"):
            idx = int(target_id.split(":", 1)[1])
            if 0 <= idx < len(state.board):
                return state.board[idx]
        elif target_id.startswith("enemy:"):
            idx = int(target_id.split(":", 1)[1])
            if 0 <= idx < len(state.opponent.board):
                return state.opponent.board[idx]
        else:
            log.warning("_resolve_minion: unknown target_id %r", target_id)
        return None
    # Plain int index → friendly board
    if 0 <= target_id < len(state.board):
        return state.board[target_id]
    return None

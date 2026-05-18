"""damage.py — Damage, heal, armor primitives."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def apply_damage(state: GameState, target_id: str | int,
                 amount: int, **kwargs: Any) -> None:
    """Deal *amount* damage to a target entity.

    target_id formats: "hero", "enemy_hero", "friendly:N", "enemy:N"
    Respects armor, divine shield, and immune.
    """
    if isinstance(target_id, str):
        if target_id == "hero" or target_id == "enemy_hero":
            hero = state.hero if target_id == "hero" else state.opponent.hero
            apply_damage_to_hero(hero, amount)
        elif target_id.startswith("friendly:"):
            idx = int(target_id.split(":", 1)[1])
            _damage_minion(state, idx, amount, is_friendly=True)
        elif target_id.startswith("enemy:"):
            idx = int(target_id.split(":", 1)[1])
            _damage_minion(state, idx, amount, is_friendly=False)
        else:
            log.warning("apply_damage: unknown target_id %r", target_id)
    else:
        # Plain int → friendly board
        _damage_minion(state, target_id, amount, is_friendly=True)


def apply_aoe_damage(state: GameState, amount: int,
                     target_kind: str = "enemy", **kwargs: Any) -> None:
    """Deal damage to all entities matching target_kind."""
    kind = target_kind.replace("_", " ").lower().strip()

    if "enemy" in kind and "minion" not in kind:
        for i, _ in enumerate(state.opponent.board):
            _damage_minion(state, i, amount, is_friendly=False)
    elif kind == "all_minions" or kind == "all minions":
        for i, _ in enumerate(state.board):
            _damage_minion(state, i, amount, is_friendly=True)
        for i, _ in enumerate(state.opponent.board):
            _damage_minion(state, i, amount, is_friendly=False)
    elif kind == "all_characters" or kind == "all characters":
        state.hero.hp -= amount
        for i, _ in enumerate(state.board):
            _damage_minion(state, i, amount, is_friendly=True)
        for i, _ in enumerate(state.opponent.board):
            _damage_minion(state, i, amount, is_friendly=False)


def apply_heal(state: GameState, target_id: str | int,
               amount: int, **kwargs: Any) -> None:
    """Restore *amount* health to a target entity."""
    if isinstance(target_id, str):
        if target_id == "hero":
            state.hero.hp = min(state.hero.hp + amount, state.hero.max_hp or 30)
        elif target_id.startswith("friendly:"):
            idx = int(target_id.split(":", 1)[1])
            if 0 <= idx < len(state.board):
                m = state.board[idx]
                m.health = min(m.health + amount, m.max_health)
        elif target_id.startswith("enemy:"):
            idx = int(target_id.split(":", 1)[1])
            if 0 <= idx < len(state.opponent.board):
                m = state.opponent.board[idx]
                m.health = min(m.health + amount, m.max_health)


def apply_armor(state: GameState, amount: int, **kwargs: Any) -> None:
    """Gain *amount* armor."""
    state.hero.armor = state.hero.armor + amount


def apply_damage_to_hero(hero, amount: int) -> None:
    """Deal damage to a hero, respecting armor and immune."""
    if getattr(hero, 'is_immune', False):
        return
    absorbed = min(hero.armor, amount)
    hero.armor -= absorbed
    hero.hp -= (amount - absorbed)


def apply_damage_to_minion(minion, amount: int) -> None:
    """Deal damage to a minion, respecting divine shield and immune."""
    if getattr(minion, 'has_immune', False):
        return
    if getattr(minion, 'has_divine_shield', False):
        minion.has_divine_shield = False
        return
    minion.health -= amount


# ── Internal ──────────────────────────────────────────────────

def _damage_minion(state: GameState, idx: int, amount: int,
                   is_friendly: bool) -> None:
    board = state.board if is_friendly else state.opponent.board
    if idx < 0 or idx >= len(board):
        log.warning("_damage_minion: idx %d out of range (len=%d)", idx, len(board))
        return
    minion = board[idx]
    # Divine Shield absorbs the damage
    if minion.has_divine_shield:
        minion.has_divine_shield = False
        return
    minion.health -= amount

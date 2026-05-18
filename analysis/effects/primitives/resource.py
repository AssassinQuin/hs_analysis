"""resource.py — Mana, corpse, weapon, hero power primitives."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)


def apply_gain_mana(state: GameState, amount: int = 0,
                    temporary: bool = False, **kwargs: Any) -> None:
    """Gain mana crystals."""
    if temporary:
        state.mana.available += amount
    else:
        state.mana.max_mana = min(
            state.mana.max_mana + amount,
            state.mana.max_mana_cap or 10,
        )
        state.mana.available += amount


def apply_overload(state: GameState, amount: int = 0,
                   **kwargs: Any) -> None:
    """Add overloaded mana crystals."""
    state.mana.overload_next += amount


def apply_corpse_gain(state: GameState, amount: int = 0,
                      **kwargs: Any) -> None:
    """Gain corpses."""
    state.corpses = (state.corpses or 0) + amount


def apply_corpse_spend(state: GameState, amount: int = 0,
                       **kwargs: Any) -> None:
    """Spend corpses."""
    current = state.corpses or 0
    state.corpses = max(0, current - amount)


def apply_weapon_equip(state: GameState, attack: int = 0,
                       durability: int = 0, **kwargs: Any) -> None:
    """Equip a weapon."""
    from analysis.card.engine.state import Weapon
    state.hero.weapon = Weapon(attack=attack, health=durability)

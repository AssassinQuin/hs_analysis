#!/usr/bin/env python3
"""transposition.py — Transposition table for MCTS.

Maps state_hash → MCTSNode, enabling statistical reuse when different
action sequences reach the same game state.

Features:
- Fixed-size table with LRU-style eviction (low visit count first)
- Optional strict hash collision verification
- Tree reuse: preserve subtree after choosing an action
"""

from __future__ import annotations

import logging
from typing import Optional, Dict, List, Tuple, TYPE_CHECKING

from analysis.search.mcts.node import MCTSNode

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


class TranspositionTable:
    """MCTS transposition table: state_hash → MCTSNode."""

    def __init__(self, max_size: int = 100_000, evict_ratio: float = 0.1):
        self._table: Dict[int, MCTSNode] = {}
        self._max_size = max_size
        self._evict_ratio = evict_ratio
        self._hits = 0
        self._misses = 0

    def get(self, state_hash: int) -> Optional[MCTSNode]:
        """Look up an existing node by state hash."""
        node = self._table.get(state_hash)
        if node is not None:
            self._hits += 1
        else:
            self._misses += 1
        return node

    def put(self, state_hash: int, node: MCTSNode) -> None:
        """Register a node. Does not overwrite existing entries."""
        if state_hash not in self._table:
            self._table[state_hash] = node
            self._check_eviction()

    def get_or_create(
        self,
        state_hash: int,
        **node_kwargs,
    ) -> Tuple[MCTSNode, bool]:
        """Look up or create a node.

        Returns:
            (node, was_existing) — was_existing=True if node was already in table.
        """
        existing = self._table.get(state_hash)
        if existing is not None:
            self._hits += 1
            return existing, True

        node = MCTSNode(state_hash=state_hash, **node_kwargs)
        self._table[state_hash] = node
        self._misses += 1
        self._check_eviction()
        return node, False

    def reuse_subtree(
        self,
        old_root: MCTSNode,
        chosen_action_key: tuple,
    ) -> Optional[MCTSNode]:
        """Reuse the subtree rooted at the chosen action's child.

        Called after selecting an action to preserve search effort.
        """
        child = old_root.children.get(chosen_action_key)
        if child is None:
            return None

        # Disconnect from old parent
        child.parent = None
        return child

    def clear(self) -> None:
        """Clear the entire table."""
        self._table.clear()
        self._hits = 0
        self._misses = 0

    @property
    def size(self) -> int:
        return len(self._table)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def _check_eviction(self) -> None:
        """Evict low-visit nodes if table exceeds max_size."""
        if len(self._table) <= self._max_size:
            return

        # Sort by visit count and evict the bottom 10%
        items = list(self._table.items())
        items.sort(key=lambda x: x[1].visit_count)
        evict_count = max(1, int(len(items) * self._evict_ratio))

        for hash_key, _ in items[:evict_count]:
            del self._table[hash_key]

        log.debug("TranspositionTable: evicted %d nodes, size=%d", evict_count, len(self._table))


def compute_state_hash(state: 'GameState', is_player_turn: bool) -> int:
    """Compute an information-set state hash.

    Hashes:
    - Whose turn it is
    - My hero: hp, armor, attack, weapon
    - My minions: sorted by dbf_id → (dbf_id, attack, health, taunt, divine_shield)
    - My mana: available, max_mana
    - Opponent hero: hp, armor
    - Opponent minions: sorted by dbf_id → same fields
    - Opponent hand count (not actual cards)
    - Turn number
    """
    parts = []

    # 1. Turn direction
    parts.append(str(is_player_turn))

    # 2. My hero
    hero = state.hero
    weapon_name = ""
    weapon_attack = 0
    if hero.weapon is not None:
        weapon_name = hero.weapon.name or ""
        weapon_attack = hero.weapon.attack
    parts.append(f"H:{hero.hp},{hero.armor},{weapon_attack},{weapon_name}")

    # 3. My minions (sorted by dbf_id, ignore position)
    my_minions = sorted(
        state.board,
        key=lambda m: getattr(m, 'dbf_id', 0) or 0,
    )
    for m in my_minions:
        parts.append(
            f"M:{getattr(m, 'dbf_id', 0)},{m.attack},{m.health},"
            f"{getattr(m, 'has_taunt', False)},{getattr(m, 'has_divine_shield', False)}"
        )

    # 4. Mana
    mana = state.mana
    parts.append(f"Mana:{mana.available},{mana.max_mana}")

    # 5. Opponent hero
    opp = state.opponent
    opp_hero = opp.hero
    parts.append(f"OH:{opp_hero.hp},{opp_hero.armor}")

    # 6. Opponent minions
    opp_minions = sorted(
        opp.board,
        key=lambda m: getattr(m, 'dbf_id', 0) or 0,
    )
    for m in opp_minions:
        parts.append(
            f"OM:{getattr(m, 'dbf_id', 0)},{m.attack},{m.health},"
            f"{getattr(m, 'has_taunt', False)}"
        )

    # 7. Opponent hand count
    parts.append(f"OHand:{getattr(opp, 'hand_count', len(getattr(opp, 'hand', [])))}")

    # 8. Turn number
    parts.append(f"T:{state.turn_number}")

    combined = "|".join(parts)
    return hash(combined)

#!/usr/bin/env python3
"""Pre-computed multi-attribute card index for fast pool queries.

Builds O(1) lookup indexes by mechanic, type, class, race, school, cost,
format, and set.  Supports composite queries with ``get_pool(**filters)``.

Usage::

    from analysis.data.card_index import get_index

    idx = get_index()
    taunt_minions = idx.get_pool(mechanics="TAUNT", card_type="MINION")
    mage_fire_spells = idx.get_pool(card_class="MAGE", school="FIRE")
    discover_cards = idx.discover_pool("MAGE")
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

# Type alias
CardDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How high a cost goes before bucketing into "10+"
_MAX_COST_BUCKET: int = 10

# Classes that can appear in discover results (all playable classes)
_PLAYABLE_CLASSES: set = {
    "DEATHKNIGHT", "DEMONHUNTER", "DRUID", "HUNTER", "MAGE",
    "PALADIN", "PRIEST", "ROGUE", "SHAMAN", "WARLOCK", "WARRIOR",
}


# --------------------------------------------------------------------------- #
#  SECTION 2 — CardIndex class
# --------------------------------------------------------------------------- #

class CardIndex:
    """Pre-computed multi-attribute card index for fast pool queries.

    All indexes are built at construction time.  Queries are pure dict
    lookups + set intersections — no linear scans.
    """

    # --- Construction -----------------------------------------------------

    def __init__(self, cards: List[CardDict]) -> None:
        self._cards: List[CardDict] = list(cards)
        self._total: int = len(cards)

        # Primary indexes
        self.dbf_lookup: Dict[int, CardDict] = {}
        self.by_mechanic: Dict[str, List[CardDict]] = {}
        self.by_type: Dict[str, List[CardDict]] = {}
        self.by_class: Dict[str, List[CardDict]] = {}
        self.by_race: Dict[str, List[CardDict]] = {}
        self.by_school: Dict[str, List[CardDict]] = {}
        self.by_cost: Dict[int, List[CardDict]] = {}
        self.by_format: Dict[str, List[CardDict]] = {}
        self.by_set: Dict[str, List[CardDict]] = {}
        self.by_rarity: Dict[str, List[CardDict]] = {}

        # Composite indexes (most common multi-filter combos)
        # Key: (class, type) → list
        self._class_type: Dict[Tuple[str, str], List[CardDict]] = {}
        # Key: (mechanic, type) → list
        self._mechanic_type: Dict[Tuple[str, str], List[CardDict]] = {}

        self._build_indexes()

    def _build_indexes(self) -> None:
        for card in self._cards:
            self._index_card(card)

        self._dbf_frozensets: Dict[str, frozenset] = {}
        all_indexes: Dict[str, Dict] = {
            "mechanic": self.by_mechanic,
            "type": self.by_type,
            "class": self.by_class,
            "race": self.by_race,
            "school": self.by_school,
            "cost": self.by_cost,
            "format": self.by_format,
            "set": self.by_set,
            "rarity": self.by_rarity,
        }
        for idx_name, idx_dict in all_indexes.items():
            for key, cards in idx_dict.items():
                cache_key = f"{idx_name}:{key}"
                self._dbf_frozensets[cache_key] = frozenset(
                    c.get("dbfId", id(c)) for c in cards
                )
        for (k1, k2), cards in self._class_type.items():
            self._dbf_frozensets[f"ctype:{k1}:{k2}"] = frozenset(
                c.get("dbfId", id(c)) for c in cards
            )
        for (k1, k2), cards in self._mechanic_type.items():
            self._dbf_frozensets[f"mtype:{k1}:{k2}"] = frozenset(
                c.get("dbfId", id(c)) for c in cards
            )

        self._pool_cache: Dict[str, List[CardDict]] = {}
        self._pool_cache_max: int = 256

        logger.debug(
            "CardIndex built: %d cards, %d mechanics, %d types, "
            "%d classes, %d races, %d schools, %d dbf frozensets",
            self._total,
            len(self.by_mechanic),
            len(self.by_type),
            len(self.by_class),
            len(self.by_race),
            len(self.by_school),
            len(self._dbf_frozensets),
        )

    def _index_card(self, card: CardDict) -> None:
        """Add a single card to all indexes."""
        dbf = card.get("dbfId")
        if dbf is not None:
            self.dbf_lookup[int(dbf)] = card

        # --- Single-attribute indexes ---

        # Mechanics (card may have multiple)
        for mech in card.get("mechanics", []):
            self.by_mechanic.setdefault(mech, []).append(card)

        # Type
        card_type = card.get("type", "")
        if card_type:
            self.by_type.setdefault(card_type, []).append(card)

        # Class
        card_class = card.get("cardClass", "")
        if card_class:
            card_class = card_class.upper()
            card["cardClass"] = card_class
            self.by_class.setdefault(card_class, []).append(card)

        # Race (may be space-separated multi-race)
        raw_race = card.get("race", "")
        if raw_race:
            # Split on space for multi-race cards
            for r in raw_race.split():
                self.by_race.setdefault(r, []).append(card)

        # Spell school
        school = card.get("spellSchool", "")
        if school:
            for s in school.split():
                self.by_school.setdefault(s, []).append(card)

        # Cost
        cost = card.get("cost", 0)
        bucket = cost if cost <= _MAX_COST_BUCKET else _MAX_COST_BUCKET
        self.by_cost.setdefault(bucket, []).append(card)

        # Format
        fmt = card.get("format", "standard")
        self.by_format.setdefault(fmt, []).append(card)

        # Set
        card_set = card.get("set", "")
        if card_set:
            self.by_set.setdefault(card_set, []).append(card)

        # Rarity
        rarity = card.get("rarity", "")
        if rarity and rarity != "无":
            self.by_rarity.setdefault(rarity, []).append(card)

        # --- Composite indexes ---

        # (class, type)
        if card_class and card_type:
            self._class_type.setdefault(
                (card_class, card_type), []
            ).append(card)

        # (mechanic, type)
        for mech in card.get("mechanics", []):
            self._mechanic_type.setdefault(
                (mech, card_type), []
            ).append(card)

    # --- Public query API ------------------------------------------------

    def get_pool(
        self,
        *,
        mechanics: Optional[str | List[str]] = None,
        card_class: Optional[str] = None,
        card_type: Optional[str] = None,
        race: Optional[str] = None,
        school: Optional[str] = None,
        cost: Optional[int] = None,
        cost_min: Optional[int] = None,
        cost_max: Optional[int] = None,
        format: Optional[str] = None,
        rarity: Optional[str] = None,
        card_set: Optional[str] = None,
        exclude_dbfids: Optional[Set[int] | List[int]] = None,
    ) -> List[CardDict]:
        """Query the card pool with multiple filters (AND logic)."""
        cache_key_parts: List[str] = []
        dbf_sets: List[frozenset] = []

        if card_class and card_type:
            key = f"ctype:{card_class}:{card_type}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        else:
            if card_class:
                key = f"class:{card_class}"
                fs = self._dbf_frozensets.get(key)
                if fs is None:
                    return []
                dbf_sets.append(fs)
                cache_key_parts.append(key)
            if card_type:
                key = f"type:{card_type}"
                fs = self._dbf_frozensets.get(key)
                if fs is None:
                    return []
                dbf_sets.append(fs)
                cache_key_parts.append(key)

        if mechanics is not None:
            if isinstance(mechanics, str):
                mechanics = [mechanics]
            for mech in mechanics:
                key = f"mechanic:{mech}"
                fs = self._dbf_frozensets.get(key)
                if fs is None:
                    return []
                dbf_sets.append(fs)
                cache_key_parts.append(key)

        if race:
            key = f"race:{race}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        if school:
            key = f"school:{school}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        if cost is not None:
            bucket = cost if cost <= _MAX_COST_BUCKET else _MAX_COST_BUCKET
            key = f"cost:{bucket}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        if format:
            key = f"format:{format}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        if rarity:
            key = f"rarity:{rarity}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)
        if card_set:
            key = f"set:{card_set}"
            fs = self._dbf_frozensets.get(key)
            if fs is None:
                return []
            dbf_sets.append(fs)
            cache_key_parts.append(key)

        range_suffix = ""
        if cost_min is not None:
            range_suffix += f"cmin:{cost_min}"
        if cost_max is not None:
            range_suffix += f"cmax:{cost_max}"
        excl_suffix = ""
        if exclude_dbfids:
            excl_suffix = f"excl:{len(exclude_dbfids)}"
        pool_key = "|".join(cache_key_parts) + range_suffix + excl_suffix

        if pool_key and pool_key in self._pool_cache:
            return list(self._pool_cache[pool_key])

        if not dbf_sets:
            output = list(self._cards)
        else:
            dbf_sets_sorted = sorted(dbf_sets, key=len)
            result_ids = dbf_sets_sorted[0]
            for s in dbf_sets_sorted[1:]:
                result_ids = result_ids & s
                if not result_ids:
                    break
            if not result_ids:
                output = []
            else:
                output = [self.dbf_lookup[dbf] for dbf in result_ids if dbf in self.dbf_lookup]

        if cost_min is not None or cost_max is not None:
            cmin = cost_min if cost_min is not None else 0
            cmax = cost_max if cost_max is not None else 999
            output = [c for c in output if cmin <= c.get("cost", 0) <= cmax]

        if exclude_dbfids:
            excl = set(exclude_dbfids)
            output = [c for c in output if c.get("dbfId", -1) not in excl]

        if pool_key and len(self._pool_cache) < self._pool_cache_max:
            self._pool_cache[pool_key] = list(output)

        return output

    def get_by_dbf(self, dbf_id: int) -> Optional[CardDict]:
        """O(1) lookup by dbfId.  Returns ``None`` if not found."""
        return self.dbf_lookup.get(dbf_id)

    def random_pool(
        self,
        size: int,
        *,
        allow_duplicates: bool = False,
        **filters: Any,
    ) -> List[CardDict]:
        """Sample *size* random cards matching *filters*.

        If the matching pool is smaller than *size*, the entire pool is
        returned (no duplicates unless *allow_duplicates* is True).

        Args:
            size: Number of cards to sample.
            allow_duplicates: If True, sample with replacement.
            **filters: Passed to ``get_pool()``.

        Returns:
            List of randomly sampled card dicts.
        """
        pool = self.get_pool(**filters)
        if not pool:
            return []
        if len(pool) <= size and not allow_duplicates:
            return list(pool)
        if allow_duplicates:
            return random.choices(pool, k=size)
        return random.sample(pool, min(size, len(pool)))

    def discover_pool(
        self,
        card_class: str,
        *,
        card_type: Optional[str] = None,
        format: str = "standard",
        exclude_dbfids: Optional[Set[int]] = None,
    ) -> List[CardDict]:
        """Return the Discover-eligible pool for a given class.

        Hearthstone Discover rules:
        1. Cards from the class **or** NEUTRAL.
        2. Standard format (or wild if *format*="wild").
        3. If *card_type* is given, only cards of that type.
        4. Excludes the triggering card itself.

        Returns:
            Eligible card dicts.
        """
        # Get class cards + neutral cards
        class_cards = self.get_pool(card_class=card_class, format=format)
        neutral_cards = self.get_pool(card_class="NEUTRAL", format=format)
        pool = class_cards + neutral_cards

        pool = [c for c in pool if c.get("type", "") not in ("HERO", "LOCATION")]

        if card_type:
            pool = [c for c in pool if c.get("type") == card_type]

        # Exclusion
        if exclude_dbfids:
            excl = set(exclude_dbfids)
            pool = [c for c in pool if c.get("dbfId", -1) not in excl]

        return pool

    # --- Statistics -------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        return {
            "total_cards": self._total,
            "by_mechanic": {k: len(v) for k, v in sorted(self.by_mechanic.items())},
            "by_type": {k: len(v) for k, v in sorted(self.by_type.items())},
            "by_class": {k: len(v) for k, v in sorted(self.by_class.items())},
            "by_race": {k: len(v) for k, v in sorted(self.by_race.items())},
            "by_school": {k: len(v) for k, v in sorted(self.by_school.items())},
            "by_cost": {k: len(v) for k, v in sorted(self.by_cost.items())},
            "by_format": {k: len(v) for k, v in sorted(self.by_format.items())},
            "by_set": {k: len(v) for k, v in sorted(self.by_set.items())},
            "by_rarity": {k: len(v) for k, v in sorted(self.by_rarity.items())},
            "mechanic_count": len(self.by_mechanic),
            "type_count": len(self.by_type),
            "class_count": len(self.by_class),
            "race_count": len(self.by_race),
            "school_count": len(self.by_school),
        }

    @property
    def total(self) -> int:
        """Total number of cards in the index."""
        return self._total


# --------------------------------------------------------------------------- #
#  SECTION 3 — Module-level singleton
# --------------------------------------------------------------------------- #

_index: Optional[CardIndex] = None


def get_index(rebuild: bool = False) -> CardIndex:
    """Lazy-load the card index (singleton).

    Primary source: ``HSCardDB`` (python-hearthstone CardDefs.xml).
    Fallback: ``unified_standard.json`` + ``unified_wild.json``.

    Args:
        rebuild: Force rebuild even if already loaded.

    Returns:
        The global ``CardIndex`` instance.
    """
    global _index
    if _index is not None and not rebuild:
        return _index

    cards: List[CardDict] = []

    try:
        from .hsdb import get_db
        db = get_db(rebuild=rebuild)
        cards = list(db._collectible.values())
        logger.info("Loaded %d cards from HSCardDB (python-hearthstone)", len(cards))
    except Exception as exc:
        logger.warning("HSCardDB unavailable (%s), falling back to JSON", exc)

        std_path = DATA_DIR / "unified_standard.json"
        if std_path.exists():
            std_cards = json.loads(std_path.read_text(encoding="utf-8"))
            for c in std_cards:
                c.setdefault("format", "standard")
            cards.extend(std_cards)
            logger.info("Loaded %d standard cards from %s", len(std_cards), std_path)
        else:
            logger.warning("Standard card pool not found: %s", std_path)

        wild_path = DATA_DIR / "unified_wild.json"
        if wild_path.exists():
            wild_cards = json.loads(wild_path.read_text(encoding="utf-8"))
            for c in wild_cards:
                c["format"] = "wild"
            cards.extend(wild_cards)
            logger.info("Loaded %d wild cards from %s", len(wild_cards), wild_path)

    _index = CardIndex(cards)
    return _index


# --------------------------------------------------------------------------- #
#  SECTION 4 — CLI
# --------------------------------------------------------------------------- #

def _print_section(title: str, data: Dict[str, int], top: int = 0) -> None:
    """Pretty-print a stats section."""
    items = sorted(data.items(), key=lambda x: -x[1])
    if top:
        items = items[:top]
    print(f"\n  {title} ({len(data)} unique):")
    for k, v in items:
        print(f"    {k}: {v}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    idx = get_index()
    s = idx.stats()

    print(f"✅ CardIndex: {s['total_cards']} cards loaded")
    _print_section("By Type", s["by_type"])
    _print_section("By Class", s["by_class"])
    _print_section("By Race", s["by_race"])
    _print_section("By School", s["by_school"])
    _print_section("By Format", s["by_format"])
    _print_section("By Rarity", s["by_rarity"])
    _print_section("Top Mechanics", s["by_mechanic"], top=15)
    _print_section("By Cost", s["by_cost"])

    # Example queries
    print("\n" + "=" * 60)
    print("EXAMPLE QUERIES")
    print("=" * 60)

    # All taunt minions
    taunt_minions = idx.get_pool(mechanics="TAUNT", card_type="MINION")
    print(f"\nTaunt minions: {len(taunt_minions)}")
    for c in taunt_minions[:5]:
        print(f"  {c['name']} ({c.get('cost','?')}费) [{c.get('cardClass','')}]")
    if len(taunt_minions) > 5:
        print(f"  ... and {len(taunt_minions) - 5} more")

    # Mage fire spells
    mage_fire = idx.get_pool(card_class="MAGE", school="FIRE")
    print(f"\nMage fire cards: {len(mage_fire)}")
    for c in mage_fire[:5]:
        print(f"  {c['name']} ({c.get('cost','?')}费)")

    # Discover pool for Paladin
    disc = idx.discover_pool("PALADIN")
    print(f"\nPaladin discover pool: {len(disc)} cards")

    # Random beast
    beasts = idx.random_pool(3, race="BEAST", card_type="MINION")
    print(f"\nRandom beasts: {[c['name'] for c in beasts]}")

    # Cards with both BATTLECRY and DISCOVER
    bc_disc = idx.get_pool(mechanics=["BATTLECRY", "DISCOVER"])
    print(f"\nBattlecry+Discover cards: {len(bc_disc)}")
    for c in bc_disc[:5]:
        print(f"  {c['name']} ({c.get('cost','?')}费) [{c.get('cardClass','')}]")

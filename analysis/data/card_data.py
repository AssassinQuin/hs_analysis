# -*- coding: utf-8 -*-
"""CardDB — 统一炉石卡牌数据库，集成自动更新与多维度搜索。

合并了原 hsdb.py (HSCardDB)、card_index.py (CardIndex)、card_updater.py、
build_unified_db.py、build_wild_db.py 五个模块的功能。

数据源: HearthstoneJSON API (api.hearthstonejson.com)
  - ``zhCN/cards.collectible.json`` 中文卡牌
  - ``enUS/cards.collectible.json`` 英文卡牌
  - ``cards.json`` 完整卡牌（含衍生物）

辅助数据源: python-hearthstone CardDefs.xml (可选)

用法::

    from analysis.data.card_data import get_db, search

    db = get_db()
    card = db.get_card("EX1_001")              # 按 card_id 查询原始字典
    card = db.get_by_dbf(1655)                  # 按 dbfId 查询

    # 多维度搜索
    results = search(name="火球", card_type="SPELL")
    results = search(mechanics="TAUNT", cost=(2, 5))
    results = search(card_class="MAGE", format="standard")

    # 快速池查询（用于模拟）
    pool = db.get_pool(card_class="ROGUE", card_type="MINION")
    discover = db.discover_pool("MAGE")
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import time
import urllib.error
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Pattern, Set, Tuple

from analysis.config import DATA_BUILD, DATA_DIR, PROJECT_ROOT
from analysis.utils import load_json
from analysis.utils.http import http_get_json

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

_API_BASE = "https://api.hearthstonejson.com/v1"
_UA = "hs_analysis/1.0"
_MAX_COST_BUCKET: int = 10
_MAX_AGE_DAYS = 7  # staleness threshold for auto-update

STANDARD_SETS: set = {
    "CATACLYSM",
    "TIME_TRAVEL",
    "THE_LOST_CITY",
    "EMERALD_DREAM",
    "CORE",
    "EVENT",
}

_SET_NAMES: Dict[str, str] = {
    "CATACLYSM": "大灾变",
    "TIME_TRAVEL": "时光之穴",
    "THE_LOST_CITY": "迷失之城",
    "EMERALD_DREAM": "翡翠梦境",
    "CORE": "核心系列",
    "EVENT": "活动",
}

_EXCLUDED_DISCOVER_TYPES: set = {
    "HERO",
    "HERO_POWER",
    "ENCHANTMENT",
    "LOCATION",
}

_DEFAULT_HERO_DBF_CLASS_MAP: Dict[int, str] = {
    7: "WARRIOR",
    31: "HUNTER",
    274: "DRUID",
    637: "MAGE",
    671: "PALADIN",
    813: "PRIEST",
    893: "WARLOCK",
    930: "ROGUE",
    1066: "SHAMAN",
    56550: "DEMONHUNTER",
    78065: "DEATHKNIGHT",
}

_CARD_FILES = (
    "cards.collectible.json",
    "cards.json",
)

_CACHE_DIR = Path(os.environ.get("HSJSON_CACHE_DIR", str(PROJECT_ROOT / "card_data")))

_METADATA_FILE = "update_metadata.json"


# ──────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Strip HTML tags, $-variables, [x] markers from card text."""
    if not text:
        return ""
    cleaned = re.sub(r"</?[^>]+>", "", text)
    cleaned = re.sub(r"[$#](\d+)", r"\1", cleaned)
    cleaned = re.sub(r"\[x\]", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", "", cleaned).strip()
    return cleaned


def _fetch_json(url: str, timeout: int = 60) -> List[dict]:
    """Fetch JSON from URL via shared HTTP utility."""
    return http_get_json(url, timeout=timeout, user_agent=_UA)


def _cache_path(build: str, locale: str, name: str) -> Path:
    """Construct cache file path, creating parent dirs."""
    p = _CACHE_DIR / build / locale / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cached(path: Path) -> Optional[List[dict]]:
    """Load JSON from cache file, return None on failure."""
    if not path.exists():
        return None
    try:
        return load_json(path)
    except (OSError, ValueError):
        return None


def _save_cache(path: Path, data: list) -> None:
    """Write JSON to cache file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("Cache write failed: %s", exc)


def _merge_locale(zh_data: List[dict], en_data: List[dict]) -> Dict[str, dict]:
    """Merge zhCN + enUS card data into unified dicts keyed by card_id."""
    merged: Dict[str, dict] = {}
    en_by_id: Dict[str, dict] = {c["id"]: c for c in en_data}
    for card in zh_data:
        cid = card["id"]
        en = en_by_id.get(cid, {})
        merged[cid] = {
            "dbfId": card.get("dbfId", 0),
            "cardId": cid,
            "name": card.get("name", ""),
            "englishName": en.get("name", ""),
            "cost": card.get("cost", 0),
            "attack": card.get("attack", 0),
            "health": card.get("health", 0),
            "durability": card.get("durability", 0),
            "armor": card.get("armor", 0),
            "type": card.get("type", ""),
            "cardClass": card.get(
                "cardClass",
                card.get("classes", ["NEUTRAL"])[0]
                if card.get("classes")
                else "NEUTRAL",
            ),
            "race": card.get("race", ""),
            "races": card.get("races", []),
            "rarity": card.get("rarity", ""),
            "spellSchool": card.get("spellSchool", ""),
            "mechanics": card.get("mechanics", []),
            "referencedTags": card.get("referencedTags", []),
            "text": card.get("text", ""),
            "englishText": en.get("text", ""),
            "set": card.get("set", ""),
            "collectible": card.get("collectible", False),
            "elite": card.get("elite", False),
            "classes": card.get("classes", []),
            "overload": card.get("overload", 0),
            "spellDamage": card.get("spellDamage", 0),
            "quest": "QUEST" in card.get("mechanics", []),
            "format": "",
        }
    return merged


def _build_card_dict(zh_card: dict, en_card: dict) -> dict:
    """Build unified card dict from zh+en HSJSON source (for DB building)."""
    text_raw = zh_card.get("text", "") or ""
    return {
        "dbfId": zh_card.get("dbfId", 0),
        "cardId": zh_card.get("id", ""),
        "name": zh_card.get("name", ""),
        "ename": en_card.get("name", ""),
        "cost": zh_card.get("cost", 0),
        "attack": zh_card.get("attack", 0),
        "health": zh_card.get("health", 0),
        "durability": zh_card.get("durability", 0),
        "armor": zh_card.get("armor", 0),
        "type": zh_card.get("type", ""),
        "cardClass": zh_card.get("cardClass", "NEUTRAL"),
        "race": zh_card.get("race", ""),
        "races": zh_card.get("races", []),
        "rarity": zh_card.get("rarity", ""),
        "text": _clean_text(text_raw),
        "textRaw": text_raw,
        "spellSchool": zh_card.get("spellSchool", ""),
        "mechanics": zh_card.get("mechanics", []),
        "referencedTags": zh_card.get("referencedTags", []),
        "overload": zh_card.get("overload", 0),
        "spellDamage": zh_card.get("spellDamage", 0),
        "set": zh_card.get("set", ""),
        "setName": _SET_NAMES.get(zh_card.get("set", ""), ""),
    }


def _card_id_fingerprint(cards: List[dict]) -> str:
    """SHA-256 fingerprint of sorted card IDs."""
    ids = sorted(c.get("id", "") for c in cards)
    blob = "\n".join(ids).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _metadata_path(build: str) -> Path:
    """Return path to update_metadata.json for build."""
    return PROJECT_ROOT / "card_data" / build / _METADATA_FILE


def _read_update_metadata(build: str) -> Dict[str, Any]:
    """Read update_metadata.json for a given build."""
    path = _metadata_path(build)
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except (OSError, ValueError):
        return {}


def _write_update_metadata(build: str, metadata: Dict[str, Any]) -> None:
    """Write update_metadata.json for a given build."""
    path = _metadata_path(build)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ──────────────────────────────────────────────
# UpdateStatus
# ──────────────────────────────────────────────

@dataclass
class UpdateStatus:
    """Result of an auto-update check or operation."""
    updated: bool = False
    version: str | None = None
    card_count: int = 0
    elapsed_seconds: float = 0.0
    error: str | None = None


# ──────────────────────────────────────────────
# CardDB — the single entry point
# ──────────────────────────────────────────────

class CardDB:
    """统一卡牌数据库，支持自动更新、快速池查询和多维度搜索。

    内部使用双层索引:
      - 列表索引 (by_class, by_type 等): 向后兼容，可迭代
      - frozenset 索引 (_dbf_frozensets): get_pool() 交集查询

    自动更新策略:
      - 初始化时检查本地数据新鲜度 (mtime)
      - 如果超过 max_age_hours 且网络可用，同步拉取最新数据
      - 失败时降级使用本地数据，不中断服务
    """

    def __init__(
        self,
        build: str | List[Dict[str, Any]] = DATA_BUILD,
        *,
        auto_update: bool = True,
        max_age_hours: float = 168.0,  # 7 days
        load_xml: bool = True,
        data_dir: Path | None = None,
    ) -> None:
        # Backward compat: CardIndex(cards_list) → test-mode indexing
        self._card_list_mode = isinstance(build, list)
        if self._card_list_mode:
            self._build = DATA_BUILD
        else:
            self._build = build
        self._load_xml_enabled = load_xml
        self._data_dir = data_dir or (PROJECT_ROOT / "card_data" / self._build)
        self._max_age_hours = max_age_hours

        # Core data stores
        self._cards: Dict[str, Dict[str, Any]] = {}       # card_id → raw dict
        self._dbf_index: Dict[int, str] = {}               # dbfId → card_id
        self._collectible: Dict[str, Dict[str, Any]] = {}  # card_id → dict (collectible only)
        self._standard: Dict[str, Dict[str, Any]] = {}     # card_id → dict (standard only)
        self._xml_db = None

        # List-based indexes (backward compat with CardIndex)
        self.dbf_lookup: Dict[int, Dict[str, Any]] = {}
        self.by_mechanic: Dict[str, List[Dict[str, Any]]] = {}
        self.by_type: Dict[str, List[Dict[str, Any]]] = {}
        self.by_class: Dict[str, List[Dict[str, Any]]] = {}
        self.by_race: Dict[str, List[Dict[str, Any]]] = {}
        self.by_school: Dict[str, List[Dict[str, Any]]] = {}
        self.by_cost: Dict[int, List[Dict[str, Any]]] = {}
        self.by_format: Dict[str, List[Dict[str, Any]]] = {}
        self.by_set: Dict[str, List[Dict[str, Any]]] = {}
        self.by_rarity: Dict[str, List[Dict[str, Any]]] = {}

        # Frozenset indexes for fast get_pool() intersection
        self._dbf_frozensets: Dict[str, frozenset] = {}
        self._pool_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._pool_cache_max: int = 256

        # Composite indexes
        self._class_type: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._mechanic_type: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

        self._indexes_built = False

        # Load data
        if self._card_list_mode:
            self._load_from_card_list(build)  # type: ignore[arg-type]
        else:
            self._load_local_data()
            if auto_update and self._is_stale(max_age_hours):
                self._try_auto_update()

    def _load_from_card_list(self, cards: List[Dict[str, Any]]) -> None:
        """Load cards from a list (test-mode, backward compat with CardIndex)."""
        for card in cards:
            dbf = card.get("dbfId", 0)
            cid = card.get("cardId", card.get("id", str(dbf)))
            card.setdefault("cardId", cid)
            self._cards[cid] = card
            if dbf:
                self._dbf_index[dbf] = cid
            # All cards in list mode are treated as collectible
            self._collectible[cid] = card
        self._build_indexes()

    # ── Loading ────────────────────────────────

    def _load_local_data(self) -> None:
        """Load HSJSON data from local cache, build indexes. Never raises."""
        try:
            self._load_hsjson()
        except Exception as exc:
            logger.warning("HSJSON load failed: %s", exc)

        if self._load_xml_enabled:
            try:
                self._load_xml_fallback()
            except Exception as exc:
                logger.warning("XML fallback failed: %s", exc)

        self._build_indexes()

    def _load_hsjson(self) -> None:
        """Load HSJSON zhCN + enUS collectible + full cards."""
        build = self._build

        # 1) Collectible cards (primary data source)
        zh_coll = _cache_path(build, "zhCN", "cards.collectible.json")
        en_coll = _cache_path(build, "enUS", "cards.collectible.json")

        zh_data = _load_cached(zh_coll)
        if zh_data is None:
            url = f"{_API_BASE}/{build}/zhCN/cards.collectible.json"
            logger.info("Fetching zhCN cards from %s", url)
            zh_data = _fetch_json(url)
            _save_cache(zh_coll, zh_data)
        logger.info("zhCN: %d collectible cards", len(zh_data))

        en_data = _load_cached(en_coll)
        if en_data is None:
            url = f"{_API_BASE}/{build}/enUS/cards.collectible.json"
            logger.info("Fetching enUS cards from %s", url)
            en_data = _fetch_json(url)
            _save_cache(en_coll, en_data)
        logger.info("enUS: %d collectible cards", len(en_data))

        merged = _merge_locale(zh_data, en_data)
        self._cards.update(merged)
        for cid, d in merged.items():
            self._dbf_index[d["dbfId"]] = cid
            if d["collectible"]:
                self._collectible[cid] = d

        # 2) Full card database (tokens, enchantments, hero powers)
        zh_full = _cache_path(build, "zhCN", "cards.json")
        en_full = _cache_path(build, "enUS", "cards.json")

        zh_full_data = _load_cached(zh_full)
        if zh_full_data is None:
            url = f"{_API_BASE}/{build}/zhCN/cards.json"
            logger.info("Fetching zhCN full cards from %s", url)
            zh_full_data = _fetch_json(url)
            _save_cache(zh_full, zh_full_data)

        en_full_data = _load_cached(en_full)
        if en_full_data is None:
            url = f"{_API_BASE}/{build}/enUS/cards.json"
            logger.info("Fetching enUS full cards from %s", url)
            en_full_data = _fetch_json(url)
            _save_cache(en_full, en_full_data)

        if zh_full_data:
            en_full_map = {c["id"]: c for c in (en_full_data or [])}
            added = 0
            for card in zh_full_data:
                cid = card["id"]
                if cid not in self._cards:
                    en = en_full_map.get(cid, {})
                    d = {
                        "dbfId": card.get("dbfId", 0),
                        "cardId": cid,
                        "name": card.get("name", ""),
                        "englishName": en.get("name", ""),
                        "cost": card.get("cost", 0),
                        "attack": card.get("attack", 0),
                        "health": card.get("health", 0),
                        "durability": card.get("durability", 0),
                        "armor": card.get("armor", 0),
                        "type": card.get("type", ""),
                        "cardClass": card.get("cardClass", "NEUTRAL"),
                        "race": card.get("race", ""),
                        "rarity": card.get("rarity", ""),
                        "mechanics": card.get("mechanics", []),
                        "text": card.get("text", ""),
                        "set": card.get("set", ""),
                        "collectible": False,
                    }
                    self._cards[cid] = d
                    if d["dbfId"]:
                        self._dbf_index[d["dbfId"]] = cid
                    added += 1
            logger.info(
                "Full DB: added %d non-collectible cards (total %d)",
                added, len(self._cards),
            )

    def _load_xml_fallback(self) -> None:
        """Load non-collectible cards from python-hearthstone XML."""
        try:
            import importlib.util
            if importlib.util.find_spec("hearthstone_data") is None:
                logger.info("hearthstone_data not installed, skipping XML fallback")
                return
        except (ImportError, ModuleNotFoundError):
            pass

        try:
            import signal
            from hearthstone.cardxml import load as _load_xml
            from hearthstone.enums import Locale

            old_handler = signal.signal(signal.SIGALRM, lambda *_: None)
            signal.alarm(10)
            try:
                self._xml_db, _ = _load_xml(locale=Locale.enUS)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            count = 0
            for cid, card_xml in self._xml_db.items():
                if cid in self._cards:
                    continue
                d = self._xml_to_dict(card_xml)
                self._cards[cid] = d
                self._dbf_index[d["dbfId"]] = cid
                count += 1
            logger.info("XML fallback: %d non-collectible cards loaded", count)
        except Exception as exc:
            logger.warning("python-hearthstone XML fallback unavailable: %s", exc)

    @staticmethod
    def _xml_to_dict(card) -> Dict[str, Any]:
        """Convert python-hearthstone CardXML to standard dict."""
        from hearthstone.enums import GameTag

        card_class = card.card_class.name if card.card_class else "NEUTRAL"
        card_type = card.type.name if card.type else ""
        rarity = card.rarity.name if card.rarity else ""
        races = " ".join(r.name for r in (card.races or []) if r) if card.races else ""
        if not races and card.race:
            races = card.race.name

        _BOOLS = {
            "taunt": "TAUNT", "charge": "CHARGE", "divine_shield": "DIVINE_SHIELD",
            "battlecry": "BATTLECRY", "deathrattle": "DEATHRATTLE",
            "windfury": "WINDFURY", "lifesteal": "LIFESTEAL", "poisonous": "POISONOUS",
            "rush": "RUSH", "reborn": "REBORN", "discover": "DISCOVER",
            "secret": "SECRET", "quest": "QUEST", "outcast": "OUTCAST",
            "corrupt": "CORRUPT", "echo": "ECHO", "twinspell": "TWINSPELL",
            "tradeable": "TRADEABLE", "colossal": "COLOSSAL", "titan": "TITAN",
            "forge": "FORGE", "overheal": "OVERHEAL", "combo": "COMBO",
        }
        mechanics = sorted(
            name for prop, name in _BOOLS.items() if getattr(card, prop, False)
        )

        zh_name = ""
        cardname_strings = (
            card.strings.get(GameTag.CARDNAME) if hasattr(card, "strings") else None
        )
        if isinstance(cardname_strings, dict):
            zh_name = cardname_strings.get("zhCN", "")

        zh_text = ""
        cardtext_strings = (
            card.strings.get(GameTag.CARDTEXT) if hasattr(card, "strings") else None
        )
        if isinstance(cardtext_strings, dict):
            zh_text = cardtext_strings.get("zhCN", "")

        return {
            "dbfId": card.dbf_id or 0,
            "cardId": card.id,
            "name": zh_name or card.english_name or "",
            "englishName": card.english_name or "",
            "cost": card.cost or 0,
            "attack": card.atk or 0,
            "health": card.health or 0,
            "durability": card.durability or 0,
            "armor": card.armor or 0,
            "type": card_type,
            "cardClass": card_class,
            "race": races,
            "rarity": rarity,
            "mechanics": mechanics,
            "text": zh_text or card.english_description or "",
            "englishText": card.english_description or "",
            "set": card.card_set.name if card.card_set else "",
            "collectible": bool(card.collectible),
            "format": "",
        }

    # ── Indexing ───────────────────────────────

    def _build_indexes(self) -> None:
        """Build list indexes + frozenset indexes + pool cache."""
        if self._indexes_built:
            return

        for cid, d in self._collectible.items():
            # Only auto-assign format if not already set
            if not d.get("format"):
                card_set = d.get("set", "")
                if card_set in STANDARD_SETS:
                    d["format"] = "standard"
                else:
                    d["format"] = "wild"

            if d.get("format") == "standard":
                self._standard[cid] = d
            self._index_card(d)

        # Build frozenset indexes from list indexes
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

        self._pool_cache = {}

        logger.info(
            "CardDB indexed: %d total, %d collectible, %d standard, %d frozensets",
            len(self._cards), len(self._collectible),
            len(self._standard), len(self._dbf_frozensets),
        )
        self._indexes_built = True

    def _index_card(self, d: Dict) -> None:
        """Index a single card into all index buckets."""
        dbf = d.get("dbfId")
        if dbf is not None:
            self.dbf_lookup[int(dbf)] = d

        # Mechanics
        for mech in d.get("mechanics", []):
            self.by_mechanic.setdefault(mech, []).append(d)

        # Type
        card_type = d.get("type", "")
        if card_type:
            self.by_type.setdefault(card_type, []).append(d)

        # Class (uppercase)
        card_class = d.get("cardClass", "")
        if card_class:
            card_class = card_class.upper()
            d["cardClass"] = card_class
            self.by_class.setdefault(card_class, []).append(d)

        # Race (space-separated multi-race)
        raw_race = d.get("race", "")
        if raw_race:
            for r in raw_race.split():
                self.by_race.setdefault(r, []).append(d)

        # Spell school
        school = d.get("spellSchool", "")
        if school:
            for s in school.split():
                self.by_school.setdefault(s, []).append(d)

        # Cost (bucket >10)
        cost = d.get("cost", 0)
        bucket = cost if cost <= _MAX_COST_BUCKET else _MAX_COST_BUCKET
        self.by_cost.setdefault(bucket, []).append(d)

        # Format
        fmt = d.get("format", "standard")
        self.by_format.setdefault(fmt, []).append(d)

        # Set
        card_set = d.get("set", "")
        if card_set:
            self.by_set.setdefault(card_set, []).append(d)

        # Rarity
        rarity = d.get("rarity", "")
        if rarity and rarity != "无":
            self.by_rarity.setdefault(rarity, []).append(d)

        # Composite: (class, type)
        if card_class and card_type:
            self._class_type.setdefault((card_class, card_type), []).append(d)

        # Composite: (mechanic, type)
        for mech in d.get("mechanics", []):
            self._mechanic_type.setdefault((mech, card_type), []).append(d)

    def _ensure_indexes(self) -> None:
        """Build indexes if not yet built."""
        if not self._indexes_built:
            self._build_indexes()

    # ── Core lookups ───────────────────────────

    def get_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Get raw card dict by card_id. Returns None if not found."""
        return self._cards.get(card_id)

    def get_by_dbf(self, dbf_id: int) -> Optional[Dict[str, Any]]:
        """Get raw card dict by dbfId. Returns None if not found."""
        card_id = self._dbf_index.get(dbf_id)
        if card_id is None:
            return None
        return self._cards.get(card_id)

    def card_id_to_dbf(self, card_id: str) -> Optional[int]:
        """Reverse lookup: card_id → dbfId."""
        card = self._cards.get(card_id)
        if card is not None:
            return card.get("dbfId")
        return None

    def get_collectible_cards(self, fmt: str = "standard") -> List[Dict]:
        """Return list of collectible cards, optionally filtered by format."""
        if fmt == "standard":
            self._ensure_indexes()
        source = self._standard if fmt == "standard" else self._collectible
        return list(source.values())

    def get_card_xml(self, card_id: str):
        """Get raw XML card object (python-hearthstone)."""
        if self._xml_db is not None:
            return self._xml_db.get(card_id)
        return None

    # ── Multi-dimensional search (NEW) ─────────

    def search(
        self,
        *,
        name: str | None = None,
        dbf_id: int | None = None,
        card_type: str | List[str] | None = None,
        mechanics: str | List[str] | None = None,
        card_class: str | List[str] | None = None,
        race: str | List[str] | None = None,
        spell_school: str | List[str] | None = None,
        cost: int | Tuple[int, int] | None = None,
        text: str | Pattern | None = None,
        set_name: str | List[str] | None = None,
        rarity: str | List[str] | None = None,
        format: str | None = None,
        collectible: bool | None = True,
    ) -> List[Dict[str, Any]]:
        """Multi-dimensional card search.

        Filter semantics:
        - name:        case-insensitive substring, zhCN + enUS
        - dbf_id:      exact match
        - card_type:   any-of (card matches if type IN list)
        - mechanics:   all-of (card must have ALL listed mechanics)
        - card_class:  any-of
        - race:        any-of
        - spell_school: any-of
        - cost:        exact int or (min, max) tuple range
        - text:        regex pattern on card text (both languages)
        - set_name:    any-of
        - rarity:      any-of
        - format:      "standard" or "wild"
        - collectible: True=only collectible, False=only non-collectible, None=all

        Implementation: frozenset intersection for indexed fields,
        then linear scan for name/text on narrowed candidates.
        """
        self._ensure_indexes()

        # Phase 1: indexed filters → frozenset intersection
        candidate_dbfs: Optional[frozenset] = None

        if dbf_id is not None:
            d = self.get_by_dbf(dbf_id)
            if d is None:
                return []
            candidate_dbfs = frozenset([dbf_id])

        def _any_of(current: Optional[frozenset], values, prefix: str) -> Optional[frozenset]:
            """Intersect current with union of all frozensets for values."""
            parts = []
            for v in ([values] if isinstance(values, str) else values):
                fs = self._dbf_frozensets.get(f"{prefix}:{v}")
                if fs is None:
                    return frozenset()  # empty → no matches
                parts.append(fs)
            if not parts:
                return current
            combined = parts[0] if len(parts) == 1 else frozenset.union(*parts)
            return combined if current is None else current & combined

        if card_type is not None:
            candidate_dbfs = _any_of(candidate_dbfs, card_type, "type")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if card_class is not None:
            candidate_dbfs = _any_of(candidate_dbfs, card_class, "class")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if race is not None:
            candidate_dbfs = _any_of(candidate_dbfs, race, "race")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if spell_school is not None:
            candidate_dbfs = _any_of(candidate_dbfs, spell_school, "school")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if mechanics is not None:
            mechs = [mechanics] if isinstance(mechanics, str) else mechanics
            for m in mechs:
                fs = self._dbf_frozensets.get(f"mechanic:{m}")
                if fs is None:
                    return []
                candidate_dbfs = fs if candidate_dbfs is None else candidate_dbfs & fs
                if not candidate_dbfs:
                    return []

        if set_name is not None:
            candidate_dbfs = _any_of(candidate_dbfs, set_name, "set")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if rarity is not None:
            candidate_dbfs = _any_of(candidate_dbfs, rarity, "rarity")
            if candidate_dbfs is not None and not candidate_dbfs:
                return []

        if format is not None:
            fs = self._dbf_frozensets.get(f"format:{format}")
            if fs is None:
                return []
            candidate_dbfs = fs if candidate_dbfs is None else candidate_dbfs & fs
            if not candidate_dbfs:
                return []

        if cost is not None:
            if isinstance(cost, tuple):
                cmin, cmax = cost
            else:
                cmin = cmax = cost
            # Intersect all cost buckets in range
            cost_parts = []
            for c in range(max(0, cmin), min(cmax + 1, _MAX_COST_BUCKET + 1)):
                bucket = c if c <= _MAX_COST_BUCKET else _MAX_COST_BUCKET
                fs = self._dbf_frozensets.get(f"cost:{bucket}")
                if fs:
                    cost_parts.append(fs)
            if not cost_parts:
                return []
            combined = frozenset.union(*cost_parts)
            candidate_dbfs = combined if candidate_dbfs is None else candidate_dbfs & combined
            if not candidate_dbfs:
                return []

        if collectible is True:
            coll_set = frozenset(
                d["dbfId"] for d in self._collectible.values() if d.get("dbfId")
            )
            candidate_dbfs = coll_set if candidate_dbfs is None else candidate_dbfs & coll_set

        # Build candidates list from dbf IDs
        if candidate_dbfs is not None:
            candidates = [
                self.dbf_lookup[dbf] for dbf in candidate_dbfs
                if dbf in self.dbf_lookup
            ]
        else:
            if collectible is True or collectible is None:
                candidates = list(self._collectible.values())
            else:
                candidates = list(self._cards.values())

        # Phase 2: linear scan for name/text
        results = []
        name_lower = name.lower() if name else None
        text_pat = None
        if text is not None:
            text_pat = re.compile(text, re.IGNORECASE) if isinstance(text, str) else text

        for c in candidates:
            if name_lower:
                zh = c.get("name", "").lower()
                en = c.get("englishName", "").lower()
                if name_lower not in zh and name_lower not in en:
                    continue
            if text_pat:
                combined_text = c.get("text", "") + c.get("englishText", "")
                if not text_pat.search(combined_text):
                    continue
            # Cost range filter for tuple cost
            if cost is not None and isinstance(cost, tuple):
                cc = c.get("cost", 0)
                if not (cost[0] <= cc <= cost[1]):
                    continue
            results.append(c)

        return results

    # ── Pool queries (backward compat) ─────────

    def get_pool(
        self,
        *,
        card_class: Optional[str] = None,
        card_type: Optional[str] = None,
        mechanics: Optional[str | List[str]] = None,
        race: Optional[str] = None,
        school: Optional[str] = None,
        cost: Optional[int] = None,
        cost_min: Optional[int] = None,
        cost_max: Optional[int] = None,
        format: Optional[str] = None,
        rarity: Optional[str] = None,
        card_set: Optional[str] = None,
        exclude_dbfids: Optional[Set[int] | List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Query card pool with multiple filters (AND logic, frozenset intersection).

        Uses pre-computed frozenset indexes for O(min_set) intersection.
        Results are cached for repeated queries.
        """
        self._ensure_indexes()
        cache_key_parts: List[str] = []
        dbf_sets: List[frozenset] = []

        # Composite: class + type
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
            output = list(self._collectible.values())
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
                output = [
                    self.dbf_lookup[dbf] for dbf in result_ids
                    if dbf in self.dbf_lookup
                ]

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

    def discover_pool(
        self,
        card_class: str,
        *,
        card_type: Optional[str] = None,
        school: Optional[str] = None,
        cost_max: Optional[int] = None,
        card_set: Optional[str] = None,
        format: str = "standard",
        exclude_dbfids: Optional[Set[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Hearthstone discover pool: class + neutral, excludes hero/location.

        Supports optional filters for spell school, mana cost ceiling, and
        card set (expansion) — all applied via the efficient frozenset indexes.
        """
        self._ensure_indexes()
        # Use get_pool for the core class+format filter (fast frozenset index)
        get_kwargs: dict = {"card_class": card_class, "format": format}
        if card_type:
            get_kwargs["card_type"] = card_type
        if school:
            get_kwargs["school"] = school
        if card_set:
            get_kwargs["card_set"] = card_set

        class_cards = self.get_pool(**get_kwargs)

        # Neutral cards: same filters but card_class="NEUTRAL"
        neut_kwargs = dict(get_kwargs, card_class="NEUTRAL")
        neutral_cards = self.get_pool(**neut_kwargs)

        pool = class_cards + neutral_cards
        pool = [c for c in pool if c.get("type", "") not in _EXCLUDED_DISCOVER_TYPES]
        if cost_max is not None:
            pool = [c for c in pool if c.get("cost", 0) <= cost_max]
        if exclude_dbfids:
            excl = set(exclude_dbfids)
            pool = [c for c in pool if c.get("dbfId", -1) not in excl]
        return pool

    def random_pool(
        self,
        size: int,
        *,
        allow_duplicates: bool = False,
        **filters: Any,
    ) -> List[Dict[str, Any]]:
        """Sample *size* random cards matching *filters*."""
        pool = self.get_pool(**filters)
        if not pool:
            return []
        if len(pool) <= size and not allow_duplicates:
            return list(pool)
        if allow_duplicates:
            return random.choices(pool, k=size)
        return random.sample(pool, min(size, len(pool)))

    # ── Auto-update ────────────────────────────

    def _is_stale(self, max_age_hours: float) -> bool:
        """Check if local data is older than threshold by file mtime."""
        threshold = time.time() - max_age_hours * 3600
        data_dir = PROJECT_ROOT / "card_data" / self._build
        if not data_dir.exists():
            return True
        zh_path = data_dir / "zhCN" / "cards.collectible.json"
        if not zh_path.exists():
            return True
        try:
            return zh_path.stat().st_mtime < threshold
        except OSError:
            return True

    def _try_auto_update(self) -> None:
        """Attempt update, log warning on failure, never raise."""
        try:
            status = self.update()
            if status.updated:
                logger.info(
                    "CardDB auto-updated: %d cards, v%s",
                    status.card_count, status.version,
                )
        except Exception as e:
            logger.warning("Auto-update failed, using local data: %s", e)

    def check_update(self) -> UpdateStatus:
        """Check if remote has newer data. No side effects."""
        t0 = time.time()
        try:
            local_fp = None
            zh_path = PROJECT_ROOT / "card_data" / self._build / "zhCN" / "cards.collectible.json"
            if zh_path.exists():
                data = load_json(zh_path)
                local_fp = _card_id_fingerprint(data)

            url = f"{_API_BASE}/latest/zhCN/cards.collectible.json"
            remote_data = _fetch_json(url, timeout=15)
            remote_fp = _card_id_fingerprint(remote_data)
            has_update = (local_fp != remote_fp) if local_fp else True

            return UpdateStatus(
                updated=has_update,
                version=str(self._build),
                card_count=len(remote_data),
                elapsed_seconds=time.time() - t0,
            )
        except Exception as exc:
            return UpdateStatus(
                updated=False,
                error=str(exc),
                elapsed_seconds=time.time() - t0,
            )

    def update(self, force: bool = False) -> UpdateStatus:
        """Full update pipeline: fetch → build → reload."""
        t0 = time.time()

        # 1. Fetch
        fetch_result = self._fetch_latest_cards(force=force)
        if not fetch_result.get("fetched") and not force:
            return UpdateStatus(
                updated=False,
                version=str(self._build),
                elapsed_seconds=time.time() - t0,
            )

        # 2. Build databases
        build_result = self.build_databases()

        # 3. Reload
        self._cards.clear()
        self._dbf_index.clear()
        self._collectible.clear()
        self._standard.clear()
        self._indexes_built = False
        self.dbf_lookup.clear()
        for attr in (
            self.by_mechanic, self.by_type, self.by_class, self.by_race,
            self.by_school, self.by_cost, self.by_format, self.by_set,
            self.by_rarity, self._class_type, self._mechanic_type,
        ):
            attr.clear()
        self._dbf_frozensets.clear()
        self._pool_cache.clear()

        self._load_local_data()

        return UpdateStatus(
            updated=True,
            version=str(self._build),
            card_count=len(self._cards),
            elapsed_seconds=time.time() - t0,
        )

    def _fetch_latest_cards(self, force: bool = False) -> Dict[str, Any]:
        """Fetch latest cards from HSJSON /latest/ endpoint."""
        build = self._build
        fetched: List[str] = []
        skipped: List[str] = []
        card_counts: Dict[str, int] = {}

        for locale in ("zhCN", "enUS"):
            for filename in _CARD_FILES:
                cache_path = PROJECT_ROOT / "card_data" / build / locale / filename
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                rel = f"{locale}/{filename}"

                if not force and cache_path.exists():
                    skipped.append(rel)
                    try:
                        data = load_json(cache_path)
                        card_counts[f"{locale}_{filename.replace('.json', '')}"] = len(data)
                    except (OSError, ValueError):
                        pass
                    continue

                url = f"{_API_BASE}/latest/{locale}/{filename}"
                logger.info("Fetching %s …", url)
                try:
                    data = _fetch_json(url, timeout=60)
                except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                    logger.error("Failed to fetch %s: %s", url, exc)
                    continue

                cache_path.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8",
                )
                fetched.append(rel)
                card_counts[f"{locale}_{filename.replace('.json', '')}"] = len(data)
                logger.info("  %s → %d cards", rel, len(data))

        now_iso = datetime.now(tz=timezone.utc).isoformat()
        meta = _read_update_metadata(build)
        meta.update({
            "last_update": now_iso,
            "build": build,
            "card_counts": card_counts,
        })
        _write_update_metadata(build, meta)

        return {
            "build": build,
            "fetched": fetched,
            "skipped": skipped,
            "card_counts": card_counts,
            "last_update": now_iso,
        }

    def build_databases(self) -> Dict[str, Any]:
        """Build unified_standard.json and unified_wild.json."""
        build = self._build
        data_dir = PROJECT_ROOT / "card_data" / build

        # 1. Standard
        std_output = data_dir / "unified_standard.json"
        std_stats: Dict[str, Any] = {}
        try:
            zh_path = data_dir / "zhCN" / "cards.collectible.json"
            en_path = data_dir / "enUS" / "cards.collectible.json"
            zh_data: List[dict] = load_json(zh_path)
            en_data: List[dict] = load_json(en_path)
            en_by_id = {c["id"]: c for c in en_data}
            cards = []
            for zh in zh_data:
                if zh.get("set", "") not in STANDARD_SETS:
                    continue
                en = en_by_id.get(zh["id"], {})
                cards.append(_build_card_dict(zh, en))
            cards.sort(key=lambda x: (x.get("cost", 0), x["name"]))
            std_output.parent.mkdir(parents=True, exist_ok=True)
            std_output.write_text(
                json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8",
            )
            std_stats = {"standard_cards": len(cards), "output": str(std_output)}
            logger.info("Standard DB rebuilt: %s", std_stats)
        except Exception as exc:
            std_stats = {"error": str(exc)}
            logger.error("Failed to rebuild standard DB: %s", exc)

        # 2. Wild
        wild_output = data_dir / "unified_wild.json"
        wild_stats: Dict[str, Any] = {}
        try:
            zh_path = data_dir / "zhCN" / "cards.collectible.json"
            en_path = data_dir / "enUS" / "cards.collectible.json"
            zh_data = load_json(zh_path)
            en_data = load_json(en_path)
            en_by_id = {c["id"]: c for c in en_data}
            wild_cards = []
            for zh in zh_data:
                card_set = zh.get("set", "")
                if card_set in STANDARD_SETS:
                    continue
                en = en_by_id.get(zh["id"], {})
                text_raw = zh.get("text", "") or ""
                wild_cards.append({
                    "dbfId": zh.get("dbfId", 0),
                    "cardId": zh.get("id", ""),
                    "name": zh.get("name", ""),
                    "ename": en.get("name", ""),
                    "cost": zh.get("cost", 0),
                    "attack": zh.get("attack", 0),
                    "health": zh.get("health", 0),
                    "durability": zh.get("durability", 0),
                    "armor": zh.get("armor", 0),
                    "type": zh.get("type", ""),
                    "cardClass": zh.get("cardClass", "NEUTRAL"),
                    "race": zh.get("race", ""),
                    "rarity": zh.get("rarity", ""),
                    "text": _clean_text(text_raw),
                    "mechanics": zh.get("mechanics", []),
                    "overload": zh.get("overload", 0),
                    "spellDamage": zh.get("spellDamage", 0),
                    "set": card_set,
                    "format": "wild",
                })
            wild_cards.sort(key=lambda x: (x.get("cost", 0), x["name"]))
            wild_output.parent.mkdir(parents=True, exist_ok=True)
            wild_output.write_text(
                json.dumps(wild_cards, ensure_ascii=False, indent=1), encoding="utf-8",
            )
            wild_stats = {"wild_only": len(wild_cards), "output": str(wild_output)}
            logger.info("Wild DB rebuilt: %s", wild_stats)
        except Exception as exc:
            wild_stats = {"error": str(exc)}
            logger.error("Failed to rebuild wild DB: %s", exc)

        # 3. Clear module-level singleton caches
        global _db_cache
        _db_cache.clear()

        return {"build": build, "standard": std_stats, "wild": wild_stats}

    # ── Statistics ─────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return index statistics."""
        self._ensure_indexes()
        return {
            "total_cards": len(self._cards),
            "collectible": len(self._collectible),
            "standard": len(self._standard),
            "by_class": {k: len(v) for k, v in sorted(self.by_class.items())},
            "by_type": {k: len(v) for k, v in sorted(self.by_type.items())},
            "by_race": {k: len(v) for k, v in sorted(self.by_race.items())},
            "by_school": {k: len(v) for k, v in sorted(self.by_school.items())},
            "by_cost": {k: len(v) for k, v in sorted(self.by_cost.items())},
            "by_mechanic": {k: len(v) for k, v in sorted(self.by_mechanic.items())},
            "by_format": {k: len(v) for k, v in sorted(self.by_format.items())},
            "by_set": {k: len(v) for k, v in sorted(self.by_set.items())},
            "by_rarity": {k: len(v) for k, v in sorted(self.by_rarity.items())},
            "mechanic_count": len(self.by_mechanic),
            "type_count": len(self.by_type),
            "class_count": len(self.by_class),
            "race_count": len(self.by_race),
            "school_count": len(self.by_school),
        }

    # ── Properties ─────────────────────────────

    @property
    def total(self) -> int:
        """Total cards (collectible + non-collectible)."""
        return len(self._cards)

    @property
    def collectible_count(self) -> int:
        """Number of collectible cards."""
        return len(self._collectible)

    @property
    def standard_count(self) -> int:
        """Number of standard-format collectible cards."""
        self._ensure_indexes()
        return len(self._standard)

    @property
    def raw_db(self):
        """Raw XML database (python-hearthstone), if loaded."""
        return self._xml_db

    # Public index attributes (backward compat with CardIndex)
    # These are populated by _build_indexes()
    dbf_lookup: Dict[int, Dict[str, Any]]
    by_mechanic: Dict[str, List[Dict[str, Any]]]
    by_type: Dict[str, List[Dict[str, Any]]]
    by_class: Dict[str, List[Dict[str, Any]]]
    by_race: Dict[str, List[Dict[str, Any]]]
    by_school: Dict[str, List[Dict[str, Any]]]
    by_cost: Dict[int, List[Dict[str, Any]]]
    by_format: Dict[str, List[Dict[str, Any]]]
    by_set: Dict[str, List[Dict[str, Any]]]
    by_rarity: Dict[str, List[Dict[str, Any]]]


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────

_db: Optional[CardDB] = None
_db_cache: Dict[Tuple[str, bool], CardDB] = {}
_hero_class_map_cache: Dict[str, Dict[int, str]] = {}


def get_db(
    rebuild: bool = False,
    build: str = DATA_BUILD,
    *,
    auto_update: bool = True,
    max_age_hours: float = 168.0,
    load_xml: bool = True,
) -> CardDB:
    """Get the global CardDB singleton."""
    key = (build, load_xml)
    if not rebuild and key in _db_cache:
        return _db_cache[key]
    _db_cache[key] = CardDB(
        build=build, auto_update=auto_update,
        max_age_hours=max_age_hours, load_xml=load_xml,
    )
    return _db_cache[key]


def reset_db() -> None:
    """Reset singleton. For testing."""
    global _db, _db_cache
    _db = None
    _db_cache.clear()


# ──────────────────────────────────────────────
# Convenience shortcuts
# ──────────────────────────────────────────────

def get_card(card_id: str) -> Optional[Dict[str, Any]]:
    """Shortcut: get_db().get_card(card_id)."""
    return get_db().get_card(card_id)


def get_by_dbf(dbf_id: int) -> Optional[Dict[str, Any]]:
    """Shortcut: get_db().get_by_dbf(dbf_id)."""
    return get_db().get_by_dbf(dbf_id)


def search(**filters) -> List[Dict[str, Any]]:
    """Shortcut: get_db().search(**filters)."""
    return get_db().search(**filters)


# ──────────────────────────────────────────────
# Hero class map (lightweight, doesn't need full DB)
# ──────────────────────────────────────────────

def get_hero_class_map(build: str = DATA_BUILD) -> Dict[int, str]:
    """Get lightweight hero dbfId → class mapping."""
    if build in _hero_class_map_cache:
        return _hero_class_map_cache[build]

    path = _cache_path(build, "meta", "hero_class_map.json")
    mapping: Dict[int, str] = dict(_DEFAULT_HERO_DBF_CLASS_MAP)

    raw = _load_cached(path)
    if raw:
        for item in raw:
            try:
                dbf = int(item.get("dbfId"))
                cls = str(item.get("cardClass", "")).upper()
                if dbf > 0 and cls:
                    mapping[dbf] = cls
            except (TypeError, ValueError):
                continue
    else:
        serializable = [
            {"dbfId": dbf, "cardClass": cls} for dbf, cls in sorted(mapping.items())
        ]
        _save_cache(path, serializable)

    _hero_class_map_cache[build] = mapping
    return mapping


# ──────────────────────────────────────────────
# Backward-compat aliases
# ──────────────────────────────────────────────

# Consumers that import get_index from card_index
def get_index(rebuild: bool = False) -> CardDB:
    """Alias for get_db(). Returns CardDB which has same API as old CardIndex."""
    return get_db(rebuild=rebuild)

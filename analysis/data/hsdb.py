# -*- coding: utf-8 -*-
"""HSCardDB — 基于 HearthstoneJSON API + python-hearthstone 的炉石卡牌数据库

主数据源: HearthstoneJSON API (api.hearthstonejson.com)
  - ``zhCN/cards.collectible.json`` 中文卡牌名称/描述
  - ``enUS/cards.collectible.json`` 英文卡牌名称/描述
  - 提供权威的可收集卡牌数据

辅助数据源: python-hearthstone CardDefs.xml (hearthstone_data 包)
  - 完整卡牌数据库，包括不可收集卡牌（衍生物、附魔、英雄等）
  - 枚举定义 (GameTag, CardType, CardClass 等)
  - 用于通过 dbfId 查询不可收集卡牌

用法::

    from analysis.data.hsdb import get_db
    db = get_db()
    card = db.get_card("EX1_001")          # 按 card_id 查询
    card = db.get_by_dbf(1655)             # 按 dbf_id 查询
    pool = db.discover_pool("MAGE")        # 发现池
    minions = db.get_pool(card_class="ROGUE", card_type="MINION")
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_API_BASE = "https://api.hearthstonejson.com/v1"
_UA = "hs_analysis/1.0"

from analysis.config import PROJECT_ROOT

_CACHE_DIR = Path(os.environ.get("HSJSON_CACHE_DIR", str(PROJECT_ROOT / "card_data")))

STANDARD_SETS: set = {
    "CATACLYSM",
    "TIME_TRAVEL",
    "THE_LOST_CITY",
    "EMERALD_DREAM",
    "CORE",
    "EVENT",
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

_hero_class_map_cache: Dict[str, Dict[int, str]] = {}


def _fetch_json(url: str, timeout: int = 60) -> List[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def _cache_path(build: str, locale: str, name: str) -> Path:
    p = _CACHE_DIR / build / locale / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_cached(path: Path) -> Optional[List[dict]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(path: Path, data: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        logger.warning("Cache write failed: %s", exc)


def _merge_locale(zh_data: List[dict], en_data: List[dict]) -> Dict[str, dict]:
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


class HSCardDB:
    """双语言卡牌数据库，数据来自 HearthstoneJSON API。

    索引所有可收集卡牌以支持快速池查询。
    不可收集卡牌（衍生物、附魔）通过 python-hearthstone 回退查询。
    """

    def __init__(
        self,
        build: str = "240397",
        *,
        load_xml: bool = True,
        build_indexes: bool = True,
    ) -> None:
        self._build = build
        self._load_xml_enabled = load_xml
        self._indexes_built = False
        self._cards: Dict[str, Dict[str, Any]] = {}
        self._dbf_index: Dict[int, str] = {}
        self._collectible: Dict[str, Dict[str, Any]] = {}
        self._standard: Dict[str, Dict[str, Any]] = {}
        self._xml_db = None

        self._by_class: Dict[str, List[Dict]] = {}
        self._by_type: Dict[str, List[Dict]] = {}
        self._by_race: Dict[str, List[Dict]] = {}
        self._by_school: Dict[str, List[Dict]] = {}
        self._by_cost: Dict[int, List[Dict]] = {}
        self._by_mechanic: Dict[str, List[Dict]] = {}
        self._by_set: Dict[str, List[Dict]] = {}
        self._by_rarity: Dict[str, List[Dict]] = {}
        self._by_format: Dict[str, List[Dict]] = {}

        self._load_hsjson()
        if self._load_xml_enabled:
            self._load_xml_fallback()
        if build_indexes:
            self._build_indexes()

    def _ensure_indexes(self) -> None:
        if not self._indexes_built:
            self._build_indexes()

    def _load_hsjson(self) -> None:
        build = self._build

        # 1) 可收集卡牌（主数据源）
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

        # 2) 完整卡牌数据库（包含衍生物、附魔、英雄技能）
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
            # 仅添加不可收集卡牌（衍生物、附魔等）
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
            logger.info("Full DB: added %d non-collectible cards (total %d)",
                        added, len(self._cards))

    def _load_xml_fallback(self) -> None:
        # 跳过XML加载，如果 hearthstone_data 未安装
        # 因为 hearthstone.cardxml.load() 会尝试下载 CardDefs.xml
        # (~200MB) 并在没有数据包时无限期挂起
        try:
            import importlib.util
            if importlib.util.find_spec("hearthstone_data") is None:
                logger.info("hearthstone_data not installed, skipping XML fallback")
                return
        except Exception:
            pass

        try:
            import signal
            from hearthstone.cardxml import load as _load_xml
            from hearthstone.enums import CardSet, CardType, Locale

            # 设置10秒超时以防止无限挂起
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
        from hearthstone.enums import CardType, CardClass, Race, Rarity, GameTag

        card_class = card.card_class.name if card.card_class else "NEUTRAL"
        card_type = card.type.name if card.type else ""
        rarity = card.rarity.name if card.rarity else ""
        races = " ".join(r.name for r in (card.races or []) if r) if card.races else ""
        if not races and card.race:
            races = card.race.name
        mechanics = []
        _BOOLS = {
            "taunt": "TAUNT",
            "charge": "CHARGE",
            "divine_shield": "DIVINE_SHIELD",
            "battlecry": "BATTLECRY",
            "deathrattle": "DEATHRATTLE",
            "windfury": "WINDFURY",
            "lifesteal": "LIFESTEAL",
            "poisonous": "POISONOUS",
            "rush": "RUSH",
            "reborn": "REBORN",
            "discover": "DISCOVER",
            "secret": "SECRET",
            "quest": "QUEST",
            "outcast": "OUTCAST",
            "corrupt": "CORRUPT",
            "echo": "ECHO",
            "twinspell": "TWINSPELL",
            "tradeable": "TRADEABLE",
            "colossal": "COLOSSAL",
            "titan": "TITAN",
            "forge": "FORGE",
            "overheal": "OVERHEAL",
            "combo": "COMBO",
        }
        for prop, name in _BOOLS.items():
            if getattr(card, prop, False):
                mechanics.append(name)
        mechanics.sort()

        # 从 strings 字典提取中文名称（card.name 始终为英文）
        zh_name = ""
        cardname_strings = (
            card.strings.get(GameTag.CARDNAME) if hasattr(card, "strings") else None
        )
        if isinstance(cardname_strings, dict):
            zh_name = cardname_strings.get("zhCN", "")

        # 同样提取中文描述
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

    def _build_indexes(self) -> None:
        if self._indexes_built:
            return

        for cid, d in self._collectible.items():
            card_set = d.get("set", "")
            if card_set in STANDARD_SETS:
                self._standard[cid] = d
                d["format"] = "standard"
            else:
                d["format"] = "wild"
            self._index_card(d)

        logger.info(
            "HSCardDB indexed: %d total, %d collectible, %d standard",
            len(self._cards),
            len(self._collectible),
            len(self._standard),
        )
        self._indexes_built = True

    def _index_card(self, d: Dict) -> None:
        cls = d.get("cardClass", "")
        if cls:
            self._by_class.setdefault(cls, []).append(d)
        typ = d.get("type", "")
        if typ:
            self._by_type.setdefault(typ, []).append(d)
        race = d.get("race", "")
        if race:
            for r in race.split():
                self._by_race.setdefault(r, []).append(d)
        school = d.get("spellSchool", "")
        if school:
            self._by_school.setdefault(school, []).append(d)
        cost = d.get("cost", 0)
        bucket = cost if cost <= 10 else 10
        self._by_cost.setdefault(bucket, []).append(d)
        fmt = d.get("format", "")
        if fmt:
            self._by_format.setdefault(fmt, []).append(d)
        card_set = d.get("set", "")
        if card_set:
            self._by_set.setdefault(card_set, []).append(d)
        rarity = d.get("rarity", "")
        if rarity:
            self._by_rarity.setdefault(rarity, []).append(d)
        for mech in d.get("mechanics", []):
            self._by_mechanic.setdefault(mech, []).append(d)

    def get_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        return self._cards.get(card_id)

    def get_card_xml(self, card_id: str):
        if self._xml_db is not None:
            return self._xml_db.get(card_id)
        return None

    def get_by_dbf(self, dbf_id: int) -> Optional[Dict[str, Any]]:
        card_id = self._dbf_index.get(dbf_id)
        if card_id is None:
            return None
        return self._cards.get(card_id)

    def card_id_to_dbf(self, card_id: str) -> Optional[int]:
        """通过 card_id 字符串查询 dbfId。

        get_by_dbf() 的反向操作——贝叶斯对手模型使用 dbfId 整数，
        而追踪器使用 card_id 字符串。
        """
        card = self._cards.get(card_id)
        if card is not None:
            return card.get("dbfId")
        return None

    def get_collectible_cards(self, fmt: str = "standard") -> List[Dict]:
        if fmt == "standard":
            self._ensure_indexes()
        source = self._standard if fmt == "standard" else self._collectible
        return list(source.values())

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
    ) -> List[Dict]:
        self._ensure_indexes()
        pools: List[List[Dict]] = []
        if card_class:
            pools.append(self._by_class.get(card_class, []))
        if card_type:
            pools.append(self._by_type.get(card_type, []))
        if mechanics is not None:
            if isinstance(mechanics, str):
                mechanics = [mechanics]
            for m in mechanics:
                pools.append(self._by_mechanic.get(m, []))
        if race:
            pools.append(self._by_race.get(race, []))
        if school:
            pools.append(self._by_school.get(school, []))
        if cost is not None:
            bucket = cost if cost <= 10 else 10
            pools.append(self._by_cost.get(bucket, []))
        if format:
            pools.append(self._by_format.get(format, []))
        if rarity:
            pools.append(self._by_rarity.get(rarity, []))
        if card_set:
            pools.append(self._by_set.get(card_set, []))

        if not pools:
            result = list(self._collectible.values())
        else:
            pools.sort(key=len)
            dbf_sets = [frozenset(c["dbfId"] for c in p) for p in pools]
            result_ids = dbf_sets[0]
            for s in dbf_sets[1:]:
                result_ids = result_ids & s
                if not result_ids:
                    return []
            id_map = {c["dbfId"]: c for c in pools[0] if c["dbfId"] in result_ids}
            result = [id_map[dbf] for dbf in result_ids if dbf in id_map]

        if cost_min is not None or cost_max is not None:
            cmin = cost_min if cost_min is not None else 0
            cmax = cost_max if cost_max is not None else 999
            result = [c for c in result if cmin <= c.get("cost", 0) <= cmax]

        if exclude_dbfids:
            excl = set(exclude_dbfids)
            result = [c for c in result if c.get("dbfId", -1) not in excl]

        return result

    def discover_pool(
        self,
        card_class: str,
        *,
        card_type: Optional[str] = None,
        format: str = "standard",
        exclude_dbfids: Optional[Set[int]] = None,
    ) -> List[Dict]:
        self._ensure_indexes()
        class_cards = self.get_pool(card_class=card_class, format=format)
        neutral_cards = self.get_pool(card_class="NEUTRAL", format=format)
        pool = class_cards + neutral_cards
        pool = [c for c in pool if c.get("type", "") not in _EXCLUDED_DISCOVER_TYPES]
        if card_type:
            pool = [c for c in pool if c.get("type") == card_type]
        if exclude_dbfids:
            excl = set(exclude_dbfids)
            pool = [c for c in pool if c.get("dbfId", -1) not in excl]
        return pool

    def stats(self) -> Dict[str, Any]:
        self._ensure_indexes()
        return {
            "total_cards": len(self._cards),
            "collectible": len(self._collectible),
            "standard": len(self._standard),
            "by_class": {k: len(v) for k, v in sorted(self._by_class.items())},
            "by_type": {k: len(v) for k, v in sorted(self._by_type.items())},
            "by_race": {k: len(v) for k, v in sorted(self._by_race.items())},
            "by_school": {k: len(v) for k, v in sorted(self._by_school.items())},
            "by_cost": {k: len(v) for k, v in sorted(self._by_cost.items())},
            "by_mechanic": {k: len(v) for k, v in sorted(self._by_mechanic.items())},
        }

    @property
    def total(self) -> int:
        return len(self._cards)

    @property
    def collectible_count(self) -> int:
        return len(self._collectible)

    @property
    def standard_count(self) -> int:
        self._ensure_indexes()
        return len(self._standard)

    @property
    def raw_db(self):
        return self._xml_db


_db_cache: Dict[Tuple[str, bool, bool], HSCardDB] = {}


def get_db(
    rebuild: bool = False,
    build: str = "240397",
    *,
    load_xml: bool = True,
    build_indexes: bool = True,
) -> HSCardDB:
    key = (build, load_xml, build_indexes)
    if not rebuild and key in _db_cache:
        return _db_cache[key]
    _db_cache[key] = HSCardDB(
        build=build, load_xml=load_xml, build_indexes=build_indexes
    )
    return _db_cache[key]


def get_hero_class_map(build: str = "240397") -> Dict[int, str]:
    """获取轻量级英雄 dbfId -> 职业映射。

    优先使用小型本地JSON缓存，并内置常见英雄的默认值。
    """
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
            except Exception:
                continue
    else:
        # 用默认值填充缓存，避免热路径触发重量级卡牌数据库初始化
        serializable = [
            {"dbfId": dbf, "cardClass": cls} for dbf, cls in sorted(mapping.items())
        ]
        _save_cache(path, serializable)

    _hero_class_map_cache[build] = mapping
    return mapping

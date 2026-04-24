# -*- coding: utf-8 -*-
"""Card data updater: freshness check, fetch latest, rebuild databases.

Features:
  1. ``get_data_status()``  — report current card data freshness
  2. ``fetch_latest_cards()`` / ``import_card_json()`` — download or import cards
  3. ``rebuild_databases()`` / ``update_all()`` — rebuild unified DBs & clear caches

CLI::

    python -m analysis.data.card_updater status
    python -m analysis.data.card_updater fetch [--build BUILD] [--force]
    python -m analysis.data.card_updater import JSON_PATH [--locale zhCN]
    python -m analysis.data.card_updater rebuild
    python -m analysis.data.card_updater update [--force]
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATA_BUILD, DATA_DIR, PROJECT_ROOT
from ..utils import load_json
from ..utils.http import http_get_json

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HSJSON_BASE = "https://api.hearthstonejson.com/v1"
_METADATA_FILE = "update_metadata.json"
_UA = "hs_analysis/1.0"
_MAX_AGE_DAYS = 7  # staleness threshold

_CARD_FILES = (
    "cards.collectible.json",
    "cards.json",
)


# ---------------------------------------------------------------------------
# Helpers — metadata persistence
# ---------------------------------------------------------------------------

def _metadata_path(build: str) -> Path:
    """Return path to ``update_metadata.json`` for *build*."""
    return PROJECT_ROOT / "card_data" / build / _METADATA_FILE


def _read_update_metadata(build: str) -> Dict[str, Any]:
    """Read ``update_metadata.json`` for a given build."""
    path = _metadata_path(build)
    if not path.exists():
        return {}
    try:
        return load_json(path)
    except (OSError, ValueError):
        return {}


def _write_update_metadata(build: str, metadata: Dict[str, Any]) -> None:
    """Write ``update_metadata.json`` for a given build."""
    path = _metadata_path(build)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Helpers — network
# ---------------------------------------------------------------------------

def _fetch_json(url: str, timeout: int = 30) -> List[dict]:
    """Fetch JSON from *url*. Returns parsed list/dict."""
    return http_get_json(url, timeout=timeout, user_agent=_UA)


# ---------------------------------------------------------------------------
# Feature 1: Freshness / Status Check
# ---------------------------------------------------------------------------

def _card_id_fingerprint(cards: List[dict]) -> str:
    """Return a stable SHA-256 fingerprint of card IDs in *cards*."""
    ids = sorted(c.get("id", "") for c in cards)
    blob = "\n".join(ids).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _local_card_fingerprint(build: str, locale: str = "zhCN") -> Optional[str]:
    """Return fingerprint of local collectible cards, or ``None`` if missing."""
    path = PROJECT_ROOT / "card_data" / build / locale / "cards.collectible.json"
    if not path.exists():
        return None
    try:
        data = load_json(path)
        return _card_id_fingerprint(data)
    except (OSError, ValueError, TypeError):
        return None


def check_remote_has_update(build: Optional[str] = None) -> Dict[str, Any]:
    """Compare local vs remote card data to detect new builds.

    The HSJSON API does **not** expose build numbers or redirect ``/latest/``
    to versioned URLs.  Instead, we fetch the remote data and compare a
    SHA-256 fingerprint of sorted card IDs against the local cache.

    Returns dict with:
      - ``local_build``: the build we compared against
      - ``local_fingerprint``: SHA-256 of local card IDs
      - ``remote_fingerprint``: SHA-256 of remote card IDs
      - ``remote_card_count``: number of cards in remote response
      - ``has_update``: whether remote data differs from local
    """
    if build is None:
        build = DATA_BUILD

    local_fp = _local_card_fingerprint(build)

    url = f"{_HSJSON_BASE}/latest/zhCN/cards.collectible.json"
    try:
        remote_data = _fetch_json(url, timeout=15)
        remote_fp = _card_id_fingerprint(remote_data)
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to fetch remote card data: %s", exc)
        return {
            "local_build": build,
            "local_fingerprint": local_fp,
            "remote_fingerprint": None,
            "remote_card_count": None,
            "has_update": False,
            "error": str(exc),
        }

    has_update = (local_fp != remote_fp) if local_fp else True

    return {
        "local_build": build,
        "local_fingerprint": local_fp,
        "remote_fingerprint": remote_fp,
        "remote_card_count": len(remote_data),
        "has_update": has_update,
    }


def detect_latest_build() -> Optional[str]:
    """Detect whether a newer Hearthstone build exists on HSJSON.

    Since the API does not expose build numbers, this returns the current
    ``DATA_BUILD`` if data is up-to-date, or ``None`` if unable to check.
    Use :func:`check_remote_has_update` for the full comparison result.
    """
    try:
        result = check_remote_has_update()
        if result.get("error"):
            logger.warning("Build detection failed: %s", result["error"])
            return None
        if result["has_update"]:
            logger.info(
                "Remote data differs from local build %s — update available",
                result["local_build"],
            )
        else:
            logger.info("Local build %s is up-to-date", result["local_build"])
        return result["local_build"]
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Failed to detect latest build: %s", exc)
        return None


def get_data_status(build: Optional[str] = None) -> Dict[str, Any]:
    """Report current card data status.

    Returns dict with:
      - ``build``: current build number
      - ``data_dir``: path to ``card_data/{build}/``
      - ``files``: per-file size / mtime / age info
      - ``last_update``: ISO-8601 timestamp of last successful update (or None)
      - ``is_stale``: whether data is stale (by age or remote comparison)
      - ``remote_check``: fingerprint comparison against remote HSJSON data
    """
    if build is None:
        build = DATA_BUILD

    data_dir = PROJECT_ROOT / "card_data" / build

    # --- enumerate JSON files recursively ---
    files_info: Dict[str, Dict[str, Any]] = {}
    now = time.time()
    if data_dir.exists():
        for fp in sorted(data_dir.rglob("*.json")):
            if fp.name == _METADATA_FILE:
                continue
            rel = str(fp.relative_to(data_dir))
            stat = fp.stat()
            mtime_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            age_days = (now - stat.st_mtime) / 86400.0
            files_info[rel] = {
                "size_kb": round(stat.st_size / 1024, 1),
                "mtime": mtime_dt.isoformat(),
                "age_days": round(age_days, 1),
            }

    # --- read metadata ---
    meta = _read_update_metadata(build)
    last_update = meta.get("last_update")

    # --- check remote for updates ---
    remote_check: Optional[Dict[str, Any]] = None
    try:
        remote_check = check_remote_has_update(build)
    except (OSError, ValueError, TypeError):
        pass

    # --- staleness ---
    is_stale = False
    # stale if any core file > MAX_AGE_DAYS old
    for rel, info in files_info.items():
        if info["age_days"] > _MAX_AGE_DAYS:
            is_stale = True
            break
    # stale if remote data differs
    if remote_check and remote_check.get("has_update"):
        is_stale = True

    return {
        "build": build,
        "data_dir": str(data_dir),
        "files": files_info,
        "last_update": last_update,
        "is_stale": is_stale,
        "remote_check": remote_check,
    }


# ---------------------------------------------------------------------------
# Feature 2: Fetch Latest & Import
# ---------------------------------------------------------------------------

def fetch_latest_cards(
    build: Optional[str] = None,
    force: bool = False,
    locales: Tuple[str, ...] = ("zhCN", "enUS"),
) -> Dict[str, Any]:
    """Fetch latest card data from the HSJSON API.

    Uses the ``/latest/`` endpoint which always serves the newest data.
    Cards are saved to the local ``card_data/{build}/`` directory.

    Args:
        build:   Target build directory for local storage. ``None`` → ``DATA_BUILD``.
        force:   Re-download even if local cache exists.
        locales: Language locales to fetch.

    Returns:
        Stats dict with files fetched, card counts, etc.
    """
    if build is None:
        build = DATA_BUILD

    fetched: List[str] = []
    skipped: List[str] = []
    card_counts: Dict[str, int] = {}

    for locale in locales:
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

            # Fetch from /latest/ — always serves the newest build
            url = f"{_HSJSON_BASE}/latest/{locale}/{filename}"
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

    # write metadata
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


def import_card_json(
    json_path: str,
    build: Optional[str] = None,
    locale: str = "zhCN",
    filename: str = "cards.collectible.json",
) -> Dict[str, Any]:
    """Import card data from an external JSON file.

    Args:
        json_path: Path to the JSON file to import.
        build:     Target build directory. ``None`` → use ``config.DATA_BUILD``.
        locale:    Locale subdirectory.
        filename:  Target filename.

    Returns:
        Stats dict with card count, etc.
    """
    if build is None:
        build = DATA_BUILD

    src = Path(json_path)
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {json_path}")

    data = load_json(src)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of card objects")

    # basic validation — every card should have an "id"
    for i, card in enumerate(data):
        if not isinstance(card, dict) or "id" not in card:
            raise ValueError(f"Card at index {i} is missing 'id' field")

    dest = PROJECT_ROOT / "card_data" / build / locale / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    logger.info("Imported %d cards → %s", len(data), dest)

    # update metadata
    meta = _read_update_metadata(build)
    meta.setdefault("card_counts", {})[f"{locale}_{filename.replace('.json', '')}"] = len(data)
    meta["last_update"] = datetime.now(tz=timezone.utc).isoformat()
    _write_update_metadata(build, meta)

    return {
        "build": build,
        "card_count": len(data),
        "destination": str(dest),
    }


# ---------------------------------------------------------------------------
# Feature 3: Rebuild After Update
# ---------------------------------------------------------------------------

def _build_standard_db(data_dir: Path, output_path: Path) -> Dict[str, Any]:
    """Build ``unified_standard.json`` (reimplements build_unified_db.main).

    This avoids depending on the module-level side-effects of
    ``build_unified_db`` (e.g. ``sys.stdout`` wrapping).
    """
    from .build_unified_db import build_card, STANDARD_SETS as STD_SETS

    zh_path = data_dir / "zhCN" / "cards.collectible.json"
    en_path = data_dir / "enUS" / "cards.collectible.json"

    zh_data: List[dict] = load_json(zh_path)
    en_data: List[dict] = load_json(en_path)
    en_by_id = {c["id"]: c for c in en_data}

    cards = []
    for zh in zh_data:
        if zh.get("set", "") not in STD_SETS:
            continue
        en = en_by_id.get(zh["id"], {})
        cards.append(build_card(zh, en))

    cards.sort(key=lambda x: (x.get("cost", 0), x["name"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8",
    )

    return {"standard_cards": len(cards), "output": str(output_path)}


def _clear_singletons() -> None:
    """Clear in-memory singletons in ``hsdb`` and ``card_index``."""
    try:
        from . import hsdb
        hsdb._db_cache.clear()
        logger.info("Cleared hsdb._db_cache")
    except (ImportError, AttributeError) as exc:
        logger.warning("Failed to clear hsdb cache: %s", exc)

    try:
        from . import card_index
        card_index._index = None
        logger.info("Cleared card_index._index")
    except (ImportError, AttributeError) as exc:
        logger.warning("Failed to clear card_index._index: %s", exc)


def rebuild_databases(build: Optional[str] = None) -> Dict[str, Any]:
    """Rebuild all card databases after an update.

    Steps:
      1. Build ``unified_standard.json``
      2. Build ``unified_wild.json``
      3. Clear in-memory singletons

    Returns:
        Stats dict.
    """
    if build is None:
        build = DATA_BUILD

    data_dir = PROJECT_ROOT / "card_data" / build

    # 1. Standard
    std_output = data_dir / "unified_standard.json"
    std_stats: Dict[str, Any] = {}
    try:
        std_stats = _build_standard_db(data_dir, std_output)
        logger.info("Standard DB rebuilt: %s", std_stats)
    except Exception as exc:
        std_stats = {"error": str(exc)}
        logger.error("Failed to rebuild standard DB: %s", exc)

    # 2. Wild
    wild_output = data_dir / "unified_wild.json"
    wild_stats: Dict[str, Any] = {}
    try:
        from .build_wild_db import build_wild_db
        wild_stats = build_wild_db(data_dir=data_dir, output_path=wild_output)
        logger.info("Wild DB rebuilt: %s", wild_stats)
    except Exception as exc:
        wild_stats = {"error": str(exc)}
        logger.error("Failed to rebuild wild DB: %s", exc)

    # 3. Clear singletons
    _clear_singletons()

    return {
        "build": build,
        "standard": std_stats,
        "wild": wild_stats,
    }


def update_all(
    build: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """One-click: fetch latest + rebuild databases.

    Combines ``fetch_latest_cards()`` + ``rebuild_databases()``.
    """
    fetch_stats = fetch_latest_cards(build=build, force=force)
    rebuild_stats = rebuild_databases(build=fetch_stats["build"])
    return {
        "fetch": fetch_stats,
        "rebuild": rebuild_stats,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Card data updater")
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show current card data status")

    # fetch
    fetch_p = sub.add_parser("fetch", help="Fetch latest card data")
    fetch_p.add_argument("--build", default=None, help="Build number (default: auto-detect)")
    fetch_p.add_argument("--force", action="store_true", help="Force re-download")

    # import
    imp_p = sub.add_parser("import", help="Import external card JSON")
    imp_p.add_argument("json_path", help="Path to JSON file")
    imp_p.add_argument("--build", default=None, help="Target build (default: current)")
    imp_p.add_argument("--locale", default="zhCN")
    imp_p.add_argument("--filename", default="cards.collectible.json")

    # rebuild
    sub.add_parser("rebuild", help="Rebuild card databases from local data")

    # update (fetch + rebuild)
    upd_p = sub.add_parser("update", help="Fetch latest + rebuild")
    upd_p.add_argument("--build", default=None, help="Target build (default: auto-detect)")
    upd_p.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.command == "status":
        status = get_data_status()
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    elif args.command == "fetch":
        stats = fetch_latest_cards(build=args.build, force=args.force)
        print(f"Fetched: {stats}")
    elif args.command == "import":
        stats = import_card_json(
            args.json_path,
            build=getattr(args, "build", None),
            locale=args.locale,
            filename=args.filename,
        )
        print(f"Imported: {stats}")
    elif args.command == "rebuild":
        stats = rebuild_databases()
        print(f"Rebuilt: {stats}")
    elif args.command == "update":
        stats = update_all(build=getattr(args, "build", None), force=args.force)
        print(f"Updated: {stats}")
    else:
        parser.print_help()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    main()

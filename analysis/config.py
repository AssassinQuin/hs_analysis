# -*- coding: utf-8 -*-
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_BUILD = "240397"
DATA_DIR = PROJECT_ROOT / "card_data" / DATA_BUILD
ENUMS_PATH = PROJECT_ROOT / "hearthstone_enums.json"
RANKINGS_PATH = PROJECT_ROOT / "HSReplay_Card_Rankings.xlsx"

UNIFIED_DB_PATH = DATA_DIR / "unified_standard.json"
CURVE_PARAMS_PATH = DATA_DIR / "curve_params.json"
SCORING_REPORT_PATH = DATA_DIR / "scoring_report.json"
HSREPLAY_CACHE_DB = DATA_DIR / "hsreplay_cache.db"
CARD_LIST_PATH = DATA_DIR / "card_list.json"

HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")
HSREPLAY_CARDS_URL = "https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD"
HSREPLAY_ARCHETYPES_URL = "https://hsreplay.net/api/v1/archetypes/"
HSJSON_API_BASE = "https://api.hearthstonejson.com/v1/latest/zhCN/"

CACHE_DAYS = 30

CLASS_MULTIPLIER = {
    "NEUTRAL": 0.85,
    "DEMONHUNTER": 0.95,
    "HUNTER": 0.95,
    "WARRIOR": 0.98,
    "PALADIN": 1.00,
    "ROGUE": 1.00,
    "MAGE": 1.00,
    "DEATHKNIGHT": 1.02,
    "PRIEST": 1.02,
    "WARLOCK": 1.02,
    "DRUID": 1.05,
    "SHAMAN": 1.05,
}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_api_headers() -> dict:
    return {
        "X-Api-Key": HSREPLAY_API_KEY,
        "User-Agent": "HSAnalysis/1.0 (educational research)",
        "Accept": "application/json",
    }

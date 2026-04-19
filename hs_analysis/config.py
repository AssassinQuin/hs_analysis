# -*- coding: utf-8 -*-
"""集中配置管理 — paths, API keys, defaults.

All paths use pathlib.Path for cross-platform compatibility.
API keys are read from environment variables (never hardcoded).
"""

import os
from pathlib import Path

# ── 项目路径 ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "hs_cards"
ENUMS_PATH = PROJECT_ROOT / "hearthstone_enums.json"
RANKINGS_PATH = PROJECT_ROOT / "HSReplay_Card_Rankings.xlsx"

# ── 数据文件路径 ─────────────────────────────────────
UNIFIED_DB_PATH = DATA_DIR / "unified_standard.json"
V2_CURVE_PARAMS_PATH = DATA_DIR / "v2_curve_params.json"
V2_KEYWORD_PARAMS_PATH = DATA_DIR / "v2_keyword_params.json"
V2_REPORT_PATH = DATA_DIR / "v2_scoring_report.json"
V7_REPORT_PATH = DATA_DIR / "v7_scoring_report.json"
HSREPLAY_CACHE_DB = DATA_DIR / "hsreplay_cache.db"
CARD_LIST_PATH = DATA_DIR / "card_list.json"

# ── API 配置 ─────────────────────────────────────────
HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")
HSREPLAY_CARDS_URL = "https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD"
HSREPLAY_ARCHETYPES_URL = "https://hsreplay.net/api/v1/archetypes/"
HSJSON_API_BASE = "https://api.hearthstonejson.com/v1/latest/zhCN/"

# ── 缓存配置 ─────────────────────────────────────────
CACHE_DAYS = 30

# ── 评分参数默认值 ─────────────────────────────────────
DEFAULT_CURVE_P0 = [3.0, 0.7, 0.0]
DEFAULT_CURVE_BOUNDS = ([0.1, 0.3, -5.0], [10.0, 1.5, 10.0])
DEFAULT_CLASS_MULTIPLIER = {
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
    """确保数据目录存在."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_api_headers() -> dict:
    """获取 HSReplay API 请求头."""
    return {
        "X-Api-Key": HSREPLAY_API_KEY,
        "User-Agent": "HSAnalysis/1.0 (educational research)",
        "Accept": "application/json",
    }

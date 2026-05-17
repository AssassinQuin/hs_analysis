# -*- coding: utf-8 -*-
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# ── Data source ──────────────────────────────────────────────────────────
DATA_BUILD = os.environ.get("HS_DATA_BUILD", "241958")
DATA_DIR = PROJECT_ROOT / "card_data" / DATA_BUILD

COLLECTIBLE_JSON = DATA_DIR / "zhCN" / "cards.collectible.json"
UNIFIED_DB_PATH = DATA_DIR / "unified_standard.json"
ENUMS_PATH = PROJECT_ROOT / "hearthstone_enums.json"
RANKINGS_PATH = PROJECT_ROOT / "HSReplay_Card_Rankings.xlsx"

CURVE_PARAMS_PATH = DATA_DIR / "curve_params.json"
SCORING_REPORT_PATH = DATA_DIR / "scoring_report.json"
HSREPLAY_CACHE_DB = DATA_DIR / "hsreplay_cache.db"
CARD_LIST_PATH = DATA_DIR / "card_list.json"

# ── External APIs ────────────────────────────────────────────────────────
HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")
HSREPLAY_CARDS_URL = "https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD"
HSREPLAY_ARCHETYPES_URL = "https://hsreplay.net/api/v1/archetypes/"
HSJSON_API_BASE = "https://api.hearthstonejson.com/v1/latest/zhCN/"
CACHE_DAYS = 30

# ── Class scoring weights ────────────────────────────────────────────────
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

# ── RHEA search engine defaults ──────────────────────────────────────────
RHEA_DEFAULT_POP_SIZE = 50
RHEA_DEFAULT_MAX_GENS = 200
RHEA_DEFAULT_CHROMOSOME_LEN = 6

RHEA_TIME_BUDGET_NORMAL_MS = 3000.0
RHEA_TIME_BUDGET_HARD_MS = 15000.0
RHEA_COMPLEXITY_THRESHOLD = 35

RHEA_TIME_ALLOCATION = {
    "utp": 0.10,
    "rhea": 0.50,
    "phase_b": 0.10,
    "opp_sim": 0.10,
    "cross_turn": 0.20,
}

# ── Phase params ─────────────────────────────────────────────────────────
PHASE_PARAMS = {
    "early": {"pop_size": 30, "max_gens": 100, "max_chromosome_length": 4},
    "mid": {"pop_size": 50, "max_gens": 200, "max_chromosome_length": 5},
    "late": {"pop_size": 60, "max_gens": 150, "max_chromosome_length": 6},
}

# ── Watcher config (loaded from cfg/live.cfg at runtime) ────────────────
# Default: False for backward compatibility. Production cfg sets True.
LATEST_GAME_ONLY = False


def load_live_config(cfg_path: str | Path | None = None) -> dict:
    """Load live.cfg and return parsed ConfigParser. Also sets module-level
    LATEST_GAME_ONLY from the [watcher] section.

    Args:
        cfg_path: Path to config file. Defaults to cfg/live.cfg under PROJECT_ROOT.

    Returns:
        Dict with parsed config values for convenience.
    """
    import configparser

    global LATEST_GAME_ONLY

    if cfg_path is None:
        cfg_path = PROJECT_ROOT / "cfg" / "live.cfg"
    cfg_path = Path(cfg_path)

    cp = configparser.ConfigParser(interpolation=None)
    cfg_loaded = False
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as f:
                cp.read_file(f)
            cfg_loaded = True
        except Exception:
            pass

    if cfg_loaded:
        LATEST_GAME_ONLY = cp.getboolean("watcher", "latest_game_only", fallback=False)

    return {
        "config_parser": cp,
        "cfg_loaded": cfg_loaded,
        "latest_game_only": LATEST_GAME_ONLY,
    }


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def get_api_headers() -> dict:
    return {
        "X-Api-Key": HSREPLAY_API_KEY,
        "User-Agent": "HSAnalysis/1.0 (educational research)",
        "Accept": "application/json",
    }

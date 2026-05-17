#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_deck_codes.py — 从 HSReplay.net 自动获取最新标准环境 Meta 卡组代码

功能：
  1. 抓取 https://hsreplay.net/decks/ 列表页，获取热门卡组 ID 和名称
  2. 逐个访问卡组详情页，提取 <meta property="x-hearthstone:deck:deckstring"> 中的卡组代码
  3. 生成格式化的 deck_codes.txt，保持与现有格式兼容
  4. 支持增量更新：保留旧版卡组，新卡组追加到顶部
  5. 可通过 CLI 独立运行，也可由启动脚本调用

使用方式：
  python scripts/update_deck_codes.py                    # 更新卡组代码
  python scripts/update_deck_codes.py --dry-run          # 仅预览，不写文件
  python scripts/update_deck_codes.py --max-decks 30     # 最多获取 N 个卡组
  python scripts/update_deck_codes.py --no-backup        # 不备份旧文件

数据获取策略：
  - 使用 z-ai-web-dev-sdk 的 page_reader 功能获取页面内容（绕过 Cloudflare）
  - 如果 z-ai SDK 不可用，回退到 requests + cloudscraper
  - 网络失败时保留现有文件不变
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 日志 ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("update_deck_codes")

# ── 常量 ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECK_CODES_PATH = PROJECT_ROOT / "deck_codes.txt"

HSREPLAY_DECKS_URL = "https://hsreplay.net/decks/"
HSREPLAY_DECK_DETAIL_URL = "https://hsreplay.net/decks/{deck_id}/"

# 职业英中映射
CLASS_ZH_MAP = {
    "WARRIOR": "战士",
    "SHAMAN": "萨满",
    "ROGUE": "潜行者",
    "PALADIN": "圣骑士",
    "HUNTER": "猎人",
    "WARLOCK": "术士",
    "MAGE": "法师",
    "PRIEST": "牧师",
    "DRUID": "德鲁伊",
    "DEMONHUNTER": "恶魔猎手",
    "DEATHKNIGHT": "死亡骑士",
}

# 卡组类型映射（基于名称关键词）
ARCHETYPE_KEYWORDS = {
    "aggro": "aggro",
    "face": "aggro",
    "zoo": "aggro",
    "rush": "aggro",
    "murloc": "aggro",
    "control": "control",
    "reno": "control",
    "highlander": "control",
    "odd": "tempo",
    "even": "tempo",
    "tempo": "tempo",
    "spell": "tempo",
    "midrange": "midrange",
    "dragon": "midrange",
    "hand": "midrange",
    "menagerie": "midrange",
    "miracle": "combo",
    "quest": "combo",
    "combo": "combo",
    "malygos": "combo",
    "otk": "combo",
    "imbue": "combo",
    "plague": "combo",
    "herald": "midrange",
    "bubble": "aggro",
    "companion": "aggro",
    "token": "midrange",
    "miracle": "combo",
    "mill": "control",
}


def guess_archetype(deck_name: str) -> str:
    """根据卡组名称猜测类型。"""
    name_lower = deck_name.lower()
    for keyword, arch in ARCHETYPE_KEYWORDS.items():
        if keyword in name_lower:
            return arch
    return "midrange"  # 默认


# ── 页面获取 ──────────────────────────────────────────────────────


def _fetch_via_zai_sdk(url: str) -> Optional[str]:
    """使用 z-ai-web-dev-sdk 的 page_reader 获取页面 HTML。

    通过 CLI 工具调用，避免在 Python 中导入 Node.js SDK。
    """
    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "z_ai_cli",
                "function", "-n", "page_reader",
                "-a", json.dumps({"url": url}),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            # 尝试直接用 z-ai CLI
            result = subprocess.run(
                [
                    "z-ai", "function",
                    "-n", "page_reader",
                    "-a", json.dumps({"url": url}),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip())
            html = data.get("data", {}).get("html", "")
            if html and len(html) > 1000:
                return html
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    # 回退：直接调用 z-ai function 并输出到临时文件
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
            tmp_path = tmp.name

        result = subprocess.run(
            [
                "z-ai", "function",
                "-n", "page_reader",
                "-a", json.dumps({"url": url}),
                "-o", tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and os.path.exists(tmp_path):
            with open(tmp_path, "r") as f:
                data = json.load(f)
            os.unlink(tmp_path)
            html = data.get("data", {}).get("html", "")
            if html and len(html) > 1000:
                return html
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass

    return None


def _fetch_via_requests(url: str) -> Optional[str]:
    """使用 requests + cloudscraper 获取页面 HTML（回退方案）。"""
    try:
        import cloudscraper
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp.text
    except ImportError:
        pass
    except Exception as e:
        log.debug("cloudscraper 获取失败: %s", e)

    # 纯 requests 尝试
    try:
        import requests
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 1000:
            return resp.text
    except Exception as e:
        log.debug("requests 获取失败: %s", e)

    return None


def fetch_page(url: str) -> Optional[str]:
    """获取页面 HTML，依次尝试多种方式。"""
    log.info("获取页面: %s", url)

    # 方式 1: z-ai SDK (能绕过 Cloudflare)
    html = _fetch_via_zai_sdk(url)
    if html:
        log.info("  ✓ z-ai SDK 获取成功 (%d 字符)", len(html))
        return html

    # 方式 2: requests/cloudscraper
    html = _fetch_via_requests(url)
    if html:
        log.info("  ✓ requests 获取成功 (%d 字符)", len(html))
        return html

    log.warning("  ✗ 所有获取方式均失败: %s", url)
    return None


# ── HTML 解析 ──────────────────────────────────────────────────────


def parse_deck_list(html: str) -> List[Tuple[str, str]]:
    """从 HSReplay 卡组列表页解析卡组 ID 和名称。

    Returns:
        [(deck_id, deck_name), ...] 去重后的列表
    """
    # 匹配 /decks/DECK_ID/ 后面跟着的 deck-name
    # 注意：同一 deck_id 可能出现在不同 tab 中，需要按出现顺序去重
    pattern = re.compile(
        r'/decks/([a-zA-Z0-9]{20,})/.*?id="deck-name"[^>]*>([^<]+)<',
        re.DOTALL,
    )
    matches = pattern.findall(html)

    seen_ids = set()
    result = []
    for deck_id, name in matches:
        if deck_id not in seen_ids:
            seen_ids.add(deck_id)
            result.append((deck_id, name.strip()))

    return result


def parse_deck_detail(html: str) -> Optional[str]:
    """从 HSReplay 卡组详情页解析卡组代码。

    查找 <meta property="x-hearthstone:deck:deckstring" content="AAECA...">
    """
    # 方式 1: 标准属性顺序
    match = re.search(
        r'x-hearthstone:deck:deckstring[^>]*content="([^"]+)"',
        html,
    )
    if match:
        return match.group(1).strip()

    # 方式 2: 反向属性顺序
    match = re.search(
        r'content="(AAECA[A-Za-z0-9+/=]+)"[^>]*x-hearthstone:deck:deckstring',
        html,
    )
    if match:
        return match.group(1).strip()

    # 方式 3: 任何包含 AAECA 的 content 属性（最宽松）
    match = re.search(r'content="(AAECA[A-Za-z0-9+/=]{30,})"', html)
    if match:
        return match.group(1).strip()

    return None


def parse_deck_class_from_detail(html: str) -> Optional[str]:
    """从详情页 HTML 解析卡组职业（英文名）。"""
    # 查找卡组详情页中的职业信息
    # 通常在页面中有 class="card-class" 或类似的标记
    match = re.search(r'data-card-class="([A-Z]+)"', html)
    if match:
        return match.group(1)

    # 回退：从 meta 标签或页面标题推断
    match = re.search(r'class-name["\s:]+([A-Z]+)', html, re.I)
    if match:
        return match.group(1).upper()

    return None


# ── 卡组代码解码 ──────────────────────────────────────────────────


def decode_deck_class(deckstring: str) -> Optional[str]:
    """从卡组代码解码出职业（使用 hearthstone.deckstrings）。"""
    try:
        from hearthstone.deckstrings import Deck
        deck = Deck.from_deckstring(deckstring)
        hero_dbf_id = deck.heroes[0] if deck.heroes else 0

        # 映射 hero dbfId → class
        from analysis.data.hsdb import get_hero_class_map
        hero_map = get_hero_class_map()
        if hero_dbf_id in hero_map:
            return hero_map[hero_dbf_id]
    except Exception:
        pass
    return None


# ── deck_codes.txt 读写 ──────────────────────────────────────────


def parse_existing_deck_codes(path: Path) -> List[Tuple[str, str, str]]:
    """解析现有的 deck_codes.txt 文件。

    Returns:
        [(name, arch, deckstring), ...]
    """
    if not path.exists():
        return []

    decks = []
    current_name = ""
    current_arch = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            # 尝试解析 # name: XXX | arch: YYY
            m = re.match(r"#\s*name:\s*(.+?)\s*\|\s*arch:\s*(\w+)", line)
            if m:
                current_name = m.group(1).strip()
                current_arch = m.group(2).strip()
            continue

        # 以 AAECA 开头的行是卡组代码
        if line.startswith("AAECA"):
            decks.append((current_name, current_arch, line))
            current_name = ""
            current_arch = ""

    return decks


def format_deck_codes_txt(
    new_decks: List[Tuple[str, str, str]],
    old_decks: List[Tuple[str, str, str]],
) -> str:
    """生成 deck_codes.txt 文件内容。

    新卡组放在顶部，旧卡组追加在底部（标记为旧版）。
    """
    lines = [
        "# deck_codes.txt — 对手卡组代码库",
        "#",
        "# 格式说明:",
        "#   1. 注释行以 # 开头",
        "#   2. 在卡组代码前可用注释指定名称和类型:",
        '#      # name: 卡组名称 | arch: aggro/control/midrange/tempo/combo',
        "#   3. 未标注的卡组将自动根据费用曲线分类",
        "#   4. 对局中修改此文件会自动热更新（无需重启）",
        "#",
        "# 支持热更新：对局中可随时添加/修改卡组，保存后自动生效",
        "#",
        f"# 更新日期: {datetime.now().strftime('%Y-%m-%d')} — 自动从 HSReplay.net 获取",
        "",
    ]

    # 新卡组
    if new_decks:
        lines.append("# " + "═" * 60)
        lines.append(f"# 最新 Meta 卡组（{datetime.now().strftime('%Y-%m-%d')} 更新）")
        lines.append("# " + "═" * 60)
        lines.append("")

        for name, arch, deckstring in new_decks:
            if name:
                lines.append(f"# name: {name} | arch: {arch}")
            lines.append(deckstring)
            lines.append("")

    # 旧卡组（去重：如果 deckstring 在新卡组中已存在则跳过）
    new_strings = {ds for _, _, ds in new_decks}
    old_unique = [(n, a, ds) for n, a, ds in old_decks if ds not in new_strings]

    if old_unique:
        lines.append("# " + "═" * 60)
        lines.append("# 历史卡组（旧版保留）")
        lines.append("# " + "═" * 60)
        lines.append("")

        for name, arch, deckstring in old_unique:
            display_name = f"{name}(旧)" if name and not name.endswith("(旧)") else name
            if display_name:
                lines.append(f"# name: {display_name} | arch: {arch}")
            lines.append(deckstring)
            lines.append("")

    return "\n".join(lines)


# ── 主流程 ──────────────────────────────────────────────────────


def update_deck_codes(
    max_decks: int = 25,
    dry_run: bool = False,
    backup: bool = True,
) -> bool:
    """从 HSReplay 获取最新卡组代码并更新 deck_codes.txt。

    Args:
        max_decks: 最多获取的卡组数量
        dry_run: 仅预览，不写文件
        backup: 是否备份旧文件

    Returns:
        True 如果成功更新
    """
    log.info("=== 开始更新卡组代码 ===")

    # 1. 获取列表页
    list_html = fetch_page(HSREPLAY_DECKS_URL)
    if not list_html:
        log.error("无法获取 HSReplay 卡组列表页，跳过更新")
        return False

    deck_list = parse_deck_list(list_html)
    if not deck_list:
        log.error("列表页未解析到任何卡组，跳过更新")
        return False

    log.info("列表页解析到 %d 个卡组，将获取前 %d 个", len(deck_list), max_decks)
    deck_list = deck_list[:max_decks]

    # 2. 逐个获取详情页并提取卡组代码
    new_decks: List[Tuple[str, str, str]] = []
    failed = 0

    for i, (deck_id, deck_name) in enumerate(deck_list):
        detail_url = HSREPLAY_DECK_DETAIL_URL.format(deck_id=deck_id)
        log.info("[%d/%d] 获取: %s (%s)", i + 1, len(deck_list), deck_name, deck_id)

        detail_html = fetch_page(detail_url)
        if not detail_html:
            log.warning("  ✗ 获取详情页失败，跳过")
            failed += 1
            continue

        deckstring = parse_deck_detail(detail_html)
        if not deckstring:
            log.warning("  ✗ 未找到卡组代码，跳过")
            failed += 1
            continue

        # 确定职业
        deck_class = parse_deck_class_from_detail(detail_html)
        if not deck_class:
            deck_class = decode_deck_class(deckstring)

        # 构建卡组名称
        class_zh = CLASS_ZH_MAP.get(deck_class, "") if deck_class else ""
        if class_zh and class_zh not in deck_name:
            full_name = f"{class_zh}{deck_name}"
        else:
            full_name = deck_name

        arch = guess_archetype(deck_name)
        new_decks.append((full_name, arch, deckstring))
        log.info("  ✓ %s [%s] → %s...", full_name, arch, deckstring[:40])

        # 避免请求过快
        if i < len(deck_list) - 1:
            time.sleep(0.5)

    if not new_decks:
        log.error("未获取到任何有效卡组代码")
        return False

    log.info("成功获取 %d 个卡组代码（失败 %d 个）", len(new_decks), failed)

    # 3. 读取现有文件
    old_decks = parse_existing_deck_codes(DECK_CODES_PATH)
    log.info("现有 deck_codes.txt 中有 %d 个卡组", len(old_decks))

    # 4. 生成新文件内容
    content = format_deck_codes_txt(new_decks, old_decks)

    if dry_run:
        log.info("=== 预览模式，不写入文件 ===")
        print(content[:2000])
        if len(content) > 2000:
            print(f"... (共 {len(content)} 字符)")
        return True

    # 5. 备份旧文件
    if backup and DECK_CODES_PATH.exists():
        backup_path = DECK_CODES_PATH.with_suffix(
            f".bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        )
        shutil.copy2(DECK_CODES_PATH, backup_path)
        log.info("已备份到: %s", backup_path)

    # 6. 写入新文件
    DECK_CODES_PATH.write_text(content, encoding="utf-8")
    log.info("已更新: %s（%d 个新卡组，%d 个旧卡组保留）",
             DECK_CODES_PATH, len(new_decks), len(old_decks))

    return True


# ── CLI ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="从 HSReplay.net 自动获取最新标准环境卡组代码",
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="仅预览，不写文件",
    )
    parser.add_argument(
        "--max-decks", "-m",
        type=int,
        default=25,
        help="最多获取的卡组数量（默认 25）",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="不备份旧文件",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    success = update_deck_codes(
        max_decks=args.max_decks,
        dry_run=args.dry_run,
        backup=not args.no_backup,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

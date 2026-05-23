#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
expand_deck_codes.py — 解码并补全 deck_codes.txt 中的套牌信息

功能:
  1. 读取 deck_codes.txt 中所有卡组代码
  2. 解码为完整卡牌列表（职业、卡名、费用、类型等）
  3. 每张卡计算"手牌留存度"——该卡在前期对手手中的可能概率
  4. 输出:
     a. deck_codes.txt — 添加 # class: 职业 和 # retain_cards: 高留存卡牌 注释
     b. analysis/data/deck_library.json — 结构化数据，供世界追踪器冷启动使用

用法:
    python scripts/expand_deck_codes.py                    # 写入 deck_library.json + 更新 deck_codes.txt
    python scripts/expand_deck_codes.py --json-only        # 只写 JSON，不修改 deck_codes.txt
    python scripts/expand_deck_codes.py --print-all        # 按职业打印所有套牌卡牌
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 确保项目根目录在 sys.path 上
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("expand_deck_codes")

DECK_CODES_PATH = _PROJECT_ROOT / "deck_codes.txt"
DECK_LIBRARY_PATH = _PROJECT_ROOT / "analysis" / "data" / "deck_library.json"

# ── Archetype → hand retention modifiers ──────────────────────
# 不同风格的卡组中，卡牌留手倾向不同
ARCHETYPE_RETENTION_MOD: Dict[str, int] = {
    "control": 25,    # 控制卡组：高费牌留手，等着解场
    "midrange": 10,   # 中速：费用适中，部分留手
    "tempo": 0,       # 节奏：按费出牌，留手少
    "aggro": -20,     # 快攻：1-2费全打出去
    "combo": 20,      # 组合技：关键组件留手
}

CARD_TYPE_RETENTION_MOD: Dict[str, int] = {
    "SPELL": 12,      # 法术很多是解牌，留手
    "MINION": -5,     # 随从按费下
    "LOCATION": 5,    # 场地看时机下
    "WEAPON": 5,      # 武器看时机挂
    "HERO": 0,
}

RARITY_RETENTION_MOD: Dict[str, int] = {
    "LEGENDARY": 10,  # 关键张，等时机
    "EPIC": 5,
    "RARE": 0,
    "COMMON": -5,
    "FREE": -10,
}

# 职业英中映射（用于文件注释）
CLASS_ZH_MAP = {
    "WARRIOR": "战士", "SHAMAN": "萨满", "ROGUE": "盗贼",
    "PALADIN": "圣骑士", "HUNTER": "猎人", "WARLOCK": "术士",
    "MAGE": "法师", "PRIEST": "牧师", "DRUID": "德鲁伊",
    "DEMONHUNTER": "恶魔猎手", "DEATHKNIGHT": "死亡骑士",
}

# ── 数据结构 ──────────────────────────────────────────────────


@dataclass
class CardEntry:
    """解码后的单张卡牌"""
    card_id: str
    name: str
    cost: int
    card_type: str
    rarity: str
    card_class: str
    count: int
    retention_score: float = 0.0  # 手牌留存度：高=更可能在手里


@dataclass
class DeckEntry:
    """解码后的完整卡组"""
    name: str
    archetype: str
    code: str
    hero_class: str
    hero_class_cn: str
    cards: List[CardEntry] = field(default_factory=list)
    card_count: int = 0

    @property
    def sorted_by_retention(self) -> List[CardEntry]:
        """按留存度降序排列的卡牌列表"""
        return sorted(self.cards, key=lambda c: (-c.retention_score, -c.cost, c.name))


def compute_retention_score(card: CardEntry, archetype: str) -> float:
    """计算单张卡牌的手牌留存度。

    留存度表示这张卡在对手手中（而非已被打出）的倾向性。
    越高越可能还在手里。

    主要因子:
      - 费用: 高费卡在前中期无法打出，自然留手
      - 卡组风格: 控制留高费，快攻打低费
      - 卡牌类型: 法术/解牌多留手，随从多打出
      - 稀有度: 关键张多留手
    """
    score = card.cost * 10.0  # 费用越高越可能留手

    # 卡组风格修饰
    score += ARCHETYPE_RETENTION_MOD.get(archetype, 0)

    # 卡牌类型修饰
    score += CARD_TYPE_RETENTION_MOD.get(card.card_type, 0)

    # 稀有度修饰
    score += RARITY_RETENTION_MOD.get(card.rarity, 0)

    # 职业卡修饰（通常是卡组核心）
    if card.card_class != "NEUTRAL":
        score += 5

    return round(score, 1)


# ── 解析 deck_codes.txt ──────────────────────────────────────


def parse_deck_codes(path: Path) -> List[Tuple[str, str, str]]:
    """解析 deck_codes.txt，返回 [(name, archetype, deckstring)]。

    支持两种名称格式:
      - # name: XXX | arch: YYY   (expand_deck_codes 生成的注释格式)
      - ### XXX                    (炉石导出格式)
    """
    if not path.exists():
        log.error("文件不存在: %s", path)
        return []

    decks: List[Tuple[str, str, str]] = []
    current_name = ""
    current_arch = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            m = re.match(r"#\s*name:\s*(.+?)\s*\|\s*arch:\s*(\w+)", line)
            if m:
                current_name = m.group(1).strip()
                current_arch = m.group(2).strip()
            else:
                m2 = re.match(r"^###\s+(.+)", line)
                if m2:
                    current_name = m2.group(1).strip()
                    current_arch = ""
            continue

        if line.startswith("AAECA"):
            decks.append((current_name, current_arch, line))
            current_name = ""
            current_arch = ""

    return decks


# ── 解码卡组 ──────────────────────────────────────────────────


def decode_deck(name: str, archetype: str, code: str) -> Optional[DeckEntry]:
    """解码一个卡组代码为完整卡牌列表。"""
    from analysis.models.game_record import DeckInfo

    try:
        info = DeckInfo.from_deck_code(name, "", code)
    except Exception as e:
        log.warning("解码失败 [%s]: %s", name or code[:30], e)
        return None

    if not info.cards:
        log.warning("解码结果为空 [%s]", name or code[:30])
        return None

    cards: List[CardEntry] = []
    card_map: Dict[str, CardEntry] = {}

    for dc in info.cards:
        # 展开 count（每张卡可能 2 张）
        for _ in range(dc.count):
            card_id = dc.card_id or f"dbf:{dc.cost}"
            if card_id in card_map:
                card_map[card_id].count += 1
                continue
            entry = CardEntry(
                card_id=card_id,
                name=dc.name or card_id,
                cost=dc.cost,
                card_type=dc.card_type or "UNKNOWN",
                rarity=dc.rarity or "",
                card_class=dc.cardClass or "",
                count=1,
            )
            card_map[card_id] = entry
            cards.append(entry)

    # 计算留存度
    for card in cards:
        card.retention_score = compute_retention_score(card, archetype)

    return DeckEntry(
        name=name,
        archetype=archetype,
        code=code,
        hero_class=info.hero_class,
        hero_class_cn=info.hero_class_cn,
        cards=cards,
        card_count=sum(c.count for c in cards),
    )


# ── 输出：deck_library.json ──────────────────────────────────


def decks_to_library(entries: List[DeckEntry]) -> dict:
    """将解码后的卡组组织成按职业索引的库。

    输出结构:
    {
      "WARRIOR": {
        "zh": "战士",
        "decks": [
          {
            "name": "Control Warrior",
            "archetype": "control",
            "all_cards": [...],
            "high_retention": [...],   # 留存度 >= 30 的卡牌（最可能在手中）
            "medium_retention": [...], # 留存度 10-29
          }
        ],
        "all_cards": [...],  # 该职业所有卡组的并集卡牌（去重）
        "common_high_retention": [...]  # 多套共有的高留存卡
      }
    }
    """
    library: dict = defaultdict(lambda: {
        "zh": "",
        "decks": [],
        "all_cards": [],
        "common_high_retention": [],
    })

    for entry in entries:
        cls = entry.hero_class
        if not cls or cls in ("ERROR", "UNKNOWN"):
            continue

        # 转成可序列化格式
        deck_data = {
            "name": entry.name,
            "archetype": entry.archetype,
            "code": entry.code,
            "card_count": entry.card_count,
            "all_cards": [asdict(c) for c in entry.cards],
            "high_retention": [
                asdict(c) for c in entry.cards if c.retention_score >= 30
            ],
            "medium_retention": [
                asdict(c) for c in entry.cards if 10 <= c.retention_score < 30
            ],
        }
        library[cls]["zh"] = entry.hero_class_cn
        library[cls]["decks"].append(deck_data)

        # 构建该职业所有卡牌的并集（去重：按 card_id）
        seen_ids = {c["card_id"] for c in library[cls]["all_cards"]}
        for c in deck_data["all_cards"]:
            if c["card_id"] not in seen_ids:
                seen_ids.add(c["card_id"])
                library[cls]["all_cards"].append(c)

    # 计算每个职业跨卡组共有的高留存卡（出现 >= 50% 卡组的热门留手牌）
    for cls, data in library.items():
        decks = data["decks"]
        n = len(decks)
        if n == 0:
            continue

        # 统计每张卡出现在多少套牌中
        card_freq: Dict[str, int] = defaultdict(int)
        card_info: Dict[str, dict] = {}
        for deck in decks:
            seen = set()
            for c in deck["all_cards"]:
                cid = c["card_id"]
                if cid not in seen:
                    card_freq[cid] += 1
                    seen.add(cid)
                if cid not in card_info:
                    card_info[cid] = c

        # 出现在 50% 以上卡组中的高留存卡
        threshold = max(1, n // 2)
        common_high = []
        for cid, freq in card_freq.items():
            if freq >= threshold:
                info = card_info[cid]
                if info["retention_score"] >= 20:
                    common_high.append(info)
        common_high.sort(key=lambda c: (-c["retention_score"], -c["cost"], c["name"]))
        data["common_high_retention"] = common_high

    return dict(library)


# ── 输出：更新 deck_codes.txt ────────────────────────────────


def format_enriched_txt(entries: List[DeckEntry]) -> str:
    """生成带职业和高留存卡注释的 deck_codes.txt。"""
    lines = [
        "# deck_codes.txt — 对手卡组代码库（含解码信息）",
        "#",
        "# 格式说明:",
        "#   1. 注释行以 # 开头",
        "#   2. 在卡组代码前可用注释指定名称和类型:",
        '#      # name: 卡组名称 | arch: aggro/control/midrange/tempo/combo',
        "#   3. 自动解码后添加:",
        "#      # class: 职业英文名 | class_cn: 职业中文",
        "#      # retain_cards: 高留存卡牌（最可能还在对手手中）",
        "#   4. 对局中修改此文件会自动热更新（无需重启）",
        "#",
        "# 支持热更新：对局中可随时添加/修改卡组，保存后自动生效",
        "",
    ]

    for entry in entries:
        if entry.name:
            arch = entry.archetype or "unknown"
            lines.append(f"# name: {entry.name} | arch: {arch}")
        lines.append(f"# class: {entry.hero_class} | class_cn: {entry.hero_class_cn}")

        # 高留存卡列表（前 10 张）
        high_ret = entry.sorted_by_retention
        if high_ret:
            top_ret = high_ret[:10]
            ret_str = ", ".join(
                f"{c.name}({c.cost}费,留存{c.retention_score:.0f})"
                for c in top_ret
            )
            lines.append(f"# retain_cards: {ret_str}")

        # 所有卡牌列表（紧凑格式）
        lines.append(f"# cards: {' '.join(c.card_id for c in entry.cards)}")
        lines.append(entry.code)
        lines.append("")

    return "\n".join(lines)


# ── 主流程 ──────────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="解码并补全 deck_codes.txt 中的套牌信息",
    )
    parser.add_argument("--json-only", action="store_true",
                        help="只写 deck_library.json，不修改 deck_codes.txt")
    parser.add_argument("--print-all", action="store_true",
                        help="打印所有解码结果到控制台")
    parser.add_argument("--print-class", type=str, default="",
                        help="只打印指定职业的解码结果（如 WARRIOR）")
    args = parser.parse_args()

    # 1. 解析 deck_codes.txt
    raw_decks = parse_deck_codes(DECK_CODES_PATH)
    if not raw_decks:
        log.error("deck_codes.txt 中没有找到卡组代码")
        return 1

    log.info("找到 %d 个卡组代码，开始解码...", len(raw_decks))

    # 2. 逐个解码
    decoded: List[DeckEntry] = []
    failed = 0
    for name, arch, code in raw_decks:
        log.debug("解码: %s", name or code[:30])
        entry = decode_deck(name, arch, code)
        if entry:
            decoded.append(entry)
        else:
            failed += 1

    if not decoded:
        log.error("所有卡组解码失败")
        return 1

    log.info("解码成功: %d 个卡组（失败 %d 个）", len(decoded), failed)

    # 汇总统计
    classes = set(d.hero_class for d in decoded)
    log.info("涉及职业: %s", ", ".join(
        f"{c}({CLASS_ZH_MAP.get(c, c)})" for c in sorted(classes)
    ))

    # 3. 输出 deck_library.json
    library = decks_to_library(decoded)
    DECK_LIBRARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECK_LIBRARY_PATH.write_text(
        json.dumps(library, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("已写入: %s (%d 个职业)", DECK_LIBRARY_PATH, len(library))

    # 按职业统计卡组数
    for cls in sorted(library.keys()):
        data = library[cls]
        n_decks = len(data["decks"])
        common = data["common_high_retention"]
        log.info("  %s: %d 套卡组, %d 张跨卡组高留存卡",
                 cls, n_decks, len(common))

    # 4. 输出更新后的 deck_codes.txt
    if not args.json_only:
        enriched = format_enriched_txt(decoded)
        DECK_CODES_PATH.write_text(enriched, encoding="utf-8")
        log.info("已更新: %s", DECK_CODES_PATH)

    # 5. 打印选项
    if args.print_all:
        _print_all(decoded)
    elif args.print_class:
        _print_class(decoded, args.print_class.upper())

    return 0


def _print_all(entries: List[DeckEntry]):
    """打印所有解码结果。"""
    for entry in entries:
        print(f"\n{'='*60}")
        print(f"卡组: {entry.name or '(无名)'}")
        print(f"职业: {entry.hero_class} ({entry.hero_class_cn})")
        print(f"风格: {entry.archetype}")
        print(f"代码: {entry.code[:40]}...")
        print(f"卡牌 ({entry.card_count}张):")
        for c in entry.sorted_by_retention:
            print(f"  [{c.retention_score:5.0f}] {c.name:<20} {c.cost}费 "
                  f"{c.card_type:<8} {c.rarity:<10}")


def _print_class(entries: List[DeckEntry], cls: str):
    """打印指定职业的解码结果。"""
    filtered = [e for e in entries if e.hero_class == cls]
    if not filtered:
        log.warning("未找到职业 %s 的卡组", cls)
        return
    _print_all(filtered)


if __name__ == "__main__":
    sys.exit(main())

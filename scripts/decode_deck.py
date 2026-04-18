# -*- coding: utf-8 -*-
"""
Hearthstone Deckstring Decoder (Python port of HearthSim/deckstrings)
Plus full deck analysis against our V2 model coverage.
"""
import base64
import json
import sys
import io
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATA_PATH = "D:/code/game/hs_cards/hsjson_standard.json"
CLASSIFICATION_PATH = "D:/code/game/hs_cards/full_classification_report.md"


class VarIntReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("Unexpected end of data")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result


FORMAT_TYPES = {1: "Wild", 2: "Standard", 3: "Classic", 4: "Twist"}


def decode_deckstring(deckstring: str) -> dict:
    raw = base64.b64decode(deckstring)
    reader = VarIntReader(raw)

    header = reader.read_byte()
    if header != 0:
        raise ValueError("Invalid deckstring: header byte must be 0")

    version = reader.read_byte()
    if version != 1:
        raise ValueError(f"Unsupported deckstring version {version}")

    fmt = reader.read_varint()
    if fmt not in FORMAT_TYPES:
        raise ValueError(f"Unknown format type {fmt}")

    num_heroes = reader.read_varint()
    heroes = [reader.read_varint() for _ in range(num_heroes)]
    heroes.sort()

    cards = []
    for count_preset in (1, 2, None):
        n = reader.read_varint()
        for _ in range(n):
            dbf_id = reader.read_varint()
            count = count_preset if count_preset else reader.read_varint()
            cards.append((dbf_id, count))
    cards.sort(key=lambda x: x[0])

    sideboard = []
    has_sb = reader.read_byte()
    if has_sb == 1:
        for count_preset in (1, 2, None):
            n = reader.read_varint()
            for _ in range(n):
                dbf_id = reader.read_varint()
                count = count_preset if count_preset else reader.read_varint()
                owner = reader.read_varint()
                sideboard.append((dbf_id, count, owner))
        sideboard.sort(key=lambda x: (x[2], x[0]))

    return {"cards": cards, "heroes": heroes, "format": fmt, "sideboardCards": sideboard}


def build_dbf_lookup(cards_data):
    lookup = {}
    for card in cards_data:
        dbf_id = card.get("dbfId")
        if dbf_id:
            lookup[dbf_id] = card
    return lookup


def classify_card(card):
    text = card.get("text", "") or ""
    mechanics = card.get("mechanics", [])
    ref_tags = card.get("referencedTags", [])
    all_mechs = set(mechanics + ref_tags)
    card_type = card.get("type", "")
    name = card.get("name", "???")

    tags = []

    if card_type == "MINION":
        tags.append("随从")
    elif card_type == "SPELL":
        tags.append("法术")
    elif card_type == "WEAPON":
        tags.append("武器")
    elif card_type == "LOCATION":
        tags.append("地标")
    elif card_type == "HERO":
        tags.append("英雄牌")

    keyword_map = {
        "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "DISCOVER": "发现",
        "DIVINE_SHIELD": "圣盾", "RUSH": "突袭", "CHARGE": "冲锋",
        "WINDFURY": "风怒", "TAUNT": "嘲讽", "LIFESTEAL": "吸血",
        "STEALTH": "潜行", "SPELLPOWER": "法术伤害", "SECRET": "奥秘",
        "FREEZE": "冻结", "POISONOUS": "剧毒", "SILENCE": "沉默",
        "OVERLOAD": "过载", "COMBO": "连击", "INSPIRE": "激励",
        "AURA": "光环", "TRIGGER_VISUAL": "触发", "COLOSSAL": "巨型",
        "QUEST": "任务", "START_OF_GAME": "开局触发", "ADAPT": "进化",
    }

    for mech in all_mechs:
        if mech in keyword_map:
            tags.append(keyword_map[mech])

    if "亡语" not in tags and ("亡语" in text or "deathrattle" in text.lower()):
        tags.append("亡语(文本)")

    return tags


def map_to_submodels(card, tags):
    text = card.get("text", "") or ""
    card_type = card.get("type", "")
    mechanics = set(card.get("mechanics", []) + card.get("referencedTags", []))
    coverage = {}

    if card_type == "MINION" or card_type == "WEAPON":
        coverage["A_场面状态"] = "场面上随从/武器的原始价值"
    if any(k in mechanics for k in ["CHARGE", "RUSH"]):
        coverage["A_场面状态"] = "冲锋/突袭即时场面影响"
    if "TAUNT" in mechanics:
        coverage["A_场面状态"] = "嘲讽场面控制"
    if card_type == "SPELL":
        coverage["A_场面状态"] = "法术直接场面效果"

    if any(k in mechanics for k in ["DEATHRATTLE"]):
        coverage["D_触发概率"] = "亡语触发EV计算"
    if "BATTLECRY" in mechanics:
        coverage["D_触发概率"] = "战吼确定性触发(概率=1.0)"
    if "SECRET" in mechanics or "奥秘" in tags:
        coverage["C_持续效果"] = "奥秘触发概率+效果"
    if "DISCOVER" in mechanics or "发现" in text:
        coverage["F_卡池"] = "Discover规则+卡池权重"
    if "QUEST" in mechanics or "任务" in tags:
        coverage["E_环境智能"] = "任务线进度+奖励"
    if "AURA" in mechanics:
        coverage["C_持续效果"] = "光环跨回合持续效果"
    if card_type == "LOCATION":
        coverage["A_场面状态"] = "地标激活EV"
        coverage["C_持续效果"] = "地标跨回合使用"

    if "随机" in text or "random" in text.lower():
        coverage["D_触发概率"] = "随机目标/效果EV加权"
    if "召唤" in text:
        coverage["A_场面状态"] = "召唤物场面价值"
        coverage["D_触发概率"] = "随机召唤池EV" if "随机" in text else ""
    if "造成" in text and "伤害" in text:
        coverage["B_对手威胁"] = "直接伤害消除威胁"
    if "消灭" in text:
        coverage["B_对手威胁"] = "消灭高威胁目标"
    if "抽" in text and "牌" in text:
        coverage["A_场面状态"] = "手牌补充"
    if "复制" in text:
        coverage["D_触发概率"] = "复制效果EV"
    if "如果" in text or "condition" in text.lower():
        coverage["D_触发概率"] = "条件触发概率折扣"
    if "抉择" in text:
        coverage["G_玩家选择"] = "抉择EV=max(A,B)"
    if "灌注" in text:
        coverage["D_触发概率"] = "灌注递增EV"
    if "发现" in text or "获取" in text or "生成" in text:
        coverage["F_卡池"] = "卡牌生成池+规则"

    return coverage


def analyze_deck(deckstring):
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    all_cards = raw["cards"] if isinstance(raw, dict) and "cards" in raw else raw

    dbf = build_dbf_lookup(all_cards)
    deck = decode_deckstring(deckstring)

    print("=" * 80)
    print(f"DECK DECODE: Format = {FORMAT_TYPES.get(deck['format'], '?')}")
    print(f"Hero DBF IDs: {deck['heroes']}")
    print(f"Total cards: {sum(c for _, c in deck['cards'])}")
    print("=" * 80)

    hero_names = []
    for h_id in deck["heroes"]:
        c = dbf.get(h_id)
        hero_names.append(c["name"] if c else f"(unknown dbf={h_id})")
    print(f"Heroes: {', '.join(hero_names)}")

    unmatched = []
    all_deck_cards = []

    print(f"\n{'=' * 80}")
    print(f"{'#':>2} | {'Cost':>4} | {'Type':>7} | {'Class':>8} | {'Name':<30} | {'Count':>1} | Submodel Coverage")
    print(f"{'-' * 2} | {'-' * 4} | {'-' * 7} | {'-' * 8} | {'-' * 30} | {'-' * 5} | {'-' * 50}")

    for dbf_id, count in deck["cards"]:
        card = dbf.get(dbf_id)
        if not card:
            unmatched.append((dbf_id, count))
            print(f"?? | {'?':>4} | {'?':>7} | {'?':>8} | dbf={dbf_id:<25} | {count} | NOT IN DATABASE")
            continue

        name = card.get("name", "???")
        cost = card.get("cost", "?")
        ctype = card.get("type", "?")
        cls = card.get("cardClass", "?")
        text = card.get("text", "") or ""
        mechanics = set(card.get("mechanics", []) + card.get("referencedTags", []))

        tags = classify_card(card)
        coverage = map_to_submodels(card, tags)

        covered_models = sorted(set(k.split("_")[0] for k in coverage.keys()))
        coverage_str = ", ".join(covered_models) if covered_models else "⚠ 无覆盖"

        all_deck_cards.append({
            "dbfId": dbf_id,
            "name": name,
            "count": count,
            "cost": cost,
            "type": ctype,
            "class": cls,
            "mechanics": list(mechanics),
            "tags": tags,
            "coverage": coverage,
            "covered_models": covered_models,
        })

        print(f"{len(all_deck_cards):2d} | {str(cost):>4} | {ctype:>7} | {cls:>8} | {name:<30} | {count} | {coverage_str}")

    if deck.get("sideboardCards"):
        print(f"\n--- Sideboard ---")
        for dbf_id, count, owner in deck["sideboardCards"]:
            card = dbf.get(dbf_id)
            name = card["name"] if card else f"dbf={dbf_id}"
            owner_card = dbf.get(owner)
            owner_name = owner_card["name"] if owner_card else f"dbf={owner}"
            print(f"  {name} x{count} (owner: {owner_name})")

    if unmatched:
        print(f"\n⚠ UNMATCHED CARDS ({len(unmatched)}):")
        for dbf_id, count in unmatched:
            print(f"  dbfId={dbf_id} x{count}")

    print(f"\n{'=' * 80}")
    print("SUBMODEL COVERAGE ANALYSIS")
    print(f"{'=' * 80}")

    submodel_names = ["A_场面状态", "B_对手威胁", "C_持续效果", "D_触发概率", "E_环境智能", "F_卡池", "G_玩家选择"]
    submodel_covered = defaultdict(list)
    uncovered_cards = []

    for dc in all_deck_cards:
        if not dc["covered_models"]:
            uncovered_cards.append(dc)
        for model in dc["covered_models"]:
            full_name = next((n for n in submodel_names if n.startswith(model)), model)
            submodel_covered[full_name].append(f"{dc['name']}x{dc['count']}")

    for sm in submodel_names:
        cards_list = submodel_covered.get(sm, [])
        status = f"✅ {len(cards_list)} cards" if cards_list else "— 无直接覆盖"
        print(f"\n  {sm}: {status}")
        for c in sorted(cards_list):
            print(f"    - {c}")

    if uncovered_cards:
        print(f"\n{'=' * 80}")
        print(f"⚠ CARDS WITH NO SUBMODEL COVERAGE ({len(uncovered_cards)}):")
        print(f"{'=' * 80}")
        for dc in uncovered_cards:
            print(f"\n  {dc['name']} x{dc['count']} ({dc['type']}, {dc['cost']}费)")
            print(f"    Tags: {', '.join(dc['tags'])}")
            print(f"    Mechanics: {', '.join(dc['mechanics'])}")

    print(f"\n{'=' * 80}")
    print("V2 MODEL COVERAGE CHECK")
    print(f"{'=' * 80}")

    v2_types = {"MINION", "SPELL", "WEAPON", "LOCATION", "HERO"}
    type_dist = defaultdict(int)
    for dc in all_deck_cards:
        type_dist[dc["type"]] += dc["count"]

    print(f"\n  卡牌类型分布:")
    for t, cnt in sorted(type_dist.items(), key=lambda x: -x[1]):
        in_v2 = "✅ V2已建模" if t in v2_types else "❌ 未建模"
        print(f"    {t}: {cnt} 张 — {in_v2}")

    unique_mechs = set()
    for dc in all_deck_cards:
        unique_mechs.update(dc["mechanics"])

    print(f"\n  关键词总计: {len(unique_mechs)} 种")
    for m in sorted(unique_mechs):
        print(f"    {m}")

    v1_kw_base = {
        "BATTLECRY": 2.0, "DEATHRATTLE": 1.5, "DIVINE_SHIELD": 2.0,
        "RUSH": 1.5, "CHARGE": 2.0, "TAUNT": 1.0, "WINDFURY": 1.5,
        "LIFESTEAL": 1.0, "STEALTH": 1.0, "SPELLPOWER": 1.0,
        "SECRET": 1.0, "FREEZE": 0.5, "POISONOUS": 1.0, "COMBO": 1.0,
        "INSPIRE": 0.5, "AURA": 1.0, "OVERLOAD": -1.0, "DISCOVER": 2.5,
        "TRIGGER_VISUAL": 1.0, "COLOSSAL": 2.0, "QUEST": 3.0,
    }

    unmapped_kw = [m for m in unique_mechs if m not in v1_kw_base]
    if unmapped_kw:
        print(f"\n  ⚠ 未在V1关键词表中注册的关键词 ({len(unmapped_kw)}):")
        for m in unmapped_kw:
            print(f"    {m}")

    total_copies = sum(dc["count"] for dc in all_deck_cards)
    covered_copies = sum(dc["count"] for dc in all_deck_cards if dc["covered_models"])
    print(f"\n  总卡牌数: {total_copies} 张")
    print(f"  子模型覆盖: {covered_copies}/{total_copies} ({covered_copies/total_copies*100:.0f}%)")
    print(f"  无覆盖: {total_copies - covered_copies} 张")

    return all_deck_cards


if __name__ == "__main__":
    deck_code = "AAECAf0EBMODB7OHB6ebB/KyBw2b8gbxkQewmwf6mwfVnQfRpgfLtgf5wweGxAeSxAeT2geG4AecgggAAA=="
    analyze_deck(deck_code)

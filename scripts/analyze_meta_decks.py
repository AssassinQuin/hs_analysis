# -*- coding: utf-8 -*-
"""
Multi-deck analyzer: decode 14 meta decks, check V2 model + submodel coverage.
"""
import base64
import json
import sys
import io
import re
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

DATA_PATH = "D:/code/game/hs_cards/unified_standard.json"
LEGEND_PATH = "D:/code/game/hs_cards/standard_legendaries_analysis.json"


class VarIntReader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def read_byte(self):
        b = self.data[self.pos]
        self.pos += 1
        return b

    def read_varint(self):
        result = shift = 0
        while True:
            b = self.read_byte()
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result


FORMAT_TYPES = {1: "Wild", 2: "Standard", 3: "Classic", 4: "Twist"}


def decode_deckstring(deckstring):
    raw = base64.b64decode(deckstring)
    r = VarIntReader(raw)
    r.read_byte()
    r.read_byte()
    fmt = r.read_varint()
    n_hero = r.read_varint()
    heroes = [r.read_varint() for _ in range(n_hero)]
    cards = []
    for cp in (1, 2, None):
        n = r.read_varint()
        for _ in range(n):
            dbf_id = r.read_varint()
            count = cp if cp else r.read_varint()
            cards.append((dbf_id, count))
    has_sb = r.read_byte() if r.pos < len(r.data) else 0
    sideboard = []
    if has_sb == 1:
        for cp in (1, 2, None):
            n = r.read_varint()
            for _ in range(n):
                dbf_id = r.read_varint()
                count = cp if cp else r.read_varint()
                owner = r.read_varint()
                sideboard.append((dbf_id, count, owner))
    return {"cards": cards, "heroes": heroes, "format": fmt, "sideboardCards": sideboard}


DECKS = {
    "任务法": "AAECAf0EBMODB7OHB6ebB/KyBw2b8gbxkQewmwf6mwfVnQfRpgfLtgf5wweGxAeSxAeT2geG4AecgggAAA==",
    "快攻骑": "AAECAZ8FBM/+BrqWB8avB+XBBw2WoATJoATTngbUngbI/wb1gQeFlQfXlwfOmwf1rwe1wAf2wQeDwgcAAA==",
    "End of Turnadin": "AAECAZ8FCPD+Bsj/BsODB+6oB++oB/CoB+XBB6vGBwvJoAS6lgfLqQfErgf1rwe+sgfiwQfowQfqwQf2wQeDwgcAAA==",
    "Merithra Druid": "AAECAZICCqn1BqGBB5KDB8ODB6+HB6yIB4KYB7iyB+DAB+LABwqunwSIgweqrwesrwfosQe+sgeEvQfXwAfYwAeT8QcAAA==",
    "无随从瞎": "AAECAea5AwaKqgeSqgeTqgensQfAsQeUvwcM4fgF3v8G/oMHqocHtJcHtpcH550HnrEHobEH6LEHkr8Hlb8HAAA=",
    "龙战": "AAECAQcCi6AE9sEHDuPmBqr8Bqv8BuiHB9KXB7etB4+xB9CyB+yyB7XAB5XCB5vCB5zCB/nDBwAA",
    "蛋战": "AAECAQcEtpQH9ZgHn5kH150HDZ+fBIagBI7UBJDUBOPmBsyPB+CdB9WmB/yvB4+xB9CyB7DBB5zCBwAA",
    "任务战": "AAECAQcIn58EqfUG7o8HtpQH1JcHyqsHucMHhMQHC4agBI7UBOiHB4uYB9WmB+qnB/yvB4+xB9iyB7DBB5zCBwAA",
    "Harold Egglock": "AAECAf0GBNGCB/WYB+ybB9edBw2PnwSxnwSRoATnoATTngbrhAepiAeEmQfgnQeTvgfXvgfYvgfgvgcAAA==",
    "邪DK": "AAECAfHhBALtnweOvwcOhfYE1J4G1+UGyIwHupUHopcHvJoH0JsH0q0HhrEH4rEHiL8H/78HtcAHAAA=",
    "BBU Harold DK": "AAECAfHhBAiSgwfDgweCmAf0qgfSrgfQvwfqyQeb1AcLh/YEgf0Gl4IHupUHn54HkasH4rEHj74Hjr8HmsUH0MUHAAA=",
    "Harold Rogue": "AAECAaIHDKGBB5KDB8ODB4KYB+ylB4aoB4eoB4ioB9C/B4rUB5vUB4jZBwn3nwTBlweMrQfZrwe0wQfAwQedxQfVxQfD8gcAAA==",
    "控制牧": "AAECAa0GBqiWB/ypB4CqB4SqB+SyB4O/BwzwnwTLoASg+wbD/waFhge2lAedrQeFvwebvweixAeyxQeW/AcAAA==",
    "空手猎": "AAECAR8EmacHmqcHm6cHhMQHDamfBKqfBNOeBq+SB4WVB86bB+6fB5CnB5inB9SvB7TAB7nAB7vABwAA",
    "任务猎": "AAECAR8GmKAEzZ4GkoMHrIgHqJcHu8AHDKmfBOD4Ba+SB8yWB9yWB96WB9eXB/2bB8iuB/qwB4SxB8GyBwAA",
    "Harold Shaman": "AAECAaoICq+fBP2fBMODB4KYB9umB9+mB+WmB9C/B4LUB5vUBwrmlgf1rAexsAe8sQePvgfDwAfJwAf3wAf2wQfm/QcAAA==",
}

SUBMODELS = ["A_场面状态", "B_对手威胁", "C_持续效果", "D_触发概率", "E_环境智能", "F_卡池", "G_玩家选择"]

V1_KEYWORDS = {
    "BATTLECRY", "DEATHRATTLE", "DISCOVER", "DIVINE_SHIELD", "RUSH", "CHARGE",
    "WINDFURY", "TAUNT", "LIFESTEAL", "STEALTH", "SPELLPOWER", "SECRET",
    "FREEZE", "POISONOUS", "SILENCE", "OVERLOAD", "COMBO", "INSPIRE",
    "AURA", "TRIGGER_VISUAL", "COLOSSAL", "QUEST", "START_OF_GAME", "ADAPT",
}

CN_KEYWORDS = {
    "BATTLECRY": "战吼", "DEATHRATTLE": "亡语", "DISCOVER": "发现",
    "DIVINE_SHIELD": "圣盾", "RUSH": "突袭", "CHARGE": "冲锋",
    "WINDFURY": "风怒", "TAUNT": "嘲讽", "LIFESTEAL": "吸血",
    "STEALTH": "潜行", "SPELLPOWER": "法强", "SECRET": "奥秘",
    "FREEZE": "冻结", "POISONOUS": "剧毒", "SILENCE": "沉默",
    "OVERLOAD": "过载", "COMBO": "连击", "AURA": "光环",
    "TRIGGER_VISUAL": "触发", "COLOSSUS": "巨型", "QUEST": "任务",
    "CHOOSE_ONE": "抉择", "INVOKER": "祈求", "OUTCAST": "流放",
    "TWINSPELL": "双生法术", "MEGA_WINDFURY": "超级风怒",
    "RITUAL": "仪式", "CORRUPT": "腐化", "SPELLBURST": "法术迸发",
    "FRENZY": "暴怒", "HONORABLEKILL": "荣誉消灭",
    "TRADEABLE": "可交易", "FINISH_ATTACK": "终结攻击",
}

PATTERN_EFFECTS = {
    "直接伤害": r"造成\d+点伤害",
    "随机伤害": r"随机.*伤害",
    "抽牌": r"抽.*牌",
    "召唤": r"召唤",
    "Buff": r"\+\d+.*攻击力|获得.*攻击力",
    "消灭": r"消灭",
    "复制": r"复制",
    "生成": r"获取|获得一张|置入",
    "减费": r"法力值消耗.*减少|消耗减少",
    "AOE": r"所有.*(?:随从|敌人|敌方)",
    "治疗": r"恢复|治疗",
    "护甲": r"护甲",
    "条件": r"如果.*(?:则|就|会)",
    "回溯": r"回溯",
    "黑暗之赐": r"黑暗之赐",
    "延系": r"延系",
    "灌注": r"灌注",
    "抉择": r"抉择",
    "任务进度": r"任务[:：]",
    "弃牌": r"弃",
    "发现": r"发现",
}


def classify_effects(text):
    found = []
    for ename, pat in PATTERN_EFFECTS.items():
        if re.search(pat, text):
            found.append(ename)
    return found


def map_submodels(card):
    text = re.sub(r"<[^>]+>", "", card.get("text", "") or "")
    ctype = card.get("type", "")
    mechs = set(card.get("mechanics", []) + card.get("referencedTags", []))
    effects = classify_effects(text)
    covered = set()

    if ctype in ("MINION", "WEAPON", "LOCATION"):
        covered.add("A")
    if ctype == "SPELL":
        covered.add("A")
    if any(k in mechs for k in ("CHARGE", "RUSH")):
        covered.add("A")
    if "TAUNT" in mechs:
        covered.add("A")
    if any(e in effects for e in ("直接伤害", "随机伤害", "消灭", "AOE")):
        covered.add("B")
    if any(k in mechs for k in ("SECRET", "AURA")):
        covered.add("C")
    if ctype == "LOCATION":
        covered.add("C")
    if "回溯" in effects:
        covered.add("C")
    if any(k in mechs for k in ("DEATHRATTLE",)):
        covered.add("D")
    if any(e in effects for e in ("随机伤害", "条件", "黑暗之赐")):
        covered.add("D")
    if "BATTLECRY" in mechs and any(e in effects for e in ("发现", "生成", "召唤")):
        covered.add("D")
    if "QUEST" in mechs or "任务进度" in effects:
        covered.add("E")
    if any(e in effects for e in ("发现", "生成")):
        covered.add("F")
    if "CHOOSE_ONE" in mechs or "抉择" in effects:
        covered.add("G")
    if any(e in effects for e in ("抽牌", "召唤", "Buff", "治疗", "护甲")):
        covered.add("A")
    if "减费" in effects:
        covered.add("A")
    if "弃牌" in effects:
        covered.add("D")
    if "灌注" in effects:
        covered.add("D")
    if not covered:
        covered.add("A")
    return covered


def main():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    all_cards = raw if isinstance(raw, list) else raw.get("cards", raw)
    name_to_card = {}
    dbf_to_card = {}
    for c in all_cards:
        name_to_card[c["name"]] = c
        if c.get("ename"):
            name_to_card[c["ename"]] = c
        if c.get("dbfId"):
            dbf_to_card[c["dbfId"]] = c

    with open(LEGEND_PATH, "r", encoding="utf-8") as f:
        legend_data = json.load(f)
    legend_names = {c["name"] for c in legend_data["legendaries"]}

    all_unique_cards = {}
    all_mechanics = Counter()
    all_effects = Counter()
    all_rarities = Counter()
    all_types = Counter()
    all_uncovered = []
    all_new_keywords = set()
    deck_summaries = []

    for deck_name, deck_code in DECKS.items():
        deck = decode_deckstring(deck_code)
        total = sum(c for _, c in deck["cards"])

        print(f"\n{'#' * 80}")
        print(f"# {deck_name} ({FORMAT_TYPES.get(deck['format'], '?')}, {total}张)")
        print(f"{'#' * 80}")

        cards_info = []
        for dbf_id, count in deck["cards"]:
            card = dbf_to_card.get(dbf_id)
            if not card:
                card = name_to_card.get(str(dbf_id))
            if not card:
                    cards_info.append({
                        "name": f"dbf={dbf_id}", "count": count, "cost": "?",
                        "type": "?", "class": "?", "rarity": "?",
                        "mechanics": [], "effects": [], "submodels": set(),
                        "in_v2": False, "card": None,
                    })
                    continue

            text = re.sub(r"<[^>]+>", "", card.get("text", "") or "")
            mechs = set(card.get("mechanics", []) + card.get("referencedTags", []))
            effects = classify_effects(text)
            submodels = map_submodels(card)
            is_legend = card.get("rarity") == "LEGENDARY"
            in_v2 = is_legend and card["name"] in legend_names

            info = {
                "name": card["name"], "count": count, "cost": card.get("cost", 0),
                "type": card.get("type", "?"), "class": card.get("cardClass", "?"),
                "rarity": card.get("rarity", "?"), "mechanics": mechs,
                "effects": effects, "submodels": submodels, "in_v2": in_v2,
                "card": card,
            }
            cards_info.append(info)

            all_unique_cards[card["name"]] = info
            all_rarities[card.get("rarity", "?")] += count
            all_types[card.get("type", "?")] += count
            for m in mechs:
                all_mechanics[m] += count
            for e in effects:
                all_effects[e] += count
            for m in mechs:
                if m not in V1_KEYWORDS:
                    all_new_keywords.add(m)
            if not submodels:
                all_uncovered.append((deck_name, card["name"]))

        v2_count = sum(c["count"] for c in cards_info if c["in_v2"])
        non_v2 = sum(c["count"] for c in cards_info if not c["in_v2"])
        rarity_dist = Counter()
        for c in cards_info:
            rarity_dist[c["rarity"]] += c["count"]

        print(f"  {'Name':<24s} {'N':>1} {'C':>2} {'Type':>7} {'Rarity':>10} {'V2':>3} | Mech | Effects | Sub")
        print(f"  {'-'*24} {'-':>1} {'-':>2} {'-'*7} {'-'*10} {'-'*3} | {'-'*4} | {'-'*20} | {'-'*6}")
        for c in cards_info:
            mech_list = sorted(c["mechanics"])[:3]
            eff_list = c["effects"][:3]
            mech_cn = ",".join(CN_KEYWORDS.get(m, m)[:2] for m in mech_list)
            eff_str = ",".join(eff_list) or "-"
            sub_str = ",".join(sorted(c["submodels"])) or "-"
            v2_mark = "Y" if c["in_v2"] else "-"
            print(f"  {c['name']:<24s} {c['count']:>1} {c['cost']:>2} {c['type']:>7} {c['rarity']:>10} {v2_mark:>3} | {mech_cn:<4s} | {eff_str:<20s} | {sub_str}")

        deck_summaries.append({
            "name": deck_name,
            "total": total,
            "v2": v2_count,
            "non_v2": non_v2,
            "rarities": dict(rarity_dist),
        })

    print(f"\n{'=' * 80}")
    print(f"全部 {len(DECKS)} 套卡组汇总")
    print(f"{'=' * 80}")

    total_cards = sum(s["total"] for s in deck_summaries)
    total_v2 = sum(s["v2"] for s in deck_summaries)
    total_non_v2 = sum(s["non_v2"] for s in deck_summaries)
    total_unique = len(all_unique_cards)

    print(f"\n  总计: {total_cards} 张 / {total_unique} 种不同卡")
    print(f"  V2模型覆盖: {total_v2} 张 ({total_v2/total_cards*100:.1f}%)")
    print(f"  V2未覆盖:   {total_non_v2} 张 ({total_non_v2/total_cards*100:.1f}%)")

    print(f"\n  === 稀有度分布 ===")
    for r, n in all_rarities.most_common():
        pct = n / total_cards * 100
        bar = "#" * int(pct)
        print(f"    {r:<12s}: {n:4d} ({pct:5.1f}%) {bar}")

    print(f"\n  === 卡牌类型分布 ===")
    for t, n in all_types.most_common():
        print(f"    {t:<10s}: {n:4d} ({n/total_cards*100:.1f}%)")

    print(f"\n  === 关键词频率 TOP 20 ===")
    for m, n in all_mechanics.most_common(20):
        cn = CN_KEYWORDS.get(m, m)
        marker = "NEW" if m not in V1_KEYWORDS else "   "
        print(f"    [{marker}] {m:<20s} ({cn}): {n}")

    print(f"\n  === 文本效果频率 ===")
    for e, n in all_effects.most_common():
        print(f"    {e:<12s}: {n}")

    print(f"\n  === V1关键词表未注册的关键词 ===")
    if all_new_keywords:
        for m in sorted(all_new_keywords):
            cn = CN_KEYWORDS.get(m, "?")
            cnt = all_mechanics.get(m, 0)
            print(f"    {m:<25s} ({cn}): {cnt} 次")
    else:
        print("    (无)")

    print(f"\n  === 未被子模型覆盖的卡牌 ===")
    if all_uncovered:
        for deck, name in all_uncovered:
            print(f"    [{deck}] {name}")
    else:
        print("    (全部覆盖)")

    print(f"\n  === 各卡组V2覆盖详情 ===")
    print(f"  {'Deck':<22s} | {'Total':>5} | {'V2':>3} | {'%':>5} | Rarity Distribution")
    print(f"  {'-'*22} | {'-'*5} | {'-'*3} | {'-'*5} | {'-'*40}")
    for s in deck_summaries:
        pct = s["v2"] / s["total"] * 100 if s["total"] else 0
        rdist = " ".join(f"{k[:3]}:{v}" for k, v in sorted(s["rarities"].items()))
        print(f"  {s['name']:<22s} | {s['total']:>5} | {s['v2']:>3} | {pct:>5.1f} | {rdist}")

    print(f"\n  === 跨卡组高频未建模卡 (出现>=3次) ===")
    card_deck_count = Counter()
    for info in all_unique_cards.values():
        if not info["in_v2"]:
            card_deck_count[info["name"]] += 1
    for name, cnt in card_deck_count.most_common():
        if cnt >= 2:
            info = all_unique_cards[name]
            print(f"    {name} ({info['rarity']}, {info['type']}, {info['cost']}费) — 出现在 {cnt} 套卡组")


if __name__ == "__main__":
    main()

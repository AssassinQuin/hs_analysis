"""
Targeted analysis of specific mechanics the user flagged:
兆示, 角色卡/英雄牌, 注能/灌注, 英雄技能, 武器, 法术特效,
回溯, 发现链(使用后继续发现), 任务, 任务奖励衍生牌
"""
import json
import re
from collections import defaultdict

with open("hs_cards/hsjson_standard.json", "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]

# Also load full collectible for reference (to find reward/derivative cards)
import requests
url = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.collectible.json"
all_cards = requests.get(url, timeout=60).json()
all_map = {c.get("dbfId"): c for c in all_cards if c.get("dbfId")}
id_map = {c.get("id"): c for c in all_cards if c.get("id")}

lines = []
L = lines.append

def clean(text):
    return re.sub(r"<[^>]+>", "", text or "")

def find_cards(pattern, cards_list=None):
    """Find cards matching regex pattern in text."""
    if cards_list is None:
        cards_list = cards
    results = []
    for c in cards_list:
        text = clean(c.get("text", ""))
        name = c.get("name", "")
        if re.search(pattern, text) or re.search(pattern, name):
            results.append(c)
    return results

# ============================================================
# 1. 兆示 (Omen/Forecast/兆示{N})
# ============================================================
L("=" * 60)
L("## 1. 兆示 (Omen — look at top N cards)")
L("=" * 60)
omen_cards = find_cards(r"兆示", cards)
L(f"Standard cards with 兆示: {len(omen_cards)}")
for c in omen_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
L("")

# ============================================================
# 2. 角色卡/英雄牌 (Hero Cards)
# ============================================================
L("=" * 60)
L("## 2. 英雄牌 (Hero Cards — change hero + gain armor + hero power)")
L("=" * 60)
hero_cards = [c for c in cards if c.get("type") == "HERO"]
L(f"Hero cards in standard: {len(hero_cards)}")
for c in hero_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
    # Check if there's a linked hero power
    if c.get("id"):
        hp_id = c["id"].replace("HERO_", "CS2_034h")  # rough guess
    L(f'    mechanics: {c.get("mechanics", [])}')
L("")

# ============================================================
# 3. 注能/灌注 (Imbue — upgrade hero power)
# ============================================================
L("=" * 60)
L("## 3. 注能/灌注 (Imbue — upgrade hero power progressively)")
L("=" * 60)
imbue_cards = [c for c in cards if "IMBUE" in (c.get("mechanics", []) or []) or "注能" in clean(c.get("text", ""))]
L(f"Cards with 注能/Imbue: {len(imbue_cards)}")
for c in imbue_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
    L(f'    mechanics: {c.get("mechanics", [])}')
L("")

# ============================================================
# 4. 英雄技能相关 (Hero Power related)
# ============================================================
L("=" * 60)
L("## 4. 英雄技能相关 (Hero Power modifications)")
L("=" * 60)
hp_cards = find_cards(r"英雄技能|英雄力量", cards)
L(f"Cards referencing hero power: {len(hp_cards)}")
for c in hp_cards[:20]:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:150]}')
if len(hp_cards) > 20:
    L(f"  ... and {len(hp_cards) - 20} more")
L("")

# ============================================================
# 5. 武器 (Weapon cards)
# ============================================================
L("=" * 60)
L("## 5. 武器 (Weapons)")
L("=" * 60)
weapons = [c for c in cards if c.get("type") == "WEAPON"]
L(f"Weapon cards: {len(weapons)}")
for c in weapons:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("attack","?")}atk | {c.get("durability","?")}dur | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:150]}')
L("")

# ============================================================
# 6. 回溯 (Rewind — TIME_TRAVEL specific mechanic)
# ============================================================
L("=" * 60)
L("## 6. 回溯 (Rewind — TIME_TRAVEL set mechanic)")
L("=" * 60)
rewind_cards = find_cards(r"回溯", cards)
L(f"Cards with 回溯: {len(rewind_cards)}")
for c in rewind_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
L("")

# ============================================================
# 7. 发现链 (Discover then if played, discover again)
# ============================================================
L("=" * 60)
L("## 7. 发现链 (Discover → play it → discover again)")
L("=" * 60)
chain_cards = find_cards(r"发现.*如果.*使用|如果.*使用.*发现|使用该牌.*发现|再从其余选项", cards)
L(f"Cards with discover chains: {len(chain_cards)}")
for c in chain_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:250]}')
L("")

# ============================================================
# 8. 任务 + 任务奖励 (Quest + Reward cards)
# ============================================================
L("=" * 60)
L("## 8. 任务 + 任务奖励衍生牌 (Quest + Reward derivative cards)")
L("=" * 60)
quest_cards = find_cards(r"任务", cards)
L(f"Quest cards: {len(quest_cards)}")
for c in quest_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:250]}')
    # Find referenced reward card
    text = clean(c.get("text", ""))
    reward_match = re.search(r"奖励[：:](.*?)(?:[。.]|$)", text)
    if reward_match:
        reward_name = reward_match.group(1).strip()
        L(f'    → Reward: {reward_name}')
        # Try to find in all cards
        for ac in all_cards:
            if ac.get("name") == reward_name:
                L(f'      Found: {ac["id"]} | {ac.get("type","?")} | {clean(ac.get("text",""))[:150]}')
                break
L("")

# ============================================================
# 9. 地标 (Location cards — detailed)
# ============================================================
L("=" * 60)
L("## 9. 地标 (Locations — with charges/cooldown)")
L("=" * 60)
locations = [c for c in cards if c.get("type") == "LOCATION"]
L(f"Location cards: {len(locations)}")
for c in locations:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
L("")

# ============================================================
# 10. 裂变 (Fission/Split — card has two modes)
# ============================================================
L("=" * 60)
L("## 10. 裂变 (Fission — card splits into two versions)")
L("=" * 60)
fission_cards = find_cards(r"裂变", cards)
L(f"Cards with 裂变: {len(fission_cards)}")
for c in fission_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:300]}')
L("")

# ============================================================
# 11. 延系 (Lineage/延系)
# ============================================================
L("=" * 60)
L("## 11. 延系 (Lineage — bonus if played after another)")
L("=" * 60)
lineage_cards = find_cards(r"延系", cards)
L(f"Cards with 延系: {len(lineage_cards)}")
for c in lineage_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
L("")

# ============================================================
# 12. 星舰 (Starship)
# ============================================================
L("=" * 60)
L("## 12. 星舰 (Starship — accumulate pieces then launch)")
L("=" * 60)
starship_cards = [c for c in cards if "STARSHIP" in str(c.get("mechanics", [])) or "星舰" in clean(c.get("text", ""))]
L(f"Cards with 星舰: {len(starship_cards)}")
for c in starship_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {c.get("type","?")} | {c.get("set","?")}')
    L(f'    {clean(c.get("text",""))[:200]}')
L("")

# ============================================================
# 13. 巨型 (Colossal — with appendages)
# ============================================================
L("=" * 60)
L("## 13. 巨型 (Colossal — main body + appendages)")
L("=" * 60)
colossal_cards = [c for c in cards if "COLOSSAL" in (c.get("mechanics", []) or [])]
L(f"Colossal cards: {len(colossal_cards)}")
for c in colossal_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("attack","?")}/{c.get("health","?")} | {c.get("cardClass","?")} | {c.get("set","?")}')
    text = clean(c.get("text", ""))
    # Extract appendage count from "巨型+N"
    col_match = re.search(r"巨型\+(\d+)", text)
    appendage_count = col_match.group(1) if col_match else "?"
    L(f'    Appendages: {appendage_count}')
    L(f'    {text[:200]}')
L("")

# ============================================================
# 14. 先驱/血亲 (Herald/Kindred)
# ============================================================
L("=" * 60)
L("## 14. 先驱/血亲/游客 (Herald/Kindred/Tourist)")
L("=" * 60)
herald_cards = find_cards(r"先驱", cards)
kindred_cards = find_cards(r"血亲", cards)
tourist_cards = find_cards(r"游客", cards)
L(f"Herald (先驱) cards: {len(herald_cards)}")
for c in herald_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {clean(c.get("text",""))[:150]}')
L(f"\nKindred (血亲) cards: {len(kindred_cards)}")
for c in kindred_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {clean(c.get("text",""))[:150]}')
L(f"\nTourist (游客) cards: {len(tourist_cards)}")
for c in tourist_cards:
    L(f'  {c["name"]} | {c.get("cost","?")}mana | {c.get("cardClass","?")} | {clean(c.get("text",""))[:150]}')
L("")

# ============================================================
# 15. 特殊关键词汇总 (all unique keywords from mechanics field)
# ============================================================
L("=" * 60)
L("## 15. 所有唯一 mechanics 关键词")
L("=" * 60)
mech_count = defaultdict(int)
for c in cards:
    for m in (c.get("mechanics", []) or []):
        mech_count[m] += 1
L(f"Total unique mechanics: {len(mech_count)}")
for m, cnt in sorted(mech_count.items(), key=lambda x: -x[1]):
    L(f"  {m}: {cnt}")
L("")

# ============================================================
# 16. 可变法力消耗 (Variable cost cards)
# ============================================================
L("=" * 60)
L("## 16. 可变法力消耗 (Variable mana cost)")
L("=" * 60)
var_cost = find_cards(r"法力值消耗.*减少|法力值消耗.*增加|消耗.*法力值|临时|可交易", cards)
L(f"Cards with variable cost: {len(var_cost)}")
# Also check for cards with 0 cost that adjust
zero_cost = [c for c in cards if c.get("cost") == 0 and c.get("type") in ("SPELL", "MINION")]
L(f"0-cost cards: {len(zero_cost)}")
for c in zero_cost[:10]:
    L(f'  {c["name"]} | {c.get("cardClass","?")} | {c.get("type","?")} | {clean(c.get("text",""))[:120]}')
L("")

# ============================================================
# Summary: New EV modeling categories needed
# ============================================================
L("=" * 60)
L("## 总结：新增 EV 建模维度")
L("=" * 60)
L("")
L("### Tier A: 直接价值计算（固定效果）")
L(f"- 武器: {len(weapons)} 张 — attack × expected_swings + battlecry")
L(f"- 英雄牌: {len(hero_cards)} 张 — armor + hero_power_value")
L(f"- 0费牌: {len(zero_cost)} 张 — free card value = V2 baseline")
L("")
L("### Tier B: 条件触发（需要状态感知）")
L(f"- 兆示(Omen): {len(omen_cards)} 张 — 看顶N张选1, EV = E[max of N from deck]")
L(f"- 回溯(Rewind): {len(rewind_cards)} 张 — 前一回合的牌可用, EV = best_previous_card")
L(f"- 裂变(Fission): {len(fission_cards)} 张 — 牌分两半, EV = sum(half_A + half_B)")
L(f"- 延系(Lineage): {len(lineage_cards)} 张 — 连续打出加成, EV = base + P(combo) × bonus")
L(f"- 注能(Imbue): {len(imbue_cards)} 张 — 升级英雄技能, EV = upgrade_value × P(trigger)")
L(f"- 星舰(Starship): {len(starship_cards)} 张 — 累积零件发射, EV = sum(pieces) × P(launch)")
L(f"- 发现链(Discover chain): {len(chain_cards)} 张 — 使用发现牌再发现, EV = discover_EV + P(play) × discover_EV")
L("")
L("### Tier C: 多回合累积（需要时间折扣）")
L(f"- 任务(Quest): {len(quest_cards)} 张 — 多回合投资, EV = reward × P(complete) × discount^n")
L(f"- 巨型(Colossal): {len(colossal_cards)} 张 — 主体+肢节, EV = body + sum(limbs × P(survive))")
L(f"- 地标(Location): {len(locations)} 张 — 可激活效果, EV = charges × per_use_EV")
L("")
L("### Tier D: 独特机制")
L(f"- 先驱(Herald): {len(herald_cards)} 张 — 特定条件下生成衍生物")
L(f"- 血亲(Kindred): {len(kindred_cards)} 张 — 种族关联效果")
L(f"- 游客(Tourist): {len(tourist_cards)} 张 — 跨职业发现")
L(f"- 英雄技能相关: {len(hp_cards)} 张 — 修改/增强英雄技能")

with open("hs_cards/mechanics_detail_analysis.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Report saved. Total lines: {len(lines)}")
print(f"兆示: {len(omen_cards)}, 回溯: {len(rewind_cards)}, 裂变: {len(fission_cards)}")
print(f"延系: {len(lineage_cards)}, 注能: {len(imbue_cards)}, 星舰: {len(starship_cards)}")
print(f"发现链: {len(chain_cards)}, 任务: {len(quest_cards)}")
print(f"巨型: {len(colossal_cards)}, 地标: {len(locations)}")
print(f"英雄牌: {len(hero_cards)}, 武器: {len(weapons)}, 0费: {len(zero_cost)}")

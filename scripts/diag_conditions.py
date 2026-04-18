import json, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

report = json.load(open("hs_cards/v2_scoring_report.json", "r", encoding="utf-8"))
unified = json.load(open("hs_cards/unified_standard.json", "r", encoding="utf-8"))
scored = report["cards"] if isinstance(report, dict) else report
name_text = {c["name"]: c.get("text", "") for c in unified}

COND_PATTERNS = {
    "条件触发": r"如果",
    "回合触发": r"每当|在你的回合|回合结束|回合开始",
    "使用/打出": r"使用一张|打出|施放",
    "黑暗之赐": r"黑暗之赐",
    "回溯": r"回溯",
    "延系": r"延系",
    "灌注递增": r"灌注",
    "任务奖励": r"任务[:：]",
    "发现联动": r"发现",
    "弃牌": r"弃",
    "费用递减": r"消耗.*减少|每.*减少",
    "召唤联动": r"召唤.*(?:每当|如果)",
}

print("=== 条件/联动卡牌 (当前评分可能低估) ===")
print(f"{'Name':<24s} {'C':>2} {'Type':>7} {'Score':>5} | Condition Types")
print("-" * 75)

results = []
for c in scored:
    text = name_text.get(c["name"], "")
    conds = []
    for cname, pat in COND_PATTERNS.items():
        if re.search(pat, text):
            conds.append(cname)
    if conds and c["score"] < 5:
        results.append((c, conds, text))

results.sort(key=lambda x: x[0]["score"])
for c, conds, text in results[:35]:
    cond_str = ", ".join(conds)
    print(f"  {c['name']:<22s} {c['cost']:>2} {c['type']:>7} {c['score']:5.1f} | {cond_str}")
    print(f"    {text[:100]}")
print(f"\n  ... {len(results)} cards total with conditional effects scored < 5")

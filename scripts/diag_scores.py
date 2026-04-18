import json, sys, io, numpy as np
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
data = json.load(open("hs_cards/v2_scoring_report.json", "r", encoding="utf-8"))

for ctype in ["MINION", "SPELL", "WEAPON", "LOCATION", "HERO"]:
    cards = [c for c in data if c["type"] == ctype]
    if not cards:
        continue
    scores = [c["score"] for c in cards]
    l1s = [c["L1"] for c in cards]
    l2s = [c["L2"] for c in cards]
    l3s = [c["L3"] for c in cards]
    costs = [c["cost"] for c in cards]
    no_eff = sum(1 for c in cards if not c["effects"])

    print(f"=== {ctype} ({len(cards)}) ===")
    print(f"  Score: min={min(scores):.1f}, mean={np.mean(scores):.1f}, max={max(scores):.1f}")
    print(f"  L1(raw): mean={np.mean(l1s):.1f}  L2(kw): mean={np.mean(l2s):.1f}  L3(text): mean={np.mean(l3s):.1f}")
    print(f"  Zero-L1: {sum(1 for x in l1s if abs(x)<0.01)}/{len(cards)}")
    print(f"  No text effects parsed: {no_eff}/{len(cards)}")

    by_cost = {}
    for c in cards:
        by_cost.setdefault(c["cost"], []).append(c["score"])
    print(f"  Per cost: ", end="")
    for cost in sorted(by_cost):
        avg = np.mean(by_cost[cost])
        print(f"{cost}m={avg:.1f}({len(by_cost[cost])}) ", end="")
    print()

    print(f"  Bottom 3:")
    for c in sorted(cards, key=lambda x: x["score"])[:3]:
        eff = ",".join(c["effects"][:3]) or "-"
        print(f"    {c['score']:6.1f} | {c['cost']}f {c['name']} | L1={c['L1']} L2={c['L2']} L3={c['L3']} | {eff}")
    print(f"  Top 3:")
    for c in sorted(cards, key=lambda x: -x["score"])[:3]:
        eff = ",".join(c["effects"][:3]) or "-"
        print(f"    {c['score']:6.1f} | {c['cost']}f {c['name']} | L1={c['L1']} L2={c['L2']} L3={c['L3']} | {eff}")
    print()

"""Save the 60 missing standard cards to file for analysis."""
import requests
import json
import time

API_URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.iyingdi.com/",
    "Origin": "https://www.iyingdi.com",
}

def fetch_all(extra_params=None):
    all_cards = []
    page = 1
    while True:
        data = {"page": str(page), "size": "50"}
        if extra_params:
            data.update(extra_params)
        resp = requests.post(API_URL, data=data, headers=HEADERS, timeout=30)
        result = resp.json()
        cards = result.get("data", {}).get("cards", [])
        if not cards:
            break
        all_cards.extend(cards)
        if len(cards) < 50:
            break
        page += 1
        time.sleep(0.2)
    return all_cards

# Load our current dataset
with open("hs_cards/iyingdi_all_standard.json", "r", encoding="utf-8") as f:
    our_data = json.load(f)
our_gids = set(c.get("gameid") for c in our_data["cards"])
print(f"Our dataset: {len(our_gids)} cards")

# Fetch ALL cards (no filter), find standard=1 ones
print("Fetching all cards from iyingdi (no filter)...")
all_cards = fetch_all({})
print(f"Total in iyingdi: {len(all_cards)}")

# Dedup
all_map = {}
for c in all_cards:
    gid = c.get("gameid")
    if gid and gid not in all_map:
        all_map[gid] = c

print(f"Unique cards: {len(all_map)}")

# Find standard=1 cards
std_cards = {gid: c for gid, c in all_map.items() if c.get("standard") == 1}
print(f"Standard=1 cards: {len(std_cards)}")

# Missing from our dataset
missing = {gid: c for gid, c in std_cards.items() if gid not in our_gids}
print(f"Missing from our dataset: {len(missing)}")

# Save missing cards
lines = []
lines.append(f"# Missing Standard Cards ({len(missing)} total)")
lines.append(f"Total standard=1 in iyingdi: {len(std_cards)}")
lines.append(f"Our dataset: {len(our_gids)}")
lines.append("")

# Categorize missing
from collections import Counter
clazz_counts = Counter(c.get("clazz", "?") for c in missing.values())
lines.append("## Missing by clazz")
for k, v in clazz_counts.most_common():
    lines.append(f"- {k}: {v}")
lines.append("")

series_counts = Counter(c.get("seriesAbbr", "?") for c in missing.values())
lines.append("## Missing by series")
for k, v in series_counts.most_common():
    lines.append(f"- {k}: {v}")
lines.append("")

faction_counts = Counter(c.get("faction", "?") for c in missing.values())
lines.append("## Missing by faction")
for k, v in faction_counts.most_common():
    lines.append(f"- {k}: {v}")
lines.append("")

lines.append("## All Missing Cards")
for gid, c in sorted(missing.items(), key=lambda x: (x[1].get("seriesAbbr", ""), x[1].get("faction", ""), x[1].get("mana", 0))):
    lines.append(f"- {c.get('cname')} | {c.get('faction')} | {c.get('clazz')} | {c.get('seriesAbbr')} | {c.get('mana')}mana | gameid={gid}")
    lines.append(f"  Rule: {(c.get('rule','') or '')[:150]}")

with open("hs_cards/missing_standard_cards.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"\nSaved to hs_cards/missing_standard_cards.md")

# Also save the complete standard=1 dataset
std_list = list(std_cards.values())
output = {
    "total": len(std_list),
    "source": "iyingdi_all_filtered_by_standard=1",
    "cards": std_list,
}
with open("hs_cards/standard_complete.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"Complete standard dataset saved to hs_cards/standard_complete.json ({len(std_list)} cards)")

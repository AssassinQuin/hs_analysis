"""
Try alternative Blizzard CN API endpoints for full card database.
"""

import json
import urllib.request


def try_url(url, body=None, label=""):
    try:
        if body:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0",
                },
            )
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            r = json.loads(resp.read().decode("utf-8"))
            print(f"  OK: {json.dumps(r, ensure_ascii=False)[:500]}")
            return r
    except Exception as e:
        print(f"  FAIL: {e}")
        return None


# Try different API paths
endpoints = [
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards/search",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards/list",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards/standard",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/cards",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/cards/constructed",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/collection",
    "https://webapi.blizzard.cn/hs-cards-api-server/api/web/card",
]

# Try GET first
for ep in endpoints:
    print(f"\nGET {ep}")
    try_url(ep)

# Try some with POST body
print("\n\n=== POST tests ===")
post_tests = [
    (
        "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards",
        {"rarity": "legendary", "page_size": 5},
    ),
    (
        "https://webapi.blizzard.cn/hs-cards-api-server/api/web/cards",
        {"mana_cost": 8, "page_size": 5},
    ),
]
for url, body in post_tests:
    print(f"\nPOST {url} with {body}")
    try_url(url, body)

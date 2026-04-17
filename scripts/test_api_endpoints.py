"""
Test different API endpoints to find the correct card database endpoint.
"""

import json
import urllib.request

BASE = "https://webapi.blizzard.cn/hs-cards-api-server/api"


def fetch(url, body=None):
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
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


# Test the /filter endpoint to understand the API structure
print("=== Filter endpoint ===")
r = fetch(f"{BASE}/web/cards/constructed/filter")
if "error" not in r:
    print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])
else:
    print(r["error"])

# Test the /set endpoint
print("\n=== Set endpoint ===")
r2 = fetch(f"{BASE}/web/cards/constructed/set")
if "error" not in r2:
    print(json.dumps(r2, ensure_ascii=False, indent=2)[:3000])
else:
    print(r2["error"])

# Test the /class endpoint
print("\n=== Class endpoint ===")
r3 = fetch(f"{BASE}/web/cards/constructed/class")
if "error" not in r3:
    print(json.dumps(r3, ensure_ascii=False, indent=2)[:2000])
else:
    print(r3["error"])

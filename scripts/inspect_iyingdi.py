# -*- coding: utf-8 -*-
import json, sys, io, urllib.request, urllib.parse
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

URL = "https://api2.iyingdi.com/hearthstone/card/search/vertical"
HEADERS = {
    "Accept": "*/*",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Origin": "https://www.iyingdi.com",
    "Referer": "https://www.iyingdi.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}
body = urllib.parse.urlencode({
    "ignoreHero": "1", "standard": "1", "statistic": "total",
    "order": "-series,+mana", "token": "", "page": "1", "size": "2",
})
req = urllib.request.Request(URL, data=body.encode("utf-8"), headers=HEADERS)
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode("utf-8"))
cards = result["data"]["cards"]
total = result["data"]["total"]
print("Total standard cards:", total)
print()
print("=== Card 0 ===")
print(json.dumps(cards[0], ensure_ascii=False, indent=2))
print()
print("=== Card 1 ===")
print(json.dumps(cards[1], ensure_ascii=False, indent=2))

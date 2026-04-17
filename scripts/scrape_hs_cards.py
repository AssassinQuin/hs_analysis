"""
Scrape all standard legendary cards from Blizzard CN Hearthstone API.
Single request gets all cards — no need to loop over sets.
"""
import requests
import json
import os
import time

BASE_URL = "https://webapi.blizzard.cn/hs-cards-api-server/api"
ENDPOINT = f"{BASE_URL}/web/cards/constructed"

RARITY_LEGENDARY = 5
PAGE_SIZE = 100

OUTPUT_DIR = "hs_cards"
IMAGES_DIR = os.path.join(OUTPUT_DIR, "images")
CROPS_DIR = os.path.join(OUTPUT_DIR, "crops")

os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(CROPS_DIR, exist_ok=True)

# Set ID to name mapping (from /web/cards/constructed/set endpoint)
SET_NAMES = {
    3: "基础", 12: "纳克萨玛斯", 13: "地精大战侏儒", 14: "黑石山",
    20: "冠军的试炼", 21: "探险者协会", 23: "上古之神", 25: "卡拉赞之夜",
    27: "龙争虎斗加基森", 1004: "勇闯安戈洛", 1125: "冰封王座",
    1127: "狗头人与地下世界", 1129: "女巫森林", 1130: "砰砰计划",
    1158: "拉斯塔哈", 1347: "暗影崛起", 1443: "奥丹姆奇兵",
    1466: "巨龙降临", 1525: "外域的灰烬", 1635: "通灵学园",
    1637: "核心", 1658: "疯狂的暗月马戏团", 1691: "暴风城下的集结",
    1776: "探寻沉没之城", 1809: "纳斯利亚堡", 1858: "巫妖王的进军",
    1892: "传奇音乐节", 1897: "威兹班的工坊", 1898: "泰坦诸神",
    1905: "胜地历险记", 1935: "深暗领域", 1941: "活动",
    1946: "漫游翡翠梦境", 1952: "安戈洛龟途", 1957: "穿越时间流",
    1980: "大地的裂变",
}

CLASS_NAMES = {
    2: "德鲁伊", 3: "猎人", 4: "法师", 5: "圣骑士", 6: "牧师",
    7: "盗贼", 8: "萨满", 9: "术士", 10: "战士", 11: "恶魔猎手",
    12: "死亡骑士", 14: "中立",
}

CARD_TYPE_NAMES = {
    4: "随从", 5: "法术", 7: "武器", 8: "英雄卡",
}


def fetch_all_legendaries():
    """Fetch all standard legendary cards in one go."""
    body = {
        "rarity_id": RARITY_LEGENDARY,
        "page": 1,
        "page_size": 200,  # Get plenty in one page
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://hs.blizzard.cn/cards/",
    }
    resp = requests.post(ENDPOINT, json=body, headers=headers, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    
    if result.get("code") != 0:
        raise Exception(f"API error: {result.get('message')}")
    
    total = result["data"]["total"]
    cards = result["data"]["list"]
    print(f"Fetched {len(cards)} cards (total: {total})")
    
    # If there are more pages, fetch them
    all_cards = list(cards)
    page = 1
    while len(all_cards) < total:
        page += 1
        time.sleep(0.3)
        body["page"] = page
        resp = requests.post(ENDPOINT, json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") != 0:
            print(f"Error on page {page}: {result.get('message')}")
            break
        page_cards = result["data"]["list"]
        all_cards.extend(page_cards)
        print(f"Page {page}: +{len(page_cards)} cards")
    
    # Deduplicate by card ID
    seen = {}
    for card in all_cards:
        cid = card["id"]
        if cid not in seen:
            seen[cid] = card
    
    return list(seen.values())


def download_image(url, filepath):
    """Download an image if it doesn't already exist."""
    if os.path.exists(filepath):
        return
    if not url:
        return
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
    except Exception as e:
        print(f"  Failed: {os.path.basename(filepath)} - {e}")


def enrich_card(card):
    """Add human-readable field names to a card."""
    card["set_name"] = SET_NAMES.get(card["card_set_id"], f"Unknown({card['card_set_id']})")
    card["class_name"] = CLASS_NAMES.get(card["class_id"], f"Unknown({card['class_id']})")
    card["type_name"] = CARD_TYPE_NAMES.get(card["card_type_id"], f"Unknown({card['card_type_id']})")
    return card


def main():
    print("Fetching all standard legendary cards...")
    cards = fetch_all_legendaries()
    
    # Enrich with readable names
    cards = [enrich_card(c) for c in cards]
    
    print(f"\nTotal unique legendary cards: {len(cards)}")
    
    # Group by class
    from collections import Counter
    class_counts = Counter(c["class_name"] for c in cards)
    print("\nCards by class:")
    for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
        print(f"  {cls}: {count}")
    
    # Group by set
    set_counts = Counter(c["set_name"] for c in cards)
    print("\nCards by set:")
    for s, count in sorted(set_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {count}")
    
    # Download images
    print(f"\nDownloading images...")
    for i, card in enumerate(cards):
        card_id = card["id"]
        name = card.get("name", "unknown")
        # Sanitize filename
        safe_name = "".join(c for c in name if c.isalnum() or c in "._- ") or "unknown"
        
        # Full card image
        if card.get("image"):
            img_path = os.path.join(IMAGES_DIR, f"{card_id}_{safe_name}.jpg")
            download_image(card["image"], img_path)
        
        # Crop/art image
        if card.get("crop_image"):
            crop_path = os.path.join(CROPS_DIR, f"{card_id}_{safe_name}.jpg")
            download_image(card["crop_image"], crop_path)
        
        # Golden image
        if card.get("image_gold"):
            gold_path = os.path.join(IMAGES_DIR, f"{card_id}_{safe_name}_gold.gif")
            download_image(card["image_gold"], gold_path)
        
        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{len(cards)}")
        time.sleep(0.1)
    
    # Save enriched card data
    output_file = os.path.join(OUTPUT_DIR, "all_standard_legendaries.json")
    
    # Group by class for structured output
    by_class = {}
    for card in cards:
        cls = card["class_name"]
        if cls not in by_class:
            by_class[cls] = []
        by_class[cls].append(card)
    
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "total": len(cards),
            "by_class": {cls: {"count": len(cs), "cards": cs} for cls, cs in sorted(by_class.items())},
            "all_cards": cards,
        }, f, ensure_ascii=False, indent=2)
    
    # Also save a simple card list (name, class, set, mana, type)
    summary_file = os.path.join(OUTPUT_DIR, "card_list.json")
    summary = []
    for card in sorted(cards, key=lambda c: (c["class_name"], c["mana_cost"], c["name"])):
        summary.append({
            "id": card["id"],
            "name": card["name"],
            "class": card["class_name"],
            "set": card["set_name"],
            "type": card["type_name"],
            "mana": card.get("mana_cost"),
            "attack": card.get("attack"),
            "health": card.get("health"),
            "text": card.get("text", ""),
        })
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"DONE! {len(cards)} unique standard legendary cards.")
    print(f"Full data: {output_file}")
    print(f"Card list: {summary_file}")
    print(f"Images: {IMAGES_DIR}/")
    print(f"Crops: {CROPS_DIR}/")
    
    # Count downloaded images
    imgs = len([f for f in os.listdir(IMAGES_DIR) if f.endswith(('.jpg', '.gif'))])
    crops = len([f for f in os.listdir(CROPS_DIR) if f.endswith('.jpg')])
    print(f"Downloaded: {imgs} images, {crops} crops")


if __name__ == "__main__":
    main()

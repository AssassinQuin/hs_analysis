"""merge_v2_manual.py — 将 card_abilities_v2_manual.json 合并到 card_abilities_v2.json。

用法:
    python analysis/card/data/merge_v2_manual.py
"""
import json
from pathlib import Path

V2_PATH = Path(__file__).parent / "card_abilities_v2.json"
MANUAL_PATH = Path(__file__).parent / "card_abilities_v2_manual.json"

def merge_deep(base, override):
    """深度合并 override 到 base (dict 递归合并)。"""
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            merge_deep(base[key], val)
        else:
            base[key] = val
    return base

def main():
    with open(V2_PATH, 'r', encoding='utf-8') as f:
        v2 = json.load(f)
    
    with open(MANUAL_PATH, 'r', encoding='utf-8') as f:
        manual = json.load(f)
    
    overrides = manual.get("manual_overrides", manual)
    
    merged_count = 0
    for cid, override_data in overrides.items():
        if cid not in v2:
            print(f"  [WARN] 卡牌 {cid} 不在 v2 JSON 中，跳过")
            continue
        merge_deep(v2[cid], override_data)
        merged_count += 1
    
    # 回写
    with open(V2_PATH, 'w', encoding='utf-8') as f:
        json.dump(v2, f, ensure_ascii=False, indent=2)
    
    print(f"合并完成: {merged_count} 张卡牌已覆盖")

if __name__ == "__main__":
    main()

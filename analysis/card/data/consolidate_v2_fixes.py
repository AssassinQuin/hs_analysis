#!/usr/bin/env python3
"""consolidate_v2_fixes.py — 将 v2 JSON 中的手动修复永久化到 manual_overrides。

工作流:
  1. 临时运行 generator 产生基准输出
  2. 对比基准输出 vs 当前 v2 JSON
  3. 将有差异的非-TODO 条目追加到 manual_overrides

用法:
    PYTHONPATH=. python3 analysis/card/data/consolidate_v2_fixes.py
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATA_DIR = Path(__file__).resolve().parent
V2_PATH = DATA_DIR / "card_abilities_v2.json"
MANUAL_PATH = DATA_DIR / "card_abilities_v2_manual.json"
GENERATOR_PATH = PROJECT_ROOT / "analysis" / "card" / "abilities" / "generator_v2.py"


def has_todo(obj):
    if isinstance(obj, dict):
        if obj.get('class') == 'TODO':
            return True
        return any(has_todo(v) for v in obj.values())
    elif isinstance(obj, list):
        return any(has_todo(item) for item in obj)
    return False


def get_flat_diff(current: dict, baseline: dict) -> dict:
    """返回 manual overrides: current 中非 TODO 但 baseline 中是 TODO 的条目。"""
    overrides = {}
    all_ids = set(current) | set(baseline)
    for cid in sorted(all_ids):
        cur_entry = current.get(cid)
        base_entry = baseline.get(cid)
        if not cur_entry or not base_entry:
            continue
        if has_todo(base_entry) and not has_todo(cur_entry):
            overrides[cid] = cur_entry
    return overrides


def main():
    # 1. 读取当前 v2 JSON (含 subtask 修复)
    print("读取当前 v2 JSON...")
    with open(V2_PATH, 'r', encoding='utf-8') as f:
        current = json.load(f)

    # 2. 读已有手动覆盖 (避免重复)
    if MANUAL_PATH.exists():
        with open(MANUAL_PATH, 'r', encoding='utf-8') as f:
            manual = json.load(f)
        existing_overrides = manual.get("manual_overrides", manual)
        existing_ids = set(existing_overrides.keys())
    else:
        existing_overrides = {}
        existing_ids = set()
    print(f"已有手动覆盖: {len(existing_ids)} 条")

    # 3. 临时生成基准输出
    print("运行 generator 产生基准输出...")
    import importlib.util
    spec = importlib.util.spec_from_file_location("generator_v2", GENERATOR_PATH)
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    # gen needs analysis module, let's sanitize imports
    # Instead, exec the generator directly
    baseline = gen.generate_abilities_json_v2()
    
    # 4. 找出差异
    diffs = get_flat_diff(current, baseline)
    new_ids = set(diffs.keys()) - existing_ids
    print(f"基准中有 TODO 但当前已修复的: {len(diffs)} 条")
    print(f"其中尚未在 manual_overrides 中的: {len(new_ids)} 条")

    if not new_ids:
        print("无新增需要持久化的修复。")
        return

    # 5. 追加到 manual_overrides
    added = 0
    for cid in sorted(new_ids):
        existing_overrides[cid] = diffs[cid]
        added += 1

    with open(MANUAL_PATH, 'w', encoding='utf-8') as f:
        json.dump({"manual_overrides": existing_overrides}, f,
                  ensure_ascii=False, indent=2)

    print(f"已追加 {added} 条修复到 manual_overrides。")
    print(f"manual_overrides 总计: {len(existing_overrides)} 条")


if __name__ == "__main__":
    main()

# Task Plan: 消除 unified_standard.json / unified_wild.json 冗余文件

> 生成时间: 2026-04-27
> 状态: ✅ 全部完成

## 前置分析

### 字段兼容性

| 消费者 | 使用的字段 | `_merge_locale()` 是否覆盖 | 备注 |
|---|---|---|---|
| bayesian_opponent (via `Card.from_hsdb_dict`) | cardId, dbfId, name, cost, type, attack, health, text, rarity, cardClass, race, mechanics, set, englishName, englishText, overload, spellDamage, armor, durability, spellSchool | ✅ 全部覆盖 | `_merge_locale` 字段名与 `from_hsdb_dict` 完全匹配 |
| packet_replayer `_load_card_names` | id (→ cardId), name (中文) | ✅ `cardId` + `name` | 旧代码读 `card.get("id")` 但 unified 文件用 `cardId`，本就是死路径 |
| rewind_delta_generator | dbfId, name, type, cost, text | ✅ 全部覆盖 | 自带 `strip_html()`，不依赖预清理的 text |

### 关键发现

1. **`_merge_locale()` 不调用 `_clean_text()`** — `text` / `englishText` 字段保留原始 HTML 标签。
   - `rewind_delta_generator` 自带 `strip_html()`，不受影响。
   - `bayesian_opponent` 不直接使用 text 字段做文本处理，不受影响。
   - **结论: 暂不需要在 `_merge_locale()` 中加入 `_clean_text()`。** 如后续消费者需要，再添加。

2. **packet_replayer 的 unified 读取已是死路径** — `card.get("id", "")` (L2025) 与 unified 文件的 `cardId` 不匹配，所有 unified 条目被静默跳过。实际数据来自 zhCN cards.json/cards.collectible.json。

3. **packet_replayer 有 3 处 `from analysis.data.hsdb import get_db`** — `hsdb.py` 已合并到 `card_data.py`，这是已有的 ImportError。需一并修复。

---

## 任务拆解

### T1: 删除 `build_databases()` 及其调用 ✅ 已完成

- **涉及文件**: `analysis/data/card_data.py`
- **行号**: L1264–1347 (`build_databases` 方法), L1169–1208 (`update` 方法中的 `build_databases()` 调用), L202–229 (`_build_card_dict` 方法，仅被 `build_databases` 使用)
- **具体改动**:
  1. 删除 `_build_card_dict()` 方法 (L202–229)
  2. 删除 `build_databases()` 方法 (L1264–1347)
  3. 修改 `update()` 方法 (L1169–1208): 移除 `self.build_databases()` 调用，保留其余逻辑（清空索引、重新 `_load_hsjson()`、重建索引）
  4. 检查 `__init__` 中是否有 `build_databases()` 调用并删除
- **依赖**: 无
- **复杂度**: 低
- **可并行**: ✅ 与 T2, T3, T4 并行

### T2: 修改 `bayesian_opponent.py` — 改用 CardDB ✅ 已完成

- **涉及文件**: `analysis/utils/bayesian_opponent.py`
- **行号**: L28 (import), L30 (UNIFIED_PATH), L131–140 (`_load_card_data` 方法)
- **具体改动**:
  1. L28: 移除 `UNIFIED_DB_PATH` import，改为 `from analysis.data.card_data import get_db`
  2. 删除 L30 `UNIFIED_PATH = str(UNIFIED_DB_PATH)`
  3. 重写 `_load_card_data()` 方法:
     ```python
     def _load_card_data(self):
         """Load card data from CardDB for dbfId lookups."""
         try:
             db = get_db()
             self.cards_by_dbf = dict(db.dbf_lookup)
         except Exception:
             self.cards_by_dbf = {}
     ```
  4. 验证: `dbf_lookup` 返回的 dict 格式与 `Card.from_hsdb_dict()` 完全兼容（字段名匹配），无需额外转换
- **依赖**: 无（CardDB.dbf_lookup 已存在）
- **复杂度**: 低
- **可并行**: ✅ 与 T1, T3, T4 并行

### T3: 修复 `packet_replayer.py` — 修复 hsdb import + 清理 unified 读取 ✅ 已完成

- **涉及文件**: `analysis/watcher/packet_replayer.py`
- **行号**: L1083, L1667, L2037 (`hsdb` import), L2009–2047 (`_load_card_names`)
- **具体改动**:
  1. 将 3 处 `from analysis.data.hsdb import get_db` → `from analysis.data.card_data import get_db`
  2. `_load_card_names()` 中移除 unified_standard.json 和 unified_wild.json 的文件路径（L2018–L2019），仅保留 zhCN cards.json 和 cards.collectible.json
  3. 保留 L2025 的 `card.get("id", "")` 逻辑（cards.json 使用 `id` 字段，正确）
  4. 可选优化: 可将 `_load_card_names` 改为使用 CardDB API 获取中文名（`db.get_card(card_id)["name"]`），但这不是必须的——当前 zhCN JSON 路径已经可用且不依赖 unified 文件
- **依赖**: 无
- **复杂度**: 低
- **可并行**: ✅ 与 T1, T2, T4 并行

### T4: 重构 `rewind_delta_generator.py` — 改用 CardDB ✅ 已完成

- **涉及文件**: `scripts/rewind_delta_generator.py`
- **行号**: L14 (硬编码路径), L19–21 (`load_cards` 函数), L91–92 (`generate_report` 中的调用)
- **具体改动**:
  1. 添加项目根目录到 sys.path（确保能 import analysis 包）
  2. 重写 `load_cards()`:
     ```python
     def load_cards():
         from analysis.data.card_data import get_db
         db = get_db()
         return db.get_collectible_cards(fmt="standard")
     ```
  3. 删除 L14 硬编码路径 `CARDS_PATH`
  4. `find_rewind_cards()` L38 搜索 `'回溯' in c.get('text', '')` — 注意 `_merge_locale()` 的 text 有 HTML 标签，`'回溯' in text` 仍能匹配（子串搜索），不受影响
  5. `find_original()` L53 已调用 `strip_html()`，不受影响
- **依赖**: 无
- **复杂度**: 低
- **可并行**: ✅ 与 T1, T2, T3 并行

### T5: 删除 `config.py` 中的 `UNIFIED_DB_PATH` ✅ 已完成

- **涉及文件**: `analysis/config.py`
- **行号**: L12
- **具体改动**:
  1. 删除 `UNIFIED_DB_PATH = DATA_DIR / "unified_standard.json"` (L12)
  2. 确认无其他文件引用 `UNIFIED_DB_PATH`（仅 bayesian_opponent.py 引用，T2 已处理）
- **依赖**: T2（必须先完成 bayesian_opponent 的 import 修改）
- **复杂度**: 低
- **可并行**: ❌ 依赖 T2

### T6: 清理遗留文件 ✅ 已完成

- **涉及文件**: `card_data/` 目录下的 `unified_standard.json`, `unified_wild.json`
- **具体改动**:
  1. 手动删除 `card_data/*/unified_standard.json` 和 `card_data/*/unified_wild.json` 文件
  2. 如有 `.gitignore` 中的相关条目，一并清理
- **依赖**: T1, T2, T3, T4, T5 全部完成
- **复杂度**: 低
- **可并行**: ❌ 依赖全部前置任务

### T7: 测试验证 ✅ 已完成（394 passed, 16 skipped, 0 failed）

- **涉及文件**: 测试文件
- **具体改动**:
  1. 验证 `bayesian_opponent._load_card_data()` 能正确通过 CardDB 加载数据
  2. 验证 `packet_replayer._load_card_names()` 不再尝试读取 unified 文件
  3. 验证 `CardDB` 初始化不再生成 unified 文件
  4. 验证 `rewind_delta_generator.py` 能通过 CardDB API 获取卡牌数据
  5. 回归测试: 确保现有测试套件全部通过
- **依赖**: T1–T6 全部完成
- **复杂度**: 中
- **可并行**: ❌

---

## 执行顺序

```
T1 ──┐
T2 ──┤
T3 ──┼──→ T5 ──→ T6 ──→ T7
T4 ──┘
```

**第一批 (并行)**: T1, T2, T3, T4 — 互不依赖，可同时执行
**第二批**: T5 — 等待 T2 完成
**第三批**: T6 — 等待全部完成
**第四批**: T7 — 最终验证

## 总复杂度: 低 (6 × 低 + 1 × 中)

所有消费者所需字段在 CardDB 现有 API 中完全覆盖，无需新增任何 API 或字段。核心工作是删除代码和替换数据源。

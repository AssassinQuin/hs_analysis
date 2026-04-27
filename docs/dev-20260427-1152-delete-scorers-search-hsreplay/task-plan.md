> **本文件功能**: 记录删除评分引擎/搜索引擎/HSReplay 三个模块的任务规划和执行状态。

# 任务计划: 删除评分引擎 + 搜索引擎 + HSReplay

## 背景说明

删除三个模块，保留 MCTS（`analysis/search/mcts/`）和游戏机制代码（corpse/corrupt/imbue/dark_gift/rune/MechanicsState/ZoneManager/abilities/engine 子目录）。

## 依赖分析

- MCTS 完全自包含于 `search/mcts/`，仅依赖 `analysis.abilities`, `analysis.engine`, `analysis.constants`
- 游戏机制代码（corpse 等）被 `engine/` 引用，需保留
- 三个任务组互不依赖，可并行执行

---

## T1: 删除评分引擎 (scorers/) ⬜

**状态**: 待执行

### 删除文件
- `analysis/scorers/` 整个目录（7 个文件）
- `scripts/run_scoring.py`
- `tests/test_v8_contextual_scorer.py`
- `tests/test_keyword_interactions.py`
- `tests/test_mechanic_base_values.py`
- `HSReplay_Card_Rankings.xlsx`（仅被 scoring_engine.py 使用）

### 修复引用
- `analysis/evaluators/siv.py`: 删除 scorers 导入 + 相关代码
- `analysis/evaluators/composite.py`: 删除 scorers.v8_contextual 导入 + 相关代码
- `analysis/config.py`: 删除 `RANKINGS_PATH` 配置

---

## T2: 删除 HSReplay 功能 ⬜

**状态**: 待执行

### 删除文件
- `analysis/data/fetch_hsreplay.py`
- `scripts/run_fetch.py`
- `.env.example`
- `card_data/240397/hsreplay_cache.db`（如存在）

### 修复引用
- `analysis/watcher/global_tracker.py`: 删除 fetch_hsreplay 导入 + 相关代码
- `analysis/utils/bayesian_opponent.py`: 删除 fetch_hsreplay 导入 + HSReplay 相关代码
- `analysis/watcher/deck_hot_reloader.py`: 删除 fetch_hsreplay 导入 + 相关代码
- `scripts/pool_quality_generator.py`: 删除 hsreplay_cache.db 引用
- `analysis/config.py`: 删除 HSREPLAY_CACHE_DB, HSREPLAY_API_KEY, HSREPLAY_CARDS_URL, HSREPLAY_ARCHETYPES_URL, get_api_headers()

---

## T3: 删除搜索引擎非 MCTS 部分 ⬜

**状态**: 待执行

### 保留（不动）
- `analysis/search/mcts/` 整个目录
- `analysis/search/abilities/` 整个目录
- `analysis/search/engine/` 整个目录
- `analysis/search/corpse.py`, `corrupt.py`, `imbue.py`
- `analysis/search/dark_gift.py`, `rune.py`
- `analysis/search/entity.py`, `zone_manager.py`, `mechanics_state.py`
- `analysis/search/__init__.py`（需更新）

### 删除文件
- `analysis/search/neural/` 整个目录
- `analysis/search/adapter.py`
- `analysis/search/lethal.py`
- `analysis/search/opponent.py`
- `analysis/search/power_parser.py`
- `analysis/search/risk.py`
- `analysis/search/action_normalize.py`
- `scripts/run_mcts.py`（需检查是否仅用已删除模块）
- `tests/search/` 中与删除模块相关的测试
- `tests/neural/` 整个目录
- `tests/test_live_games.py`（引用 adapter）

### 修复引用
- `analysis/evaluators/composite.py`: 删除 `search.risk` 导入
- `analysis/watcher/decision_loop.py`: 删除 `search.adapter` 导入 + 相关代码
- `analysis/watcher/packet_replayer.py`: 删除已删除模块的导入
- `analysis/watcher/state_bridge.py`: 检查注释掉的导入
- `tests/watcher/test_watcher.py`: 删除 adapter 引用
- `analysis/search/__init__.py`: 更新导出

---

## 并行组

T1, T2, T3 无依赖关系，可并行执行。

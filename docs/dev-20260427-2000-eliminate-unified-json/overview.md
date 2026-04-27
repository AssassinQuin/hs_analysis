> **本文件功能**: 记录消除 unified_standard.json/unified_wild.json 冗余文件的重构分析。

## 需求

消除 `card_data/240397/unified_standard.json` 和 `unified_wild.json`，将其消费者改用 CardDB 直接从 enUS/zhCN 加载数据。

## 背景

### 现状：双轨数据加载

1. **CardDB（运行时核心路径）**: `_load_hsjson()` → `_merge_locale()` 直接读 enUS/zhCN 的 `cards.collectible.json`，合并中英文字段到内存
2. **Unified 文件（冗余构建产物）**: `build_databases()` 读同样的 enUS/zhCN 文件 → 生成 unified_standard.json / unified_wild.json → 被少数消费者读取

### 关键区别

| 特性 | CardDB | unified JSON |
|------|--------|-------------|
| 数据源 | enUS/zhCN 直接读 | 同（冗余） |
| `_clean_text()` HTML 清理 | ❌ 没有 | ✅ 有 |
| 英文名字段 | `englishName` | `ename` |
| Card ID 字段 | `cardId` | `cardId` |
| 格式过滤 | 内存中按 set 计算 | 按文件分 standard/wild |

### 消费者清单（3处）

| 文件 | 行号 | 用途 | 状态 |
|------|------|------|------|
| `analysis/utils/bayesian_opponent.py` | 131-140 | `_load_card_data()` 构建 cards_by_dbf | 可改用 CardDB |
| `scripts/rewind_delta_generator.py` | 14 | 读 unified_standard.json | 可改用 CardDB |
| `analysis/watcher/packet_replayer.py` | 2016-2017 | 读 unified 文件构建名称映射 | **已坏**（读 `id` 字段但 unified 用 `cardId`） |

## 项目规范摘要

- Python 3.10+, snake_case 命名, PascalCase 类名
- 单文件不超过 800 行
- 配置集中 `analysis/config.py`
- 测试 pytest, `tests/{模块}/test_*.py`
- 设计模式: Bridge + Strategy + Observer
- 数据: HearthstoneJSON API (enUS + zhCN 双语言)

## 涉及文件

| 文件 | 行数 | 角色 |
|------|------|------|
| `analysis/data/card_data.py` | 1504 | CardDB 核心类，含 `_merge_locale()` 和 `build_databases()` |
| `analysis/utils/bayesian_opponent.py` | 817 | 贝叶斯对手建模，`_load_card_data()` 读 unified |
| `analysis/watcher/packet_replayer.py` | 2142 | 回放引擎，第 2016 行读 unified（已坏） |
| `analysis/config.py` | ~67 | 全局配置，`UNIFIED_DB_PATH` 定义 |
| `scripts/rewind_delta_generator.py` | 140 | 一次性脚本，读 unified |
| `card_data/240397/unified_standard.json` | 3.1MB | 待删除 |
| `card_data/240397/unified_wild.json` | 646KB | 待删除 |

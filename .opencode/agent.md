# Agent Init — 炉石传说卡牌数值分析

## ⚡ Session 启动流程

每次新 session 第一条消息前必须执行：

1. **环境与命令**：`aivectormemory_recall(tags: ["environment", "system"], scope: "user", brief: true, top_k: 5)`
2. **项目约定**：`aivectormemory_recall(tags: ["skill", "rules"], scope: "user", brief: true, top_k: 5)`
3. **会话状态**：`aivectormemory_status()` — 检查是否 blocked，读取 current_task 和进度
4. **项目知识**：`aivectormemory_recall(tags: ["project-knowledge"], scope: "project", brief: true, top_k: 20)`

如果环境信息与当前系统不匹配，重新检测并更新 memory。

## 项目定位

通过**数学建模 + 数据驱动**量化《炉石传说》卡牌价值，建立多版本评分引擎（V2→V7→V8→L6）和竞技场决策系统（RHEA 搜索 + 贝叶斯对手建模）。

## 技术栈

- **语言**: Python 3.11+
- **包管理**: pyproject.toml, `pip install -e .`
- **依赖**: numpy, scipy, requests, dataclasses
- **数据存储**: JSON 文件（hs_cards/）, SQLite（hsreplay_cache.db）
- **数据源**: HearthstoneJSON, HSReplay, iyingdi
- **测试**: pytest（163+ 测试用例）

## 核心包结构

```
hs_analysis/                    # 核心包
├── config.py                   # 全局配置（路径、常量）
├── data/                       # 数据获取与处理
│   ├── card_index.py           # CardIndex — O(1) 卡牌查询
│   ├── card_cleaner.py         # 数据清洗（种族/机制/法术派系）
│   ├── fetch_hsjson.py         # HearthstoneJSON API
│   ├── fetch_hsreplay.py       # HSReplay 数据获取
│   ├── fetch_iyingdi.py        # iyingdi 数据获取
│   ├── fetch_wild.py           # 狂野卡牌获取
│   ├── build_unified_db.py     # 统一数据库构建
│   └── build_wild_db.py        # 狂野去重构建
├── models/
│   └── card.py                 # Card 数据模型（dataclass）
├── scorers/                    # 评分引擎（多版本演进）
│   ├── vanilla_curve.py        # 白板曲线基准
│   ├── v2_engine.py            # V2 基础评分
│   ├── v7_engine.py            # V7 数据驱动评分
│   ├── v8_contextual.py        # V8 上下文感知评分
│   ├── l6_real_world.py        # L6 真实世界评分
│   └── constants.py            # 评分常量
├── evaluators/                 # 评估器
│   ├── composite.py            # 复合评估器
│   ├── submodel.py             # 子模型评估器
│   └── multi_objective.py      # 多目标评估器
├── search/                     # 搜索引擎
│   ├── rhea_engine.py          # RHEA 滚动水平线进化
│   ├── game_state.py           # 游戏状态管理（GameState, HeroState 等）
│   ├── lethal_checker.py       # 致命检测
│   ├── opponent_simulator.py   # 对手模拟
│   ├── risk_assessor.py        # 风险评估
│   └── action_normalize.py     # 动作归一化
└── utils/                      # 工具模块
    ├── score_provider.py       # 评分数据提供（懒加载 + 缓存）
    ├── bayesian_opponent.py    # 贝叶斯对手建模
    └── spell_simulator.py      # 法术模拟
```

## 数据文件

| 文件 | 用途 |
|------|------|
| `hs_cards/unified_standard.json` | 清洗后的标准池卡牌数据（主数据源） |
| `hs_cards/hsjson_standard.json` | HearthstoneJSON 原始数据 |
| `hs_cards/hsreplay_cache.db` | HSReplay 缓存数据库 |
| `hs_cards/v7_scoring_report.json` | V7 评分报告 |
| `hs_cards/l6_scoring_report.json` | L6 评分报告 |

## 运行入口

| 脚本 | 功能 |
|------|------|
| `scripts/run_fetch.py` | 数据获取 |
| `scripts/run_rhea.py` | RHEA 引擎运行 |
| `scripts/run_score_v2.py` | V2 评分 |
| `scripts/run_score_v7.py` | V7 评分 |
| `scripts/analyze_meta_decks.py` | 环境套牌分析 |
| `scripts/deep_analysis.py` | 深度分析 |

## 测试

```bash
pytest                          # 全量测试（163+ 用例）
pytest tests/                   # 仅 tests/ 目录
pytest hs_analysis/search/      # search 模块内嵌测试
```

## 评分体系演进

- **V2** — 属性 + 关键词基础评分
- **V7** — 基于 HSReplay 数据驱动的实绩评分
- **V8** — 上下文感知（回合数、场面饱和度、种族协同、发现池期望）
- **L6** — 真实世界综合评分

## 开发约定

- 所有核心逻辑在 `hs_analysis/` 包内，不在 `scripts/`
- `scripts/` 只放运行入口和独立工具脚本
- 数据文件通过脚本生成，不手动修改
- 测试文件放在 `tests/` 或模块内（`hs_analysis/search/test_*.py`）
- import 路径使用 `from hs_analysis.xxx import yyy`
- 设计文档在 `thoughts/shared/designs/`，归档在 `thoughts/archive/`
- commit 格式: `feat: / fix: / cleanup: 简述`

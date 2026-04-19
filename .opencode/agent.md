# Agent Init — 炉石传说卡牌数值分析

## ⚡ Session 启动流程

每次新 session **第一条消息前**必须执行：

1. **平台检测**：运行 `uname -s 2>/dev/null || echo "Windows"` 自动识别当前 OS
   - macOS/Darwin → 使用 POSIX 命令（`rm -rf`, `&&`, `python3`）
   - Windows → 使用 PowerShell 语法（`Remove-Item -Recurse -Force`, `; if ($?) { }`, `python`）
   - 检测结果决定后续所有 shell 命令语法
2. **环境与命令**：`memory_search(query: "environment system preferences", tags: ["environment"], limit: 5)`
3. **项目约定**：`memory_search(query: "project rules conventions", tags: ["convention"], limit: 5)`
4. **项目知识**：`memory_search(query: "hs_analysis card modeling scoring", tags: ["project-knowledge"], limit: 10)`

如果 memory 中的环境信息与当前平台不匹配，重新检测并更新。

## 🔧 工具优先级

生成文件、执行代码、搜索代码时，**严格按以下优先级选择工具**：

1. **MCP 工具**（最高优先级）— 优先使用 MCP 提供的工具
   - 文件操作：`memory_ingest`, `memory_search` 等
   - 代码搜索：`ast_grep_search`, `ast_grep_replace`
   - GitHub：`github_*` 系列
   - Web：`web_search_exa`, `web_fetch_exa`, `searxng_web_search`
2. **OpenCode 内置工具**（次优先）— MCP 无对应工具时使用
   - `bash`, `read`, `write`, `edit`, `glob`, `grep`
   - `look_at`, `batch_read`
3. **子代理**（按需）— 复杂任务分解时使用
   - `codebase-locator`, `codebase-analyzer`, `pattern-finder`

**规则：** 同一功能有 MCP 和 OpenCode 两种工具时，选 MCP。

## 📐 大文件生成策略

当需要生成超过 **500 行**的文件时：

1. **先骨架后填充** — 先生成文件结构（imports、class 骨架、method 签名、docstring），再逐步填充实现
2. **分块写入** — 每次写入一个逻辑单元（一个类、一个函数组），不超过 200 行
3. **验证再继续** — 每写完一个模块，运行相关测试确认无误后再继续
4. **标记 TODO** — 未填充的部分用 `# TODO: implement` 标记，方便后续定位

## 🔬 研究任务流程

所有研究/调研性质的任务，**必须使用项目级 skill**：

- 卡牌建模研究 → 加载 `card-modeling` skill（`.opencode/skills/card-modeling/SKILL.md`）
- 文献调研、学术参考 → 使用 skill 中的 Academic References 和方法论
- 数据分析 → 遵循 skill 中的 5-phase 科学方法论（Collect → EDA → Model → Critique → Refine）

**触发词：** "调研"、"研究"、"分析"、"文献"、"方法论"、"评分模型"、"数据探索"

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

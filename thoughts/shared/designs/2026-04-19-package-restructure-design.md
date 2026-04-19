---
date: 2026-04-19
topic: "Package Restructure for Multi-Platform Support"
status: validated
---

# 炉石分析项目包重构设计

## Problem Statement

当前项目有 28 个 Python 脚本平铺在 `scripts/` 目录，存在以下核心问题：

1. **无法跨平台运行**：6 个脚本硬编码 Windows 路径 `D:/code/game/...`
2. **安全隐患**：HSReplay API key 明文写在 `fetch_hsreplay.py:38`
3. **代码重复**：V2 和 V7 评分引擎 ~400 行完全相同的逻辑（关键词、文本解析、条件EV）
4. **数据模型混乱**：同一张卡在不同层级有 3 种字段名（`dbfId`/`dbf_id`/`gameid`）
5. **无包结构**：依赖 `sys.path.insert` hack 实现模块间导入
6. **无依赖管理**：缺少 `requirements.txt` / `pyproject.toml`
7. **无配置系统**：所有参数硬编码在各脚本中

**目标**：将松散脚本重构为规范 Python 包，保持所有现有功能不变，支持 macOS/Linux/Windows 跨平台运行。

## Constraints

- **零功能回归**：重构后所有 44 个测试必须通过
- **渐进迁移**：不一次性重写，允许新旧并存过渡
- **保持现有数据文件格式**：JSON 报告结构不变（V2/V7/V8/L6 输出格式保持兼容）
- **不引入新外部依赖**（除已有的 numpy/scipy/openpyxl）
- **中文注释和中文输出保持不变**

## Approach

**渐进式包重构**——不推翻现有代码，而是添加一层规范包结构，逐步将逻辑迁移到包中。

选择此方案而非"全量重写"的原因：
- 项目已有 44 个通过的测试，全量重写风险太高
- 脚本间依赖关系复杂（RHEA → composite → submodel → game_state），全量重写难以保证正确性
- 渐进迁移允许边迁移边验证

### 被排除的方案

- **方案 B：全量重写**——风险高，测试覆盖不足
- **方案 C：仅修路径问题**——治标不治本，V2/V7 重复代码问题仍在

## Architecture

### 目标包结构

```
hs_analysis/
├── hs_analysis/                  # Python 主包
│   ├── __init__.py               # __version__ + 便捷导入
│   ├── config.py                 # 集中配置管理
│   │
│   ├── models/                   # 统一数据模型
│   │   ├── __init__.py
│   │   └── card.py               # Card dataclass + 字段映射
│   │
│   ├── data/                     # 数据源层
│   │   ├── __init__.py
│   │   ├── fetch_hsreplay.py     # HSReplay 抓取器
│   │   ├── fetch_hsjson.py       # HearthstoneJSON 抓取器
│   │   ├── fetch_iyingdi.py      # iyingdi 抓取器
│   │   └── build_unified_db.py   # 数据合并
│   │
│   ├── scorers/                  # 评分引擎
│   │   ├── __init__.py
│   │   ├── constants.py          # 共享常量（消除V2/V7重复）
│   │   ├── vanilla_curve.py      # L1 白板曲线拟合
│   │   ├── keyword_model.py      # L2 关键词三层模型
│   │   ├── text_parser.py        # L3 文本效果解析
│   │   ├── conditional_ev.py     # L5 条件期望值
│   │   ├── v2_engine.py          # V2 综合引擎
│   │   ├── v7_engine.py          # V7 综合引擎（含L6/L7校准）
│   │   └── v8_contextual.py      # V8 情境评分器
│   │
│   ├── evaluators/               # 对局评估器
│   │   ├── __init__.py
│   │   ├── submodel.py           # 4 子模型评估
│   │   ├── composite.py          # 复合评估器
│   │   └── multi_objective.py    # 多目标 Pareto 评估
│   │
│   ├── search/                   # 搜索引擎
│   │   ├── __init__.py
│   │   ├── game_state.py         # GameState 数据结构
│   │   ├── action.py             # Action 数据结构
│   │   └── rhea_engine.py        # RHEA 进化搜索
│   │
│   └── utils/                    # 工具模块
│       ├── __init__.py
│       ├── score_provider.py     # 评分查询桥接
│       ├── spell_simulator.py    # 法术效果模拟
│       └── bayesian_opponent.py  # 贝叶斯对手建模
│
├── tests/                        # 测试目录
│   ├── __init__.py
│   ├── test_integration.py
│   ├── test_score_provider.py
│   ├── test_v8_contextual_scorer.py
│   └── ...
│
├── data/                         # 数据文件（原 hs_cards/ 重命名）
│   ├── unified_standard.json
│   ├── v7_scoring_report.json
│   └── ...
│
├── scripts/                      # CLI 入口薄壳
│   ├── fetch_data.py             # python -m hs_analysis.data...
│   ├── score_v2.py
│   ├── score_v7.py
│   └── run_rhea.py
│
├── pyproject.toml                # 包定义 + 依赖声明
├── .env.example                  # 环境变量模板
└── README.md
```

### 迁移映射

每个现有脚本映射到新位置：

| 现有脚本 | 新位置 | 说明 |
|----------|--------|------|
| `scripts/game_state.py` | `hs_analysis/search/game_state.py` + `action.py` | 拆分 GameState 和 Action |
| `scripts/v2_scoring_engine.py` | `hs_analysis/scorers/v2_engine.py` | 调用共享模块 |
| `scripts/v7_scoring_engine.py` | `hs_analysis/scorers/v7_engine.py` | 调用共享模块 |
| `scripts/v8_contextual_scorer.py` | `hs_analysis/scorers/v8_contextual.py` | 保持类结构 |
| `scripts/composite_evaluator.py` | `hs_analysis/evaluators/composite.py` | 正常导入 |
| `scripts/submodel_evaluator.py` | `hs_analysis/evaluators/submodel.py` | 正常导入 |
| `scripts/multi_objective_evaluator.py` | `hs_analysis/evaluators/multi_objective.py` | 正常导入 |
| `scripts/rhea_engine.py` | `hs_analysis/search/rhea_engine.py` | 正常导入 |
| `scripts/score_provider.py` | `hs_analysis/utils/score_provider.py` | 正常导入 |
| `scripts/spell_simulator.py` | `hs_analysis/utils/spell_simulator.py` | 正常导入 |
| `scripts/bayesian_opponent.py` | `hs_analysis/utils/bayesian_opponent.py` | 正常导入 |
| `scripts/fetch_hsreplay.py` | `hs_analysis/data/fetch_hsreplay.py` | 配置外部化 |
| `scripts/fetch_hsjson.py` | `hs_analysis/data/fetch_hsjson.py` | 配置外部化 |
| `scripts/fetch_iyingdi_full.py` | `hs_analysis/data/fetch_iyingdi.py` | 路径修复 |
| `scripts/build_unified_db.py` | `hs_analysis/data/build_unified_db.py` | 路径修复 |
| `scripts/v2_vanilla_curve.py` | `hs_analysis/scorers/vanilla_curve.py` | 共享模块 |
| `scripts/l6_real_world.py` | `hs_analysis/scorers/v7_engine.py` (部分) | 合并到V7 |
| `scripts/classify_all_cards.py` | `hs_analysis/data/classify.py` | 数据处理 |
| `scripts/deep_analysis.py` | 保留在 scripts/ | 分析工具，不进包 |
| `scripts/quick_analysis.py` | 保留在 scripts/ | 分析工具，不进包 |

## Components

### 1. config.py — 集中配置管理

**职责**：
- 用 `pathlib.Path` 计算所有项目路径（替代硬编码路径）
- 从环境变量读取敏感信息（API key）
- 提供评分参数的默认值 + 覆盖机制

**设计要点**：
- `PROJECT_ROOT = Path(__file__).parent.parent` 自动定位
- `DATA_DIR = PROJECT_ROOT / "data"`
- `HSREPLAY_API_KEY = os.environ.get("HSREPLAY_API_KEY", "")` 从环境变量读取
- 所有路径用 `pathlib.Path`，不再拼字符串

### 2. models/card.py — 统一卡牌数据模型

**职责**：
- 定义标准化的 Card dataclass
- 提供从各数据源格式到标准模型的转换函数

**设计要点**：
- 统一字段名：`dbf_id`（int）、`name`（str）、`cost`（int）、`card_type`（str）、`attack`（int|None）、`health`（int|None）
- `from_hsjson(data: dict) -> Card` 工厂方法
- `from_iyingdi(data: dict) -> Card` 工厂方法
- `from_unified(data: dict) -> Card` 工厂方法
- 消除 `score_provider.py:116` 的字段名适配逻辑

### 3. scorers/constants.py — 共享评分常量

**职责**：
- 集中定义 V2/V7 共享的所有常量
- 消除 ~400 行重复代码

**包含内容**：
- `KEYWORD_TIERS` — 关键词分层
- `TIER_BASES` — 各层基础分值
- `EFFECT_PATTERNS` — 文本效果正则模式
- `CONDITION_DEFS` — 条件EV定义
- `CLASS_MULTIPLIER` — 职业系数

**设计要点**：
- V7 的扩展常量（更多关键词/模式）继承自基础集，用 `|` 合并
- V2 引擎和 V7 引擎都从 `constants.py` 导入，不再各自声明

### 4. data/ — 数据源层

**职责**：
- 每个数据源一个独立模块
- 所有路径通过 `config.py` 获取
- API key 通过 `config.py` 读取

### 5. scripts/ — CLI 入口薄壳

**职责**：
- 仅做 `from hs_analysis.xxx import main; main()` 转发
- 保持命令行使用习惯不变
- 逐步迁移过程中，旧脚本继续可用

## Data Flow

### 重构前

```
fetch_*.py (各自硬编码路径)
    → JSON 文件 (各格式不统一)
    → v2_engine.py (直接 json.load + 硬编码常量)
    → v7_engine.py (复制V2代码 + 扩展)
    → rhea_engine.py (sys.path.insert hack)
```

### 重构后

```
hs_analysis/data/fetch_*.py (config.py 路径 + env key)
    → JSON 文件 (不变)
    → models/card.py 统一转换
    → scorers/constants.py 共享常量
    → scorers/v2_engine.py (import constants)
    → scorers/v7_engine.py (import constants, 不再重复)
    → search/rhea_engine.py (正常 from import)
```

## Error Handling

- **配置缺失**：`config.py` 启动时检查必要环境变量，缺失时打印友好提示（不 crash）
- **数据文件缺失**：保持 V8 的优雅降级模式（`_load_json` 返回空 dict）
- **导入兼容**：`hs_analysis/__init__.py` 导出关键类，确保 `from hs_analysis import Card, GameState` 可用

## Testing Strategy

1. **迁移前**：运行所有 44 个测试，记录基线
2. **每步迁移后**：重新运行测试，确认零回归
3. **新增测试**：
   - `test_config.py` — 验证路径计算在不同 OS 上正确
   - `test_models_card.py` — 验证字段映射正确
   - `test_scorers_constants.py` — 验证 V2/V7 共享常量一致
4. **最终验证**：完整 pipeline 端到端测试

## Open Questions

1. **`hs_cards/` 重命名为 `data/`？** — 需要确认是否影响其他工具/脚本
2. **`scripts/` 保留多久？** — 建议保留到 V9 实现完成后统一清理
3. **libs/hearthstone-deckstrings/** — TypeScript 库，是否继续保留在 Python 项目中？

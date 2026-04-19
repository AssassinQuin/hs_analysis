# 炉石传说卡牌数值分析

> 通过数学建模量化卡牌价值，辅助竞技场决策分析

## 项目简介

本项目以《炉石传说》（Hearthstone）标准/狂野模式卡牌为研究对象，建立了一套**多版本卡牌评分引擎**和**竞技场决策系统**。从 V2 基础评分到 V8 上下文感知评分，再到 RHEA 搜索引擎，覆盖了从单卡评估到完整对局决策的全链路。

## 项目结构

```
hs_analysis/
├── hs_analysis/                 # 核心包
│   ├── config.py                # 全局配置
│   ├── data/                    # 数据获取与处理
│   │   ├── card_index.py        # 卡牌索引（O(1) 查询）
│   │   ├── card_cleaner.py      # 数据清洗流水线
│   │   ├── fetch_hsjson.py      # HearthstoneJSON API
│   │   ├── fetch_hsreplay.py    # HSReplay 数据获取
│   │   ├── fetch_iyingdi.py     # iyingdi 数据获取
│   │   ├── fetch_wild.py        # 狂野卡牌获取
│   │   ├── build_unified_db.py  # 统一数据库构建
│   │   └── build_wild_db.py     # 狂野去重构建
│   ├── models/                  # 数据模型
│   │   └── card.py              # Card 数据模型
│   ├── scorers/                 # 评分引擎
│   │   ├── vanilla_curve.py     # 白板曲线基准
│   │   ├── v2_engine.py         # V2 评分引擎
│   │   ├── v7_engine.py         # V7 评分引擎
│   │   ├── v8_contextual.py     # V8 上下文感知评分
│   │   ├── l6_real_world.py     # L6 真实世界评分
│   │   └── constants.py         # 评分常量
│   ├── evaluators/              # 评估器
│   │   ├── composite.py         # 复合评估器
│   │   ├── submodel.py          # 子模型评估器
│   │   └── multi_objective.py   # 多目标评估器
│   ├── search/                  # 搜索引擎
│   │   ├── rhea_engine.py       # RHEA 滚动水平线进化
│   │   ├── game_state.py        # 游戏状态管理
│   │   ├── lethal_checker.py    # 致命检测
│   │   ├── opponent_simulator.py# 对手模拟
│   │   ├── risk_assessor.py     # 风险评估
│   │   └── action_normalize.py  # 动作归一化
│   └── utils/                   # 工具模块
│       ├── score_provider.py    # 评分数据提供
│       ├── bayesian_opponent.py # 贝叶斯对手建模
│       └── spell_simulator.py   # 法术模拟
├── scripts/                     # 运行入口 & 工具脚本
│   ├── run_fetch.py             # 数据获取
│   ├── run_rhea.py              # RHEA 引擎运行
│   ├── run_score_v2.py          # V2 评分运行
│   ├── run_score_v7.py          # V7 评分运行
│   ├── analyze_meta_decks.py    # 环境套牌分析
│   ├── deep_analysis.py         # 深度分析
│   ├── decision_presenter.py    # 决策展示
│   ├── pool_quality_generator.py# 池质量报告
│   ├── rewind_delta_generator.py# 回溯差异报告
│   └── diag_*.py                # 诊断工具
├── tests/                       # 测试套件
├── hs_cards/                    # 卡牌数据文件
├── research/                    # 研究文档
└── libs/                        # 外部库
```

## 数学模型

### 白板测试（Vanilla Test）

基准公式：**期望属性 = 法力消耗 × 2 + 1**

一张 N 费的"白板"随从，其攻击力 + 生命值之和应接近 `2N + 1`。偏差部分即为特效的"隐性价值"。

### 关键词价值模型

| 关键词 | 分值 | 说明 |
|--------|------|------|
| 圣盾 | 2.0 | 等效一次额外存活 |
| 冲锋 | 2.0 | 即时场面影响力 |
| 发现 | 2.0 | 灵活选牌的价值 |
| 战吼 | 1.5 | 入场效果平均价值 |
| 亡语 | 1.5 | 延迟收益 |
| 突袭 | 1.5 | 当回合解场能力 |
| 吸血 | 1.5 | 生存恢复 |
| 风怒 | 1.5 | 双倍输出潜力 |
| 嘲讽 | 1.0 | 场控防御 |
| 潜行 | 1.0 | 保证一回合存活 |
| 过载 | -1.0 | 负面效果惩罚 |

### 评分体系演进

- **V2** — 基础属性 + 关键词评分
- **V7** — 基于 HSReplay 数据驱动的实绩评分
- **V8** — 上下文感知评分（回合数、场面饱和度、种族协同等）
- **L6** — 真实世界评分（综合多维度数据）

## 快速开始

```bash
# 安装依赖
pip install -e .

# 获取卡牌数据
python scripts/run_fetch.py

# 运行评分
python scripts/run_score_v7.py

# 运行测试
pytest
```

## 数据来源

- **HearthstoneJSON** — 社区维护的完整卡牌数据
- **HSReplay** — 对战胜率与卡牌排名数据
- **iyingdi** — 竞技场卡牌数据

## 依赖

- Python 3.11+
- 参见 `pyproject.toml`

## 许可

本项目仅供学习研究，卡牌数据版权归 Blizzard Entertainment 所有。

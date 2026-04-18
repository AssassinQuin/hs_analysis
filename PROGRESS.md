# 项目进展日志

> 炉石传说 AI 决策引擎 — 完整开发记录

---

## Phase 0: 项目初始化 (2026-04-17)

### Commit `1d29a87` — 项目初始化

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-17 09:26 |
| 内容 | 项目脚手架、初始脚本、传说卡分析数据 |

**完成事项:**
- [x] README.md 项目文档（含数学模型说明）
- [x] .opencode/agent.md agent 上下文配置
- [x] 10 个 Python 脚本整理到 scripts/ 目录
- [x] .gitignore（排除图片、缓存、数据库）
- [x] HS 卡牌 JSON 数据（传说卡分析结果）

**脚本清单（初始批次）:**

| 脚本 | 功能 |
|------|------|
| scrape_hs_cards.py | Blizzard CN API 抓取传说卡 |
| fetch_hsjson.py | HearthstoneJSON 数据获取 |
| quick_analysis.py | 快速分析 256 张传说卡 |
| full_analysis.py | 完整分析脚本 |
| deep_analysis.py | 深度分析：关键词、效果、属性分布 |
| explore_api.py | API 端点探索 |
| test_api.py / test_api_endpoints.py | API 测试 |
| show_slugs.py | 卡包 slug 展示 |
| rescrape_legendaries.py | 传说卡重抓取 |
| check_rarity.py | 稀有度检查 |

---

## Phase 0.5: 数据基础设施 (2026-04-17 ~ 04-18)

### 数据源确认

| 数据源 | 状态 | 说明 |
|--------|------|------|
| HearthstoneJSON | ✅ 主数据源 | 完整标准卡牌数据 |
| iyingdi API | ⚠️ 不完整 | 缺 49 张卡，仅作辅助 |
| python-hearthstone 9.20.2 | ✅ 已安装 | 卡牌解析库 |
| hearthstone-data | ✅ 已安装 | 卡牌数据包 |

### 新增脚本

| 脚本 | 功能 |
|------|------|
| scrape_iyingdi_standard.py | iyingdi 标准卡抓取 |
| build_hsjson_standard.py | 构建 HSJSON 标准卡数据 |
| detect_standard_sets.py | 检测标准卡组 |
| find_missing_cards.py | 缺失卡牌检测 |
| debug_missing_cards.py | 缺失卡调试 |
| check_missing_cards.py | 缺失卡检查 |
| analyze_cards.py | 通用卡牌分析 |
| analyze_card_pool.py | 卡池分析 |
| analyze_card_effects.py | 效果分析 |
| analyze_gaps.py | 差距分析 |
| analyze_specific_mechanics.py | 特定机制分析 |
| classify_all_cards.py | 综合分类器（71 类） |

### 数据文件

| 文件 | 内容 |
|------|------|
| hsjson_standard.json | 984 张标准卡牌完整数据 |
| hsjson_standard_compact.json | 精简版标准卡数据 |
| standard_legendaries_analysis.json | 256 张传说卡分析结果 |
| standard_legendaries_v2.json | V2 传说卡数据 |
| standard_complete.json | 完整标准卡 |
| iyingdi_*.json | iyingdi 抓取数据（多版本） |
| full_classification_report.md | 984/984 分类报告（100%覆盖） |
| card_pool_analysis.md | 卡池分析报告 |
| effect_analysis_report.md | 效果分析报告 |
| mechanics_detail_analysis.md | 机制细节分析 |
| missing_standard_cards.md | 缺失卡牌报告 |

### 卡牌分类系统

- **71 个文本模式类别**, 100% 覆盖 984 张卡
- 0 张未分类，0 张未被子模型覆盖
- 分类器: `scripts/classify_all_cards.py`

---

## Phase 1: V2 卡牌模型设计 + 任务规划 (2026-04-18 08:46)

### Commit `96b2ebf` — V2 任务工作流初始化

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-18 08:46 |
| 内容 | 状态跟踪、任务计划、V2 设计文档 |

**完成事项:**
- [x] state.json — 主项目跟踪器（5 阶段，18 任务 T001-T018）
- [x] V2 设计文档: `thoughts/shared/designs/2026-04-17-hearthstone-card-model-v2-design.md`
- [x] Phase 1 计划: `thoughts/shared/plans/2026-04-18-phase1-v2-model.md`
- [x] 5 个独立任务执行计划（T001-T005），含验收标准
- [x] T001 执行日志模板
- [x] deep_analysis.py + quick_analysis.py 暂存

**任务依赖图:**
```
T001 (曲线拟合) → T002 (关键词校准) → T003 (文本解析) → T004 (类型适配) → T005 (综合评分)
```

### Commit `6e5faa5` — 卡牌建模 Skill

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-18 08:56 |
| 内容 | 5 阶段科学工作流 Skill |

- [x] SKILL.md — 结构化方法论（collect → EDA → model V1 → critique → refine）
- [x] reference.md — 统计技术、输出模板、卡牌类型策略
- [x] 项目级 Skill 存放于 `skills/card-modeling/`

### Commit `4563ca7` + `065a203` — Session 自动化

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-18 09:01 ~ 09:09 |
| 内容 | 项目约定、Session 启动流程 |

- [x] .opencode/CONVENTIONS.md — 项目约定
- [x] .opencode/agent.md — 4 步 memory recall 启动流程
- [x] 跨平台命令适配策略（Windows PS 5.1 / Bash）

---

## Phase 1.5: 学术调研 + 完整 EV 设计 (2026-04-18)

### 设计文档产出

| 文档 | 内容 |
|------|------|
| 2026-04-17-hearthstone-card-model-v2-design.md | V2 三层卡牌价值模型设计 |
| 2026-04-18-mathematical-model-design.md | 完整数学模型设计（POMDP、EV公式、搜索算法） |
| 2026-04-18-ev-decision-engine-design.md | 7 子模型 EV 决策引擎设计 |
| 2026-04-18-hdt-analysis-report.md | HDT 集成方案分析 |
| 2026-04-18-hearthstone-projects-survey.md | 14 个 GitHub 开源项目 + 5 篇论文调研 |

### 七子模型 EV 框架

| 子模型 | 覆盖范围 | 卡牌数 | 职责 |
|--------|----------|--------|------|
| A: 场面状态 | 随从、手牌、英雄、buff | 776 | 核心场面评估 |
| B: 对手威胁 | 伤害、毁灭、沉默、冰冻 | 315 | 对手动作建模 |
| C: 持续效果 | 武器、光环、奥秘、地标 | 388 | 跨回合效果 |
| D: 触发概率 | 亡语、随机、战吼、灌注 | 581 | 随机效果期望值 |
| E: 环境智能 | 任务、发现、奖励 | 91 | 元数据驱动 |
| F: 卡池 | 发现、暗影赐福、随机 | 207 | 池定义与权重 |
| G: 玩家选择 | 抉择卡 | 23 | EV = max(A, B) |

### 数学模型核心公式

- **POMDP 形式化**: belief state 表示隐藏信息
- **状态评估**: 6 项加权线性组合
- **EV 公式**: 覆盖确定性/随机/条件/延迟/选择 5 种效果类型
- **Discover EV**: Order Statistics `E[max] = Σ v_i × [i^k - (i-1)^k] / N^k`
- **对手建模**: 贝叶斯推断 + Dirichlet 先验
- **搜索算法**: Top-K Beam Search (K=8, depth=2, <3s)

---

## Phase 1 继续执行: T001 非线性白板曲线拟合 (2026-04-18)

### 执行结果

**脚本**: `scripts/v2_vanilla_curve.py`
**参数输出**: `hs_cards/v2_curve_params.json`

**拟合公式**: `expected_stats(mana) = 3.187 × mana^0.697 - 0.014`

| Mana | N | 实际 | V1(2N+1) | V1残差 | V2预测 | V2残差 | 改善 |
|------|---|------|----------|--------|--------|--------|------|
| 0 | 1 | 0.0 | 1.0 | -1.0 | -0.0 | +0.0 | +1.0 |
| 1 | 1 | 2.0 | 3.0 | -1.0 | 3.2 | -1.2 | -0.2 |
| 2 | 7 | 7.0 | 5.0 | +2.0 | 5.2 | +1.8 | +0.2 |
| 3 | 29 | 7.2 | 7.0 | +0.2 | 6.8 | +0.4 | -0.2 |
| 4 | 35 | 8.3 | 9.0 | -0.7 | 8.4 | -0.0 | +0.6 |
| 5 | 38 | 9.0 | 11.0 | -2.0 | 9.8 | -0.8 | +1.2 |
| 6 | 32 | 10.4 | 13.0 | -2.6 | 11.1 | -0.7 | +1.9 |
| 7 | 34 | 12.6 | 15.0 | -2.4 | 12.4 | +0.2 | +2.2 |
| 8 | 23 | 13.7 | 17.0 | -3.3 | 13.6 | +0.1 | +3.3 |
| 9 | 17 | 13.8 | 19.0 | -5.2 | 14.7 | -1.0 | +4.3 |
| 10 | 9 | 17.0 | 21.0 | -4.0 | 15.9 | +1.1 | +2.9 |

**模型对比:**

| 指标 | V1 (2N+1) | V2 (幂律) | 改善 |
|------|-----------|----------|------|
| MAE | 2.22 | 0.66 | **70.1%** |
| RMSE | 2.66 | 0.87 | 67.3% |

**验证结果:**
- [x] 拟合残差均值 < 1.0 (实际 0.66)
- [x] 参数 b ∈ [0.65, 0.95] (实际 0.697)
- [x] RMSE < V1 RMSE
- [x] 脚本可独立运行
- [x] 输出包含新旧对比表

---

## 整体进度总览

### 已完成 ✅

| # | 任务 | 产出 |
|---|------|------|
| 1 | 数据基础设施 | 984 张标准卡 JSON, 多源抓取脚本 |
| 2 | 卡牌分类系统 | 71 类, 100% 覆盖, classify_all_cards.py |
| 3 | 七子模型 EV 框架 | 7 子模型映射, 完整覆盖报告 |
| 4 | 数学模型设计 | 5 篇设计文档, 完整公式体系 |
| 5 | V2 卡牌价值模型设计 | 三层设计, 任务计划 T001-T005 |
| 6 | 学术调研 | 5+ 论文, 14 个 GitHub 项目 |
| 7 | HDT 集成方案 | 方案 B: C# 插件 + Python 后端 |
| 8 | T001 白板曲线拟合 | v2_vanilla_curve.py + v2_curve_params.json |

### 进行中 🔄

| # | 任务 | 依赖 |
|---|------|------|
| - | T002 关键词三层校准 | T001 ✅ |

### 待开始 ⏳

| 优先级 | 任务 | 说明 |
|--------|------|------|
| 🔴 P0 | T002-T005 V2 模型剩余 | 关键词校准 → 文本解析 → 类型适配 → 综合评分 |
| 🔴 P0 | 状态评估函数 | 数学模型 → 代码 |
| 🔴 P0 | EV 计算器 | 5 种效果类型 |
| 🟡 P1 | 卡池数据库 | 解析随机效果池定义 |
| 🟡 P1 | 发现规则引擎 | 自排除、职业加权、过滤 |
| 🟡 P1 | 贝叶斯对手模型 | HSReplay + 实时更新 |
| 🟡 P1 | 动作枚举+剪枝 | 合法动作枚举、剪枝规则 |
| 🟢 P2 | Top-K Beam Search | depth-2 搜索 |
| 🟢 P2 | HSReplay API 集成 | 每职业 Top5 卡组缓存 |
| 🟢 P2 | HDT C# 插件 | IPC 桥接 |
| 🟢 P2 | 权重优化 | ~21 个参数进化算法 |

### 关键设计决策

1. **轻量 EV 建模** 而非完整模拟器（区别于所有学术方案）
2. **HearthstoneJSON** 而非 iyingdi（数据完整性）
3. **7 子模型** 而非 6 个（增加 G: 玩家选择）
4. **方案 B 架构** HDT 插件 + Python 后端

### Git 提交历史

| Hash | 日期 | 说明 |
|------|------|------|
| `1d29a87` | 04-17 09:26 | 项目初始化 |
| `96b2ebf` | 04-18 08:46 | V2 任务工作流初始化 |
| `6e5faa5` | 04-18 08:56 | 卡牌建模 Skill |
| `4563ca7` | 04-18 09:01 | 项目约定文件 |
| `065a203` | 04-18 09:09 | Session 启动流程 |
| *(pending)* | 04-18 | T001 + 数据/分析/设计/分类 全量提交 |

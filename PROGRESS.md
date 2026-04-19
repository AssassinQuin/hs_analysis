# 项目进展日志

> 炉石传说 AI 决策引擎 — 完整开发记录
> 最后更新：2026-04-19

---

## Phase 0: 项目初始化 (2026-04-17)

### Commit `1d29a87` — 项目初始化

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-17 09:26 |
| 内容 | 项目脚手架、初始脚本、传说卡分析数据 |

- [x] README.md 项目文档
- [x] 10 个 Python 脚本整理到 scripts/
- [x] HS 卡牌 JSON 数据

---

## Phase 0.5: 数据基础设施 (2026-04-17 ~ 04-18)

### 数据源确认

| 数据源 | 状态 | 说明 |
|--------|------|------|
| HearthstoneJSON | ✅ 主数据源 | 完整标准卡牌数据 |
| iyingdi API | ⚠️ 不完整 | 缺 49 张卡，仅作辅助 |
| HSReplay | ✅ 校准源 | 卡牌使用率/胜率排名缓存 |

### 产出

- 984→1015 张标准卡入库（unified_standard.json）
- 6174 张全卡（iyingdi_all_raw.json）→ 5209 张狂野去重
- CardIndex O(1) 多维度索引
- Card cleaner：56 个关键词正则，中英文兼容
- 71 类文本分类器，100% 卡牌覆盖

---

## Phase 1: V2 评分模型 (2026-04-18)

### Commit `96b2ebf` ~ T001-T005 完成

**V2 幂律曲线拟合**: `expected_stats(mana) = 3.187 × mana^0.697 - 0.014`

| 指标 | V1 (2N+1) | V2 (幂律) | 改善 |
|------|-----------|----------|------|
| MAE | 2.22 | 0.66 | **70.1%** |
| RMSE | 2.66 | 0.87 | 67.3% |

**任务链**: T001(曲线拟合) → T002(关键词校准) → T003(文本解析) → T004(类型适配) → T005(综合评分)

---

## Phase 2: V7+ 数据驱动评分 (2026-04-18 ~ 04-19)

### 评分管线演进

```
L1(白板曲线) → L2(关键词分层) → L3(28正则文本) → L4(类型基线)
  → L5(37条件EV) → L6(HSReplay CPI混合) → L7(报告生成)
```

- **V7**: L1→L7 完整管线 + HSReplay Rankings 校准
- **V8**: 7 个上下文修正因子（回合曲线、类型上下文、池质量、亡语EV、斩杀加速、回溯EV、协同）
- **L6**: `V2 × (1-θ) + CPI × θ × max`, θ=0.3

### 数据文件

| 文件 | 内容 |
|------|------|
| v7_scoring_report.json | V7 评分全量 |
| v2_scoring_report.json | V2 评分 |
| l6_scoring_report.json | L6 评分 |
| pool_quality_report.json | 种族/类型池质量 |
| card_turn_data.json | HSReplay 平均回合 |
| rewind_delta_report.json | 回溯卡EV增量 |

---

## Phase 3: V9 RHEA 决策引擎 (2026-04-19)

### 核心组件

| 模块 | 文件 | 功能 |
|------|------|------|
| RHEA 搜索 | search/rhea_engine.py | 进化算法搜索最优出牌 |
| 斩杀检测 | search/lethal_checker.py | DFS 致命检测 |
| 游戏状态 | search/game_state.py | GameState/Minion/HeroState |
| 法术模拟 | utils/spell_simulator.py | 10 正则法术效果解析 |
| 对手模拟 | search/opponent_simulator.py | 贪心对手模型 |
| 风险评估 | search/risk_assessor.py | AoE脆弱性/超铺惩罚 |
| 动作规范 | search/action_normalize.py | 合法动作枚举+交叉修复 |

### 综合评估器

| 模块 | 文件 | 功能 |
|------|------|------|
| 复合评估 | evaluators/composite.py | 3轴加权融合 (tempo+value+survival) |
| 子模型 | evaluators/submodel.py | 场面/威胁/持续效果/触发4子模型 |
| 多目标 | evaluators/multi_objective.py | 3维Pareto + 阶段自适应标量化 |

### 集成测试

- 15 批次 HDT 真实卡组场景测试 (batch01→batch15)
- 覆盖：快速铺场、控制后期、OTK斩杀、疲劳、极端场面等
- **213→233 测试通过**

---

## Phase 4: V10 引擎大修 (2026-04-19)

### Phase 4a: 基础修复 (8 个 bug fix)

**Commit `3d1a409`**

| # | 修复 | 文件 |
|---|------|------|
| 1 | 斩杀检测：冲锋随从必须尊重嘲讽 | lethal_checker.py |
| 2 | 风怒双击：`has_attacked_once` 标记 | game_state.py + rhea_engine.py |
| 3 | 过载解析：中文正则 + PLAY时设定 + END_TURN扣减 | rhea_engine.py |
| 4 | 剧毒即杀：伤害后 target.health=0 | rhea_engine.py |
| 5 | 连击追踪：`cards_played_this_turn` 列表 | game_state.py |
| 6 | 疲劳伤害：递增计数器 | rhea_engine.py |
| 7 | 潜行打破：攻击后清除 | rhea_engine.py |
| 8 | 冰冻效果：`frozen_until_next_turn` 标记 | game_state.py + rhea_engine.py |

**设计文档**: `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### Phase 4b: 游戏规则研究

**Commit `c76e902`** — 1017 行，10 章 61 节

| 章节 | 内容 |
|------|------|
| Ch1 | 游戏区域（手牌10、场面7、奥秘5） |
| Ch2 | 法力系统（水晶增长、过载、临时法力） |
| Ch3 | 战斗系统（6阶段攻击序列、嘲讽/冲锋/突袭/风怒/圣盾/剧毒/潜行/冰冻/免疫/吸血） |
| Ch4 | 关键词机制（战吼/亡语/发现/抉择/连击/激励/过载/流放/复生/超额/腐蚀） |
| Ch5 | 触发/光环系统（Phase/Sequence、Whenever vs After、光环重算） |
| Ch6 | 奥秘系统（各职业触发条件、反制特殊规则） |
| Ch7 | 英雄技能（11职业、灌注升级路径、刷新机制） |
| Ch8 | 抽牌/疲劳（爆牌→墓地、疲劳递增1/2/3/…） |
| Ch9 | 2026特殊机制（兆示/裂变/延系/回溯/黑暗之赐/寓言/巨型/休眠/手牌定位/任务） |
| Ch10 | 附录（阶段解析、死亡创建步骤、触发队列不可变性） |

**研究来源**: wiki.gg Advanced Rulebook、Blizzard 补丁说明、outof.games

### Phase 4c: V10 状态感知评分框架设计

**Commit `788c461`**

诊断出 3 个根本缺陷：
1. **线性叠加** — 无法表达"斩杀=无限价值"
2. **静态vs动态脱节** — 评分不考虑游戏状态
3. **规则脱节** — 关键词分值无规则依据

三层架构设计：
- **CIV**（基础层）：V2→V7 离线管线 + 关键词交互 + 2026机制公式
- **SIV**（交互层）：8 个运行时状态修正器
- **BSV**（全局层）：softmax 非线性融合

**设计文档**: `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`

### Phase 4d: V10 评分实现 ✨

**Commit `a1b3221`** — 16 文件, 2758 行新增

| 模块 | 文件 | 功能 | 测试 |
|------|------|------|------|
| SIV | evaluators/siv.py | 8 状态修正器 + siv_score() 入口 | 54 |
| BSV | evaluators/bsv.py | softmax 融合 + 3轴 + 斩杀覆盖 | 24 |
| 关键词交互 | scorers/keyword_interactions.py | 8 条规则推导交互 | 168 |
| 机制基础值 | scorers/mechanic_base_values.py | 9 个2026机制CIV公式 | 含 |
| 集成 | evaluators/composite.py | V10_ENABLED 开关 + evaluate_v10() | 7 |
| A/B 对比 | evaluators/test_v10_ab_comparison.py | V10 vs legacy 验证 | 4 |
| 性能 | evaluators/test_v10_performance.py | 基准测试 | 3 |

**8 个 SIV 修正器**:

| # | 修正器 | 关键公式 | 规则章节 |
|---|--------|---------|---------|
| 1 | 斩杀感知 | `1 + (1-hp/30)² × 3.0` | Ch3 战斗 |
| 2 | 嘲讽约束 | `1 + 0.3 × 敌方嘲讽数` | Ch3.2 嘲讽 |
| 3 | 节奏窗口 | 法力曲线匹配度惩罚 | Ch2 法力 |
| 4 | 手牌位置 | 外域/裂变位置奖励 | Ch9.2 裂变 |
| 5 | 触发概率 | 铜须/瑞文/光环倍率 | Ch5 触发 |
| 6 | 种族协同 | 同族计数 × 0.1 | Ch9.3 延系 |
| 7 | 累积进度 | 灌注/兆示/任务阈值跳跃 | Ch9.1/9.7/9.10 |
| 8 | 反制感知 | 冰冻/奥秘/AoE威胁修正 | Ch6 奥秘 |

**BSV softmax 融合**:

```
raw = [tempo×w_t, value×w_v, survival×w_s]
weights = softmax(raw / 0.5)   # temperature=0.5
BSV = Σ weights[i] × raw[i]
if lethal_possible → BSV = 999.0
```

**阶段权重**: 早期(t=1.3,v=0.7,s=0.5) / 中期(1.0,1.0,1.0) / 后期(0.7,1.2,1.5)

**8 条关键词交互**（规则推导）:

| 交互 | 效果 | 规则源 |
|------|------|--------|
| 剧毒 vs 圣盾 | ×0.1 | Ch3.5+3.6 |
| 潜行+嘲讽 | 嘲讽=0 | Ch3.2+3.7 |
| 免疫+嘲讽 | 嘲讽=0 | Ch3.2+3.9 |
| 冰冻+风怒 | ×0.5 | Ch3.4+3.8 |
| 吸血 vs 圣盾敌人 | 吸血=0 | Ch3.5+3.10 |
| 复生+亡语 | ×1.5 | Ch4.2+4.9 |
| 铜须+战吼 | ×2.0 | Ch4.1 |
| 瑞文+亡语 | ×2.0 | Ch4.2 |

**测试**: 493 通过（260 新增 + 233 原有），零回归

---

## 整体进度总览 (2026-04-19)

### 已完成 ✅

| # | 阶段 | 产出 | 测试 |
|---|------|------|------|
| 1 | 数据管线 | 1015 标准卡 + 5209 狂野卡, CardIndex | 51+35+6=92 |
| 2 | V2 评分 | 幂律曲线 MAE 0.66 | 含 |
| 3 | V7 评分 | HSReplay 校准完整管线 | 16 |
| 4 | V8 评分 | 7 上下文修正因子 | 16 |
| 5 | V9 RHEA 引擎 | 搜索+斩杀+状态+模拟全套 | 150+ |
| 6 | 综合评估器 | 3轴复合 + 4子模型 + Pareto | 含 |
| 7 | V10 Phase 1 | 8 个基础 bug 修复 | 20 |
| 8 | 游戏规则 | 1017 行完整规则参考 | 0 (文档) |
| 9 | V10 评分框架设计 | 三层架构 CIV+SIV+BSV | 0 (设计) |
| 10 | V10 评分实现 | SIV+BSV+交互+机制+集成 | 260 |
| **总计** | | **32 源文件, 10022 行** | **493 通过** |

### 进行中 🔄

无当前进行中的任务。

### 待开始 ⏳

| 优先级 | 任务 | 说明 | 前置依赖 |
|--------|------|------|---------|
| 🔴 P1 | V10 Phase 2: 附魔框架 | Enchantment + TriggerDispatcher | 设计完成 |
| 🔴 P1 | V10 Phase 2: 战吼派发 | 文本解析→效果应用 | 附魔框架 |
| 🔴 P1 | V10 Phase 2: 亡语队列 | 板位顺序执行，5层级联 | 触发系统 |
| 🔴 P1 | V10 Phase 2: 光环引擎 | 连续附魔重算 | 附魔框架 |
| 🔴 P1 | V10 Phase 2: 发现框架 | 池生成+三选一最优 | 评估器 |
| 🔴 P1 | V10 Phase 2: 地标支持 | 新卡类型+耐久+冷却 | GameState |
| 🟡 P2 | V10 Phase 3: 灌注系统 | 英雄技能升级 | Phase 2 |
| 🟡 P2 | V10 Phase 3: 手牌位置 | 外域/裂变/手牌定位 | Phase 2 |
| 🟡 P2 | V10 Phase 3: 兆示+巨型 | 计数器+附属物召唤 | Phase 2 |
| 🟡 P2 | V10 Phase 3: 延系 | 上回合种族/学派追踪 | Phase 2 |
| 🟡 P2 | V10 Phase 3: 任务/黑暗之赐/回溯 | 进度追踪+分支模拟 | Phase 2 |
| 🟢 P3 | 评分校准 | 温度/斩杀比例调优 | 实战数据 |
| 🟢 P3 | 性能基准 | 75ms RHEA 目标 | Phase 2 |
| 🟢 P3 | 狂野评分 | 5209 卡池扩展 | Phase 3 |

---

## Git 提交历史

| Hash | 日期 | 说明 |
|------|------|------|
| `1d29a87` | 04-17 | 项目初始化 |
| `96b2ebf` | 04-18 | V2 任务工作流 |
| `6e5faa5` | 04-18 | 卡牌建模 Skill |
| `4563ca7` | 04-18 | 项目约定文件 |
| `065a203` | 04-18 | Session 启动流程 |
| *(multiple)* | 04-18~19 | T001-T005 + 数据/分析/分类 |
| `3d1a409` | 04-19 | V10 engine overhaul 设计 |
| `6d49ddf` | 04-19 | V10 Phase 1 基础修复 + 文档约定 |
| `c76e902` | 04-19 | 完整游戏规则参考文档 |
| `788c461` | 04-19 | V10 评分框架设计 + PROJECT_STATE v3.0 |
| `46f7007` | 04-19 | V10 评分实现设计 |
| `1c4c3af` | 04-19 | V10 评分实现计划 |
| `a1b3221` | 04-19 | V10 评分实现 (SIV+BSV+集成, 493测试) |

---

## 架构决策摘要

| # | 决策 | 理由 |
|---|------|------|
| D001 | HearthstoneJSON 主数据源 | 100% 覆盖，社区维护 |
| D002 | 轻量 EV 建模 | 80% 精度 × 10% 复杂度 |
| D006 | RHEA 进化搜索 | 探索/利用平衡，75ms 预算 |
| D009 | 三阶段渐进改造 | 233 测试不回归 |
| D010 | 附魔框架关键多米诺 | 所有触发型机制的基础 |
| D014 | 三层评分 CIV+SIV+BSV | 规则→价值修正器映射 |
| D015 | softmax 非线性融合 | 线性无法表达斩杀=∞ |
| D016 | 规则推导关键词交互 | 确定性交互逻辑，非经验常数 |

完整决策记录: `thoughts/DECISIONS.md`

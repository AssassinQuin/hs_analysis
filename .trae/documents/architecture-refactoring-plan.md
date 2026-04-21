# 炉石传说 AI 决策引擎 — 架构重构优化方案

> **原则**：不兼容旧版本，仅保留最新活跃版本。消除冗余、统一版本线、简化代码结构。

---

## 一、当前问题诊断

### 1.1 版本碎片化
代码中同时存在 **V2 / V7 / V8 / V10(BSV/SIV) / L6 / V9(RHEA) / V11(Pipeline)** 共 7 个版本概念：
- **评分链**：V2 → V7 → V8 → SIV → BSV，层层叠加，V2 和 L6 已无实际价值
- **搜索链**：V9(RHEA) 仍在运行，V11(Pipeline) 正在开发但未激活
- **Card 字段**：保留 `v2_score`、`l6_score`、`v7_score` 三个旧版字段

### 1.2 代码冗余
| 冗余类型 | 详情 |
|---------|------|
| V2/V7 评分引擎重复 | `v2_engine.py` 和 `v7_engine.py` 的评分函数几乎逐行复制 |
| HSCardDB / CardIndex 重叠 | 两者都实现多属性索引和组合查询 |
| V11 mechanics 死代码 | engine_v11/mechanics/ 下 12 个 Handler 全是透传包装器，且从未在运行时被调用 |
| 多目标评估重复 | `bsv.py` 和 `multi_objective.py` 实现几乎相同的三维评估 |
| 阶段检测重复 | 4 个文件各自实现 `early/mid/late` 阶段判断，且阈值不一致 |
| Card 工厂方法重复 | `from_hsjson()` 和 `from_unified()` 完全相同 |

### 1.3 巨型模块
- `rhea_engine.py`（~1500 行），`apply_action()` 单函数 460+ 行，承担 20+ 种机制模拟
- `v7_engine.py` 的 `main()` 混合评分、统计、输出、保存

### 1.4 死代码/无效文件
- `l6_real_world.py`：无任何模块导入，输出文件不存在
- `deep_analysis.py`、`analyze_meta_decks.py`：依赖已删除的数据文件
- `diag_scores.py`、`diag_conditions.py`：一次性诊断脚本
- `decision_presenter.py`：导入路径已过时
- 9 个 `test_v9_hdt_batch*` 文件：V9 批量回归测试，维护成本高

---

## 二、重构目标架构

### 2.1 统一版本线

重构后的清晰架构：

```
数据层 (data/)
  ↓
静态评分层 (scorers/) — 仅保留 V7 静态引擎 + V8 上下文评分
  ↓
状态评估层 (evaluators/) — 仅保留 BSV 三轴融合 + SIV 单卡评分
  ↓
搜索层 (search/) — 仅保留 V11 Pipeline（当前目标）或 RHEA（过渡期）
```

### 2.2 重构后目录结构

```
hs_analysis/
├── __init__.py
├── config.py                    # 清理旧 V2 路径常量
├── data/
│   ├── __init__.py
│   ├── hsdb.py                  # 保留：核心数据库（合并 CardIndex 功能）
│   ├── card_index.py            # 删除：功能合并入 hsdb.py
│   ├── card_cleaner.py          # 保留
│   ├── fetch_hsjson.py          # 保留
│   ├── fetch_hsreplay.py        # 保留（清理 V2 引用）
│   ├── fetch_iyingdi.py         # 保留
│   ├── build_unified_db.py      # 保留
│   └── build_wild_db.py         # 保留
├── models/
│   ├── __init__.py
│   └── card.py                  # 重构：删除 v2_score/l6_score，合并重复工厂方法
├── scorers/
│   ├── __init__.py
│   ├── constants.py             # 保留（清理 V2 专用常量）
│   ├── vanilla_curve.py         # 保留
│   ├── v7_engine.py             # 保留（作为唯一静态评分引擎，重命名）
│   ├── v8_contextual.py         # 保留
│   ├── keyword_interactions.py  # 保留
│   └── mechanic_base_values.py  # 保留
├── evaluators/
│   ├── __init__.py
│   ├── submodel.py              # 保留
│   ├── composite.py             # 保留（清理 V10 开关逻辑，默认启用）
│   ├── bsv.py                   # 保留
│   └── siv.py                   # 保留
├── search/
│   ├── __init__.py
│   ├── game_state.py            # 保留
│   ├── rhea_engine.py           # 保留（过渡期），后续考虑拆分 apply_action
│   ├── lethal_checker.py        # 保留
│   ├── opponent_simulator.py    # 保留
│   ├── risk_assessor.py         # 保留
│   ├── action_normalize.py      # 保留
│   ├── rewind.py                # 保留
│   ├── [30+ 机制处理模块]        # 保留
│   └── engine_v11/              # 保留，但删除 mechanics/ 死代码
│       ├── pipeline.py
│       ├── strategic.py
│       ├── tactical.py
│       ├── attack_planner.py
│       ├── action_pruner.py
│       ├── factors/             # 保留
│       └── models/              # 保留
├── utils/
│   ├── __init__.py
│   ├── score_provider.py        # 保留（清理 L6 引用）
│   ├── bayesian_opponent.py     # 保留
│   └── spell_simulator.py       # 保留
scripts/
├── run_rhea.py                  # 保留
├── run_score_v7.py              # 保留（重命名，作为唯一评分脚本）
├── run_fetch.py                 # 保留
├── pool_quality_generator.py    # 保留
├── rewind_delta_generator.py    # 保留
├── decision_presenter.py        # 删除
├── run_score_v2.py              # 删除
├── diag_scores.py               # 删除
├── diag_conditions.py           # 删除
├── deep_analysis.py             # 删除
└── analyze_meta_decks.py        # 删除
```

---

## 三、重构步骤

### Phase 1：删除死代码和废弃模块（低风险）

#### 步骤 1.1：删除无引用的废弃评分层
- **删除** `hs_analysis/scorers/l6_real_world.py`
- **删除** `hs_analysis/scorers/v2_engine.py`

#### 步骤 1.2：删除废弃的 CLI 脚本
- **删除** `scripts/run_score_v2.py`
- **删除** `scripts/diag_scores.py`
- **删除** `scripts/diag_conditions.py`
- **删除** `scripts/deep_analysis.py`
- **删除** `scripts/analyze_meta_decks.py`
- **删除** `scripts/decision_presenter.py`

#### 步骤 1.3：删除废弃数据文件
- **删除** `hs_cards/v2_scoring_report.json`
- **删除** `hs_cards/v2_keyword_params.json`

#### 步骤 1.4：删除 V11 mechanics 死代码
- **删除** `hs_analysis/search/engine_v11/mechanics/` 整个目录
  - 这些 Handler 全是透传包装器，且 MechanicRegistry 从未在运行时被调用
  - V11 Pipeline 实际依赖 V10 的 `apply_action()` 进行状态转换

#### 步骤 1.5：删除冗余评估器
- **删除** `hs_analysis/evaluators/multi_objective.py`
  - 与 `bsv.py` 功能高度重复（均为 Tempo/Value/Survival 三维评估）
  - BSV 是更新的实现，且已被 composite.py 使用

#### 步骤 1.6：清理废弃测试文件
- **删除** `hs_analysis/search/test_v9_hdt_batch02_deck_random.py` 及其 8 个 batch 文件
  - 这些是 V9 RHEA 的回归测试，文件名表明是临时测试数据
  - 删除缺失的 batch03-05、batch08-09 表明这些测试已不完整
- **删除** `hs_analysis/search/test_phase3_state.py`（如果存在，验证后处理）
- **删除** `tests/test_wild_dedup.py` 中对旧版本的引用

---

### Phase 2：清理配置和常量（中风险）

#### 步骤 2.1：清理 config.py
- **删除** `V2_CURVE_PARAMS_PATH`、`V2_KEYWORD_PARAMS_PATH`、`V2_REPORT_PATH` 常量
- **删除** `CARD_LIST_PATH`（如无引用）

#### 步骤 2.2：清理 constants.py
- **删除** 所有 `_V2` 后缀的常量：`KEYWORD_TIERS_V2`、`KEYWORD_CN_V2`、`CONDITION_DEFS_V2`
- **重命名** `KEYWORD_TIERS_V7` → `KEYWORD_TIERS`，`EFFECT_PATTERNS_V7` → `EFFECT_PATTERNS`，`CONDITION_DEFS_V7` → `CONDITION_DEFS`
- **更新** 所有引用这些常量的模块（`v7_engine.py`、`v8_contextual.py` 等）

#### 步骤 2.3：清理 score_provider.py
- **删除** `field_map` 中的 `"l6": "L6"` 条目
- **简化** 为仅支持 v7_score 字段

---

### Phase 3：重构数据模型（中风险）

#### 步骤 3.1：简化 Card dataclass
- **删除** `v2_score` 和 `l6_score` 字段
- **添加类型标注**：`mechanics: list[str] = field(default_factory=list)` 替代 `mechanics: list = None`
- **删除** `__post_init__` 方法（不再需要）
- **更新** `to_dict()` 方法：删除 `v2_score`、`l6_score` 字段

#### 步骤 3.2：合并重复的工厂方法
- **合并** `from_hsjson()` 和 `from_unified()` 为单一方法（两者完全相同）
  - 保留 `from_unified()` 名称（更通用），将 `from_hsjson()` 指向它
  - 或者两者都保留为 `from_unified` 的别名

#### 步骤 3.3：更新所有引用 Card 旧字段的代码
- 搜索所有 `v2_score`、`l6_score` 引用并替换/删除
- 更新 `fetch_hsreplay.py` 中对 `v2_scoring_report.json` 的引用

---

### Phase 4：统一共享工具函数（中风险）

#### 步骤 4.1：抽取阶段检测工具函数
- **创建** `hs_analysis/utils/game_phase.py`（或在现有 utils 模块中添加）
- **定义** 统一的 `detect_phase(turn: int) -> str` 函数
- **统一阈值**：采用 `turn <= 4` early, `<= 7` mid, else late（目前 4/5 个模块使用的值）
- **更新** 所有 4 处重复实现：`v8_contextual.py`、`bsv.py`、`rhea_engine.py`、`factor_base.py`

#### 步骤 4.2：抽取伤害估算工具函数
- **统一** `strategic.py` 的 `_max_damage_bound()`、`rhea_engine.py` 的 `next_turn_lethal_check()`、`submodel.py` 的 `eval_threat()` 中的重复伤害计算逻辑
- **放置** 在 `hs_analysis/utils/combat.py` 或类似位置

---

### Phase 5：简化评估器链（中风险）

#### 步骤 5.1：移除 composite.py 的 V10 开关
- **删除** `V10_ENABLED` 全局变量和 `set_v10_enabled()` 函数
- **让** `evaluate()` 直接调用 BSV 路径（目前已是更优路径）
- **保留** 旧路径作为 `evaluate_legacy()` 或直接删除

#### 步骤 5.2：清理 composite.py 注释
- 更新文档字符串：删除 "V2+L6" 引用，改为 "V7/V8 + BSV"

---

### Phase 6：V7 引擎重命名和清理（低风险）

#### 步骤 6.1：重命名 v7_engine.py
- **重命名** `hs_analysis/scorers/v7_engine.py` → `hs_analysis/scorers/scoring_engine.py`
  - 作为唯一的静态评分引擎，不再需要版本号前缀
- **更新** 所有 `from hs_analysis.scorers.v7_engine import ...` 引用

#### 步骤 6.2：清理 v7_engine.py 内部
- **删除** 未使用的 `Counter` 导入
- **清理** `main()` 函数：删除评分报告生成逻辑（已由 `run_score_v7.py` 脚本承担）

#### 步骤 6.3：重命名 run_score_v7.py
- **重命名** `scripts/run_score_v7.py` → `scripts/run_scoring.py`
- **更新** 内部导入路径

---

### Phase 7：清理 engine_v11 引用（低风险）

#### 步骤 7.1：更新 engine_v11/__init__.py
- **删除** 对已删除 mechanics 模块的引用

#### 步骤 7.2：更新 pipeline.py
- **删除** `MechanicRegistry` 的构建代码（已删除 mechanics 目录）
- **简化** pipeline 仅保留 Strategy → Prune → Tactical → Factor Eval 流程

---

### Phase 8：测试更新（高优先级）

#### 步骤 8.1：更新现有测试
- 更新所有因删除/重命名导致的导入路径变更
- 更新引用 `v2_score`、`l6_score` 的测试用例
- 更新引用 `_V2` 后缀常量的测试用例

#### 步骤 8.2：运行全量测试验证
- 执行 `pytest` 确保所有测试通过
- 修复因重构引入的失败测试

---

## 四、删除文件清单汇总

| 文件路径 | 删除原因 |
|---------|---------|
| `hs_analysis/scorers/v2_engine.py` | 被 V7 完全取代 |
| `hs_analysis/scorers/l6_real_world.py` | 无任何模块导入，输出不存在 |
| `hs_analysis/evaluators/multi_objective.py` | 与 bsv.py 功能重复 |
| `hs_analysis/search/engine_v11/mechanics/` (整个目录) | 透传包装器，运行时从未调用 |
| `scripts/run_score_v2.py` | V2 入口随 V2 废弃 |
| `scripts/diag_scores.py` | 一次性诊断脚本 |
| `scripts/diag_conditions.py` | 一次性诊断脚本 |
| `scripts/deep_analysis.py` | 依赖已删除的数据文件 |
| `scripts/analyze_meta_decks.py` | 依赖已删除的数据文件 |
| `scripts/decision_presenter.py` | 导入路径已过时 |
| `hs_cards/v2_scoring_report.json` | V2 引擎输出 |
| `hs_cards/v2_keyword_params.json` | V2 引擎输出 |
| `hs_analysis/search/test_v9_hdt_batch*.py` (9个文件) | V9 批量回归测试，不完整 |

## 五、重命名文件清单

| 原路径 | 新路径 |
|-------|-------|
| `hs_analysis/scorers/v7_engine.py` | `hs_analysis/scorers/scoring_engine.py` |
| `scripts/run_score_v7.py` | `scripts/run_scoring.py` |

## 六、风险评估

| 阶段 | 风险 | 缓解措施 |
|------|------|---------|
| Phase 1（删除死代码） | **极低** | 这些文件要么无引用，要么依赖不存在 |
| Phase 2（清理配置） | **低** | 全局搜索确认引用后修改 |
| Phase 3（数据模型） | **中** | 需要更新所有引用点，但 v2_score/l6_score 使用范围有限 |
| Phase 4（共享工具） | **中** | 阈值统一需确保不影响评估结果 |
| Phase 5（评估器） | **低** | V10 路径已经是更优路径 |
| Phase 6（重命名） | **低** | 纯重命名，IDE 可追踪 |
| Phase 7（V11 清理） | **低** | mechanics 本身是死代码 |
| Phase 8（测试） | **中** | 需要仔细更新断言和导入 |

---

## 七、执行顺序建议

按风险从低到高执行：
1. **Phase 1** → Phase 6 → Phase 7（纯删除/重命名，无逻辑变更）
2. **Phase 2** → Phase 3（配置和数据模型清理）
3. **Phase 4** → Phase 5（逻辑统一）
4. **Phase 8**（测试验证贯穿全程）

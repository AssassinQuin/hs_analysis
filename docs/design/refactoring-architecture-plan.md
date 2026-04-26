# Analysis 模块重构架构计划

> **⚠️ 已废弃** — 本文档已被 `unified-engine-redesign.md` 完全替代。
> 
> 新方案更激进：删除 ~4,253 行（含死代码+解析器），统一模拟引擎为单一执行路径，
> 确定性化所有随机效果，新增声明式 JSON 能力系统。
>
> 请参阅：**[unified-engine-redesign.md](./unified-engine-redesign.md)**

---

> **版本**: v2.0  
> **生成日期**: 2026-04-26  
> **范围**: `analysis/` 全模块架构重构  
> **基于**: 代码库分析 + 成熟项目架构调研  
> **状态**: ❌ 已废弃 — 参见 unified-engine-redesign.md  

---

## 一、现状诊断

### 1.1 项目定位

hs_analysis 是一个**炉石传说分析决策引擎**，而非完整模拟器：
- 核心能力：卡牌评分 → 效果解析 → 游戏模拟 → MCTS/因子搜索 → 决策输出
- 输入管线：Power.log 实时解析（watcher）或离线批量分析
- 不涉及：UI、多人对战、卡牌编辑器

### 1.2 核心架构问题

| # | 问题 | 影响范围 | 严重度 |
|---|------|----------|--------|
| A | 三套并行解析系统 | 15个文件，80+个CN regex | 🔴 高 |
| B | Mechanic 模块碎片化 | 12个文件绕过 ability pipeline | 🔴 高 |
| C | Shim 文件链（card_index/hsdb） | 2个零逻辑文件 | 🟡 中 |
| D | 双 EffectKind 枚举不兼容 | effects.py vs definition.py | 🟡 中 |
| E | 评估器碎片化（composite/siv/bsv） | 3套独立评估管线 | 🟡 中 |
| F | 常量散落三处 | constants/scorers/keywords | 🟢 低 |

### 1.3 已有设计文档约束

| 约束 | 内容 |
|------|------|
| C1 | 测试基线 613 passed 不可下降 |
| C5 | simulation/orchestrator/executor 零 regex |
| C8 | `rhea/` 保留为 re-export shim |
| C12 | `watcher/` 层不在重构范围 |

---

## 二、目标架构

### 2.1 设计原则

基于 MetaStone（声明式卡牌）、Fireplace（事件驱动）、SabberStone（任务系统）的经验：

1. **单一 Abilities Pipeline**：卡牌效果解析走唯一管线（parser → orchestrator → executor）
2. **EN-Only 逻辑层**：模拟/搜索/评估层零中文 regex
3. **分层解耦**：data → abilities → search → evaluator 各层单向依赖
4. **渐进迁移**：不推翻重写，新旧并存过渡
5. **数据驱动**：效果池/token池从数据库查询，不硬编码

### 2.2 目标目录结构

```
analysis/
│
├── __init__.py
├── config.py                        # 集中配置
│
├── data/                            # 【数据层】卡牌数据库 & 效果提取
│   ├── __init__.py                  # 公共 API 导出
│   ├── card_data.py                 # CardDB 统一卡牌数据库（含向后兼容别名）
│   ├── card_effects.py              # CardEffects + RoleTag 分类（G3合并）
│   ├── card_cleaner.py              # 数据归一化（legacy, deprecated）
│   ├── token_cards.py               # Token 卡牌数据
│   └── fetch_hsreplay.py            # HSReplay 数据获取
│
├── models/                          # 【模型层】核心数据结构
│   ├── __init__.py                  # 含 Phase + detect_phase（G4合并）
│   ├── card.py                      # Card dataclass
│   └── game_record.py               # GameRecord 数据类
│
├── abilities/                       # 【能力层】效果解析 & 执行（原 search/abilities/）
│   ├── __init__.py                  # 公共 API
│   ├── definition.py                # EffectKind + CardAbility + ActionType + Action（G6合并）
│   ├── tokens.py                    # 映射表
│   ├── extractors.py                # 字符串提取
│   ├── parser.py                    # AbilityParser
│   ├── executor.py                  # AbilityExecutor（含 corrupt/rewind 函数，G2合并）
│   ├── orchestrator.py              # 效果编排
│   ├── enumeration.py               # 合法动作枚举
│   └── simulation.py                # apply_action 核心状态转移
│
├── engine/                          # 【引擎层】游戏状态 & 机制
│   ├── __init__.py
│   ├── game_state.py                # GameState 核心可变状态
│   ├── entity.py                    # CardInstance + Zone 管理
│   ├── zone_manager.py              # 6区域管理
│   ├── enchantment.py               # Enchantment + TRIGGER_REGISTRY（G5合并）
│   ├── aura_engine.py               # 光环引擎
│   ├── trigger_system.py            # 触发器事件总线
│   ├── mechanics_state.py           # MechanicState 组合根
│   ├── keywords.py                  # KeywordSet 不可变关键词容器
│   │
│   └── mechanics/                   # 【机制模块】各类关键字机制实现
│       ├── __init__.py
│       ├── deathrattle.py           # 亡语
│       ├── discover.py              # 发现
│       ├── choose_one.py            # 抉择
│       ├── quest.py                 # 任务
│       ├── corpse.py                # 残骸
│       ├── imbue.py                 # 灌注
│       ├── kindred.py               # 延系
│       ├── herald.py                # 兆示
│       ├── secret_triggers.py       # 奥秘
│       ├── shatter.py               # 裂变
│       ├── dormant.py               # 休眠
│       ├── colossal.py              # 巨型
│       ├── outcast.py               # 流放
│       ├── dark_gift.py             # 暗影之赐
│       ├── rune.py                  # 符文
│       └── location.py              # 位置
│
├── search/                          # 【搜索层】决策引擎
│   ├── __init__.py
│   ├── effects.py                   # 旧 EffectKind（deprecated，按P8计划桥接）
│   ├── opponent_simulator.py        # 对手模拟
│   ├── lethal_checker.py            # 致命检测
│   ├── risk_assessor.py             # 风险评估
│   ├── action_normalize.py          # 动作归一化
│   ├── power_parser.py              # Power.log 批量解析
│   ├── engine_adapter.py            # 搜索引擎适配器
│   │
│   ├── mcts/                        # MCTS 子系统（结构合理，不调整）
│   │   ├── __init__.py
│   │   ├── engine.py                # MCTS 入口
│   │   ├── node.py                  # 节点
│   │   ├── uct.py                   # UCB1 选择
│   │   ├── expansion.py             # 扩展
│   │   ├── simulation.py            # 随机 rollout
│   │   ├── backprop.py              # 回溯
│   │   ├── determinization.py       # DUCT 确定化
│   │   ├── transposition.py         # 转置表
│   │   ├── pruning.py               # 剪枝
│   │   ├── turn_advance.py          # 跨回合模拟
│   │   └── config.py                # MCTS 配置
│   │
│   └── pipeline/                    # 因子管线引擎（原 engine/，更明确命名）
│       ├── __init__.py
│       ├── pipeline.py              # DecisionPipeline
│       ├── strategic.py             # 策略模式选择
│       ├── tactical.py              # 战术规划
│       ├── unified_tactical.py      # 统一战术
│       ├── turn_plan.py             # 回合规划
│       ├── attack_planner.py        # 攻击规划
│       ├── action_pruner.py         # 动作剪枝
│       ├── factors/                 # 因子评估
│       └── models/                  # 概率模型
│
├── scorers/                         # 【评分层】卡牌评分引擎
│   ├── __init__.py
│   ├── scoring_engine.py            # 多层评分引擎
│   ├── v8_contextual.py             # V8 情境评分
│   ├── vanilla_curve.py             # L1 白板曲线
│   ├── keyword_interactions.py      # 关键词交互
│   ├── mechanic_base_values.py      # 机制基础值
│   └── constants.py                 # 评分常量（引用 constants/ 消除重复）
│
├── evaluators/                      # 【评估层】局面评估
│   ├── __init__.py
│   ├── composite.py                 # 复合评估器
│   ├── submodel.py                  # 子模型评估
│   ├── bsv.py                       # BSV 融合
│   ├── siv.py                       # SIV 评估
│   ├── card_impact.py               # 卡牌影响评估
│   └── archetype_profile.py         # 套牌画像
│
├── constants/                       # 【常量层】共享常量
│   ├── __init__.py
│   └── effect_keywords.py           # 效果关键词（CN+EN，被 evaluators/search 使用）
│
├── utils/                           # 【工具层】（保持现状）
│   ├── __init__.py
│   ├── hero_class.py
│   ├── player_name.py
│   ├── http.py
│   ├── load_json.py
│   ├── bayesian_opponent.py
│   └── spell_simulator.py
│
└── watcher/                         # 【集成层】Power.log 实时管线（不调整）
    ├── __init__.py
    ├── decision_loop.py             # 主决策循环
    ├── state_bridge.py              # hslog→GameState 转换
    ├── game_log_parser.py           # 日志解析
    ├── game_tracker.py              # 游戏追踪
    ├── log_watcher.py               # 文件监听
    └── ...                          # 其他 watcher 文件
```

### 2.3 与当前架构的关键差异

| 变更 | 当前 | 目标 | 理由 |
|------|------|------|------|
| abilities/ 从 search/ 提升为顶层 | `search/abilities/` | `abilities/` | 能力层是核心子系统，与 search 平级 |
| mechanics/ 从散落收归子包 | `search/*.py` 12个文件 | `engine/mechanics/` | 按域分组，减少根目录碎片 |
| pipeline/ 重命名 | `search/engine/` | `search/pipeline/` | 避免与顶层 engine/ 概念混淆 |
| 消除 4 个文件 | card_index, hsdb, card_roles, phase | 合并入主文件 | 减少间接层 |
| 合并 2 个文件 | trigger_registry, actions | 并入主体 | 紧耦合合一 |

---

## 三、合并计划

### Phase 0: 文件合并（低风险，~1小时）

| 合并组 | 操作 | 风险 |
|--------|------|------|
| **G1** | 删除 `card_index.py` + `hsdb.py`，别名移入 `card_data.py` | 🟢 低 |
| **G3** | `card_roles.py` 并入 `card_effects.py` | 🟢 低 |
| **G4** | `phase.py` 并入 `models/__init__.py` | 🟢 低 |
| **G5** | `trigger_registry.py` 并入 `enchantment.py` | 🟢 低 |
| **G9** | `scorers/constants.py` 引用 `constants/effect_keywords.py` 去重 | 🟢 低 |

### Phase 1: 目录重组（中风险，~2小时）

| 步骤 | 操作 | 风险 |
|------|------|------|
| **S1** | `search/abilities/` → `abilities/`（顶层包） | 🟡 中（需更新大量 import） |
| **S2** | 12个 mechanic 文件 → `engine/mechanics/` | 🟡 中（需更新 import） |
| **S3** | `search/engine/` → `search/pipeline/` | 🟡 中（需更新 import） |
| **S4** | `search/game_state.py` + `entity.py` + `zone_manager.py` 等 → `engine/` | 🟡 中 |

### Phase 2: 中等合并（中风险，~2小时）

| 合并组 | 操作 | 风险 |
|--------|------|------|
| **G2** | `corrupt.py` + `rewind.py` 并入 `executor.py` | 🟡 中 |
| **G6** | `actions.py` 并入 `definition.py`，保留 shim | 🟡 中 |

### Phase 3: 按已有计划执行

| Phase | 操作 | 参考 |
|-------|------|------|
| **P7** | CN Regex 大迁移（15文件，80+ patterns → EN） | analysis-full-refactoring-design.md |
| **P8** | effects.py 合并（消除双 EffectKind） | analysis-full-refactoring-design.md |
| **P9** | Mechanic 模块收编试点（herald/dormant/shatter） | analysis-full-refactoring-design.md |
| **P10** | 解耦与清理 | analysis-full-refactoring-design.md |
| **P11** | I-MCTS 就绪（LLM 集成接口） | analysis-full-refactoring-design.md |

---

## 四、执行策略

### 4.1 每个 Phase 的验证流程

```bash
# 1. 语法检查
python -m py_compile <changed_files>

# 2. 单元测试
python -m pytest tests/ -x -q -k "not (live_games or powerlog_mcts or powerlog_scenario or game5 or game7 or watcher or scenario_integration or engine_v1)"

# 3. CN regex 扫描（Phase 3+）
rg '[\x{4e00}-\x{9fff}]' analysis/search/abilities/ analysis/search/*.py --include '*.py'

# 4. import 验证
python -c "from analysis.abilities import ActionType, Action; print('OK')"
```

### 4.2 回滚策略

每个 Phase 使用独立 git branch，验证失败即回滚：
- `refactor/phase-0-merge` — 文件合并
- `refactor/phase-1-restructure` — 目录重组
- `refactor/phase-2-medium-merge` — 中等合并

### 4.3 Import 兼容策略

目录重组后，保留 re-export shim 确保向后兼容：

```python
# analysis/search/abilities/__init__.py (re-export shim)
"""Backward compatibility — abilities/ is now a top-level package."""
from analysis.abilities import *  # noqa: F401,F403
```

```python
# analysis/search/__init__.py (添加旧路径兼容)
"""Backward compatibility for mechanics moved to engine/mechanics/."""
from analysis.engine.mechanics.corrupt import has_corrupt  # noqa: F401
```

---

## 五、收益预估

### 5.1 定量收益

| 指标 | 当前 | 目标 | 改善 |
|------|------|------|------|
| 根目录碎片文件 | 12个 mechanic + 2个 shim | 0 | -14 文件 |
| 总文件数 | ~115 | ~105 | -10 文件 |
| 解析系统 | 3套并行 | 1套统一 | -67% |
| CN regex 文件 | 15个 | 3个（data层允许） | -80% |
| import 深度 | `analysis.search.abilities.executor` | `analysis.abilities.executor` | -1层 |

### 5.2 定性收益

1. **认知成本降低**：abilities/ 作为顶层包，职责一目了然
2. **mechanics/ 归组**：从散落的12个文件变为有组织的子包
3. **依赖方向清晰**：data → abilities → engine → search → evaluators
4. **与成熟项目对齐**：分层结构与 MetaStone/SabberStone 一致

---

## 六、不做的事

| 提案 | 决定 | 理由 |
|------|------|------|
| 完全重写为 ECS 架构 | ❌ 丢弃 | 过度设计，成本远超收益 |
| game_state + entity 合并 | ❌ 丢弃 | 新旧架构并存期，不可合并 |
| card_data.py 拆分 | ❌ 丢弃 | 1346行但内聚，拆分风险>收益 |
| watcher/ 层重构 | ❌ 丢弃 | 独立输入管线，设计文档约束 |
| utils/ 小文件合并 | ❌ 丢弃 | 收益不足 |
| 完全迁移到 Fireplace 架构 | ❌ 丢弃 | 项目定位不同，不适合 |

---

## 七、参考文档

| 文档 | 路径 | 内容 |
|------|------|------|
| 代码库合并分析 | `docs/design/merge-analysis.md` | 文件合并详细方案 |
| 全面重构设计 | `docs/design/analysis-full-refactoring-design.md` | P7-P11 实施计划 |
| 卡牌效果解析标准 | `docs/design/card-effect-parsing-standard.md` | 设计标准 |
| 成熟项目调研 | `docs/research/2026-04-26-card-game-simulator-architecture-survey.md` | 架构参考 |
| 项目架构 | `docs/architecture/ARCHITECTURE.md` | 整体架构 |

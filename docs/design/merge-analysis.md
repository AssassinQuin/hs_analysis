# 炉石分析项目 — 文件合并与架构改进分析

> **⚠️ 已废弃** — 本文档的合并建议已纳入 `unified-engine-redesign.md` 第 4 节文件变更清单。
> 新方案更激进：删除 21 文件（~4,253 行），统一模拟引擎。
>
> 请参阅：**[unified-engine-redesign.md](./unified-engine-redesign.md)**

> **生成日期**: 2026-04-26  
> **范围**: `analysis/` 全模块  
> **方法**: 逐一阅读源文件内容，基于实际职责和耦合关系分析
> **状态**: ❌ 已废弃 — 参见 unified-engine-redesign.md

---

## 一、当前架构问题诊断

### 1.1 总览

| 区域 | 文件数 | 代码行数 | 核心问题 |
|------|--------|----------|----------|
| `search/abilities/` | 10 | ~2,900 | 架构清晰，职责分明 |
| `search/` 根文件 | 29 | ~7,200 | 12个mechanic模块边界模糊，shim文件冗余 |
| `search/mcts/` | 13 | ~2,800 | 结构合理，独立子系统 |
| `search/engine/` | 12 | ~1,500 | 新引擎，结构良好 |
| `data/` | 9 | ~2,300 | 双shim文件，card_data.py过大(1346行) |
| `models/` | 4 | ~370 | phase.py过于微小 |
| `scorers/` | 8 | ~1,800 | constants.py与scoring_engine.py高度耦合 |
| `evaluators/` | 7 | ~1,750 | 三个评估器各自为政，重复评估逻辑 |
| `constants/` | 3 | ~290 | 与scorers/constants.py职责重叠 |
| `utils/` | 7 | ~1,380 | hero_class.py/rune.py属于不同域 |
| `watcher/` | 11 | ~3,900 | 架构合理，tracker_types.py可考虑内联 |

### 1.2 核心架构问题

#### 问题 A: 三层间接 — shim 文件链

```
消费者 → data/card_index.py (11行shim)
       → data/card_data.py (1346行真实逻辑)

消费者 → data/hsdb.py (16行shim)  
       → data/card_data.py (1346行真实逻辑)
```

`card_index.py` 和 `hsdb.py` 都是纯 re-export shim，零逻辑。`CardDB` 类同时承担了旧 `HSCardDB`、`CardIndex`、`card_updater`、`build_unified_db`、`build_wild_db` 五个角色的职责，但由于历史原因保留了两层别名。

#### 问题 B: mechanic 模块碎片化

`search/` 根目录下有 12+ 个独立 mechanic 文件：

```
corrupt.py (49行)    rewind.py (61行)    herald.py (~86行)
dormant.py (~50行)   shatter.py (~74行)  colossal.py (~100行)
outcast.py (~110行)  dark_gift.py (173行) imbue.py (~204行)
quest.py (~265行)    location.py (~210行) secret_triggers.py (~143行)
```

其中 `corrupt.py` (49行) 和 `rewind.py` (61行) 极其微小，只有 1-2 个函数。这些文件与 `abilities/executor.py` 中的 handler 紧密耦合——executor 内已有 `herald_summon`、`imbue_upgrade`、`combo_discount`、`outcast_*`、`colossal_summon`、`kindred_buff`、`corrupt_upgrade`、`corpse_effect` 的实现，而 mechanic 模块本身仍被 `simulation.py` 直接调用。

#### 问题 C: 双 EffectKind 枚举不兼容

```
search/effects.py       → EffectKind (14个 auto-int 值)
search/abilities/definition.py → EffectKind (31+ string 值)
```

两套枚举有重叠语义（DAMAGE, SUMMON, DRAW 等）但完全不兼容。`effects.py` 作为 System 3 仅有 2 个消费者（deathrattle.py, trigger_system.py），通过 `dispatch_via_abilities()` 桥接到新管线。

#### 问题 D: 评估器碎片化

三个独立的评估管线共存：

```
evaluators/composite.py + submodel.py  → V8 评估（5子模型）
evaluators/siv.py                     → V10 SIV（8乘法修饰符）
evaluators/bsv.py + card_impact.py    → V10 BSV（3轴融合）
```

`composite.py` 中有 fallback 逻辑——当 `submodel.py` import 失败时直接内联计算，说明两者耦合极高但被人为分离。

#### 问题 E: 常量散落三处

```
constants/effect_keywords.py → CN+EN 关键词 frozenset（被 evaluators + search 使用）
scorers/constants.py         → 评分常量 + CN regex patterns（被 scorers 使用）
search/keywords.py           → KeywordSet + 关键词映射表（被 game_state 使用）
```

三处都涉及关键词/效果分类，但各有不同的映射维度和用途。

#### 问题 F: card_data.py 职责过载

1346 行的 `CardDB` 类同时承担：
- API 数据获取（HSJSON API + XML fallback）
- 索引构建（frozenset 多维索引）
- 查询服务（多属性查找、池查询）
- 数据更新（新鲜度检测、自动更新）
- 数据合并（标准/狂野模式合并）
- 单例缓存管理

---

## 二、可合并文件清单

### 合并组 G1: data/ 层 shim 消除

| 文件 | 行数 | 操作 |
|------|------|------|
| `data/card_index.py` | 11 | **并入** `card_data.py` |
| `data/hsdb.py` | 16 | **并入** `card_data.py` |

**理由**: 纯 re-export shim，零逻辑。`CardIndex` 只是 `CardDB` 的别名。两个文件加起来 27 行，全是从 `card_data.py` re-export。可以在 `card_data.py` 末尾添加 `CardIndex = CardDB` + 旧函数名别名。

**风险**: 🟢 **低** — 只需更新 `from analysis.data.card_index import ...` 为 `from analysis.data.card_data import ...`。可通过 shim `__init__.py` 保持过渡期兼容。

**合并后**: `card_data.py` 末尾添加：
```python
# Backward compatibility aliases
CardIndex = CardDB
def get_index() -> CardDB: return get_db()
```
删除 `card_index.py` 和 `hsdb.py`。

---

### 合并组 G2: 微型 mechanic 模块归入 executor

| 文件 | 行数 | 操作 |
|------|------|------|
| `search/corrupt.py` | 49 | **并入** `abilities/executor.py` |
| `search/rewind.py` | 61 | **并入** `abilities/executor.py` |

**理由**: 
- `corrupt.py` 只有两个函数 `has_corrupt()` 和 `check_corrupt_upgrade()`，executor.py 已有 `_exec_corrupt_upgrade()` handler
- `rewind.py` 只有两个函数 `is_rewind_card()` 和 `evaluate_with_rewind()`，是纯工具函数
- 两者都是 detection+application 模式，与 executor 内其他 mechanic handler（herald, imbue, kindred 等）结构完全一致
- simulation.py 对两者的调用都可以通过 executor 管线完成

**风险**: 🟡 **中** — `corrupt.py` 和 `rewind.py` 被 `simulation.py` 直接调用。需要将调用点改为通过 orchestrator → executor 调度，或在 simulation.py 中改为从 executor 导入。

**合并后**: executor.py 中添加：
```python
# From corrupt.py
def has_corrupt(card) -> bool: ...
def check_corrupt_upgrade(state, card_index): ...

# From rewind.py  
def is_rewind_card(card) -> bool: ...
def evaluate_with_rewind(card, state, eval_fn): ...
```

---

### 合并组 G3: card_roles.py 并入 card_effects.py

| 文件 | 行数 | 操作 |
|------|------|------|
| `data/card_roles.py` | 104 | **并入** `data/card_effects.py` |

**理由**: `card_roles.py` 的 `classify_roles()` 直接接收 `card_effects.get_effects()` 的输出，`classify_card_roles()` 是 `get_effects()` → `classify_roles()` 的简单封装。两个模块形成紧耦合管道：text → effects → roles。分离没有收益——它们总是一起变化，一起使用。

**风险**: 🟢 **低** — `card_roles.py` 的消费者极少（主要是 scorers 和 evaluators），直接改 import 路径即可。

**合并后**: `card_effects.py` 末尾追加 `RoleTag` enum + `classify_roles()` + `classify_card_roles()` 函数。

---

### 合并组 G4: models/phase.py 并入就近消费者

| 文件 | 行数 | 操作 |
|------|------|------|
| `models/phase.py` | 15 | **并入** `evaluators/composite.py` 或 `scorers/v8_contextual.py` |

**理由**: 15 行的 `Phase` enum + `detect_phase()` 函数。消费者主要是评估器和评分器。独立成文件增加了认知成本和 import 路径深度。值得保留在 models/ 中但合并到 `models/__init__.py` 或直接内联。

**风险**: 🟢 **低** — 纯枚举+函数，无状态。

**合并后**: 将 `Phase` 和 `detect_phase` 移入 `models/__init__.py`，删除 `phase.py`。

---

### 合并组 G5: enchantment + trigger_registry 合并

| 文件 | 行数 | 操作 |
|------|------|------|
| `search/enchantment.py` | 243 | 保留为主体 |
| `search/trigger_registry.py` | 95 | **并入** `enchantment.py` |

**理由**: `trigger_registry.py` 只有 `get_triggers_for_minion()` 一个函数，返回 `Enchantment` 对象。它是 enchantment 系统的查找表，与 `enchantment.py` 形成 "数据结构 + 数据源" 关系。分离的唯一理由是避免循环依赖，但 trigger_registry 不导入 enchantment 以外的模块。

**风险**: 🟢 **低** — 只有 4 个硬编码条目，消费者极少。

**合并后**: `enchantment.py` 中添加 `TRIGGER_REGISTRY` dict + `get_triggers_for_minion()` 函数。

---

### 合并组 G6: abilities/actions.py 并入 abilities/definition.py

| 文件 | 行数 | 操作 |
|------|------|------|
| `abilities/actions.py` | 106 | **并入** `abilities/definition.py` |

**理由**: `actions.py` 定义了 `ActionType` enum 和 `Action` dataclass——与 `definition.py` 中定义的其他核心类型（`EffectKind`, `CardAbility`, `TargetSpec` 等）是同一层面的领域类型。分离的唯一原因是 definition.py 已经 421 行，但 actions.py 只有 106 行，且两者总行数 527 行完全合理。

**风险**: 🟡 **中** — `actions.py` 被 `__init__.py` eager import，被 enumeration/simulation/orchestrator 广泛使用。需要更新所有 import 路径。

**合并后**: `definition.py` 中追加 `ActionType` + `Action` + 辅助函数。保留 `actions.py` 作为 re-export shim 过渡期。

---

### 合并组 G7: effects.py 标记 deprecated 并保留

| 文件 | 行数 | 操作 |
|------|------|------|
| `search/effects.py` | 444 | **不合并，但桥接** |

**理由**: 已有的设计文档明确决定不删除 `effects.py`（约束 C9）。它有 2 个活跃消费者（deathrattle.py, trigger_system.py），且已有 `dispatch_via_abilities()` 桥接函数。合并到 abilities/ 会引入循环依赖。

**建议操作**: 
- 在文件头部添加 `@deprecated` 注释
- 在两个消费者中添加 TODO 注释标记迁移计划
- P8 阶段按已有设计文档执行 adapter 合并

**风险**: 🔴 **不操作** — 按已有设计文档处理

---

### 合并组 G8: utils 小工具函数合并

| 文件 | 行数 | 操作 |
|------|------|------|
| `utils/hero_class.py` | 57 | **并入** `utils/__init__.py` 或保留 |
| `utils/player_name.py` | 76 | **并入** `utils/__init__.py` 或保留 |
| `utils/http.py` | 42 | **并入** `utils/__init__.py` 或保留 |

**理由**: 这三个文件都是小型纯函数工具（hero→class映射、名字标准化、HTTP GET），各自 40-80 行。独立成文件增加了 import 深度但没有架构收益。但它们的使用频率不同（http.py 仅被 data/ 使用，player_name.py 仅被 watcher/ 使用，hero_class.py 被广泛使用）。

**风险**: 🟡 **中** — 消费者散布在不同包，合并后需要更新大量 import。

**建议**: 保持现状。这三个文件虽小但职责清晰、消费者稳定，合并的收益不足以抵消 import 更新的成本。

---

### 合并组 G9: constants/ 与 scorers/constants.py 理清边界

| 文件 | 行数 | 操作 |
|------|------|------|
| `constants/effect_keywords.py` | 74 | 保留 |
| `scorers/constants.py` | 166 | 保留，但去重复 |

**理由**: 两个 constants 文件服务于不同域：
- `constants/effect_keywords.py` → 被 evaluators/ 和 search/ 使用，是**效果分类**常量
- `scorers/constants.py` → 被 scorers/ 使用，是**评分参数**常量

职责不同，不应合并。但 `scorers/constants.py` 中的 `KEYWORD_CN` 与 `constants/effect_keywords.py` 有语义重叠。

**建议**: 
- `scorers/constants.py` 中需要关键词分类时，改为 import `effect_keywords.py`
- 保持两个文件独立但建立清晰的依赖方向：`scorers/constants.py` → `constants/effect_keywords.py`

**风险**: 🟢 **低** — 纯重构依赖方向

---

## 三、合并风险评估

### 汇总表

| 合并组 | 文件数 | 总行数 | 风险 | 收益 | 优先级 |
|--------|--------|--------|------|------|--------|
| **G1** shim 消除 | 2 | 27 | 🟢 低 | 消除间接层 | **P0** |
| **G3** card_roles 并入 card_effects | 2 | 413 | 🟢 低 | 紧耦合合一 | **P0** |
| **G4** phase.py 内联 | 1 | 15 | 🟢 低 | 减少 1 文件 | **P0** |
| **G5** trigger_registry 并入 enchantment | 2 | 338 | 🟢 低 | 相关数据合一 | **P1** |
| **G2** 微型 mechanic 归入 executor | 2 | 110 | 🟡 中 | 消除碎片 | **P2** |
| **G6** actions 并入 definition | 2 | 527 | 🟡 中 | 领域类型统一 | **P2** |
| **G8** utils 小工具合并 | 3 | 175 | 🟡 中 | 收益不明显 | **不做** |
| **G7** effects.py 桥接 | 1 | 444 | 🔴 不操作 | 按已有计划 | **P3** |
| **G9** constants 理清边界 | 2 | 240 | 🟢 低 | 去重 | **P1** |

### 风险详细分析

#### G1 (shim 消除) — 风险详情
- **消费者数量**: card_index.py 有 ~5 个消费者，hsdb.py 有 ~3 个消费者
- **回归风险**: 几乎为零——re-export 不改变运行时行为
- **缓解**: 在 `data/__init__.py` 中保留过渡期 re-export

#### G2 (mechanic 归入) — 风险详情
- **关键风险**: simulation.py 中有多处直接 `from analysis.search.corrupt import has_corrupt` 的调用
- **回归风险**: 中——需要确保 simulation.py 中的调用链在合并后仍然正确
- **缓解**: 先在 executor.py 中添加函数，保留旧文件作为 re-export shim，验证测试通过后删除

#### G6 (actions 并入 definition) — 风险详情
- **关键风险**: abilities/__init__.py 的 `from .actions import ActionType, Action` 被 eager import
- **消费者**: enumeration.py, simulation.py, orchestrator.py, mcts/ 子系统
- **缓解**: 保留 actions.py 作为 re-export shim (`from .definition import ActionType, Action`)

---

## 四、依赖关系分析

### 4.1 包间依赖矩阵

```
                    data  models  scorers  evaluators  search  constants  utils  watcher
data/                 ●      ←       ←                   ←                 ←
models/                      ●                           ←                  ←
scorers/              ←              ●                           ←
evaluators/           ←      ←       ←         ●                ←       ←
search/abilities/     ←                        ←         ●                ←
search/ (root)        ←      ←                 ←         ●       ←        ←
search/mcts/          ←                        ←         ←                ←
search/engine/        ←                        ←         ←                ←
constants/                                  ←                  ●
utils/                ←              ←                   ←                ●
watcher/              ←      ←                        ←   ←       ←        ●

● = 自身   ← = 依赖方向（左边的包依赖上边的包）
```

### 4.2 循环依赖风险点

| 依赖路径 | 风险 | 说明 |
|----------|------|------|
| `abilities/__init__.py` → `simulation.py` → `abilities/*` | 🟡 中 | 已通过 lazy import 解决 |
| `card.py` → `card_effects.py` → `card_data.py` → `Card` model | 🟢 低 | 单向延迟加载 |
| `composite.py` ↔ `submodel.py` | 🟢 低 | 已通过 try/except fallback 解决 |
| `effects.py` → `abilities/` → `card_effects.py` | 🟡 中 | bridge pattern 已建立 |

### 4.3 不应合并的文件（重要）

以下文件虽然看似可合并，但由于**独立变化**或**架构边界**原因不应合并：

1. **`game_state.py` + `entity.py` + `zone_manager.py`**: 新旧两套架构并存。entity.py + zone_manager.py 是新的基于 Zone 的架构，game_state.py 是旧的扁平结构。两者不应合并直到迁移完成。

2. **`mcts/` 整包**: 完整的 MCTS 子系统，13个文件分工明确（config/node/expansion/simulation/backprop/uct/pruning/transposition），不应与 search/ 根文件合并。

3. **`engine/` 整包**: 新的 factor-based 引擎，12个文件独立子系统，不应与旧 search/ 根文件合并。

4. **`bayesian_opponent.py` (844行)**: 虽然在 utils/ 但逻辑自足，消费者包括 watcher/ 和 search/，不应拆分或合并。

5. **`card_data.py` (1346行)**: 虽然过大但职责连贯，拆分风险高于收益。建议内部用注释分区而非物理拆分。

6. **`watcher/` 整包**: 独立输入管线，不在本次合并范围（设计文档约束 C12）。

### 4.4 高价值但高难度的合并（未来考虑）

| 目标 | 难度 | 前置条件 |
|------|------|----------|
| `game_state.py` 旧的 Minion boolean 字段 → 全部迁移到 `KeywordSet` | 🔴 高 | 所有消费者支持 KeywordSet |
| `simulation.py` 880行中 mechanic 调用 → 全部路由到 ability pipeline | 🔴 高 | P7-P9 完成 |
| `card_data.py` 1346行 → 拆分 data/核心 + index/查询 + update/同步 | 🟡 中 | 明确的接口边界 |
| evaluator 三系统统一 (composite/siv/bsv) | 🔴 高 | V10 评估框架成熟后 |

---

## 五、建议执行顺序

```
Phase 1 (P0, 低风险, ~1小时):
  G1: 删除 card_index.py + hsdb.py, 在 card_data.py 添加别名
  G3: card_roles.py 并入 card_effects.py
  G4: phase.py 并入 models/__init__.py

Phase 2 (P1, 低风险, ~1小时):
  G5: trigger_registry.py 并入 enchantment.py
  G9: scorers/constants.py 引用 constants/effect_keywords.py 去重

Phase 3 (P2, 中风险, ~2小时):
  G6: actions.py 并入 definition.py, 保留 shim
  G2: corrupt.py + rewind.py 并入 executor.py, 保留 shim

Phase 4 (P3, 按已有计划):
  G7: effects.py 按已有设计文档 P8 执行 bridge → deprecated
```

每个 Phase 完成后执行验证：
```bash
python -m pytest tests/ -x -q -k "not (live_games or powerlog_mcts or powerlog_scenario or game5 or game7 or watcher or scenario_integration or engine_v1)"
```

---

## 六、总结

### 核心发现

1. **shim 文件是最大浪费**: `card_index.py`(11行) 和 `hsdb.py`(16行) 是纯粹的 re-export，增加了 0 价值但增加了认知成本
2. **微型 mechanic 文件是次要浪费**: `corrupt.py`(49行) 和 `rewind.py`(61行) 太小不值得独立
3. **紧耦合文件被人为分离**: `card_roles.py` + `card_effects.py` 总是一起使用
4. **大部分文件不应合并**: mcts/, engine/, watcher/ 的文件结构合理

### 收益预估

- 删除 **4个文件** (card_index, hsdb, card_roles, phase)
- 合并 **2个文件** 到现有主体 (trigger_registry→enchantment, actions→definition)  
- 理清 **1个依赖方向** (scorers/constants → constants/effect_keywords)
- 净减少约 **~100行** shim/boilerplate 代码

### 不建议做的事

- ❌ 不合并 `game_state.py` + `entity.py`（新旧架构并存期）
- ❌ 不拆分 `card_data.py`（1346行但内聚）
- ❌ 不合并 `utils/` 小文件（收益不足）
- ❌ 不删除 `effects.py`（已有设计决策）
- ❌ 不动 `watcher/`（约束 C12）
- ❌ 不动 `mcts/` 和 `engine/`（结构合理）

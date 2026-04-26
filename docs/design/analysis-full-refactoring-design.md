# Analysis 模块全面重构设计文档

> **版本**: v1.0  
> **生成日期**: 2026-04-26  
> **范围**: `analysis/` 全模块 — 卡牌解析、效果模拟、MCTS 搜索  
> **状态**: 待实施（阶段 4）  
> **前置标准**: [card-effect-parsing-standard.md](./card-effect-parsing-standard.md)  

---

## 一、背景与目标

### 1.1 项目现状

| 区域 | 文件数 | 代码行数 | 核心问题 |
|------|--------|----------|----------|
| `analysis/search/` | 79 | 16,455 | 三套并行解析系统，15个文件含 CN regex，12个 mechanic 模块绕过 ability pipeline |
| `analysis/data/` | 9 | 3,207 | 双单例 (HSCardDB + CardIndex)，6处私有 API 泄漏 |
| `analysis/evaluators/` | 6 | ~1,200 | 评分函数重复，5处内联关键词检测 |
| `analysis/scorers/` | 4 | ~1,000 | 5个 score_* 函数共享管道已重构 |
| `analysis/constants/` | 3 | ~200 | effect_keywords.py 已去重 |

**测试基线**: 613 passed (unit tests, excluding fixtures)

### 1.2 重构目标

1. **统一解析管线**: 消除三套并行解析系统 → 单一 abilities pipeline
2. **EN-Only 逻辑层**: 15 个文件的 CN regex → 全部迁至 parser/card_effects 层
3. **Mechanic 模块收编**: 12 个绕过 ability pipeline 的模块 → 路由到统一管线
4. **解耦模拟与评估**: orchestrator 不再依赖 evaluators
5. **I-MCTS 就绪**: GameState + Action 结构化描述，便于 LLM 集成

### 1.3 约束条件（不可违反）

| 约束 ID | 约束内容 | 来源 |
|---------|---------|------|
| **C1** | 测试基线 613 passed 不可下降 | 项目约定 |
| **C2** | `data/card_effects.py` 中 CN regex 允许保留 | 设计标准 §1 |
| **C3** | `spell_target_resolver.py` 中 CN regex 允许保留 | 设计标准 §1 |
| **C4** | `constants/effect_keywords.py` 中 CN 关键词允许保留 | 设计标准 §1 |
| **C5** | simulation/orchestrator/executor 零 regex | 设计标准 §5 |
| **C6** | 零 card.name / card.dbf_id 行为检测 | 设计标准 §2 |
| **C7** | ≥500 行文件必须 Framework-First（骨架→验证→填充） | 重构工作流 |
| **C8** | `rhea/` 保留为 re-export shim（28 处消费者未迁移） | 历史约束 |
| **C9** | `effects.py` 被 deathrattle.py + trigger_system.py 依赖（2处），不可删除 | 消费者约束 |
| **C10** | `OpponentSimulator` 类有测试但无生产使用，保留并标 deprecation | 历史决策 |
| **C11** | `turn_advance.py` 是 MCTS 完整并行模拟，不可拆为 ability pipeline | 架构边界 |
| **C12** | `watcher/` 层不在本次范围（独立输入管线） | 范围约束 |

---

## 二、当前架构全景图

### 2.1 三套并行解析系统

```
系统 1: data/card_effects.py
  CN+EN regex (26 patterns) → CardEffects dataclass (22 fields)
  19 个消费者: simulation, enumeration, lethal_checker, spell_target_resolver, hero_card_handler, rng_model...

系统 2: search/abilities/ (parser.py + extractors.py + tokens.py)
  EN string.find() → List[CardAbility] (EffectSpec + ConditionSpec + TargetSpec)
  2 个消费者: simulation._play_minion, simulation._play_spell
  兜底: 调用系统 1 的 get_effects() 补充

系统 3: search/effects.py
  Colon-delimited string → EffectSpec (13 EffectKind auto-int)
  2 个消费者: deathrattle.py, trigger_system.py
  独立 EffectKind 枚举，与 abilities/definition.py 的 EffectKind 不兼容
```

### 2.2 数据流图

```
                          ┌──────────────────────────────────────────┐
                          │            Card Data Sources             │
                          │  data/card_data.py (CardDB)              │
                          │  data/card_effects.py (regex extraction) │
                          └──────┬──────────────────┬───────────────┘
                                 │                  │
                    mechanics tags + english_text    │ CardEffects (flat data)
                                 │                  │
                                 ▼                  ▼
                    ┌────────────────────┐   ┌─────────────────┐
                    │  abilities/parser  │──→│  get_effects()   │ ← 兜底补充
                    │  (EN string.find)  │   │  (CN+EN regex)   │
                    └────────┬───────────┘   └────────┬────────┘
                             │ List[CardAbility]       │ CardEffects
                             ▼                        ▼
                    ┌────────────────────┐    ┌─────────────────┐
                    │  orchestrator.py   │    │  19 direct call  │
                    │  (trigger dispatch)│    │  sites (legacy)  │
                    └────────┬───────────┘    └─────────────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │  executor.py       │
                    │  (31 EffectKind)   │
                    └────────┬───────────┘
                             │
                             ▼
                    ┌────────────────────┐
                    │  simulation.py     │
                    │  (apply_action)    │
                    └────────────────────┘
```

### 2.3 12 个 Mechanic 模块绕过 Ability Pipeline

这些模块直接操作 GameState，不经过 `orchestrate() → execute_effects()`:

| # | 模块 | 绕过原因 | 行数 | 迁移难度 |
|---|------|----------|------|----------|
| 1 | `imbue.py` | 英雄职业技能体系，class-specific | 204 | 🟡 中 |
| 2 | `herald.py` | 简单计数+召唤 | 86 | 🟢 低 |
| 3 | `outcast.py` | 手牌位置机制 | 110 | 🟡 中 |
| 4 | `shatter.py` | 抽牌时手牌操作 | 74 | 🟢 低 |
| 5 | `choose_one.py` | 德鲁伊抉择 | 159 | 🟡 中 |
| 6 | `dormant.py` | 休眠状态标志 | 50 | 🟢 低 |
| 7 | `quest.py` | 任务进度追踪 | 265 | 🔴 高 |
| 8 | `secret_triggers.py` | 对手奥秘解析 | 143 | 🔴 高 |
| 9 | `corpse.py` | 死亡骑士残骸 | 222 | 🟡 中 |
| 10 | `deathrattle.py` | 亡语触发（部分在 pipeline） | 141 | 🟡 中 |
| 11 | `location.py` | 位置效果（混合管线） | 210 | 🟡 中 |
| 12 | `mcts/turn_advance.py` | **完整并行模拟** | 644 | 🔴 高 |

### 2.4 15 个 CN Regex 违规文件

| # | 文件 | CN regex 数量 | 主要模式 |
|---|------|-------------|----------|
| 1 | `choose_one.py` | 4 | `获得护甲`, `获得攻击力`, `召唤`, `抽张` |
| 2 | `executor.py` | 2 | `召唤`, `费` (随机召唤) |
| 3 | `discover.py` | 3 | `发现.*?法力值`, `费法术`, `消耗` |
| 4 | `simulation.py` | 1 | `获得个` (残骸) |
| 5 | `turn_advance.py` | 1 | `回合开始时获得` |
| 6 | `hero_card_handler.py` | 1 | `英雄技能` |
| 7 | `quest.py` | 5 | `总计张`, `施放个`, `奖励` |
| 8 | `corpse.py` | 4 | `消耗份残骸`, `获得残骸`, `造成伤害` |
| 9 | `v8_contextual.py` | 3 | `召唤`, `造成伤害`, `抽牌` |
| 10 | `kindred.py` | 5 | `延系`, `法术伤害+`, `消耗减少` |
| 11 | `outcast.py` | 3 | `流放再抽`, `流放+`, `流放消耗` |
| 12 | `rng_model.py` | 1 | `damage.*到.*` |
| 13 | `lethal_threat.py` | 3 | `造成伤害` (×3) |
| 14 | `colossal.py` | 1 | `巨型+` |
| 15 | `dormant.py` | 1 | `休眠个回合` |

**总计约 80 个 CN regex 模式需要迁移**

---

## 三、设计标准（不可违反）

> 详细版见 [card-effect-parsing-standard.md](./card-effect-parsing-standard.md)

### Standard 1: English-Only Logic Layer
- `abilities/*.py`（解析层）: 仅英文文本
- `search/*.py`（模拟/编排层）: 仅 mechanics tags / CardAbility 结构
- `mcts/*.py`（搜索层）: 仅 mechanics tags
- `evaluators/*.py`（评估层）: 仅英文（只读）
- **允许 CN**: `card_effects.py`, `spell_target_resolver.py`, `effect_keywords.py`

### Standard 2: Mechanics-Based Detection
- 检测卡牌行为用 `mechanics` tags, `english_text` patterns, `CardAbility` structs
- **禁止**: card.name 字符串, dbf_id 比对

### Standard 3: Data-Driven Pools
- 效果池/token池/附魔池从卡牌数据库查询，不用硬编码 Python 列表

### Standard 4: Constraint Parsing via Structured Data
- 约束解析用 EN 文本关键词匹配，不用 CN regex
- 例: `_DARK_GIFT_CONSTRAINT_MAP` 模式

### Standard 5: Zero Regex in Simulation Layer
- orchestrator.py, simulation.py, executor.py, mechanic modules **零 regex**
- 所有解析在 parser.py 或 card_effects.py

---

## 四、重构实施计划

### Phase P7: CN Regex 大迁移（15 文件 → EN）

**目标**: 消除逻辑层全部 80 个 CN regex

**策略**: 每个 CN regex 转换为以下三种方式之一：
- **A. Mechanics tag 检测**: 适用于有 mechanics 标签的效果（如 BATTLECRY, DEATHRATTLE）
- **B. EN text keyword 匹配**: 适用于有 english_text 的卡牌
- **C. card_effects.get_effects()**: 适用于 card_effects.py 已有提取的数据

**分组执行**（按难度，每组 3-5 文件）:

#### P7-1: 简单模块（3 文件，5 patterns）

| 文件 | CN pattern | 目标方式 |
|------|-----------|----------|
| `colossal.py:52` | `巨型\+(\d+)` | B: `"colossal" in english_text` + extractors |
| `dormant.py:19` | `休眠\s*(\d+)\s*个?回合` | B: `"dormant" in english_text` + extractors |
| `executor.py:347,356` | `召唤\s*(\d+)`, `(\d+)费` | C: 用 `get_effects()` 数据 |

#### P7-2: Mechanic 模块（5 文件，17 patterns）

| 文件 | CN patterns | 目标方式 |
|------|-----------|----------|
| `outcast.py` (3) | `流放再抽`, `流放+/+`, `流放消耗` | B: `"outcast"` keyword |
| `kindred.py` (5) | `延系`, `法术伤害+`, `消耗减少` | B: `"kindred"` keyword |
| `corpse.py` (4) | `消耗残骸`, `获得残骸`, `造成伤害` | B: `"corpse"` keyword |
| `quest.py` (5) | `总计张`, `施放个`, `奖励` | B: `"quest"` keyword |
| `choose_one.py` (4) | `获得护甲`, `获得攻击力`, `召唤`, `抽张` | B: `"choose one"` keyword |

#### P7-3: 复杂模块（4 文件，12 patterns）

| 文件 | CN patterns | 目标方式 |
|------|-----------|----------|
| `discover.py` (3) | `发现.*?法力值`, `费法术`, `消耗` | B: `"discover"` keyword |
| `simulation.py` (1) | `获得个` (残骸) | C: `get_effects()` |
| `hero_card_handler.py` (1) | `英雄技能` | B: EN text |
| `turn_advance.py` (1) | `回合开始时获得` | C: `get_effects()` |

#### P7-4: 评估/搜索层（3 文件，7 patterns）

| 文件 | CN patterns | 目标方式 |
|------|-----------|----------|
| `v8_contextual.py` (3) | `召唤`, `造成伤害`, `抽牌` | C: `get_effects()` |
| `lethal_threat.py` (3) | `造成伤害` | C: `get_effects()` |
| `rng_model.py` (1) | `damage.*到.*` | C: `get_effects()` |

**验证**: 每组完成后 `python -m pytest tests/ -x -q` 必须全部通过

---

### Phase P8: Effects.py 合并（消除双 EffectKind）

**目标**: 将 `effects.py` (System 3) 合并到 abilities pipeline

**当前状态**:
- `effects.py` EffectKind: 13 auto-int 值 (DAMAGE, HEAL, SUMMON, DRAW, BUFF, ARMOR, DESTROY, RANDOM_DAMAGE, AOE_DAMAGE, DISCARD, MANA, COPY, TRANSFORM, ENCHANT)
- `definition.py` EffectKind: 31 string 值 (DAMAGE, SUMMON, DRAW, GAIN, HEAL, GIVE, DESTROY, FREEZE, SILENCE, DISCOVER, ...)
- 5 种效果仅存在于 effects.py: BUFF, ARMOR, RANDOM_DAMAGE, AOE_DAMAGE, MANA

**方案**:
1. 将 5 种缺失效果添加到 `definition.py` EffectKind
2. 在 `executor.py` 添加对应 _exec_* handlers
3. 创建 `parse_legacy_effect()` adapter: colon-delimited string → definition.py EffectSpec
4. 更新 `deathrattle.py` 和 `trigger_system.py` 使用 adapter
5. 保留 `effects.py` 但标记为 deprecated

**风险**: 低（仅 2 个消费者，lazy import）

---

### Phase P9: Mechanic 模块收编（选择 2-3 个试点）

**目标**: 将部分 mechanic 模块路由到 ability pipeline

**优先级排序**:

| 模块 | 难度 | 收益 | 推荐顺序 |
|------|------|------|----------|
| `herald.py` | 🟢 低 | 消除直接 board.append | 1 |
| `dormant.py` | 🟢 低 | 消除直接 flag 设置 | 2 |
| `shatter.py` | 🟢 低 | 消除直接 hand 操作 | 3 |
| `outcast.py` | 🟡 中 | 已有 executor handlers | 4 |
| `colossal.py` | 🟡 中 | 已有 executor handler | 5 |

**试点方案**: herald + dormant + shatter → 通过 orchestrator 调度

**暂不收编** (太复杂):
- quest.py (进度追踪有状态)
- secret_triggers.py (对手行为触发)
- turn_advance.py (完整并行模拟)

---

### Phase P10: 解耦与清理

**目标**: 解决剩余架构问题

#### P10-1: 双 TargetSpec 统一
- `spell_target_resolver.TargetSpec`: 零外部导入，纯内部实现
- **方案**: 重命名为 `_InternalTargetSpec`，不合并

#### P10-2: 7 个 Executor Stubs
- COPY, SHUFFLE, TRANSFORM, RETURN, TAKE_CONTROL, SWAP, CAST_SPELL
- **方案**: 添加 `NotImplementedError` 或标记为 `log.debug`

#### P10-3: orchestrator → evaluator 解耦
- `_pick_target()` 已注入 `target_selector` 参数 ✅
- 移除 lazy-load fallback，要求显式注入

#### P10-4: 消除 effects.py 死 import re
- `effects.py:20` imports re 但未使用 → 直接删除

#### P10-5: choose_one._parse_option_effects CN regex
- 4 个 CN regex patterns → EN keyword matching

---

### Phase P11: I-MCTS 就绪

**目标**: 为 LLM+MCTS 集成准备结构化接口

#### P11-1: GameState 结构化描述
```python
def to_llm_prompt(self) -> str:
    """返回 LLM 可读的游戏状态描述"""
    # 我方: 生命/护甲/法力/手牌(名称+费用)/场面(随从名+攻血+关键词)
    # 敌方: 生命/护甲/场面(已知) / 秘密数 / 手牌数
```

#### P11-2: Action 描述
```python
def to_llm_description(self) -> str:
    """返回动作的英文描述"""
    # "Play Fireball (cost 4) targeting enemy hero"
    # "Attack with 3/2 minion into enemy 2/2 minion"
```

#### P11-3: EffectKind 人类可读描述
```python
EFFECT_DESCRIPTIONS = {
    EffectKind.DAMAGE: "Deal {value} damage to {target}",
    EffectKind.HEAL: "Restore {value} health to {target}",
    # ...
}
```

---

## 五、不做的事（裁剪结果）

| 提案 | 决定 | 理由 |
|------|------|------|
| 统一双 TargetSpec | 🔴 丢弃 | 字段根本不同，零外部消费者 |
| 全面 Grammar Parser | 🔴 丢弃 | PoC 已失败，NL 文本太灵活 |
| 删除 effects.py | 🔴 丢弃 | 2 个活跃消费者 |
| 迁移 rhea/ 消费者 | 🔴 丢弃 | 28 处，范围太大 |
| turn_advance.py 收编 | 🔴 丢弃 | 完整并行模拟，独立路径 |
| watcher/ 层重构 | 🔴 丢弃 | 独立输入管线，不在范围 |
| token_cards.py 硬编码 | 🟡 简化 | 数据文件可接受，未来 data-driven |
| global_tracker.py COIN_CARD_IDS | 🟡 简化 | watcher 层，标准 ID |

---

## 六、架构演进目标

### 当前架构
```
3 套并行解析 → 混合调度 → 直接状态变异
15 个 CN regex 文件 → 12 个绕过 pipeline 的模块
```

### 目标架构
```
单一 abilities pipeline:
  card_data.py (CardDB) → parser.py (EN) → definition.py (CardAbility)
    → orchestrator.py (trigger dispatch) → executor.py (state mutation)
    → simulation.py (action application)

允许例外:
  card_effects.py (CN+EN regex, 数据层)
  spell_target_resolver.py (CN+EN regex, 目标解析层)
  turn_advance.py (独立 MCTS 模拟)
```

### 演进路径
```
P7 (CN regex 迁移) → P8 (effects.py 合并) → P9 (mechanic 收编试点)
  → P10 (解耦清理) → P11 (I-MCTS 就绪)
```

---

## 七、验证矩阵

每个 Phase 完成后必须验证：

| 检查项 | 命令 |
|--------|------|
| 单元测试 | `python -m pytest tests/ -x -q -k "not (live_games or powerlog_mcts or powerlog_scenario or game5 or game7 or watcher or scenario_integration or engine_v1)"` |
| 语法检查 | `python -m py_compile <changed_file>` |
| CN regex 扫描 | `rg '[\x{4e00}-\x{9fff}]' analysis/search/abilities/ analysis/search/*.py --include '*.py'` |
| import re 扫描 | `rg 'import re' analysis/search/abilities/ analysis/search/*.py --include '*.py'` |
| 硬编码扫描 | `rg "(card\.name|dbf_id\s*==|'brann'|'fandral')" analysis/ --include '*.py'` |

---

## 八、已完成重构历史

| Phase | 描述 | 日期 | 测试 |
|-------|------|------|------|
| R1-R12 | Card data consolidation, scoring, http, load_json, except narrowing | 2026-04-24~25 | 736→769 |
| R13 | Abilities architecture unification | 2026-04-25 | 780 |
| P4-1~3 | Abilities framework (definition + tokens + executor) | 2026-04-26 | 848 |
| P4-A~E | orchestrator DRY, simulation cleanup, enumeration, parser | 2026-04-26 | 610 |
| P5 | God methods split + flush_deaths + GameState.copy + _pick_target | 2026-04-26 | 610 |
| P6-1~2 | Dead code removal + keyword dedup | 2026-04-26 | 610 |
| V1-V3+ | Hardcoding cleanup + dark_gift redo + design standard | 2026-04-26 | 613 |

---

## 九、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| CN regex 迁移破坏语义 | 中 | 高 | 逐文件迁移+测试验证，保留 card_effects.py 兜底 |
| mechanic 模块收编引入 bug | 中 | 中 | 先试点 3 个简单模块 |
| effects.py 合并导致循环依赖 | 低 | 高 | adapter 层隔离，lazy import |
| 测试覆盖不足 | 中 | 中 | 每个 Phase 添加 parser 单元测试 |
| 过度工程 | 中 | 中 | 默认选择简单方案，遵循 Standard 5 |

---

## 十、参考资源

### 研究来源
- **Metastone/Spellsource**: JSON card definitions, Spell-Condition-Filter-ValueProvider
- **Fireplace**: Python DSL, Selector/Evaluator/LazyNum/Action
- **Hearthbreaker**: Action/Selector/Condition/Event + JSON
- **SabberStone**: ISimpleTask stack system, 94% coverage
- **Lark parser**: Grammar PoC 失败但设计模式有效

### 项目文档
- [card-effect-parsing-standard.md](./card-effect-parsing-standard.md) — 设计标准
- [completed-refactorings.md](../../.opencode/skills/refactor/references/completed-refactorings-hs_analysis.md) — 完成历史
- [project-defects.md](../../.opencode/skills/refactor/references/project-defects-hs_analysis.md) — 已知缺陷

### 关键记忆标签
- `refactor,phase-4,done,*` — 已完成重构
- `refactor,phase-1,*` — 考古发现
- `refactor,research,design-standard` — 设计标准
- `architecture,abilities,spec` — abilities 架构规范

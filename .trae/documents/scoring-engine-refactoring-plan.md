# 评分引擎重构计划 — 状态模式调研 + 正则替代方案

## 调研结论

### 1. 状态模式是否适用？→ **不适用**

**传统状态模式（State Pattern / FSM）不适合此项目**。原因：

1. **GameState 不是状态机** — 它是一个不可变数据快照（deepcopy 分支），不是有限状态自动机中的"状态"。游戏状态有无限种组合（场面 × 手牌 × 法力 × HP × ...），无法枚举为有限状态集。
2. **炉石不是状态驱动的游戏** — 不像 RPG 中的 Idle→Patrol→Attack→Dead，炉石的"状态"是数据快照而非行为模式。
3. **研究文档已否决 FSM** — "State explosion: too many game states to enumerate"。
4. **已有的更好替代方案**：
   - **MechanicRegistry（注册表/策略模式）** — 已在 V11 设计中，解决 `apply_action` 的可扩展性
   - **FactorGraph（因子图）** — 已在 V11 中实现，替代线性加权评估
   - **StrategicMode（策略枚举）** — LETHAL/DEFENSIVE/DEVELOPMENT 三模式已起作用

**真正需要改进的地方**：

| 改进项 | 当前问题 | 建议方案 |
|--------|---------|---------|
| 统一 Phase 定义 | 分界点散落且不一致（early 是 3/4？late 是 7+/8+？） | 创建 `Phase` 枚举 + 工厂方法 |
| apply_action 拆分 | ~350 行 if/elif + 15+ try/except | 实现 MechanicRegistry 注册表模式 |
| 事件统一 | TriggerDispatcher 和 apply_action 各自处理 | 让 apply_action 通过 MechanicRegistry 统一调度 |

---

### 2. 正则覆盖率分析

#### 数据概况
- 标准卡池 **1015 张**（1012 张有文本）
- 类型分布：MINION 630, SPELL 335, WEAPON 29, LOCATION 17, HERO 2

#### EFFECT_PATTERNS 覆盖率
| 指标 | 数值 |
|------|------|
| 有文本的卡 | 1012 |
| 被至少 1 个正则匹配 | 585 (57.8%) |
| **未被任何正则匹配** | **427 (42.2%)** |

#### 各正则命中次数
| 正则 | 命中数 |
|------|--------|
| summon | 182 |
| direct_damage | 120 |
| summon_stats | 84 |
| generate | 77 |
| summon_race | 50 |
| buff_atk | 49 |
| destroy | 46 |
| copy | 46 |
| aoe_damage | 45 |
| mana_thirst | 29 |
| armor | 25 |
| random_damage | 24 |
| discover_minion | 23 |
| dark_gift | 20 |
| reveal | 19 |
| imbue | 19 |
| discover_spell | 19 |
| discard | 18 |
| discover_race | 17 |
| buff_race | 17 |
| condition | 15 |
| heal | 9 |
| discover_spell_school | 6 |
| draw | 3 |
| **mana_reduce** | **0** |
| **discover_weapon** | **0** |
| **forge_effect** | **0** |
| **excavate_effect** | **0** |

**4 个正则零命中**，可以移除。

#### 未匹配的 427 张卡 — 根因分析

**核心问题：`<b>` HTML 标签和 `$` / `#` 变量符号导致匹配失败**。

实际卡牌文本格式：
```
造成$6点伤害        ← $ 符号导致 "造成\s*(\d+)" 失配
恢复#3点生命值       ← # 符号导致 "恢复\s*(\d+)" 失配
<b>发现</b>一张      ← HTML 标签导致 "发现" 命中但其他模式失配
战吼：冻结一个敌人    ← "战吼" 不在 EFFECT_PATTERNS 中
```

340 张未匹配的卡**有 mechanics 标签**（BATTLECRY, DISCOVER 等），但没有被 EFFECT_PATTERNS 匹配到具体效果。

---

### 3. 有没有不用正则的更好方式？

#### 3.1 HearthstoneJSON API 结构化数据

API 提供的结构化字段：

| 字段 | 覆盖 | 可替代的正则 |
|------|------|-------------|
| `mechanics` | 37 种标签，覆盖 1015 张中的 ~530 张 | 可完全替代 L2 关键词评分层 |
| `referencedTags` | 30 种，覆盖 1441 张（全量 API） | 可补充 mechanics 未覆盖的标签 |
| `overload` | 81 张 | 可替代 "过载" 文本解析 |
| `spellDamage` | 57 张 | 可替代 "法术伤害" 文本解析 |
| `spellSchool` | 175 张 | 已在使用，无需文本推断 |
| `armor` | ~81 张 | 可替代 "获得护甲" 文本解析 |
| `races` | 多种族卡 | 比文本匹配更准确 |

**关键发现：API 不提供具体效果数值**。例如：
- Fireball 的 API 数据只有 `spellSchool: 'FIRE'`，**没有** "造成 6 点伤害" 的结构化字段
- 死亡之翼的 API 数据只有 `mechanics: ['BATTLECRY']`，**没有** "选择一个大灾变" 的结构化字段

**结论：API 的 `mechanics` + `referencedTags` 可以替代 L2 关键词层（完全不用正则），但 L3 文本效果层（具体数值如伤害量、抽牌数）仍需从 `text` 字段解析。**

#### 3.2 改进方案：结构化标签 + 预处理正则

**推荐方案：三层混合架构**

```
Layer 1: 纯结构化标签（不用正则）
  └─ mechanics + referencedTags + overload + spellDamage + armor + races
  └─ 覆盖所有卡牌的 "是什么"（关键词类型）

Layer 2: 预处理文本 + 正则（修复匹配率）
  └─ 先清除 <b></b> HTML 标签
  └─ 将 $N 和 #N 替换为纯数字
  └─ 然后用精简的正则提取数值参数
  └─ 覆盖卡牌的 "具体效果量"（伤害/治疗/抽牌数量）

Layer 3: 条件期望（保留，但基于结构化标签触发）
  └─ 用 mechanics 替代文本正则判断条件类型
```

**预处理文本修复示例**：
```
原始: "造成$6点伤害" → 清洗后: "造成6点伤害" → 正则 "造成\s*(\d+)\s*点伤害" ✓
原始: "恢复#3点"     → 清洗后: "恢复3点"     → 正则 "恢复\s*(\d+)\s*点" ✓
原始: "<b>发现</b>"  → 清洗后: "发现"         → 正则 "发现" ✓
```

**预估覆盖率提升**：从 57.8% → ~85%+

---

## 实施计划

### Phase 1: 文本预处理函数（预估覆盖率 57.8% → 85%+）

**文件**: `hs_analysis/scorers/scoring_engine.py`

1. 新增 `_clean_card_text(text)` 函数：
   - 移除 `<b>` / `</b>` HTML 标签
   - 将 `$N` 和 `#N` 替换为纯数字 `N`
   - 移除 `[x]` 格式标记
   - 规范化空白字符

2. 在 `parse_text_effects()` 中先调用 `_clean_card_text()`

3. 移除 4 个零命中正则：`mana_reduce`、`discover_weapon`、`forge_effect`、`excavate_effect`

4. 运行覆盖率验证脚本确认提升

### Phase 2: 结构化标签评分层（替代 L2 正则部分）

**文件**: `hs_analysis/scorers/constants.py` + `scoring_engine.py`

1. 将 `mechanics` 和 `referencedTags` 字段纳入 `Card` 模型和 `unified_standard.json`
   - 修改 `hs_analysis/data/hsdb.py` 的数据导出，确保 `referencedTags` 进入 JSON
   - 修改 `Card` dataclass 新增 `referenced_tags: List[str]`

2. 重构 `calc_keyword_score()` — 完全基于 `mechanics` 列表，不依赖文本
   - 已有的 `KEYWORD_TIERS` 和 `KEYWORD_CN` 直接匹配 mechanics 标签
   - 无需正则

3. 新增结构化数值提取：
   - `overload` 字段 → 直接使用数值（替代正则）
   - `spellDamage` 字段 → 直接使用数值（替代正则）
   - `armor` 字段 → 直接使用数值（替代正则）

### Phase 3: L3 文本效果层精简

**文件**: `hs_analysis/scorers/constants.py`

1. `EFFECT_PATTERNS` 精简为只提取"具体数值"的模式：
   - 保留：`direct_damage`, `random_damage`, `draw`, `summon_stats`, `heal`, `aoe_damage`, `buff_atk`, `armor`（数值型）
   - 移除：`summon`, `destroy`, `copy`, `generate` 等纯关键词型（已由 mechanics 覆盖）
   - 新增：`buff_health`（`+\d+.*生命值`）

2. `CONDITION_DEFS` 改为基于 mechanics 触发：
   - `"discover_chain"` → 触发条件从 `r"发现"` 改为 `"DISCOVER" in card.mechanics`
   - `"deathrattle_payoff"` → `"DEATHRATTLE" in card.mechanics`
   - 其他类似

### Phase 4: 统一 Phase 枚举

**文件**: 新增 `hs_analysis/models/phase.py`

1. 定义 `Phase` 枚举（EARLY/MID/LATE）
2. 定义 `detect_phase(turn_number, hp_ratio)` 工厂方法
3. 统一分界点：early ≤ 4, mid ≤ 7, late > 7
4. 更新所有使用方：
   - `bsv.py` 的 `_get_phase()`
   - `rhea_engine.py` 的 `_detect_phase()`
   - `pipeline.py` 的 `_combo_depth_for_phase()`

### Phase 5: 验证

1. 运行正则覆盖率验证脚本，确认从 57.8% 提升到 85%+
2. 运行全量测试确保无回归
3. 对比重构前后评分差异（抽样 TOP 30 卡牌排名变化）

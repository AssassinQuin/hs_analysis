---
date: 2026-04-19
topic: "V10 Position-Aware Decision Engine"
status: draft
parent: v9-decision-engine-v2
---

## Problem Statement

V9 引擎把场面当成无序集合处理——`board` 是平面 `List[Minion]`，没有位置语义。但炉石传说中，**站位本身就是决策的一部分**，且影响：

1. 位置解牌的目标选择（"消灭最左/最右的随从"）
2. 邻接加成（"相邻随从获得+X攻击力"）
3. 亡语召唤的继承位置
4. OUTCAST 的手牌位置判定
5. 多目标解牌的覆盖范围

当前 V9 的 `enumerate_legal_actions` 已为 PLAY MINION 生成不同位置的 Action（rhea_engine.py:120-125），但评估函数和对手建模完全没有位置感知。

---

## 炉石位置规则（完整）

### 规则1：场面位置 0-6

- 场面最多 7 个随从，位置从左到右为 index 0-6
- 随从的位置在打出时由**玩家主动选择**
- 位置影响：邻接 buff、位置解牌目标、OUTCAST 激活

### 规则2：手牌位置

- 手牌最多 10 张，位置从左到右为 index 0-9
- **OUTCAST** 卡牌只有在最左(index 0)或最右(index hand_size-1)才触发额外效果
- 抽牌/生成的卡牌加入**最右侧**（`append`）

### 规则3：召唤位置

| 召唤来源 | 放置位置 | 当前引擎 |
|----------|----------|----------|
| 玩家打出随从 | 玩家选择任意位置 | ✅ `insert(pos)` |
| 法术召唤 | 最右侧 (`append`) | ✅ `append` |
| 亡语召唤 | **继承死亡随从的位置** | ❌ 死亡后 list comp 移除，无继承 |
| 战吼召唤 | 继承打出随从位置（或指定位置） | ❌ 无战吼机制 |
| 衍生物/Token | 最右侧 | ✅ `append` |
| Discover/发现获得 | 手牌最右侧 | ✅ `append` |

### 规则4：死亡清理后的位置

- 随从死亡后，右侧随从**自动左移**填补空位
- 当前引擎用 `list comprehension filter` 实现，等价于左移 ✅
- **但**：如果有亡语召唤，需要在移除前记录位置，召唤后插入该位置

### 规则5：位置相关解牌

- "消灭最左边/最右边的随从" → 按 board index 选择目标
- "对一个随从及其相邻随从造成伤害" → 需要 index±1 计算
- "将一个随从移到最左/最右" → 改变位置
- "随从相邻的随从获得+X" → 需要 index 邻接感知

### 规则6：站位策略决策因素

玩家打出随从时选择站位，决策基于：

- **对手职业的解牌池概率** — 牧师有"消灭最左边"？高价值随从不放左
- **对手卡组特征** — 快攻少位置解，控制卡组可能有
- **己方随从价值排序** — 核心随从避开常见解位
- **邻接加成最大化** — buff 随从放中间，让两侧都能吃到
- **亡语链考虑** — 亡语随从死亡后继承位置，影响后续站位

---

## 当前引擎现状

### 已有的位置基础设施 ✅

| 组件 | 位置感知 | 文件位置 |
|------|----------|----------|
| `Action.position` | ✅ 有 position 字段 | rhea_engine.py:Action dataclass |
| `enumerate_legal_actions` | ✅ 为每个 board position 生成 PLAY action | rhea_engine.py:120-125 |
| `apply_action` PLAY MINION | ✅ `insert(pos, minion)` | rhea_engine.py:217 |
| `spell_simulator.apply_summon` | ✅ 支持 position 参数 | spell_simulator.py:206 |
| `spell_simulator.apply_destroy` | ✅ `pop(idx)` 按位置移除 | spell_simulator.py:310 |

### 缺失的位置感知 ❌

| 组件 | 缺失内容 |
|------|----------|
| `evaluate()` | 不考虑位置风险 |
| `OpponentSimulator` | 对手站位策略未建模 |
| `RiskAssessor` | 无位置风险因子 |
| 死亡+亡语联动 | `list comp` 移除不保留位置 |
| OUTCAST 判定 | 手牌位置未检查 |
| 邻接 buff | 无 index±1 逻辑 |
| 位置解牌解析 | `spell_simulator` 无位置目标 |
| `resolve_effects` | summon 调用不传 position（默认-1→append） |

---

## 设计方向

### 核心思想：位置作为决策变量

当前 `enumerate_legal_actions` 已经为 PLAY MINION 生成 N 个位置变体。V10 的核心是让**评估函数理解位置差异**，使 RHEA 搜索能自然选择最优站位。

### Phase 1：评估函数加入位置因子

在 `evaluate()` 中新增位置风险评分：

- **位置风险因子** = 对手职业 × 位置 × 随从价值的函数
- 牧师 vs 最左边 → 高风险
- 猎人 → 位置风险低（少位置解）
- 高价值随从在"危险位置" → 降低评估分

### Phase 2：死亡+亡语位置继承

修改死亡清理逻辑：

- 移除死亡随从前记录 `(index, has_deathrattle)`
- 如果有亡语，在清理后在该 index 位置 `insert` 召唤的随从
- 多个亡语按从左到右顺序处理

### Phase 3：对手站位建模

`OpponentSimulator` 扩展：

- 对手打随从也选位置（基于简单启发式：高价值放"安全"位置）
- 对手可能持有的解牌 → 影响我方站位最优策略

### Phase 4：Discover 池 + 位置解牌概率

- 构建位置解牌的卡池
- Discover 时计算"抽到位置解牌"的概率
- 该概率影响站位策略的期望值

---

## 依赖关系

```
Phase 1 (评估位置因子) ──→ Phase 3 (对手站位建模)
                              ↓
Phase 2 (亡语位置继承) ──→ Phase 4 (Discover 池 + 概率)
```

Phase 1 和 Phase 2 可并行，Phase 3 和 4 依赖前面的基础。

---

## 风险评估

| 风险 | 影响 | 缓解 |
|------|------|------|
| 决策空间膨胀 | 每个随从 × 7 位置 = 7x 动作空间 | RHEA 染色体长度限制 + 位置只在关键场景展开 |
| 评估函数复杂度 | 位置因子计算可能拖慢搜索 | 预计算对手职业的位置风险表 |
| 数据缺失 | 位置解牌清单需要手动整理 | 从 unified_standard.json 文本解析 |
| 亡语链复杂度 | 多个亡语同时触发 → 位置竞争 | 从左到右确定性处理 |

---

## Open Questions

1. 当前卡池中有多少张位置相关解牌？需要从 unified_standard.json 中提取
2. 对手站位建模的精度需求？简单启发式 vs 贝叶斯推断
3. 是否需要区分"已知对手卡组" vs "未知卡组"的位置策略？
4. 亡语召唤多个随从时（如载人飞天魔像），多个随从如何排列？是否都在同一位置向右扩展？

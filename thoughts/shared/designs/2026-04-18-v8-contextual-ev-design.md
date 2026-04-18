---
date: 2026-04-18
topic: "V8 Contextual Expected Value System"
status: validated
---

# V8 情境期望价值系统设计

## Problem Statement

当前评分系统（V7）给每张牌一个静态分数。实际对战中，牌的价值高度依赖情境：

1. **回合效率**：第2回合出两张1费 vs 一张2费，曲线利用率不同
2. **类型差异**：同费用的随从、法术、武器、地标、任务价值完全不同
3. **时间衰减**：同一张牌第2回合和第8回合打出的价值不同
4. **发现/随机池质量**：发现龙 vs 发现海盗，池子质量天差地别
5. **回溯决策**：回溯后的牌是否比原版更好，取决于当前局面
6. **致命感知**：丝血场景下，伤害类发现/亡语的期望应该暴涨
7. **亡语随机池**：亡语召唤/伤害的期望应该纳入牌面解析

**核心问题**：手牌总价值 ≠ Σ v7_score。我们需要 `V(hand, game_state)` 而不是 `Σ V(card)`。

## Constraints

- **性能约束**：RHEA 每代评估数百个染色体，情境修正必须是 O(hand_size) 级别的查表+算术，不能做蒙特卡洛模拟
- **数据约束**：没有按回合×组合×对手职业的细粒度胜率数据，只有 per-card 的 HSReplay 数据
- **兼容约束**：V8 是 V7 的上层包装，不替代 V7。V7 作为 base score 继续存在
- **牌池数据**：`unified_standard.json` 有 1015 张牌，可按 race/type/cardClass 过滤构建池子，但没有现成的池子定义文件
- **现有依赖**：composite_evaluator、multi_objective_evaluator、rhea_engine 都从 Card.v7_score 读分。V8 修正必须在读取点之前完成

## Approach

**混合规则+预计算查表方案**。

选择理由：
- 蒙特卡洛模拟最准确但性能不可接受（每个发现/亡语做 100+ 模拟，RHEA 性能降 100x）
- ML 模型需要大量训练数据，我们没有
- 纯 HSReplay 数据驱动缺少细粒度（无 per-turn×combo 数据）
- 混合方案：离线预计算池子质量和修正系数，运行时 O(1) 查表

## Architecture

### 总体结构

```
V7 static score (base)
    │
    ▼
┌──────────────────────────────────────┐
│        V8 Contextual Scorer          │
│                                      │
│  ┌──────────────────────────────┐    │
│  │ 1. Turn Curve Adjuster       │    │  ← 回合价值衰减
│  │    turn_factor(turn, card)   │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 2. Type Context Modifier     │    │  ← 类型情境修正
│  │    type_factor(type, board)  │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 3. Pool Quality Assessor     │    │  ← 发现/随机池 EV
│  │    pool_ev(card, state)      │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 4. Deathrattle EV Resolver   │    │  ← 亡语期望解析
│  │    deathrattle_ev(card)      │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 5. Lethal-Aware Booster      │    │  ← 致命感知加权
│  │    lethal_boost(card, state) │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 6. Rewind Decision Maker     │    │  ← 回溯收益判断
│  │    rewind_ev(card, state)    │    │
│  └──────────────────────────────┘    │
│  ┌──────────────────────────────┐    │
│  │ 7. Combo Synergy Detector    │    │  ← 组合协同价值
│  │    synergy_ev(hand)          │    │
│  └──────────────────────────────┘    │
│                                      │
│  contextual_score = base_v7          │
│    × turn_factor                     │
│    × type_factor                     │
│    + pool_ev_bonus                   │
│    + deathrattle_ev_bonus            │
│    × lethal_boost                    │
│    + rewind_ev_delta                 │
│    + synergy_bonus                   │
└──────────────────────────────────────┘
    │
    ▼
composite_evaluator reads contextual_score instead of raw v7_score
```

### 集成方式

V8 不是替代 V7，而是在 composite_evaluator 的读取点插入情境修正层。

**关键**：不改 Card.v7_score（保持静态值），而是在 evaluator 中引入修正函数。

```
之前: hand_value = sum(c.v7_score for c in state.hand)
之后: hand_value = sum(contextual_score(c, state) for c in state.hand)
```

其中 `contextual_score(card, state)` 内部组合 7 个子模块的输出。

## Components

### Component 1: Turn Curve Adjuster（回合曲线调整器）

**解决的问题**：需求 1（费用组合效率）、需求 3（同一牌不同回合价值不同）

**输入**：
- `card` — 待评估的牌
- `state.turn_number` — 当前回合
- `state.mana.available` — 当前可用费用
- `card.cost` — 牌的费用
- HSReplay `avg_turns` 数据（从 hsreplay_cache.db 读取）

**逻辑**：
- 每张牌有一个最佳出牌回合（基于 HSReplay avg_turns 或 cost+1 推算）
- 偏离最佳回合时衰减：`turn_factor = 1.0 - 0.08 * |current_turn - optimal_turn|`
- 下限 0.5（不会完全归零）
- 费用曲线效率：手牌总费用 / 可用费用的比率。高利用率 = 好曲线

**数据来源**：
- `hsreplay_cache.db` → `card_stats.avg_turns`
- 兜底公式：`optimal_turn = cost + 1`（对于没有数据的牌）

**输出**：`turn_factor: float`（0.5 ~ 1.2）

### Component 2: Type Context Modifier（类型情境修正器）

**解决的问题**：需求 2（同费用不同类型牌价值不同）

**输入**：
- `card.card_type` — MINION / SPELL / WEAPON / LOCATION / HERO
- `state.board` — 当前场面（是否已有随从、武器等）
- `state.turn_number` — 回合数

**逻辑**：
- 基础类型修正系数表（基于游戏阶段）

| 阶段 | 回合 | 随从 | 法术 | 武器 | 地标 |
|------|------|------|------|------|------|
| 早期 | 1-4 | 1.1 | 0.9 | 0.8 | 0.7 |
| 中期 | 5-7 | 1.0 | 1.0 | 1.0 | 1.0 |
| 后期 | 8+ | 0.9 | 1.1 | 1.1 | 1.1 |

- 场面修正：已有 5+ 随从时，随从价值下降（场面快满了）；没有武器时，武器价值上升
- 法术修正：对手场面强时，AOE 法术价值上升

**输出**：`type_factor: float`（0.6 ~ 1.3）

### Component 3: Pool Quality Assessor（牌池质量评估器）

**解决的问题**：需求 4（发现/随机牌要关联具体牌池期望）

**离线预计算**（生成 `hs_cards/pool_quality_report.json`）：
- 从 `unified_standard.json` 按条件过滤出每个池子
- 池子类型：
  - 种族池：龙、恶魔、野兽、鱼人、海盗、元素、亡灵、图腾、机械、纳迦、德莱尼
  - 法术池：火焰、冰霜、奥术、自然、暗影、神圣、邪能
  - 类型池：随从、法术、武器
  - 职业池：按 cardClass 过滤
- 对每个池子计算：
  - `avg_v7_score` — 池中牌的平均 V7 分数
  - `top_10_pct_score` — 池中前 10% 牌的平均分（发现更可能选到好牌）
  - `pool_size` — 池子大小
  - `quality_std` — 标准差（高方差 = 池子质量不稳定）

**运行时**：
- 牌文本中有"发现"或"随机"时，匹配池子类型
- `pool_ev = pool_quality_report[pool_name].top_10_pct_score * 0.6 + avg_v7_score * 0.4`
- 乘以 L5 的 discover_chain 概率（0.8）

**数据来源**：
- `hs_cards/unified_standard.json` — 1015 张牌
- `hs_cards/v7_scoring_report.json` — 每张牌的 V7 分数
- `scripts/v7_scoring_engine.py:276-277` — RACE_NAMES, SCHOOL_NAMES 常量

**输出**：`pool_ev_bonus: float`（加到 base score 上）

### Component 4: Deathrattle EV Resolver（亡语期望解析器）

**解决的问题**：需求 7（亡语随机池的期望计算）

**输入**：
- `card.text` — 牌面文本
- `state.board` — 当前场面

**逻辑**：
- 扩展现有 EFFECT_PATTERNS，新增亡语定向模式：

| 模式 | 正则 | EV 计算 |
|------|------|---------|
| 亡语召唤 | `亡语.*?召唤.*?(\d+)/(\d+)` | `(atk+hp) * 0.3 * 0.7` |
| 亡语召唤X个 | `亡语.*?召唤(\d+)个` | `count * avg_minion_v7 * 0.3` |
| 亡语伤害 | `亡语.*?造成.*?(\d+)` | `damage * 0.35` |
| 亡语抽牌 | `亡语.*?抽.*?(\d+)` | `count * 1.2 * 0.7` |
| 亡语装备 | `亡语.*?装备` | `weapon_avg_v7 * 0.5` |
| 亡语buff | `亡语.*?\+\d+/?\+?\d*` | `stat_bonus * 0.5` |
| 通用亡语 | `亡语` (兜底) | `L5_deathrattle_payoff = 0.7 * base * 0.3` |

- 亡语触发概率：基于随从存活回合数的估计。快攻场面 0.9，控制场面 0.6
- 亡语与场面交互：已有"亡语触发"类牌（如 Teron Gorefiend 效果）时，亡语价值翻倍

**输出**：`deathrattle_ev_bonus: float`（加到 base score 上）

### Component 5: Lethal-Aware Booster（致命感知加权器）

**解决的问题**：需求 6（丝血反杀场景下的期望调整）

**输入**：
- `state.opponent.hero.hp + armor` — 对手剩余血量
- `card.text` — 牌面文本（是否包含伤害效果）
- `state.get_total_attack()` — 场面总攻击力

**逻辑**：
- 计算致命距离：`lethal_gap = opp_hp + opp_armor - total_attack`
- 修正系数：

| 致命距离 | 伤害类修正 | 非伤害类修正 |
|----------|-----------|-------------|
| ≤ 0（已致命） | 1.0（不重要了） | 1.0 |
| 1-5 | 1.5 | 0.8 |
| 6-10 | 1.3 | 0.9 |
| 11-15 | 1.15 | 0.95 |
| > 15 | 1.0 | 1.0 |

- 伤害类牌检测：文本匹配 "造成.*伤害" 或 "消灭" 或 card_type == "WEAPON"
- 发现池加权：如果发现池中有伤害牌，发现EV在致命距离内提升（需查询 pool_quality_report 中伤害牌比例）

**输出**：`lethal_boost: float`（0.8 ~ 1.5 的乘数）

### Component 6: Rewind Decision Maker（回溯决策器）

**解决的问题**：需求 5（回溯牌要判断回溯收益）

**输入**：
- `card.text` — 包含"回溯"关键字的牌
- `card.v7_score` — 当前牌的 V7 分数
- `state` — 游戏状态

**逻辑**：
- 回溯牌的文本通常描述回溯后的效果
- 预计算：对每张回溯牌，从 unified_standard.json 中找到回溯变体，对比两者的 V7 分数
- 存储 `rewind_delta_report.json`：每张回溯牌的 `{dbfId, original_v7, rewind_v7, delta}`
- 运行时：
  - 如果回溯后分数更高（delta > 0），给回溯选项加分
  - 如果当前手牌有空位、费用充裕，回溯价值更高
  - 如果场面压力大（对手攻击力高），不回溯（保持当前节奏）更优

**数据来源**：
- 回溯牌识别：文本含"回溯"关键字的牌
- 回溯变体识别：同名牌的不同 dbfId，或 text 中含"回溯"后描述的效果

**输出**：`rewind_ev_delta: float`（加到 base score 上，可为负）

### Component 7: Combo Synergy Detector（组合协同检测器）

**解决的问题**：需求 1 的组合效率部分

**输入**：
- `state.hand` — 整个手牌
- `state.board` — 场面随从

**逻辑**：
- 种族协同：手牌中有 N 张同种族牌时，种族相关牌获得 `(N-1) * 0.1` 的协同加成
- 法术协同：手牌中有"施放法术时触发"的牌 + 法术牌时，双方都获得加成
- 武器协同：有武器buff手牌时，武器牌价值上升
- AOE+场面：有AOE清场法术 + 场面弱时，AOE 价值上升

**协同规则表**（可扩展）：

| 协同类型 | 条件 | 加成 |
|----------|------|------|
| 种族聚集 | 手牌中 3+ 张同种族 | 每张 +0.15 |
| 法术触发 | "施放法术"牌 + 法术牌 | 法术 +0.2, 触发牌 +0.3 |
| buff目标 | buff牌 + 高攻随从 | buff牌 +0.2 |
| 曲线完整 | 手牌覆盖 1-4 费 | 全手牌 ×1.05 |
| 武器武装 | 武器 + 武器buff | 武器 +0.25 |

**输出**：`synergy_bonus: float`（加到 base score 上）

## Data Flow

### 离线预计算流程

```
unified_standard.json ──┐
v7_scoring_report.json ──┤
                         ├─→ pool_quality_generator.py ──→ pool_quality_report.json
hsreplay_cache.db ───────┘
                         │
                         ├─→ rewind_delta_generator.py ──→ rewind_delta_report.json
                         │
                         └─→ synergy_rules.py ──→ synergy_rules.json (硬编码规则)
```

### 运行时流程

```
RHEAEngine.search()
  │
  ├── load_scores_into_hand(state)  ← 加载 V7 base scores
  │
  ├── 对每个 chromosome:
  │     │
  │     ├── apply_actions(state)  ← 模拟出牌
  │     │
  │     └── evaluate_delta(before, after, weights)
  │           │
  │           ├── evaluate(state_after, weights)
  │           │     │
  │           │     └── hand_value = sum(
  │           │           contextual_score(card, state_after)  ← V8 修正
  │           │           for card in state_after.hand
  │           │         )
  │           │         # contextual_score 内部:
  │           │         # base = card.v7_score
  │           │         # × turn_factor(turn, card)
  │           │         # × type_factor(type, board)
  │           │         # × lethal_boost(card, state)
  │           │         # + pool_ev_bonus(card)
  │           │         # + deathrattle_ev_bonus(card)
  │           │         # + rewind_ev_delta(card, state)
  │           │         # + synergy_bonus(hand)
  │           │
  │           └── evaluate(state_before, weights)  ← 同样经过 V8 修正
  │
  └── 返回最优 chromosome
```

### 数据加载策略

- `pool_quality_report.json` — 在 `RHEAEngine.__init__` 时加载一次，缓存在内存
- `rewind_delta_report.json` — 同上
- `hsreplay_cache.db` — 仅 avg_turns 查询，在 ScoreProvider 中缓存
- 协同规则 — 硬编码在 V8 scorer 模块中（规则数量有限，不需要外部配置）

## Error Handling

- **牌池为空**：如果某个池子过滤结果为 0 张牌，`pool_ev_bonus = 0`（不加分）
- **HSReplay 数据缺失**：`avg_turns` 缺失时用兜底公式 `optimal_turn = cost + 1`
- **文本解析失败**：亡语/回溯解析失败时，回退到 L5 的固定概率模型（当前行为）
- **V8 模块加载失败**：整个 V8 层应该是可选的。如果 pool_quality_report.json 不存在，退化为纯 V7 模式
- **性能超时**：如果 V8 修正导致单次 evaluate 超过阈值（如 10ms），自动降级为纯 V7

## Testing Strategy

### 单元测试（每个组件独立测试）

| 组件 | 测试要点 |
|------|----------|
| Turn Curve Adjuster | 同牌不同回合的 turn_factor 变化；极端回合的衰减下限 |
| Type Context Modifier | 不同阶段不同类型的系数；场面饱和时的修正 |
| Pool Quality Assessor | 各池子 avg/top10 分数计算；空池子处理；匹配"发现龙"到龙池 |
| Deathrattle EV Resolver | 各类亡语文本解析；触发概率随场面变化；未知亡语的兜底 |
| Lethal-Aware Booster | 不同致命距离的修正；伤害/非伤害牌的差异 |
| Rewind Decision Maker | 回溯vs原版分数对比；场面压力对回溯决策的影响 |
| Combo Synergy Detector | 种族聚集检测；法术触发协同；无协同时的零输出 |

### 集成测试

- 端到端：构建含发现牌、亡语牌、回溯牌的 GameState → 运行 RHEA → 验证 contextual_score ≠ raw v7_score
- 性能基准：对比有/无 V8 的 RHEA 搜索时间，确认开销 < 20%
- 回归测试：所有现有 test_integration.py 测试继续通过（V8 是叠加层，不改变 V7 base）

### 对比测试

- 选取 5-10 个经典场景（如丝血反杀、空场面铺场、发现池优劣）
- 对比 V7-only vs V8 的出牌决策差异
- 人工验证 V8 决策是否更合理

## Open Questions

1. **回溯变体识别**：回溯牌的变体（回溯后的版本）如何精确匹配？可能需要通过卡牌名称+文本模式匹配，或者需要额外数据源
2. **地标/任务/英雄牌支持**：当前 RHEA 的 action 枚举不处理 LOCATION 和 QUEST，V8 是否需要先扩展 action 枚举？
3. **亡语触发概率**：随从存活回合数估计的精确度。是否需要更复杂的模型（考虑对手的解场能力）？
4. **池子大小惩罚**：小池子（如图腾只有 3 张）发现质量是否应该有惩罚？因为容易重复或质量方差大
5. **V8 权重调优**：7 个组件的相对权重如何确定？可能需要实战数据反馈循环

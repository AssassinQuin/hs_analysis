---
date: 2026-04-18
topic: "RHEA Search + HSReplay L6 Integration Redesign"
status: validated
---

# RHEA 搜索引擎 + HSReplay 单卡数据集成设计

## Problem Statement

现有 EV 决策引擎存在两个核心缺陷：

1. **缺乏实战数据**：V2 模型 (L1-L5) 完全基于理论推导（幂律曲线、关键词分桶、正则解析），没有任何真实对局数据验证。卡牌评分可能与实战强度严重偏离。
2. **搜索框架不够强大**：21 参数线性加权求和 + Top-K Beam Search 的方案：
   - 权重无校准方法（无训练循环）
   - 线性组合无法捕捉非线性交互效应（如圣盾+风怒的组合价值）
   - 对手建模是贪心启发式
   - 学术验证仅达 72% 胜率

**目标**：集成 HSReplay 单卡实战数据，并采用更强的搜索算法，使得决策引擎能综合一切资源（费用、手牌、对手卡牌、场面、武器、奥秘、任务、卡组资源等），通过多轮布局让对手血量归零。

## Constraints

- **无需完整游戏模拟器** — 项目核心理念是纯分析计算，不依赖 fireplace/Sabberstone 等模拟器
- **决策时间 < 75 秒** — 炉石回合时间限制
- **内存 < 10 MB** — 轻量级运行时
- **Python 实现** — 与现有 V2 引擎一致
- **可解释性** — 评分系统需要人类可理解
- **API 免费额度限制** — HSReplay 非 Premium 数据

## Approach

### HSReplay 单卡数据集成：新增 L6 层

在 V2 模型 (L1-L5) 之上新增 **Real-World Performance Layer (L6)**，利用 HSReplay 的海量实战数据修正理论评分。

**为什么选这个方案**：

- 不修改已验证的 V2 模型 — V2 作为理论基线保持不变
- L6 作为叠加修正层 — 理论评分低的卡如果实战表现好，会被修正上调
- 数据驱动而非猜测 — 用百万级对局的统计结果

**替代方案及拒绝原因**：

- ~~用 HSReplay 数据完全替换 V2 评分~~ → 每个扩展重置，新卡无数据时无法评分
- ~~只用 HSReplay winrate 排序~~ → 无法解释为什么某张卡强，无法泛化到新卡

### 搜索引擎：从 Beam Search 升级到 RHEA

采用 **Rolling Horizon Evolutionary Algorithm (RHEA)** 替代 Top-K Beam Search。

**为什么选 RHEA**：

- 不需要完整游戏模拟器 — 与纯分析理念一致
- Sakurai 2023 论文验证 97.5% 胜率 — 远超 Beam Search 的 72%
- 进化搜索直接优化动作序列 — 能发现非线性最优组合
- 现有 V2+L6 评分直接作为适应度函数 — 零额外开发
- UCB-based 交叉算子能复用历史适应度信息 — 避免重复计算

**替代方案及拒绝原因**：

- ~~MCTS + 完整模拟器~~ → 需要 fireplace/Sabberstone，4.2 games/sec 太慢
- ~~ByteRL (PPO 深度强化学习)~~ → 需要 GPU + 完整模拟器 + 大量训练数据，不透明
- ~~保留 21 参数线性权重~~ → 无校准方法，72% 胜率不够
- ~~XGBoost 叶子评估~~ → 需要大量标注对局数据，目前没有

## Architecture

### 总体架构图

```
┌─────────────────────────────────────────────────────────┐
│                  Game State Reader                       │
│  (HDT Plugin / 日志解析 / 手动输入)                       │
│  输出: 完整 GameState (手牌/场面/奥秘/任务/疲劳/武器)     │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Belief State Generator                      │
│  ┌─────────────────────┐  ┌─────────────────────────┐  │
│  │ Bayesian 对手卡组推断 │  │ 对手手牌概率分布         │  │
│  │ P(deck_i | seen_X)   │  │ P(secret_k | context)   │  │
│  └─────────────────────┘  └─────────────────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│                  RHEA Search Engine                      │
│  种群: 50个动作序列染色体                                 │
│  适应度: CompositeEvaluator (V2 + L6 + A-G)              │
│  时间预算: 75秒或200代                                    │
│  输出: 最优动作序列 + 备选方案                             │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Composite State Evaluator                   │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌───────────┐ │
│  │V2 (L1-L5)│ │L6 HSReplay│ │子模型A-D  │ │对手威胁B  │ │
│  │理论评分   │ │实战修正   │ │场面+触发  │ │威胁消除   │ │
│  └──────────┘ └──────────┘ └───────────┘ └───────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌───────────┐               │
│  │子模型C   │ │子模型E   │ │子模型F+G  │               │
│  │持续效果  │ │环境智能  │ │卡池+选择  │               │
│  └──────────┘ └──────────┘ └───────────┘               │
└────────────────────────┬────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────┐
│                 Decision Presenter                       │
│  推荐动作序列 + EV估计 + 置信度 + 备选方案               │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. HSReplay 数据获取器 (DataFetcher)

**职责**：每日从 HSReplay API 获取单卡统计，缓存到 SQLite

**数据源**：

- HSReplay Cards API: `https://hsreplay.net/api/v1/cards/?game_type=RANKED_STANDARD`
- 已有 API Key: `089b2bc6-3c26-4aab-adbe-bcfd5bb48671`
- 非订阅用户可获取：基础 winrate、play rate、按费用分桶

**获取的数据字段**：

| 字段 | 说明 | 用途 |
|------|------|------|
| `winrate` | 打出该卡的胜率 | L6a 核心指标 |
| `deck_winrate` | 包含该卡的卡组胜率 | L6a 辅助指标 |
| `play_rate` | 使用率 | L6c 环境热度 |
| `keep_rate` | 留牌率 | L6b 费用曲线 |
| `avg_turns` | 平均打出回合 | L6b Tempo |
| `popularity_by_class` | 按职业使用率 | L6c 环境 |

**缓存策略**：

- SQLite 数据库，表结构: `card_stats(dbfId, date, winrate, deck_winrate, play_rate, keep_rate, avg_turns, class_stats_json)`
- 每日刷新，保留 30 天历史
- 降级：API 不可用时使用最近缓存

### 2. L6 实战数据层 (RealWorldLayer)

**职责**：基于 HSReplay 数据计算卡牌实战修正值

#### L6a — Card Power Index (CPI)

```
CPI(card) = α × normalize(played_winrate) 
          + β × normalize(deck_winrate) 
          + γ × normalize(play_rate)

参数: α=0.5, β=0.3, γ=0.2 (初始值, 可通过回归优化)
normalize(x) = (x - min) / (max - min) 映射到 [0, 1]
```

**与 V2 的融合方式**：

```
adjusted_score(card) = V2_score × (1 - θ) + CPI × θ
θ = 0.3  (30% 权重给实战数据，70% 保留理论评分)
```

对于**新卡**（无 HSReplay 数据时）：θ=0，完全依赖 V2 理论评分。

#### L6b — Tempo Efficiency

利用 turn winrate 数据判断卡牌在哪个费用曲线打出最优：

```
tempo_bonus(card) = max(0, turn_winrate[card.turn_played] - avg_turn_winrate[card.cost])
```

如果一张卡在低于平均费用的回合打出胜率更高，说明它是 tempo 卡，给予额外加分。

#### L6c — Meta Context

利用 HSReplay 的 tier list 数据，对当前环境热门职业/卡组的卡牌加权：

```
meta_factor(card) = 1.0 + 0.1 × Σ_deck_usage_rate(card ∈ deck_i)
```

如果一张卡出现在多个热门卡组中，说明它是环境核心卡。

### 3. RHEA 搜索引擎 (RHEAEngine)

**职责**：在合法动作空间中搜索最优动作序列

#### 染色体编码

```
Chromosome = [action_1, action_2, ..., action_n]

action = {
    type: PLAY | ATTACK | HERO_POWER | END_TURN,
    card_index: int,        # 对于 PLAY
    target_index: int,      # 对于 ATTACK
    position: int,          # 场面位置
}

n = 可变长度（一回合内可执行的动作数量）
```

#### 进化参数

| 参数 | 值 | 依据 |
|------|----|------|
| 种群大小 | 50 | RHEA 文献标准 |
| 锦标赛大小 | 5 | 平衡选择压力 |
| 交叉率 | 0.8 | 均匀交叉 |
| 变异率 | 1/N (N=染色体长度) | 每个基因期望变异1次 |
| 最大代数 | 200 | 时间预算限制 |
| 时间限制 | 75秒 | 炉石回合时间 |
| 精英保留 | 2 | 保护最优解 |

#### 适应度函数

```
fitness(chromosome) = V(state_after_execution) - V(state_before)

V(state) = V2_adjusted(state)    # V2 + L6 修正
         + board_advantage(state) # 子模型 A
         - threat_level(state)    # 子模型 B  
         + lingering_EV(state)    # 子模型 C
         + trigger_EV(state)      # 子模型 D
         + meta_factor(state)     # 子模型 E
```

#### UCB 选择算子（来自 Sakurai 2023）

```
UCB(arm) = avg_fitness(arm) + C × sqrt(ln(total_pulls) / arm_pulls)

C = sqrt(2)  (探索常数)
```

UCB 替代传统锦标赛选择，能在探索新动作和利用已知好动作之间平衡。

#### 统计树（Statistical Tree，来自 Sakurai 2023）

复用历史适应度信息，避免重复评估：

- 每个动作节点维护: `{total_evals, avg_fitness, variance}`
- 新一代可复用上一代的统计信息
- 收敛时（方差 < 阈值），跳过评估直接使用缓存值

### 4. 状态评估器 (CompositeEvaluator)

**职责**：对任意游戏状态计算综合评分

融合所有评分层：

```
V(state) = w_v2 × V2_adjusted(board + hand)
         + w_board × board_advantage
         + w_threat × threat_reduction  
         + w_lingering × lingering_EV
         + w_trigger × trigger_EV
         + w_meta × meta_bonus
         + w_tempo × tempo_efficiency
```

**关键区别**：这里 `w_*` 不再是手工标定的 21 个参数，而是**通过 RHEA 进化过程中的自然选择隐式优化**。好的权重组合会使得适应度高的染色体被保留，从而自动校准。

### 5. 贝叶斯对手推断器 (BayesianOpponentModel)

**职责**：基于观察到的对手行为推断对手卡组和策略

保留现有设计但增强：

```
# 先验：HSReplay 每日更新
P(deck_i) = usage_rate_i / Σ usage_rates

# 序贯贝叶斯更新
P(deck_i | X₁,...,Xₙ) ∝ P(deck_i) × Π P(X_k | deck_i)

# 锁定阈值
if max_i P(deck_i) > 0.60: lock to deck_i

# 新增：对手动作推断
P(opponent_action | deck_i, state) 
  = frequency_in_replay_data / total_actions_in_context
```

### 6. 决策展示器 (DecisionPresenter)

**职责**：向用户展示推荐动作及理由

输出内容：

- **推荐动作序列**（按执行顺序）
- **EV 估计**（预期收益值）
- **置信度**（种群中Top-1 vs Top-2的适应度差距）
- **备选方案**（适应度排名第2-3的染色体）
- **关键决策点标注**（"如果对手有AOE则B方案更优"）

## Data Flow

### 完整决策流程

```
1. [离线] DataFetcher 每日拉取 HSReplay 数据 → SQLite 缓存
2. [离线] 计算 L6a CPI / L6b Tempo / L6c Meta → L6 缓存

3. [运行时] GameStateReader 读取当前局面 → GameState
4. [运行时] BeliefStateGenerator:
   a. 从 GameState 提取观察信息
   b. 贝叶斯更新对手卡组概率
   c. 生成对手手牌/奥秘概率分布
   d. 输出: BeliefState = (GameState, P(opponent_decks), P(secrets))

5. [运行时] RHEA Search:
   a. 初始化种群: 50个随机合法动作序列
   b. 循环 (直到时间/代数限制):
      i. 对每个染色体:
         - 在 BeliefState 上模拟执行
         - CompositeEvaluator 计算适应度
         - 处理随机效果 (使用 Tier 1 EV 查表)
      ii. 选择 + 交叉 + 变异 → 新种群
      iii. 精英保留 Top 2
   c. 返回最优染色体

6. [运行时] DecisionPresenter:
   a. 格式化推荐动作序列
   b. 计算置信度 (Top-1 vs Top-2 差距)
   c. 展示给用户
```

## Error Handling

### 数据获取失败

- **HSReplay API 不可用**：降级到最近缓存日数据；如果缓存为空，θ=0，完全依赖 V2 理论评分
- **数据格式变更**：JSON schema 校验 + 版本检测，不匹配时跳过本次更新

### 搜索超时

- **RHEA 超时**：返回当前种群中的最优解（即使未收敛）
- **单次评估超时**：设置单次评估时间上限（200ms），超时返回 V2 基线分数

### 动作枚举错误

- **非法动作**：每个变异/交叉产生的染色体都需要验证合法性，非法基因替换为随机合法动作
- **状态不一致**：动作序列执行前检查前置条件（法力值、目标存在等）

### 对手推断失败

- **无 HSReplay 数据**：使用均匀先验，不做贝叶斯更新
- **锁定错误的卡组**：60% 阈值是保守的，且对手打出不在锁定卡组中的卡时自动解锁

## Testing Strategy

### 单元测试

- **L6 层**：对比已知环境（如 "深暗领域" 版本）的热门卡和冷门卡，验证 CPI 排序合理性
- **RHEA 搜索**：构造简单局面（如 1 个动作明显最优），验证搜索能在 10 代内找到最优解
- **贝叶斯推断**：模拟对手打出一系列卡，验证推断收敛到正确卡组

### 集成测试

- **端到端决策**：输入经典对局局面（如"对手 12 血，我方手上有火球术 + 冰霜法师"），验证决策合理性
- **V2 + L6 一致性**：理论高分卡 + 实战高分卡应排名靠前

### 回归测试

- **V2 基线不退化**：L6 修正后，排名前 20 的卡不应与 V2 排名差异超过 10 位（除非有实战数据强支撑）
- **RHEA vs Beam Search**：在相同局面下，RHEA 的决策质量应不低于 Beam Search

### 性能测试

- **决策时间**：95% 的决策应在 30 秒内完成（预留 75 秒上限）
- **内存**：运行时峰值 < 10 MB

## Open Questions

1. **HSReplay API 免费额度具体限制**：需要实际测试每日请求限制
2. **L6 θ 参数最优值**：0.3 是初始猜测，需要通过对局数据回归
3. **RHEA 种群大小 vs 决策时间**：50 是文献默认值，炉石动作空间可能需要更大种群
4. **新扩展发布时的冷启动**：新卡无 HSReplay 数据，需要等待数据积累
5. **RHEA 在隐藏信息博弈中的具体表现**：Sakurai 论文是全信息设定，炉石是不完全信息
6. **对手动作推断数据来源**：需要 HSReplay Premium 才能获取"对手打出某卡的概率"数据

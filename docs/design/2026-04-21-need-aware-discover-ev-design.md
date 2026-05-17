# Need-Aware Discover EV — 设计文档

> 日期: 2026-04-21
> 状态: 设计完成，待实现
> 依赖: V11 FactorGraph, MechanicRegistry, TacticalPlanner

## 1. Problem Statement

当前发现(discover)机制的决策质量不足：

1. **DiscoverModel 用静态 SIV 评分选牌** — 不区分"我现在需要回血 vs 解场 vs 铺场"
2. **发现牌不在搜索空间内** — TacticalPlanner 枚举出牌组合时，发现牌被打出后随机选一张就完事
3. **无法比较"打发现牌 vs 打其他牌"的期望值** — 缺少发现 EV 与其他行动的对比
4. **无可解释输出** — 用户看不到"发现期望得到什么类型的牌"

## 2. Constraints

- 发现有时间限制：标准池 187 张法术，每张模拟打出 → 187 次 FactorGraph 评估
- 不能超过 100ms 总时间预算（与 V11 pipeline 共享）
- 不能修改 V10 代码（engine_v11/ 独立原则）
- 发现可能嵌套（发现一张牌，那张牌也有发现效果）→ 限制嵌套深度为 1 层

## 3. Approach

### 选定方案：Need-Aware Discover EV

对发现池中的每张牌，**完整模拟打出后用 FactorGraph 评估**，计算 3 选 1 的期望最大值。

### 排斥的替代方案

| 方案 | 排斥理由 |
|------|---------|
| 静态 SIV 选最高分 | 不感知场面需求，可能选到无用高费牌 |
| 纯分类权重（heal=0.8, removal=0.6...） | 分类不精确，同一类牌价值差异大 |
| MCTS 模拟多回合 | 时间预算不够，且不确定性太大 |
| 深度 RL 学习发现策略 | 无训练数据，无模拟器 |

### 核心洞察

发现牌是一个**嵌套决策**：打出发现牌后，3 选 1 的最优选择取决于场面状态。因此发现牌的 EV 不是"池中最强牌的分数"，而是"3 选 1 期望最优牌打出后的场面变化"。

## 4. Architecture

```
DiscoverModelV2
├── NeedAnalyzer           分析场面需求（生存/解场/节奏/直伤/资源）
├── PoolSimulator          对池中每张牌模拟打出 + FactorGraph 评估
├── OrderStatistics        计算 3 选 1 期望最大值（精确 or MC）
├── CardClassifier         牌面分类（回血/解场/铺场/直伤/过牌）
└── DiscoverEVResult       输出 EV + TOP 选项 + 需求分布

TacticalPlanner (扩展)
├── 原有 BFS 枚举出牌组合
└── 发现牌扩展: 打出发现牌 → DiscoverModelV2.compute_ev() → EV 参与 combo 比较
```

## 5. Components

### 5.1 NeedAnalyzer (`models/need_analyzer.py`)

```python
@dataclass
class NeedProfile:
    survival: float    # 0-1, 血量低/对手威胁大时高
    removal: float     # 0-1, 对手场面威胁时高
    tempo: float       # 0-1, 场面均势/可以铺场时高
    damage: float      # 0-1, 对手血量低时高
    draw: float        # 0-1, 手牌少/牌库厚时高

class NeedAnalyzer:
    def analyze(self, state: GameState) -> NeedProfile
```

需求权重计算规则：
- **survival**: `enemy_damage_bound / hero_eff_hp`, capped at 1.0
- **removal**: `sum(enemy.attack * health) / scale`, 基于 enemy board 的威胁总量
- **tempo**: `1 - board_saturation`, 场面空位越多越高
- **damage**: `max_damage_bound / opp_hp`, 斩杀线越近越高
- **draw**: `hand_count < 3 ? 0.8 : 0.2`, 手牌少时高

### 5.2 PoolSimulator (`models/pool_simulator.py`)

```python
class PoolSimulator:
    def simulate_card(self, card, state, evaluator) -> float:
        """模拟发现这张牌后打出的最优场景"""
        sim = state.copy()
        sim.hand.append(card)
        # 模拟打出这张牌（如果有法力）
        if card.cost <= sim.mana.available:
            action = Action(action_type="PLAY", card_index=len(sim.hand)-1)
            sim = apply_action(sim, action)
        # FactorGraph 评估场面变化
        ctx = EvalContext.from_state(state)
        scores = evaluator.evaluate(state, sim, context=ctx)
        return scores.total
```

### 5.3 OrderStatistics (`models/order_statistics.py`)

```python
class OrderStatistics:
    def expected_max_of_k(self, sorted_scores: list, k: int = 3) -> float:
        """计算 3 选 1 的期望最大值"""
        n = len(sorted_scores)
        if n <= k:
            return max(sorted_scores)
        # 池大(>50): Monte Carlo 200 次
        # 池小(≤50): 精确组合数计算
        # E[max] = Σ x_i * P(x_i is the max of k picks)
        # P(x_i is max) = C(i, k-1) / C(n, k) where i = rank-1
```

### 5.4 CardClassifier (`models/card_classifier.py`)

```python
class CardClassifier:
    def classify(self, card) -> str:
        """返回 "heal" / "removal" / "tempo" / "damage" / "draw" / "utility"
        基于卡牌效果文本的 regex 分类"""
```

### 5.5 DiscoverModelV2 (`models/discover_model_v2.py`)

主入口，整合以上组件：

```python
@dataclass
class DiscoverEVResult:
    expected_value: float
    top_options: List[Tuple[Card, float, str]]  # (card, score, category)
    need_distribution: NeedProfile
    pool_size: int
    time_elapsed_ms: float

class DiscoverModelV2:
    def compute_ev(self, pool, state, evaluator) -> DiscoverEVResult
```

### 5.6 TacticalPlanner 扩展

在 `_enumerate_card_combos` 中，当打出发现牌时：
1. 获取发现池
2. 用 DiscoverModelV2 计算发现 EV
3. 将 EV 作为该 combo 的附加分数
4. 发现牌不再"随机选一张"，而是用 EV 代表期望场面收益

## 6. Data Flow

```
GameState
  │
  ├─ NeedAnalyzer.analyze(state) → NeedProfile
  │
  ├─ CardIndex.discover_pool(constraint) → pool (e.g., 187 cards)
  │
  ├─ PoolSimulator.simulate_card(card, state, evaluator) → score  (× pool_size)
  │   ├─ state.copy()
  │   ├─ sim.hand.append(card)
  │   ├─ apply_action(sim, play_action)
  │   └─ FactorGraph.evaluate(state_before, sim) → score
  │
  ├─ OrderStatistics.expected_max_of_k(scores, k=3) → EV
  │
  ├─ CardClassifier.classify(top_cards) → categories
  │
  └─ DiscoverEVResult(EV, top_options, needs, pool_size)
```

## 7. Error Handling

- 池为空 → EV = 0.0, 返回空结果
- 单张模拟超时（>2ms）→ 降级到 SIV 静态评分
- FactorGraph 评估异常 → 降级到 (attack+health)*0.5 + cost*0.3
- 池过大(>300) → 截取 TOP 200（按 mana cost 排序去极端值）

## 8. Testing Strategy

| 批次 | 测试数 | 覆盖场景 |
|------|-------|---------|
| Batch 1 | 8 | NeedAnalyzer: 各种场面状态的需求判定 |
| Batch 2 | 6 | PoolSimulator: 单牌模拟 + FactorGraph 评分 |
| Batch 3 | 5 | OrderStatistics: 精确计算 vs MC 近似 vs 边界 |
| Batch 4 | 4 | CardClassifier: 5 种分类 + 混合效果牌 |
| Batch 5 | 8 | DiscoverModelV2: 完整流程 + 池为空/单张/大量 |
| Batch 6 | 6 | TacticalPlanner 集成: 发现牌 vs 非发现牌 combo 对比 |

## 9. Open Questions

1. **性能**：187 次 FactorGraph 评估约需 50-100ms，可能超出 pipeline 预算。需要缓存池评分或限制池大小。
2. **RNG 牌处理**：池中有效果随机的牌（如"对一个随机随从造成 2-4 伤害"），当前用期望值（RNGModel）。
3. **嵌套发现**：发现一张牌后打出，那张牌也有发现 → 限制嵌套深度为 1 层。
4. **输出粒度**：默认输出 TOP 5 选项 + 需求分布，可配置。

# Next-Gen Decision Engine Architecture (V11)

> Date: 2026-04-21
> Status: DRAFT
> Author: analysis
> Supersedes: V10 RHEA flat search + BSV evaluation

---

## 1. Problem Statement

V10 引擎的根本架构缺陷：

1. **评估函数**：BSV 是"全局分数差"，无法区分单个行动的边际价值（"攻击A好还是攻击B好"）
2. **搜索算法**：RHEA 是随机进化搜索，75ms 内采样不足，复杂场面漏最优解
3. **信息不完全**：抽牌是占位符，发现是贪心选最贵，RNG 效果无建模
4. **机制硬编码**：每个新机制需要在 apply_action 里加 if/elif，维护成本 O(n²)
5. **跨回合缺失**：chromosome 长度 4-8 只覆盖当回合，无法做"留资源"决策

目标：设计一个**可扩展、模块化、决策质量显著提升**的新引擎架构，使：
- 攻击能确定性选择最优目标
- 发现/抽牌用概率模型给最优策略
- 复杂场面（7v7）能在 100ms 内给出合理决策
- 新增机制只需实现一个 Handler 类，零改动核心引擎

---

## 2. Constraints

| 约束 | 说明 |
|------|------|
| **向后兼容** | GameState 数据结构不变（Minion, HeroState 等 dataclass 保留） |
| **性能** | 单回合决策 < 100ms（当前 75ms 基准） |
| **无训练依赖** | V11 核心不依赖神经网络/训练数据，纯规则 + 搜索 |
| **渐进迁移** | 可与 V10 并行运行，A/B 对比验证后再切换 |
| **Python 3.11+** | 不引入新语言依赖 |

---

## 3. Approach: Five Pillars

基于 Hearthstone AI 竞赛（IEEE CoG 2018-2022）的实证研究：

- **ISMCTS** 在不完全信息卡牌游戏中表现优于 RHEA（Choe & Kim 2019 冠军）
- **分层分解** 是处理组合行动空间的关键（Santos et al. 2017）
- **因子化评估** 提供可解释、可独立调优的评分（Miernik & Kowalski 2021）
- **行动剪枝** 是在有限时间内覆盖搜索空间的必要手段

选定方案由 **5 个核心子系统** 组成：

```
┌─────────────────────────────────────────────────────┐
│                    DecisionPipeline                  │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Action   │→│ Action   │→│ Hierarchical      │  │
│  │ Generator│  │ Pruner   │  │ Search (分层搜索)  │  │
│  └──────────┘  └──────────┘  └───────┬───────────┘  │
│                                      │               │
│  ┌───────────────────────────────────▼───────────┐  │
│  │          Factor Graph Evaluator (因子评估)      │  │
│  │  board_control · lethal_threat · tempo · value │  │
│  │  · survival · resource_efficiency · discover   │  │
│  └───────────────────────────────────┬───────────┘  │
│                                      │               │
│  ┌───────────────────────────────────▼───────────┐  │
│  │       Mechanic Registry (机制注册表)            │  │
│  │  register("battlecry", BattlecryHandler)       │  │
│  │  register("deathrattle", DeathrattleHandler)   │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

排斥的替代方案：
- **AlphaGo-style MCTS+NN**：需要大量训练数据 + 游戏模拟器，本项目不具备
- **ByteRL-style deep RL**：需要百万局自博弈，训练周期不可接受
- **纯 Minimax + α-β**：无法处理不完全信息（对手手牌/奥秘）

---

## 4. Architecture: Five Pillars in Detail

### 4.1 Pillar 1: MechanicRegistry（机制注册表）

**问题**：当前 apply_action 有 ~200 行 if/elif 处理各种机制，新增机制成本 O(n)。

**方案**：注册表模式 + Handler 接口

```python
# hs_analysis/search/mechanics/registry.py

class MechanicHandler(ABC):
    """每个机制的处理器接口"""

    @abstractmethod
    def trigger_point(self) -> str:
        """触发时机: 'on_play', 'on_attack', 'on_death', 'on_turn_end', ..."""

    @abstractmethod
    def apply(self, state: GameState, context: ActionContext) -> GameState:
        """执行机制效果"""

    @abstractmethod
    def evaluate(self, state_before: GameState, state_after: GameState) -> float:
        """评估此机制的价值贡献"""

class MechanicRegistry:
    _handlers: Dict[str, List[MechanicHandler]] = defaultdict(list)

    def register(self, keyword: str, handler: MechanicHandler):
        self._handlers[keyword].append(handler)

    def dispatch(self, trigger: str, state: GameState, context: ActionContext) -> GameState:
        for keyword in context.keywords:
            for handler in self._handlers.get(keyword, []):
                if handler.trigger_point() == trigger:
                    state = handler.apply(state, context)
        return state
```

**注册示例**：
```python
registry = MechanicRegistry()
registry.register("battlecry", BattlecryHandler())
registry.register("deathrattle", DeathrattleHandler())
registry.register("discover", DiscoverHandler())
registry.register("colossal", ColossalHandler())
registry.register("outcast", OutcastHandler())
# 未来新增机制：
registry.register("invoke", InvokeHandler())        # 只需一个类
registry.register("spellburst", SpellburstHandler()) # 只需一个类
```

**apply_action 简化为**：
```python
def apply_action(state, action):
    # ... 通用逻辑（费用、位置、死亡） ...
    card = state.hand[action.card_index]
    context = ActionContext(card=card, action=action, state=state)

    state = registry.dispatch("on_play", state, context)
    state = registry.dispatch("on_attack", state, context) if action.action_type == "ATTACK" else state
    state = resolve_deaths(state)
    state = registry.dispatch("on_death", state, context)
    state = aura_engine.recompute(state)
    return state
```

**迁移路径**：V10 的每个机制文件（battlecry_dispatcher.py, deathrattle.py, colossal.py 等）包装为 Handler，零逻辑重写。

---

### 4.2 Pillar 2: FactorGraph Evaluator（因子图评估）

**问题**：BSV 是单一标量评分，无法解释"为什么这个行动比那个好"。

**方案**：因子化评估，每个因子独立计算，加权融合。

```python
@dataclass
class FactorScores:
    board_control: float     # 场面控制力
    lethal_threat: float     # 致命威胁
    tempo: float             # 节奏优势
    value: float             # 价值（手牌+场面总资源）
    survival: float          # 生存安全
    resource_efficiency: float  # 法力利用效率
    discover_ev: float       # 发现期望价值
    total: float             # 加权总分

class EvaluationFactor(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def compute(self, state_before: GameState, state_after: GameState,
                action: Action, context: EvalContext) -> float:
        """返回 [-1, 1] 范围的因子分数"""
        ...

class FactorGraphEvaluator:
    _factors: List[EvaluationFactor] = []
    _weights: Dict[str, float] = {}  # phase-adaptive weights

    def register(self, factor: EvaluationFactor):
        self._factors.append(factor)

    def evaluate(self, state_before, state_after, action, context) -> FactorScores:
        scores = {}
        for f in self._factors:
            scores[f.name()] = f.compute(state_before, state_after, action, context)
        weights = self._phase_weights(context.phase)
        scores["total"] = sum(scores[f.name()] * weights.get(f.name(), 1.0)
                             for f in self._factors)
        return FactorScores(**scores)
```

**因子设计**：

| 因子 | 计算方法 | 说明 |
|------|---------|------|
| `board_control` | (我方随从总攻击力 - 敌方) / max(总, 1) | 场面谁强 |
| `lethal_threat` | max_damage_bound / enemy_hp（0或1） | 本回合/下回合能否斩杀 |
| `tempo` | (我方场面总费 - 敌方) / max_turn_cost | 节奏优势 |
| `value` | (我方手牌数 + 场面随从数) - (敌方同) | 资源数量 |
| `survival` | (hero_hp + armor) / 30 | 存活概率 |
| `resource_efficiency` | mana_spent / max_mana | 法力利用 |
| `discover_ev` | SIV评分最高的池牌分数 | 发现期望值 |

**阶段自适应权重**：

```python
PHASE_WEIGHTS = {
    "early": {"tempo": 1.5, "value": 0.5, "survival": 0.5, "board_control": 1.0, ...},
    "mid":   {"tempo": 1.0, "value": 1.0, "survival": 1.0, "board_control": 1.2, ...},
    "late":  {"tempo": 0.8, "value": 0.7, "survival": 1.5, "board_control": 1.0, ...},
}
```

**关键改进**：每个因子可独立测试、调优、替换，不影响其他因子。

---

### 4.3 Pillar 3: Hierarchical Search（分层搜索）

**问题**：RHEA 的 flat 进化在复杂场面搜索空间覆盖不足。

**方案**：3 层决策架构，每层用最适合的算法。

```
Layer 0: 战略判定 (Strategic Decision) — O(1)
  ├─ 致命可能？ → LethalSearch (DFS, 确定性)
  ├─ 致命威胁？ → DefensiveSearch (生存优先)
  └─ 发展期？   → DevelopmentSearch (最优资源利用)

Layer 1: 战术规划 (Tactical Planning) — O(n²)
  ├─ 枚举手牌组合（法力内）
  ├─ 对每个组合：模拟出牌 → 确定性攻击规划 → 评估
  ├─ 剪枝：dominance pruning（组合A ≥ B 则丢弃B）
  └─ 返回 top-K 候选

Layer 2: 执行优化 (Execution Optimization) — O(n!)
  ├─ 攻击序列：贪心 + 1-step lookahead
  │   └─ 对每个可攻击随从：尝试所有目标，选最优因子分
  ├─ 法术/战吼目标：枚举 + 评估
  └─ 出牌顺序：按依赖排序（需要目标在前，buff 在后）
```

**Layer 0 伪代码**：
```python
def strategic_decision(state: GameState) -> str:
    if check_lethal(state):
        return "LETHAL"
    enemy_damage = max_damage_bound_enemy(state)
    if enemy_damage >= state.hero.hp + state.hero.armor:
        return "DEFENSIVE"
    return "DEVELOPMENT"
```

**Layer 1 核心改进 — 确定性攻击规划**（替代 RHEA 随机搜索）：

```python
class AttackPlanner:
    """确定性攻击序列规划器"""

    def plan(self, state: GameState) -> List[AttackAction]:
        attacks = []
        attackers = [m for m in state.board if m.can_attack and not m.frozen_until_next_turn]
        targets = self._get_valid_targets(state)

        # 贪心 + 1-step lookahead
        for attacker in sorted(attackers, key=lambda m: -m.attack):  # 大怪优先
            best_target = None
            best_score = -float('inf')
            for target in targets:
                sim_state = simulate_attack(state, attacker, target)
                score = self._quick_eval(sim_state)
                if score > best_score:
                    best_score = score
                    best_target = target
            if best_target:
                attacks.append(AttackAction(attacker, best_target))
                state = simulate_attack(state, attacker, best_target)  # cascade
                targets = self._get_valid_targets(state)  # refresh after death

        return attacks

    def _quick_eval(self, state: GameState) -> float:
        """轻量评估：只用 board_control + tempo 两个因子"""
        bc = self._board_control(state)
        tempo = self._tempo_score(state)
        return 0.6 * bc + 0.4 * tempo
```

**Layer 2 组合枚举**：

```python
def enumerate_card_combos(hand, available_mana, max_depth=4) -> List[List[int]]:
    """枚举法力内的手牌组合，用 BFS + 剪枝"""
    combos = []
    queue = [([], 0, 0)]  # (card_indices, total_cost, depth)

    while queue:
        indices, cost, depth = queue.pop(0)
        if depth > 0:
            combos.append(indices)
        if depth >= max_depth:
            continue
        for i, card in enumerate(hand):
            if i in indices:
                continue
            new_cost = cost + card.cost
            if new_cost <= available_mana:
                queue.append((indices + [i], new_cost, depth + 1))

    return combos
```

**对比 RHEA**：

| 维度 | RHEA (V10) | Hierarchical Search (V11) |
|------|-----------|--------------------------|
| 攻击目标选择 | 随机进化碰对 | 确定性贪心 + 评估 |
| 出牌序列 | 随机 chromosome | 枚举组合 + 剪枝 |
| 复杂场面 | 采样不足，漏解 | 分层降维，确定性覆盖 |
| 时间控制 | 整体时间预算 | 每层独立预算，可超时截断 |
| 可解释性 | 黑盒进化 | 每层决策可解释 |

---

### 4.4 Pillar 4: Probability Models（概率模型）

**问题**：抽牌/发现/RNG 没有概率建模。

#### 4.4.1 DrawModel（抽牌模型）

```python
class DrawModel:
    """基于 deck_list 的抽牌期望价值模型"""

    def expected_draw_value(self, state: GameState, n_cards: int = 1) -> float:
        if not state.deck_list or len(state.deck_list) == 0:
            return 0.0

        remaining = [c for c in state.deck_list if c not in state._drawn_cards]
        if not remaining:
            return -1.0  # 疲劳惩罚

        total_score = sum(siv_score(c, state) for c in remaining)
        avg_value = total_score / len(remaining)

        # 抽多张：考虑手牌上限
        effective_cards = min(n_cards, 10 - len(state.hand))
        return effective_cards * avg_value

    def draw_variance(self, state: GameState) -> float:
        """抽牌方差 — 高方差意味着不稳定，需要保守策略"""
        if not state.deck_list:
            return 0.0
        scores = [siv_score(c, state) for c in state.deck_list]
        return statistics.variance(scores) if len(scores) > 1 else 0.0
```

#### 4.4.2 DiscoverModel（发现模型）

```python
class DiscoverModel:
    """发现的最优选择模型"""

    def best_discover(self, pool: List[Card], state: GameState) -> Tuple[Card, float]:
        """用 SIV 评分评估发现池中所有卡牌，返回最优及其期望值"""
        scored = [(card, siv_score(card, state)) for card in pool]
        scored.sort(key=lambda x: -x[1])

        # 3 选 1 的期望：最优牌被选中的概率
        # 简化：假设随机 3 张，取最优的期望
        if len(scored) <= 3:
            return scored[0]

        # 蒙特卡洛模拟 3 选 1
        n_sims = 50
        best_picks = []
        for _ in range(n_sims):
            sample = random.sample(scored, min(3, len(scored)))
            best_picks.append(max(sample, key=lambda x: x[1]))
        avg_best = sum(p[1] for p in best_picks) / len(best_picks)
        top_card = max(best_picks, key=lambda x: x[1])[0]

        return top_card, avg_best

    def discover_ev(self, pool: List[Card], state: GameState) -> float:
        """发现期望价值 — 用于评估含发现的卡牌"""
        _, ev = self.best_discover(pool, state)
        return ev
```

#### 4.4.3 RNGModel（随机效果模型）

```python
class RNGModel:
    """随机效果的期望值模型"""

    def expected_value(self, effect: str, state: GameState,
                       n_samples: int = 8) -> float:
        """蒙特卡洛采样随机效果期望值"""
        results = []
        for _ in range(n_samples):
            outcome = self._resolve_random(effect, state)
            results.append(quick_eval(outcome))
        return sum(results) / len(results)

    def _resolve_random(self, effect: str, state: GameState) -> GameState:
        """解析随机效果字符串，模拟一个随机结果"""
        # "damage:random_enemy:2-4" → 随机选敌人，伤害 2-4
        # "summon:random:3-5:3-5" → 随机 3-5/3-5 随从
        # etc.
        ...
```

---

### 4.5 Pillar 5: ActionPruner（行动剪枝器）

**问题**：7 随从场面 × 多攻击目标 = 巨大搜索空间，100ms 内搜索不完。

**方案**：在搜索前用领域知识剪掉明显劣质行动。

```python
class ActionPruner:
    """领域知识驱动的行动剪枝"""

    def prune(self, actions: List[Action], state: GameState) -> List[Action]:
        pruned = []
        for a in actions:
            if self._is_dominated(a, state):
                continue
            pruned.append(a)
        return pruned

    def _is_dominated(self, action: Action, state: GameState) -> bool:
        """检查行动是否被其他行动严格支配"""
        if action.action_type == "ATTACK":
            return self._attack_dominated(action, state)
        if action.action_type == "PLAY":
            return self._play_dominated(action, state)
        return False

    def _attack_dominated(self, action: Action, state: GameState) -> bool:
        attacker = state.board[action.source_index]
        target = self._get_target(action, state)

        # 1攻击力随从打圣盾 = 浪费（除非是唯一选择）
        if target.has_divine_shield and attacker.attack == 1:
            return True

        # 攻击不会死的随从且自己会死 = 坏交易
        if (target.health > attacker.attack and
            attacker.health <= target.attack and
            not attacker.has_divine_shield):
            return True

        # 冲锋随从打脸 vs 有更好目标（非致命场景）
        if action.target_index == 0 and attacker.has_rush:
            return True  # rush 不能打脸

        return False

    def _play_dominated(self, action: Action, state: GameState) -> bool:
        card = state.hand[action.card_index]

        # 满手牌（10张）时不打出牌（除非有即时收益）
        if len(state.hand) == 10 and card.card_type == "MINION":
            if state.board and len(state.board) >= 7:
                return True  # 场面满，手牌满，出怪直接烧

        return False
```

**剪枝效果估计**：

| 场景 | 剪枝前行动数 | 剪枝后 | 降幅 |
|------|-------------|--------|------|
| 7 随从场面，多目标 | ~50 | ~15 | 70% |
| 5 手牌，7 法力 | ~20 | ~8 | 60% |
| 简单场面（2 随从） | ~10 | ~7 | 30% |

---

## 5. Complete Decision Pipeline

```
输入: GameState (from StateBridge / test fixture)
  │
  ├─ 1. 战略判定 (O(1))
  │    ├─ check_lethal() → LETHAL 模式
  │    ├─ enemy_lethal_threat() → DEFENSIVE 模式
  │    └─ → DEVELOPMENT 模式
  │
  ├─ 2. 行动生成 + 剪枝
  │    ├─ enumerate_legal_actions() → ~50 actions
  │    └─ ActionPruner.prune() → ~15 actions
  │
  ├─ 3. 分层搜索
  │    │
  │    ├─ LETHAL 模式:
  │    │   └─ DFS lethal checker (不变，已验证)
  │    │
  │    ├─ DEFENSIVE 模式:
  │    │   ├─ 枚举防御性出牌（嘲讽、回血、冰冻、清场）
  │    │   └─ 评估 survival 因子最高者
  │    │
  │    └─ DEVELOPMENT 模式:
  │        ├─ 3a. 枚举手牌组合 (法力内, BFS)
  │        │   ├─ 对每个组合: simulate_play → FactorGraph.evaluate()
  │        │   ├─ dominance pruning
  │        │   └─ top-K 候选 (~5)
  │        │
  │        ├─ 3b. 确定性攻击规划 (每个候选)
  │        │   ├─ AttackPlanner.plan() → 贪心最优攻击序列
  │        │   └─ 每步: 枚举目标 → FactorGraph.evaluate() → 选最优
  │        │
  │        └─ 3c. 因子图评估
  │            ├─ board_control, tempo, value, survival, resource_efficiency
  │            ├─ 概率模型: DrawModel (抽牌), DiscoverModel (发现), RNGModel (随机)
  │            └─ 阶段自适应权重 → 加权总分
  │
  ├─ 4. 对手模拟 (top-3 候选)
  │    └─ OpponentSimulator → 风险惩罚
  │
  └─ 5. 输出: Decision
       ├─ best_plan: List[Action]  (最优行动序列)
       ├─ factor_scores: FactorScores  (因子分解，可解释)
       ├─ alternatives: List[Decision]  (top-3 备选)
       ├─ confidence: float  (最优 vs 次优分差)
       └─ reasoning: str  ("选择此方案因为: board_control +0.3, tempo +0.2")
```

---

## 6. Data Flow: 新增 vs 现有

```
现有 (V10):
  GameState → enumerate → RHEA evolve → BSV score → SearchResult

新增 (V11):
  GameState → enumerate → prune → strategic_layer
                                    ├─ LETHAL → DFS (existing)
                                    ├─ DEFENSIVE → survival_factor
                                    └─ DEVELOPMENT → combo_enum + AttackPlanner
                                                      → FactorGraph(7 factors)
                                                      → DrawModel / DiscoverModel / RNGModel
                                                      → OpponentSim
                                                      → DecisionResult(factors + reasoning)
```

**迁移路径**：V11 Pipeline 可与 V10 RHEA 并行运行，用因子分 vs BSV 分对比验证。

---

## 7. File Structure

```
hs_analysis/search/
├── engine_v11/                    # 新引擎目录（与现有代码并行）
│   ├── __init__.py
│   ├── pipeline.py                # DecisionPipeline 主入口
│   ├── strategic.py               # Layer 0: 战略判定
│   ├── tactical.py                # Layer 1: 战术规划（组合枚举）
│   ├── attack_planner.py          # Layer 2: 确定性攻击规划
│   ├── action_pruner.py           # 行动剪枝器
│   ├── factors/                   # 因子图评估器
│   │   ├── __init__.py
│   │   ├── factor_base.py         # EvaluationFactor ABC
│   │   ├── factor_graph.py        # FactorGraphEvaluator
│   │   ├── board_control.py       # 场面控制因子
│   │   ├── lethal_threat.py       # 致命威胁因子
│   │   ├── tempo.py               # 节奏因子
│   │   ├── value.py               # 价值因子
│   │   ├── survival.py            # 生存因子
│   │   ├── resource_efficiency.py # 法力效率因子
│   │   └── discover_ev.py         # 发现期望值因子
│   ├── models/                    # 概率模型
│   │   ├── __init__.py
│   │   ├── draw_model.py          # 抽牌期望
│   │   ├── discover_model.py      # 发现最优选择
│   │   └── rng_model.py           # 随机效果期望
│   └── mechanics/                 # 机制注册表
│       ├── __init__.py
│       ├── registry.py            # MechanicRegistry
│       ├── handler_base.py        # MechanicHandler ABC
│       ├── battlecry_handler.py   # 战吼（包装现有 battlecry_dispatcher）
│       ├── deathrattle_handler.py # 亡语（包装现有 deathrattle）
│       ├── discover_handler.py    # 发现（包装现有 discover）
│       ├── colossal_handler.py    # 巨型
│       ├── outcast_handler.py     # 流放
│       ├── kindred_handler.py     # 延系
│       └── ...                    # 未来机制只加文件
│
├── rhea_engine.py                 # V10 保留，不修改
├── game_state.py                  # 共用，不修改
├── lethal_checker.py              # 共用，不修改
└── ...                            # 其他 V10 文件保留
```

**关键原则**：`engine_v11/` 是独立目录，不修改任何 V10 文件。两个引擎可以并行运行、A/B 对比。

---

## 8. Implementation Plan

### Phase 1: Foundation (6-8h)

| Task | Files | Hours |
|------|-------|-------|
| MechanicRegistry + Handler ABC | `mechanics/registry.py`, `handler_base.py` | 2 |
| 包装现有 battlecry/deathrattle/discover 为 Handler | `mechanics/*_handler.py` | 2 |
| FactorGraphEvaluator + Factor ABC | `factors/factor_base.py`, `factor_graph.py` | 2 |
| BoardControl + Tempo + Survival 因子 | `factors/board_control.py`, `tempo.py`, `survival.py` | 2 |

### Phase 2: Search (6-8h)

| Task | Files | Hours |
|------|-------|-------|
| ActionPruner | `action_pruner.py` | 2 |
| AttackPlanner（确定性攻击） | `attack_planner.py` | 3 |
| Strategic layer (L0) | `strategic.py` | 1 |
| Tactical layer (L1) — 组合枚举 | `tactical.py` | 2 |

### Phase 3: Probability Models (4-6h)

| Task | Files | Hours |
|------|-------|-------|
| DrawModel | `models/draw_model.py` | 2 |
| DiscoverModel | `models/discover_model.py` | 2 |
| RNGModel | `models/rng_model.py` | 1 |

### Phase 4: Pipeline + Validation (4-6h)

| Task | Files | Hours |
|------|-------|-------|
| DecisionPipeline 主入口 | `pipeline.py` | 2 |
| A/B 对比测试（V10 vs V11） | `test_v11_ab_comparison.py` | 2 |
| V10 batch tests 用 V11 重跑 | `test_v11_regression.py` | 2 |

**Total: 20-28 hours**

---

## 9. Expected Improvements

| 场景 | V10 (RHEA) | V11 (Hierarchical) | 改进 |
|------|-----------|-------------------|------|
| 攻击最优目标 | 随机搜索，~60% 命中最优 | 确定性枚举，~95% | **+35%** |
| 发现选最优 | 贪心选最贵 | SIV 评分选最优 | **质变** |
| 抽牌评估 | 占位符 = 0 | deck_list 期望值 | **质变** |
| 7v7 复杂场面 | 采样不足 | 分层剪枝 + 确定性 | **+50%** |
| 新增机制成本 | 改 apply_action 200行 | 加一个 Handler 文件 | **-80% 代码** |
| 可解释性 | "fitness = 3.7" | "因为 board_control +0.3, tempo +0.2" | **质变** |

---

## 10. Open Questions

1. **deck_list 来源**：抽牌模型需要知道牌库内容。竞技场模式下需要追踪已选牌；天梯模式下需要假设标准池。HDT 日志是否暴露牌库列表？
2. **对手手牌建模**：当前 OpponentSimulator 只看场面。如果结合 HDT 的 opponent hand_count + 已玩卡牌推断，可以做简单的对手手牌概率模型。
3. **因子权重调优**：阶段自适应权重目前是手工设定。长期可用进化算法（遗传算法优化权重）或从 HSReplay 数据学习。
4. **MCTS 升级路径**：V11 的分层搜索是确定性 + 贪心的。如果未来需要更强搜索，可以在 Layer 1 替换为 ISMCTS，因子图作为 rollout 评估函数。这是预留的升级路径。
5. **缓存策略**：FactorGraph 评估可能被多次调用（每个候选 × 每步攻击）。需要设计增量评估缓存。

---

## 11. Research References

1. **Choe & Kim (2019)** — ISMCTS + sparse sampling, Hearthstone AI Competition winner. IEEE CoG.
2. **Santos et al. (2017)** — Hierarchical action decomposition for card games.
3. **Miernik & Kowalski (2021)** — Evolved evaluation functions for LOCM competition.
4. **Bitan & Kraus (2017)** — SDMCTS (Semi-Determinized MCTS), arxiv 1709.09451.
5. **Swiechowski et al. (2018)** — MCTS + supervised learning for Hearthstone, arxiv 1808.04794.
6. **ByteRL (2022)** — Deep RL agent, 84.41% win rate vs top-10 human, arxiv 2305.11814.
7. **Zhang & Buro (2017)** — Card-play policy networks for Legends of Code and Magic.

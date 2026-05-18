# MCTS/UCT 炉石传说搜索引擎 — 详细开发文档

> 版本: v1.0-draft
> 日期: 2026-04-24
> 基于项目: hs_analysis
> 前置文档: `总结报告.md`, `相关资料整理/`

---

## 目录

1. [系统架构总览](#一系统架构总览)
2. [数据结构设计](#二数据结构设计)
3. [UCT 选择策略](#三uct-选择策略)
4. [展开策略](#四展开策略)
5. [模拟/评估策略](#五模拟评估策略)
6. [反向传播](#六反向传播)
7. [确定化采样 (DUCT)](#七确定化采样-duct)
8. [动作剪枝](#八动作剪枝)
9. [转置表](#九转置表)
10. [时间预算管理](#十时间预算管理)
11. [管线集成](#十一管线集成)
12. [参数配置](#十二参数配置)
13. [文件结构](#十三文件结构)
14. [接口规范](#十四接口规范)
15. [测试方案](#十五测试方案)
16. [性能优化](#十六性能优化)
17. [开发路线图](#十七开发路线图)
18. [附录](#十八附录)

---

## 一、系统架构总览

### 1.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    DecisionLoop (watcher/)                   │
│                  Power.log → parse → decide → output         │
└──────────────────────┬──────────────────────────────────────┘
                       │ GameState
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Search Pipeline (engine/)                 │
│                                                             │
│  Layer 0: LethalChecker (5ms)                               │
│      ↓ 致命未找到                                           │
│  Layer 1: MCTSEngine ←── 新增搜索引擎                      │
│      │  ┌────────────────────────────────────────────┐      │
│      │  │  DUCT Determinizer (numWorlds=7)           │      │
│      │  │    ↓ 每次迭代选择一个世界                    │      │
│      │  │  UCT Selection → Expansion → Eval Cutoff   │      │
│      │  │    ↓                                       │      │
│      │  │  Backpropagation → 更新路径统计             │      │
│      │  │    ↓ 时间用尽                              │      │
│      │  │  输出: 最优动作序列 (Action[])              │      │
│      │  └────────────────────────────────────────────┘      │
│      ↓                                                      │
│  Layer 2: RiskAssessor + OpponentSimulator (复用)            │
│      ↓ 安全验证通过                                         │
│  输出: SearchResult                                         │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 与现有管线的集成位置

MCTS 替代现有管线中的 RHEA + UTP 两层：

```
现有管线:  Lethal(5ms) → UTP(10%) → RHEA(50%) → Multi-turn(10%) → Cross-turn(20%)
MCTS管线:  Lethal(5ms) → MCTS(80%)            → Risk+OppSim(15%) → 余量(5%)
```

- **前置层 (不变)**: `LethalChecker` 先检测致命，若找到立即返回
- **主搜索层 (新增)**: `MCTSEngine` 获得总预算的 ~80%
- **后验证层 (复用)**: `RiskAssessor` + `OpponentSimulator` 对输出序列做安全验证

### 1.3 数据流

```
GameState (from StateBridge)
    │
    ├── load_scores_into_hand(state)  // 复用: 加载卡牌评分
    │
    ▼
MCTSEngine.search(state, time_budget_ms)
    │
    ├── 1. Determinizer.create_worlds(state, num_worlds=7)
    │      → List[DeterminizedWorld]  (对手手牌/奥秘/牌库的假设)
    │
    ├── 2. MCTS 主循环 (见 §1.4)
    │      → 选择每一步最优动作 → 动作后以新状态为根继续
    │
    ├── 3. 输出 List[Action] (动作序列, 最后一个为 END_TURN)
    │
    ▼
RiskAssessor.assess(final_state, action_sequence)  // 复用
    │
    ▼
SearchResult(best_sequence, fitness, alternatives)
```

### 1.4 各模块职责

| 模块 | 文件 | 职责 |
|------|------|------|
| `MCTSEngine` | `mcts/engine.py` | 主入口，时间管理，动作序列拼接 |
| `MCTSNode` | `mcts/node.py` | 树节点数据结构，统计维护 |
| `UCTPolicy` | `mcts/uct.py` | UCB1 选择公式，探索-利用平衡 |
| `Expander` | `mcts/expansion.py` | 节点展开，渐进展开 |
| `Evaluator` | `mcts/simulation.py` | 评估截断 / rollout 策略 |
| `Backpropagator` | `mcts/backprop.py` | 反向传播统计更新 |
| `Determinizer` | `mcts/determinization.py` | DUCT 确定化采样 |
| `ActionPruner` | `mcts/pruning.py` | 动作过滤 + 必要动作 |
| `TranspositionTable` | `mcts/transposition.py` | 状态哈希 → 节点映射 |
| `MCTSConfig` | `mcts/config.py` | 参数配置 |

## 二、数据结构设计

### 2.1 MCTSNode — MCTS 树节点

```python
@dataclass
class MCTSNode:
    """MCTS 搜索树节点。
    
    设计理由:
    - state_hash 而非完整 GameState 引用: 节省内存，支持转置表查找
    - children 通过 action_key 索引: O(1) 查找已展开子节点
    - untried_actions 延迟计算: 首次访问时才生成，避免未访问节点的开销
    """
    
    # === 身份 ===
    node_id: int                        # 全局唯一 ID (用于调试)
    state_hash: int                     # IS-state 哈希值 (见 §2.6)
    is_terminal: bool = False           # 是否终止状态 (英雄死亡)
    terminal_reward: Optional[float] = None  # 终止状态的奖励值
    
    # === 树结构 ===
    parent: Optional['MCTSNode'] = None
    children: Dict[int, 'MCTSNode'] = field(default_factory=dict)
        # key = action.action_key(), value = 子节点
    
    # === 统计信息 ===
    visit_count: int = 0                # 总访问次数
    total_reward: float = 0.0           # 累积奖励 (用于 UCT 的 Q 值)
    
    # === 展开控制 ===
    untried_actions: Optional[List[Action]] = None  # None = 未初始化
    is_expanded: bool = False           # 是否已完成首次展开
    
    # === 上下文 ===
    is_player_turn: bool = True         # True = 我方回合, False = 对手回合
    depth: int = 0                      # 树深度 (用于调试和截断)
    
    # === 渐进展开 ===
    pw_threshold: int = 0               # 当前渐进展开阈值
    
    @property
    def q_value(self) -> float:
        """平均奖励 Q(n) = total_reward / visit_count"""
        return self.total_reward / max(self.visit_count, 1)
    
    @property
    def is_leaf(self) -> bool:
        """是否为叶节点 (未展开 或 无子节点)"""
        return not self.children or not self.is_expanded
    
    def get_untried_actions(self, state: GameState, pruner: 'ActionPruner') -> List[Action]:
        """延迟计算未尝试动作 (首次调用时生成并缓存)"""
        if self.untried_actions is None:
            all_actions = enumerate_legal_actions(state)
            self.untried_actions = pruner.filter(all_actions, state)
            # 打乱顺序以避免偏向性
            random.shuffle(self.untried_actions)
        return self.untried_actions
```

**关键设计决策:**

1. **不存储 GameState 引用**: 节点只存哈希，需要状态时从根节点沿动作路径重建。这大幅减少内存占用 (GameState ~2KB/个 vs int 哈希 28B)
2. **untried_actions 延迟初始化**: 未访问的节点不需要计算合法动作，节省大量预计算
3. **is_player_turn 标记**: 反向传播时需要知道当前节点的视角 (我方取正，对手取反)

### 2.2 ActionEdge — 动作边

```python
@dataclass
class ActionEdge:
    """MCTS 树中的有向边 (父节点 → 动作 → 子节点)。
    
    设计理由:
    - 分离边统计与节点统计: 支持 DAG 结构的扩展 (如 UCD 算法)
    - 记录产生此边的动作: 用于最终输出动作序列
    """
    action: Action                      # 产生此边的动作
    child_node: Optional[MCTSNode] = None  # 目标节点 (展开后设置)
    
    # 边级统计 (用于 DAG 扩展，当前版本可等同于子节点统计)
    visit_count: int = 0
    total_reward: float = 0.0
    
    @property
    def is_expanded(self) -> bool:
        return self.child_node is not None
```

**注意**: 当前版本 (MVP) 中，边统计与子节点统计一致。若后续升级为 DAG/UCD 架构 [S1]，边统计将独立维护。

### 2.3 DeterminizedWorld — 确定化世界

```python
@dataclass
class DeterminizedWorld:
    """DUCT 中的一个确定化世界。
    
    将不完全信息转化为完美信息:
    - 填充对手手牌 (从 BayesianOpponent 采样)
    - 确定对手奥秘
    - 确定对手牌库顺序
    """
    world_id: int                       # 世界编号
    state: GameState                    # 完整确定化的游戏状态
    weight: float = 1.0                 # 世界权重 (用于加权聚合)
    
    # 采样信息 (调试用)
    sampled_hand: List[Card] = field(default_factory=list)
    sampled_secrets: List[str] = field(default_factory=list)
```

### 2.4 SearchContext — 搜索上下文

```python
@dataclass
class SearchContext:
    """单次 MCTS 搜索的全局上下文。
    
    在搜索开始时创建，所有模块共享引用。
    """
    # 搜索状态
    root_state: GameState               # 原始根状态 (不完全信息)
    worlds: List[DeterminizedWorld]     # 确定化世界集合
    current_world: Optional[DeterminizedWorld] = None  # 当前迭代的世界
    
    # 树结构
    root_node: MCTSNode                 # 搜索树根节点
    transposition_table: TranspositionTable  # 转置表
    
    # 配置
    config: 'MCTSConfig'                # 搜索参数
    
    # 计时
    start_time: float = 0.0             # 搜索开始时间
    time_budget_ms: float = 5000.0      # 总时间预算 (ms)
    iterations_done: int = 0            # 已完成迭代次数
    
    # 统计 (调试/分析)
    nodes_created: int = 0
    evaluations_done: int = 0
    
    @property
    def time_remaining_ms(self) -> float:
        return max(0, self.time_budget_ms - (time.time() * 1000 - self.start_time))
    
    @property
    def should_stop(self) -> bool:
        return self.time_remaining_ms <= 0
```

### 2.5 状态哈希方案

```python
def compute_state_hash(state: GameState, is_player_turn: bool) -> int:
    """计算 IS-state (信息集状态) 的哈希值。
    
    基于 Świechowski & Tajmajer [S2] 的方案:
    - 公开信息: 双方英雄、场上随从 (按 ID 排序)、法力、奥秘数量
    - 活跃方私有信息: 手牌 (完整)、牌库数量
    - 非活跃方: 仅手牌数量 (不含具体卡牌)
    
    哈希内容:
    1. is_player_turn (1 bit)
    2. 我方英雄: (hp, armor, attack, weapon_name) → hash
    3. 我方随从: sorted by dbf_id → [(dbf_id, attack, health, has_taunt, ...)] → hash
    4. 我方法力: (available, max_mana, overloaded)
    5. 我方手牌数: len(hand) (不哈希具体卡牌，除非是活跃方)
    6. 对手英雄: 同上
    7. 对手随从: 同上 (全部公开)
    8. 对手手牌数: hand_count
    9. 回合数: turn_number
    """
    parts = []
    
    # 1. 回合方向
    parts.append(str(is_player_turn))
    
    # 2. 我方英雄
    hero = state.hero
    parts.append(f"H:{hero.hp},{hero.armor},{hero.attack},{hero.weapon}")
    
    # 3. 我方随从 (按 dbf_id 排序，忽略位置)
    my_minions = sorted(state.board, key=lambda m: m.dbf_id or 0)
    for m in my_minions:
        parts.append(f"M:{m.dbf_id},{m.attack},{m.health},{m.taunt},{m.divine_shield}")
    
    # 4. 法力
    parts.append(f"Mana:{state.mana.available},{state.mana.max_mana}")
    
    # 5. 对手 (全部公开信息)
    opp = state.opponent
    parts.append(f"OH:{opp.hero.hp},{opp.hero.armor}")
    opp_minions = sorted(opp.board, key=lambda m: m.dbf_id or 0)
    for m in opp_minions:
        parts.append(f"OM:{m.dbf_id},{m.attack},{m.health},{m.taunt}")
    parts.append(f"OHand:{opp.hand_count}")
    
    # 6. 回合数
    parts.append(f"T:{state.turn_number}")
    
    combined = "|".join(parts)
    return hash(combined)
```

### 2.6 与现有 GameState/Action 的映射

| MCTS 概念 | 现有项目组件 | 映射方式 |
|-----------|-------------|---------|
| 状态 S | `GameState` | 直接使用，通过 `copy()` 分支 |
| 动作 a | `Action` (`rhea/actions.py`) | 直接使用，`action_key()` 做哈希 |
| 合法动作集 | `enumerate_legal_actions(state)` | 直接调用 |
| 状态转移 T(s,a) | `apply_action(state, action)` | 直接调用，返回新状态副本 |
| 评估 V(s) | `evaluate_delta(s0, s1)` | 直接调用 |
| 阶段检测 | `detect_phase(turn_number)` | 直接调用 |

## 三、UCT 选择策略

### 3.1 标准 UCB1 公式

UCT (Upper Confidence Bound applied to Trees) 使用 UCB1 公式在探索与利用间平衡 [Kocsis & Szepesvári, 2006]:

```
UCT(n, a) = Q(n,a) + c * sqrt(ln(N(n)) / N(a))
```

其中:
- `Q(n,a)` = 从节点 n 执行动作 a 后的平均奖励
- `N(n)` = 节点 n 的总访问次数
- `N(a)` = 动作 a (即边 a) 的访问次数
- `c` = 探索常数，控制探索力度

### 3.2 针对炉石的调整

**探索常数 c 的选择依据** [S1][S3]:

| 卡组类型 | 推荐 c | 原因 |
|---------|--------|------|
| 快攻 (Aggro) | 0.25-0.4 | 动作序列短，决策相对确定 |
| 中速 (Midrange) | 0.5 | 默认值，平衡探索与利用 |
| 控制 (Control) | 0.6-1.0 | 决策空间大，需要更多探索 |

本项目默认 **c = 0.5**，可通过 `MCTSConfig.uct_constant` 调整。

**与 RHEA 参数的关系**: RHEA 的种群大小和变异率间接控制搜索宽度，UCT 的 c 直接控制。c=0.5 约对应 RHEA pop=40 的搜索宽度。

### 3.3 终止动作 (END_TURN) 的特殊处理

END_TURN 动作在炉石中是终止动作，需要特殊处理:

1. **始终包含在合法动作中**: END_TURN 在每个节点都是可选的 (模拟"结束本回合")
2. **终止标志**: 选择 END_TURN 后标记子节点为回合终止
3. **对手回合衔接**: END_TURN 后的子节点为对手回合 (is_player_turn=False)
4. **时间分配**: END_TURN 不分配独立搜索时间，而是作为 MCTS 树中的自然终止点

```python
def _handle_end_turn(self, node: MCTSNode, action: Action, state: GameState) -> MCTSNode:
    """END_TURN 动作的特殊处理"""
    new_state = apply_action(state, action)
    child = MCTSNode(
        node_id=self._next_node_id(),
        state_hash=compute_state_hash(new_state, is_player_turn=False),
        parent=node,
        is_player_turn=False,  # 切换到对手回合
        depth=node.depth + 1,
    )
    # 检查是否游戏结束
    if new_state.is_lethal():
        child.is_terminal = True
        child.terminal_reward = 1.0  # 我方获胜
    return child
```

### 3.4 对手回合的节点处理

对手回合不使用 UCT 选择，而是采用**贪心/随机混合策略**:

```python
def _select_opponent_action(self, state: GameState) -> Action:
    """对手回合的动作选择策略 (非 UCT)"""
    actions = enumerate_legal_actions(state)
    if not actions:
        return Action(action_type=ActionType.END_TURN)
    
    # 80% 概率选择贪心最优 (用评估函数)
    # 20% 概率随机选择 (保持多样性)
    if random.random() < 0.8:
        best_action = max(actions, key=lambda a: self._quick_opp_eval(state, a))
        return best_action
    else:
        return random.choice(actions)
```

**设计理由**: 对手回合的节点在单回合 MCTS 中通常是叶节点 (搜索到 END_TURN 后评估截断)。如果需要搜索对手回合 (跨回合搜索)，使用简化策略而非完整 UCT，以节省时间。

### 3.5 伪代码

```python
def uct_select(node: MCTSNode, config: MCTSConfig) -> Tuple[Action, ActionEdge]:
    """UCT 选择: 从已展开的子节点中选择最优"""
    c = config.uct_constant
    log_parent_visits = math.log(max(node.visit_count, 1))
    
    best_score = -float('inf')
    best_edge = None
    
    for action_key, child in node.children.items():
        if child.visit_count == 0:
            # 未访问过的子节点优先级最高
            return action_key, node.action_edges[action_key]
        
        # UCB1 公式
        exploitation = child.q_value
        exploration = c * math.sqrt(log_parent_visits / child.visit_count)
        uct_score = exploitation + exploration
        
        if uct_score > best_score:
            best_score = uct_score
            best_edge = node.action_edges[action_key]
    
    return best_edge.action, best_edge
```

## 四、展开策略

### 4.1 基本展开

从叶节点的 `untried_actions` 中选择一个动作进行展开:

```python
def expand(node: MCTSNode, state: GameState, pruner: ActionPruner) -> Action:
    """基本展开: 从未尝试动作中弹出一个"""
    untried = node.get_untried_actions(state, pruner)
    if not untried:
        return None  # 所有动作已展开
    return untried.pop()  # 弹出最后一个 (已打乱)
```

### 4.2 渐进展开 (Progressive Widening)

炉石单节点可能有数十个合法动作。标准 MCTS 要求展开所有子节点后才能使用 UCT 选择，这对大动作空间不现实。

**渐进展开** [Couëtoux et al., 2011]: 限制子节点数随访问次数增长:

```
k(n) = ⌊C_pw * n^α_pw⌋
```

- `n` = 节点访问次数
- `C_pw` = 展开系数 (默认 1.0)
- `α_pw` = 展开指数 (默认 0.5, 即 sqrt)

**含义**: 节点被访问 k 次时，最多展开 k^0.5 个子节点。

| 访问次数 | 最大子节点数 (α=0.5, C=1) |
|---------|--------------------------|
| 1 | 1 |
| 4 | 2 |
| 9 | 3 |
| 25 | 5 |
| 100 | 10 |
| 400 | 20 |

**来源**: Choe & Kim [S1] 在炉石中使用 DPW (Double Progressive Widening) 处理决策节点和机遇节点，α=0.5 是跨域通用值。

### 4.3 展开时的状态复制策略

```python
def expand_node(
    self, 
    node: MCTSNode, 
    state: GameState,
    ctx: SearchContext
) -> Optional[MCTSNode]:
    """展开节点: 创建一个新的子节点"""
    
    # 1. 检查渐进展开限制
    pw_limit = int(ctx.config.pw_constant * (node.visit_count ** ctx.config.pw_alpha))
    if len(node.children) >= pw_limit and node.is_expanded:
        return None  # 已达上限，不展开新节点
    
    # 2. 获取未尝试动作
    untried = node.get_untried_actions(state, ctx.pruner)
    if not untried:
        node.is_expanded = True
        return None
    
    # 3. 选择展开动作 (可加入启发式排序)
    action = self._select_expansion_action(untried, state, ctx)
    
    # 4. 复制状态并应用动作 (关键: 此处才复制状态)
    new_state = apply_action(state, action)
    
    # 5. 创建子节点
    is_player_turn = not (action.action_type == ActionType.END_TURN and node.is_player_turn)
    if action.action_type == ActionType.END_TURN:
        is_player_turn = not node.is_player_turn
    
    child = MCTSNode(
        node_id=self._next_node_id(),
        state_hash=compute_state_hash(new_state, is_player_turn),
        parent=node,
        is_player_turn=is_player_turn,
        depth=node.depth + 1,
    )
    
    # 6. 检查终止条件
    if new_state.is_lethal():
        child.is_terminal = True
        child.terminal_reward = 1.0 if is_player_turn == ctx.root_is_player else -1.0
    
    # 7. 注册到父节点
    edge = ActionEdge(action=action, child_node=child)
    node.children[action.action_key()] = child
    node.action_edges[action.action_key()] = edge
    
    # 8. 注册到转置表
    ctx.transposition_table.put(child.state_hash, child)
    
    return child
```

**状态复制只在展开时发生**: Selection 阶段沿已有路径下降，不复制状态。仅在 Expansion 时才调用 `apply_action(state, action)` 创建新副本。

### 4.4 展开动作选择策略

对 `untried_actions` 的选择顺序影响收敛速度。推荐策略:

```python
def _select_expansion_action(self, untried: List[Action], state: GameState, ctx: SearchContext) -> Action:
    """选择下一个展开的动作"""
    if ctx.config.expansion_order == "random":
        return untried.pop()
    
    elif ctx.config.expansion_order == "heuristic":
        # 按启发式评分排序: 高分动作先展开
        scored = [(a, self._heuristic_score(a, state)) for a in untried]
        scored.sort(key=lambda x: x[1], reverse=True)
        best = scored[0][0]
        untried.remove(best)
        return best
    
    elif ctx.config.expansion_order == "balanced":
        # 交替: 一半随机, 一半启发式
        if random.random() < 0.5:
            return untried.pop()
        else:
            return max(untried, key=lambda a: self._heuristic_score(a, state))
```

### 4.5 伪代码 (完整展开流程)

```
function EXPAND(node, state, ctx):
    if node.is_terminal:
        return node, state
    
    // 检查渐进展开限制
    pw_limit = floor(C_pw * node.visit_count ^ α_pw)
    if len(node.children) >= pw_limit AND node.is_expanded:
        return node, state  // 不展开, 直接评估
    
    // 获取未尝试动作
    untried = node.get_untried_actions(state, pruner)
    
    if not untried:
        node.is_expanded = True
        return node, state  // 所有动作已展开
    
    // 选择并移除一个动作
    action = select_expansion_action(untried, state)
    
    // 复制状态并应用
    new_state = apply_action(state, action)
    
    // 创建子节点
    child = create_child_node(node, action, new_state)
    
    // 注册
    node.children[action.action_key()] = child
    transposition_table.put(child.state_hash, child)
    
    return child, new_state
```

## 五、模拟/评估策略

### 5.1 方案 A: 评估截断 (推荐方案)

不执行完整游戏模拟，直接用评估函数评估叶节点状态。这是对 Python 性能瓶颈最有效的应对策略。

```python
def evaluate_leaf(
    self,
    leaf_state: GameState,
    root_state: GameState,
    ctx: SearchContext
) -> float:
    """评估截断: 使用评估函数计算叶节点值"""
    
    # 终止状态直接返回确定值
    if leaf_state.is_lethal():
        # 检查是我方还是对方死亡
        if leaf_state.hero.hp <= 0:
            return -1.0  # 我方死亡
        elif leaf_state.opponent.hero.hp <= 0:
            return 1.0   # 对方死亡
    
    # 使用现有评估器
    raw_score = evaluate_delta(root_state, leaf_state)
    
    # 归一化到 [-1, 1]
    return normalize_score(raw_score)
```

**优势**:
- 单次评估 ~0.1-0.5ms (vs 完整 rollout ~5-50ms)
- 允许在相同时间内完成 10-50x 更多迭代
- 复用项目已有的高质量评估器 (7 个 EvaluationFactor)

**劣势**:
- 评估函数偏差直接影响搜索质量
- 不具备 MCTS 随机 rollout 的多样性

### 5.2 方案 B: 混合策略 (短 Rollout + 评估)

结合 rollout 和评估截断的优点:

```python
def simulate_hybrid(
    self,
    state: GameState,
    ctx: SearchContext
) -> float:
    """混合策略: 短 rollout (1-2步) + 评估截断"""
    current = state
    rollout_depth = 0
    max_rollout_depth = ctx.config.rollout_depth  # 默认 1
    
    # 短 rollout: 执行 1-2 个随机动作
    while rollout_depth < max_rollout_depth:
        actions = enumerate_legal_actions(current)
        if not actions:
            break
        # 过滤后的随机动作
        filtered = ctx.pruner.filter_simulate(actions, current)
        action = random.choice(filtered) if filtered else random.choice(actions)
        current = apply_action(current, action)
        rollout_depth += 1
        
        if current.is_lethal():
            break
    
    # 评估截断
    return evaluate_leaf(current, ctx.root_state, ctx)
```

### 5.3 方案 C: 完整随机 Rollout (基准对比)

标准 MCTS rollout，用于基准测试对比:

```python
def simulate_random(self, state: GameState, max_depth: int = 3) -> float:
    """完整随机 rollout (基准)"""
    current = state
    depth = 0
    
    while depth < max_depth and not current.is_lethal():
        actions = enumerate_legal_actions(current)
        if not actions:
            break
        action = random.choice(actions)
        current = apply_action(current, action)
        depth += 1
    
    if current.is_lethal():
        return 1.0 if current.opponent.hero.hp <= 0 else -1.0
    
    return normalize_score(evaluate(current))
```

**不推荐作为主方案的原因**: Python 中 `apply_action` 每次约 0.5-2ms，3 回合 rollout 可能需要 30-100ms，5 秒预算仅能完成 ~50 次迭代。

### 5.4 评估值归一化

```python
def normalize_score(raw_score: float) -> float:
    """将评估器输出归一化到 [-1, 1]"""
    # evaluate_delta 通常输出 [-30, 30] 范围
    # 使用 tanh 压缩到 [-1, 1]
    return math.tanh(raw_score / 15.0)
    
    # 备选: 线性裁剪
    # return max(-1.0, min(1.0, raw_score / 20.0))
```

**tanh 的优势**: 
- 保持单调性 (高分仍然高分)
- 平滑压缩极端值
- 导数性质好 (梯度不会消失)

### 5.5 终止状态检测

```python
def get_terminal_reward(state: GameState, perspective_is_player: bool) -> Optional[float]:
    """检查终止状态并返回奖励值"""
    my_hero = state.hero if perspective_is_player else state.opponent.hero
    opp_hero = state.opponent.hero if perspective_is_player else state.hero
    
    if opp_hero.hp <= 0:
        return 1.0   # 对手死亡 → 我方获胜
    if my_hero.hp <= 0:
        return -1.0  # 我方死亡 → 对手获胜
    return None       # 游戏未结束
```

## 六、反向传播

### 6.1 标准反向传播

沿 Selection 路径从叶节点回溯到根节点，更新沿途每个节点的 `visit_count` 和 `total_reward`:

```python
def backpropagate(path: List[MCTSNode], reward: float) -> None:
    """标准反向传播
    
    Args:
        path: Selection 阶段经过的节点列表 (不含叶节点)
        reward: 模拟/评估阶段返回的奖励值 [-1, 1]
    """
    for node in reversed(path):
        node.visit_count += 1
        
        # 根据视角决定奖励方向
        if node.is_player_turn:
            node.total_reward += reward      # 我方节点: 好结果 → 正值
        else:
            node.total_reward += (1 - reward)  # 对手节点: 好结果 → 负值 (反转)
```

### 6.2 对手回合节点的值处理

MCTS 在双人零和博弈中，对手回合的节点值需要取反:

- **我方节点**: 倾向选择高 Q 值 (对我方有利)
- **对手节点**: 倾向选择对我方不利的动作 (对手会最大化自己的收益)

```python
def get_node_value_for_parent(child: MCTSNode, parent: MCTSNode) -> float:
    """获取子节点对父节点的价值"""
    if child.visit_count == 0:
        return 0.0
    
    child_q = child.total_reward / child.visit_count
    
    # 如果父节点和子节点视角不同 (我方→对手 或 对手→我方)
    # 需要取反 (零和博弈)
    if parent.is_player_turn != child.is_player_turn:
        return 1.0 - child_q  # 对手的好结果 = 我方的坏结果
    else:
        return child_q
```

### 6.3 多世界统计聚合 (DUCT)

DUCT 中，多个世界共享同一棵树。每次迭代的奖励来自一个特定世界:

```python
def backpropagate_duct(path: List[MCTSNode], reward: float, world_id: int) -> None:
    """DUCT 反向传播: 多世界共享统计"""
    for node in reversed(path):
        node.visit_count += 1
        node.total_reward += reward  # 所有世界的统计聚合
        
        # 注意: 不区分不同世界的统计
        # UCT 选择时使用聚合后的 Q 值
        # 这假设不同世界下的最优动作高度相关
```

**关键设计**: Zhang [S3] 验证了聚合统计的有效性 — 不同确定化世界下的最优动作通常高度重合，聚合不会导致明显的策略偏差。

### 6.4 伪代码

```
procedure BACKPROPAGATE(path, reward):
    for node in REVERSED(path):
        node.visit_count += 1
        
        if node.is_player_turn:
            node.total_reward += reward
        else:
            node.total_reward += (1 - reward)
        
        // 可选: 更新边统计 (为 DAG 扩展预留)
        if node.parent is not None:
            edge = node.parent.action_edges[node.action_key]
            edge.visit_count += 1
            edge.total_reward += reward
```

## 七、确定化采样 (DUCT)

### 7.1 确定化流程

DUCT (Determinized UCT) [S3] 将不完全信息转化为完美信息:

```
原始状态 (不完全信息):
  已知: 我方手牌、场上随从、公开信息
  未知: 对手手牌、对手奥秘、双方牌库顺序

确定化后 (完美信息):
  采样对手手牌 ← BayesianOpponent 或均匀采样
  采样对手奥秘 ← 已知奥秘池中选取
  采样牌库顺序 ← 随机打乱
  
  → 完整 GameState (可执行 apply_action)
```

### 7.2 采样策略

```python
class Determinizer:
    """DUCT 确定化采样器"""
    
    def create_worlds(self, state: GameState, num_worlds: int) -> List[DeterminizedWorld]:
        """创建 num_worlds 个确定化世界"""
        worlds = []
        for i in range(num_worlds):
            determinized = self._determinize(state)
            worlds.append(DeterminizedWorld(
                world_id=i,
                state=determinized,
                weight=1.0 / num_worlds,  # 均匀权重
            ))
        return worlds
    
    def _determinize(self, state: GameState) -> GameState:
        """从信息集采样一个完整世界"""
        det = state.copy()
        opp = det.opponent
        
        # 1. 采样对手手牌
        if opp.hand_count > 0:
            det.hand = self._sample_opponent_hand(opp, state)
        
        # 2. 采样对手奥秘
        if opp.secrets:
            det.opponent.secrets = self._sample_secrets(opp.secrets)
        
        # 3. 采样对手牌库
        if opp.deck_remaining > 0:
            det.opponent.deck_list = self._sample_opponent_deck(opp)
        
        return det
```

### 7.3 采样方法

**对手手牌采样 (两种策略)**:

```python
def _sample_opponent_hand(self, opp: OpponentState, state: GameState) -> List[Card]:
    """采样对手手牌"""
    # 策略 A: BayesianOpponent 加权采样 (推荐)
    # 基于已观察到的对手行为推断可能的卡牌
    candidate_cards = self.bayesian_opponent.predict_hand(opp, state)
    return random.sample(candidate_cards, min(opp.hand_count, len(candidate_cards)))
    
    # 策略 B: 均匀采样 (回退)
    # 从对手可能持有的卡牌池中随机选择
    pool = self._get_possible_cards(opp, state)
    return random.sample(pool, min(opp.hand_count, len(pool)))
```

**对手牌库采样**:

```python
def _sample_opponent_deck(self, opp: OpponentState) -> List[Card]:
    """采样对手牌库 (剩余部分)"""
    # 已知信息: 对手已打出的卡牌 + 可见的卡组列表 (如果已知)
    known_cards = opp.opp_known_cards or []
    remaining = opp.deck_remaining
    
    # 从已知卡组中去除已打出和手牌中的卡牌
    pool = self._get_remaining_pool(opp)
    deck = list(pool)
    random.shuffle(deck)
    return deck[:remaining]
```

### 7.4 多世界统计聚合

UCT 选择时，所有世界共享同一棵树。每次迭代随机选择一个世界:

```python
def select_world(self, worlds: List[DeterminizedWorld]) -> DeterminizedWorld:
    """选择本次迭代使用的世界"""
    # 均匀选择 (简单有效, Zhang [S3] 推荐)
    return random.choice(worlds)
```

### 7.5 软等价: 动作哈希聚合

不同确定化世界可能产生"等价"的动作。使用软等价 (Soft Hash) 聚合统计 [S3]:

```python
def action_soft_hash(action: Action) -> int:
    """动作软哈希: 忽略不影响决策的属性"""
    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        # 打牌: 卡牌ID + 目标类型 (忽略手牌位置)
        return hash((action.action_type, action.card_index, 
                     action.target_index if action.target_index >= 0 else -1))
    elif action.action_type == ActionType.ATTACK:
        # 攻击: 攻击者ID + 目标ID (忽略位置)
        return hash((action.action_type, action.source_index, action.target_index))
    else:
        return hash(action.action_key())
```

### 7.6 与 BayesianOpponent 的集成

```python
# 在 MCTSEngine 初始化时
self.bayesian_opponent = BayesianOpponent()

# 在创建确定化世界时
def create_worlds_with_bayesian(self, state: GameState, game_record: Optional[GameRecord]) -> List[DeterminizedWorld]:
    """使用贝叶斯对手模型创建确定化世界"""
    if game_record:
        self.bayesian_opponent.update(game_record)
    
    worlds = []
    for i in range(self.config.num_worlds):
        det = self._determinize(state)
        worlds.append(DeterminizedWorld(world_id=i, state=det))
    return worlds
```

### 7.7 伪代码 (DUCT 主循环)

```
procedure DUCT_SEARCH(root_state, time_budget):
    worlds ← create_worlds(root_state, numWorlds)
    root_node ← create_root(root_state)
    
    while time_remaining > 0:
        // 1. 选择世界
        world ← random.choice(worlds)
        
        // 2. Selection
        path, leaf, leaf_state ← select(root_node, world.state)
        
        // 3. Expansion (if not terminal and is leaf)
        if not leaf.is_terminal and leaf.is_leaf:
            child, new_state ← expand(leaf, leaf_state)
            path.append(leaf)
            leaf ← child
            leaf_state ← new_state
        
        // 4. Simulation/Evaluation
        reward ← evaluate_leaf(leaf_state, root_state)
        
        // 5. Backpropagation
        backpropagate(path, reward)
    
    // 6. 选择最优动作
    best_action ← argmax_{a} root_node.children[a].visit_count
    return best_action
```

## 八、动作剪枝

### 8.1 类别动作过滤 (Category-based Filtering)

据 Choe & Kim [S1] 的研究，过滤自毁/浪费性动作可将 MCTS 效率提升 30-50%。

```python
class ActionPruner:
    """动作剪枝器"""
    
    def filter(self, actions: List[Action], state: GameState) -> List[Action]:
        """过滤树阶段的动作 (宽松: 保留可能的'小众'动作)"""
        filtered = []
        for action in actions:
            if self._should_prune_tree(action, state):
                continue
            filtered.append(action)
        return filtered
    
    def filter_simulate(self, actions: List[Action], state: GameState) -> List[Action]:
        """过滤模拟阶段的动作 (严格: 只保留明显合理的动作)"""
        filtered = []
        for action in actions:
            if self._should_prune_simulate(action, state):
                continue
            filtered.append(action)
        return filtered
```

### 8.2 必要动作 (Obliged Actions)

某些动作在特定条件下是无条件有利的，应强制执行 [S1]:

```python
def get_obliged_actions(self, actions: List[Action], state: GameState) -> List[Action]:
    """返回必要动作 (如果存在，移除 END_TURN 选项强制执行)"""
    obliged = []
    
    for action in actions:
        # 条件 1: 随从可无代价攻击对手英雄 (无嘲讽阻挡)
        if (action.action_type == ActionType.ATTACK 
            and action.target_index == TARGET_OPPO_HERO
            and self._no_taunt_blocking(state)):
            obliged.append(action)
        
        # 条件 2: 0 费卡牌 (无代价打出)
        if (action.action_type == ActionType.PLAY
            and self._card_cost(action, state) == 0
            and not self._is_self_harm(action, state)):
            obliged.append(action)
    
    return obliged
```

### 8.3 过滤规则清单

**树阶段 (宽松过滤)**:

| 规则 | 描述 | 保留? |
|------|------|------|
| 自伤法术 | 对己方英雄使用伤害法术 | ❌ 剪枝 |
| 过度治疗 | 治疗已满血角色 | ❌ 剪枝 |
| 友军伤害 | 对己方随从使用伤害法术 (无特殊效果) | ❌ 剪枝 |
| 无效增益 | 给无法攻击的随从加攻击力 | ⚠️ 保留 (可能有联动) |
| 明显劣交换 | 用高价值随从换低价值随从 | ✅ 保留 (MCTS 自行判断) |

**模拟阶段 (严格过滤)**:

在树阶段基础上额外剪枝:
- 不攻击有嘲讽的随从以外的目标
- 不打出明显亏节奏的卡牌
- 优先执行必要动作

### 8.4 伪代码

```python
def _should_prune_tree(self, action: Action, state: GameState) -> bool:
    """树阶段剪枝判断"""
    if action.action_type == ActionType.PLAY_WITH_TARGET:
        card = state.hand[action.card_index]
        target = self._get_target(action, state)
        
        # 伤害法术打友方 → 剪枝
        if self._is_damage_spell(card) and self._is_friendly_target(target, state):
            return True
        
        # 治疗法术打满血目标 → 剪枝
        if self._is_heal_spell(card) and self._is_full_health(target):
            return True
    
    if action.action_type == ActionType.ATTACK:
        source = state.board[action.source_index]
        target = self._get_attack_target(action, state)
        
        # 0 攻击随从不攻击 → 剪枝
        if source.attack <= 0:
            return True
    
    return False
```

## 九、转置表

### 9.1 设计目标

转置表解决的核心问题: **不同动作序列可能到达相同状态**。

例: "先打随从A再攻击B" 与 "先攻击B再打随从A" 的终态可能相同。转置表让这两个序列共享统计信息。

### 9.2 表结构

```python
class TranspositionTable:
    """MCTS 转置表: state_hash → MCTSNode"""
    
    def __init__(self, max_size: int = 100_000):
        self._table: Dict[int, MCTSNode] = {}
        self._max_size = max_size
    
    def get(self, state_hash: int) -> Optional[MCTSNode]:
        """查找已有节点"""
        return self._table.get(state_hash)
    
    def get_or_create(self, state_hash: int, **node_kwargs) -> MCTSNode:
        """查找或创建节点"""
        if state_hash in self._table:
            return self._table[state_hash]
        
        node = MCTSNode(state_hash=state_hash, **node_kwargs)
        self._table[state_hash] = node
        
        # 内存保护
        if len(self._table) > self._max_size:
            self._evict()
        
        return node
    
    def put(self, state_hash: int, node: MCTSNode) -> None:
        """注册节点"""
        if state_hash not in self._table:
            self._table[state_hash] = node
    
    def _evict(self) -> None:
        """淘汰策略: 移除访问次数最少的 10% 节点"""
        items = list(self._table.items())
        items.sort(key=lambda x: x[1].visit_count)
        evict_count = len(items) // 10
        for hash_key, _ in items[:evict_count]:
            del self._table[hash_key]
    
    def clear(self) -> None:
        self._table.clear()
    
    @property
    def size(self) -> int:
        return len(self._table)
```

### 9.3 冲突处理

由于使用 Python 内置 `hash()` 产生 int64 哈希值，碰撞概率极低 (生日悖论: 10万条目时碰撞率 ~0.0003%)。

若需更严格的碰撞保护，可在 `get` 时额外比较关键状态字段:

```python
def get_strict(self, state_hash: int, state: GameState) -> Optional[MCTSNode]:
    """严格查找: 哈希匹配后再验证状态"""
    node = self._table.get(state_hash)
    if node is None:
        return None
    # 可选: 验证哈希冲突 (开发阶段启用, 生产环境关闭)
    return node
```

### 9.4 跨搜索复用 (树重用)

选择一个动作后，以该动作产生的状态为新根，复用已有子树:

```python
def reuse_tree(self, old_root: MCTSNode, chosen_action_key: int) -> MCTSNode:
    """树重用: 保留已选动作的子树作为新根"""
    if chosen_action_key in old_root.children:
        new_root = old_root.children[chosen_action_key]
        new_root.parent = None  # 断开与旧根的连接
        return new_root
    else:
        return None  # 无可复用的子树, 需要新建
```

### 9.5 内存管理

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `max_size` | 100,000 | 最大节点数 |
| `evict_ratio` | 0.1 | 淘汰时移除的比例 |
| 预估内存 | ~200MB | 100K 节点 × ~2KB/节点 (含统计) |

如果内存紧张，可将 `max_size` 降至 50,000。MCTS 的统计特性使得即使部分节点被淘汰，搜索质量也不会严重下降 (不同于 AlphaBeta 需要精确的转置表)。

## 十、时间预算管理

### 10.1 指数递减策略

据 Choe & Kim [S1] 的研究，为单回合中每个动作的搜索时间指数递减是有效的:

```
T(n) = T0 × γ^(n-1)

其中:
  T(n) = 第 n 个动作的搜索时间
  T0   = 首个动作的搜索时间
  γ    = 衰减因子 (< 1)
  
  γ 由总预算约束确定:
  T_max = Σ_{i=1}^{k} T0 × γ^(i-1)
```

**示例**: 总预算 8s, 预计 5 个动作:

| 动作序号 | 时间 (γ=0.6) | 占比 |
|---------|-------------|------|
| 1 | 4.62s | 57.8% |
| 2 | 2.77s | 34.6% |
| 3 | 1.66s | 20.8% |
| 4 | 1.00s | 12.5% |
| 5 | 0.60s | 7.5% |

### 10.2 总时间预算自适应

```python
def compute_time_budget(self, state: GameState, base_ms: float = 5000.0) -> float:
    """自适应时间预算"""
    phase = detect_phase(state.turn_number)
    
    # 基础预算
    budget = base_ms
    
    # 阶段调整
    if phase == Phase.EARLY:
        budget *= 0.7   # 早期决策简单
    elif phase == Phase.LATE:
        budget *= 1.3   # 后期决策关键
    
    # 复杂度调整: 动作空间大小
    action_count = len(enumerate_legal_actions(state))
    if action_count > 30:
        budget *= 1.2   # 复杂局面多给时间
    
    return budget
```

### 10.3 多步动作序列的时间分配

```python
def search_action_sequence(
    self,
    state: GameState,
    total_budget_ms: float
) -> List[Action]:
    """搜索完整动作序列 (多步 MCTS)"""
    
    actions = []
    current_state = state
    remaining_budget = total_budget_ms
    step = 0
    
    # 计算衰减因子
    gamma = 0.6  # 经验值 [S1]
    t0 = remaining_budget * (1 - gamma)  # 首步时间
    
    while remaining_budget > 200:  # 最低 200ms
        # 当前步的时间预算
        step_budget = t0 * (gamma ** step)
        step_budget = max(step_budget, 300)  # 下限 300ms
        
        if step_budget > remaining_budget * 0.8:
            step_budget = remaining_budget * 0.8
        
        # 搜索下一步最优动作
        best_action = self._search_single_action(current_state, step_budget)
        
        if best_action.action_type == ActionType.END_TURN:
            actions.append(best_action)
            break
        
        # 应用动作
        actions.append(best_action)
        current_state = apply_action(current_state, best_action)
        remaining_budget -= step_budget
        step += 1
        
        # 检查是否有更多动作可做
        legal = enumerate_legal_actions(current_state)
        if not legal:
            break
    
    # 确保序列以 END_TURN 结束
    if not actions or actions[-1].action_type != ActionType.END_TURN:
        actions.append(Action(action_type=ActionType.END_TURN))
    
    return actions
```

### 10.4 树重用

选择动作后，复用已有子树:

```python
def _search_single_action(self, state: GameState, budget_ms: float) -> Action:
    """搜索单个最优动作"""
    start = time.time() * 1000
    
    # 尝试复用上一步的子树
    root = self._try_reuse_tree(state)
    if root is None:
        root = self._create_root(state)
    
    # MCTS 主循环
    while (time.time() * 1000 - start) < budget_ms:
        self._run_iteration(root, state)
    
    # 选择访问次数最多的动作
    if not root.children:
        return Action(action_type=ActionType.END_TURN)
    
    best_key = max(root.children.keys(), 
                   key=lambda k: root.children[k].visit_count)
    
    self._last_root = root  # 保存用于下次复用
    self._last_action_key = best_key
    
    return root.action_edges[best_key].action
```

### 10.5 紧急动作快速处理

```python
def _should_quick_play(self, state: GameState) -> bool:
    """判断是否应快速出牌 (不需要深度搜索)"""
    legal = enumerate_legal_actions(state)
    
    # 只有 1-2 个合法动作: 直接选择
    if len(legal) <= 2:
        return True
    
    # 只有 END_TURN 和少数无意义动作
    non_end = [a for a in legal if a.action_type != ActionType.END_TURN]
    if not non_end:
        return True
    
    return False
```

## 十一、管线集成

### 11.1 MCTS 在决策管线中的位置

```
                    GameState (from StateBridge)
                            │
                            ▼
┌─────────────────────────────────────────────────┐
│               Search Pipeline                    │
│                                                  │
│  Layer 0: LethalChecker (5ms)                    │
│      ↓ 未找到致命                               │
│  Layer 1: MCTSEngine (80% of remaining budget)   │
│      ↓ 输出 List[Action]                        │
│  Layer 2: RiskAssessor (10% of remaining budget) │
│      ↓ 风险可接受                               │
│  Layer 3: OpponentSimulator (10% of budget)      │
│      ↓ 验证通过                                 │
│                                                  │
│  Output: SearchResult                            │
└─────────────────────────────────────────────────┘
```

### 11.2 与致命检测层的交互

```python
# 在 Search Pipeline 中的调用逻辑
def search(self, state: GameState, time_budget_ms: float) -> SearchResult:
    # Layer 0: 致命检测 (复用现有)
    lethal_result = self.lethal_checker.check_lethal(state, max_time_ms=5)
    if lethal_result:
        return SearchResult(
            best_sequence=lethal_result.actions,
            fitness=1.0,  # 致命 = 最高优先
            source="lethal"
        )
    
    # Layer 1: MCTS 搜索
    mcts_budget = time_budget_ms * 0.80
    mcts_result = self.mcts_engine.search(state, mcts_budget_ms=mcts_budget)
    
    # Layer 2: 风险评估
    risk = self.risk_assessor.assess(state, mcts_result.best_sequence)
    if risk.total_risk > self.config.risk_threshold:
        # 风险过高 → 调整或重新搜索
        mcts_result = self._adjust_for_risk(state, mcts_result, risk)
    
    return mcts_result
```

### 11.3 与风险评估层的交互

MCTS 输出动作序列后，风险评估层验证安全性:

```python
# RiskAssessor 评估 MCTS 输出
def assess_mcts_result(self, initial_state: GameState, actions: List[Action]) -> RiskReport:
    """评估 MCTS 输出序列的风险"""
    # 模拟执行动作序列
    final_state = initial_state.copy()
    for action in actions:
        final_state = apply_action(final_state, action)
    
    # 评估 4 个维度 (复用现有)
    aoe_vul = self._assess_aoe_vulnerability(final_state)
    overextension = self._assess_overextension(final_state)
    survival = self._assess_survival(final_state)
    secret_threat = self._assess_secret_threat(final_state)
    
    total_risk = 0.3 * aoe_vul + 0.2 * overextension + 0.2 * secret_threat + 0.3 * (1 - survival)
    
    return RiskReport(
        total_risk=total_risk,
        aoe_vulnerability=aoe_vul,
        overextension=overextension,
        survival=survival,
        secret_threat=secret_threat
    )
```

### 11.4 与对手模拟层的交互

```python
# 可选: 对手模拟验证 MCTS 输出的鲁棒性
def validate_with_opponent_sim(self, state: GameState, actions: List[Action]) -> ValidationResult:
    """用对手模拟验证 MCTS 输出"""
    # 模拟我方执行动作序列
    my_state = state.copy()
    for action in actions:
        my_state = apply_action(my_state, action)
    
    # 模拟对手最佳响应
    opp_response = self.opponent_simulator.simulate_best_response(my_state)
    
    # 评估对手响应后的状态
    opp_state = apply_action(my_state, opp_response)
    resilience_score = evaluate_delta(state, opp_state)
    
    return ValidationResult(
        is_resilient=resilience_score > 0,
        resilience_score=resilience_score
    )
```

### 11.5 DecisionLoop 调用接口

```python
# analysis/watcher/decision_loop.py 中的修改
class DecisionLoop:
    def __init__(self, config):
        # 现有
        self.rhea_engine = RHEAEngine(config)
        # 新增
        self.mcts_engine = MCTSEngine(config)
        self.search_mode = config.get("search_mode", "mcts")  # "rhea" / "mcts" / "hybrid"
    
    def _on_decision_point(self, game_state: GameState) -> SearchResult:
        """决策点触发"""
        if self.search_mode == "mcts":
            return self.mcts_engine.search(game_state, self._compute_budget())
        elif self.search_mode == "rhea":
            return self.rhea_engine.search(game_state)
        elif self.search_mode == "hybrid":
            # 混合模式: 两个引擎都搜索，选更好的结果
            return self._hybrid_search(game_state)
```

### 11.6 配置切换

```ini
# cfg/live.cfg 新增配置
[search]
# 搜索引擎选择: rhea / mcts / hybrid
engine = mcts

[mcts]
# MCTS 参数 (详见 §十二)
uct_constant = 0.5
num_worlds = 7
pw_constant = 1.0
pw_alpha = 0.5
time_budget_ms = 8000
expansion_order = heuristic
```

## 十二、参数配置

### 12.1 完整参数表

```python
@dataclass
class MCTSConfig:
    """MCTS 搜索引擎完整参数配置"""
    
    # === UCT 参数 ===
    uct_constant: float = 0.5            # UCB1 探索常数 c [S1][S3]
                                        # 范围: 0.25-1.0, 快攻低/控制高
    
    # === 确定化参数 ===
    num_worlds: int = 7                  # DUCT 世界数 [S3]
                                        # 范围: 5-11
    sampling_method: str = "bayesian"    # 采样方法: "uniform" / "bayesian"
    
    # === 渐进展开参数 ===
    pw_constant: float = 1.0             # Progressive Widening C [S1]
    pw_alpha: float = 0.5                # Progressive Widening α [S1]
                                        # k = floor(C * n^α)
    
    # === 模拟/评估参数 ===
    simulation_mode: str = "eval_cutoff" # "eval_cutoff" / "hybrid" / "random"
    rollout_depth: int = 1               # 混合模式 rollout 深度 (回合)
    
    # === 时间预算 ===
    time_budget_ms: float = 8000.0       # 总时间预算 (ms)
    time_decay_gamma: float = 0.6        # 指数递减衰减因子 [S1]
    min_step_budget_ms: float = 300.0    # 单步最低时间 (ms)
    max_actions_per_turn: int = 10       # 单回合最大动作数
    
    # === 展开策略 ===
    expansion_order: str = "heuristic"   # "random" / "heuristic" / "balanced"
    
    # === 转置表 ===
    transposition_max_size: int = 100000 # 转置表最大节点数
    enable_transposition: bool = True    # 是否启用转置表
    
    # === 动作剪枝 ===
    enable_tree_pruning: bool = True     # 树阶段剪枝
    enable_sim_pruning: bool = True      # 模拟阶段剪枝
    enable_obliged_actions: bool = True  # 必要动作
    
    # === 搜索深度 ===
    max_tree_depth: int = 15             # 最大树深度 (动作数)
    
    # === 调试 ===
    debug_mode: bool = False             # 启用详细日志
    log_interval: int = 100              # 每 N 次迭代输出日志
```

### 12.2 阶段自适应参数

```python
def get_phase_config(phase: Phase) -> dict:
    """阶段自适应参数覆盖"""
    if phase == Phase.EARLY:
        return {
            "uct_constant": 0.4,       # 早期决策简单, 减少探索
            "num_worlds": 5,           # 对手手牌不确定性低 (刚开局)
            "time_budget_ms": 5000,    # 早期不需要太长时间
        }
    elif phase == Phase.MID:
        return {
            "uct_constant": 0.5,       # 默认值
            "num_worlds": 7,           # 标准世界数
            "time_budget_ms": 8000,    # 中期关键决策
        }
    else:  # LATE
        return {
            "uct_constant": 0.7,       # 后期决策复杂, 需要更多探索
            "num_worlds": 9,           # 对手可能有更多未知卡牌
            "time_budget_ms": 12000,   # 后期决策至关重要
        }
```

### 12.3 参数调优指南

| 参数 | 调优方法 | 调优指标 |
|------|---------|---------|
| uct_constant | 网格搜索 [0.25, 0.5, 0.75, 1.0] | 胜率 vs RHEA |
| num_worlds | 网格搜索 [3, 5, 7, 9, 11] | 胜率 + 时间效率 |
| pw_constant | 网格搜索 [0.5, 1.0, 2.0] | 迭代数/秒 |
| pw_alpha | 固定 0.5 | 理论最优值 |
| time_decay_gamma | [0.4, 0.6, 0.8] | 首步胜率贡献 |
| expansion_order | A/B 测试三种 | 收敛速度 |

**调优流程**:
1. 先用默认参数跑 100 局 vs RHEA
2. 每次只调一个参数，跑 50 局对比
3. 找到最优单参数后组合测试
4. 最终用最优参数跑 200 局验证

## 十三、文件结构

### 13.1 目录结构

```
analysis/search/mcts/
├── __init__.py              # 公开 API 导出 (~20行)
├── engine.py                # MCTSEngine 主类: search(), 动作序列拼接 (~400行)
├── node.py                  # MCTSNode, ActionEdge 数据类 (~150行)
├── uct.py                   # UCT 选择策略 (~100行)
├── expansion.py             # 展开策略 + 渐进展开 (~150行)
├── simulation.py            # 评估截断 / rollout 策略 (~120行)
├── backprop.py              # 反向传播 (~80行)
├── determinization.py       # DUCT 确定化采样 + BayesianOpponent 集成 (~200行)
├── pruning.py               # 动作过滤 + 必要动作 (~150行)
├── transposition.py         # 转置表 (~100行)
└── config.py                # MCTSConfig 参数配置 (~80行)

tests/search/mcts/
├── test_node.py             # 节点数据结构测试
├── test_uct.py              # UCT 选择策略测试
├── test_expansion.py        # 展开策略测试
├── test_simulation.py       # 评估策略测试
├── test_backprop.py         # 反向传播测试
├── test_determinization.py  # 确定化采样测试
├── test_pruning.py          # 动作剪枝测试
├── test_transposition.py    # 转置表测试
└── test_engine.py           # 集成测试: 完整 MCTS 搜索
```

### 13.2 各文件职责与预估行数

| 文件 | 职责 | 预估行数 | 依赖 |
|------|------|---------|------|
| `engine.py` | 搜索入口、时间管理、动作序列拼接 | ~400 | node, uct, expansion, simulation, backprop, determinization, config |
| `node.py` | MCTSNode / ActionEdge 数据类 | ~150 | game_state, actions |
| `uct.py` | UCB1 选择公式 | ~100 | node, config |
| `expansion.py` | 节点展开 + 渐进展开 | ~150 | node, enumeration, pruning, transposition |
| `simulation.py` | 评估截断 / rollout | ~120 | composite, config |
| `backprop.py` | 反向传播 | ~80 | node |
| `determinization.py` | DUCT 采样 | ~200 | game_state, bayesian_opponent |
| `pruning.py` | 动作过滤 | ~150 | actions, game_state |
| `transposition.py` | 转置表 | ~100 | node |
| `config.py` | 参数配置 | ~80 | phase |
| **总计** | | **~1530** | |

### 13.3 与现有 analysis/search/ 的关系

```
analysis/search/
├── rhea/              # 现有 RHEA 引擎 (保持不变)
├── mcts/              # 新增 MCTS 引擎
├── engine/            # 现有管线和评估因子 (MCTS 复用)
├── game_state.py      # 共享: 状态模型
├── lethal_checker.py  # 共享: 致命检测
├── opponent_simulator.py  # 共享: 对手模拟
├── risk_assessor.py   # 共享: 风险评估
└── ...
```

### 13.4 导入依赖图

```
engine.py
  ├── node.py ← game_state.py, actions.py
  ├── uct.py ← node.py, config.py
  ├── expansion.py ← node.py, enumeration.py, pruning.py, transposition.py
  ├── simulation.py ← composite.py (evaluators), config.py
  ├── backprop.py ← node.py
  ├── determinization.py ← game_state.py, bayesian_opponent.py
  ├── pruning.py ← actions.py, game_state.py
  └── config.py ← phase.py
```

## 十四、接口规范

### 14.1 MCTSEngine 公开接口

```python
class MCTSEngine:
    """MCTS/UCT 搜索引擎
    
    用法:
        engine = MCTSEngine(config)
        result = engine.search(game_state, time_budget_ms=8000)
        for action in result.best_sequence:
            execute(action)
    """
    
    def __init__(self, config: Optional[MCTSConfig] = None):
        """初始化 MCTS 引擎
        
        Args:
            config: MCTS 配置, None 使用默认配置
        """
        ...
    
    def search(
        self,
        state: GameState,
        time_budget_ms: Optional[float] = None,
        game_record: Optional[GameRecord] = None
    ) -> SearchResult:
        """执行 MCTS 搜索
        
        Args:
            state: 当前游戏状态 (不完全信息)
            time_budget_ms: 时间预算 (ms), None 使用配置默认值
            game_record: 游戏记录 (用于 BayesianOpponent)
        
        Returns:
            SearchResult 包含:
              - best_sequence: List[Action] 最优动作序列
              - fitness: float 评估分数
              - alternatives: List[Tuple[List[Action], float]] 备选方案
              - stats: MCTSStats 搜索统计
        """
        ...
    
    def search_single_action(
        self,
        state: GameState,
        time_budget_ms: float
    ) -> Tuple[Action, MCTSStats]:
        """搜索单个最优动作 (用于逐步执行)
        
        Returns:
            (最优动作, 搜索统计)
        """
        ...
```

### 14.2 MCTSNode 内部接口

```python
class MCTSNode:
    # 属性
    @property
    def q_value(self) -> float: ...       # 平均奖励
    @property
    def is_leaf(self) -> bool: ...        # 是否叶节点
    @property
    def best_child(self) -> Optional['MCTSNode']: ...  # 访问次数最多的子节点
    
    # 方法
    def get_untried_actions(self, state: GameState, pruner: ActionPruner) -> List[Action]: ...
    def update(self, reward: float) -> None: ...  # 更新统计
    def child_for_action(self, action_key: int) -> Optional['MCTSNode']: ...
```

### 14.3 与 GameState 的交互

```python
# MCTS 使用 GameState 的接口:
state.copy()                           # 状态复制 (展开时)
enumerate_legal_actions(state)         # 合法动作枚举
apply_action(state, action)            # 状态转移 → 新 GameState
state.is_lethal()                      # 终止检测
state.hero.hp                          # 英雄 HP
state.opponent.hero.hp                 # 对手英雄 HP
state.turn_number                      # 回合数 (用于阶段检测)
state.board                            # 场上随从
state.hand                             # 手牌
state.mana.available                   # 可用法力
```

### 14.4 与评估器的交互

```python
# MCTS 使用评估器的接口:
from analysis.evaluators.composite import evaluate_delta, evaluate

# 评估截断 (推荐)
score = evaluate_delta(initial_state, final_state)
# 返回: float (越大越好)

# 绝对评估 (备选)
score = evaluate(final_state)
# 返回: float
```

### 14.5 与管线的交互

```python
# SearchResult 格式兼容 (复用现有)
@dataclass
class SearchResult:
    best_sequence: List[Action]
    fitness: float
    alternatives: List[Tuple[List[Action], float]] = field(default_factory=list)
    source: str = "mcts"           # "rhea" / "mcts" / "lethal"
    
    # MCTS 特有统计
    mcts_stats: Optional['MCTSStats'] = None

@dataclass
class MCTSStats:
    iterations: int = 0                # 总迭代次数
    nodes_created: int = 0             # 创建节点数
    evaluations_done: int = 0          # 评估次数
    time_used_ms: float = 0.0          # 实际耗时
    world_count: int = 0               # 世界数
    transposition_hits: int = 0        # 转置表命中次数
    actions_explored: int = 0          # 探索的动作数
    pruning_rate: float = 0.0          # 剪枝率
```

## 十五、测试方案

### 15.1 单元测试

**测试清单**:

| 测试文件 | 测试内容 | 关键断言 |
|---------|---------|---------|
| `test_node.py` | MCTSNode 创建、更新、属性 | q_value 计算、is_leaf 判断 |
| `test_uct.py` | UCT 选择策略 | UCB1 公式正确性、探索-利用平衡 |
| `test_expansion.py` | 节点展开 + 渐进展开 | 子节点创建、PW 阈值计算 |
| `test_simulation.py` | 评估截断 / rollout | 评估值归一化、终止检测 |
| `test_backprop.py` | 反向传播 | 统计更新正确、对手节点值反转 |
| `test_determinization.py` | DUCT 采样 | 世界数正确、状态完整性 |
| `test_pruning.py` | 动作过滤 | 自伤法术被过滤、必要动作保留 |
| `test_transposition.py` | 转置表 | 哈希查找、淘汰策略 |

### 15.2 集成测试

```python
class TestMCTSIntegration:
    """MCTS 完整搜索流程集成测试"""
    
    def test_simple_board_state(self):
        """简单场面: 2个我方随从, 1个对手随从"""
        state = create_test_state(
            my_board=[minion("Yeti", 4, 5), minion("Boulderfist", 6, 7)],
            opp_board=[minion("Bear", 3, 3)],
            my_hand=[card("Fireball", cost=4)],
            my_mana=10
        )
        engine = MCTSEngine(MCTSConfig(time_budget_ms=1000))
        result = engine.search(state)
        
        assert result.best_sequence is not None
        assert len(result.best_sequence) > 0
        assert result.best_sequence[-1].action_type == ActionType.END_TURN
        assert result.fitness is not None
    
    def test_lethal_detection_in_mcts(self):
        """MCTS 应能发现致命"""
        state = create_test_state(
            my_board=[minion("Charger", 6, 1, charge=True)],
            opp_hero_hp=5,
            my_mana=0
        )
        engine = MCTSEngine(MCTSConfig(time_budget_ms=500))
        result = engine.search(state)
        
        # 应选择攻击英雄而非结束回合
        assert any(a.action_type == ActionType.ATTACK for a in result.best_sequence)
    
    def test_progressive_widening_limits(self):
        """渐进展开应限制子节点数"""
        state = create_test_state(large_action_space=True)
        engine = MCTSEngine(MCTSConfig(
            time_budget_ms=1000,
            pw_constant=1.0,
            pw_alpha=0.5
        ))
        result = engine.search(state)
        
        # 根节点子节点数应远少于总合法动作数
        legal_count = len(enumerate_legal_actions(state))
        root = engine._last_root
        assert len(root.children) <= legal_count
    
    def test_duct_worlds_are_used(self):
        """DUCT 应使用多个世界"""
        state = create_test_state(hidden_opponent_hand=True)
        config = MCTSConfig(num_worlds=5, time_budget_ms=1000)
        engine = MCTSEngine(config)
        result = engine.search(state)
        
        assert result.mcts_stats.world_count == 5
```

### 15.3 对比测试: MCTS vs RHEA

```python
class TestMCTSVsRHEA:
    """MCTS 与 RHEA 的 A/B 对比测试"""
    
    def setup_method(self):
        self.mcts = MCTSEngine(MCTSConfig(time_budget_ms=5000))
        self.rhea = RHEAEngine()  # 现有引擎
    
    @pytest.mark.slow
    def test_win_rate_against_rhea(self):
        """MCTS vs RHEA 胜率测试 (至少 50 局)"""
        results = run_matchup(
            player_a=self.mcts,
            player_b=self.rhea,
            num_games=50,
            deck="midrange_hunter",
            time_budget_ms=5000
        )
        
        mcts_wins = results.count("A")
        win_rate = mcts_wins / len(results)
        
        # MCTS 应至少与 RHEA 持平 (45%+ 胜率)
        assert win_rate >= 0.45, f"MCTS win rate too low: {win_rate:.2%}"
    
    @pytest.mark.slow
    def test_decision_quality_comparison(self):
        """相同局面下 MCTS 与 RHEA 的决策质量对比"""
        test_states = load_test_scenarios()  # 预设场景
        
        for state_file in test_states:
            state = load_state(state_file)
            
            mcts_result = self.mcts.search(state, time_budget_ms=5000)
            rhea_result = self.rhea.search(state)
            
            # 比较最终状态的评估值
            mcts_score = evaluate_delta(state, self._apply_sequence(state, mcts_result.best_sequence))
            rhea_score = evaluate_delta(state, self._apply_sequence(state, rhea_result.best_sequence))
            
            # MCTS 不应显著差于 RHEA
            assert mcts_score >= rhea_score - 5.0
```

### 15.4 性能测试

```python
class TestMCTSPerformance:
    """MCTS 性能基准测试"""
    
    def test_iterations_per_second(self):
        """迭代速率测试"""
        state = create_test_state(medium_complexity=True)
        engine = MCTSEngine(MCTSConfig(time_budget_ms=3000))
        
        result = engine.search(state)
        
        # 评估截断模式下应达到 >= 200 迭代/秒
        rate = result.mcts_stats.iterations / (result.mcts_stats.time_used_ms / 1000)
        assert rate >= 200, f"Too slow: {rate:.0f} iter/s"
    
    def test_memory_usage(self):
        """内存使用测试"""
        state = create_test_state()
        engine = MCTSEngine(MCTSConfig(
            time_budget_ms=5000,
            transposition_max_size=50000
        ))
        
        import tracemalloc
        tracemalloc.start()
        result = engine.search(state)
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # 峰值内存不应超过 500MB
        assert peak < 500 * 1024 * 1024, f"Memory too high: {peak / 1024 / 1024:.0f}MB"
```

### 15.5 测试数据: 预设 GameState 场景

```python
# tests/search/mcts/fixtures/states.py

def create_empty_board_state() -> GameState:
    """空场面, 仅有英雄"""
    ...

def create_simple_trade_state() -> GameState:
    """简单交换: 我方 4/5 vs 对手 3/3"""
    ...

def create_lethal_state() -> GameState:
    """致命局面: 对手 5HP, 我方有冲锋随从"""
    ...

def create_complex_midgame_state() -> GameState:
    """复杂中局: 多随从, 多手牌, 10 法力"""
    ...

def create_late_game_state() -> GameState:
    """后期: 大场面, 高法力, 多手牌选择"""
    ...

def create_hidden_info_state() -> GameState:
    """隐藏信息测试: 对手有多张手牌和奥秘"""
    ...
```

## 十六、性能优化

### 16.1 Python 性能瓶颈分析

基于项目现有代码的性能特征:

| 操作 | 耗时 | 频率/MCTS迭代 | 瓶颈程度 |
|------|------|-------------|---------|
| `GameState.copy()` | ~0.1-0.5ms | 1次 (展开时) | ★★★ 高 |
| `enumerate_legal_actions()` | ~0.05-0.2ms | 1-2次 (展开+UCT) | ★★☆ 中 |
| `apply_action()` | ~0.2-1.0ms | 1次 (展开时) | ★★★ 高 |
| `evaluate_delta()` | ~0.1-0.3ms | 1次 (评估截断) | ★★☆ 中 |
| `compute_state_hash()` | ~0.01-0.05ms | 1次 (展开时) | ★☆☆ 低 |
| **单次迭代总计** | **~0.5-2.0ms** | — | — |

**对比**: C++ 实现 (peter1591) 单次迭代 ~0.01ms，Python 慢 ~50-200x。

### 16.2 评估截断 vs 完整模拟耗时对比

| 策略 | 单次评估/模拟耗时 | 5秒内迭代次数 | 搜索质量 |
|------|-----------------|-------------|---------|
| 评估截断 (推荐) | ~1ms | ~5000 | 中-高 (依赖评估函数) |
| 短 Rollout (1步) | ~3ms | ~1600 | 高 |
| 完整 Rollout (3回合) | ~30-100ms | ~50-170 | 高 (但迭代太少) |

### 16.3 状态复制优化

```python
# 优化方案 1: 浅拷贝 + 延迟深拷贝
class LazyGameState:
    """延迟复制的游戏状态包装器"""
    def __init__(self, original: GameState):
        self._original = original
        self._copy = None
    
    def get(self) -> GameState:
        if self._copy is None:
            self._copy = self._original.copy()
        return self._copy
    
    @property
    def is_copied(self) -> bool:
        return self._copy is not None

# 优化方案 2: 仅在需要修改时复制 (Copy-on-Write)
# apply_action 已经返回新副本，无需额外优化
```

### 16.4 动作枚举缓存

```python
class ActionCache:
    """动作枚举缓存: state_hash → legal_actions"""
    def __init__(self, max_size: int = 1000):
        self._cache: Dict[int, List[Action]] = {}
        self._max_size = max_size
    
    def get_or_compute(self, state_hash: int, state: GameState) -> List[Action]:
        if state_hash in self._cache:
            return self._cache[state_hash]
        
        actions = enumerate_legal_actions(state)
        
        if len(self._cache) >= self._max_size:
            self._cache.clear()  # 简单淘汰
        self._cache[state_hash] = actions
        
        return actions
```

### 16.5 可选: C 扩展 / Cython 加速点

如果 Python 性能不够，以下是最值得用 C/Cython 重写的热点:

| 热点 | 加速预期 | 优先级 |
|------|---------|--------|
| `GameState.copy()` | 5-10x | P1 (最高) |
| `apply_action()` | 5-10x | P1 |
| `enumerate_legal_actions()` | 3-5x | P2 |
| `compute_state_hash()` | 3-5x | P3 |

### 16.6 内存优化

```python
# 节点池: 预分配节点, 避免频繁 GC
class NodePool:
    """节点对象池"""
    def __init__(self, initial_size: int = 10000):
        self._pool: List[MCTSNode] = []
        self._index = 0
        for _ in range(initial_size):
            self._pool.append(MCTSNode(node_id=0, state_hash=0))
    
    def acquire(self, **kwargs) -> MCTSNode:
        if self._index < len(self._pool):
            node = self._pool[self._index]
            # 重置并设置字段
            node.__init__(**kwargs)
            self._index += 1
            return node
        else:
            node = MCTSNode(**kwargs)
            self._pool.append(node)
            self._index += 1
            return node
    
    def release_all(self):
        self._index = 0
```

## 十七、开发路线图

### 17.1 阶段分解

#### P0: 基础 MCTS 骨架 (3-5 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T0.1: 创建 `config.py` — MCTSConfig 数据类 | `mcts/config.py` | 所有参数有默认值和类型注解 |
| T0.2: 创建 `node.py` — MCTSNode + ActionEdge | `mcts/node.py` | q_value、is_leaf 属性正确 |
| T0.3: 创建 `uct.py` — UCB1 选择策略 | `mcts/uct.py` | 单元测试通过 |
| T0.4: 创建 `backprop.py` — 标准反向传播 | `mcts/backprop.py` | 统计更新正确 |
| T0.5: 创建 `simulation.py` — 评估截断 | `mcts/simulation.py` | 归一化到 [-1,1] |
| T0.6: 创建 `expansion.py` — 基本展开 (无PW) | `mcts/expansion.py` | 子节点正确创建 |
| T0.7: 创建 `engine.py` — 基本搜索循环 | `mcts/engine.py` | 能在 5s 内输出动作序列 |
| T0.8: 创建 `__init__.py` — 公开 API | `mcts/__init__.py` | import analysis.search.mcts 可用 |

**P0 交付物**: 能在简单局面下执行 MCTS 搜索并输出动作序列。

#### P1: 确定化层 (2-3 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T1.1: 创建 `determinization.py` — DUCT 采样 | `mcts/determinization.py` | 正确采样对手手牌 |
| T1.2: 集成 BayesianOpponent | `mcts/determinization.py` | 使用贝叶斯模型加权采样 |
| T1.3: 多世界统计聚合 | `mcts/engine.py` | 多世界共享树，统计正确聚合 |
| T1.4: 测试 | `tests/search/mcts/test_determinization.py` | 单元测试通过 |

**P1 交付物**: DUCT 完整工作，能处理不完全信息。

#### P2: 动作剪枝 (2-3 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T2.1: 创建 `pruning.py` — 类别动作过滤 | `mcts/pruning.py` | 自伤/浪费动作被过滤 |
| T2.2: 实现必要动作 | `mcts/pruning.py` | 无条件有利动作优先 |
| T2.3: 集成到展开和模拟阶段 | `mcts/expansion.py`, `simulation.py` | 剪枝率 30%+ |
| T2.4: 测试 | `tests/search/mcts/test_pruning.py` | 单元测试通过 |

**P2 交付物**: 动作空间减少 30-50%，搜索效率显著提升。

#### P3: 渐进展开 (1-2 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T3.1: 实现 Progressive Widening | `mcts/expansion.py` | k = floor(C * n^α) 正确 |
| T3.2: 测试 | `tests/search/mcts/test_expansion.py` | 子节点数随访问次数增长 |

#### P4: 转置表 + 树重用 (2-3 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T4.1: 创建 `transposition.py` | `mcts/transposition.py` | 哈希查找正确 |
| T4.2: 集成到展开阶段 | `mcts/expansion.py` | 相同状态共享节点 |
| T4.3: 树重用 (动作后保留子树) | `mcts/engine.py` | 连续搜索间复用统计 |
| T4.4: 测试 | `tests/search/mcts/test_transposition.py` | 命中率 > 0 |

#### P5: 管线集成 (2-3 天)

| 任务 | 文件 | 验收标准 |
|------|------|---------|
| T5.1: SearchResult 格式兼容 | `mcts/engine.py` | 与 RHEA 输出格式一致 |
| T5.2: SearchPipeline 集成 | `search/engine/pipeline.py` | Lethal → MCTS → Risk 管线可用 |
| T5.3: DecisionLoop 配置切换 | `watcher/decision_loop.py` | cfg 切换 RHEA/MCTS |
| T5.4: 集成测试 | `tests/search/mcts/test_engine.py` | 端到端搜索流程通过 |

#### P6: 参数调优 (3-5 天)

| 任务 | 方法 | 验收标准 |
|------|------|---------|
| T6.1: UCT 常数 c 调优 | 网格搜索 | 找到最优 c |
| T6.2: numWorlds 调优 | 网格搜索 | 找到最优世界数 |
| T6.3: 时间分配调优 | A/B 测试 | 确定最优 γ |
| T6.4: 阶段自适应验证 | 对比测试 | 自适应 > 固定参数 |

#### P7: 对比验证 (3-5 天)

| 任务 | 方法 | 验收标准 |
|------|------|---------|
| T7.1: MCTS vs RHEA 胜率 | 50+ 局对战 | MCTS ≥ 45% 胜率 |
| T7.2: 性能基准 | 性能测试 | ≥ 200 迭代/秒 |
| T7.3: 内存基准 | 内存测试 | < 500MB 峰值 |

### 17.2 依赖关系

```
P0 (基础骨架)
 ├──→ P1 (确定化)
 ├──→ P2 (剪枝)
 │    └──→ P3 (渐进展开)
 ├──→ P4 (转置表)
 │    └──→ P5 (管线集成)
 │         └──→ P6 (参数调优)
 │              └──→ P7 (对比验证)
 └────────────────────────────────→ P7
```

P1-P4 可并行开发 (P0 之后)。P5 依赖 P1-P4 完成。P6-P7 串行。

### 17.3 里程碑

| 里程碑 | 包含阶段 | 预计时间 | 交付物 |
|--------|---------|---------|--------|
| M1: MVP | P0 | 5 天 | 基本 MCTS 搜索 (完美信息) |
| M2: 不完全信息 | P0+P1 | 8 天 | DUCT 搜索 |
| M3: 优化版 | P0-P4 | 15 天 | 完整 MCTS + 剪枝 + 转置表 |
| M4: 集成版 | P0-P5 | 18 天 | 集成到决策管线 |
| M5: 正式版 | P0-P7 | 26 天 | 调优完成 + 对比验证 |

## 十八、附录

### 18.1 参考文献

1. **Kocsis & Szepesvári (2006)**. "Bandit based Monte-Carlo Planning." ECML. — UCT 算法原始论文
2. **Choe & Kim (2020)**. "Enhancing Monte Carlo Tree Search for Playing Hearthstone." IEEE CoG. [S1] — DAG+UCD、稀疏采样+阻尼采样
3. **Świechowski & Tajmajer (2021)**. "A Practical Solution to Handling Randomness and Imperfect Information in MCTS." FedCSIS. [S2] — 双接口设计、多层转置表
4. **Zhang (2017)**. "Improving CCG AI with Heuristic Search and ML." MSc Thesis, UAlberta. [S3] — DUCT、CNB、策略网络
5. **Zhang & Buro (2017)**. "Improving Hearthstone AI by Learning High-Level Rollout Policies." IEEE CIG. [S4]
6. **Santos et al. (2017)**. "Monte Carlo tree search experiments in Hearthstone." IEEE CIG. [S5]
7. **Świechowski et al. (2018)**. "Improving Hearthstone AI by Combining MCTS and SL." IEEE CIG. [S6]
8. **Couëtoux et al. (2011)**. "Continuous Upper Confidence Trees." LION. — 渐进展开 (Progressive Widening) 原始论文
9. **Saffidine et al. (2012)**. "UCD: Upper Confidence Bound for Rooted Directed Acyclic Graphs." KBS. — UCD 算法
10. **Cowling et al. (2012)**. "Information Set Monte Carlo Tree Search." IEEE TCIAIG. — ISMCTS 原始论文

### 18.2 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| MCTS | Monte Carlo Tree Search | 蒙特卡洛树搜索 |
| UCT | Upper Confidence Bound for Trees | 树的上置信界算法 |
| UCB1 | Upper Confidence Bound 1 | 多臂赌博机算法中的选择策略 |
| DUCT | Determinized UCT | 确定化 UCT，处理不完全信息 |
| ISMCTS | Information Set MCTS | 信息集 MCTS |
| DAG | Directed Acyclic Graph | 有向无环图 |
| UCD | Upper Confidence bound for DAG | DAG 上的上置信界 |
| PW / DPW | (Double) Progressive Widening | (双重) 渐进展开 |
| CNB | Chance Node Bucketing | 机会节点分桶 |
| AMAF | All Moves As First | 所有动作视为首次 |
| RAVE | Rapid Action Value Estimation | 快速动作价值估计 |
| IS-state | Information Set State | 信息集状态 (玩家可见信息) |
| GS-state | Game Simulation State | 游戏模拟状态 (完整信息) |
| Rollout | / | 从叶节点到终止的模拟过程 |
| Eval Cutoff | Evaluation Cutoff | 评估截断: 用评估函数替代 rollout |
| RHEA | Rolling Horizon Evolutionary Algorithm | 滚动视野进化算法 |

### 18.3 UCT 公式推导

UCT 基于多臂赌博机问题中的 UCB1 公式。核心思想是在探索 (尝试未充分测试的动作) 和利用 (选择当前最优动作) 间取得平衡。

**UCB1 公式**:
```
UCB1(a) = Q(a) + c * sqrt(ln(N) / n(a))
```

**理论保证** [Kocsis & Szepesvári, 2006]:
- 当 c = sqrt(2) 时, UCB1 在 K 臂赌博机上的 regret 为 O(sqrt(K * N * ln(N)))
- UCT 将此保证扩展到树搜索: 随迭代次数增加, 每个节点的值估计收敛到真实值
- 收敛速率: O(1/sqrt(n)) (Hoeffding 不等式)

**炉石中的调整**:
- 标准 c = sqrt(2) ≈ 1.414 在炉石中偏大 (动作空间太大导致过度探索)
- 实践中 c = 0.25-1.0 效果更好 [S1][S3]
- 因为炉石评估函数已有较强信号, 不需要过多探索

### 18.4 渐进展开收敛性说明

渐进展开 [Couëtoux et al., 2011] 的收敛条件:
- α < 1 时: 保证所有动作最终被展开 (当 n → ∞ 时 k → ∞)
- α = 0.5 时: 展开速率适中, 是常用选择
- 当 C * n^α > |legal_actions| 时: 退化为标准 MCTS (展开所有动作)

在炉石场景下, α = 0.5 意味着:
- 前 100 次访问: 最多展开 10 个子动作
- 前 1000 次访问: 最多展开 ~32 个子动作
- 实际合法动作通常 10-50 个, 1000 次访问后基本覆盖

### 18.5 与 RHEA 的详细对比分析

| 维度 | RHEA (现有) | MCTS/UCT (新增) |
|------|------------|-----------------|
| **搜索范式** | 进化算法 (种群优化) | 统计搜索 (树构建) |
| **全局覆盖** | 依赖种群多样性 | UCT 保证渐近覆盖 |
| **理论收敛** | 无保证 | UCT 有 Hoeffding 收敛保证 |
| **不完全信息** | 无内置支持 | DUCT 原生支持 |
| **动作序列** | 染色体 = 完整序列 | 逐步搜索 + 序列拼接 |
| **评估次数** | pop×gens = 30×100 = 3000 | iterations = ~3000 (5s) |
| **状态复制** | 每次评估 1 次 | 每次展开 1 次 |
| **内存** | O(pop × chrom_len) | O(tree_nodes) ≈ O(iterations) |
| **时间管理** | 固定世代数 | 迭代至时间用尽 |
| **可解释性** | 染色体 = 动作序列 | 树结构可分析 |
| **并行化** | 种群评估可并行 | 树并行 / 根并行 |
| **参数敏感性** | pop, gens, mut_rate | c, numWorlds, PW params |
| **Python 适配** | 中等 (染色体长度短) | 好 (评估截断减少计算) |

**结论**: MCTS 在理论保证和不完全信息处理上优于 RHEA，但最终胜率取决于实现质量和参数调优。建议先实现 MCTS 作为 RHEA 的替代选项，通过 A/B 测试确定最终使用哪个引擎。

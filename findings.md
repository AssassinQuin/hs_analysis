# Findings: MCTS World Tracker

## 现有基础架构

### Log Ingestion Pipeline
- `analysis/watcher/game_tracker.py` — `GameTracker.feed_line(line)` 逐行解析 Power.log
- `analysis/watcher/state_bridge.py` — `StateBridge.convert()` → GameState
- `analysis/watcher/packet_replayer.py` — 完整离线 replay (2181 行)

### v2 Game Engine
- `analysis/card/engine/state.py` — `GameState`, `Minion`, `HeroState`, `ManaState`, `OpponentState`
- `analysis/card/engine/rules.py` — `enumerate_legal(state)` → `List[Action]`
- `analysis/card/engine/simulation.py` — `apply_action(state, action)` → `GameState`
- `analysis/card/abilities/definition.py` — `Action`, `ActionKind` (PLAY, ATTACK, HERO_POWER, END_TURN, etc.)

### 现存 MCTS 相关
- `analysis/engine/opponent_hand_mcts.py` — **Inverse MCTS** (手牌推断), 非 action-space MCTS
- `analysis/engine/world_model.py` — 贝叶斯 LR 证据系统
- `analysis/engine/powerlog_game_state_builder.py` — 实体缓存 → GameState

### 缺失组件 (需要新建)
- Action-space MCTS/UCT (v1 已删除)
- Particle filter / world tracking
- Observation matching
- World tracker orchestrator

## MCTS UCT 设计

### 核心算法
- Selection: UCB1 `Q(s,a) + c * sqrt(ln(N(s)) / N(s,a))`
- Expansion: 首次到达节点时展开所有合法动作
- Simulation: 随机 rollout (depth-limited)
- Backpropagation: 沿路径更新 visit_count + total_reward

### 关键参数
- `exploration_constant = 1.414` (标准 UCB1)
- `iterations = 500-2000` (根据 time_budget 调整)
- `rollout_depth = 20`
- `time_budget_ms = 1000`

## 粒子滤波器设计

### 世界 (World) 结构
```python
@dataclass
class World:
    world_id: str
    game_state: GameState
    weight: float
    parent_world_id: Optional[str]
    depth: int
    action_history: List[Action]
    matched_observations: List[ObservedEvent]
    predicted_branches: List[World]
    metadata: Dict
```

### 观察匹配维度
1. 动作类型匹配 (played / attacked / passed)
2. 卡牌 ID 匹配
3. 目标选择匹配
4. 消耗资源匹配 (mana / corpses)
5. 盘面状态匹配 (board state delta)

## Output 格式

每回合输出:
```
┌─ World Tracker Report ──────────────────────────┐
│ Turn 5 | Confidence: 0.72 | Entropy: 1.83      │
│                                                  │
│ Top Worlds:                                      │
│   W01: 38% | [Mage, Frost] | HP:22 | Board:3   │
│   W02: 24% | [Mage, Secret]| HP:18 | Board:4   │
│   W03: 15% | [Mage, Big]   | HP:25 | Board:2   │
│   ─── 5 more worlds (23%) ─────                │
│                                                  │
│ Predicted Opponent Actions:                      │
│   Play Frostbolt (65%) → face                   │
│   Attack with minion (52%) → our minion #2      │
│   Play Secret (30%)                             │
│                                                  │
│ World Evolution:                                 │
│   W01 ↑ 12% (matched "play spell")              │
│   W02 ↓ 8%  (didn't play secret)                │
│   W03 - (no relevant observation)                │
└──────────────────────────────────────────────────┘
```

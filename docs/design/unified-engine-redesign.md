# 统一引擎激进重构设计

> 日期: 2026-04-26
> 状态: Draft
> 替代: P7-P11, Q1-Q4, refactoring-architecture-plan.md
> 前置文档: declarative-card-effect-json-design.md, merge-analysis.md

---

## 目录

1. [问题诊断总结](#1-问题诊断总结)
2. [目标架构：统一模拟引擎](#2-目标架构统一模拟引擎)
3. [模拟引擎重写：核心修正](#3-模拟引擎重写核心修正)
4. [文件变更清单](#4-文件变更清单)
5. [实施路线图](#5-实施路线图)

---

## 1. 问题诊断总结

### 1.1 问题全览

对 `analysis/search/` 全部核心文件逐行审查，发现 **17 个结构性问题**，按严重度分级：

| # | 严重度 | 问题 | 文件 | 对 MCTS 的影响 |
|---|--------|------|------|----------------|
| 1 | **P0** | executor 7种效果为空壳 stub | executor.py L175-196 | 变形/移回/精神控制/进化卡牌被系统性低估 |
| 2 | **P0** | 随机目标 `random.randint()` 破坏确定性 | executor.py L743-758 | 同一节点 Q-value 不收敛，搜索质量退化 |
| 3 | **P0** | 死亡处理无"死亡阶段"语义 | simulation.py L636-644 | 亡语链失真，贪板评估错误 |
| 4 | P1 | Aura 引擎仅 10 张硬编码 | aura_engine.py L21-85 | 50+ 光环卡效果被忽略 |
| 5 | P1 | 抽牌系统是 stub（空占位 Card） | simulation.py L810-835 | 搜索树深度被限制，后续分支退化为噪声 |
| 6 | P1 | 复生错误移除嘲讽 | simulation.py L592-603 | 嘲讽复生随从防御价值被低估 |
| 7 | P1 | 模拟层无嘲讽验证 | simulation.py, executor.py | 可能探索到非法动作（打脸穿过嘲讽） |
| 8 | P1 | 秘密系统仅 12 个且多为 TODO | secret_triggers.py | 对手秘密触发效果不可预测 |
| 9 | P1 | Discover `random.sample` 不可复现 | discover.py L315 | 发现卡牌估值波动 |
| 10 | P2 | MechanicsState/ZoneManager 定义了未用 | mechanics_state.py, zone_manager.py | 维护负担，新开发者可能双写 |
| 11 | **P1** | 13/15 个 mechanic 模块双路径（executor + 直接变异） | 全部 mechanic 模块 | 双重触发或遗漏，reward 不可靠 |
| 12 | **P1** | orchestrator 目标选择 N 次 `state.copy()` | orchestrator.py L229-289 | 每次展开 24-40 次深拷贝，MCTS 性能瓶颈 |
| 13 | P2 | `GameState.copy()` 缺字段 | game_state.py L406-481 | 复活/抽牌触发/法术连击估值不准 |
| 14 | P2 | DecisionPipeline ~1500 行死代码 | engine/pipeline.py + factors/ | 认知负担 |
| 15 | P2 | 英雄技能硬编码 IMBUE_HERO_POWERS | imbue.py L15-83 | 英雄牌后技能效果不符实际 |
| 16 | P2 | 战吼加倍器检测不完整 | orchestrator.py L292-315 | 有铜须时部分战吼未加倍 |
| 17 | P1 | 对手回合模拟完全缺失 | opponent_simulator.py | MCTS 退化为单回合贪心 |

### 1.2 核心结论

模拟引擎是"能跑但不可靠"的原型。三个根因：

1. **双路径执行** — 13 个 mechanic 模块既有 executor 路径又有直接变异路径，效果可能双重触发或遗漏
2. **随机性未确定性化** — MCTS 要求同一状态同一动作产出确定结果，当前 5+ 处使用 `random.*`
3. **核心规则缺失** — 死亡阶段语义、抽牌系统、7 种效果 stub、嘲讽验证均不符合炉石规则

### 1.3 死代码清单

| 文件/目录 | 行数 | 原因 |
|-----------|------|------|
| `engine/pipeline.py` | 199 | engine_adapter 仅注册 mcts |
| `engine/strategic.py` | ~200 | pipeline 死代码的依赖 |
| `engine/tactical.py` | ~300 | 同上 |
| `engine/unified_tactical.py` | ~200 | 同上 |
| `engine/turn_plan.py` | ~150 | 同上 |
| `engine/attack_planner.py` | ~200 | 同上 |
| `engine/action_pruner.py` | ~150 | 同上 |
| `engine/factors/` (7个文件) | ~700 | 同上 |
| `mechanics_state.py` | 210 | 定义了未被使用 |
| `zone_manager.py` | 60 | 定义了未被使用 |
| `entity.py` | ~80 | 定义了未被使用 |
| **合计** | **~2,449** | |

## 2. 目标架构：统一模拟引擎

### 2.1 设计原则

1. **单一执行路径** — 所有效果必须经由 `Engine.dispatch()` → `EffectHandler`，禁止直接变异 GameState
2. **确定性优先** — 所有效果执行结果由 `(state_hash, action)` 唯一确定，零 `random.*` 调用
3. **声明式卡牌** — 能力来自 JSON 数据而非运行时解析，卡牌为纯数据载体
4. **分层职责** — Engine(规则) / State(数据) / Abilities(声明) / MCTS(搜索) 各层独立可测

### 2.2 目标目录结构

```
analysis/
├── data/                          # 数据层（保持）
│   ├── card_data.py               # CardDB — 统一卡牌数据库
│   ├── card_effects.py            # → Phase 1 删除，由 JSON 替代
│   ├── token_cards.py             # Token 数据
│   └── fetch_hsreplay.py          # HSReplay 数据拉取
│
├── models/                        # 模型层（保持）
│   ├── __init__.py                # + 合并 phase.py
│   └── card.py                    # Card 数据类（abilities 改为预填充）
│
├── engine/                        # ★ 统一模拟引擎（新顶层包）
│   ├── __init__.py
│   ├── state.py                   # GameState — 唯一游戏状态容器
│   │   ├── HeroState, ManaState, Minion, OpponentState
│   │   ├── DeathQueue — 标准死亡阶段
│   │   ├── MechanicsState — 统一机制状态
│   │   └── .copy() — 完整深拷贝（含所有字段）
│   │
│   ├── rules.py                   # ★ 规则引擎（新）
│   │   ├── validate_action()      # 嘲讽/费用/合法性验证
│   │   ├── enumerate_legal()      # 合法动作枚举（从 abilities/enumeration.py 迁入）
│   │   └── check_game_over()      # 终局判定
│   │
│   ├── dispatch.py                # ★ 效果分发表（新，替代 executor if-chain）
│   │   ├── EFFECT_HANDLERS: Dict[EffectKind, Callable]
│   │   ├── register_handler()     # 注册效果处理器
│   │   ├── dispatch(state, effect, target) → GameState
│   │   └── dispatch_batch()       # 批量执行效果列表
│   │
│   ├── executor.py                # 效果执行器（重写 executor.py）
│   │   ├── damage(state, amount, target, ...)
│   │   ├── summon(state, card_id, position, ...)
│   │   ├── draw_cards(state, count, from_deck=)
│   │   ├── heal(state, amount, target)
│   │   ├── buff(state, atk, hp, keywords, target)
│   │   ├── destroy(state, target)
│   │   ├── transform(state, target, into_card_id)
│   │   ├── silence(state, target)
│   │   ├── freeze(state, target)
│   │   ├── take_control(state, target)
│   │   ├── return_to_hand(state, target)
│   │   ├── copy_entity(state, target)
│   │   ├── shuffle_into_deck(state, card_ids)
│   │   ├── swap(state, target_a, target_b)
│   │   ├── discover(state, pool, count=3)
│   │   ├── enchant(state, target, enchantment)
│   │   ├── equip_weapon(state, card_id)
│   │   ├── gain_armor(state, amount)
│   │   ├── reduce_cost(state, amount, filter=)
│   │   └── discard(state, count)
│   │
│   ├── simulation.py              # 状态转移（重写 abilities/simulation.py）
│   │   ├── apply_action(state, action) → GameState  # 唯一入口
│   │   ├── _play_card()
│   │   ├── _attack()
│   │   ├── _hero_power()
│   │   ├── _end_turn()
│   │   ├── _activate_location()
│   │   └── _resolve_deaths()      # ★ 标准死亡阶段（收集→同步击杀→亡语→再检查）
│   │
│   ├── aura.py                    # 光环引擎（重写 aura_engine.py）
│   │   ├── AuraRegistry — 从能力系统注册光环
│   │   ├── apply_auras(state)     # 重算所有光环
│   │   └── invalidate(state)      # 标记脏数据
│   │
│   ├── trigger.py                 # 触发器系统（重写 trigger_system.py）
│   │   ├── EventDispatcher        # 事件总线
│   │   ├── emit(state, event)     # 发射事件
│   │   └── Event types: ON_PLAY, ON_DEATH, ON_ATTACK, ON_DAMAGE, ON_TURN_START, ...
│   │
│   ├── target.py                  # 目标解析（从 orchestrator 分离）
│   │   ├── resolve_target(state, spec, fallback)
│   │   ├── validate_target(state, action) — 嘲讽/潜行/免疫
│   │   └── best_target(state, effect) — 确定性启发式选择（无 copy-eval）
│   │
│   ├── mechanics/                 # ★ 机制子包（mechanic 模块统一收编）
│   │   ├── __init__.py
│   │   ├── deathrattle.py         # 亡语队列（保留核心逻辑）
│   │   ├── discover.py            # 发现（确定性 top-K 采样）
│   │   ├── dormant.py             # 休眠
│   │   ├── location.py            # 地标
│   │   ├── quest.py               # 任务
│   │   ├── secret.py              # 秘密（扩展到完整）
│   │   ├── choose_one.py          # 抢一
│   │   ├── shatter.py             # 裂变
│   │   └── _data.py               # 共享数据表（herald_soldiers, colossal_appendages 等）
│   │
│   └── deterministic.py           # ★ 确定性化工具（新）
│       ├── DeterministicRNG       # 基于 state_hash 的伪随机
│       ├── det_choice(seq, seed)  # 确定性选择
│       ├── det_sample(pool, k, seed)  # 确定性采样
│       └── expected_value_expand(state, random_effect)  # 期望值展开
│
├── abilities/                     # ★ 能力系统（提升为顶层包，从 search/abilities/ 迁出）
│   ├── __init__.py
│   ├── definition.py              # 核心类型（+ 合并 actions.py）
│   │   ├── AbilityTrigger, EffectKind, ConditionKind, TargetKind
│   │   ├── EffectSpec, CardAbility, ConditionSpec, TargetSpec
│   │   ├── LazyValue → ValueExpr  # 重命名为值表达式
│   │   ├── Action, ActionType     # 从 actions.py 合并
│   │   └── CardAbility JSON 序列化/反序列化
│   ├── loader.py                  # ★ JSON 能力加载器（新，替代 parser.py）
│   │   ├── load_abilities(card_id) → List[CardAbility]
│   │   └── _registry: Dict[str, List[CardAbility]]
│   └── value_expr.py              # 值表达式求值器（新）
│       ├── resolve(expr, state, source) → int
│       ├── $attr, $count, $add, $mul, $if, $ref
│       └── to_json() / from_json()
│
├── search/                        # 搜索层（精简）
│   ├── __init__.py
│   ├── mcts/                      # MCTS 引擎（保持结构）
│   │   ├── engine.py              # MCTSEngine
│   │   ├── node.py                # MCTSNode
│   │   ├── uct.py                 # UCB1 选择
│   │   ├── expansion.py           # 节点扩展
│   │   ├── simulation.py          # 叶节点评估
│   │   ├── backprop.py            # 反向传播
│   │   ├── determinization.py     # DUCT
│   │   ├── transposition.py       # 转置表
│   │   ├── pruning.py             # 剪枝
│   │   ├── turn_advance.py        # 跨回合模拟
│   │   └── config.py              # 配置
│   ├── opponent.py                # 对手模拟（重命名 opponent_simulator.py）
│   ├── lethal.py                  # 致命检测（重命名 lethal_checker.py）
│   ├── risk.py                    # 风险评估（重命名 risk_assessor.py）
│   └── adapter.py                 # 搜索引擎适配器（重命名 engine_adapter.py）
│
├── scorers/                       # 评分层（保持）
├── evaluators/                    # 评估层（保持）
├── watcher/                       # 集成层（保持，不重构）
└── utils/                         # 工具层（保持）
```

### 2.3 核心数据流

```
Power.log
  │
  ▼
StateBridge.convert() ─── GameState
  │                          │
  │                    rules.enumerate_legal()
  │                          │
  │                    List[Action]
  │                          │
  ▼                          ▼
MCTSEngine.search(state) ─── apply_action(state, action)
  │                          │
  │                          ├── dispatch(effect)  ←─ engine/dispatch.py
  │                          │     │
  │                          │     └── executor.*()  ←─ engine/executor.py
  │                          │           │
  │                          │           └── target.resolve()  ←─ engine/target.py
  │                          │
  │                          ├── trigger.emit(ON_DAMAGE)
  │                          │     └── dispatch(triggered_effect)
  │                          │
  │                          └── _resolve_deaths()  ←─ 标准死亡阶段
  │                                ├── 收集 health ≤ 0
  │                                ├── 同步击杀
  │                                ├── deathrattle.resolve()
  │                                └── 再检查
  │
  ▼
SearchResult(best_sequence: List[Action])
```

### 2.4 效果执行唯一路径

**Before（当前）：**
```
simulation.apply_action()
  ├── orchestrator.orchestrate()     # 路径 A
  │     └── executor._execute_single()
  │           └── if-chain → _exec_damage()
  ├── kindred.apply_kindred()        # 路径 B（直接变异）
  ├── colossal.summon_appendages()   # 路径 B
  ├── herald.apply_herald()          # 路径 B
  ├── choose_one.resolve()           # 路径 B
  └── dormant.apply()               # 路径 B
```

**After（统一）：**
```
simulation.apply_action()
  └── engine.dispatch_batch(ability.effects)
        └── for effect in effects:
              dispatch(effect)
                ├── EFFECT_HANDLERS[effect.kind](state, effect, target)
                └── target = target.resolve(effect.target)
```

所有 mechanic 数据（herald_soldiers, colossal_appendages 等）存放在 `mechanics/_data.py`，
处理器注册在 `dispatch.py` 的分发表中。没有第二条代码路径。

### 2.5 确定性化策略

| 场景 | 当前 | 目标 |
|------|------|------|
| 随机目标伤害 | `random.randint()` | `DeterministicRNG.choice(state_hash, candidates)` — 固定 seed per state |
| 随机发现 | `random.sample(pool, 3)` | `det_top_k(pool, k=3, score_fn)` — 按 score 排序取 top-K |
| 随机抽牌 | 无（stub） | 从 `deck_list` 确定性取顶（MCTS 多世界各自采样） |
| 乱斗等完全随机 | 不处理 | 期望值展开：对所有结果取加权平均 |
| 重采样（DUCT 多世界） | `random.sample` 填充对手手牌 | `DeterministicRNG` per world_id |

## 3. 模拟引擎重写：核心修正

### 3.1 标准死亡阶段（修正问题 #3）

**炉石规则（严格顺序）：**
1. **收集** — 快照所有 health ≤ 0 的随从（友方+敌方混合）
2. **同步击杀** — 所有被标记随从同时从场上移除
3. **按全局出场顺序**结算亡语
4. **再检查** — 新产生的死亡随从，重复 1-3 直到无新死亡

**新实现（engine/simulation.py `_resolve_deaths`）：**

```python
def _resolve_deaths(state: GameState) -> GameState:
    """标准死亡阶段 — 收集→击杀→亡语→再检查"""
    max_iterations = 10  # 防止无限循环
    for _ in range(max_iterations):
        # Step 1: 收集所有待死亡随从（快照）
        dead_friendly = [(i, m) for i, m in enumerate(state.board) if m.health <= 0]
        dead_enemy = [(i, m) for i, m in enumerate(state.opponent.board) if m.health <= 0]

        if not dead_friendly and not dead_enemy:
            break

        # Step 2: 按全局出场顺序合并（field_index 作为出场顺序代理）
        all_dead = [(m, 'friendly', i) for i, m in dead_friendly] + \
                   [(m, 'enemy', i) for i, m in dead_enemy]
        all_dead.sort(key=lambda x: x[0].field_index)  # 出场顺序

        # Step 3: 同步击杀 — 从场上移除
        dead_ids = {id(m) for m, _, _ in all_dead}
        state.board = [m for m in state.board if id(m) not in dead_ids]
        state.opponent.board = [m for m in state.opponent.board if id(m) not in dead_ids]

        # Step 4: 按顺序结算亡语
        for minion, side, _ in all_dead:
            if minion.abilities:
                for ability in minion.abilities:
                    if ability.trigger == AbilityTrigger.DEATHRATTLE:
                        state = dispatch_batch(state, ability.effects, source=minion)

            # 复生处理
            if minion.has_reborn:
                reborn = minion.copy()
                reborn.health = 1
                reborn.has_reborn = False
                # 保留嘲讽、圣盾等关键词（修正问题 #6）
                if side == 'friendly':
                    state.board.append(reborn)
                else:
                    state.opponent.board.append(reborn)

        # Step 5: 更新光环（死亡可能移除光环源）
        state = apply_auras(state)

    return state
```

**关键变化：**
- 友方+敌方混合收集，按全局出场顺序结算（之前分开处理）
- 亡语在击杀后结算（之前在击杀前移除导致引用丢失）
- 复生保留所有关键词（之前错误移除嘲讽）
- 最多 10 次循环防止无限递归

### 3.2 确定性化（修正问题 #2, #9）

**DeterministicRNG 设计：**

```python
class DeterministicRNG:
    """基于状态哈希的确定性伪随机数生成器"""

    def __init__(self, seed: int):
        self._state = seed

    def _next(self) -> int:
        """xorshift32"""
        self._state ^= (self._state << 13) & 0xFFFFFFFF
        self._state ^= (self._state >> 17)
        self._state ^= (self._state << 5) & 0xFFFFFFFF
        return self._state

    def choice(self, seq: list) -> Any:
        if len(seq) == 1:
            return seq[0]
        idx = self._next() % len(seq)
        return seq[idx]

    def sample(self, seq: list, k: int) -> list:
        """确定性采样 — Fisher-Yates 变体"""
        pool = list(seq)
        result = []
        for _ in range(min(k, len(pool))):
            idx = self._next() % len(pool)
            result.append(pool.pop(idx))
        return result

    @staticmethod
    def from_state(state: GameState) -> 'DeterministicRNG':
        """从游戏状态创建确定性 RNG"""
        seed = hash((
            state.turn,
            tuple(m.card_id for m in state.board),
            tuple(m.card_id for m in state.opponent.board),
            state.hero.hp,
            state.opponent.hero.hp,
        )) & 0xFFFFFFFF
        return DeterministicRNG(seed)
```

**Discover 确定性化：**

```python
def discover_cards(state: GameState, pool: List[str], count: int = 3) -> List[str]:
    """确定性发现 — 按 score 排序取 top-K"""
    scored = [(card_id, _card_score(card_id, state)) for card_id in pool]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [card_id for card_id, _ in scored[:count]]
```

### 3.3 效果分发表（修正问题 #1, #11）

**替代 executor.py 的 if-chain：**

```python
# engine/dispatch.py

EffectHandler = Callable[[GameState, EffectSpec, Any], GameState]

EFFECT_HANDLERS: Dict[EffectKind, EffectHandler] = {}

def register_handler(kind: EffectKind):
    """效果处理器注册装饰器"""
    def decorator(fn: EffectHandler):
        EFFECT_HANDLERS[kind] = fn
        return fn
    return decorator

def dispatch(state: GameState, effect: EffectSpec, target=None) -> GameState:
    """单效果分派"""
    handler = EFFECT_HANDLERS.get(effect.kind)
    if handler is None:
        return state  # 未注册的效果静默跳过（可加 log warning）
    return handler(state, effect, target)

def dispatch_batch(state: GameState, effects: List[EffectSpec],
                   source=None, target=None) -> GameState:
    """批量效果分派"""
    for effect in effects:
        resolved_target = target or resolve_target(state, effect, source)
        state = dispatch(state, effect, resolved_target)
    return state
```

**处理器注册示例：**

```python
@register_handler(EffectKind.DAMAGE)
def _handle_damage(state: GameState, effect: EffectSpec, target) -> GameState:
    return executor.damage(state, amount=effect.value, target=target,
                           spell_power=effect.keyword == "SPELLPOWER")

@register_handler(EffectKind.SUMMON)
def _handle_summon(state: GameState, effect: EffectSpec, target) -> GameState:
    return executor.summon(state, card_id=effect.subtype,
                           position=effect.value2 or -1,
                           count=effect.value or 1)

# ... 35 种 EffectKind 全部注册

@register_handler(EffectKind.TRANSFORM)  # ★ 修正 stub
def _handle_transform(state: GameState, effect: EffectSpec, target) -> GameState:
    return executor.transform(state, target=target, into_card_id=effect.subtype)

@register_handler(EffectKind.RETURN)  # ★ 修正 stub
def _handle_return(state: GameState, effect: EffectSpec, target) -> GameState:
    return executor.return_to_hand(state, target=target)

@register_handler(EffectKind.TAKE_CONTROL)  # ★ 修正 stub
def _handle_take_control(state: GameState, effect: EffectSpec, target) -> GameState:
    return executor.take_control(state, target=target)
```

### 3.4 目标选择去 copy-eval（修正问题 #12）

**当前：** 每个候选目标做 `state.copy()` + 模拟 + 评估，8 候选 = 24-40 次深拷贝

**新方案：启发式打分 + 确定性选择（零拷贝）：**

```python
def best_target(state: GameState, effect: EffectSpec) -> Any:
    """确定性目标选择 — 启发式打分，不做 state.copy()"""
    candidates = resolve_candidates(state, effect.target)

    if len(candidates) <= 1:
        return candidates[0] if candidates else None

    # 简单启发式打分（不模拟）
    scored = []
    for c in candidates:
        score = _target_heuristic(state, effect, c)
        scored.append((c, score))

    # 确定性排序选择（无随机）
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[0][0]

def _target_heuristic(state, effect, target) -> float:
    """轻量级目标启发式"""
    if effect.kind == EffectKind.DAMAGE:
        if isinstance(target, Minion):
            # 优先击杀（剩余血最少）、高威胁（攻击高）
            if target.health <= effect.value:
                return 100 + target.attack  # 可击杀优先
            return target.attack - target.health * 0.5
        else:
            # 英雄目标：血量越低越优先
            return (30 - target.hp) * 2
    elif effect.kind == EffectKind.BUFF:
        if isinstance(target, Minion):
            return target.attack + target.health  # 越大越值得 buff
    # ... 其他效果类型
    return 0
```

**性能对比：**
- Before: 每次目标选择 24-40 次 `state.copy()` + 评估
- After: 0 次 `state.copy()`，纯算术启发式
- 预计 MCTS 迭代数提升 **5-10x**

### 3.5 抽牌系统修正（修正问题 #5）

```python
def draw_cards(state: GameState, count: int = 1) -> GameState:
    """从 deck_list 抽牌"""
    for _ in range(count):
        if state.deck_remaining <= 0:
            # 疲劳伤害
            state.hero.fatigue += 1
            state = damage(state, amount=state.hero.fatigue, target='friendly_hero')
            continue

        if state.deck_list and len(state.deck_list) > 0:
            # 从牌库顶端取实际卡牌
            card_id = state.deck_list.pop(0)
            card = CardDB.get_card(card_id)
            state.hand.append(card)
        else:
            # 无牌库信息时，减少计数
            state.deck_remaining -= 1
            # 创建占位符（但标记为 unknown）
            drawn = Card(card_id=f"drawn_{state.deck_remaining}",
                        name="Unknown", card_type="SPELL")
            state.hand.append(drawn)

        state.cards_drawn_this_turn += 1

    return state
```

### 3.6 GameState.copy() 完整化（修正问题 #13）

```python
def copy(self) -> 'GameState':
    """完整深拷贝 — 含所有字段"""
    new = GameState()
    new.hero = self.hero.copy()
    new.mana = self.mana.copy()
    new.opponent = self.opponent.copy()
    new.board = [m.copy() for m in self.board]
    new.hand = [c.copy() if hasattr(c, 'copy') else c for c in self.hand]
    # ★ 新增字段
    new.deck_list = list(self.deck_list) if self.deck_list else None
    new.deck_remaining = self.deck_remaining
    new.graveyard = [m.copy() for m in self.graveyard]  # ★ 新增
    new.cards_drawn_this_turn = self.cards_drawn_this_turn  # ★ 新增
    new.spells_cast_this_turn = self.spells_cast_this_turn  # ★ 新增
    new.turn = self.turn
    # ... 所有字段逐一拷贝
    new._defer_deaths = False  # 重置管线状态
    new._pending_dead_friendly = []
    new._pending_dead_enemy = []
    return new
```

### 3.7 双路径统一（修正问题 #11）

**当前每个 mechanic 模块有两条路径：**

```python
# 路径 A: executor 路径（新）
executor._exec_herald(state, effect, source)  # 通过 dispatch

# 路径 B: 直接变异（旧）
herald.apply_herald(state, minion)  # 直接修改 state.board, state.herald_count
```

**统一方案：**

| 模块 | 保留（数据+注册） | 删除（直接变异函数） |
|------|-------------------|---------------------|
| herald.py | `HERALD_SOLDIERS` 数据表 | `apply_herald()` |
| kindred.py | `check_kindred_active()` | `apply_kindred_bonus()` |
| colossal.py | `COLOSSAL_APPENDAGES` 数据表 | `summon_colossal_appendages()` |
| corpse.py | `parse_corpse_effect()` | `_apply_corpse_damage()` |
| imbue.py | `IMBUE_DATA` 数据表 | `apply_hero_power()` |
| choose_one.py | `parse_choose_options()` | `resolve_choose_one()` |
| shatter.py | `parse_shatter()` | `apply_shatter()` |
| dormant.py | `DORMANT_DATA` 数据表 | `apply_dormant()` |
| outcast.py | `is_outcast_position()` | `apply_outcast()` |
| corrupt.py | `CORRUPT_MAP` | `apply_corrupt()` |
| rewind.py | `REwind_DATA` | `apply_rewind()` |
| rune.py | `RUNE_MAP` | `check_rune()` |
| dark_gift.py | `DARK_GIFT_MAP` | `apply_dark_gift()` |

所有实际执行逻辑移入 `dispatch.py` 中对应的 handler。mechanic 模块仅保留纯数据表和解析辅助函数。

## 4. 文件变更清单

### 4.1 删除文件（~4,200 行）

| # | 文件 | 行数 | 原因 |
|---|------|------|------|
| 1 | `search/engine/pipeline.py` | 199 | 死代码，engine_adapter 仅注册 mcts |
| 2 | `search/engine/strategic.py` | ~200 | pipeline 依赖 |
| 3 | `search/engine/tactical.py` | ~300 | pipeline 依赖 |
| 4 | `search/engine/unified_tactical.py` | ~200 | pipeline 依赖 |
| 5 | `search/engine/turn_plan.py` | ~150 | pipeline 依赖 |
| 6 | `search/engine/attack_planner.py` | ~200 | pipeline 依赖 |
| 7 | `search/engine/action_pruner.py` | ~150 | pipeline 依赖 |
| 8 | `search/engine/factors/` (7文件) | ~700 | pipeline 依赖 |
| 9 | `search/mechanics_state.py` | 210 | 定义了未使用 |
| 10 | `search/zone_manager.py` | 60 | 定义了未使用 |
| 11 | `search/entity.py` | ~80 | 定义了未使用 |
| 12 | `search/effects.py` | ~200 | 三套并行效果系统之一，由 dispatch.py 统一 |
| 13 | `data/card_effects.py` | 309 | 由 JSON 声明式数据替代 |
| 14 | `data/card_index.py` | 11 | 纯 shim re-export |
| 15 | `data/hsdb.py` | 16 | 纯 shim re-export |
| 16 | `data/card_cleaner.py` | ~150 | 遗留，已由 card_data.py 替代 |
| 17 | `data/card_roles.py` | 104 | 并入 card_effects JSON 或 card_data.py |
| 18 | `search/abilities/parser.py` | 449 | JSON 加载器替代运行时解析 |
| 19 | `search/abilities/extractors.py` | ~200 | parser 依赖，一并删除 |
| 20 | `search/abilities/tokens.py` | ~150 | parser 依赖，一并删除 |
| 21 | `models/phase.py` | 15 | 并入 models/__init__.py |
| | **合计** | **~4,253** | |

### 4.2 合并文件

| # | 源文件 | 目标文件 | 操作 |
|---|--------|----------|------|
| 1 | `abilities/actions.py` (106行) | `abilities/definition.py` | ActionType + Action 合入类型定义 |
| 2 | `search/trigger_registry.py` (95行) | `engine/enchantment.py` | 触发器注册并入附魔系统 |
| 3 | `search/corrupt.py` (49行) | `engine/mechanics/_data.py` | 数据表保留，执行逻辑移入 dispatch |
| 4 | `search/rewind.py` (61行) | `engine/mechanics/_data.py` | 同上 |
| 5 | `search/rune.py` (109行) | `engine/mechanics/_data.py` | 同上 |
| 6 | `search/dark_gift.py` (~50行) | `engine/mechanics/_data.py` | 同上 |
| 7 | `search/trigger_system.py` (255行) | `engine/trigger.py` | 重写为事件总线 |
| 8 | `search/enchantment.py` (~150行) | `engine/enchantment.py` | 重写附魔系统 |

### 4.3 迁移文件

| # | 当前位置 | 目标位置 | 说明 |
|---|----------|----------|------|
| 1 | `search/abilities/definition.py` | `abilities/definition.py` | 核心类型提升为顶层包 |
| 2 | `search/abilities/orchestrator.py` | `engine/target.py` (拆分) | 目标选择逻辑独立 |
| 3 | `search/abilities/simulation.py` | `engine/simulation.py` | 状态转移移入引擎 |
| 4 | `search/abilities/executor.py` | `engine/executor.py` + `engine/dispatch.py` | 拆分为分发表+处理器 |
| 5 | `search/abilities/enumeration.py` | `engine/rules.py` | 合法动作枚举归入规则引擎 |
| 6 | `search/game_state.py` | `engine/state.py` | GameState 移入引擎 |
| 7 | `search/aura_engine.py` | `engine/aura.py` | 光环引擎重写 |
| 8 | `search/deathrattle.py` | `engine/mechanics/deathrattle.py` | 机制子包 |
| 9 | `search/discover.py` | `engine/mechanics/discover.py` | 确定性化重写 |
| 10 | `search/dormant.py` | `engine/mechanics/dormant.py` | 数据表保留 |
| 11 | `search/quest.py` | `engine/mechanics/quest.py` | 数据表保留 |
| 12 | `search/secret_triggers.py` | `engine/mechanics/secret.py` | 扩展完整 |
| 13 | `search/choose_one.py` | `engine/mechanics/choose_one.py` | 数据表保留 |
| 14 | `search/location.py` | `engine/mechanics/location.py` | 数据表保留 |
| 15 | `search/shatter.py` | `engine/mechanics/shatter.py` | 数据表保留 |
| 16 | `search/herald.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 17 | `search/kindred.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 18 | `search/colossal.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 19 | `search/corpse.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 20 | `search/imbue.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 21 | `search/outcast.py` | `engine/mechanics/_data.py` | 仅保留数据表 |
| 22 | `search/opponent_simulator.py` | `search/opponent.py` | 重命名 |
| 23 | `search/lethal_checker.py` | `search/lethal.py` | 重命名 |
| 24 | `search/risk_assessor.py` | `search/risk.py` | 重命名 |
| 25 | `search/engine_adapter.py` | `search/adapter.py` | 重命名 |
| 26 | `search/power_parser.py` | 保留位置 | 不变 |
| 27 | `search/keywords.py` | `abilities/keywords.py` | 提升为顶层包 |

### 4.4 新增文件

| # | 文件 | 说明 |
|---|------|------|
| 1 | `engine/__init__.py` | 新顶层包初始化 |
| 2 | `engine/rules.py` | 规则引擎 — 动作验证、合法枚举 |
| 3 | `engine/dispatch.py` | 效果分发表 — Dict[EffectKind, Handler] |
| 4 | `engine/target.py` | 目标解析 — 确定性选择，零 copy-eval |
| 5 | `engine/deterministic.py` | 确定性 RNG + 期望值展开 |
| 6 | `engine/mechanics/__init__.py` | 机制子包初始化 |
| 7 | `engine/mechanics/_data.py` | 共享数据表（合并 10 个微型模块的数据） |
| 8 | `abilities/__init__.py` | 新顶层包初始化 |
| 9 | `abilities/loader.py` | JSON 能力加载器（替代 parser.py） |
| 10 | `abilities/value_expr.py` | 值表达式求值器（替代 LazyValue） |

### 4.5 修改文件

| # | 文件 | 修改内容 |
|---|------|----------|
| 1 | `models/card.py` | `abilities` 改为预填充（从 JSON loader），删除 lazy property |
| 2 | `models/__init__.py` | 合并 phase.py 内容 |
| 3 | `watcher/decision_loop.py` | import 路径更新 |
| 4 | `watcher/state_bridge.py` | import 路径更新 |
| 5 | `search/mcts/engine.py` | import 路径更新，使用新的 engine/ API |
| 6 | `search/mcts/simulation.py` | import 路径更新 |
| 7 | `search/mcts/turn_advance.py` | import 路径更新 |
| 8 | `scorers/scoring_engine.py` | import 路径更新（如引用 abilities） |
| 9 | `evaluators/composite.py` | import 路径更新 |
| 10 | `data/card_data.py` | 删除对 card_index/hsdb/card_cleaner 的引用 |

## 5. 实施路线图

### 5.1 总览

| Phase | 名称 | 持续 | 核心目标 | 删除行数 | 新增行数 |
|-------|------|------|----------|----------|----------|
| **P0** | 清理死代码 + 目录创建 | 1天 | 删除 ~2,500 行死代码，创建 engine/ 和 abilities/ 顶层包 | ~2,500 | ~50 |
| **P1** | 核心引擎重写 | 3-4天 | 死亡阶段 + 确定性化 + 分发表 + 目标选择 | ~300 | ~800 |
| **P2** | mechanic 统一 + 迁移 | 2-3天 | 双路径统一 → 单路径，10 个模块迁入 mechanics/ | ~500 | ~200 |
| **P3** | JSON 能力系统 | 2-3天 | loader.py 替代 parser.py，Card 预填充 | ~800 | ~400 |
| **P4** | 效果补全 + 测试 | 2天 | 7 个 stub 效果补全，集成测试 | 0 | ~500 |
| **P5** | I-MCTS + 训练管道 | 3-5天 | StateEncoder + 训练数据提取 | 0 | ~600 |

### 5.2 Phase 0: 清理死代码 + 目录创建（1天）

**删除：**
```
search/engine/pipeline.py         # 199行
search/engine/strategic.py        # ~200行
search/engine/tactical.py         # ~300行
search/engine/unified_tactical.py # ~200行
search/engine/turn_plan.py        # ~150行
search/engine/attack_planner.py   # ~200行
search/engine/action_pruner.py    # ~150行
search/engine/factors/            # ~700行 (7文件)
search/mechanics_state.py         # 210行
search/zone_manager.py            # 60行
search/entity.py                  # ~80行
data/card_index.py                # 11行
data/hsdb.py                      # 16行
data/card_cleaner.py              # ~150行
models/phase.py                   # 15行 (合并入 __init__.py)
```

**创建：**
```
engine/__init__.py                 # 新顶层包
engine/mechanics/__init__.py       # 机制子包
abilities/__init__.py              # 新顶层包
```

**验证：**
- `python -c "from analysis.search.mcts.engine import MCTSEngine"` 通过
- `python -c "from analysis.data.card_data import CardDB"` 通过

### 5.3 Phase 1: 核心引擎重写（3-4天）

#### 1a. GameState 迁移 + copy 完善（0.5天）

```
search/game_state.py → engine/state.py
```
- 新增 `graveyard: List[Minion]` 字段
- 新增 `cards_drawn_this_turn: int`
- 新增 `spells_cast_this_turn: int`
- 完善 `copy()` 方法覆盖所有字段
- 合并 MechanicsState 为组合字段而非独立类

#### 1b. 效果分发表（1天）

```
新建 engine/dispatch.py
新建 engine/executor.py（重写 abilities/executor.py）
```
- `EFFECT_HANDLERS: Dict[EffectKind, Handler]` 注册表
- 35 种 EffectKind 全部注册（含当前 7 个 stub 先注册为 pass）
- `dispatch()` + `dispatch_batch()` 入口函数
- 删除旧 `abilities/executor.py` 的 if-chain

#### 1c. 标准死亡阶段（0.5天）

```
重写 engine/simulation.py 中的 _resolve_deaths()
```
- 收集 → 同步击杀 → 按出场顺序亡语 → 再检查
- 复生保留所有关键词

#### 1d. 确定性化（1天）

```
新建 engine/deterministic.py
```
- `DeterministicRNG` 类（xorshift32）
- 替换 executor 中所有 `random.*` 调用
- Discover 改为 top-K 采样

#### 1e. 目标选择去 copy-eval（0.5天）

```
新建 engine/target.py
```
- `best_target()` 启发式打分替代 copy-eval 循环
- `validate_target()` 嘲讽验证

**验证：**
- MCTS 迭代数提升 5x+（由目标选择优化带来）
- 同一 GameState + 同一 Action → 确定性结果
- 死亡阶段：亡语链正确触发

### 5.4 Phase 2: Mechanic 统一 + 迁移（2-3天）

#### 2a. 数据表合并（1天）

10 个微型模块的数据表合并到 `engine/mechanics/_data.py`：
```
HERALD_SOLDIERS (from herald.py)
COLOSSAL_APPENDAGES (from colossal.py)
CORRUPT_MAP (from corrupt.py)
REwind_DATA (from rewind.py)
RUNE_MAP (from rune.py)
DARK_GIFT_MAP (from dark_gift.py)
DORMANT_DATA (from dormant.py)
OUTCAST_DATA (from outcast.py)
KINDRED_DATA (from kindred.py)
CORPSE_DATA (from corpse.py)
IMBUE_DATA (from imbue.py)
```

#### 2b. 执行路径统一（1天）

- 删除每个 mechanic 模块的直接变异函数
- 在 `dispatch.py` 注册所有 mechanic 效果 handler
- 验证 simulation.py 中只有 `dispatch_batch()` 调用

#### 2c. 大型模块迁移（0.5天）

保留完整逻辑的模块迁入 `engine/mechanics/`：
```
deathrattle.py  → engine/mechanics/deathrattle.py
discover.py     → engine/mechanics/discover.py  (确定性重写)
quest.py        → engine/mechanics/quest.py
secret_triggers → engine/mechanics/secret.py (扩展)
choose_one.py   → engine/mechanics/choose_one.py
location.py     → engine/mechanics/location.py
shatter.py      → engine/mechanics/shatter.py
dormant.py      → engine/mechanics/dormant.py
```

**验证：**
- `grep -r "random\." analysis/engine/` 无结果
- `grep -r "state\.board\." analysis/engine/mechanics/` 无直接变异
- 所有效果仅通过 `dispatch()` 触发

### 5.5 Phase 3: JSON 能力系统（2-3天）

#### 3a. 值表达式系统（1天）

```
新建 abilities/value_expr.py
```
- `resolve(expr, state, source) → int`
- 支持 `$attr`, `$count`, `$add`, `$mul`, `$sub`, `$if`, `$ref`
- `to_json()` / `from_json()` 序列化

#### 3b. JSON 能力加载器（1天）

```
新建 abilities/loader.py
```
- `load_abilities(card_id) → List[CardAbility]`
- 离线工具：现有 parser 输出 → JSON 文件
- Card.abilities 改为预填充（从 loader）

#### 3c. 删除解析器（0.5天）

```
删除 abilities/parser.py
删除 abilities/extractors.py
删除 abilities/tokens.py
删除 data/card_effects.py
删除 data/card_roles.py
```

**验证：**
- `Card(card_id="EX1_116").abilities` 返回预填充的能力列表
- 无运行时文本解析

### 5.6 Phase 4: 效果补全 + 测试（2天）

#### 4a. 7 个 stub 效果补全（1天）

```python
# 当前 stub → 实际实现
COPY          → executor.copy_entity()
SHUFFLE       → executor.shuffle_into_deck()
TRANSFORM     → executor.transform()
RETURN        → executor.return_to_hand()
TAKE_CONTROL  → executor.take_control()
SWAP          → executor.swap_stats()
CAST_SPELL    → executor.cast_spell()
```

#### 4b. 抽牌系统修正（0.5天）

- `draw_cards()` 从 `deck_list` 取实际卡牌
- 疲劳伤害处理

#### 4c. 集成测试（0.5天）

```
新建 tests/test_engine/
  test_death_phase.py      — 亡语链、复生、死亡顺序
  test_deterministic.py    — 同状态同动作确定性
  test_dispatch.py         — 35 种效果分派
  test_target.py           — 目标选择、嘲讽验证
  test_simulation.py       — 端到端状态转移
```

**验证：**
- 7 个 stub 效果全部有实际逻辑
- 所有测试通过

### 5.7 Phase 5: I-MCTS + 训练管道（3-5天）

此阶段与 `declarative-card-effect-json-design.md` 的 Q3-Q4 对齐。

#### 5a. StateEncoder（1天）

```
新建 analysis/search/neural/
  state_encoder.py   — GameState → 固定长度向量
  action_encoder.py  — Action → 独热编码
```

- ability_tags 特征编码（52维）
- 场面向量（友方随从、敌方随从、英雄状态）
- 手牌/牌库/法力力特征

#### 5b. 训练数据提取器（1天）

```
新建 analysis/training/
  extractor.py     — Power.log → (state_vector, action, reward)
  pipeline.py      — 批量处理管道
```

#### 5c. NeuralMCTS（2-3天）

```
新建 analysis/search/neural/
  policy_net.py    — 策略网络
  value_net.py     — 价值网络
  neural_mcts.py   — 神经网络引导的 MCTS
```

**验证：**
- 训练数据可从 Power.log 提取
- NeuralMCTS 在简单场景下优于纯 MCTS

### 5.8 风险与缓解

| 风险 | 缓解 |
|------|------|
| Phase 1 引入回归 | 每个 sub-phase 后跑已有 MCTS 端到端测试 |
| 确定性 RNG 与真实游戏不一致 | 训练数据来自真实 Power.log，RNG 仅影响模拟 |
| JSON 数据覆盖不全 | Phase 3 离线工具先跑全量卡牌，缺失卡牌 fallback 到现有解析器 |
| mechanic 迁移遗漏 | Phase 2 后 grep 确认无直接变异路径 |
| GameState.copy 性能 | Phase 1e 后 benchmark 对比 copy 次数 |

### 5.9 与已有设计文档的关系

| 文档 | 状态 |
|------|------|
| `declarative-card-effect-json-design.md` | **部分替代** — JSON Schema + 值表达式 + I-MCTS 仍有效；实施路线由本文 Phase 3-5 替代 |
| `refactoring-architecture-plan.md` | **完全替代** — 本文更激进，删除更多文件 |
| `merge-analysis.md` | **完全替代** — 合并建议已纳入本文 |
| `analysis-full-refactoring-design.md` (P7-P11) | **完全替代** — Phase 0-5 覆盖全部 P7-P11 范围 |
| `ARCHITECTURE.md` | Phase 5 完成后更新 |

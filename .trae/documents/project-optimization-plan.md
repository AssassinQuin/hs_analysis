# 项目优化方案

> 基于 `docs/research/2026-04-23-hearthstone-actions-and-decision-taxonomy.md` 调研文档  
> 制定日期: 2026-04-23

---

## 总体目标

将系统从"能算当前最优步"升级为"可解释的中期规划引擎"，具体聚焦三个统一：

1. **统一动作字典** — 强类型枚举替代字符串，消除拼写漂移风险
2. **统一功能类别标签** — 贯通发现概率、抽牌概率、回合目标
3. **统一跨回合规划** — 显式 TurnPlan 输出，连接"当前动作"与"后续准备"

---

## 优化项一览

| # | 优化项 | 优先级 | 影响范围 | 复杂度 |
|---|--------|--------|----------|--------|
| 1 | Action 类型字符串→枚举 | P0 | actions/enumeration/simulation/pipeline | 中 |
| 2 | 卡牌功能类别标签系统 | P0 | card_effects/draw_model/discover_model/strategic | 中 |
| 3 | TurnPlan 显式规划输出 | P1 | pipeline/tactical/新增 turn_plan.py | 高 |
| 4 | StrategicMode 新增 CONTROL 模式 | P1 | strategic | 低 |
| 5 | 概率面板统一接口 | P1 | draw_model/discover_model/新增 probability_panel.py | 中 |
| 6 | 信息探测动作元标签 | P2 | enumeration/action_pruner/strategic | 低 |
| 7 | 对手模拟器增强 | P2 | opponent_simulator | 中 |
| 8 | bare except 清理 | P2 | 全局 30+ 处 | 低 |

---

## 优化项 1：Action 类型字符串→枚举（P0）

### 问题
当前 `Action.action_type` 是纯字符串（`"PLAY"`, `"ATTACK"`, `"END_TURN"` 等），存在拼写漂移风险，IDE 无法做静态检查。

### 方案

**1.1 新建 `ActionType` 枚举**

位置：`analysis/search/rhea/actions.py`

```python
from enum import Enum, auto

class ActionType(Enum):
    PLAY = auto()
    PLAY_WITH_TARGET = auto()
    ATTACK = auto()
    HERO_POWER = auto()
    ACTIVATE_LOCATION = auto()
    HERO_REPLACE = auto()
    DISCOVER_PICK = auto()
    CHOOSE_ONE = auto()      # 新增：抉择分支
    TRANSFORM = auto()
    END_TURN = auto()
```

**1.2 Action.action_type 改为 ActionType**

- `action_type: str` → `action_type: ActionType`
- `describe()` 方法内 switch 改为枚举比较
- 保持 `action_key()` 兼容（枚举是可哈希的）

**1.3 全量迁移调用方**

需要修改的文件：
- `enumeration.py` — 所有 `Action(action_type="PLAY")` → `Action(action_type=ActionType.PLAY)`
- `simulation.py` — 所有 `action.action_type == "PLAY"` → `action.action_type == ActionType.PLAY`
- `pipeline.py` — 同上
- `tactical.py` — 同上
- `action_normalize.py` — action_key 已支持枚举
- `action_pruner.py` — 字符串比较→枚举比较
- `attack_planner.py` — 同上

**1.4 兼容性过渡**

- 提供临时 `action_type_from_str(s: str) -> ActionType` 转换函数
- 在 1-2 个版本后移除

---

## 优化项 2：卡牌功能类别标签系统（P0）

### 问题
调研文档指出"功能类别标签（解场/回血/战场）"尚未系统化沉淀到所有卡牌。当前 `card_effects.py` 提取的是具体效果（damage/heal/summon），缺少高层功能分类。

### 方案

**2.1 定义 RoleTag 枚举**

位置：`analysis/data/card_roles.py`（新文件）

```python
from enum import Enum, auto

class RoleTag(Enum):
    REMOVAL_SINGLE = auto()    # 单体解场
    REMOVAL_AOE = auto()       # 群体解场
    HEAL = auto()              # 回血/护甲
    TEMPO_BOARD = auto()       # 优质战场（高攻防随从/突袭/冲锋）
    CARD_DRAW = auto()         # 过牌/资源补充
    BURST_DAMAGE = auto()      # 直伤/斩杀
    TAUNT_DEFENSE = auto()     # 嘲讽防御
    BUFF = auto()              # 增益（手牌buff/场面buff）
    UTILITY = auto()           # 工具牌（沉默/冻结/发现）
```

**2.2 从 card_effects 到 RoleTag 的映射规则**

```python
def classify_roles(effects: dict) -> set[RoleTag]:
    roles = set()
    if effects.get("direct_damage", 0) >= 3:
        roles.add(RoleTag.BURST_DAMAGE)
    if effects.get("aoe_damage", 0) > 0:
        roles.add(RoleTag.REMOVAL_AOE)
    if effects.get("destroy"):
        roles.add(RoleTag.REMOVAL_SINGLE)
    if effects.get("heal", 0) > 0 or effects.get("armor", 0) > 0:
        roles.add(RoleTag.HEAL)
    if effects.get("draw", 0) > 0:
        roles.add(RoleTag.CARD_DRAW)
    # ... 更多规则
    return roles
```

**2.3 集成到 Card 模型**

- `Card` 新增 `roles: frozenset[RoleTag]` 字段
- `Card.__post_init__` 中从 `get_effects()` 自动计算 roles
- 懒加载 + 缓存（大部分卡牌 roles 不变）

**2.4 消费方集成**

- `DrawModel.top_deck_probability()` → 新增 `draw_role_probability(state, role: RoleTag, n_draws: int) -> float` 方法
- `DiscoverModel` → 新增 `discover_role_hit_prob(pool, role: RoleTag) -> float` 方法
- `StrategicMode` → 根据 `RoleTag` 分布辅助判定模式

---

## 优化项 3：TurnPlan 显式规划输出（P1）

### 问题
当前 `Decision` 输出是 `List[Action]`，缺少跨回合信息。调研文档建议 `TurnPlan` 结构应包含后续准备概率。

### 方案

**3.1 定义 TurnPlan 数据结构**

位置：`analysis/search/engine/turn_plan.py`（新文件）

```python
@dataclass
class NextTurnOuts:
    clear_prob: float    # P_draw(解场, 1抽)
    heal_prob: float     # P_draw(回血, 1抽)
    board_prob: float    # P_draw(战场, 1抽)
    burst_prob: float    # P_draw(直伤, 1抽)

@dataclass
class TurnPlan:
    objective: str       # LETHAL / DEFENSIVE / DEVELOPMENT / CONTROL
    primary_line: list[Action]
    backup_lines: list[list[Action]]  # 备选线路（最多3条）
    reserve_resources: list[str]      # 建议保留的资源描述
    next_turn_outs: NextTurnOuts
    risk_report: RiskReport           # 当前风险评估
    confidence: float
```

**3.2 集成到 DecisionPipeline**

- `DecisionPipeline.decide()` 返回类型可选扩展为 `TurnPlan`
- 在 `decide()` 末尾增加 `_compute_outs()` 步骤
- 利用 `DrawModel` + `RoleTag` 计算下回合抽牌概率

**3.3 输出格式化**

- `TurnPlan.describe()` → 人类可读的多行文本
- 概率面板输出到日志

---

## 优化项 4：StrategicMode 新增 CONTROL 模式（P1）

### 问题
调研文档定义了四种回合目标（LETHAL/DEFENSIVE/DEVELOPMENT/CONTROL），当前只有前三种。缺少"优先解除关键威胁并建立可持续优势"的控场模式。

### 方案

**4.1 新增 CONTROL 模式判定**

在 `strategic.py` 的 `strategic_decision()` 中：

```python
if mode != "LETHAL" and mode != "DEFENSIVE":
    if _check_control_needed(state):
        return StrategicMode(mode="CONTROL", confidence=..., reason="...")
```

**4.2 CONTROL 模式判定条件**

- 敌方场面有高价值目标（攻击力>=4 或有关键词如 windfury/divine_shield）
- 我方不处于发展窗口（非空场/非极早期）
- 无立即致命威胁（排除 DEFENSIVE）

**4.3 战术适配**

- `TacticalPlanner.plan()` 对 CONTROL 模式优先枚举 removal spell + trade combo
- `ActionPruner` 对 CONTROL 模式保留更多解场选项

---

## 优化项 5：概率面板统一接口（P1）

### 问题
当前 `DrawModel` 和 `DiscoverModel` 各自独立，缺少"需求感知权重模型"统一接口。

### 方案

**5.1 新建 `ProbabilityPanel`**

位置：`analysis/search/engine/models/probability_panel.py`（新文件）

```python
@dataclass
class ProbabilityPanel:
    # 抽牌概率
    draw_clear_1: float    # 单抽解场概率
    draw_heal_1: float     # 单抽回血概率
    draw_board_1: float    # 单抽战场概率
    draw_burst_1: float    # 单抽直伤概率
    draw_clear_2: float    # 两抽至少命中解场概率

    # 发现概率（如果有发现动作）
    discover_clear: float | None
    discover_heal: float | None
    discover_board: float | None

    # 对手威胁
    opp_lethal_prob: float  # 对手下回合斩杀估计
```

**5.2 统一计算入口**

```python
def compute_panel(state: GameState) -> ProbabilityPanel:
    draw_model = DrawModel()
    # 利用 RoleTag 从 deck_list 统计各类别数量
    # 用超几何分布公式计算 n 抽命中概率
    ...
```

**5.3 集成到 TurnPlan**

- `TurnPlan.next_turn_outs` 直接使用 `ProbabilityPanel` 的字段
- 日志输出一行概率摘要

---

## 优化项 6：信息探测动作元标签（P2）

### 问题
调研文档指出"隐藏信息动作（奥秘试探、读手）"尚未作为独立动作层建模。

### 方案

**6.1 在 Action 上新增可选 `meta_tags`**

```python
@dataclass
class Action:
    action_type: ActionType
    ...
    meta_tags: frozenset[str] = frozenset()  # {"PROBE_SECRET", "RESOURCE_HOLD"}
```

**6.2 在 enumeration 阶段标记探测动作**

- 低费用法术（≤2费）且对手有奥秘 → 标记 `PROBE_SECRET`
- 低价值随从（总属性≤4）→ 标记 `PROBE_SECRET`（试探冰冻/爆炸陷阱）
- 这些标记不影响执行，仅用于上层规划排序

**6.3 在 action_pruner 中利用元标签**

- 有 `PROBE_SECRET` 标签的动作优先级提升（信息先行原则）
- 有 `RESOURCE_HOLD` 标签的动作在 DEFENSIVE 模式下优先级提升

---

## 优化项 7：对手模拟器增强（P2）

### 问题
当前 `OpponentSimulator` 仅做贪心换怪，未考虑：法术解场、英雄技能、武器攻击。

### 方案

**7.1 增强模拟维度**

- 添加对手英雄技能伤害估计（已知职业的技能伤害）
- 添加对手武器攻击（已知武器时）
- 添加简单法术解场估计（基于对手职业的常见 AoE 概率）

**7.2 输出增强**

- `SimulatedOpponentTurn` 新增 `spell_threat: float` 字段
- 新增 `estimated_opp_damage()` 综合计算

---

## 优化项 8：bare except 清理（P2）

### 问题
`项目进度.md` 缺陷 #1 指出 30+ 处 `except Exception: pass`，导致调试困难。

### 方案

**8.1 分级处理**

- 关键路径（simulation/strategic/pipeline）：改为 `except Exception as e: log.warning(..., exc_info=e)`
- 非关键路径（评分/效果提取）：保留 `except Exception` 但添加 `log.debug(...)`
- 确实不应失败的路径：保留 bare except 但添加注释说明原因

**8.2 批量替换**

使用 IDE 批量替换 + 人工审核结合，按文件分批处理。

---

## 实施顺序

```
Phase 1 (基础强化):
  优化项 1 → Action枚举化
  优化项 8 → bare except 清理（并行）

Phase 2 (决策升级):
  优化项 2 → RoleTag 标签系统
  优化项 4 → CONTROL 模式

Phase 3 (规划能力):
  优化项 5 → 概率面板
  优化项 3 → TurnPlan

Phase 4 (增强):
  优化项 6 → 元标签
  优化项 7 → 对手模拟器增强
```

---

## 验证策略

每个优化项完成后：
1. 运行 `pytest tests/` 确保现有测试全通过
2. 运行 `python scripts/replay_game.py` 回放真实对局验证输出
3. 检查 IDE 诊断零错误
4. 更新 `项目进度.md`

---
date: 2026-04-22
topic: "V12 Power.log 驱动的引擎缺陷分析与改进设计"
status: draft
version: 1.0
based_on: Power.log 真实对局分析 + V11 引擎代码审查
supersedes: 2026-04-21-next-gen-engine-architecture-design.md
---

# 问题描述

基于 [Power.log](file:///d:/code/game/Power.log) 中 23 回合真实对局（死亡阴影瓦莉拉 vs 卡德加），提取了 10 个复杂场面决策场景，逐一对照 V11 引擎代码进行评估。分析揭示了 **20 个引擎不足**，其中 5 个为架构级致命缺陷，5 个因子评估缺陷，5 个搜索/枚举缺陷，5 个数据模型缺陷。

**核心结论：** V11 引擎本质上是一个"数值评估器"而非"游戏模拟器"。10 个场景中有 6 个直接涉及战吼/发现/英雄替换/控制变形等效果，这些都无法被当前的 `apply_action()` 处理。引擎最关键的瓶颈是 **卡牌效果模拟层的缺失**。

**本对局涉及的关键机制（V11 全部无法处理）：**

| 机制 | 出现场景 | 引擎状态 |
|------|---------|---------|
| 连击 (Combo) | 回合6: 伺机待发→抹除存在 | ❌ 无出牌顺序感知 |
| 发现 (Discover) | 回合8: 梦魇之王萨维斯战吼发现 | ❌ 战术枚举无法分支 |
| 英雄替换 (Hero Card) | 回合20: 灭世者死亡之翼 | ❌ 无 HERO_REPLACE action |
| 黑暗之赐 (Dark Gift) | 回合4/10: 苦花骑士buff | ❌ 无增益来源追踪 |
| 英雄技能变体 | 回合8+: 青铜龙的祝福/无情 | ❌ 技能固定2伤害 |
| 控制/变形 (Transform) | 回合9: 诅咒之链控米罗克 | ❌ 无 CONTROL action |
| 时光回溯 (Rewind) | 回合23: 时光流汇扫荡者 | ❌ 无状态回滚 |
| 衍生随从链 | 回合14+: 希奈丝特拉士兵 | ❌ 无召唤链模拟 |

---

# 约束

1. **向后兼容** — 保留 V11 所有 25 个测试继续通过
2. **性能** — 单回合决策 < 150ms（V11 基准 100ms，允许因模拟层增长 50%）
3. **无外部依赖** — 纯 Python，不引入新包
4. **增量实现** — 每个 Phase 独立可测试、可部署
5. **真实卡牌数据** — 所有实现基于 `unified_standard.json` 中的卡牌数据

---

# 10 个复杂场面决策场景

## 场景 1：回合 6 — 连击法术链（资源调度极限操作）

### 场面状态

```
玩家1 (盗贼):
  英雄: 死亡阴影瓦莉拉 30HP
  武器: 弑君者 3/2
  法力: 6/6
  手牌: 幸运币(0费)、伺机待发(0费)、抹除存在(3费)、...
  场面: (可能有少量随从)

玩家2 (法师):
  英雄: 卡德加 30HP
  场面: 可能有随从
```

### 实际决策

幸运币(+1法力) → 伺机待发(下张法术-3费) → 抹除存在(本应3费,现0费)

### 引擎行为分析

**TacticalPlanner._enumerate_card_combos()** 的枚举逻辑：

```python
# 当前代码 (tactical.py L111-146)
affordable = [(idx, card) for idx, card in enumerate(hand) if card.cost <= mana]
# 幸运币 cost=0 → affordable
# 伺机待发 cost=0 → affordable
# 抹除存在 cost=3 → affordable
# 但枚举时每个 combo 只看 cost <= available_mana，不考虑顺序依赖
```

**问题列表：**

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 伺机待发的减费效果不被模拟 | `apply_action("PLAY")` 不处理"下张法术-3费" | 抹除存在仍按3费计算，combo 被跳过 |
| 2 | 幸运币的临时法力不被追踪 | `ManaState` 无"本回合临时法力"字段 | 无法精确计算法力上限 |
| 3 | 出牌顺序无影响 | BFS枚举 `(card_idx, pos)` 不编码顺序 | 无法发现"先A后B"比"先B后A"更优 |
| 4 | 连击(Combo)标签不触发 | `cards_played_this_turn` 存在但 `apply_action` 不检查 combo 条件 | 抹除存在的连击效果被忽略 |

### 改进方案

#### 方案 A: 法力修改器栈

```python
@dataclass
class ManaModifier:
    modifier_type: str    # "reduce_next_spell", "temporary_crystal", "overload_discount"
    value: int
    scope: str            # "next_spell", "this_turn", "next_turn"
    used: bool = False

@dataclass
class ManaState:
    available: int = 0
    overloaded: int = 0
    max_mana: int = 0
    overload_next: int = 0
    max_mana_cap: int = 10
    modifiers: List[ManaModifier] = field(default_factory=list)  # 新增

    def effective_cost(self, card: Card) -> int:
        base = card.cost
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card.card_type == "SPELL":
                base = max(0, base - mod.value)
            elif mod.scope == "this_turn":
                base = max(0, base - mod.value)
        return base

    def consume_modifiers(self, card: Card):
        for mod in self.modifiers:
            if mod.used:
                continue
            if mod.scope == "next_spell" and card.card_type == "SPELL":
                mod.used = True
```

#### 方案 B: 有序枚举

将 `_enumerate_card_combos` 从 BFS 改为排列枚举，每个 combo 内的卡牌有明确顺序：

```python
def _enumerate_ordered_combos(self, state):
    combos = []
    affordable = [(idx, card) for idx, card in enumerate(state.hand)
                  if state.mana.effective_cost(card) <= state.mana.available]
    for depth in range(1, self._max_combo_depth + 1):
        for perm in permutations(affordable, depth):
            sim_mana = state.mana.copy()
            valid = True
            for idx, card in perm:
                eff_cost = sim_mana.effective_cost(card)
                if eff_cost > sim_mana.available:
                    valid = False
                    break
                sim_mana.available -= eff_cost
                sim_mana.consume_modifiers(card)
            if valid:
                combos.append([(idx, -1) for idx, _ in perm])
    return combos
```

---

## 场景 2：回合 8 — 梦魇之王萨维斯的发现选择

### 场面状态

```
玩家1 (盗贼):
  武器: 弑君者 3/2
  场面: 米罗克(3/X)
  法力: 4/8
  手牌: 梦魇之王萨维斯(4费传说)

玩家2 (法师): 卡德加 30HP
```

### 实际决策

打出梦魇之王萨维斯(4费) → 战吼发现 → 选择活体梦魇 → 使用青铜龙的祝福(英雄技能) → 米罗克打脸(3伤)

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 发现选择无法在枚举中模拟 | `_enumerate_card_combos` 只处理 PLAY action，发现是多步决策 | 萨维斯被当作白板4/4 |
| 2 | 战吼效果链断裂 | `apply_action` 无战吼触发点 | 33%标准池卡牌被低估 |
| 3 | 英雄技能与出牌的交互 | 英雄技能固定2伤害，无职业变体 | 青铜龙的祝福效果被忽略 |
| 4 | 衍生随从(活体梦魇)的价值 | `DiscoverEVFactor` 只算期望值，不加入战术枚举 | 发现的实际价值被大幅低估 |

### 改进方案

#### 战吼/发现分支枚举

```python
class BattlecryResolver:
    def resolve(self, state: GameState, card: Card) -> List[Tuple[GameState, float]]:
        if "战吼" not in card.text and "BATTLECRY" not in (card.mechanics or []):
            return [(state, 1.0)]

        if "发现" in card.text or "DISCOVER" in (card.mechanics or []):
            return self._resolve_discover(state, card)

        return self._resolve_simple(state, card)

    def _resolve_discover(self, state, card):
        pool = self._get_discover_pool(state, card)
        if not pool:
            return [(state, 0.0)]

        scored = [(c, siv_score(c, state)) for c in pool]
        scored.sort(key=lambda x: -x[1])

        top_n = scored[:3]
        results = []
        for chosen_card, score in top_n:
            new_state = state.copy()
            new_state.hand.append(chosen_card)
            results.append((new_state, score))

        return results
```

**集成到 TacticalPlanner**：每个含发现的卡牌在枚举时展开为多个分支（top-3 发现选项），每个分支独立评估。

---

## 场景 3：回合 9 — 法师的资源调度与防守决策

### 场面状态

```
玩家1 (盗贼):
  场面: 米罗克(3/X)、梦魇之王萨维斯(4/4) 等
  武器: 弑君者

玩家2 (法师):
  英雄: 卡德加 27HP(3伤)
  法力: 5/9
  手牌: 诅咒之链、时间之沙、石丘防御者、火焰冲击(技能)
```

### 实际决策

诅咒之链控米罗克 → 时间之沙(维持时间线) → 石丘防御者 → 火焰冲击

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | "控制/变形"效果无 Action type | `Action` 只有 ATTACK/PLAY/END_TURN/HERO_POWER | 诅咒之链无法被枚举 |
| 2 | 时间之沙/回溯机制完全缺失 | `GameState` 无历史状态栈 | 无法模拟 GAME_RESET |
| 3 | 防守决策缺乏优先级 | `SurvivalFactor` 只有血量+危险度，无"先解谁"策略 | 无法区分解场优先级 |
| 4 | 英雄技能伤害不计入致命 | `LethalThreatFactor._max_damage()` 忽略技能 | 漏算斩杀 |

### 改进方案

#### 新增 Action Types

```python
class Action:
    action_type: str  # 扩展支持:
    # "ATTACK"          — 已有
    # "PLAY"            — 已有
    # "END_TURN"        — 已有
    # "HERO_POWER"      — 已有
    # "PLAY_WITH_TARGET" — 新增: 法术/战吼需要选择目标
    # "TRANSFORM"        — 新增: 变形/控制效果
    # "DISCOVER_PICK"    — 新增: 发现选择
    # "HERO_REPLACE"     — 新增: 英雄牌替换
    # "ACTIVATE_LOCATION"— 新增: 地标激活
```

#### SurvivalFactor 增强: 威胁排序

```python
def _threat_priority(self, state: GameState) -> List[Tuple[int, Minion, float]]:
    threats = []
    for i, m in enumerate(state.opponent.board):
        threat_score = m.attack * 2.0
        if m.has_windfury:
            threat_score *= 1.8
        if m.has_stealth:
            threat_score *= 1.5
        if m.has_divine_shield:
            threat_score *= 1.3
        if m.has_poisonous:
            threat_score *= 2.0
        threats.append((i, m, threat_score))
    threats.sort(key=lambda x: -x[2])
    return threats
```

---

## 场景 4：回合 10 — 暮光祭礼连击 + 多法术

### 场面状态

```
玩家1 (盗贼):
  法力: 6/10
  场面: 苦花骑士(2/3+黑暗之赐)、梦魇之王萨维斯(4/4)等
  手牌: 暮光祭礼x2、狐人老千(2费)

玩家2 (法师): 卡德加 30HP, 场面: 石丘防御者
```

### 实际决策

苦花骑士(2费+黑暗之赐) → 暮光祭礼(目标石丘防御者) → 暮光祭礼(目标石丘防御者) → 狐人老千(2费) → 萨维斯打脸 → 青铜龙的祝福

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 法术目标选择缺失 | `_enumerate_card_combos` 只为 MINION 分配 position | 暮光祭礼无法模拟目标选择 |
| 2 | 黑暗之赐增益无来源追踪 | `BoardControlFactor` 只看 `attack+health` 求和 | 无法区分原始身材与 buff |
| 3 | 同名卡牌重复使用问题 | 枚举用 `card_idx` 区分手牌，同一张不能打两次 | 暮光祭礼x2 被正确枚举但目标无法指定 |
| 4 | combo 深度不足 | `max_combo_depth=3`(中期)，实际打了5张 | 最优序列不在搜索空间内 |

### 改进方案

#### 法术目标枚举

```python
def _enumerate_card_combos(self, state):
    # ... 现有逻辑 ...
    for card_idx, card in affordable:
        if card.card_type == "MINION":
            # 现有逻辑: 枚举 position
            for pos in range(min(len(state.board) + depth, 7) + 1):
                queue.append(...)
        elif card.card_type == "SPELL":
            # 新增: 枚举法术目标
            targets = self._spell_targets(state, card)
            if not targets:
                queue.append((combo + [(card_idx, -1)], new_cost, depth + 1))
            else:
                for tgt in targets:
                    queue.append((combo + [(card_idx, tgt)], new_cost, depth + 1))

def _spell_targets(self, state, card):
    text = card.text or ""
    if "敌方随从" in text or "enemy minion" in text.lower():
        return list(range(1, len(state.opponent.board) + 1))
    if "随从" in text or "minion" in text.lower():
        return list(range(0, len(state.opponent.board) + 1 + len(state.board) + 1))
    return []
```

#### 自适应 Combo 深度

```python
@staticmethod
def _combo_depth_for_phase(turn_number: int, hand_size: int, mana: int) -> int:
    base = 2 if turn_number <= 4 else (3 if turn_number <= 7 else 4)
    affordable = min(hand_size, mana)
    if affordable >= 5:
        base = min(base + 1, 6)
    return base
```

---

## 场景 5：回合 11 — 法师的防守反击（劣势下的最优选择）

### 场面状态

```
玩家1 (盗贼):
  场面: 苦花骑士、狐人老千、梦魇之王萨维斯、米罗克、希奈丝特拉士兵 等(5+随从)

玩家2 (法师):
  英雄: 卡德加 23HP(7伤)
  法力: 7/10
```

### 实际决策

冬泉雏龙 + 源生之石 + 迅猛龙先锋（全力铺场，不解场）

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | DEFENSIVE 模式过于保守 | `_check_defensive_needed()` 面对高场面返回0.95，进入DEFENSIVE模式倾向于解场 | 但实际最优解是铺场 |
| 2 | 无"无法解完则转铺场"判断 | 引擎无解场效率评估 | 浪费资源做无效解场 |
| 3 | 场面威胁评估过于线性 | `enemy_damage_bound` 简单求和攻击力 | 无法评估关键词协同 |

### 改进方案

#### 智能战略模式: "不可解则铺"

```python
def strategic_decision(state: GameState) -> StrategicMode:
    if check_lethal_possible(state):
        return StrategicMode(mode="LETHAL", ...)

    enemy_damage = _enemy_damage_bound(state)
    hero_hp = state.hero.hp + state.hero.armor

    if enemy_damage >= hero_hp:
        # 检查是否能有效解场
        if _can_clear_board(state):
            return StrategicMode(mode="DEFENSIVE", ...)
        else:
            return StrategicMode(mode="DEVELOPMENT",
                reason="无法完全解场，转为铺场寻求翻盘")

    return StrategicMode(mode="DEVELOPMENT", ...)

def _can_clear_board(state: GameState) -> bool:
    """估算能否在本回合清除对手场面"""
    total_enemy_hp = sum(m.health for m in state.opponent.board)
    available_damage = state.get_total_attack()
    for card in state.hand:
        if card.card_type == "SPELL" and card.cost <= state.mana.available:
            dmg = _parse_spell_damage(card)
            available_damage += dmg
    return available_damage >= total_enemy_hp * 0.7
```

---

## 场景 6：回合 14 — 解场 vs 打脸的全局最优攻击

### 场面状态

```
玩家1 (盗贼):
  场面: 苦花骑士、狐人老千(3/2)、萨维斯(4/4)、希奈丝特拉士兵x2、米罗克(3/X)

玩家2 (法师):
  英雄: 卡德加 ~11HP
  场面: 冬泉雏龙、迅猛龙先锋
```

### 实际决策

苦花骑士交换随从 → 其余全部打脸 → 卡德加被打到19伤

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 贪心攻击无全局最优 | `AttackPlanner._pick_best_attack()` 每步贪心 | 可能错过"先解后打脸"的最优序列 |
| 2 | 斩杀线不考虑后续回合 | 只看当前回合最大伤害 | 无法做"压血线"的多回合规划 |
| 3 | `_valid_targets` 嘲讽处理有歧义 | 有嘲讽时先赋 taunt_targets 再 hero，逻辑不清晰 | 可能允许在有嘲讽时打脸 |

### 改进方案

#### Beam Search 攻击规划器

```python
class AttackPlannerV2:
    def __init__(self, beam_width: int = 3):
        self._beam_width = beam_width

    def plan(self, state: GameState) -> AttackPlan:
        beam = [AttackPlan(attacks=[], score=0.0, state_after=state.copy())]

        for _ in range(20):
            expanded = []
            for plan in beam:
                if plan.state_after.is_lethal():
                    return plan
                for src_idx, minion in enumerate(plan.state_after.board):
                    if not self._can_attack(minion):
                        continue
                    for tgt in self._valid_targets(plan.state_after, minion):
                        new_plan = self._extend(plan, src_idx, tgt)
                        expanded.append(new_plan)

            if not expanded:
                break

            expanded.sort(key=lambda p: -p.score)
            beam = expanded[:self._beam_width]

        return beam[0] if beam else AttackPlan(attacks=[], score=0.0)
```

---

## 场景 7：回合 16 — 复杂随从交换链（法术+攻击穿插）

### 场面状态

```
玩家1 (盗贼):
  法力: 8/16
  手牌: 传承之火、激寒急流
  场面: 多个随从

玩家2 (法师): 卡德加 ~10HP
  场面: 莫尔葛熔魔、石丘防御者、未来主义先祖
```

### 实际决策

传承之火(目标狐人老千) → 激寒急流(目标苦花骑士) → 5次随从交换 → 英雄攻击随从

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | **出牌和攻击阶段强制分离** | TacticalPlanner 先枚举出牌，再 AttackPlanner 规划攻击 | 无法模拟"法术→攻击→法术→攻击"的穿插 |
| 2 | 传承之火的增益效果无法评估 | 复合"代价+收益"效果无因子捕获 | 低估此类卡牌 |
| 3 | 英雄攻击随从的风险未量化 | SurvivalFactor 只看血量变化 | 无法权衡"英雄受伤换场面" |

### 改进方案

#### 统一行动序列枚举（核心架构变更）

```python
class UnifiedActionEnumerator:
    def enumerate(self, state: GameState, max_actions: int = 8) -> List[List[Action]]:
        sequences = [[]]
        results = []

        for _ in range(max_actions):
            expanded = []
            for seq in sequences:
                current = self._apply_sequence(state, seq)
                legal = enumerate_legal_actions(current)
                for action in legal:
                    if action.action_type == "END_TURN":
                        results.append(seq + [action])
                    else:
                        expanded.append(seq + [action])
            sequences = self._prune_sequences(expanded, top_k=20)

        results.extend(sequences)
        return results

    def _prune_sequences(self, sequences, top_k):
        if len(sequences) <= top_k:
            return sequences
        scored = [(seq, self._quick_eval(seq)) for seq in sequences]
        scored.sort(key=lambda x: -x[1])
        return [s for s, _ in scored[:top_k]]
```

---

## 场景 8：回合 18 — 法师回溯恢复后的再次压制

### 场面状态

```
玩家1 (盗贼):
  法力: 9/18
  场面: 豆蔓蛮兵、紫色珍鳃鱼人、古神的眼线等

玩家2 (法师): 卡德加 40HP(回溯恢复)
```

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 无"回合历史"概念 | `GameState` 是当前快照，无血量变化来源追踪 | 无法理解血量为什么突变 |
| 2 | 特殊随从效果缺失 | 豆蔓蛮兵可能有成长效果，引擎只看数值 | 低估成长型随从 |
| 3 | 长期价值 vs 短期节奏 | `ValueFactor` 用卡差，无法评估"压血线" | 低估打脸的战略价值 |

---

## 场景 9：回合 20 — 英雄替换（灭世者死亡之翼）

### 场面状态

```
玩家1 (盗贼):
  法力: 10/20
  场面: 奥卓克希昂
  手牌: 灭世者死亡之翼(英雄牌)

玩家2 (法师): 卡德加 ~10HP(30/40伤)
```

### 实际决策

奥卓克希昂打脸 → 打出灭世者死亡之翼 → 英雄替换 → 获得15护甲 → 新技能"无情" → 触发摧折+奴役效果链

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | **英雄替换完全无法处理** | 无 `HERO_REPLACE` action type | 最致命缺陷 |
| 2 | 护甲获取不在模拟中 | `apply_action` 不处理"打出→获得护甲" | 无法评估防御收益 |
| 3 | 衍生效果链无法展开 | 摧折/奴役等随机效果需多步模拟 | 低估英雄牌价值 |
| 4 | 新技能价值无法评估 | 英雄技能固定，无动态变更机制 | 无法权衡技能替换 |

### 改进方案

#### Hero Card Handler

```python
class HeroCardHandler(MechanicHandler):
    def trigger_point(self) -> str:
        return "on_play"

    def apply(self, state: GameState, context: ActionContext) -> GameState:
        card = context.card
        state.hero.hp = 30  # 重置血量
        state.hero.armor += self._parse_armor(card)  # 获得护甲
        state.hero.hero_class = self._new_class(card)
        state.hero.weapon = None
        state.hero.hero_power_used = False

        # 触发战吼效果链
        state = self._resolve_battlecry_chain(state, card)
        return state

    def evaluate(self, state_before, state_after) -> float:
        armor_gain = state_after.hero.armor - state_before.hero.armor
        hp_change = state_after.hero.hp - state_before.hero.hp
        return (armor_gain + hp_change) / 30.0 + 0.5  # 基础价值
```

---

## 场景 10：回合 23 — 时光回溯 + 投降决策

### 场面状态

```
玩家1 (盗贼):
  英雄: 灭世者死亡之翼 30HP+13护甲
  场面: 希奈丝特拉 + 4个士兵

玩家2 (法师):
  英雄: 卡德加 ~5HP(35/40伤)
  手牌: 10张
```

### 实际决策

打出时光流汇扫荡者 → GAME_RESET → 卡德加血量部分回复 → 攻击 → 投降

### 引擎行为分析

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | GAME_RESET 超出引擎能力 | 无状态回滚/历史栈 | 无法模拟回溯 |
| 2 | 投降决策无法评估 | 引擎只做单回合最优 | 无法判断"是否该投降" |
| 3 | 10张手牌搜索空间爆炸 | C(10,1)+...+C(10,4)=385组合 | 时间预算内无法枚举完 |

---

# 系统性改进设计

## Phase 1: 卡牌效果模拟层 (P0 — 致命缺陷)

### 1.1 BattlecryDispatcher — 战吼分发器

**新文件**: `hs_analysis/search/engine/mechanics/battlecry_dispatcher.py`

```python
class BattlecryDispatcher:
    _patterns: List[Tuple[Pattern, Callable]] = []

    def __init__(self):
        self._register_patterns()

    def resolve(self, state: GameState, card: Card) -> List[Tuple[GameState, float]]:
        text = card.text or ""
        results = []

        for pattern, handler in self._patterns:
            match = pattern.search(text)
            if match:
                states = handler(state, match, card)
                results.extend(states)

        if not results:
            results.append((state, 0.0))

        return results

    def _register_patterns(self):
        self._patterns = [
            (re.compile(r"战吼[：:]\s*发现"), self._handle_discover),
            (re.compile(r"战吼[：:]\s*造成\s*(\d+)\s*点伤害"), self._handle_damage),
            (re.compile(r"战吼[：:]\s*召唤"), self._handle_summon),
            (re.compile(r"战吼[：:]\s*抽\s*(\d+)\s*张牌"), self._handle_draw),
            (re.compile(r"战吼[：:]\s*获得\s*(\d+)\s*点护甲"), self._handle_armor),
            (re.compile(r"Battlecry[：:]\s*[Dd]eal\s*(\d+)\s*damage"), self._handle_damage_en),
            (re.compile(r"Battlecry[：:]\s*[Dd]iscover"), self._handle_discover_en),
        ]
```

### 1.2 SpellTargetResolver — 法术目标解析

**新文件**: `hs_analysis/search/engine/mechanics/spell_target_resolver.py`

```python
class SpellTargetResolver:
    def resolve(self, state: GameState, card: Card) -> List[int]:
        text = (card.text or "").lower()
        targets = []

        if any(k in text for k in ["敌方随从", "enemy minion"]):
            targets = list(range(1, len(state.opponent.board) + 1))
        elif any(k in text for k in ["友方随从", "friendly minion"]):
            targets = list(range(1, len(state.board) + 1))
        elif any(k in text for k in ["随从", "minion"]):
            targets = (list(range(1, len(state.opponent.board) + 1)) +
                       list(range(1 + len(state.opponent.board),
                                  1 + len(state.opponent.board) + len(state.board) + 1)))
        elif any(k in text for k in ["英雄", "hero"]):
            targets = [0]

        if not targets and "造成" in text or "deal" in text:
            targets = [0] + list(range(1, len(state.opponent.board) + 1))

        return targets
```

### 1.3 HeroCardHandler — 英雄牌处理

**新文件**: `hs_analysis/search/engine/mechanics/hero_card_handler.py`

如上文场景 9 的代码所示。

---

## Phase 2: 统一行动序列 (P0 — 架构缺陷)

### 2.1 合并出牌与攻击阶段

**核心变更**: 将 `TacticalPlanner` 的"先出牌后攻击"改为"统一行动序列"。

```python
class UnifiedTacticalPlanner:
    def plan(self, state: GameState) -> List[TacticalCandidate]:
        sequences = self._enumerate_unified(state)
        candidates = []

        for seq in sequences:
            current = state.copy()
            for action in seq:
                current = apply_action(current, action)
                if current.is_lethal():
                    break

            ctx = EvalContext.from_state(state)
            scores = self._evaluator.evaluate(state, current, context=ctx)
            candidates.append(TacticalCandidate(
                play_actions=seq,
                attack_plan=AttackPlan(attacks=[], score=scores.total),
                factor_scores=scores,
                state_after=current,
                combined_score=scores.total + (1000.0 if current.is_lethal() else 0.0),
            ))

        candidates.sort(key=lambda c: -c.combined_score)
        return candidates
```

**搜索空间控制**:

| 策略 | 说明 | 效果 |
|------|------|------|
| Beam width=5 | 每步保留 top-5 序列 | 搜索空间从 n! 降到 5n |
| 行动剪枝 | ActionPruner 在每步剪除劣质操作 | 每步候选从~30降到~8 |
| 时间预算 | 超时截断，返回已找到的最优 | 保证 <150ms |
| Lethal early exit | 发现致命立即返回 | 快速路径 |

---

## Phase 3: 因子评估增强 (P1)

### 3.1 BoardControlFactor 增强: 关键词组合价值

```python
def compute(self, state_before, state_after, action, context):
    friend_after = self._weighted_board_value(state_after.board)
    enemy_after = self._weighted_board_value(state_after.opponent.board)
    friend_before = self._weighted_board_value(state_before.board)
    enemy_before = self._weighted_board_value(state_before.opponent.board)
    raw = (friend_after - friend_before) - (enemy_after - enemy_before)
    scale = max(friend_before + enemy_before, 1)
    return max(-1.0, min(1.0, raw / scale))

def _weighted_board_value(self, board: List[Minion]) -> float:
    total = 0.0
    for m in board:
        value = m.attack + m.health
        if m.has_taunt:
            value *= 1.3
        if m.has_divine_shield:
            value = m.attack * 2 + m.health  # 盾 ≈ 多打一次
        if m.has_windfury:
            value *= 1.5
        if m.has_poisonous:
            value += 3.0
        if m.has_stealth:
            value *= 1.2
        if m.has_lifesteal:
            value += m.attack * 0.3
        if m.has_reborn:
            value *= 1.4
        total += value
    return total
```

### 3.2 LethalThreatFactor 增强: 英雄技能伤害

```python
@staticmethod
def _max_damage(state: GameState) -> int:
    dmg = sum(m.attack for m in state.board if m.can_attack)
    for m in state.board:
        if m.has_windfury and m.can_attack:
            dmg += m.attack
    if state.hero.weapon is not None:
        dmg += state.hero.weapon.attack
    # 新增: 英雄技能伤害
    if not state.hero.hero_power_used:
        hero_dmg = _hero_power_damage(state)
        if hero_dmg > 0 and state.mana.available >= 2:
            dmg += hero_dmg
    # 新增: 手牌法术伤害
    for card in state.hand:
        if card.card_type == "SPELL" and card.cost <= state.mana.available:
            spell_dmg = _parse_spell_damage(card, state)
            dmg += spell_dmg
    return dmg
```

### 3.3 ValueFactor 增强: 牌质感知

```python
def compute(self, state_before, state_after, action, context):
    try:
        from hs_analysis.evaluators.siv import siv_score
        friend_quality_before = sum(siv_score(c, state_before) for c in state_before.hand)
        friend_quality_after = sum(siv_score(c, state_after) for c in state_after.hand)
        quality_delta = friend_quality_after - friend_quality_before
    except Exception:
        quality_delta = 0.0

    card_adv_delta = ((len(state_after.hand) + len(state_after.board)) -
                      (state_after.opponent.hand_count + len(state_after.opponent.board))) - \
                     ((len(state_before.hand) + len(state_before.board)) -
                      (state_before.opponent.hand_count + len(state_before.opponent.board)))

    raw = card_adv_delta * 0.3 + quality_delta * 0.02
    return max(-1.0, min(1.0, raw))
```

### 3.4 SurvivalFactor 增强: 阈值自适应

```python
def compute(self, state_before, state_after, action, context):
    hero_hp_after = state_after.hero.hp + state_after.hero.armor
    hero_hp_before = state_before.hero.hp + state_before.hero.armor
    hp_delta = hero_hp_after - hero_hp_before

    enemy_damage = sum(
        m.attack for m in state_after.opponent.board
        if m.can_attack or m.has_charge or m.has_rush
    )
    if state_after.opponent.hero.weapon:
        enemy_damage += state_after.opponent.hero.weapon.attack

    # 自适应阈值: 后期更敏感
    threshold_lethal = 1.0
    threshold_danger = 0.5 if context.phase == Phase.EARLY else 0.7

    danger = 0.0
    if enemy_damage >= hero_hp_after:
        danger = -0.8
    elif enemy_damage >= hero_hp_after * threshold_danger:
        danger = -0.4

    hp_change_norm = hp_delta / max(hero_hp_before, 1)
    raw = max(-1.0, min(1.0, hp_change_norm)) + danger
    return max(-1.0, min(1.0, raw))
```

---

## Phase 4: 数据模型扩展 (P1)

### 4.1 Minion 字段扩展

```python
@dataclass
class Minion:
    # ... 现有字段 ...
    has_magnetic: bool = False
    has_invoke: bool = False
    has_corrupt: bool = False
    has_spellburst: bool = False
    has_outcast: bool = False
    race: str = ""              # "DRAGON", "DEMON", "MECHANICAL", etc.
    spell_school: str = ""      # "FIRE", "FROST", "ARCANE", etc.
    enchantment_ids: List[str] = field(default_factory=list)
```

### 4.2 HeroState 扩展

```python
@dataclass
class HeroState:
    # ... 现有字段 ...
    hero_power_cost: int = 2
    hero_power_effect: str = ""     # "deal_2", "armor_2", "summon_1_1", etc.
    hero_power_damage: int = 0      # 技能伤害(含spell_power加成)
    is_hero_card: bool = False      # 是否已替换为英雄牌
```

### 4.3 Action 扩展

```python
@dataclass
class Action:
    action_type: str
    source_index: int = -1
    target_index: int = -1
    card_index: int = -1
    position: int = -1
    discover_choice_index: int = -1   # 新增: 发现选择索引
    sub_option: int = -1              # 新增: 子选项(如英雄技能变体)
```

---

## Phase 5: AttackPlanner 升级 (P2)

### 5.1 Beam Search 替代纯贪心

如上文场景 6 的 `AttackPlannerV2` 所示。

### 5.2 多回合致命预估

```python
def _two_turn_lethal_probability(self, state: GameState) -> float:
    this_turn_dmg = self._max_damage(state)
    next_turn_draw = 1.0
    next_turn_dmg_estimate = this_turn_dmg * 0.8 + next_turn_draw * 2.0
    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor

    if this_turn_dmg >= opp_hp:
        return 1.0
    if this_turn_dmg + next_turn_dmg_estimate >= opp_hp:
        return 0.6
    return 0.0
```

---

# 组件清单

## 新文件

| 文件 | 职责 | Phase |
|------|------|-------|
| `engine/mechanics/battlecry_dispatcher.py` | 战吼文本解析 + 效果分发 | P1 |
| `engine/mechanics/spell_target_resolver.py` | 法术目标枚举 | P1 |
| `engine/mechanics/hero_card_handler.py` | 英雄牌替换处理 | P1 |
| `engine/mechanics/control_handler.py` | 控制/变形效果处理 | P1 |
| `engine/unified_tactical.py` | 统一行动序列枚举器 | P2 |

## 修改文件

| 文件 | 改动 | Phase |
|------|------|-------|
| `game_state.py` | Minion/HeroState/Action 字段扩展 | P4 |
| `rhea_engine.py` | apply_action 新增战吼/发现/英雄牌触发点 | P1 |
| `engine/tactical.py` | 法术目标枚举 + 自适应深度 | P1 |
| `engine/strategic.py` | 智能战略模式("不可解则铺") | P3 |
| `engine/attack_planner.py` | Beam Search + 多回合致命预估 | P5 |
| `engine/factors/board_control.py` | 关键词组合价值 | P3 |
| `engine/factors/lethal_threat.py` | 英雄技能+手牌法术伤害 | P3 |
| `engine/factors/survival.py` | 自适应阈值 | P3 |
| `engine/factors/value.py` | 牌质感知(SIV加权) | P3 |
| `engine/action_pruner.py` | 扩展剪枝规则 | P2 |

---

# 数据流

```
输入: GameState
  │
  ├─ 1. 战略判定
  │    ├─ check_lethal() → LETHAL
  │    ├─ _can_clear_board() + enemy_threat → DEFENSIVE 或 DEVELOPMENT
  │    └─ DEVELOPMENT
  │
  ├─ 2. 统一行动序列枚举  ← 核心变更: 出牌+攻击不再分离
  │    ├─ 法力修改器栈计算 (幸运币/伺机待发等)
  │    ├─ 战吼分支展开 (发现→top-3分支)          ← 新增
  │    ├─ 法术目标枚举                           ← 新增
  │    ├─ 英雄牌处理                             ← 新增
  │    ├─ Beam width=5 剪枝
  │    └─ 时间预算截断
  │
  ├─ 3. 增强因子图评估
  │    ├─ BoardControl (关键词组合价值)           ← 增强
  │    ├─ LethalThreat (英雄技能+法术伤害)        ← 增强
  │    ├─ Tempo (法力利用+场面费用差)
  │    ├─ Value (SIV加权牌质)                     ← 增强
  │    ├─ Survival (自适应阈值)                   ← 增强
  │    ├─ ResourceEfficiency (含过载)
  │    └─ DiscoverEV (发现期望)
  │
  └─ 4. 输出: Decision
       ├─ best_plan: 统一行动序列 (出牌+攻击穿插)
       ├─ factor_scores: 7因子分解
       ├─ alternatives: top-3
       └─ reasoning: "选择此方案因为..."
```

---

# 测试策略

## Phase 1 测试 (~15 个)

| 测试 | 覆盖 |
|------|------|
| 战吼伤害正确应用 | BattlecryDispatcher |
| 战吼发现选最优 | BattlecryDispatcher + DiscoverModel |
| 英雄牌替换: 血量/护甲/技能更新 | HeroCardHandler |
| 伺机待发减费效果 | ManaModifier |
| 幸运币临时法力 | ManaModifier |
| 连击标签触发 | cards_played_this_turn |
| 法术定向目标选择 | SpellTargetResolver |

## Phase 2 测试 (~10 个)

| 测试 | 覆盖 |
|------|------|
| 出牌→攻击→出牌穿插序列 | UnifiedTacticalPlanner |
| Beam width 限制搜索空间 | AttackPlannerV2 |
| 时间预算截断返回最优 | UnifiedTacticalPlanner |
| 致命提前退出 | UnifiedTacticalPlanner |

## Phase 3 测试 (~10 个)

| 测试 | 覆盖 |
|------|------|
| 嘲讽+圣盾组合价值高于纯数值 | BoardControlFactor |
| 英雄技能伤害计入致命 | LethalThreatFactor |
| 高SIV手牌的Value因子更高 | ValueFactor |
| 后期生存阈值更敏感 | SurvivalFactor |

## 回归测试

V11 全部 25 个测试必须继续通过。

---

# 实施优先级

```
Phase 1 (P0, 致命): 卡牌效果模拟层
  ├─ BattlecryDispatcher    ← 33% 标准池卡牌需要
  ├─ SpellTargetResolver    ← 法术目标选择
  ├─ HeroCardHandler        ← 英雄牌是现代炉石核心
  └─ ManaModifier           ← 伺机待发/幸运币

Phase 2 (P0, 架构): 统一行动序列
  ├─ UnifiedTacticalPlanner ← 解决出牌/攻击分离
  └─ 扩展 ActionPruner      ← 搜索空间控制

Phase 3 (P1, 因子): 因子评估增强
  ├─ BoardControl 关键词组合
  ├─ LethalThreat 英雄技能
  ├─ Value 牌质感知
  └─ Survival 自适应阈值

Phase 4 (P1, 模型): 数据模型扩展
  └─ Minion/HeroState/Action 字段

Phase 5 (P2, 优化): AttackPlanner 升级
  ├─ Beam Search
  └─ 多回合致命预估
```

---

# 开放问题

1. **战吼分支展开的搜索空间** — 发现 top-3 分支 × 法术目标 × combo 深度，可能导致组合爆炸。需要更激进的剪枝策略。
2. **英雄牌效果链的模拟深度** — 灭世者死亡之翼的摧折/奴役是随机效果，需要用 RNGModel 做蒙特卡洛采样。
3. **时光回溯的处理策略** — GAME_RESET 机制在引擎中是否值得支持？还是标记为"不可模拟"并跳过？
4. **投降决策** — 引擎是否需要多回合胜率预估来决定是否投降？这需要完全不同的评估框架。
5. **性能回归** — 统一行动序列枚举可能比分离式慢 2-3 倍。是否需要在 150ms 预算内做更激进的剪枝？

---

# 参考

1. Power.log 对局分析报告 (本文档上方的对话记录)
2. [V11 引擎架构设计](file:///d:/code/game/thoughts/shared/designs/2026-04-21-next-gen-engine-architecture-design.md)
3. [V10 引擎大修设计](file:///d:/code/game/thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md)
4. [V10 状态感知评分设计](file:///d:/code/game/thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md)
5. [V10 评分实现设计](file:///d:/code/game/thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md)

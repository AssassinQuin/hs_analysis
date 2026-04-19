---
date: 2026-04-19
topic: "V10 State-Aware Scoring Framework"
status: draft
version: 1.0
based_on: 2026-04-19-hearthstone-complete-rules.md
---

# 问题描述

当前评分系统（V2→V7→V8→Composite）存在三个根本缺陷：

1. **线性叠加假设** — 所有评分都是加法/乘法链，无法捕捉非线性价值跳跃
   - 斩杀法术在对手1血时价值无限大，30血时约等于0
   - 兆示机制在2次和4次时有阈值跳跃，线性模型无法表达

2. **静态评分 vs 动态状态脱节** — V2~V7是卡牌固有分数（离线计算），V8仅7个粗糙修正器
   - 剧毒在有圣盾敌方时价值为0，在无圣盾时价值极高
   - 流放牌在手牌中间 vs 边缘价值完全不同

3. **关键词评分与规则脱节** — 经验常数（power=1.5, mechanical=0.75）无规则依据
   - 规则文档精确定义了每个机制的触发条件、交互逻辑、价值链
   - 当前评分系统完全忽略这些交互

**目标：** 设计一个基于完整游戏规则的、状态感知的评分框架，使决策引擎能正确评估每种游戏状态下的卡牌/局面价值。

---

# 约束

1. **向后兼容** — 保留V2~V7离线评分管线作为基础层，不破坏现有报告输出
2. **性能** — SIV计算必须在RHEA搜索循环内完成（<1ms/卡牌）
3. **增量实现** — 每个修正器独立实现，可逐步添加
4. **数据驱动** — 修正器参数可从HSReplay数据校准，不纯靠人工设定
5. **大文件规范** — >500行的实现文件按骨架→填充方式生成

---

# 方案：三层状态感知评分架构

## 架构总览

```
┌─────────────────────────────────────────────┐
│          Board State Value (BSV)            │  ← 全局层：非线性融合
│   tempo × value × survival + lethal_bonus   │
├─────────────────────────────────────────────┤
│      State Interaction Value (SIV)          │  ← 交互层：8个状态修正器
│   CIV × lethal × taunt × curve × position   │
│        × trigger × synergy × progress       │
│        × counter                             │
├─────────────────────────────────────────────┤
│       Card Intrinsic Value (CIV)            │  ← 基础层：增强V7管线
│   L1(vanilla) + L2(keyword) + L3(text)      │
│   + L4(type) + L5(conditional)              │
│   + keyword_interaction_table               │
│   + 2026_mechanic_base_values               │
└─────────────────────────────────────────────┘
```

## 为什么选这个方案

**替代方案A：纯ML模型** — 用神经网络从对局数据学习评分。
- 优点：自动发现非线性关系
- 缺点：需要大量标注数据、不可解释、难以调试、冷启动问题
- **不选原因：** 当前没有足够的对局日志数据，且引擎需要可调试的评分

**替代方案B：Monte Carlo模拟** — 对每个候选动作模拟100局游戏取平均。
- 优点：最精确的期望价值估计
- 缺点：计算量远超实时限制（RHEA需要<250ms）
- **不选原因：** 性能不可行

**选择方案的理由：** 三层架构在现有管线基础上增量改进，每个修正器有明确的规则文档依据，性能可控（查表+乘法链），可解释性强。

---

# 架构详细设计

## 基础层：Card Intrinsic Value (CIV)

### 保留现有管线

V2~V7评分管线经过验证，保留不动：
- L1: 幂律曲线拟合 (a × mana^b + c)
- L2: 关键词层级评分 (power/mechanical/niche × (1+0.1×mana))
- L3: 文本效果解析 (28个正则模式 → 数值)
- L4: 类型适配基线 (法术/武器/地标/英雄牌)
- L5: 条件期望 (37个条件 × 概率 × 倍率)

### 新增：关键词交互价值表

<!-- TODO: 详细的关键词交互矩阵 -->
<!-- 例如：剧毒+圣盾敌方=剧毒价值归零 -->

从规则文档第3-4章推导的交互规则：

| 交互 | 规则来源 | 价值影响 |
|------|---------|----------|
| 剧毒 vs 圣盾 | 3.5+3.6 | 剧毒价值×0.1（圣盾吸收后剧毒不触发） |
| 潜行+嘲讽 | 3.2+3.7 | 嘲讽价值归零（潜行压制嘲讽） |
| 免疫+嘲讽 | 3.2+3.9 | 嘲讽价值归零（免疫压制嘲讽） |
| 冰冻+风怒 | 3.4+3.8 | 风怒价值×0.5（可能被冰冻阻止第二次攻击） |
| 吸血+圣盾敌方 | 3.5+3.10 | 吸血治疗量归零（0伤害=0治疗） |
| 复生+亡语 | 4.2+4.9 | 亡语价值×1.5（死亡两次=亡语可触发两次） |
| 铜须+战吼 | 4.1 | 战吼价值×2（明确规则：战吼触发两次） |
| 里维endas+亡语 | 4.2 | 亡语价值×2（明确规则：亡语触发两次） |

### 新增：2026机制基础价值

<!-- TODO: 每种2026机制的CIV基础值 -->

| 机制 | 规则来源 | CIV基础值 | 公式 |
|------|---------|----------|------|
| 灌注(Imbue) | 9.1→7.3 | `Σ(k=1..∞) base_hp × 0.8^(k-1)` | 递减边际价值 |
| 兆示(Herald) | 9.1 | `soldier_value × 1 + jump(floor(n/2))` | 阈值跳跃 |
| 裂变(Shatter) | 9.2 | `(half_value × 2) × merge_bonus` | 合并加成 |
| 延系(Kindred) | 9.3 | `base_value × P(match)` | 条件概率 |
| 回溯(Rewind) | 9.4 | `max(E1, E2)` | 双分支最优 |
| 黑暗之赐 | 9.5 | `avg(gift_values)` | 10种礼物的期望均值 |
| 巨型(Colossal)+N | 9.7 | `(body + N × appendage) × space_penalty` | 场地惩罚 |
| 休眠(Dormant) | 9.8 | `awakened_value × P(survive_dormant)` | 觉醒概率 |
| 任务(Quest) | 9.10 | `reward_value × P(complete)` | 完成概率 |

## 交互层：State Interaction Value (SIV)

<!-- TODO: 8个状态修正器的详细公式 -->

### 修正器1：斩杀感知（Lethal Awareness）

**规则依据：** 战斗系统3.1 — 攻击流程、组合伤害可击杀英雄

**核心洞察：** 伤害价值在敌方英雄低血量时指数增长，不是线性增长。

```
lethal_proximity = 1 - (enemy_hp + enemy_armor) / 30
damage_multiplier = 1 + lethal_proximity² × LETHAL_SCALE

# LETHAL_SCALE = 3.0（可校准）
# 30血 → 1.0×, 15血 → 2.75×, 5血 → 4.69×, 1血 → 7.0×
```

**适用卡牌：** 造成伤害的法术、有冲锋/突袭的随从、武器

### 修正器2：嘲讽约束（Taunt Constraint）

**规则依据：** 战斗系统3.2 — 嘲讽强制攻击

**核心洞察：** 需要过墙时，穿透能力（沉默、消灭、剧毒）价值上升。

```
if enemy_has_taunt:
    taunt_multiplier = 1 + 0.3 × count(enemy_taunts)
    # 穿透类卡牌额外加成
    if card_has_silence_or_destroy: taunt_multiplier += 0.5
    if card_has_poisonous: taunt_multiplier += 0.3
else:
    taunt_multiplier = 1.0
```

### 修正器3：节奏窗口（Tempo Window）

**规则依据：** 法力系统2.1 — 每回合法力增长

**核心洞察：** 卡牌价值取决于能否在当前/下一回合打出（法力匹配度）。

```
if card.cost <= mana_available:
    curve_bonus = 1.0  # 可立即打出
elif card.cost <= mana_available + 1:
    curve_bonus = 0.9  # 下一回合可打
else:
    curve_bonus = 0.8 - 0.05 × (card.cost - mana_available - 1)

# 费用溢出惩罚
overflow_penalty = max(0, card.cost - turn_number - 1) × 0.1
curve_multiplier = curve_bonus - overflow_penalty
```

### 修正器4：手牌位置（Hand Position）

**规则依据：** 流放(4.8)、裂变(9.2)、手牌指定(9.9)

**核心洞察：** 手牌边缘 vs 中间的位置影响流放/裂变触发概率。

```
hand_size = len(hand)
if card has OUTCAST:
    if position == 0 or position == hand_size - 1:
        position_multiplier = 1 + outcast_bonus  # 流放加成
    else:
        position_multiplier = 1.0
elif card has SHATTER:
    # 裂变牌总是分裂到两端，合并概率取决于手牌密度
    merge_prob = P(halves_become_adjacent)
    position_multiplier = 1 + merge_prob × shatter_merge_bonus
else:
    position_multiplier = 1.0
```

### 修正器5：触发概率（Trigger Probability）

**规则依据：** 触发与光环系统5.x — 铜须/里维endas使战吼/亡语翻倍

```
trigger_multiplier = 1.0

if card has BATTLECRY and friendly_brann_in_play:
    trigger_multiplier *= 2.0  # 战吼双倍
if card has DEATHRATTLE and friendly_rivendare_in_play:
    trigger_multiplier *= 2.0  # 亡语双倍
if card has END_OF_TURN and friendly_drakkari_in_play:
    trigger_multiplier *= 2.0  # 回合结束双倍

# 光环源在场时，受光环影响的卡牌加成
if friendly_aura_active(card.race):
    trigger_multiplier *= 1.3
```

### 修正器6：种族协同（Race Synergy）

**规则依据：** 延系(9.3)、巨型(9.7)、随从种族(1.2)

```
friendly_race_count = count(minions_of_same_race_on_board)
hand_race_count = count(cards_of_same_race_in_hand)
synergy_bonus = 0.1 × (friendly_race_count + hand_race_count)

# 延系额外加成
if card has KINDRED:
    if last_turn_played_matching_race:
        synergy_bonus += kindred_bonus_value

synergy_multiplier = 1.0 + synergy_bonus
```

### 修正器7：累积进度（Progress Tracker）

**规则依据：** 灌注(7.3)、兆示(9.1)、任务(9.10)

```
progress_multiplier = 1.0

# 灌注：已灌注次数越多，边际价值递减但总价值递增
if card has IMBUE:
    current_imbue_level = state.hero.imbue_level
    progress_multiplier = 1 + 0.3 × (1 - 0.15 × current_imbue_level)

# 兆示：接近阈值时价值跳跃
if card has HERALD:
    herald_count = state.herald_count
    if herald_count == 1: progress_multiplier = 1.5  # 接近2次阈值
    elif herald_count == 3: progress_multiplier = 1.5  # 接近4次阈值
    else: progress_multiplier = 1.0

# 任务：完成进度越高，新进度的边际价值越大
if card is QUEST_PROGRESS:
    completion_pct = quest_progress / quest_threshold
    progress_multiplier = 1 + completion_pct² × 2.0
```

### 修正器8：对手反制（Counter Awareness）

**规则依据：** 冰冻(3.8)、免疫(3.9)、潜行(3.7)、奥秘(6.x)

```
counter_multiplier = 1.0

# 冰冻威胁：对手可能有冰冻手段
if opponent_class in FREEZE_CLASSES:
    if card is key_minion:
        counter_multiplier -= 0.1  # 冰冻风险

# 奥秘威胁：对手可能有狙击/冰冻陷阱
if opponent_has_secrets:
    if card has BATTLECRY:
        counter_multiplier -= 0.05  # 可能被计数法术阻止
    if card.attack >= 3:
        counter_multiplier -= 0.1  # 可能被冰冻陷阱弹回

# 潜行价值：关键随从需要保护
if opponent_has_aoe_potential:
    if card has STEALTH:
        counter_multiplier += 0.2  # 潜行躲避AoE的价值上升
```

### SIV完整公式

```
SIV(card, state) = CIV(card)
    × lethal_modifier(card, state)
    × taunt_modifier(card, state)
    × curve_modifier(card, state)
    × position_modifier(card, state)
    × trigger_modifier(card, state)
    × synergy_modifier(card, state)
    × progress_modifier(card, state)
    × counter_modifier(card, state)
```

## 全局层：Board State Value (BSV)

<!-- TODO: 增强的Composite评估设计 -->

### 增强的3维评估

保留现有3维结构（节奏/价值/生存度），增加非线性融合：

```
# 节奏维度（来自场面控制力）
tempo = Σ SIV(friendly_minions) × board_presence_weight
      - Σ SIV(enemy_minions) × threat_urgency_weight
      + mana_efficiency × 5.0
      + weapon_value

# 价值维度（来自手牌质量）
value = Σ SIV(hand_cards) + card_advantage × 2.0
      + resource_generation_value
      + discover_pool_ev

# 生存维度（来自威胁评估）
survival = (hero_hp + hero_armor) / 30.0 × 10.0
         - enemy_observable_damage × 0.5
         - enemy_lethal_threat × 50.0
         + healing_potential × 0.3
```

### 非线性融合（替代线性加权）

```
# Softmax融合 + 温度参数
raw = [tempo × phase_weight_t, value × phase_weight_v, survival × phase_weight_s]
temperature = 0.5  # 越小越趋向取最大值
weights = softmax(raw / temperature)
BSV = Σ weights[i] × raw[i]

# 阶段权重（替代硬编码系数）
# Early(turn≤4):  t=1.3, v=0.7, s=0.5
# Mid(turn 5-7):  t=1.0, v=1.0, s=1.0
# Late(turn 8+):  t=0.7, v=1.2, s=1.5
```

### 斩杀检测模块

独立于BSV，直接增强：
```
if lethal_checker.can_achieve_lethal(state):
    BSV = max(BSV, ABSOLUTE_LETHAL_VALUE)  # 斩杀=无限大价值
```

---

# 组件

## 新文件

| 文件 | 职责 |
|------|------|
| `hs_analysis/evaluators/siv.py` | State Interaction Value：8个状态修正器 |
| `hs_analysis/evaluators/bsv.py` | Board State Value：增强的3维评估 + 非线性融合 |
| `hs_analysis/scorers/v10_stateful.py` | V10评分引擎：CIV+SIV+BSV整合 |
| `hs_analysis/scorers/keyword_interactions.py` | 关键词交互价值表 |
| `hs_analysis/scorers/mechanic_base_values.py` | 2026机制基础价值表 |

## 修改文件

| 文件 | 改动 |
|------|------|
| `composite.py` | SIV替代V8作为输入源，BSV替代线性加权 |
| `submodel.py` | SIV融入board/threat/lingering评估 |
| `card.py` | 新增spell_school、location_durability字段 |
| `game_state.py` | 新增imbue_level、herald_count等状态追踪字段 |

---

# 数据流

```
游戏状态 (GameState)
  │
  ├── 手牌中每张卡 ──→ CIV(card) ──→ SIV(card, state) ──→ 手牌质量总和
  │                                              │
  ├── 场面随从 ────────────────────→ SIV(minion, state) ──→ 节奏维度
  │                                              │
  ├── 敌方场面 ────────────────────→ SIV(enemy, state) ──→ 威胁评估
  │                                              │
  └── 英雄状态 ─────────────────────────────────────→ 生存维度
                                                     │
                                          ┌──────────┘
                                          ▼
                                    BSV(非线性融合)
                                          │
                                          ▼
                                  RHEA适应度函数
```

---

# 错误处理

1. **修正器缺失** — 若某个修正器所需的状态字段不存在（如imbue_level未实现），该修正器返回1.0（无效果），不崩溃
2. **数值溢出** — SIV乘法链结果clamp到[0.01, 100.0]范围，防止NaN/Inf
3. **除零保护** — 所有除法使用max(denominator, 0.001)
4. **性能保护** — 每个修正器计算时间<0.1ms，超时则跳过返回1.0

---

# 测试策略

## 基础层测试（~15个）
- 关键词交互表查询正确性
- 2026机制CIV基础值计算正确
- 灌注递增价值函数正确收敛
- 兆示阈值跳跃在正确位置触发

## 交互层测试（~25个）
- 斩杀感知：1血vs30血时的伤害价值差异 >5×
- 嘲讽约束：有嘲讽时穿透卡牌价值上升
- 节奏窗口：当前回合可打vs不可打的费用差异
- 手牌位置：流放牌在边缘vs中间的价值差异
- 触发概率：铜须在场时战吼牌价值翻倍
- 种族协同：场面有3个同种族时的加成
- 累积进度：兆示计数1→2时价值跳跃
- 对手反制：有奥秘时高攻随从价值微降

## 全局层测试（~15个）
- 非线性融合：斩杀局面下BSV远大于正常局面
- 阶段检测：Early/Mid/Late权重正确切换
- 斩杀检测：lethal_checker发现斩杀时BSV=ABSOLUTE_LETHAL_VALUE
- 回归测试：现有362个测试全部通过

---

# 开放问题

1. **LETHAL_SCALE参数校准** — 3.0是初始猜测，需要从实战数据拟合
2. **Softmax温度参数** — 0.5是经验值，可能需要A/B测试确定最优值
3. **修正器交互** — 8个乘法修正器是否会产生过度放大？是否需要归一化层？
4. **种族协同的衰减** — 同种族第10个随从的价值增量应该远小于第1个，如何建模？
5. **性能预算** — 8个修正器×10张手牌=80次计算/评估，是否在1ms内完成？

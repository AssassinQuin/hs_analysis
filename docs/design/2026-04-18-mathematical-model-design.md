---
date: 2026-04-18
topic: "Complete Mathematical Model for Hearthstone EV Decision Engine"
status: research-v1
references:
  - García-Sánchez et al. (2019) "Optimizing Hearthstone Agents using an EA" — 2018 competition runner-up
  - Sakurai & Hasebe (2023) "Decision-Making in Hearthstone Based on RHEA" — 97.5% win rate
  - Świechowski et al. (2018) "Improving Hearthstone AI by Combining MCTS and SL"
  - Ganzfried & Sun (2016) "Bayesian Opponent Exploitation in Imperfect-Information Games"
  - Silverfish AI — state evaluation, move pruning, opponent modeling
  - 2020 Hearthstone AI Competition — 1st: 2-Step Lookahead (72.3%), 2nd: Dynamic Lookahead (70.9%)
---

# 炉石传说完备数学决策模型

## 0. 问题形式化

炉石传说的决策问题可以形式化为一个**部分可观测马尔可夫决策过程 (POMDP)**：

```
POMDP = (S, A, T, R, Ω, O, γ)

S = 所有游戏状态的集合（完整状态，包括双方手牌、牌库顺序）
A = 所有可能的动作集合（打牌、攻击、英雄技能、结束回合）
T(s'|s,a) = 状态转移函数（包含随机性：随机效果、抽牌顺序）
R(s,a,s') = 即时奖励函数
Ω = 观测空间（玩家能看到的：己方手牌、场面、对手手牌数量等）
O(o|s',a) = 观测函数
γ = 折扣因子（未来回合价值的衰减率）
```

**核心挑战**：对手手牌和双方牌库顺序不可观测 → 需要信念状态 (belief state) 建模。

**目标**：在每个决策点，选择使期望总奖励最大的动作：

```
π*(s) = argmax_a E[Σ_{t=0}^{T} γ^t × R(s_t, a_t, s_{t+1}) | a_0 = a, s_0 = s]
```

---

## 1. 状态表示 (State Representation)

### 1.1 完整状态向量

```
S = (S_self, S_opp, S_shared)

S_self = {
    hero_hp, hero_armor,                          # 英雄状态
    mana_available, mana_overloaded,              # 法力值
    board[1..7]: {attack, health, keywords,       # 场面随从
                  enchantments, can_attack},
    hand[1..10]: {cost, card_value,               # 手牌
                  card_text_effects},
    deck_remaining,                               # 牌库剩余
    weapon: {attack, durability},                  # 武器
    fatigue_counter,                              # 疲劳计数
    quest_progress[],                             # 任务进度
    imbue_level,                                  # 灌注等级
}

S_opp = {
    hero_hp, hero_armor,
    board[1..7]: {attack, health, keywords, enchantments},
    hand_count,                                   # 只知道数量，不知道具体
    deck_remaining,
    weapon: {attack, durability},
    class,                                        # 已识别的职业
    secrets[],                                    # 已挂奥秘（数量已知，内容未知）
}

S_shared = {
    turn_number,
    cards_played_this_turn,
    minions_died_this_turn,
    damage_dealt_to_enemy_hero_this_turn,
}
```

### 1.2 信念状态 (Belief State) — 处理隐藏信息

由于对手手牌和牌库内容未知，我们需要维护一个概率分布：

```
Belief(t) = {
    P(opponent_deck = deck_i | observations)     # 贝叶斯牌组推断
    P(opponent_hand = hand_j | deck_i, seen)     # 给定牌组的手牌分布
    P(opponent_secret = secret_k | context)       # 奥秘概率分布
}
```

---

## 2. 状态评估函数 (State Evaluation Function)

### 2.1 核心公式

将完整状态映射为单一数值优势评分：

```
V(S) = Σ w_i × f_i(S)
```

**权重通过进化算法 / 经验调参 / 回归学习确定。**

### 2.2 各分量定义

```
V(S) = w_hero × hero_advantage
     + w_board × board_advantage
     + w_hand × hand_advantage
     + w_tempo × tempo_score
     + w_threat × threat_score
     + w_fatigue × fatigue_factor
```

#### 2.2.1 英雄优势 (Hero Advantage)

```
hero_advantage = (HP_self + armor_self) - (HP_opp + armor_opp) × aggression_factor

aggression_factor = {
    1.0                          默认
    1.3                          当对手 HP ≤ 15（可斩杀范围）
    1.5                          当我方手牌有直伤且法力够用
}
```

#### 2.2.2 场面优势 (Board Advantage)

```
board_advantage = Σ_minion_self value_of(m) - Σ_minion_opp threat_of(m)
```

**随从价值函数**（综合 Silverfish + 进化算法论文）：

```
value_of(m) = w_atk × m.attack + w_hp × m.health
            + Σ_keyword w_kw × keyword_bonus(m)
            + w_survival × survival_prob(m)
            + w_effect × effect_value(m)
```

**关键词加成**（基于进化算法论文的权重表）：

| 关键词 | 权重 | 理由 |
|--------|------|------|
| 嘲讽 | 0.8-1.2 | 保护英雄和关键随从 |
| 突袭 | 1.0-1.5 | 即时场面影响力 |
| 冲锋 | 1.2-1.8 | 可以直接打脸 |
| 圣盾 | 1.5-2.0 | 等价于多一条命 |
| 潜行 | 0.8-1.2 | 保证存活一回合 |
| 风怒 | 1.0-1.5 | 双倍输出 |
| 吸血 | 0.8-1.2 | 回复价值 |
| 亡语 | 0.5 × 亡语EV | 需要触发概率 |
| 剧毒 | 1.5-2.0 | 高威胁 |
| 复生 | 0.6-0.8 | 额外存活 |

**生存概率**（Sub-Model D 触发概率模型）：

```
survival_prob(m) = 1.0                                       如果潜行且本回合未攻击
                 × (1 + 0.2)                                  如果嘲讽
                 × P(m不会被对手伤害法术击杀)                    基于对手剩余法力
                 × P(m不会被对手随从交换击杀)                    基于对手场面

P(不会被随从交换击杀) = 1 - max_{enemy_e} P(e能杀死m)
P(e能杀死m) = P(e攻击m) × min(1, e.attack / m.health)
```

#### 2.2.3 手牌优势 (Hand Advantage)

```
hand_advantage = Σ_card_in_hand card_play_value(c)

card_play_value(c) = V2_card_score(c) × playability(c)

playability(c) = P(能在下N回合内打出c)
               = P(mana_available ≥ c.cost within N turns)
```

**手牌协同效应**（Sub-Model A）：

```
hand_synergy = Σ_{i,j in hand} synergy(c_i, c_j)

synergy(c_i, c_j) = {
    +1.0    如果 c_i 是龙牌 且 c_j 有"如果你手牌中有龙牌"条件
    +0.5    如果 c_i + c_j 形成连击 (combo pieces)
    +0.3    如果 c_i 能 buff c_j (如手牌中的随从)
}
```

#### 2.2.4 节奏评分 (Tempo Score)

```
tempo_score = mana_efficiency + board_development_rate

mana_efficiency = Σ mana_spent_this_turn / mana_available
                （理想情况 = 1.0，充分利用每一点法力）

board_development_rate = (minions_played_this_turn × 0.3)
                       + (total_stats_summoned_this_turn × 0.1)
```

#### 2.2.5 威胁评分 (Threat Score) — Sub-Model B

```
threat_score = lethal_threat + board_control_threat

lethal_threat = P(can_kill_opponent_this_turn)
              = max over {action_sequences} P(enemy_hero_hp → 0)

board_control_threat = Σ_{enemy_m} threat_weight(m)

threat_weight(m) = (m.attack × (1 + rush/charge_bonus)) / m.health
                 × importance_factor(m)

importance_factor(m) = {
    1.5    如果 m 有亡语
    1.3    如果 m 有光环效果
    1.2    如果 m 有圣盾
    1.0    普通
}
```

### 2.3 基于论文的权重优化

进化算法论文（García-Sánchez 2019）定义了 **21 个权重参数**：

```
动作评分 = w₁ × Δhero_hp_opp + w₂ × Δhero_hp_self
         + w₃ × Δminion_count_self + w₄ × Δminion_count_opp
         + w₅ × Δtotal_attack_self + w₆ × Δtotal_attack_opp
         + w₇ × Δtotal_health_self + w₈ × Δtotal_health_opp
         + w₉ × Δhand_size_self + w₁₀ × Δhand_size_opp
         + w₁₁ × Δarmor_self + w₁₂ × Δweapon_durability
         + w₁₃ × draw_value + w₁₄ × secret_value
         + w₁₅ × keyword_value_self + w₁₆ × keyword_value_opp
         + w₁₇ × mana_efficiency + w₁₈ × board_full_penalty
         + w₁₉ × overkill_penalty + w₂₀ × tempo_value
         + w₂₁ × future_turn_value
```

这些权重 w₁...w₂₁ ∈ [0, 1]，通过**竞争协同进化**自动优化。

---

## 3. 动作期望值计算 (EV Calculation)

### 3.1 一般公式

对于动作 a 在状态 S 下的期望值：

```
EV(a, S) = Σ_{s'} P(s'|s,a) × [R(s,a,s') + γ × V(s')]
         = R_immediate(a, S) + γ × E[V(s')]
```

展开为：

```
EV(a, S) = V(S_after_a) - V(S_before_a)
```

### 3.2 按效果类型分类的 EV 公式

#### 确定性效果（Sub-Model A 直连）

```
EV_deterministic(a, S) = V(apply(a, S)) - V(S)
```

例：火球术造成6伤害 = `V(S') - V(S)`，其中 S' 中对手英雄 HP - 6。

#### 随机目标效果（Sub-Model D）

```
EV_random_target(a, S) = Σ_{t ∈ targets} P(target=t) × [V(S'_t) - V(S)]

其中 P(target=t) = 1 / |valid_targets|
```

#### Discover 效果（Sub-Model F + G）

```
EV_discover(card, pool, S) = E[max(V(c₁), V(c₂), V(c₃))]

使用顺序统计量：
E[max of k draws from pool] = Σ_{i=1}^{N} v_i × [i^k - (i-1)^k] / N^k

其中 pool 中卡牌按 V2 分数排序: v₁ ≤ v₂ ≤ ... ≤ v_N
k = 3 (Discover 给3张选1)
```

**考虑手牌上下文调整**（Sub-Model A + Tier 2）：

```
EV_discover_adjusted = EV_discover × context_multiplier

context_multiplier = {
    1.3    如果手牌 ≤ 3（资源稀缺）
    1.0    默认
    0.8    如果手牌 = 10（可能爆牌）
}
```

#### 条件效果（Sub-Model D）

```
EV_conditional(a, S) = P(condition_met) × V(if_met) + (1 - P(condition_met)) × V(if_not_met)

P(condition_met) 的估计方法：
- "如果你手牌中有龙牌" → P = count_dragons(hand) > 0 ? 1.0 : 0.0
- "如果你的英雄在本回合中受到过伤害" → P 基于对手场面威胁估计
- "每有一个友方随从" → count = len(friendly_minions)
```

#### 延迟效果（Sub-Model C）

```
EV_deferred(a, S) = immediate_value + Σ_{n=1}^{T} γ^n × P(effects_triggers_at_turn_n) × value_at_turn_n

γ = 0.85（每回合折扣因子，来自金融DCF模型）

例：武器 = atk × min(durability, expected_swings) × survival_prob
   奥秘 = effect_value × P(triggered) × avg_turn_discount
```

#### 玩家选择效果（Sub-Model G）

```
EV_choose_one(a, S) = max(option_A_value, option_B_value)

option_value = V(S_after_playing_option) - V(S)

特殊：范达尔·鹿盔在场时 = option_A_value + option_B_value
```

### 3.3 嵌套随机性

当效果形成链时（如 Discover → 打出发现的牌 → 该牌有随机效果）：

```
EV_nested(chain, S) = Σ_{c ∈ discover_pool} P(c_is_best_option) × [V_immediate(c) + γ × EV_of_playing_c]

简化：深度限制为2层，超出部分用 Tier 1 预计算值代替。
```

---

## 4. 隐藏信息处理 (Hidden Information)

### 4.1 信息集 (Information Sets)

信息集 I(s) 是玩家无法区分的所有可能状态：

```
I(s) = {s' ∈ S : observation(s') = observation(s)}
```

即：所有对手手牌和牌库排序不同的状态，但己方观测相同。

### 4.2 对手手牌建模

对手手牌未知，但可以通过以下信息推断：

```
P(opponent_hand = H | observations) = ?

观察到的信息：
1. 对手职业
2. 对手已打出的牌
3. 对手手牌数量
4. 对手每个回合的打法（用了多少费，是否用英雄技能）
5. 当前回合数
```

**简化方法**：不枚举具体手牌组合，而是**通过牌组推断间接估计**：

```
P(opponent_has_card_X) = P(deck_i | seen) × count(X in remaining_deck_i) / remaining_deck_i_size
```

### 4.3 对手牌组推断 — 贝叶斯框架 (Sub-Model E)

这是数学模型中最关键的部分。

#### 先验分布

```
初始先验：P(deck_i) = usage_rate_i / Σ usage_rates
```

数据来源：HSReplay API 每日更新各职业 Top 5 流行卡组 + 使用率。

#### 贝叶斯更新

```
对手打出卡牌 X 后：

P(deck_i | seen_X) = P(seen_X | deck_i) × P(deck_i) / P(seen_X)

其中：
P(seen_X | deck_i) = count(X in deck_i) / 30
P(seen_X) = Σ_j P(seen_X | deck_j) × P(deck_j)
```

#### 多张观察的累积更新

```
对手打出 X₁, X₂, ..., X_n 后：

P(deck_i | X₁, ..., X_n) ∝ P(deck_i) × Π_{k=1}^{n} P(X_k | deck_i, X₁,...,X_{k-1})
```

#### 锁定阈值

```
当 max_i P(deck_i) > 0.60 时，锁定为该卡组：
  → 使用该卡组的完整30张牌列表
  → 可以精确预测对手剩余手牌/牌库
```

**关键数学性质**（来自 Ganzfried & Sun 2016）：

> **定理**: 对抗后验分布的期望收益 = 对抗后验均值的期望收益
>
> 即：`E_{σ~posterior}[u(π, σ)] = u(π, E[σ])`
>
> 含义：只需要跟踪后验均值（每个策略的期望概率），不需要跟踪整个分布。

这意味着我们可以简化计算——只需维护每个候选牌组的概率，而非完整的手牌分布。

### 4.4 奥秘概率分布

```
P(secret = s_k | class, turn, board_state)

= P(s_k | class) × context_adjustment(s_k)

先验（从 HSReplay 统计各职业各奥秘使用率）：
  法师：法术反制 30%, 爆炸符文 25%, 寒冰护体 20%, ...
  
上下文调整：
  如果我方场上有大随从 → 消灭类奥秘概率 ×1.5
  如果我方准备打脸 → 冰冻陷阱/爆炸陷阱概率 ×1.3
  如果我方法术多 → 法术反制概率 ×1.5
```

---

## 5. 对手回合预测 (Opponent Turn Prediction)

### 5.1 预测框架

```
给定推断的对手牌组 deck_i（概率 P_i）：

opponent_remaining = deck_list - cards_seen - cards_in_opponent_hand

predicted_plays(turn_mana) = filter(opponent_remaining, cost ≤ turn_mana)
                           → sort by V2_score descending
                           → top 3 plays
```

### 5.2 威胁预测对我方 EV 的影响

```
如果对手预测的下一回合最高威胁为 T_opponent：

defensive_premium = {
    1.5 × T_opponent        如果我方 HP 低且有AOE可用
    1.2 × T_opponent        如果需要解场
    1.0                      默认（不需要防守）
}
```

### 5.3 两回合前瞻中的对手建模

来自 Silverfish 的方法：在搜索树中模拟对手的回合。

```
在 depth=2 的搜索中：

Level 0: 我方当前状态 S₀
Level 1: 枚举我方动作 a₁ → 得到 S₁ (我方回合结束状态)
Level 2: 模拟对手最优响应 o₁ → 得到 S₂ (对手回合结束状态)
Level 3: 评估 V(S₂)

EV(a₁, S₀) = V(S₂) × α + V(S₁) × (1 - α)
α = 0.50 (Silverfish 默认：下一回合权重 50%)
```

对手响应模拟：

```
对手动作生成（简化版）：
1. 解场优先：攻击能被我方随从击杀的敌方随从
2. 打出能打出的最高价值手牌
3. 英雄技能（如果有剩余法力）
```

---

## 6. 决策搜索树 (Decision Tree & Search)

### 6.1 动作枚举

```
Actions(S) = play_actions(S) + attack_actions(S) + hero_power(S) + end_turn(S)

play_actions:  对每张手牌 c，如果 mana ≥ c.cost:
               - 如果 c 需要目标：对每个合法目标生成一个动作
               - 否则：一个动作
               
attack_actions: 对每个可攻击的友方随从 m：
               - 对每个可攻击的敌方目标 t：attack(m, t)
               - 英雄攻击（如果有武器）

hero_power:   如果法力够且本回合未使用
```

**典型动作数量**：5-30 个（中期回合）。

### 6.2 搜索算法 — Top-K Beam Search

2020年竞赛冠军使用的是 **2步前瞻 (2-Step Lookahead)**，我们采用改进版：

```
Algorithm: Top-K Beam Search with Opponent Modeling

Input: Current state S, beam width K=8, depth D=2

1. Enumerate all legal actions A = {a₁, ..., aₙ}
2. For each a ∈ A:
   S' = apply(a, S)
   score(a) = V(S') + random_effect_EV(a, S')    # Tier 1 + Tier 2
3. Keep top-K actions: A_top = {a₁*, ..., a_K*}
4. For each a_i* ∈ A_top:
   S_i' = apply(a_i*, S)
   Opp_response = predict_opponent_turn(S_i')     # 对手建模
   S_i'' = apply_opponent_response(S_i', Opp_response)
   final_score(a_i*) = α × V(S_i'') + (1-α) × V(S_i')
5. Return argmax(final_score)
```

### 6.3 剪枝策略

来自 Silverfish 和竞赛论文的剪枝技巧：

```
剪枝规则（在动作枚举阶段就过滤）：

1. 过杀剪枝：不使用伤害 > 目标HP×1.5 的法术打随从
   （例外：如果额外伤害溢出到英雄，保留）

2. 重复剪枝：如果两个动作产生相同的最终场面，只保留法力效率更高的

3. 显然劣质剪枝：
   - 不用英雄攻击有剧毒的随从
   - 不把buff给即将死亡的随从（除非有特殊理由）
   - 不在空场上使用群体buff

4. 法力效率剪枝：
   如果 score(a)/cost(a) < 0.3 × max_{a'} score(a')/cost(a')，剪掉

5. 置信度剪枝（Alpha-Beta 变体）：
   如果当前分支的 EV 低于当前最优分支的 50%，剪掉
```

### 6.4 复杂度分析

```
动作数: |A| ≈ 10-30 (典型中期)
Beam width: K = 8
Depth: D = 2 (我方1步 + 对手1步)

总评估数: |A| + K × |Opp_A| ≈ 30 + 8 × 20 = 190 次状态评估

每次评估: O(7 + 7 + 10) = O(24) 操作（遍历场面+手牌）

总复杂度: O(190 × 24) ≈ O(4,560) 算术运算

目标: < 3秒 → 每秒 >1,500 次评估 → 非常可行
```

---

## 7. 完整 EV 计算流水线

```
┌───────────────────────────────────────────────────────────┐
│                    输入：当前观测状态                        │
│  己方场面、手牌、牌库剩余、英雄状态                          │
│  对手场面、手牌数量、职业、奥秘、英雄状态                    │
└─────────────────────┬─────────────────────────────────────┘
                      │
          ┌───────────▼───────────┐
          │ Step 1: 对手建模        │
          │ 贝叶斯牌组推断          │
          │ P(deck_i | observed)    │
          │ 奥秘概率分布            │
          │ 预测对手下回合打法       │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │ Step 2: 动作枚举+剪枝   │
          │ 生成所有合法动作         │
          │ 应用剪枝规则过滤         │
          │ 结果: 10-30 候选动作     │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │ Step 3: 对每个动作      │
          │ 计算综合 EV:           │
          │                        │
          │ EV(a) = Tier1(a)       │ ← 预计算查表
          │       + Tier2(a, S)    │ ← 状态感知调整
          │       + SubModel_A-G   │ ← 7个子模型
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │ Step 4: Top-K 前瞻     │
          │ 取 EV 最高的 K=8 动作   │
          │ 对每个模拟对手回合       │
          │ 计算 V(S_after_opp)    │
          │ 综合评分               │
          └───────────┬───────────┘
                      │
          ┌───────────▼───────────┐
          │ Step 5: 排序+输出       │
          │ 按综合EV降序排列         │
          │ 输出 Top-5 决策         │
          │ 每个附带EV+推理原因      │
          └───────────────────────┘
```

### 7.1 综合EV公式

```
最终EV(a, S) = EV_base(a, S)             # V2模型 + Tier 1预计算
             × meta_factor(S)             # Sub-Model E: 对手建模调整
             + EV_random(a, S)            # Sub-Model D/F: 随机效果EV
             × state_factor(S)            # Sub-Model A: 场面上下文
             + EV_deferred(a, S)          # Sub-Model C: 延迟效果折现
             + EV_conditional(a, S)       # Sub-Model D: 条件概率
             + EV_threat_reduction(a, S)  # Sub-Model B: 威胁消除价值
             + EV_choice(a, S)            # Sub-Model G: 抉择最优值
             + α × EV_lookahead(a, S)     # Tier 3: 前瞻（α=0.50）
```

---

## 8. 实现可行性分析

### 8.1 计算资源预算

| 组件 | 预计耗时 | 频率 |
|------|---------|------|
| 贝叶斯牌组推断更新 | < 1ms | 每次对手出牌 |
| 动作枚举+剪枝 | < 5ms | 每回合 |
| 单次状态评估 V(S) | < 0.1ms | 每个动作 |
| Discover EV查表 | < 0.01ms | 每个Discover效果 |
| Top-8前瞻 (含对手模拟) | < 500ms | 每回合 |
| **总计** | **< 1秒** | **每回合** |

### 8.2 内存预算

| 数据 | 大小 |
|------|------|
| 984张卡牌数据 | ~2 MB |
| V2卡牌分数缓存 | ~100 KB |
| Discover牌池预计算 | ~5 MB |
| HSReplay Top5牌组缓存 | ~200 KB |
| 贝叶斯概率矩阵 | ~50 KB |
| **总计** | **< 10 MB** |

### 8.3 与学术方案对比

| 方案 | 方法 | 胜率 | 决策时间 | 需要模拟器 |
|------|------|------|---------|-----------|
| 2020冠军 (Miller) | 2-Step Lookahead | 72.3% | ~2s | ✅ Sabberstone |
| 2020亚军 (Bohnhof) | Dynamic Lookahead | 70.9% | ~2s | ✅ Sabberstone |
| EA Agent (García-Sánchez) | 进化算法+贪心 | ~68% | <1s | ✅ Sabberstone |
| RHEA (Sakurai 2023) | 滚动进化 | 97.5%* | ~2s | ✅ 自建 |
| MCTS+NN (Świechowski) | MCTS+监督学习 | ~65% | ~3s | ✅ 自建 |
| **我们的方案** | **EV分析+贝叶斯** | **目标 70%+** | **< 2s** | **❌ 不需要** |

*RHEA 97.5% 是在特定牌组（Midrange Jade Shaman）上对固定对手的结果

### 8.4 我们方案的独特优势

1. **不需要完整模拟器** — 所有其他方案都依赖游戏模拟器（Sabberstone/自建）
2. **可解释的数学模型** — 每个决策都有EV+原因，不像MCTS/NN是黑盒
3. **实时运行** — 纯数学计算，不依赖游戏状态模拟
4. **可增量更新** — 新卡牌发布只需更新数据，不需要重新训练模型
5. **贝叶斯对手建模** — 其他方案大多没有对手建模，或只是简单的贪心模拟

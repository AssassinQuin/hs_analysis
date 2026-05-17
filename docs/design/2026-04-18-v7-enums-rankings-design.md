---
date: 2026-04-18
topic: "V7 模型升级：enums 类型 + rankings 权重融合"
status: validated
---

## Problem Statement

当前 V2 评分模型存在三大缺陷：

1. **随从类型（race）完全未参与评分** — 630 张随从卡的种族信息被忽略
2. **50+ 关键字中只覆盖了 29 个** — FORGE、EXCAVATE、TITAN 等新机制未纳入
3. **权重全靠手工设定** — 没有利用 HSReplay 真实对战数据校准

数据源已就绪：
- `hearthstone_enums.json`：13 种随从类型、7 种法术派系、50+ 关键字定义
- `HSReplay_Card_Rankings.xlsx`：1000 张卡的 deck_wr、played_wr、include_rate、play_count

## Constraints

- 保持 V2 五层架构（L1-L5）的兼容性，在 L2 和 L3 上扩展
- Rankings 数据只有 1000 张卡（部分卡缺数据），需要 fallback 到模型评分
- 不能破坏现有的下游消费者（L6、composite_evaluator、RHEA）
- 法术派系字段（spellSchool）在 unified_standard.json 中为空，需从卡牌文本反推

## Approach

### 扩展方案：V2 → V7 增量升级

**不重写 V2，而是在其基础上增加 3 个增强层：**

- **L2+ 关键字扩展**：基于 enums.json 更新 KEYWORD_TIERS，新增 ~20 个关键字
- **L2.5 类型协同层**：随从种族 + 法术派系的价值评估
- **L3+ 类型条件解析**："发现一张龙牌" vs "发现一张法术牌" 的差异化评分
- **L7 Rankings 校准层**：用 HSReplay 真实胜率数据校准模型分数

### 为什么不另起炉灶

V2 的五层模型已经能产出合理的评分，问题出在覆盖度和权重校准上。
增量升级更安全，且能保持与下游的兼容性。

## Architecture

### 数据流

```
hearthstone_enums.json ──→ L2+ 关键字扩展 + L2.5 类型评分
                                     ↓
HSReplay_Card_Rankings.xlsx ──→ L7 Rankings 校准
                                     ↓
unified_standard.json ──→ v2_scoring_engine.py (V7) ──→ v7_scoring_report.json
```

### L2+ 关键字层级扩展

基于 enums.json 的 50 个关键字，重新分三级：

| 层级 | Base | 关键字（新增用 ★ 标记） |
|------|------|------------------------|
| **power** | 1.5 | BATTLECRY, DEATHRATTLE, DISCOVER, DIVINE_SHIELD, RUSH, CHARGE, WINDFURY, TAUNT, LIFESTEAL, STEALTH, CHOOSE_ONE, QUEST, ★FORGE, ★EXCAVATE, ★QUICKDRAW, ★TITAN, ★ECHO |
| **mechanical** | 0.75 | TRIGGER_VISUAL, AURA, COLOSSUS, REBORN, IMBUE, OUTCAST, IMMUNE, SECRET, OVERLOAD, COMBO, SPELLPOWER, FREEZE, POISONOUS, SILENCE, TRADEABLE, SIDE_QUEST, START_OF_GAME, ★SPELLBURST, ★FRENZY, ★CORRUPT, ★DREDGE, ★INFUSE, ★HONORABLE_KILL, ★OVERHEAL, ★MANATHIRST, ★OVERKILL, ★INSPIRE, ★MAGNETIC, ★TWINSPELL, ★MINIATURIZE, ★GIGANTIFY, ★MORPH, ★COUNTER |
| **niche** | 0.5 | VENOMOUS, CANT_ATTACK, AVENGE, ENRAGED, JADE_GOLEM, END_OF_TURN_TRIGGER, START_OF_COMBAT, START_OF_GAME_KEYWORD, COLLECTIONMANAGER_FILTER_MANA_EVEN/ODD |

注意：VENOMOUS 和 POISONOUS 在中文里都是"剧毒"，合并处理。

### L2.5 类型协同层

**随从种族价值**：基于类型在环境中的流行度和协同深度

| 种族 | 中文 | 基础协同值 | 说明 |
|------|------|-----------|------|
| BEAST | 野兽 | 1.2 | 最多种族卡牌(76)，协同广泛 |
| DRAGON | 龙 | 1.3 | 龙体系完善，手牌触发强 |
| DEMON | 恶魔 | 1.2 | 术士核心，自伤协同 |
| ELEMENTAL | 元素 | 1.1 | 连续打出协同 |
| UNDEAD | 亡灵 | 1.1 | 死亡骑士核心 |
| MURLOC | 鱼人 | 1.3 | 鱼人体系爆发力强 |
| MECHANICAL | 机械 | 1.0 | 磁力协同 |
| NAGA | 纳迦 | 1.1 | 法术协同 |
| PIRATE | 海盗 | 1.2 | 武器/节奏协同 |
| TOTEM | 图腾 | 1.0 | 萨满专属 |
| DRAENEI | 德莱尼 | 1.0 | 新种族 |
| QUILBOAR | 野猪人 | 1.0 | 稀有种族 |

公式：
```
L2_5_race = race_bonus × (1 + 0.05 × mana_cost)
```

**法术派系价值**：基于派系的法术质量和池子大小

| 派系 | 中文 | 基础值 |
|------|------|--------|
| FIRE | 火焰 | 1.0 |
| FROST | 冰霜 | 1.0 |
| ARCANE | 奥术 | 1.0 |
| NATURE | 自然 | 1.1 |
| SHADOW | 暗影 | 1.0 |
| HOLY | 神圣 | 1.0 |
| FEL | 邪能 | 1.0 |

法术派系不在 unified_standard.json 中，需要从卡牌文本和职业推断。

### L3+ 类型条件解析

新增效果模式：类型约束的发现/生成

| 模式 | Regex | 价值修正 |
|------|-------|----------|
| discover_race | `发现.*?(龙\|恶魔\|野兽\|鱼人\|海盗\|元素\|亡灵\|图腾\|机械\|纳迦\|德莱尼)` | +1.0（窄池=高质量） |
| discover_spell | `发现.*?法术` | +0.5 |
| discover_weapon | `发现.*?武器` | +0.3 |
| discover_minion | `发现.*?随从` | +0.3 |
| discover_spell_school | `发现.*?(火焰\|冰霜\|奥术\|自然\|暗影\|神圣\|邪能)法术` | +0.8 |
| summon_race | `召唤.*?(龙\|恶魔\|野兽\|鱼人\|海盗\|元素\|亡灵\|图腾\|机械)` | +0.3（种族协同） |
| buff_race | `(龙\|恶魔\|野兽\|鱼人\|海盗\|元素\|亡灵\|图腾\|机械).*?\+` | +0.5（种族增益） |
| condition_race_in_hand | `手牌中有.*?(龙\|恶魔\|野兽\|鱼人\|海盗\|元素)` | 条件P=0.4，mult=1.5 |
| condition_spell_played | `使用一张.*?法术\|施放` | 条件P=0.6，mult=1.2 |

**核心原理**：池子越窄，发现/生成的平均质量越高。
- "发现一张龙牌"（73 张中的 best-of-3）>> "发现一张随从牌"（630 张中的 best-of-3）当龙牌平均质量高时
- 但这只是修正，不是替代 — 基础发现价值仍在 L2 的 DISCOVER 关键字中

### L7 Rankings 校准层

**数据源**：`HSReplay_Card_Rankings.xlsx`（总排行 + 11 职业分表）

**列定义**：
- `deck_wr`：含卡组胜率(%) — 卡牌在卡组中时该卡组的平均胜率
- `played_wr`：打出时胜率(%) — 这张卡被打出时的对局胜率
- `include_rate`：卡组包含率(%) — 多少比例的卡组带这张卡
- `play_count`：出场次数 — 数据置信度

**融合公式**：

```python
# 标准化到 [0, 1]
norm_deck_wr = (deck_wr - min_deck_wr) / (max_deck_wr - min_deck_wr)
norm_played_wr = (played_wr - min_played_wr) / (max_played_wr - min_played_wr)

# 置信度权重（基于出场次数）
confidence = min(1.0, log10(1 + play_count) / log10(1 + max_play_count))

# 混合权重
alpha = 0.5  # 模型权重
beta = 0.3   # 含卡组胜率权重
gamma = 0.2  # 打出时胜率权重

# 模型分数标准化
norm_model = (v2_score - min_v2) / (max_v2 - min_v2)

# 最终融合
data_weight = beta * norm_deck_wr + gamma * norm_played_wr
V7 = norm_model * (alpha + (1 - alpha) * (1 - confidence)) + data_weight * confidence
```

**无 Rankings 数据的卡牌**：直接使用 V2 模型评分（alpha=1.0）。

## Components

### 1. `scripts/v7_scoring_engine.py`（主文件）

**职责**：
1. 加载 enums.json 构建扩展关键字映射
2. 加载 rankings.xlsx 构建真实数据查找表
3. 执行 V7 评分管道
4. 输出 v7_scoring_report.json

**关键变更（相对 V2）**：
- `KEYWORD_TIERS`：从 29 → 50 个关键字
- 新增 `calc_race_synergy(card)`：L2.5 随从种族评分
- 新增 `calc_spell_school(card)`：L2.5 法术派系评分
- `EFFECT_PATTERNS`：新增 9 个类型条件模式
- `CONDITION_DEFS`：新增种族条件、法术条件
- 新增 `calc_rankings_calibration(card, model_score)`：L7 层
- `score_minion`：total = L1 + L2 + L2.5 + L3 + L3+ + L5，然后 L7 校准

### 2. 更新文件

**不修改** v2_scoring_engine.py（保持向后兼容）。

## Data Flow

```
1. 加载 enums.json → RACE_BONUS, SPELL_SCHOOL_MAP, 扩展 KEYWORD_TIERS
2. 加载 rankings.xlsx → RANKINGS_DB (dict[name] → {deck_wr, played_wr, include_rate, play_count})
3. 加载 unified_standard.json → cards list
4. For each card:
   a. L1: power_law(mana) vanilla curve (不变)
   b. L2: calc_keyword_score() — 使用扩展后的 KEYWORD_TIERS
   c. L2.5: calc_race_synergy() + calc_spell_school() — 新增
   d. L3: parse_text_effects() — 使用扩展后的 EFFECT_PATTERNS
   e. L3+: parse_type_conditions() — 新增
   f. L5: calc_conditional_ev() — 使用扩展后的 CONDITION_DEFS
   g. L7: calc_rankings_calibration() — 新增
   h. Total = L7(L1 + L2 + L2.5 + L3 + L3+ + L5)
5. 输出 v7_scoring_report.json
```

## Error Handling

- rankings.xlsx 中无匹配的卡 → L7 跳过，使用纯模型分数
- openpyxl 未安装 → 提示安装，fallback 到纯模型
- 卡牌无 race 字段 → L2.5 跳过（bonus=0）
- 法术派系无法推断 → L2.5 法术部分跳过
- 卡牌无 text 字段 → L3/L3+/L5 全部为 0

## Testing Strategy

1. **关键字覆盖度测试**：验证 enums.json 中所有 50 个关键字都有 tier 分配
2. **Rankings 融合测试**：手动构造已知数据，验证融合公式
3. **类型条件测试**：构造含"发现一张龙牌"等文本的测试卡
4. **回归测试**：V7 top 20 与 V2 top 20 对比，验证不会出现不合理的排名变动
5. **rankings 一致性**：deck_wr 高的卡应该在 V7 排名中更高
6. **Fallback 测试**：无 rankings 数据的卡应该得到与 V2 相同（或接近）的分数

## Open Questions

1. 法术派系推断准确度 — unified_standard.json 中没有 spellSchool 字段，只能从文本和职业推断
2. α/β/γ 融合权重最优值 — 初始 0.5/0.3/0.2 需要后续验证
3. Rankings 数据时效性 — 2026-04-18 数据，需要定期更新
4. 类型协同值的具体数值 — 需要环境数据验证

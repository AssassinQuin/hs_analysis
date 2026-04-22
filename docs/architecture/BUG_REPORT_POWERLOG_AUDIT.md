# Power.log 实时决策管道 — Bug 报告与优化方案

> 基于 Power.log (6.3MB, 23回合 Deathshadow Valeera vs Khadgar 对局) 的深度审计

## 对局概况

| 属性 | Player 0 (Valeera) | Player 1 (Khadgar) |
|------|-------------------|-------------------|
| 英雄 | CATA_190h (hp=30) | HERO_08b (hp=40) |
| 回合 23 场面 | 6 随从 (4/4, 7/7, 4/4×4) | 6 随从 (2/2×2, 1/1, 2/3T×2, 7/7) |
| 回合 23 手牌 | 7 张 (card_id 未知) | 10 张 (有 card_id) |
| 法力 | 0/10 | 1/10 |
| 牌库剩余 | 18 | 5 |

## Bug 分级

### 🔴 P0 — 致命缺陷（引擎从未在真实数据上运行过）

#### P0-1: StateBridge 字段名全部错误
**文件**: `analysis/watcher/state_bridge.py:126, 344`

`HeroState` 的字段是 `hp`/`max_hp`，但 bridge 写的是 `current_health`/`max_health`。
`Weapon` 的字段是 `attack`/`health`/`name`，但 bridge 写的是 `durability`/`max_damage`/`current_damage`。

**影响**: HeroState 构造抛 TypeError，被外层 try/except 吞掉，返回默认值 (hp=30, armor=0)。**引擎从未接收到真实的英雄状态。**

```python
# 当前 (错误)
return HeroState(current_health=current_health, max_health=max_health, ...)

# 修正
return HeroState(hp=current_health, max_hp=max_health, ...)
```

Weapon 同理：
```python
# 当前 (错误)
return Weapon(durability=durability, max_damage=max_damage, current_damage=current_damage)

# 修正
return Weapon(attack=attack, health=durability, name=entity.card_id or "")
```

#### P0-2: Charge/Rush 随从可无限攻击
**文件**: `analysis/search/rhea_engine.py:203`

```python
if not (can_act or minion.has_charge or minion.has_rush):
```

`has_charge` 是永久标记，不随攻击消耗。冲锋随从攻击后 `can_attack=False`，但 `has_charge=True` 仍通过检查 → 无限攻击。

**修正**: 改为依赖 `can_attack` 标记：
```python
if not minion.can_attack:
    continue
# 风怒二次攻击单独处理
if minion.has_windfury and minion.has_attacked_once:
    can_act = True
```

#### P0-3: 毒杀绕过免疫
**文件**: `analysis/search/rhea_engine.py:662`

```python
if source.has_poisonous and not target_had_divine_shield:
    target.health = 0  # 免疫随从也被秒杀
```

免疫应阻止所有攻击效果，包括毒杀。修正：
```python
if source.has_poisonous and not target_had_divine_shield and not target.has_immune:
    target.health = 0
```

#### P0-4: 伤害不消耗护甲
**文件**: `analysis/search/rhea_engine.py:637`

```python
s.opponent.hero.hp -= source.attack  # 护甲未减少
```

应先扣护甲再扣血：
```python
damage = source.attack
if s.opponent.hero.armor >= damage:
    s.opponent.hero.armor -= damage
else:
    damage -= s.opponent.hero.armor
    s.opponent.hero.armor = 0
    s.opponent.hero.hp -= damage
```

#### P0-5: 潜行随从可被攻击
**文件**: `analysis/search/rhea_engine.py:241`

枚举攻击目标时未过滤 `has_stealth`，生成了非法动作。

### 🟠 P1 — 严重缺陷（状态不准/功能缺失）

| ID | 文件 | 问题 |
|----|------|------|
| P1-1 | state_bridge:143 | 法力可用量未扣除过载，`TEMP_RESOURCES` 未提取 |
| P1-2 | state_bridge:243 | 手牌过滤只保留 MINION/SPELL，丢弃 WEAPON/HERO/LOCATION |
| P1-3 | state_bridge:265 | `card_type` 存为 CardType IntEnum，引擎调用 `.upper()` 崩溃 |
| P1-4 | state_bridge | 未提取 hero_power_used/cost/damage/imbue_level |
| P1-5 | rhea_engine:282 | 英雄技能无目标选择（法师/牧师等需定向） |
| P1-6 | rhea_engine:509 | 冻结永远作用于 board[0]，非目标随从 |
| P1-7 | state_bridge | Locations、Secrets、对手牌库数未提取 |
| P1-8 | state_bridge:229 | Minion 无 `card_id` 字段，卡牌ID丢失 |
| P1-9 | rhea_engine:1248 | 负 fitness 时置信度计算为负值 |

### 🟡 P2 — 优化项（不致命但影响质量）

| ID | 文件 | 问题 |
|----|------|------|
| P2-1 | rhea_engine:843 | END_TURN 时疲劳重置为 0，应递增 |
| P2-2 | rhea_engine:856 | 无条件清除免疫（寒冰屏障等跨回合免疫丢失） |
| P2-3 | rhea_engine:761 | 英雄技能伤害未计入法术强度 |
| P2-4 | rhea_engine:639 | 吸血回血上限硬编码 30，忽略英雄牌加血 |
| P2-5 | state_bridge:287 | 牌库剩余计算公式错误 |
| P2-6 | rhea_engine | LOCATION 卡牌未枚举合法动作 |
| P2-7 | state_bridge | 手牌 card_id 为空时无 fallback 查询 |

## Power.log 对局分析发现

从 Power.log 的 23 回合对局中观察到的实际问题：

1. **手牌提取完全失败**: Player 0 有 7 张手牌但 bridge 提取出 0 张（card_type IntEnum 比较失败）
2. **Player 1 部分成功**: P1 有 10 张手牌，其中 6 张有 card_id（SPELL/type=5），4 张无 card_id
3. **场面随从 card_id 丢失**: Minion dataclass 无 card_id 字段，bridge 写入的 card_id 属性无人读取
4. **英雄职业缺失**: `hero_class` 始终为空字符串
5. **武器未检测**: 场上可能存在武器但因 Weapon 构造错误无法提取

## 优化方案

### Batch 1: 修复 Bridge（4-5h）— 最高优先级

**目标**: 让引擎首次在真实数据上正确运行

1. 修复 `HeroState` 构造 (hp/max_hp 字段名)
2. 修复 `Weapon` 构造 (attack/health/name 字段名)
3. 修复手牌提取：
   - 扩展 card_type 过滤：MINION/SPELL/WEAPON/HERO/LOCATION
   - `card_type` 从 CardType IntEnum 转为字符串：`CardType(card_type).name`
   - Card 构造时 `id` 字段 → `dbf_id`（Card dataclass 的实际字段名）
4. Minion 增加 `card_id` 字段，或在 `name` 中存储 card_id
5. 法力提取增加过载扣除和临时水晶
6. 提取英雄技能状态（used/cost/damage）

### Batch 2: 修复引擎 Bug（3-4h）

1. 修复 Charge/Rush 无限攻击 (P0-2)
2. 修复毒杀绕过免疫 (P0-3)
3. 修复伤害不消耗护甲 (P0-4)
4. 修复潜行目标过滤 (P0-5)
5. 修复冻结目标选择 (P1-6)
6. 修复负 fitness 置信度 (P1-9)

### Batch 3: 增强功能（3-4h）

1. 英雄技能目标选择 (P1-5)
2. Location 卡牌枚举 (P2-6)
3. Secret 提取 (P1-7)
4. 对手牌库数提取 (P1-7)
5. 疲劳递增修正 (P2-1)
6. 吸血上限修正 (P2-4)

### 验证标准

每个 Batch 完成后需通过：
- Power.log 全对局分析无异常
- 手牌数 = 实际手牌数
- 场面随从 card_id 正确
- 法力计算含过载
- 英雄 HP/护甲正确
- RHEA 搜索在真实状态上产出合理决策
- 654+ 测试全部通过

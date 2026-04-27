> **本文件功能**: 记录 4 个成熟炉石模拟器（Fireplace/RosettaStone/SabberStone/MetaStone）的架构研究结论，以及对本项目重构的指导建议。

# 炉石模拟器架构调研报告

## 一、五大架构共识

### 1. Tag/GameTag 统一属性模型
所有项目都使用枚举 tag 索引属性，而非分散的布尔字段。

| 项目 | 实现 |
|------|------|
| Fireplace | `GameTag` 枚举 + `boolean_property`/`int_property` 装饰器 |
| RosettaStone | `map<GameTag, int>` 字典 |
| SabberStone | `EntityData[GameTag]` + `AuraEffects[GameTag]` 双层 |
| MetaStone | `EnumMap<GameTag, Object>` |

**hs_analysis 现状**: 三套并存（mechanics[]/KeywordSet/has_X 布尔）→ 应统一。

### 2. 双层加载架构
JSON/XML 静态属性 + 代码/DSL 动态效果是标准模式。

| 项目 | 静态层 | 动态层 |
|------|--------|--------|
| Fireplace | python-hearthstone XML | Python DSL 脚本类 |
| RosettaStone | cards.json | C++ CardSetsGen.cpp |
| SabberStone | CardDefs.xml | C# CardSets 注册 |
| MetaStone | JSON 卡牌文件 | Java Spell 类（反射加载） |

**hs_analysis 现状**: JSON 静态层已有（HearthstoneJSON），动态层缺失（card_abilities.json 不存在）→ 应补全。

### 3. Power 容器模式
一张卡的效果统一为 Power 对象，包含：

```python
# 通用 Power 结构
class Power:
    aura: Aura           # 光环（持续效果）
    enchant: Enchant     # 附魔（属性修改）
    trigger: Trigger     # 触发器（事件响应）
    power_task: list     # 战吼/使用效果
    deathrattle_task: list   # 亡语
    combo_task: list     # 连击
    spellburst_task: list    # 法术迸发
    # ...更多触发时机
```

### 4. Task/Spell 管道
可组合的原子操作链，通过中间数据栈传递数据：

```
IncludeTask → FilterTask → RandomTask → SummonTask
(收集实体)    (条件过滤)    (随机选择)    (执行召唤)
```

### 5. 事件驱动触发器
~30 种游戏事件通过 TriggerManager 广播，触发器订阅并响应：

```
GAME_START, TURN_START, TURN_END,
PLAY_CARD, CAST_SPELL, SUMMON, DEATH,
ATTACK, DEAL_DAMAGE, TAKE_DAMAGE, DRAW, DISCARD, ...
```

---

## 二、各项目核心创新

### Fireplace（最可借鉴 — Python 项目）

**声明式 DSL** — 一行代码定义完整卡牌效果：
```python
events = Attack(FRIENDLY_HERO).after(Buff(CONTROLLER, "BT_351e"))
play = Hit(TARGET, 3)
deathrattle = Give(CONTROLLER, "BT_407t")
```

**Selector 集合运算**:
```python
FRIENDLY_MINIONS + DRAGON - SELF    # 交集 + 差集
RANDOM(ENEMY_MINIONS - DEAD)        # 随机选取
```

**LazyNum 惰性计算**:
```python
ATK(SELF)                           # 运行时求值
Count(FRIENDLY_MINIONS) == 7        # 条件判断
```

### MetaStone（最接近用户需求 — 纯 JSON 驱动）

**JSON 中引用 Spell 类名+参数**:
```json
{
  "name": "Fireball",
  "type": "SPELL",
  "baseManaCost": 4,
  "spell": {"class": "DamageSpell", "value": 6}
}
```

**MetaSpell 组合模式**: 多个 Spell 嵌套组合复杂效果，80+ Spell 类型库。

**SpellDeserializer**: 通过反射 `Class.forName(spellClassName)` 动态加载。

---

## 三、对 hs_analysis 重构的指导

### 推荐路径：MetaStone 模式（JSON 数据驱动）+ Fireplace 风格（Python 友好）

#### 1. Tag 系统 → 统一为 GameTag 枚举 + 字典

**现状问题**: Minion 有 18 个 `has_X` 布尔字段，executor 有 `_KEYWORD_FIELD_MAP` 硬编码映射。

**目标方案**:
```python
# 替代 has_taunt, has_rush, has_divine_shield ... 18个字段
class Minion:
    def __init__(self):
        self.tags: dict[GameTag, int] = {}  # 统一属性存储
    
    def has_taunt(self) -> bool:
        return bool(self.tags.get(GameTag.TAUNT, 0))
```

**兼容策略**: 保留 `has_taunt` 等为 property，内部读 `tags[GameTag.TAUNT]`，避免全代码库修改。

#### 2. card_abilities.json → 参考 MetaStone 的 Spell 引用模式

```json
{
  "EX1_066": {
    "id": "EX1_066",
    "name": "Fear Doomguard",
    "abilities": [{
      "trigger": "BATTLECRY",
      "actions": [{
        "effect": "DAMAGE",
        "target": "RANDOM_ENEMY_CHARACTER",
        "value": 3
      }]
    }]
  }
}
```

#### 3. Power 容器 → 统一 abilities 结构

```python
@dataclass
class CardPower:
    """卡牌能力容器 — 一张卡的所有效果定义"""
    battlecry: list[Action] = field(default_factory=list)
    deathrattle: list[Action] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    aura: Optional[AuraDef] = None
    enchant: Optional[EnchantDef] = None
```

#### 4. Action 管道 → 替代 EffectKind 枚举

现状 `dispatch.py` 有 35 种 EffectKind → 应参考 RosettaStone 的 Task 管道，使 Action 可组合。

---

## 四、风险评估与优先级

| 借鉴点 | 实现难度 | 收益 | 优先级 |
|--------|---------|------|--------|
| Tag 统一属性模型 | 中（兼容层） | 高（消除三套系统） | P0 |
| card_abilities.json 骨架 | 中 | 高（打通能力管线） | P0 |
| Power 容器 | 低（dataclass） | 中（结构清晰化） | P1 |
| Action 管道 | 高（重写 dispatch） | 高（可扩展性） | P2 |
| Fireplace DSL | 极高（全新子系统） | 高（声明式定义） | 远期 |

**结论**: 先做 Tag 统一 + card_abilities.json，这是所有成熟模拟器的基础设施。后续迭代引入 Power 容器和 Action 管道。

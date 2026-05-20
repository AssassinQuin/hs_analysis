# Card Abilities System v2 — 设计文档

> 完全重写的卡牌效果系统，基于 Fireplace / SabberStone / Spellsource 成熟设计，
> JSON 数据驱动 + 分层递归 Spell 架构，替换现有平铺 actions + 文本回退模式。

---

## 目录

1. [指导思想](#1-指导思想)
2. [整体架构](#2-整体架构)
3. [核心数据模型](#3-核心数据模型)
4. [JSON Schema v2](#4-json-schema-v2)
5. [目标选择器系统](#5-目标选择器系统)
6. [值提供器系统](#6-值提供器系统)
7. [条件系统](#7-条件系统)
8. [过滤器系统](#8-过滤器系统)
9. [触发类型系统](#9-触发类型系统)
10. [Spell 类族](#10-spell-类族)
11. [光环系统](#11-光环系统)
12. [执行流程](#12-执行流程)
13. [文件结构](#13-文件结构)
14. [迁移计划](#14-迁移计划)
15. [附录：典型卡牌 JSON 示例](#15-附录典型卡牌-json-示例)

---

## 1. 指导思想

### 核心原则

| 原则 | 含义 |
|------|------|
| **数据驱动** | 卡牌效果由 JSON 定义，generator 从 CardDB 产出正确的结构化 JSON |
| **递归组合** | Spell 嵌套组合（MetaSpell → 多个子 Spell），不支持平铺 actions |
| **关注点分离** | Spell/目标/过滤器/条件/值提供器各司其职，各自独立注册 |
| **类型安全** | 目标选择器是封闭枚举、ValueDesc 是有类型的描述对象 |
| **事件驱动触发** | 所有触发（战吼/亡语/法术迸发/光环等）都走统一 TriggerRegistry |
| **光环即持续 Spell** | 光环是注册到 GameState 的持久 Spell，随条件变化自动重算 |
| **附魔即状态效果** | 附魔是有持续时间的 Spell 效果，可被沉默移除 |

### 对现有系统的断舍离

| 现文件 | 处理方式 |
|--------|----------|
| ~~`generator.py`~~ | 已删除 — 由 `generator_v2.py` 替代 |
| `spells.py` | 拆分为 `spells/` 模块，保留关键类，废弃旧注册表模式 |
| `power.py` | 废弃，由 `CardAbility` 替代 |
| `simulation.py` | 清理 — 移除 `_apply_text_spell_effects`，改为统一 SpellExecutor |
| `_apply_text_spell_effects` | 删除，不再需要文本回退 |
| `target.py` | 重写为 `target/resolver.py` |
| `aura.py` | 集成进 `spells/aura.py` + `AuraRegistry` |
| `executor.py` | 保留，作为底层状态变更函数库 |

---

## 2. 整体架构

```
                    ┌──────────────────────┐
                    │      CardDB (hsdb)    │
                    └──────────┬───────────┘
                               │
               ┌──────────▼───────────┐
               │   generator_v2.py    │
               │  CardDB → v2 JSON     │
                    └──────────┬───────────┘
                               │ card_abilities_v2.json
                    ┌──────────▼───────────┐
                    │     loader.py         │
                    │  JSON → CardAbility   │
                    └──────────┬───────────┘
                               │ CardAbility 对象
                               │
               ┌───────────────┼───────────────────┐
               ▼               ▼                   ▼
      ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
      │ SpellExecutor │ │TriggerRegistry│ │  AuraRegistry    │
      │  执行 Spell   │ │ 注册+分发触发  │ │  管理光环重算    │
      └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
             │                │                  │
             ▼                ▼                  ▼
      ┌─────────────────────────────────────────────────┐
      │         GameState (engine/state.py)              │
      │  + spell_queue, trigger_registry, aura_registry  │
      └─────────────────────────────────────────────────┘
             │
             ▼
      ┌─────────────────────────────────────────────────┐
      │  底层 executor 函数 (executor.py)                │
      │  damage(), heal(), summon(), draw(), equip()... │
      └─────────────────────────────────────────────────┘
```

---

## 3. 核心数据模型

### CardAbility — 卡牌能力容器

```python
@dataclass
class CardAbility:
    """一张卡牌的所有能力，按触发类型分组。"""
    card_id: str
    name: str
    abilities: Dict[TriggerType, AbilityEntry]  # trigger → entry
    minion_info: Optional[MinionInfo] = None     # 随从基础属性
```

### AbilityEntry — 单个触发类型条目

```python
@dataclass
class AbilityEntry:
    """一个触发类型对应的效果定义。"""
    trigger: TriggerType
    spell: "SpellDesc"           # 要执行的效果
    condition: Optional["ConditionDesc"] = None  # 可选触发条件
```

### SpellDesc — 效果描述（可递归嵌套）

```python
@dataclass
class SpellDesc:
    """Spell 的序列化描述，可任意嵌套。"""
    class_name: str                        # "DamageSpell", "MetaSpell"...
    target: str = "NONE"                   # 目标选择器
    filter: Optional["FilterDesc"] = None  # 可选过滤器
    random_target: bool = False
    how_many: int = 1                      # 选多少个目标（用于 RANDOM 类）
    
    # 复合 Spell 使用
    spells: List["SpellDesc"] = field(default_factory=list)   # MetaSpell / RandomSpell
    spell: Optional["SpellDesc"] = None    # 子 Spell (Repeat, AddEnchantment)
    
    # 条件分支
    condition: Optional["ConditionDesc"] = None  # ConditionalSpell
    then: Optional["SpellDesc"] = None
    else_spell: Optional["SpellDesc"] = None
    
    # 效果参数（具体类各取所需）
    value: Any = None
    count: int = 1
    attack: int = 0
    health: int = 0
    card_id: str = ""
    attribute: str = ""
    keyword: str = ""
    duration: int = 0
    pool: str = ""
```

### ValueDesc — 值描述

```json
// 直接 int：
"value": 6

// 带 SpellDamage 加成：
"value": {"provider": "spell_damage", "base": 6}

// 动态值：
"value": {"provider": "count", "target": "ENEMY_MINIONS"}
"value": {"provider": "attribute", "target": "SELF", "attribute": "ATTACK"}
```

```python
@dataclass
class ValueDesc:
    """可延迟计算的值。"""
    provider: str        # "fixed", "spell_damage", "count", "attribute"
    base: int = 0
    target: str = ""
    attribute: str = ""
```

### FilterDesc — 过滤器描述

```python
@dataclass
class FilterDesc:
    """在目标列表上执行的过滤器。"""
    class_name: str       # "RaceFilter", "AttributeFilter", "NotFilter"
    params: dict = field(default_factory=dict)
    filters: List["FilterDesc"] = field(default_factory=list)  # 嵌套
```

### ConditionDesc — 条件描述

```python
@dataclass
class ConditionDesc:
    """运行时布尔条件。"""
    class_name: str       # "HoldingRaceCondition", "BoardCountCondition"...
    params: dict = field(default_factory=dict)
```

---

## 4. JSON Schema v2

### 根结构

```json
{
  "version": 2,
  "cards": {
    "{card_id}": {
      "name": "卡牌名",
      "type": "SPELL | MINION | WEAPON | LOCATION | HERO",
      "abilities": {
        "BATTLECRY": {
          "spell": { /* SpellDesc */ },
          "condition": { /* 可选 ConditionDesc */ }
        },
        "DEATHRATTLE": { /* ... */ },
        "ON_PLAY": { /* ... */ }
      },
      "minion": {
        "attack": 6,
        "health": 7,
        "mechanics": ["TAUNT", "RUSH"]
      }
    }
  }
}
```

### SpellDesc JSON 格式

```json
{
  "class": "MetaSpell",
  "spells": [
    {"class": "DamageSpell", "value": {"provider": "spell_damage", "base": 4}, "target": "ALL_ENEMY_MINIONS"},
    {"class": "DrawSpell", "value": 1}
  ]
}
```

### 标准 Spell 的 JSON 结构

```json
// DamageSpell — 造成伤害
{"class": "DamageSpell", "value": {"provider": "spell_damage", "base": 4}, "target": "ALL_ENEMY_MINIONS"}

// HealSpell — 治疗
{"class": "HealSpell", "value": {"provider": "spell_damage", "base": 4}, "target": "TARGET"}

// BuffSpell — 增益属性
{"class": "BuffSpell", "attack": 3, "health": 3, "target": "SELF"}

// SetAttributeSpell — 设置属性为特定值
{"class": "SetAttributeSpell", "attribute": "CURRENT_HP", "value": 15, "target": "TARGET", "filter": {"class": "IsCharacterFilter"}}

// DrawSpell — 抽牌
{"class": "DrawSpell", "value": 2}

// SummonSpell — 召唤随从
{"class": "SummonSpell", "card_id": "CS2_222", "target": "NONE"}

// DestroySpell — 摧毁
{"class": "DestroySpell", "target": "TARGET"}

// ArmorSpell — 护甲
{"class": "ArmorSpell", "value": 5}

// ManaSpell — 法力水晶
{"class": "ManaSpell", "value": 2}

// DiscoverSpell — 发现
{"class": "DiscoverSpell", "pool": "ALL_MINIONS", "count": 3}

// EquipWeaponSpell — 装备武器
{"class": "EquipWeaponSpell", "card_id": "CS2_106"}

// GiveKeywordSpell — 添加关键词
{"class": "GiveKeywordSpell", "keyword": "TAUNT", "target": "FRIENDLY_MINIONS"}

// ConditionalSpell — 条件分支
{
  "class": "ConditionalSpell",
  "condition": {"class": "HoldingRaceCondition", "race": "DRAGON"},
  "then": {"class": "DamageSpell", "value": 4, "target": "TARGET"},
  "else": {"class": "DamageSpell", "value": 3, "target": "TARGET"}
}

// RepeatSpell — 重复
{"class": "RepeatSpell", "spell": {"class": "SummonSpell", "card_id": "EX1_009"}, "value": 2}

// AddEnchantmentSpell — 添加附魔（带触发器的 buff）
{
  "class": "AddEnchantmentSpell",
  "target": "SELF",
  "spell": {
    "class": "BuffSpell", "attack": 1, "health": 1
  },
  "trigger": {
    "event": "TURN_END",
    "spell": {"class": "DamageSpell", "value": 1, "target": "SELF"}
  },
  "duration": 1
}

// AuraBuffSpell — 光环增益
{
  "class": "AuraBuffSpell",
  "attack_bonus": 1,
  "health_bonus": 1,
  "target": "OTHER_FRIENDLY_MINIONS",
  "condition": {"class": "HasRaceCondition", "race": "BEAST"}
}
```

---

## 5. 目标选择器系统

### 选择器枚举

| 选择器 | 含义 |
|--------|------|
| `NONE` | 无目标（AOE 等自身决定） |
| `TARGET` | 从外部传入的目标（玩家选择的） |
| `SELF` | 来源实体自身 |
| `ALL_ENEMY_CHARACTERS` | 敌方英雄 + 全部敌方随从 |
| `ALL_FRIENDLY_CHARACTERS` | 我方英雄 + 全部我方随从 |
| `ALL_ENEMY_MINIONS` | 敌方所有随从 |
| `ALL_FRIENDLY_MINIONS` | 我方所有随从 |
| `ALL_MINIONS` | 全部随从（双方） |
| `ALL_CHARACTERS` | 全部角色 |
| `ENEMY_HERO` | 敌方英雄 |
| `FRIENDLY_HERO` | 我方英雄 |
| `RANDOM_ENEMY_CHARACTER` | 随机敌方角色 |
| `RANDOM_ENEMY_MINION` | 随机敌方随从 |
| `RANDOM_FRIENDLY_CHARACTER` | 随机我方角色 |
| `RANDOM_FRIENDLY_MINION` | 随机我方随从 |
| `OTHER_FRIENDLY_MINIONS` | 其他我方随从（不含来源自身） |
| `ADJACENT_MINIONS` | 来源两侧的随从 |
| `FRIENDLY_WEAPON` | 我方武器 |
| `ALL_HAND` | 手牌中全部卡牌 |
| `DECK` | 牌库 |

### 运行时解析

```python
class TargetResolver:
    """将目标选择器 + 过滤器解析为具体实体列表。"""
    
    SELECTORS = {
        "NONE": lambda ctx: [],
        "SELF": lambda ctx: [ctx.source],
        "TARGET": lambda ctx: [ctx.action_target] if ctx.action_target else [],
        "ALL_ENEMY_MINIONS": lambda ctx: list(ctx.state.opponent.board),
        "ALL_FRIENDLY_MINIONS": lambda ctx: list(ctx.state.board),
        "ALL_MINIONS": lambda ctx: list(ctx.state.board) + list(ctx.state.opponent.board),
        # ... 以此类推
    }
    
    def resolve(self, selector: str, ctx: CastContext) -> List[Any]:
        entities = self.SELECTORS[selector](ctx)
        if ctx.spell_desc.filter:
            entities = FilterResolver.apply(entities, ctx.spell_desc.filter, ctx)
        if ctx.spell_desc.random_target:
            entities = [random.choice(entities)] if entities else []
        elif ctx.spell_desc.how_many > 1 and len(entities) > 1:
            entities = entities[:ctx.spell_desc.how_many]
        return entities
```

---

## 6. 值提供器系统

### 提供器类型

| 提供器 | 含义 | 参数 |
|--------|------|------|
| `fixed` | 固定值 | `base` |
| `spell_damage` | 基础值 + 法术伤害加成 | `base` |
| `count` | 目标数量 | `target`（选择器） |
| `attribute` | 从实体属性读取 | `target`, `attribute` |
| `random` | 随机范围 | `min`, `max` |
| `multiply` | 乘法 | `value`, `multiplier` |
| `add` | 加法 | `values[]` |

### 运行时解析

```python
class ValueResolver:
    PROVIDERS = {
        "fixed": lambda desc, ctx: desc.base,
        "spell_damage": lambda desc, ctx: desc.base + _sum_spell_power(ctx),
        "count": lambda desc, ctx: len(TargetResolver.resolve(desc.target, ctx)),
        "attribute": lambda desc, ctx: _get_attribute(ctx.source, desc.attribute),
    }
    
    def resolve(self, value_spec: Any, ctx: CastContext) -> int:
        if isinstance(value_spec, int):
            return value_spec
        provider = value_spec.get("provider", "fixed")
        return self.PROVIDERS[provider](value_spec, ctx)
```

---

## 7. 条件系统

### 条件类型

| 条件 | 含义 | 参数 |
|------|------|------|
| `HoldingRaceCondition` | 手牌中有某种族 | `race` |
| `BoardCountCondition` | 场上某类实体数量条件 | `target`, `comparison`, `count` |
| `HpCondition` | 目标血量条件 | `comparison`, `value` |
| `HasAttributeCondition` | 有某属性 | `attribute` |
| `ComparisonCondition` | 任意值比较 | `type`, `comparison`, `value` |
| `AndCondition` | 与 | `conditions[]` |
| `OrCondition` | 或 | `conditions[]` |
| `NotCondition` | 非 | `condition` |

### 运行时

```python
class ConditionResolver:
    CONDITIONS = {
        "HoldingRaceCondition": lambda cond, ctx: _hand_has_race(ctx.state, cond.race),
        "BoardCountCondition": lambda cond, ctx: len(resolve(cond.target, ctx)) >= cond.count,
        "HasAttributeCondition": lambda cond, ctx: _has_tag(ctx.source, cond.attribute),
    }
    
    def evaluate(self, condition: ConditionDesc, ctx: CastContext) -> bool:
        return self.CONDITIONS[condition.class_name](condition, ctx)
```

---

## 8. 过滤器系统

### 过滤器类型

| 过滤器 | 含义 | 参数 |
|--------|------|------|
| `RaceFilter` | 种族过滤 | `race` |
| `AttributeFilter` | 属性过滤 | `attribute`, `has` |
| `NotFilter` | 排除类型 | `filter` 子过滤器 |
| `HpFilter` | 血量过滤 | `comparison`, `value` |
| `AttackFilter` | 攻击力过滤 | `comparison`, `value` |
| `IsCharacterFilter` | 是角色（英雄或随从） | |
| `IsMinionFilter` | 是随从 | |
| `SelfFilter` | 排除自身 | |

---

## 9. 触发类型系统

### TriggerType 枚举

```python
class TriggerType(Enum):
    ON_PLAY = "ON_PLAY"        # 法术主效果/英雄牌战吼
    BATTLECRY = "BATTLECRY"    # 随从入场战吼
    COMBO = "COMBO"            # 连击（本回合打过牌）
    DEATHRATTLE = "DEATHRATTLE" # 亡语
    SPELLBURST = "SPELLBURST"  # 法术迸发
    FRENZY = "FRENZY"          # 暴怒
    INSPIRE = "INSPIRE"        # 激励
    OUTCAST = "OUTCAST"        # 流放
    FINALE = "FINALE"          # 终曲
    AURA = "AURA"              # 光环（持续）
    TRIGGER = "TRIGGER"        # 通用事件触发（含 event_type 字段）
    SECRET = "SECRET"          # 奥秘
    QUEST = "QUEST"            # 任务
    HERO_POWER = "HERO_POWER"  # 英雄技能
```

### TriggerRegistry

```python
class TriggerRegistry:
    """
    按触发类型注册卡牌效果，事件发生时分发执行。
    
    注册时机：
    - 随从进场时注册 BATTLECRY (立即执行) / DEATHRATTLE / AURA / TRIGGER
    - 法术打出时注册 SECRET / QUEST
    - 英雄替换时注册 HERO_POWER
    """
    
    def register(self, card_id: str, trigger: TriggerType, entry: AbilityEntry, source: Entity):
        """将能力注册到触发器，source 移除时解除注册。"""
        
    def fire(self, trigger: TriggerType, ctx: CastContext):
        """触发某类型的所有已注册效果。"""
        
    def unregister(self, source: Entity):
        """某个 entity 被移除/沉默时解除其所有注册。"""
```

### 执行序列

```
玩家打出 Fireball
  → _play_spell()
    → 费用校验
    → 从手牌移除
    → trigger_registry.fire(ON_PLAY, CastContext(card, spell_desc))
      → SpellExecutor.execute(damage_spell, ctx)
        → TargetResolver.resolve("TARGET", ctx) → [enemy_hero]
        → ValueResolver.resolve(6, ctx) → 6
        → DamageSpell.on_cast(ctx, targets)
          → executor.damage(ctx.state, 6, enemy_hero)
    → trigger_registry.fire(SPELL_CAST, CastContext(card))
      → 触发"施放法术后"的事件（如法术迸发）
    → _resolve_deaths()
```

---

## 10. Spell 类族

### 抽象基类

```python
class Spell(ABC):
    """所有可执行效果的抽象基类。"""
    
    @abstractmethod
    def on_cast(self, ctx: "CastContext", targets: List[Any]) -> "GameState":
        """执行效果。由 SpellExecutor 解析目标后调用。"""
    
    @classmethod
    def from_desc(cls, desc: SpellDesc) -> "Spell":
        """从 SpellDesc 构造实例（工厂）。"""
```

### CastContext

```python
@dataclass
class CastContext:
    """Spell 执行的完整上下文。"""
    state: "GameState"
    spell_desc: SpellDesc           # 当前执行的 SpellDesc
    source: Any = None              # 来源实体（牌、随从、英雄）
    action_target: Any = None       # 玩家选择的初始目标
    child: bool = False             # 是否为子 Spell（影响事件触发）
```

### Spell 完整清单

```python
# ── 组合 ──
class MetaSpell(Spell):       # 顺序执行 spells 列表
class RepeatSpell(Spell):     # 重复执行子 spell N 次
class ConditionalSpell(Spell): # 条件分支
class RandomSpell(Spell):     # 随机选一个子 spell 执行
class ActorOrCardSpell(Spell): # 根据目标类型选分支（Spellsource 模式）

# ── 伤害/治疗 ──
class DamageSpell(Spell):     # 造成伤害 (带 spellpower)
class HealSpell(Spell):       # 治疗

# ── 增益/属性 ──
class BuffSpell(Spell):       # +attack/+health
class SetAttributeSpell(Spell): # 设特定值（Alexstrasza: 设血为15）
class GiveKeywordSpell(Spell):  # 添加关键词（Taunt, Rush...）
class EnchantSpell(Spell):    # 暂时附魔（有 duration）

# ── 抽牌/弃牌 ──
class DrawSpell(Spell):
class DiscardSpell(Spell):
class ShuffleSpell(Spell):

# ── 召唤/摧毁/变形 ──
class SummonSpell(Spell):     # 召唤
class DestroySpell(Spell):    # 摧毁
class SilenceSpell(Spell):    # 沉默
class TransformSpell(Spell):  # 变形（羊/蛙等）

# ── 控制/复制/回手 ──
class TakeControlSpell(Spell): # 精神控制
class CopySpell(Spell):       # 复制（无面操纵者）
class ReturnSpell(Spell):     # 回手

# ── 资源 ──
class ArmorSpell(Spell):      # 护甲
class ManaSpell(Spell):       # 法力水晶

# ── 其他 ──
class DiscoverSpell(Spell):
class FreezeSpell(Spell):
class EquipWeaponSpell(Spell):
class AddEnchantmentSpell(Spell): # 为目标添加附魔（含触发器）

# ── 光环 ──
class AuraBuffSpell(Spell):     # +attack/+health 光环
class AuraCostSpell(Spell):     # 费用修改光环
class AuraAttributeSpell(Spell): # 属性修改光环
```

---

## 11. 光环系统

### 设计原则

光环是有条件的持续状态修改，与 Spell 执行模型不同：
- Spell 是一次性效果（fire-and-forget）
- 光环是注册的持续效果，在 board state 变化时重算

### AuraRegistry

```python
class AuraRegistry:
    """
    管理所有活跃光环。
    
    光环来源可以是：
    - 场上的随从（Stormwind Champion）
    - 英雄（某些英雄牌的光环）
    - 武器（某些武器特效）
    
    触发重算时机：
    - 随从进场/离场
    - 回合开始/结束
    - 沉默
    - 变形
    """
    
    def register(self, aura_spell: "AuraBuffSpell", source: Entity, state: GameState):
    def recompute(self, state: GameState):
        """重新计算所有活跃光环，更新受影响实体的属性。"""
    def unregister(self, source: Entity):
```

### 光环 JSON 示例

```json
// Stormwind Champion（暴风城勇士）
{
  "class": "AuraBuffSpell",
  "attack_bonus": 1,
  "health_bonus": 1,
  "target": "OTHER_FRIENDLY_MINIONS"
}

// Dire Wolf Alpha（恐狼前锋）
{
  "class": "AuraBuffSpell",
  "attack_bonus": 1,
  "health_bonus": 0,
  "target": "ADJACENT_MINIONS"
}
```

### 光环与属性的叠加

Aura 修改存储在 `Minion.aura_attack` / `Minion.aura_health` 中，
运算时 `effective_attack = base_attack + aura_attack + buff_attack`。

```
┌──────────────┬─────────────┬──────────────┐
│  base_attack  │ aura_attack │ buff_attack  │ → effective_attack
│ (from card)  │ (from aura) │ (from spells)│
└──────────────┴─────────────┴──────────────┘
```

---

## 12. 执行流程

### 玩家打出卡牌的完整流程

```
play_card(state, card, action)
  │
  ├─ 1. 费用校验 (validate_and_pay_cost)
  │
  ├─ 2. 从手牌移除 (hand.pop)
  │
  ├─ 3. 按类型分发:
  │     │
  │     ├─ SPELL → _play_spell(state, card, action)
  │     │            ├─ Load CardAbility from loader
  │     │            ├─ 检查 combo 条件
  │     │            └─ SpellExecutor.execute(ability.spell, ctx)
  │     │                ├─ ResolveTargets(spell_desc.target, ctx)
  │     │                ├─ ResolveValues(spell_desc.value, ctx)
  │     │                └─ spell.on_cast(ctx, targets)
  │     │                    └─ MetaSpell → 递归执行子 spell
  │     │
  │     ├─ MINION → _play_minion(state, card, action)
  │     │            ├─ 创建 Minion 实体
  │     │            ├─ 放置到 board
  │     │            ├─ 注册 aura（如果有）
  │     │            ├─ 执行 BATTLECRY（如果有）
  │     │            └─ 注册 DEATHRATTLE/TRIGGER（如果有）
  │     │
  │     └─ WEAPON → _play_weapon(state, card, action)
  │     
  ├─ 4. 事件触发阶段
  │     ├─ fire(TRIGGER, "AFTER_SPELL_CAST")
  │     ├─ fire(TRIGGER, "AFTER_MINION_SUMMONED")
  │     └─ recompute_auras()
  │
  └─ 5. 死亡结算 (_resolve_deaths)
        └─ 执行 DEATHRATTLE（通过 TriggerRegistry）
```

### SpellExecutor 详细流程

```python
class SpellExecutor:
    def execute(self, desc: SpellDesc, ctx: CastContext) -> GameState:
        # 1. 解析目标
        targets = TargetResolver.resolve(desc.target, ctx)
        
        # 2. 解析值
        value = ValueResolver.resolve(desc.value, ctx) if desc.value else 0
        
        # 3. 创建 Spell 实例并执行
        spell_cls = SPELL_REGISTRY[desc.class_name]
        spell = spell_cls.from_desc(desc)
        
        # 4. 对每个目标执行（批量处理 / 逐目标）
        if targets:
            for target in targets:
                child_ctx = replace(ctx, action_target=target)
                state = spell.on_cast(child_ctx, [target])
        else:
            state = spell.on_cast(ctx, [])
        
        # 5. 后处理（子 Spell 等由 on_cast 内部处理）
        return state
```

---

## 13. 文件结构

### 新结构

```
analysis/card/abilities/
  ├── __init__.py
  ├── model.py                  # SpellDesc, ValueDesc, FilterDesc, ConditionDesc
  ├── loader.py                 # 加载 card_abilities_v2.json → CardAbility
   ├── generator_v2.py           # CardDB → card_abilities_v2.json (English-only)
  │
  ├── executor.py               # SpellExecutor: 统一 spell 执行入口
  ├── registry.py               # SPELL_REGISTRY, TRIGGER_REGISTRY
  │
  ├── spells/
  │   ├── __init__.py
  │   ├── base.py               # Spell ABC + CastContext
  │   ├── composite.py          # MetaSpell, RepeatSpell, ConditionalSpell, RandomSpell
  │   ├── damage.py             # DamageSpell, HealSpell
  │   ├── buff.py               # BuffSpell, SetAttributeSpell, EnchantSpell, GiveKeywordSpell
  │   ├── board.py              # SummonSpell, DestroySpell, SilenceSpell, TransformSpell
  │   ├── hand.py               # DrawSpell, DiscardSpell, ShuffleSpell, ReturnSpell
  │   ├── control.py            # TakeControlSpell, CopySpell
  │   ├── resource.py           # ArmorSpell, ManaSpell
  │   ├── discover.py           # DiscoverSpell
  │   ├── weapon.py             # EquipWeaponSpell
  │   └── aura.py               # AuraBuffSpell, AuraCostSpell, AuraAttributeSpell
  │
  ├── target/
  │   ├── __init__.py
  │   ├── resolver.py           # TargetResolver
  │   └── filter.py             # FilterResolver + 所有 Filter 类
  │
  ├── condition/
  │   ├── __init__.py
  │   └── conditions.py         # ConditionResolver + 所有 Condition 类
  │
  ├── value/
  │   ├── __init__.py
  │   └── providers.py          # ValueResolver + 所有 Provider 函数
  │
  └── trigger/
      ├── __init__.py
      └── registry.py           # TriggerRegistry + TriggerType
```

### 清理/修改的文件

```
analysis/card/engine/
  ├── simulation.py             # 清理: 去掉 _apply_text_spell_effects
  │                             # 改为调用 SpellExecutor + TriggerRegistry
  ├── state.py                  # 保持，轻微扩展
  └── executor.py               # 保持底层函数库，不加高层逻辑

分析/card/abilities/
  ├── spells.py                 # 拆分为 spells/ 包，移除旧注册表模式
  ├── power.py                  # 废弃删除
  ├── definition.py             # 保留 Action/ActionType 供搜索层用

分析/card/engine/
  ├── target.py                 # 废弃删除（由 abilities/target/ 替代）
  ├── aura.py                   # 废弃删除（由 abilities/spells/aura.py 替代）
```

---

## 14. 迁移计划

### Phase 0 — 基础结构搭建（估计: 2 天）

```
1. 创建新文件结构
   - abilities/model.py       → SpellDesc, ValueDesc, etc.
   - abilities/executor.py    → SpellExecutor
   - abilities/trigger/registry.py → TriggerRegistry
   - spells/ 子模块全部创建
   - target/ 子模块全部创建
   - condition/ 子模块全部创建
   - value/ 子模块全部创建

2. 移植并扩展
   - 从现有 spells.py 移植 MetaSpell, ConditionalSpell 等
   - 从现有 spells.py 移植 DamageSpell, HealSpell 等
   - 重写 TargetResolver（不走字符串 if-elif，用注册表）
   - 实现 ValueResolver
   - 实现 ConditionResolver

3. 实现 TriggerRegistry
   - 触发注册/反注册
   - 事件分发

4. 实现 AuraRegistry
   - 光环注册/重算/反注册
```

### Phase 1 — Generator 重写（估计: 2 天）

```
1. 重写 generate_abilities_json()
   - 产出 v2 格式（嵌套 SpellDesc，不是平铺 actions）
   - 检测多效果 → MetaSpell
   - 检测条件文本 ("If", "instead", "corrupt") → ConditionalSpell
   - 检测光环文本 ("Your X have +1/+1") → AuraBuffSpell
   - 检测触发文本 ("Whenever", "After") → TRIGGER entry
   - 检测固定值 (#) 和动态值 ($) → 不同 ValueDesc
   - 评估召唤随从名称 → 查找 card_id
   - 目标推断：检测 "all", "random", "enemy", "friendly", "adjacent" → 正确选择器

2. 新增 _MECHANIC_HANDLERS 条目
   - 完全使用注册表，无 if-elif

3. 生成产物：card_abilities_v2.json
```

### Phase 2 — Simulation 对接（估计: 1 天）

```
1. 清理 simulation.py
   - remove _apply_text_spell_effects
   - _play_spell → 使用 CardAbility + SpellExecutor
   - _play_minion → 注册 aura + trigger + 执行 battlecry
   - _play_minion → 注册 deathrattle（触发 TriggerRegistry）

2. 整合 TriggerRegistry
   - 在 apply_action 的适当位置 fire trigger
   - death phase 走 TriggerRegistry.fire(DEATHRATTLE)

3. 整合 AuraRegistry
   - recompute_auras → AuraRegistry.recompute
   - 在 board 变更时触发重算
```

### Phase 3 — 清理与测试（估计: 1 天）

```
1. 删除废弃文件
   - power.py
   - engine/target.py
   - engine/aura.py
   - 旧 spells.py（不兼容部分）

2. 修复所有测试
   - 更新卡牌 mock 数据（若使用旧格式）
   - 确认 751 张卡全部有正确的 v2 abilities

3. 统计覆盖率
   - 对比旧 TODO 数量 vs 新 TODO 数量
   - 确认所有简单效果卡（Damage/Draw/Heal）正确

4. 全量测试运行
   - pytest tests/
   - 目标：0 failed，skipped 数量合理
```

### 当前状态 (2026-05-20)

| 指标 | 数量 | 占比 |
|------|------|------|
| 总收藏卡牌 (Wild) | 7935 | 100% |
| 推断成功 | 4975 | 69.5% |
| TODO (复杂效果) | 2178 | 30.4% |
| 纯关键字 (跳过) | 772 | 9.7% |

**持久化机制:**
- `card_abilities_v2_manual.json` — 手动覆盖文件 (261 条)，generator 每次运行后自动合并
- `consolidate_v2_fixes.py` — 一键式修复持久化脚本
- 规则: 永远不直接编辑 `card_abilities_v2.json`；通过 `card_abilities_v2_manual.json` 或 `generator_v2.py` 修改

**近期清理:**
- 2026-05-20: 删除 v1 死代码 (`generator.py`, `generate_card_ability_v2()`, `load_from_v1_file()`, `load_from_generator()`)
- 2026-05-20: 移除所有中文正则模式（之前作为防御性代码存在），generator 仅处理英文文本

### 总计: 约 6 天工作量

---

## 15. 附录：典型卡牌 JSON 示例

### Fireball (火球术, CS2_029)

```json
{
  "CS2_029": {
    "name": "Fireball",
    "type": "SPELL",
    "abilities": {
      "ON_PLAY": {
        "spell": {
          "class": "DamageSpell",
          "value": {"provider": "spell_damage", "base": 6},
          "target": "TARGET"
        }
      }
    }
  }
}
```

### Arcane Intellect (奥术智慧, CS2_023)

```json
{
  "CS2_023": {
    "name": "Arcane Intellect",
    "type": "SPELL",
    "abilities": {
      "ON_PLAY": {
        "spell": {
          "class": "DrawSpell",
          "value": 2
        }
      }
    }
  }
}
```

### Flamestrike (烈焰风暴, CS2_032)

```json
{
  "CS2_032": {
    "name": "Flamestrike",
    "type": "SPELL",
    "abilities": {
      "ON_PLAY": {
        "spell": {
          "class": "DamageSpell",
          "value": {"provider": "spell_damage", "base": 4},
          "target": "ALL_ENEMY_MINIONS"
        }
      }
    }
  }
}
```

### Starfire (星火术, NEW1_007) — 多效果

```json
{
  "NEW1_007": {
    "name": "Starfire",
    "type": "SPELL",
    "abilities": {
      "ON_PLAY": {
        "spell": {
          "class": "MetaSpell",
          "spells": [
            {"class": "DamageSpell", "value": {"provider": "spell_damage", "base": 5}, "target": "TARGET"},
            {"class": "DrawSpell", "value": 1}
          ]
        }
      }
    }
  }
}
```

### Alexstrasza (阿莱克斯塔萨, EX1_561) — 条件+属性设置

```json
{
  "EX1_561": {
    "name": "Alexstrasza",
    "type": "MINION",
    "minion": {"attack": 8, "health": 8, "mechanics": []},
    "abilities": {
      "BATTLECRY": {
        "spell": {
          "class": "SetAttributeSpell",
          "attribute": "CURRENT_HP",
          "value": 15,
          "target": "TARGET",
          "filter": {"class": "IsCharacterFilter"}
        }
      }
    }
  }
}
```

### Flik Skyshiv (间谍大师弗林, DAL_010) — 条件分支

```json
{
  "DAL_010": {
    "name": "Flik Skyshiv",
    "type": "MINION",
    "minion": {"attack": 4, "health": 4, "mechanics": []},
    "abilities": {
      "BATTLECRY": {
        "spell": {
          "class": "DamageSpell",
          "value": 3,
          "target": "TARGET",
          "filter": {"class": "IsMinionFilter"}
        },
        "spell": {
          "class": "DestroySpell",
          "target": "TARGET"
        }
      }
    }
  }
}
```

### Stormwind Champion (暴风城勇士, CS2_222)

```json
{
  "CS2_222": {
    "name": "Stormwind Champion",
    "type": "MINION",
    "minion": {"attack": 7, "health": 7, "mechanics": ["TAUNT"]},
    "abilities": {
      "AURA": {
        "spell": {
          "class": "AuraBuffSpell",
          "attack_bonus": 1,
          "health_bonus": 1,
          "target": "OTHER_FRIENDLY_MINIONS"
        }
      }
    }
  }
}
```

### SI:7 Agent (军情七处密探, EX1_284) — Combo

```json
{
  "EX1_284": {
    "name": "SI:7 Agent",
    "type": "MINION",
    "minion": {"attack": 3, "health": 3, "mechanics": []},
    "abilities": {
      "COMBO": {
        "spell": {
          "class": "DamageSpell",
          "value": 2,
          "target": "TARGET"
        }
      },
      "BATTLECRY": {
        "spell": {
          "class": "DamageSpell",
          "value": 2,
          "target": "TARGET"
        }
      }
    }
  }
}
```

### Truesilver Champion (真银圣剑, CS2_097) — 武器多效果

```json
{
  "CS2_097": {
    "name": "Truesilver Champion",
    "type": "WEAPON",
    "minion": {"attack": 4, "health": 2, "mechanics": []},
    "abilities": {
      "TRIGGER": {
        "spell": {
          "class": "HealSpell",
          "value": 2,
          "target": "FRIENDLY_HERO"
        },
        "event": "HERO_ATTACK"
      }
    }
  }
}
```

---

> **注**: 本设计受以下项目启发：Fireplace (https://github.com/jleclanche/fireplace)、
> Spellsource/MetaStone (https://playspellsource.com)、
> SabberStone (https://github.com/HearthSim/SabberStone)。
> 取三者之长，适配本项目 Python + JSON-driven 的现状。

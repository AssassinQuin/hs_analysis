> **本文件功能**: 定义 card_abilities.json 的 MetaStone 风格 JSON Schema。

# card_abilities.json Schema

## 概览

MetaStone 风格的卡牌能力定义格式。JSON 中引用效果类名 + 参数，运行时通过 SPELL_REGISTRY 反射加载。

## 顶层结构

```json
{
  "version": 1,
  "cards": {
    "CARD_ID": { ... },
    ...
  }
}
```

## 卡牌条目

```json
{
  "EX1_066": {
    "name": "疯狂投弹手",
    "abilities": [
      {
        "trigger": "BATTLECRY",
        "actions": [
          {
            "class": "DamageSpell",
            "target": "RANDOM_ENEMY_CHARACTER",
            "value": 3
          }
        ]
      }
    ]
  }
}
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `name` | string | 否 | 卡牌中文名（仅用于可读性） |
| `abilities` | array | 是 | 能力列表，每项包含 trigger + actions |

### 能力条目

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `trigger` | string | 是 | 触发时机（见 AbilityTrigger 枚举） |
| `condition` | object | 否 | 触发条件（见条件格式） |
| `actions` | array | 是 | Spell 实例列表，按顺序执行 |

## Spell 实例格式

每个 action 是一个 JSON 对象，`class` 字段指定 Spell 类名，其余字段为参数：

```json
{
  "class": "DamageSpell",
  "value": 6,
  "target": "ANY"
}
```

## 目标选择器 (Target)

| 值 | 说明 |
|----|------|
| `ANY` | 任意角色（英雄+随从） |
| `FRIENDLY_HERO` | 友方英雄 |
| `FRIENDLY_MINION` | 友方随从 |
| `FRIENDLY_MINIONS` | 所有友方随从 |
| `ENEMY_HERO` | 敌方英雄 |
| `ENEMY_MINION` | 敌方随从（需指定） |
| `ENEMY_MINIONS` | 所有敌方随从 |
| `ALL_MINIONS` | 全部随从 |
| `RANDOM_ENEMY_CHARACTER` | 随机敌方角色 |
| `RANDOM_ENEMY_MINION` | 随机敌方随从 |
| `RANDOM_FRIENDLY_MINION` | 随机友方随从 |
| `SELF` | 自身 |
| `ALL_ENEMY_CHARACTERS` | 全部敌方角色 |
| `ALL_FRIENDLY_CHARACTERS` | 全部友方角色 |
| `TARGET` | 当前法术/战吼目标 |

## 条件格式

```json
{
  "kind": "HOLDING_RACE",
  "params": { "race": "DRAGON" }
}
```

## 值表达式

支持字面量和惰性表达式：

```json
"value": 6
"value": {"$attr": "source.attack"}
"value": {"$count": "friendly_minions"}
"value": {"$add": [3, {"$attr": "source.attack"}]}
```

## 标准 Spell 类库

| 类名 | 参数 | 说明 |
|------|------|------|
| `DamageSpell` | value, target | 造成伤害 |
| `HealSpell` | value, target | 治疗 |
| `SummonSpell` | card_id, position | 召唤随从 |
| `BuffSpell` | attack, health, target | 增益属性 |
| `DrawSpell` | count | 抽牌 |
| `DestroySpell` | target | 摧毁 |
| `SilenceSpell` | target | 沉默 |
| `FreezeSpell` | target | 冻结 |
| `ReturnSpell` | target | 返回手牌 |
| `TakeControlSpell` | target | 获得控制权 |
| `DiscoverSpell` | pool, count | 发现 |
| `DiscardSpell` | count | 弃牌 |
| `ShuffleSpell` | card_id | 洗入牌库 |
| `TransformSpell` | target, card_id | 变形 |
| `CopySpell` | target | 复制 |
| `WeaponEquipSpell` | card_id | 装备武器 |
| `ArmorSpell` | value | 获得护甲 |
| `ManaSpell` | value | 获得法力 |
| `GiveSpell` | keyword, target | 给予关键词 |
| `MetaSpell` | spells | 顺序组合多个 Spell |
| `ConditionalSpell` | condition, then_spell, else_spell | 条件分支 |
| `EnchantSpell` | attack, health, duration, target | 附魔 |

## 示例

### 火球术 (CS2_029) — 简单法术
```json
{
  "CS2_029": {
    "name": "火球术",
    "abilities": [
      {
        "trigger": "ON_PLAY",
        "actions": [
          {"class": "DamageSpell", "value": 6, "target": "ANY"}
        ]
      }
    ]
  }
}
```

### 凯恩·血蹄 (EX1_110) — 亡语召唤
```json
{
  "EX1_110": {
    "name": "凯恩·血蹄",
    "abilities": [
      {
        "trigger": "DEATHRATTLE",
        "actions": [
          {"class": "SummonSpell", "card_id": "EX1_110t"}
        ]
      }
    ]
  }
}
```

### 黑翼腐蚀者 (BRM_033) — 条件战吼
```json
{
  "BRM_033": {
    "name": "黑翼腐蚀者",
    "abilities": [
      {
        "trigger": "BATTLECRY",
        "condition": {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}},
        "actions": [
          {"class": "DamageSpell", "value": 3, "target": "RANDOM_ENEMY_MINION"}
        ]
      }
    ]
  }
}
```

### 纯关键字随从 (无 abilities)
```json
{
  "CS2_124": {
    "name": "麦田傀儡",
    "abilities": [
      {
        "trigger": "DEATHRATTLE",
        "actions": [
          {"class": "SummonSpell", "card_id": "CS2_124t"}
        ]
      }
    ]
  }
}
```

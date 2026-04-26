# 声明式卡牌效果 JSON 系统 — 详细设计文档

> **版本**: v1.0  
> **生成日期**: 2026-04-26  
> **目标**: 将运行时文本解析翻转为离线 JSON 声明式数据，为 Power.log 训练数据清洗 + I-MCTS 铺路  
> **前置文档**: [analysis-full-refactoring-design.md](./analysis-full-refactoring-design.md), [card-effect-parsing-standard.md](./card-effect-parsing-standard.md)  
> **状态**: 设计中  

---

## 一、设计动机

### 1.1 当前痛点

```
Card → AbilityParser.parse(card) → List[CardAbility]
                  ↑
     运行时文本解析，每次 card.abilities 首次访问触发
     包含 EN string.find() + CN/EN regex 回退 + mechanics 标签映射
     脆弱、慢、不完整（无法覆盖全部 7898+ 张卡牌）
```

**具体问题**:
1. **运行时解析开销** — 每张卡牌首次访问 `.abilities` 触发 parser，MCTS 搜索中重复创建 Card 对象时尤其浪费
2. **覆盖不全** — 三套并行系统 (card_effects regex + abilities parser + effects.py) 仍不能覆盖所有卡牌
3. **不可序列化** — `LazyValue`, `EntitySelector` 是运行时 Python 对象，无法导出为训练数据
4. **无法机器学习** — 效果是代码而非数据，无法提取为特征向量

### 1.2 目标收益

| 维度 | 当前 | 目标 |
|------|------|------|
| 卡牌能力加载 | 运行时 parser.parse() | JSON 直接加载，零解析 |
| Power.log 训练数据 | 无法提取 effect features | 标准化 ability_tags 特征向量 |
| I-MCTS LLM 集成 | 需要 Python 对象 | JSON 可直接序列化为 prompt |
| 新卡牌支持 | 修改 parser 代码 | 修改 JSON 数据文件 |
| 卡牌覆盖率 | ~60% (依赖文本匹配) | 100% (手动标注 + 工具辅助) |

---

## 二、JSON Schema 设计

### 2.1 卡牌能力文件格式

**文件**: `data/card_abilities.json`

```json
{
  "_version": 1,
  "_generated": "2026-04-26T00:00:00Z",
  "_stats": {
    "total_cards": 7898,
    "with_abilities": 5234,
    "no_abilities": 2664,
    "coverage_percent": 100
  },
  "cards": {
    "CS2_029": {
      "id": "CS2_029",
      "name": "Fireball",
      "type": "SPELL",
      "cost": 4,
      "card_class": "MAGE",
      "mechanics_tags": [],
      "abilities": [
        {
          "trigger": "SPELL_CAST",
          "condition": null,
          "effects": [
            {
              "kind": "DAMAGE",
              "value": 6,
              "target": {"kind": "SINGLE_TARGET"}
            }
          ]
        }
      ]
    }
  }
}
```

### 2.2 Ability Schema

```json
{
  "trigger": "BATTLECRY | DEATHRATTLE | SPELL_CAST | SECRET | COMBO | SPELLBURST | CORRUPT | QUEST | TURN_START | TURN_END | WHENEVER | AFTER | ON_ATTACK | ON_DAMAGE | ON_SPELL_CAST | ON_DEATH | AURA | PASSIVE_COST | ACTIVATE | TRIGGER_VISUAL | HERALD | IMBUE | KINDRED | COLOSSAL | CORPSE_SPEND | CORPSE_GAIN | DORMANT | INSPIRE | CHOOSE_ONE | OUTCAST | ON_FEL_SPELL_CAST",
  "condition": {
    "kind": "HOLDING_RACE | THIS_TURN | FOR_EACH | HAS_KEYWORD | PLAYED_THIS_TURN | COST_COMPARISON | HEALTH_THRESHOLD | BOARD_STATE | HAND_POSITION | RACE_MATCH | RESOURCE_SUFFICIENT",
    "params": {
      "race": "DRAGON",
      "threshold": 5,
      "keyword": "TAUNT",
      "comparison": ">=",
      "resource": "CORPSE"
    }
  },
  "effects": [ /* EffectSpec[] */ ]
}
```

### 2.3 EffectSpec Schema

```json
{
  "kind": "DAMAGE | SUMMON | DRAW | GAIN | HEAL | GIVE | DESTROY | COPY | HEAL | SHUFFLE | REDUCE_COST | TRANSFORM | RETURN | TAKE_CONTROL | DISCARD | SWAP | WEAPON_EQUIP | DISCOVER | FREEZE | SILENCE | CAST_SPELL | ENCHANT | BUFF | ARMOR | RANDOM_DAMAGE | AOE_DAMAGE | MANA | HERALD_SUMMON | IMBUE_UPGRADE | COMBO_DISCOUNT | OUTCAST_DRAW | OUTCAST_BUFF | OUTCAST_COST | COLOSSAL_SUMMON | KINDRED_BUFF | CORRUPT_UPGRADE | CORPSE_EFFECT",
  "value": "int | ValueExpr",
  "value2": "int | ValueExpr",
  "subtype": "armor | health | attack | ...",
  "keyword": "TAUNT | RUSH | CHARGE | DIVINE_SHIELD | ...",
  "target": {
    "kind": "SINGLE_TARGET | SINGLE_MINION | RANDOM | FRIENDLY_HERO | FRIENDLY_MINION | RANDOM_ENEMY | ALL_MINIONS | ENEMY | ALL_ENEMY | ALL_FRIENDLY | DAMAGED | UNDAMAGED | SELF | ALL",
    "count": 1,
    "side": "friendly | enemy | both",
    "filters": [
      {"field": "race", "op": "==", "value": "BEAST"},
      {"field": "damaged", "op": "==", "value": true},
      {"field": "max_cost", "op": "<=", "value": 3}
    ]
  },
  "condition": { /* same as Ability.condition */ },
  "meta": {
    "spell_power_boost": true,
    "lifesteal": false,
    "overkill": false
  }
}
```

### 2.4 值表达式语言 (ValueExpr)

替代运行时 `LazyValue`，JSON 中的动态值使用声明式表达式：

#### 字面值
```json
"value": 6
"value": 0
```

#### 属性引用
```json
{"$attr": "source.attack"}           // 施放者的攻击力
{"$attr": "target.health"}           // 目标的生命值
{"$attr": "hero.armor"}              // 英雄护甲
{"$attr": "source.cost"}             // 卡牌费用
```

#### 集合计数
```json
{"$count": "friendly_minions"}       // 友方随从数
{"$count": "enemy_minions"}          // 敌方随从数
{"$count": "damaged_friendly"}       // 受伤友方角色数
{"$count": "hand"}                   // 手牌数
{"$count": "secrets"}                // 奥秘数
```

#### 算术组合
```json
{"$add": [6, {"$attr": "source.spell_power"}]}            // 6 + 法强
{"$mul": [2, {"$count": "friendly_minions"}]}              // 2 × 随从数
{"$sub": [{"$attr": "target.health"}, 1]}                  // 目标生命 - 1
{"$max": [0, {"$sub": [10, {"$attr": "hero.armor"}]}]}     // max(0, 10 - 护甲)
```

#### 条件值
```json
{
  "$if": {
    "condition": {"kind": "HOLDING_RACE", "params": {"race": "DRAGON"}},
    "then": 5,
    "else": 3
  }
}
```

#### 随机值
```json
{"$random": {"min": 1, "max": 6}}                          // 1~6 随机
{"$random_choice": [2, 3, 4]}                               // 从列表随机选
```

### 2.5 完整卡牌示例

#### 火球术 (CS2_029) — 简单法术
```json
{
  "id": "CS2_029",
  "name": "Fireball",
  "type": "SPELL",
  "cost": 4,
  "card_class": "MAGE",
  "mechanics_tags": [],
  "abilities": [
    {
      "trigger": "SPELL_CAST",
      "condition": null,
      "effects": [
        {
          "kind": "DAMAGE",
          "value": {"$add": [6, {"$attr": "source.spell_power"}]},
          "target": {"kind": "SINGLE_TARGET"},
          "meta": {"spell_power_boost": true}
        }
      ]
    }
  ]
}
```

#### 烈焰风暴 (CS2_032) — AOE 法术
```json
{
  "id": "CS2_032",
  "name": "Flamestrike",
  "type": "SPELL",
  "cost": 7,
  "card_class": "MAGE",
  "mechanics_tags": [],
  "abilities": [
    {
      "trigger": "SPELL_CAST",
      "condition": null,
      "effects": [
        {
          "kind": "DAMAGE",
          "value": {"$add": [4, {"$attr": "source.spell_power"}]},
          "target": {"kind": "ALL_ENEMY"},
          "meta": {"spell_power_boost": true}
        }
      ]
    }
  ]
}
```

#### 碧蓝龙 (CS2_032 → EX1_564) — 被动光环 + 战吼
```json
{
  "id": "EX1_564",
  "name": "Azure Drake",
  "type": "MINION",
  "cost": 5,
  "attack": 4,
  "health": 4,
  "card_class": "NEUTRAL",
  "mechanics_tags": ["BATTLECRY", "SPELL_DAMAGE"],
  "abilities": [
    {
      "trigger": "AURA",
      "condition": null,
      "effects": [
        {
          "kind": "BUFF",
          "subtype": "spell_power",
          "value": 1,
          "target": {"kind": "SELF"}
        }
      ]
    },
    {
      "trigger": "BATTLECRY",
      "condition": null,
      "effects": [
        {
          "kind": "DRAW",
          "value": 1,
          "target": {"kind": "SELF"}
        }
      ]
    }
  ]
}
```

#### 龙人惩击者 (DRG_066) — 条件战吼
```json
{
  "id": "DRG_066",
  "name": "Necrium Apothecary",
  "type": "MINION",
  "cost": 5,
  "attack": 4,
  "health": 4,
  "card_class": "NEUTRAL",
  "mechanics_tags": ["BATTLECRY"],
  "abilities": [
    {
      "trigger": "BATTLECRY",
      "condition": {
        "kind": "HOLDING_RACE",
        "params": {"race": "DRAGON"}
      },
      "effects": [
        {
          "kind": "DAMAGE",
          "value": 3,
          "target": {"kind": "RANDOM_ENEMY", "count": 1}
        }
      ]
    }
  ]
}
```

#### 灵魂之镜 (SCH_270) — 复杂条件效果
```json
{
  "id": "SCH_270",
  "name": "Soul Mirror",
  "type": "SPELL",
  "cost": 7,
  "card_class": "PRIEST",
  "mechanics_tags": [],
  "abilities": [
    {
      "trigger": "SPELL_CAST",
      "condition": null,
      "effects": [
        {
          "kind": "SUMMON",
          "value": {"$count": "enemy_minions"},
          "target": {"kind": "SELF"},
          "meta": {"summon_type": "copy_enemy_minions", "destroy_summoned": true}
        }
      ]
    }
  ]
}
```

#### 暗影之刃 (ICC_327) — 武器 + 免疫
```json
{
  "id": "ICC_327",
  "name": "Shadowblade",
  "type": "WEAPON",
  "cost": 3,
  "attack": 3,
  "health": 2,
  "card_class": "ROGUE",
  "mechanics_tags": ["BATTLECRY"],
  "abilities": [
    {
      "trigger": "BATTLECRY",
      "condition": null,
      "effects": [
        {
          "kind": "GIVE",
          "keyword": "IMMUNE",
          "target": {"kind": "FRIENDLY_HERO"},
          "meta": {"duration": "this_turn"}
        }
      ]
    }
  ]
}
```

#### 地狱咆哮 (EX1_116) — 多效果组合
```json
{
  "id": "EX1_116",
  "name": "Leeroy Jenkins",
  "type": "MINION",
  "cost": 5,
  "attack": 6,
  "health": 2,
  "card_class": "NEUTRAL",
  "mechanics_tags": ["BATTLECRY", "CHARGE"],
  "abilities": [
    {
      "trigger": "BATTLECRY",
      "condition": null,
      "effects": [
        {
          "kind": "SUMMON",
          "value": 2,
          "target": {"kind": "ENEMY"},
          "meta": {"card_id": "EX1_116t", "attack": 1, "health": 1}
        }
      ]
    }
  ]
}
```

---

## 三、Power.log → 训练数据清洗管道

### 3.1 管道架构

```
Power.log
    ↓ hslog 解析
EntityTree (hslog Game object)
    ↓ StateBridge.convert()
GameState
    ↓ TrainingDataExtractor.extract()
TrainingSample[]
    ↓ 批量输出
training_data.jsonl
```

### 3.2 训练样本格式

**文件**: `training_data.jsonl` (每行一个 JSON 对象)

```json
{
  "game_id": "abc123",
  "turn": 5,
  "player_class": "MAGE",
  "opponent_class": "WARLOCK",

  "state_vector": {
    "hero": {
      "hp": 28, "armor": 0,
      "weapon": null,
      "hero_power_used": false
    },
    "mana": {"available": 7, "total": 7, "overloaded": 0},
    "board_friendly": [
      {
        "card_id": "EX1_116",
        "attack": 6, "health": 2,
        "keywords": ["CHARGE"],
        "ability_tags": ["SUMMON:ENEMY:2:EX1_116t"]
      }
    ],
    "board_enemy": [],
    "hand": [
      {
        "card_id": "CS2_029",
        "cost": 4,
        "ability_tags": ["DAMAGE:SINGLE_TARGET:6"]
      },
      {
        "card_id": "CS2_032",
        "cost": 7,
        "ability_tags": ["DAMAGE:ALL_ENEMY:4"]
      }
    ],
    "deck_remaining": 18,
    "opponent_hand_count": 5,
    "secrets_opponent": 0
  },

  "action_taken": {
    "type": "PLAY",
    "card_index": 0,
    "card_id": "CS2_029",
    "target_index": -1,
    "target_entity": "ENEMY_HERO",
    "meta": {
      "mana_spent": 4,
      "mana_remaining": 3
    }
  },

  "reward": 0.73,

  "outcome": "WIN"
}
```

### 3.3 ability_tags 特征编码

`ability_tags` 是从 JSON 声明式数据直接提取的标准化特征，格式为：

```
"EFFECT_KIND:TARGET_KIND:VALUE[:META]"
```

**编码规则**:

| 模式 | 示例 | 含义 |
|------|------|------|
| `DAMAGE:SINGLE_TARGET:6` | 火球术 | 对单体造成6点伤害 |
| `DAMAGE:ALL_ENEMY:4` | 烈焰风暴 | 对所有敌方造成4点 |
| `DRAW:SELF:1` | 碧蓝龙 | 抽1张牌 |
| `SUMMON:ENEMY:2:token_id` | 地狱咆哮 | 为对手召唤2个token |
| `BUFF:SELF:spell_power:1` | 碧蓝龙光环 | +1法强 |
| `GIVE:FRIENDLY_HERO:IMMUNE` | 暗影之刃 | 英雄免疫 |
| `HEAL:SINGLE_TARGET:5` | 治疗之触 | 恢复5点生命 |
| `DISCOVER:SELF:3` | 暗影形态 | 发现3选1 |
| `DAMAGE:RANDOM_ENEMY:3` | 龙人触发 | 随机敌方3点伤害 |

**特征向量化** (给神经网络用):

```python
# EffectKind one-hot (35维) + TargetKind one-hot (13维) + value (1维) + meta flags (3维)
ABILITY_TAG_DIM = 35 + 13 + 1 + 3  # = 52 维

def encode_ability_tag(tag: str) -> np.ndarray:
    parts = tag.split(":")
    kind_idx = EFFECT_KIND_INDEX[parts[0]]      # one-hot
    target_idx = TARGET_KIND_INDEX[parts[1]]    # one-hot
    value = float(parts[2]) if len(parts) > 2 else 0.0
    return np.concatenate([
        one_hot(kind_idx, 35),
        one_hot(target_idx, 13),
        [value],
        meta_flags(parts)
    ])
```

### 3.4 卡牌效果特征矩阵

每张手牌的特征 (用于 I-MCTS 策略网络的输入):

```python
# Card feature vector: [cost(1), attack(1), health(1), type_onehot(5), class_onehot(12),
#                        mechanics_multihot(25), ability_tags_pooled(52×max_abilities)]
CARD_FEATURE_DIM = 1 + 1 + 1 + 5 + 12 + 25 + (52 * 4)  # = 253 维
# max_abilities=4, 不足的 zero-pad，超过的截断
```

### 3.5 训练数据提取器

```python
class TrainingDataExtractor:
    """从 Power.log 提取 (state, action, reward) 训练数据"""

    def __init__(self, card_abilities: dict):
        self.card_abilities = card_abilities  # card_id → abilities JSON

    def extract_sample(
        self,
        state: GameState,
        action: Action,
        reward: float,
        outcome: str
    ) -> dict:
        return {
            "state_vector": self._encode_state(state),
            "action_taken": self._encode_action(action),
            "reward": reward,
            "outcome": outcome
        }

    def _encode_state(self, state: GameState) -> dict:
        return {
            "hero": {
                "hp": state.my_hero.hp,
                "armor": state.my_hero.armor,
                "weapon": self._encode_weapon(state),
                "hero_power_used": state.my_hero.power_used
            },
            "mana": {
                "available": state.my_mana.available,
                "total": state.my_mana.total,
                "overloaded": state.my_mana.overloaded
            },
            "board_friendly": [
                self._encode_minion(m) for m in state.my_board
            ],
            "board_enemy": [
                self._encode_minion(m) for m in state.opp_board
            ],
            "hand": [
                self._encode_hand_card(c) for c in state.my_hand
            ],
            "deck_remaining": state.deck_remaining,
            "opponent_hand_count": state.opp_hand_count,
            "secrets_opponent": len(state.opp_secrets) if state.opp_secrets else 0
        }

    def _encode_hand_card(self, card: Card) -> dict:
        """使用 JSON 声明式数据生成 ability_tags"""
        abilities = self.card_abilities.get(card.card_id, {}).get("abilities", [])
        tags = []
        for ability in abilities:
            for effect in ability.get("effects", []):
                tag = self._effect_to_tag(effect)
                if tag:
                    tags.append(tag)
        return {
            "card_id": card.card_id,
            "cost": card.cost,
            "ability_tags": tags
        }

    def _effect_to_tag(self, effect: dict) -> str:
        kind = effect["kind"]
        target = effect.get("target", {}).get("kind", "NONE")
        value = effect.get("value", 0)
        if isinstance(value, dict):
            value = "dynamic"  # 动态值标记
        meta = ""
        if "meta" in effect:
            card_id = effect["meta"].get("card_id", "")
            if card_id:
                meta = f":{card_id}"
        return f"{kind}:{target}:{value}{meta}"

    def _encode_minion(self, minion) -> dict:
        abilities = self.card_abilities.get(
            getattr(minion, 'card_id', ''), {}
        ).get("abilities", [])
        tags = []
        for ability in abilities:
            for effect in ability.get("effects", []):
                tag = self._effect_to_tag(effect)
                if tag:
                    tags.append(tag)
        return {
            "card_id": getattr(minion, 'card_id', ''),
            "attack": getattr(minion, 'attack', 0),
            "health": getattr(minion, 'health', 0),
            "keywords": list(getattr(minion, 'keywords', [])),
            "ability_tags": tags
        }

    def _encode_action(self, action: Action) -> dict:
        return {
            "type": action.action_type.name,
            "card_index": action.card_index,
            "target_index": action.target_index,
            "source_index": action.source_index
        }

    def _encode_weapon(self, state: GameState) -> dict | None:
        w = state.my_hero.weapon
        if not w or not getattr(w, 'name', ''):
            return None
        return {
            "card_id": getattr(w, 'card_id', ''),
            "attack": getattr(w, 'attack', 0),
            "durability": getattr(w, 'durability', 0)
        }
```

---

## 四、I-MCTS 集成方案

### 4.1 架构概览

```
                         ┌─────────────────────┐
                         │  card_abilities.json │  ← 声明式卡牌效果数据
                         └──────────┬──────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
          ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
          │ GameState    │ │ Action       │ │ Ability Tags │
          │ Encoder      │ │ Encoder      │ │ Pooler       │
          └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
                 │                │                 │
                 └────────┬───────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ State Vector    │  ← 神经网络输入
                 │ (fixed-length)  │
                 └────────┬────────┘
                          │
                  ┌───────┼───────┐
                  ▼               ▼
          ┌──────────────┐ ┌──────────────┐
          │ Policy Net   │ │ Value Net    │
          │ (action prob)│ │ (win chance) │
          └──────┬───────┘ └──────┬───────┘
                 │                │
                 └────────┬───────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │ I-MCTS Engine   │
                 │ (neural + tree) │
                 └─────────────────┘
```

### 4.2 状态编码器

```python
class StateEncoder:
    """将 GameState + JSON abilities → 固定长度向量"""

    def __init__(self, card_abilities: dict):
        self.card_abilities = card_abilities

    def encode(self, state: GameState) -> np.ndarray:
        """返回固定长度的状态向量"""
        features = []

        # 1. 英雄信息 (6维)
        features.extend([
            state.my_hero.hp / 30.0,
            state.my_hero.armor / 30.0,
            1.0 if state.my_hero.weapon else 0.0,
            state.my_mana.available / 10.0,
            state.my_mana.overloaded / 10.0,
            state.my_hero.power_used
        ])

        # 2. 友方场面 (7 × minion_dim)
        for i in range(7):
            if i < len(state.my_board):
                features.extend(self._encode_board_minion(state.my_board[i]))
            else:
                features.extend([0.0] * MINION_DIM)

        # 3. 敌方场面 (7 × minion_dim)
        for i in range(7):
            if i < len(state.opp_board):
                features.extend(self._encode_board_minion(state.opp_board[i]))
            else:
                features.extend([0.0] * MINION_DIM)

        # 4. 手牌 (10 × card_dim)
        for i in range(10):
            if i < len(state.my_hand):
                features.extend(self._encode_card(state.my_hand[i]))
            else:
                features.extend([0.0] * CARD_DIM)

        # 5. 全局信息 (5维)
        features.extend([
            state.deck_remaining / 30.0,
            state.opp_hand_count / 10.0,
            len(state.opp_secrets) / 5.0 if state.opp_secrets else 0.0,
            state.turn / 30.0,
            1.0 if getattr(state, 'opp_playstyle', '') == 'aggro' else 0.0
        ])

        return np.array(features, dtype=np.float32)

    def _encode_card(self, card) -> list:
        """卡牌特征: cost + type + ability_tags pooled"""
        abilities = self.card_abilities.get(card.card_id, {}).get("abilities", [])

        # 基础属性
        feats = [
            card.cost / 10.0,
            1.0 if card.card_type == "MINION" else 0.0,
            1.0 if card.card_type == "SPELL" else 0.0,
            1.0 if card.card_type == "WEAPON" else 0.0,
            getattr(card, 'attack', 0) / 10.0,
            getattr(card, 'health', 0) / 10.0
        ]

        # ability_tags pooled (52 × max_abilities=4, mean pooling)
        tag_vectors = []
        for ability in abilities:
            for effect in ability.get("effects", []):
                tag = self._effect_to_tag(effect)
                if tag:
                    tag_vectors.append(encode_ability_tag(tag))

        if tag_vectors:
            pooled = np.mean(tag_vectors[:4], axis=0)
        else:
            pooled = np.zeros(ABILITY_TAG_DIM)

        feats.extend(pooled.tolist())
        return feats

    def _encode_board_minion(self, minion) -> list:
        """场面随从特征"""
        # ... similar pattern with ability tags
```

### 4.3 Action 编码

```python
class ActionEncoder:
    """将 Action → 神经网络可用的 action mask + features"""

    ACTION_TYPES = ["PLAY", "ATTACK", "HERO_POWER", "END_TURN",
                    "ACTIVATE_LOCATION", "DISCOVER_PICK", "CHOOSE_ONE"]

    def encode_action_space(self, state: GameState) -> tuple:
        """
        Returns:
            action_mask: np.ndarray [max_actions] — 合法动作掩码
            action_features: np.ndarray [max_actions, action_dim] — 动作特征
        """
        legal_actions = enumerate_legal_actions(state)
        mask = np.zeros(MAX_ACTIONS, dtype=np.float32)
        features = np.zeros((MAX_ACTIONS, ACTION_DIM), dtype=np.float32)

        for i, action in enumerate(legal_actions[:MAX_ACTIONS]):
            mask[i] = 1.0
            features[i] = self._encode_single_action(action, state)

        return mask, features

    def _encode_single_action(self, action: Action, state: GameState) -> np.ndarray:
        type_onehot = [0.0] * len(self.ACTION_TYPES)
        type_idx = self.ACTION_TYPES.index(action.action_type.name) \
            if action.action_type.name in self.ACTION_TYPES else 0
        type_onehot[type_idx] = 1.0

        # 如果是出牌，附带卡牌特征
        card_feats = [0.0] * 8
        if action.action_type.name in ("PLAY", "PLAY_WITH_TARGET"):
            if 0 <= action.card_index < len(state.my_hand):
                card = state.my_hand[action.card_index]
                card_feats = [
                    card.cost / 10.0,
                    1.0 if card.card_type == "MINION" else 0.0,
                    1.0 if card.card_type == "SPELL" else 0.0,
                    1.0 if card.card_type == "WEAPON" else 0.0,
                    getattr(card, 'attack', 0) / 10.0,
                    getattr(card, 'health', 0) / 10.0,
                    1.0 if action.target_index >= 0 else 0.0,
                    action.target_index / 7.0 if action.target_index >= 0 else 0.0
                ]

        # 如果是攻击
        attack_feats = [0.0] * 4
        if action.action_type.name == "ATTACK":
            attack_feats = [
                action.source_index / 7.0,
                action.target_index / 8.0 if action.target_index >= 0 else 0.0,
                1.0,  # is_attack
                0.0
            ]

        return np.array(type_onehot + card_feats + attack_feats, dtype=np.float32)
```

### 4.4 I-MCTS 神经增强

```python
class NeuralMCTS:
    """I-MCTS: MCTS + 神经网络策略/价值引导"""

    def __init__(self, policy_net, value_net, state_encoder, action_encoder):
        self.policy_net = policy_net
        self.value_net = value_net
        self.state_encoder = state_encoder
        self.action_encoder = action_encoder

    def search(self, state: GameState, time_budget_ms: float) -> SearchResult:
        state_vec = self.state_encoder.encode(state)

        # 1. 神经网络先验
        action_mask, action_features = self.action_encoder.encode_action_space(state)
        policy_logits = self.policy_net(state_vec, action_mask, action_features)
        value_prior = self.value_net(state_vec)

        # 2. MCTS 搜索 (使用神经网络先验 + UCB)
        root = MCTSNode(state, prior=policy_logits)

        # ... standard MCTS loop with neural-guided selection ...

        return self._extract_result(root)
```

---

## 五、系统架构变更

### 5.1 目标目录结构

```
analysis/
├── abilities/                        ← [提升] 从 search/abilities/ 提升为顶层包
│   ├── __init__.py                   ← 重写公共 API
│   ├── definition.py                 ← [修改] 添加 to_json()/from_json()
│   ├── value_expr.py                 ← [新增] 值表达式解析器 ($attr, $count, $ref...)
│   ├── executor.py                   ← [重写] if-chain → EffectDispatcher 分发表
│   ├── orchestrator.py               ← [保留] 触发调度，改用分发表
│   ├── simulation.py                 ← [保留] apply_action，改用 JSON abilities
│   ├── enumeration.py                ← [保留] 合法动作枚举
│   └── mechanics/                    ← [新增目录] 收编散落 mechanic 模块
│       ├── __init__.py
│       ├── dark_gift.py              ← ← 从 search/dark_gift.py 迁入
│       ├── discover.py               ← ← 从 search/discover.py 迁入
│       ├── deathrattle.py            ← ← 从 search/deathrattle.py 迁入
│       ├── dormant.py                ← ← 从 search/dormant.py 迁入
│       ├── herald.py                 ← ← 从 search/herald.py 迁入
│       ├── imbue.py                  ← ← 从 search/imbue.py 迁入
│       ├── colossal.py               ← ← 从 search/colossal.py 迁入
│       ├── corpse.py                 ← ← 从 search/corpse.py 迁入
│       ├── kindred.py                ← ← 从 search/kindred.py 迁入
│       ├── outcast.py                ← ← 从 search/outcast.py 迁入
│       ├── shatter.py                ← ← 从 search/shatter.py 迁入
│       ├── choose_one.py             ← ← 从 search/choose_one.py 迁入
│       ├── quest.py                  ← ← 从 search/quest.py 迁入
│       ├── location.py               ← ← 从 search/location.py 迁入
│       └── secret_triggers.py        ← ← 从 search/secret_triggers.py 迁入
│
├── data/
│   ├── card_abilities.json           ← [新增] 声明式卡牌能力数据 (主数据文件)
│   ├── card_data.py                  ← [修改] 添加 load_abilities() + 淘汰旧单例
│   ├── card_effects.py               ← [删除] 被 card_abilities.json 完全替代
│   ├── card_index.py                 ← [删除] 纯 re-export shim (11行)
│   ├── hsdb.py                       ← [删除] 纯 re-export shim (16行)
│   ├── card_roles.py                 ← [删除] 角色分类并入 card_abilities.json
│   ├── card_cleaner.py               ← [删除] 废弃的遗留数据标准化器
│   ├── token_cards.py                ← [保留] token 数据，后续迁移到 JSON
│   └── fetch_hsreplay.py            ← [保留] HSReplay 数据抓取器
│
├── models/
│   ├── card.py                       ← [修改] abilities 从 JSON 预填充，删除惰性 parser 调用
│   └── __init__.py                   ← [修改] phase.py 内容并入此文件
│
├── search/                           ← [精简] 只保留搜索核心
│   ├── game_state.py                 ← [保留] 核心状态
│   ├── entity.py                     ← [保留] 实体/区域
│   ├── zone_manager.py               ← [保留] 区域管理
│   ├── enchantment.py                ← [修改] 合并 trigger_registry.py
│   ├── keywords.py                   ← [保留] 关键词集合
│   ├── aura_engine.py                ← [保留] 光环引擎
│   ├── trigger_system.py             ← [保留] 触发器系统
│   ├── mechanics_state.py            ← [保留] mechanic 状态容器
│   ├── opponent_simulator.py         ← [保留] 对手模拟
│   ├── lethal_checker.py             ← [保留] 致命检测
│   ├── risk_assessor.py              ← [保留] 风险评估
│   ├── power_parser.py               ← [保留] 离线 Power.log 解析
│   ├── engine_adapter.py             ← [保留] 引擎适配器
│   ├── action_normalize.py           ← [保留] 动作标准化
│   │
│   ├── pipeline/                     ← [重命名] engine/ → pipeline/
│   │   └── ... (不变)
│   │
│   └── mcts/                         ← [保留+扩展]
│       ├── engine.py                 ← [保留]
│       ├── neural_mcts.py            ← [新增] I-MCTS 神经增强引擎
│       └── ... (其余不变)
│
├── training/                         ← [新增] 训练数据管道
│   ├── __init__.py
│   ├── extractor.py                  ← TrainingDataExtractor
│   ├── encoder.py                    ← StateEncoder + ActionEncoder
│   ├── ability_tags.py               ← ability_tags 特征编码
│   └── pipeline.py                   ← Power.log → JSONL 批处理管道
│
├── scorers/                          ← [保留] 不变
├── evaluators/                       ← [保留] 不变
├── watcher/                          ← [保留] 不变 (范围外)
├── utils/                            ← [保留] 不变
└── constants/                        ← [保留] 不变
```

### 5.2 文件删除清单

以下文件在新架构中**不再需要**，JSON 声明式数据完全替代了它们的功能：

| 文件 | 行数 | 删除原因 | 替代方案 |
|------|------|----------|----------|
| `data/card_effects.py` | 309 | CN+EN regex 提取效果 → JSON 声明式数据直接包含 | `card_abilities.json` |
| `data/card_index.py` | 11 | 纯 re-export shim (`CardDB as CardIndex`) | 直接使用 `CardDB` |
| `data/hsdb.py` | 16 | 纯 re-export shim (`from card_data import *`) | 直接使用 `card_data` |
| `data/card_roles.py` | 104 | 角色分类基于 card_effects → JSON 包含 role tags | `card_abilities.json` 的 `role_tags` 字段 |
| `data/card_cleaner.py` | ~100 | 废弃的遗留数据标准化器，已被 CardDB 取代 | 已无消费者 |
| `search/abilities/parser.py` | 449 | 运行时文本解析 → JSON 预加载 | 降级为 `scripts/build_card_abilities.py` 离线工具 |
| `search/abilities/extractors.py` | ~200 | parser 的字符串辅助函数 | 随 parser 一起移除 |
| `search/abilities/tokens.py` | ~250 | parser 的映射表 | 映射关系固化到 JSON 数据 |
| `search/effects.py` | ~150 | System 3: 独立 EffectKind + colon-string dispatch | 分发表 + `definition.py` 统一 EffectKind |
| `search/corrupt.py` | 49 | 微型 mechanic，逻辑并入 executor | `EffectKind.CORRUPT_UPGRADE` handler |
| `search/rewind.py` | 61 | 微型 mechanic，逻辑并入 executor | `EffectKind.REWIND` handler |
| `search/rune.py` | 15 | 微型 mechanic，逻辑并入 discover 过滤 | discover pool filter |
| `models/phase.py` | 15 | 15行不值得独立文件 | 并入 `models/__init__.py` |

**共删除 ~1,729 行代码** (不含空行和注释)

### 5.3 文件合并清单

| 源文件 | 目标文件 | 合并内容 |
|--------|----------|----------|
| `search/trigger_registry.py` (95行) | `search/enchantment.py` | 触发器注册是附魔数据的一部分 |
| `search/corrupt.py` (49行) + `search/rewind.py` (61行) | `abilities/executor.py` | 微型 mechanic handler 注册到分发表 |
| `search/abilities/actions.py` (106行) | `abilities/definition.py` | ActionType/Action 是能力系统的核心类型 |
| `models/phase.py` (15行) | `models/__init__.py` | Phase enum 直接导出 |
| `search/effects.py` EffectKind | `abilities/definition.py` EffectKind | 统一为单一 EffectKind 枚举 |

### 5.4 文件迁移清单 (search/ → abilities/mechanics/)

12 个散落在 `search/` 根目录的 mechanic 模块迁入 `abilities/mechanics/` 子包：

| 原路径 | 新路径 | 行数 |
|--------|--------|------|
| `search/dark_gift.py` | `abilities/mechanics/dark_gift.py` | 95 |
| `search/discover.py` | `abilities/mechanics/discover.py` | ~150 |
| `search/deathrattle.py` | `abilities/mechanics/deathrattle.py` | 141 |
| `search/dormant.py` | `abilities/mechanics/dormant.py` | 50 |
| `search/herald.py` | `abilities/mechanics/herald.py` | 86 |
| `search/imbue.py` | `abilities/mechanics/imbue.py` | 204 |
| `search/colossal.py` | `abilities/mechanics/colossal.py` | ~80 |
| `search/corpse.py` | `abilities/mechanics/corpse.py` | 222 |
| `search/kindred.py` | `abilities/mechanics/kindred.py` | ~100 |
| `search/outcast.py` | `abilities/mechanics/outcast.py` | 110 |
| `search/shatter.py` | `abilities/mechanics/shatter.py` | 74 |
| `search/choose_one.py` | `abilities/mechanics/choose_one.py` | 159 |
| `search/quest.py` | `abilities/mechanics/quest.py` | 265 |
| `search/location.py` | `abilities/mechanics/location.py` | 210 |
| `search/secret_triggers.py` | `abilities/mechanics/secret_triggers.py` | 143 |

### 5.5 文件修改清单

| 文件 | 修改内容 |
|------|----------|
| `abilities/definition.py` | 添加 `to_json()`/`from_json()` 序列化；合并 `actions.py` 的 ActionType/Action；合并 `effects.py` 的 EffectKind |
| `abilities/executor.py` | if-chain → `EffectDispatcher` 分发表；合并 corrupt/rewind handler |
| `abilities/orchestrator.py` | 改用分发表 `dispatcher.dispatch()`；import 路径更新 |
| `abilities/simulation.py` | `Card.abilities` 从 JSON 加载而非 parser；import 路径更新 |
| `abilities/enumeration.py` | import 路径更新 |
| `data/card_data.py` | 添加 `CardDB.load_abilities(path)` + `CardDB.get_abilities(card_id)` |
| `models/card.py` | `abilities` 属性改为从 JSON 预填充，删除惰性 `AbilityParser.parse()` 调用；`roles` 从 JSON `role_tags` 加载 |
| `search/enchantment.py` | 合并 `trigger_registry.py` 内容 |
| `search/game_state.py` | import 路径更新 (`abilities.mechanics.*`) |
| `search/mcts/engine.py` | import 路径更新 |
| `search/mcts/turn_advance.py` | import 路径更新 |
| `search/engine_adapter.py` | import 路径更新 |
| `watcher/decision_loop.py` | import 路径更新 |
| `watcher/state_bridge.py` | import 路径更新 |
| `evaluators/composite.py` | import 路径更新（`card_effects` → JSON） |
| `scorers/scoring_engine.py` | import 路径更新（`card_effects` → JSON） |

### 5.6 新增文件清单

| 文件 | 描述 |
|------|------|
| `data/card_abilities.json` | 声明式卡牌能力数据 (主数据文件) |
| `abilities/value_expr.py` | 值表达式解析器 (`$attr`, `$count`, `$ref`, `$add`...) |
| `abilities/mechanics/__init__.py` | mechanic 子包公共 API |
| `training/__init__.py` | 训练管道包 |
| `training/extractor.py` | TrainingDataExtractor (Power.log → 训练样本) |
| `training/encoder.py` | StateEncoder + ActionEncoder (→ 神经网络输入) |
| `training/ability_tags.py` | ability_tags 特征编码 (52维向量) |
| `training/pipeline.py` | Power.log → JSONL 批处理管道 |
| `search/mcts/neural_mcts.py` | I-MCTS 神经增强 MCTS 引擎 |
| `scripts/build_card_abilities.py` | 离线 JSON 构建器 (parser → JSON 导出) |

### 5.7 变更汇总

| 操作 | 数量 | 说明 |
|------|------|------|
| **删除** | 13 文件 | shim、废弃代码、被 JSON 替代的解析器 |
| **合并** | 5 组 | 小文件并入同域大文件 |
| **迁移** | 15 文件 | mechanic 模块 search/ → abilities/mechanics/ |
| **修改** | 15+ 文件 | import 路径、序列化、分发表等 |
| **新增** | 10 文件 | JSON 数据、value_expr、training 管道、I-MCTS |
| **删除代码** | ~1,729 行 | 解析器、shim、regex 提取等 |
| **新增代码** | ~1,200 行 | value_expr、训练管道、I-MCTS (不含 JSON 数据) |
| **净减少** | ~500 行 | 代码更少，功能更强 |

### 5.3 值表达式解析器

```python
# abilities/value_expr.py

class ValueExpr:
    """声明式值表达式的运行时求值器"""

    def resolve(self, state, source=None) -> int:
        raise NotImplementedError

class LiteralValue(ValueExpr):
    def __init__(self, value: int):
        self.value = value
    def resolve(self, state, source=None) -> int:
        return self.value

class AttrRef(ValueExpr):
    def __init__(self, attr_path: str):
        self.attr_path = attr_path
    def resolve(self, state, source=None) -> int:
        # "source.attack" → source.attack
        # "hero.armor" → state.my_hero.armor
        parts = self.attr_path.split(".")
        obj = {"source": source, "hero": state.my_hero,
               "target": None}.get(parts[0])
        if obj is None and len(parts) > 1:
            obj = state
        for part in parts[1:]:
            obj = getattr(obj, part, 0)
        return int(obj) if obj else 0

class CountRef(ValueExpr):
    def __init__(self, field: str):
        self.field = field
    def resolve(self, state, source=None) -> int:
        counts = {
            "friendly_minions": lambda: len(state.my_board),
            "enemy_minions": lambda: len(state.opp_board),
            "damaged_friendly": lambda: sum(1 for m in state.my_board
                                            if getattr(m, 'damage_taken', 0) > 0),
            "hand": lambda: len(state.my_hand),
            "secrets": lambda: len(state.opp_secrets) if state.opp_secrets else 0,
        }
        fn = counts.get(self.field)
        return fn() if fn else 0

class BinaryOp(ValueExpr):
    def __init__(self, op: str, left: ValueExpr, right: ValueExpr):
        self.op = op
        self.left = left
        self.right = right
    def resolve(self, state, source=None) -> int:
        l = self.left.resolve(state, source)
        r = self.right.resolve(state, source)
        ops = {"$add": lambda a, b: a + b,
               "$sub": lambda a, b: a - b,
               "$mul": lambda a, b: a * b,
               "$max": lambda a, b: max(a, b),
               "$min": lambda a, b: min(a, b)}
        return ops.get(self.op, lambda a, b: 0)(l, r)

class ConditionalValue(ValueExpr):
    def __init__(self, condition: dict, then_val: ValueExpr, else_val: ValueExpr):
        self.condition = condition
        self.then_val = then_val
        self.else_val = else_val
    def resolve(self, state, source=None) -> int:
        if evaluate_condition(self.condition, state, source):
            return self.then_val.resolve(state, source)
        return self.else_val.resolve(state, source)


def parse_value_expr(data) -> ValueExpr:
    """将 JSON 值表达式解析为 ValueExpr 树"""
    if isinstance(data, (int, float)):
        return LiteralValue(int(data))
    if isinstance(data, dict):
        if "$attr" in data:
            return AttrRef(data["$attr"])
        if "$count" in data:
            return CountRef(data["$count"])
        if "$add" in data or "$sub" in data or "$mul" in data:
            for op in ("$add", "$sub", "$mul", "$max", "$min"):
                if op in data:
                    left = parse_value_expr(data[op][0])
                    right = parse_value_expr(data[op][1])
                    return BinaryOp(op, left, right)
        if "$if" in data:
            cond = data["$if"]["condition"]
            then_val = parse_value_expr(data["$if"]["then"])
            else_val = parse_value_expr(data["$if"]["else"])
            return ConditionalValue(cond, then_val, else_val)
        if "$random" in data:
            # 运行时随机值 — 返回期望值用于确定性评估
            r = data["$random"]
            return LiteralValue((r["min"] + r["max"]) // 2)
    return LiteralValue(0)
```

### 5.4 执行器分发表

```python
# abilities/executor.py — 从 if-chain 到分发表

class EffectDispatcher:
    """效果分发表 — 替代 if-chain"""

    def __init__(self):
        self._handlers: dict[EffectKind, Callable] = {}
        self._register_defaults()

    def register(self, kind: EffectKind, handler: Callable):
        self._handlers[kind] = handler

    def dispatch(self, state: GameState, effect: EffectSpec,
                 source=None, target=None) -> GameState:
        handler = self._handlers.get(effect.kind)
        if handler:
            return handler(state, effect, source, target)
        return state

    def _register_defaults(self):
        self.register(EffectKind.DAMAGE, self._exec_damage)
        self.register(EffectKind.SUMMON, self._exec_summon)
        self.register(EffectKind.DRAW, self._exec_draw)
        self.register(EffectKind.HEAL, self._exec_heal)
        self.register(EffectKind.BUFF, self._exec_buff)
        self.register(EffectKind.DESTROY, self._exec_destroy)
        # ... 其余 30+ handlers

# 全局单例
dispatcher = EffectDispatcher()
```

---

## 六、实施路线图

### Phase Q1: 基础设施 + 删除 shim（2-3 天）

1. **Q1-1**: 删除 shim 文件: `card_index.py`, `hsdb.py`, `card_cleaner.py`, `models/phase.py` (→ 并入 `models/__init__.py`)
2. **Q1-2**: 创建 `abilities/value_expr.py` — 值表达式解析器 ($attr, $count, $ref, $add...)
3. **Q1-3**: 为 `definition.py` 添加 `to_json()` / `from_json()` 序列化
4. **Q1-4**: 重写 `executor.py` if-chain → `EffectDispatcher` 分发表
5. **Q1-5**: 合并 `actions.py` → `definition.py`, `corrupt.py` + `rewind.py` → executor handlers
6. **验证**: 613 tests passed + 全部 import 路径修复

### Phase Q2: JSON 数据构建 + 删除解析器（3-5 天）

1. **Q2-1**: 编写 `scripts/build_card_abilities.py` — 离线构建器
   - 输入: HearthstoneJSON + 当前 parser + card_effects
   - 输出: `data/card_abilities.json`
   - 策略: 先用现有 parser 跑一遍全部卡牌，导出为 JSON
2. **Q2-2**: 手动审核高频卡牌（Tier1 卡组 50 张）
3. **Q2-3**: `CardDB.load_abilities()` + `Card.abilities` 改为 JSON 预填充
4. **Q2-4**: 删除运行时解析器: `parser.py`, `extractors.py`, `tokens.py`, `card_effects.py`, `card_roles.py`
5. **Q2-5**: 删除 `effects.py` (System 3)，统一到 definition.py EffectKind
6. **Q2-6**: 更新所有消费者 import 路径
7. **验证**: 对比 parser 输出与 JSON 输出一致性 + 全部测试通过

### Phase Q3: Mechanic 迁移 + 训练数据管道（4-5 天）

1. **Q3-1**: 创建 `abilities/mechanics/` 子包，迁移 15 个 mechanic 模块
2. **Q3-2**: 合并 `trigger_registry.py` → `enchantment.py`
3. **Q3-3**: `training/ability_tags.py` — 特征编码
4. **Q3-4**: `training/extractor.py` — TrainingDataExtractor
5. **Q3-5**: `training/encoder.py` — StateEncoder + ActionEncoder
6. **Q3-6**: `training/pipeline.py` — Power.log → JSONL 批处理
7. **验证**: 全部测试通过 + 从已有 Power.log 生成训练样本，人工检查质量

### Phase Q4: I-MCTS 集成（5-7 天）

1. **Q4-1**: `search/mcts/neural_mcts.py` — I-MCTS 框架
2. **Q4-2**: 策略网络 (轻量 MLP 或 Transformer)
3. **Q4-3**: 价值网络 (轻量 MLP)
4. **Q4-4**: 训练循环 + 评估
5. **验证**: I-MCTS vs 纯 MCTS 对比测试

### 与已有 P7-P11 计划的关系

```
P7 (CN regex 迁移) ← Q1-Q2 并行完成 (删除解析器 = 删除 CN regex)
P8 (effects.py 合并) ← Q2-5 直接删除 effects.py
P9 (mechanic 收编) ← Q3-1 迁移到 abilities/mechanics/
P10 (解耦清理) ← Q1-Q3 自然完成 (shim删除、分发表、import整理)
P11 (I-MCTS 就绪) ← Q4 直接实现
```

**关键**: Q1-Q4 **替代** P7-P11，不是并行方案。删除解析器比迁移 CN regex 更彻底。

---

## 七、风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| JSON 覆盖不全 | 高 | 中 | 现有 parser 作为 fallback，逐步覆盖 |
| 值表达式语言不够表达 | 中 | 高 | 保留 Python handler 扩展点 |
| 训练数据质量 | 中 | 高 | 人工审核 + 对比实验 |
| 性能回退 | 低 | 高 | JSON 加载比 parser 快，预期性能提升 |
| 过度工程 | 中 | 中 | 分阶段实施，每阶段独立可用 |

---

## 八、设计原则

1. **数据 > 代码** — 卡牌效果是数据文件，不是 Python 代码
2. **离线 > 在线** — 解析在构建时完成，运行时只做加载
3. **声明式 > 命令式** — JSON 描述"做什么"，executor 决定"怎么做"
4. **可序列化 > 可执行** — 所有效果可以转为 JSON，便于 ML 训练
5. **渐进 > 革命** — 分阶段实施，每阶段独立可用，不破坏现有功能

---

## 九、参考

- [card-effect-parsing-standard.md](./card-effect-parsing-standard.md) — 设计标准
- [analysis-full-refactoring-design.md](./analysis-full-refactoring-design.md) — P7-P11 实施计划
- [2026-04-26-card-game-simulator-architecture-survey.md](../research/2026-04-26-card-game-simulator-architecture-survey.md) — 成熟项目调研
- [merge-analysis.md](./merge-analysis.md) — 文件合并分析
- [refactoring-architecture-plan.md](./refactoring-architecture-plan.md) — 重构架构计划

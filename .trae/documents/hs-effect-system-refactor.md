# 炉石模拟引擎效果系统重构方案 v3

## 一、真实数据分析结果

### 1.1 数据源：`cards.collectible.json`（enUS）— 7898 张卡

### 1.2 Card Types（5 种）

| Type     | Count | 引擎当前处理    |
| -------- | ----- | --------- |
| MINION   | 4631  | ✅ 有       |
| SPELL    | 2230  | ✅ 有       |
| HERO     | 745   | ⚠️ 部分     |
| WEAPON   | 235   | ✅ 有       |
| LOCATION | 57    | ❌ 缺失（刚修复） |

### 1.3 Mechanics Tags（30 种，取前 15）

| Mechanics       | Count | 触发时机映射         |
| --------------- | ----- | -------------- |
| BATTLECRY       | 2239  | `ON_PLAY`      |
| TRIGGER\_VISUAL | 936   | `文本解析`         |
| DEATHRATTLE     | 670   | `ON_DEATH`     |
| TAUNT           | 477   | `静态关键词`        |
| DISCOVER        | 368   | `ON_PLAY`      |
| RUSH            | 238   | `静态关键词`        |
| AURA            | 171   | `持续光环`         |
| LIFESTEAL       | 133   | `静态关键词`        |
| SECRET          | 117   | `对手动作触发`       |
| CHOOSE\_ONE     | 101   | `ON_PLAY + 分支` |
| DIVINE\_SHIELD  | 93    | `静态关键词`        |
| COMBO           | 83    | `ON_PLAY + 条件` |
| STEALTH         | 83    | `静态关键词`        |
| OVERLOAD        | 81    | `ON_PLAY + 延迟` |
| SPELLPOWER      | 57    | `静态被动`         |

### 1.4 Action Verbs in Text（效果动词频率）

| Verb      | Count | 效果类型                                      |
| --------- | ----- | ----------------------------------------- |
| summon    | 972   | SUMMON                                    |
| deal      | 866   | DAMAGE                                    |
| give      | 747   | BUFF / GIVE\_KEYWORD                      |
| draw      | 532   | DRAW                                      |
| gain      | 513   | GAIN\_ARMOR / GAIN\_HEALTH / GAIN\_ATTACK |
| destroy   | 277   | DESTROY                                   |
| copy      | 265   | COPY                                      |
| cast      | 258   | CAST / DISCOVER\_CAST                     |
| play      | 169   | (条件/触发)                                   |
| restore   | 158   | HEAL                                      |
| shuffle   | 115   | SHUFFLE                                   |
| reduce    | 88    | COST\_REDUCTION                           |
| transform | 84    | TRANSFORM                                 |
| return    | 79    | RETURN\_TO\_HAND                          |
| control   | 77    | TAKE\_CONTROL                             |
| discard   | 56    | DISCARD                                   |
| swap      | 45    | SWAP\_STATS                               |
| equip     | 36    | WEAPON\_EQUIP                             |

### 1.5 Condition Patterns（条件模式频率）

| Pattern          | Count | 条件类型           |
| ---------------- | ----- | -------------- |
| "if you"         | 539   | 通用条件前缀         |
| "after"          | 472   | AFTER 触发       |
| "this turn"      | 333   | 本回合状态          |
| "whenever"       | 292   | WHENEVER 触发    |
| "for each"       | 264   | 计数条件           |
| "at the end"     | 230   | TURN\_END 触发   |
| "you're holding" | 86    | 手牌条件           |
| "at the start"   | 77    | TURN\_START 触发 |
| "costs less"     | 1+    | 费用条件           |
| "if your"        | 140   | 场景状态条件         |

### 1.6 Target Patterns（目标模式频率）

| Pattern        | Count | 目标类型             |
| -------------- | ----- | ---------------- |
| "a minion"     | 711   | SINGLE\_MINION   |
| "a random"     | 579   | RANDOM           |
| "your hero"    | 450   | FRIENDLY\_HERO   |
| "a friendly"   | 320   | FRIENDLY\_MINION |
| "random enemy" | 169   | RANDOM\_ENEMY    |
| "all minions"  | 166   | ALL\_MINIONS     |
| "an enemy"     | 138   | ENEMY            |
| "all enemies"  | 90    | ALL\_ENEMY       |

***

## 二、数据模型设计（基于真实数据）

### 2.1 CardAbility 数据模型

```python
class AbilityTrigger(Enum):
    # From mechanics tags (direct 1:1 mapping)
    BATTLECRY = "BATTLECRY"           # 2239 cards
    DEATHRATTLE = "DEATHRATTLE"       # 670 cards
    SECRET = "SECRET"                 # 117 cards
    INSPIRE = "INSPIRE"               # 27 cards
    CHOOSE_ONE = "CHOOSE_ONE"         # 101 cards
    COMBO = "COMBO"                   # 83 cards
    OUTCAST = "OUTCAST"               # 33 cards
    SPELLBURST = "SPELLBURST"         # 43 cards
    INFUSE = "INFUSE"                 # 52 cards
    CORRUPT = "CORRUPT"              # 31 cards
    QUEST = "QUEST"                   # 30 cards

    # From text patterns
    TURN_START = "TURN_START"         # 77 cards ("at the start of your turn")
    TURN_END = "TURN_END"             # 230 cards ("at the end of your turn")
    WHENEVER = "WHENEVER"             # 292 cards
    AFTER = "AFTER"                   # 472 cards
    ON_ATTACK = "ON_ATTACK"
    ON_DAMAGE = "ON_DAMAGE"
    ON_SPELL_CAST = "ON_SPELL_CAST"

    # Passive / continuous
    AURA = "AURA"                     # 171 cards (mechanics tag)
    PASSIVE_COST = "PASSIVE_COST"     # cost reduction in text
    ACTIVATE = "ACTIVATE"             # LOCATION cards (57)
    TRIGGER_VISUAL = "TRIGGER_VISUAL" # 936 cards (complex triggers)

class EffectKind(Enum):
    # Top action verbs from data
    DAMAGE = "DAMAGE"                 # deal (866)
    SUMMON = "SUMMON"                 # summon (972)
    DRAW = "DRAW"                     # draw (532)
    GAIN = "GAIN"                     # gain (513) - armor/health/attack
    GIVE = "GIVE"                     # give (747) - keyword/buff
    DESTROY = "DESTROY"               # destroy (277)
    COPY = "COPY"                     # copy (265)
    HEAL = "HEAL"                     # restore (158)
    SHUFFLE = "SHUFFLE"               # shuffle (115)
    REDUCE_COST = "REDUCE_COST"       # reduce (88)
    TRANSFORM = "TRANSFORM"           # transform (84)
    RETURN = "RETURN"                 # return (79)
    TAKE_CONTROL = "TAKE_CONTROL"     # control (77)
    DISCARD = "DISCARD"               # discard (56)
    SWAP = "SWAP"                     # swap (45)
    WEAPON_EQUIP = "WEAPON_EQUIP"     # equip (36)
    DISCOVER = "DISCOVER"             # 368 cards
    FREEZE = "FREEZE"
    SILENCE = "SILENCE"
    CAST_SPELL = "CAST_SPELL"         # cast (258)

class ConditionKind(Enum):
    HOLDING_RACE = "HOLDING_RACE"     # 86 cards ("you're holding a Dragon")
    THIS_TURN = "THIS_TURN"           # 333 cards ("this turn")
    FOR_EACH = "FOR_EACH"             # 264 cards ("for each")
    HAS_KEYWORD = "HAS_KEYWORD"       # 183 cards ("has taunt/rush/etc")
    PLAYED_THIS_TURN = "PLAYED_THIS_TURN"  # "if you've played a Fire spell"
    COST_COMPARISON = "COST_COMPARISON"  # "costs more/less"
    HEALTH_THRESHOLD = "HEALTH_THRESHOLD"  # "if you have 15 or less"

class TargetKind(Enum):
    SINGLE_MINION = "SINGLE_MINION"   # 711 ("a minion")
    RANDOM = "RANDOM"                 # 579 ("a random")
    FRIENDLY_HERO = "FRIENDLY_HERO"   # 450 ("your hero")
    FRIENDLY_MINION = "FRIENDLY_MINION" # 320 ("a friendly")
    RANDOM_ENEMY = "RANDOM_ENEMY"     # 169 ("random enemy")
    ALL_MINIONS = "ALL_MINIONS"       # 166 ("all minions")
    ENEMY = "ENEMY"                   # 138 ("an enemy")
    ALL_ENEMY = "ALL_ENEMY"           # 90 ("all enemies")
    ALL_FRIENDLY = "ALL_FRIENDLY"     # 33 ("all friendly")
    DAMAGED = "DAMAGED"               # 96 ("damaged")
    UNDAMAGED = "UNDAMAGED"           # 11 ("undamaged")
    SELF = "SELF"                     # self-reference
```

### 2.2 Mechanics 标签 → 触发时机映射表（零解析）

```python
MECHANICS_TRIGGER_MAP = {
    "BATTLECRY":       AbilityTrigger.BATTLECRY,
    "DEATHRATTLE":     AbilityTrigger.DEATHRATTLE,
    "SECRET":          AbilityTrigger.SECRET,
    "INSPIRE":         AbilityTrigger.INSPIRE,
    "CHOOSE_ONE":      AbilityTrigger.CHOOSE_ONE,
    "COMBO":           AbilityTrigger.COMBO,
    "OUTCAST":         AbilityTrigger.OUTCAST,
    "SPELLBURST":      AbilityTrigger.ON_SPELL_CAST,
    "INFUSE":          AbilityTrigger.INFUSE,
    "CORRUPT":         AbilityTrigger.CORRUPT,
    "QUEST":           AbilityTrigger.QUEST,
    "AURA":            AbilityTrigger.AURA,
    "TRIGGER_VISUAL":  AbilityTrigger.TRIGGER_VISUAL,
}
```

### 2.3 Mechanics 标签 → 静态关键词映射（不需要能力解析）

```python
STATIC_KEYWORD_MECHANICS = {
    "TAUNT", "RUSH", "LIFESTEAL", "DIVINE_SHIELD", "STEALTH",
    "CHARGE", "WINDFURY", "POISONOUS", "REBORN", "ELUSIVE",
    "FREEZE", "SPELLPOWER", "OVERLOAD", "TRADEABLE",
}
```

这些 mechanics 是**静态属性**，不需要解析为 CardAbility。直接附加到 Minion 的 keywords 集合。

***

## 三、解析器设计（基于真实频率排序）

### 3.1 解析优先级（按频率）

```
1. mechanics 标签 → 触发时机（2239 BATTLECRY, 670 DEATHRATTLE, ...）
2. text 动词 → 效果类型（972 summon, 866 deal, 747 give, 532 draw, ...）
3. text 条件 → 条件类型（539 if you, 292 whenever, 264 for each, ...）
4. text 目标 → 目标类型（711 a minion, 579 a random, 320 a friendly, ...）
5. card.type → 特殊处理（LOCATION → ACTIVATE, 57 cards）
```

### 3.2 文本清洗（去掉 HTML 标记，非正则）

```python
def clean_text(text: str) -> str:
    """Remove Hearthstone HTML markup from card text."""
    result = text
    # Remove <b>, </b>, <i>, </i> tags
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        result = result.replace(tag, "")
    # Replace $N and #N with just N
    # [x] is card text overflow marker, remove it
    result = result.replace("[x]", "")
    # Replace \n with space
    result = result.replace("\n", " ")
    # Collapse multiple spaces
    while "  " in result:
        result = result.replace("  ", " ")
    return result.strip()
```

### 3.3 动词 → 效果提取（string.find + split，零正则）

按数据频率排序的匹配逻辑：

```python
def parse_effects(text: str) -> List[EffectSpec]:
    effects = []
    tl = text.lower()

    # summon (972) — "summon a 2/2 Ghost" / "summon two 1/1 Pirates"
    if "summon" in tl:
        atk, hp = extract_stats_after(tl, "summon")
        target = extract_summon_target(tl)
        effects.append(EffectSpec(EffectKind.SUMMON, value=atk, value2=hp))

    # deal (866) — "deal 5 damage" / "deal 3 damage randomly split"
    if "deal" in tl and "damage" in tl:
        amount = extract_number_after(tl, "deal")
        target = extract_target_kind(tl)
        effects.append(EffectSpec(EffectKind.DAMAGE, value=amount, target=target))

    # give (747) — "give +2/+1" / "give it Rush" / "give a friendly minion +2 Attack"
    if "give" in tl:
        atk, hp = extract_plus_stats(tl)
        if atk > 0 or hp > 0:
            effects.append(EffectSpec(EffectKind.GIVE, value=atk, value2=hp))
        keyword = extract_keyword_after_give(tl)
        if keyword:
            effects.append(EffectSpec(EffectKind.GIVE, keyword=keyword))

    # draw (532) — "draw 2 cards" / "draw a card"
    if "draw" in tl:
        count = extract_number_after(tl, "draw")
        effects.append(EffectSpec(EffectKind.DRAW, value=max(count, 1)))

    # gain (513) — "gain 3 Armor" / "gain Spell Damage +1"
    if "gain" in tl:
        if "armor" in tl:
            amount = extract_number_before(tl, "armor")
            effects.append(EffectSpec(EffectKind.GAIN, value=amount, subtype="armor"))
        if "attack" in tl:
            amount = extract_number_before(tl, "attack")
            effects.append(EffectSpec(EffectKind.GAIN, value=amount, subtype="attack"))
        if "health" in tl:
            amount = extract_number_before(tl, "health")
            effects.append(EffectSpec(EffectKind.GAIN, value=amount, subtype="health"))

    # equip (36) — "equip a 2/2 Sword"
    if "equip" in tl:
        atk, hp = extract_stats_after(tl, "equip")
        effects.append(EffectSpec(EffectKind.WEAPON_EQUIP, value=atk, value2=hp))

    # discover (368)
    if "discover" in tl:
        effects.append(EffectSpec(EffectKind.DISCOVER))

    # Additional verbs...
    return effects
```

### 3.4 条件提取

```python
def parse_condition(text: str, card) -> Optional[ConditionSpec]:
    tl = text.lower()

    # "you're holding a Dragon" (86 cards)
    for phrase in ("you're holding a ", "you are holding a "):
        idx = tl.find(phrase)
        if idx >= 0:
            after = tl[idx + len(phase):].strip()
            race = extract_race_name(after)
            if race:
                return ConditionSpec(ConditionKind.HOLDING_RACE, {"race": race})

    # "this turn" (333 cards) — various forms
    if "this turn" in tl:
        return ConditionSpec(ConditionKind.THIS_TURN, {})

    # "for each" (264 cards)
    if "for each" in tl:
        entity_type = extract_entity_after(tl, "for each")
        return ConditionSpec(ConditionKind.FOR_EACH, {"entity": entity_type})

    # "if you've played a Fire spell" → played_this_turn
    if "if you've played" in tl or "if you have played" in tl:
        card_type = extract_card_type_from_condition(tl)
        return ConditionSpec(ConditionKind.PLAYED_THIS_TURN, {"card_type": card_type})

    # Cost patterns: "costs (1) less for each..."
    if "costs" in tl and "less" in tl:
        amount = extract_paren_number(tl, "costs")
        return ConditionSpec(ConditionKind.COST_COMPARISON, {"amount": amount})

    return None
```

***

## 四、实施计划（4 阶段）

### Phase 1: 数据模型 + 解析器（零正则，纯英文 token）

1. 创建 `analysis/search/abilities/` 目录
2. `definition.py` — CardAbility, AbilityTrigger, EffectKind, ConditionKind, TargetKind
3. `tokens.py` — mechanics 映射表 + 动词频率映射表 + 条件 token 映射表
4. `extractors.py` — 纯 string.find/split 提取器（extract\_number\_after, extract\_stats\_after, extract\_target\_kind, extract\_race\_name）
5. `parser.py` — AbilityParser.parse(card) → List\[CardAbility]
6. 修改 Card 增加 `abilities` 字段 + `__post_init__`
7. 修改 Minion.from\_card 传递 abilities
8. 测试：覆盖 top-20 动词对应卡牌

### Phase 2: 统一执行器

1. `executor.py` — AbilityExecutor.trigger(state, event)
2. 扩展 effects.py EffectKind
3. simulation.py → 用 AbilityExecutor 替代 if/elif
4. deathrattle.py → 委托
5. turn\_advance.py → 委托
6. location.py → 委托

### Phase 3: 被动效果 + 光环

1. PASSIVE\_COST → effective\_cost hook
2. AURA → AuraManager
3. 替代 aura\_engine.py / trigger\_registry.py 硬编码

### Phase 4: 清理

1. 删除中文正则
2. 删除旧函数
3. 更新测试

***

## 五、修改文件清单

### 新增

| 文件                        | 职责                                                    |
| ------------------------- | ----------------------------------------------------- |
| `abilities/__init__.py`   | 模块入口                                                  |
| `abilities/definition.py` | 数据模型（基于真实 mechanics/verbs/conditions）                 |
| `abilities/tokens.py`     | 映射表（mechanics→trigger, verbs→effect, conditions→kind） |
| `abilities/extractors.py` | 纯字符串提取器（零正则）                                          |
| `abilities/parser.py`     | 统一解析器                                                 |
| `abilities/executor.py`   | 统一执行器                                                 |
| `tests/test_abilities.py` | 测试                                                    |

### 修改

| 文件                               | 修改内容                             |
| -------------------------------- | -------------------------------- |
| `models/card.py`                 | abilities 字段 + __post\_init__    |
| `search/game_state.py`           | Minion.abilities + from\_card 传递 |
| `search/effects.py`              | 扩展 EffectKind                    |
| `search/rhea/simulation.py`      | AbilityExecutor 替代 if/elif       |
| `search/rhea/enumeration.py`     | abilities 驱动枚举                   |
| `search/deathrattle.py`          | 委托                               |
| `search/mcts/turn_advance.py`    | 委托                               |
| `search/location.py`             | 委托                               |
| `search/battlecry_dispatcher.py` | 简化                               |

***

## 六、预期收益

| 指标          | 重构前            | 重构后                              |
| ----------- | -------------- | -------------------------------- |
| 新增卡需改文件数    | 3-5            | 0（大多数自动）                         |
| 效果解析方式      | 中文正则 12 处      | 英文 token + mechanics 标签          |
| Minion 场上能力 | 只有基础属性         | 携带完整 abilities                   |
| 效果执行入口      | 5+ 个 if/elif 链 | 1 个 AbilityExecutor              |
| 可维护性        | 每次加新效果改多处      | 加 token 映射即可                     |
| 数据驱动程度      | 0%             | mechanics 标签 100% + text 动词 90%+ |


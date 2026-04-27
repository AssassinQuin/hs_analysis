> **本文件功能**: 记录卡牌模拟功能 json+tag 模式重构的项目架构分析、相关文件清单和开发约束。

# 卡牌模拟 json+tag 模式重构 — 项目架构分析

## 需求概述

重构卡牌模拟功能，使用 json+tag 模式统一卡牌加载和模拟执行链路：
1. 创建 `card_abilities.json` 能力定义文件
2. 统一三套标签系统（mechanics[]/KeywordSet/has_X）
3. 修复 CardDB 全量加载字段丢失
4. Token 卡牌从 JSON 加载而非硬编码

## 项目规范摘要

- 类型: 炉石传说 AI 决策分析系统（Python 3.10+）
- 技术栈: Python + hslog + hearthstone + NumPy/SciPy + pytest
- 命名: 文件 snake_case, 类 PascalCase, 函数/变量 snake_case
- 通用规范: 文档开头标注功能说明; 函数需中文 docstring; 测试30s超时; >500行文件分批生成

## 相关文件清单

### 核心文件（必改）

| 文件 | 行数 | 关键类/函数 | 职责 |
|------|------|------------|------|
| `analysis/data/card_data.py` | 1375 | `CardDB`, `_merge_locale()`, `_load_hsjson()` | 统一卡牌数据库，JSON加载+索引 |
| `analysis/data/token_cards.py` | 85 | `get_token()`, `get_random_naga()` | Token卡牌（硬编码，需改为JSON驱动） |
| `analysis/models/card.py` | 192 | `Card`, `from_hsdb_dict()` | 卡牌OO模型，含abilities字段 |
| `analysis/abilities/definition.py` | 520 | `AbilityTrigger`, `EffectKind`, `CardAbility`, `Action` | 能力系统类型定义 |
| `analysis/abilities/keywords.py` | 315 | `KeywordSet`, `CANONICAL_KEYWORDS`, `from_mechanics()` | 关键字系统 |
| `analysis/abilities/loader.py` | 273 | `load_abilities()`, `load_all_abilities()` | JSON能力加载器（目标文件不存在） |
| `analysis/engine/state.py` | 575 | `GameState`, `Minion`, `HeroState` | 游戏状态容器，Minion含30+has_X字段 |
| `analysis/engine/simulation.py` | 1252 | `apply_action()`, `_play_card()`, `_play_spell()` | 统一状态转换引擎 |
| `analysis/engine/dispatch.py` | 502 | `dispatch_batch()`, `EFFECT_HANDLERS` | 效果分发表（35种EffectKind） |
| `analysis/engine/executor.py` | 829 | `_apply_keyword()`, `damage()`, `summon_minion()` | 原语执行器 |
| `analysis/engine/mechanics/_data.py` | 574 | `HERALD_SOLDIERS`, `COLOSSUS_APPENDAGES` | 机制数据表 |

### 机制模块（可能需要适配）

| 文件 | 职责 |
|------|------|
| `analysis/engine/mechanics/discover.py` | Discover框架 |
| `analysis/engine/mechanics/deathrattle.py` | 亡语执行 |
| `analysis/engine/mechanics/choose_one.py` | 抉择机制 |
| `analysis/engine/mechanics/dormant.py` | 休眠机制 |
| `analysis/engine/mechanics/secret.py` | 奥秘机制 |
| `analysis/engine/mechanics/location.py` | 地点机制 |
| `analysis/engine/mechanics/quest.py` | 任务机制 |
| `analysis/engine/mechanics/shatter.py` | 裂变机制 |

### 搜索引擎（消费者，需验证兼容性）

| 文件 | 职责 |
|------|------|
| `analysis/search/mcts/engine.py` | MCTS/UCT搜索引擎 |
| `analysis/search/engine/mechanics/hero_card_handler.py` | 英雄牌处理 |
| `analysis/search/engine/mechanics/spell_target_resolver.py` | 法术目标解析 |

### 数据文件

| 文件 | 说明 |
|------|------|
| `card_data/240397/enUS/cards.json` | 全量卡牌（含token/enchantment） |
| `card_data/240397/enUS/cards.collectible.json` | 可收集卡牌 |
| `card_data/240397/zhCN/cards.json` | 全量卡牌（中文） |
| `card_data/240397/zhCN/cards.collectible.json` | 可收集卡牌（中文） |
| `analysis/data/card_abilities.json` | **不存在** — 需创建 |

## 现状问题

### 1. card_abilities.json 缺失
- `abilities/loader.py:load_abilities()` 期望从 `analysis/data/card_abilities.json` 读取
- 文件不存在 → 所有卡牌 `abilities=[]`
- 模拟回退到 `engine/mechanics/` 硬编码模块

### 2. 三套标签系统并存
| 系统 | 位置 | 格式 | 用途 |
|------|------|------|------|
| mechanics列表 | CardDB dict → Card | `["TAUNT","RUSH"]` 大写 | 索引/搜索 |
| KeywordSet | abilities/keywords.py | `frozenset({"taunt","rush"})` 小写 | 搜索树共享 |
| has_X布尔 | Minion dataclass | `has_taunt=True` | 模拟运行时 |

转换链: `mechanics[] → KeywordSet.from_mechanics() → Minion.from_card() → has_X`

### 3. CardDB 全量加载字段丢失
`_load_hsjson()` 非收集卡分支（L397-416）仅提取基础字段，缺少:
- `referencedTags`
- `spellDamage`
- `overload`
- `spellSchool`

### 4. Token 卡牌硬编码
`token_cards.py` 仅含 1 个示例 token + 1 个娜迦池，无法覆盖实际游戏需求。

## 当前数据流

```
HearthstoneJSON → _load_hsjson() → _merge_locale() → CardDB dict
                                                        ↓
                                              Card.from_hsdb_dict()
                                                        ↓
                                              Minion.from_card() → mechanics→has_X
                                                        ↓
                                              simulation.apply_action() → 硬编码分支
```

## 期望数据流（重构后）

```
HearthstoneJSON → _merge_locale() → CardDB dict（完整字段）
                        ↓                    ↓
              abilities/loader.py    Card.from_hsdb_dict()
              (card_abilities.json)          ↓
                        ↓           Minion（统一标签系统）
              CardAbility[]                  ↓
                        ↓           simulation（数据驱动）
              dispatch.py → executor.py
```

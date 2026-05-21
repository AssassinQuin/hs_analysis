# 炉石传说 AI 决策分析系统

> 实时解析 Power.log → 追踪游戏状态 → 对手手牌推断 → 叠加 UI 手牌预测

## 项目简介

本项目是一套完整的**炉石传说 AI 决策分析系统**，覆盖从日志解析、状态追踪、卡牌评分到实时决策建议的全链路。核心能力包括：

- **对手手牌推断**：逆 MCTS + 贝叶斯粒子滤波，推断对手最可能的手牌组合
- **叠加追踪**：半透明 PyQt5 叠加 UI，实时显示对手手牌预测、卡组推断、墓地追踪
- **离线回放**：加载历史日志，逐回合回放并分析
- **多层评分**：从白板曲线到 HSReplay 校准的卡牌评分引擎
- **对手建模**：贝叶斯卡组推断 + 奥秘概率模型 + 跨回合状态追踪

---

## 系统架构总览

本项目有两条独立的执行管线，共享核心分析模块：

### 管线 A：GUI 叠加追踪器（活跃）

```
Power.log
    │
    ▼
LogMonitor (QThread)
    ├── GameTracker (hslog 增量解析)
    ├── GlobalTracker (跨回合状态追踪)
    │       ├── BayesianOpponentModel (HSReplay 卡组推断)
    │       ├── SecretProbabilityModel (奥秘概率)
    │       └── TrackerRuleDispatcher (规则引擎)
    │
    ├── PowerLogGameStateBuilder → GameState
    │       └── EntityCache + GlobalGameState → 完整游戏状态
    │
    ├── HandPredictor → OpponentHandMCTS
    │       ├── HandSampler (候选手牌采样)
    │       ├── OpponentTurnSimulator (对手回合模拟)
    │       ├── BehaviorMatcher (行为匹配度)
    │       └── 粒子权重更新
    │
    └── OverlayWindow (PyQt5 叠加 UI)
            手牌预测 │ 卡组切换(A/B/C) │ 墓地追踪
```

### 管线 B：CLI 决策循环（搜索层已移除，当前不可用）

```
Power.log → LogWatcher → DecisionLoop
    ├── GameTracker → StateBridge → GameState
    └── [已删除] GameEngine → RHEA 搜索
```

> **状态说明**：`analysis/search/` 目录（含 RHEA 搜索引擎）已在 v1 清理中删除。
> `decision_loop.py` 中有 fallback stub 会抛出 `RuntimeError("v1 search engine removed")`。
> MCTS 搜索引擎（`mcts_uct.py`、`mcts_world_tracker.py`）仍存在于 `analysis/engine/`，但未接入主管线。

---

## 详细功能架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户入口                                     │
│  tracker/app.py (GUI)  │  scripts/run_live.py (CLI)                │
│  scripts/replay_game.py│  scripts/run_world_tracker.py             │
└──────┬─────────────────┴──────────┬────────────────────────────────┘
       │                            │
       ▼                            ▼
┌──────────────────────────┐  ┌──────────────────────────────────┐
│ tracker/                 │  │ analysis/watcher/                 │
│                          │  │                                   │
│ LogMonitor  (QThread)    │  │ LogWatcher  (50ms 文件轮询)       │
│ OverlayWindow (PyQt5)    │  │ DecisionLoop (CLI 主循环)         │
│ HandPredictor            │  │ PacketReplayer (离线回放)          │
│ GameStateManager         │  │ GameLogParser (批量解析)           │
│ CardImageManager         │  │ DeckHotReloader (热重载)           │
│ HSReplayUpdater          │  │ DeckProvider (卡组匹配)            │
└──────┬───────────────────┘  └──────────┬────────────────────────┘
       │                                 │
       ▼                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│                    核心解析 & 追踪层                               │
│                                                                   │
│  GameTracker (game_tracker.py)                                    │
│    hslog.LogParser 封装 + EntityCache                             │
│    事件检测: game_start / game_end / turn_start                   │
│                                                                   │
│  GlobalTracker (global_tracker.py) [1550行]                       │
│    跨回合状态: 手牌计数/牌库/奥秘/武器/残骸/疲劳                   │
│    卡牌来源分类: DECK vs GENERATED                                │
│    BayesianOpponentModel 集成                                      │
│    SecretProbabilityModel 集成                                     │
│    TrackerRuleDispatcher 规则分发                                  │
│                                                                   │
│  StateBridge (state_bridge.py)                                    │
│    hslog 实体树 → GameState 转换 (CLI 管线)                       │
│                                                                   │
│  PowerLogGameStateBuilder (powerlog_game_state_builder.py)        │
│    EntityCache + GlobalTracker → GameState (GUI 管线)             │
└──────────────────────────────┬───────────────────────────────────┘
                               │
       ┌───────────────────────┼───────────────────────┐
       ▼                       ▼                       ▼
┌──────────────┐  ┌──────────────────────┐  ┌─────────────────────┐
│ 对手推断引擎  │  │   卡牌效果引擎 (v2)    │  │    评估器            │
│               │  │                       │  │                     │
│ OpponentHand  │  │ analysis/card/engine/ │  │ analysis/evaluators/│
│ MCTS (1620行) │  │                       │  │                     │
│               │  │ state.py   GameState  │  │ composite.py 融合   │
│ HandSampler   │  │ rules.py   合法动作   │  │ bsv.py  节奏+生存   │
│  候选手牌采样  │  │ simulation.py 模拟    │  │ siv.py  子模型集成   │
│               │  │ executor.py  执行器   │  │ submodel.py 子模型  │
│ OpponentTurn  │  │ tags.py    标签系统   │  │ card_impact.py      │
│ Simulator     │  │ target.py  目标选择   │  │ eval_logger.py      │
│  对手回合模拟  │  │ trigger.py 触发器     │  │                     │
│               │  │ aura.py    光环       │  │                     │
│ Behavior      │  │ enchant.py 附魔       │  │                     │
│ Matcher       │  │ deterministic.py      │  │                     │
│  行为匹配度    │  │ mechanics/            │  │                     │
│               │  │  discover/deathrattle  │  │                     │
│ MCTSUCT       │  │  secret/dormant/quest  │  │                     │
│  (独立UCT)    │  │  location/hero_card    │  │                     │
│               │  │  choose_one/shatter    │  │                     │
│ MCTSWorld     │  │  targeting             │  │                     │
│ Tracker       │  │                       │  │                     │
│  (POMDP粒子)  │  │ analysis/card/abilities│  │                     │
│               │  │  definition/model      │  │                     │
│ World/Branch  │  │  loader/executor       │  │                     │
│ ParticleFilter│  │  generator_v2/spells   │  │                     │
│ Observation   │  │  keywords/value_expr   │  │                     │
│ Matcher       │  │  power/registry        │  │                     │
└──────────────┘  └──────────────────────┘  └─────────────────────┘
       │                       │                       │
       └───────────────────────┼───────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                      数据层                                       │
│                                                                   │
│  HSCardDB (card_data.py) — 双语言卡牌数据库                       │
│  CardEffectInference (card_effect_inference.py) — 效果推断        │
│  DynamicProbability (dynamic_probability.py) — 概率引擎           │
│  FetchHSReplay (fetch_hsreplay.py) — HSReplay 数据获取+SQLite    │
│  BayesianOpponentModel (bayesian_opponent.py) — 贝叶斯卡组推断    │
│  DeckClassifier (deck_classifier.py) — 卡组分类(快攻/中速/控制)   │
│                                                                   │
│  models/ — Card, GameRecord 数据模型                              │
│  scorers/ — L1→L7 多层卡牌评分引擎                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 当前目录结构

```
analysis/
├── config.py                          # 全局配置
├── card/                              # 卡牌系统 (v2 效果引擎)
│   ├── abilities/                     #   技能定义、加载器、生成器
│   ├── condition/                     #   条件系统
│   ├── constants/                     #   枚举常量
│   ├── data/                          #   HSCardDB 卡牌数据库
│   ├── engine/                        #   游戏状态引擎 (核心)
│   │   ├── state.py                   #     GameState/HeroState/Minion
│   │   ├── rules.py                   #     合法动作枚举
│   │   ├── simulation.py              #     动作模拟 apply_action()
│   │   ├── mechanics/                 #     机制: 发现/亡语/奥秘/任务等
│   │   └── aura/enchantment/trigger/  #     持续效果系统
│   ├── models/card.py                 #   Card 数据模型
│   ├── spells/                        #   法术效果组合
│   ├── target/                        #   目标选择系统
│   ├── trigger/                       #   触发器系统
│   └── value/                         #   价值评估提供者
│
├── engine/                            # MCTS & 对手推断
│   ├── powerlog_game_state_builder.py #   Power.log → GameState 构建器
│   ├── opponent_hand_mcts.py          #   逆MCTS对手手牌推断 [1620行]
│   ├── mcts_uct.py                    #   纯UCT搜索引擎 (独立，未接入主管线)
│   ├── mcts_world_tracker.py          #   POMDP粒子滤波 (独立，未接入主管线)
│   ├── card_effect_inference.py       #   卡牌效果推断引擎
│   ├── dynamic_probability.py         #   动态概率引擎
│   ├── world_model.py                 #   世界模型 (贝叶斯似然)
│   ├── world_branch.py                #   世界分支数据结构
│   ├── particle_filter.py             #   粒子滤波器
│   ├── observation_matcher.py         #   观测匹配器
│   └── world_tracker_output.py        #   世界追踪输出
│
├── evaluators/                        # 搜索树叶子节点评估
│   ├── composite.py                   #   复合评估器 (BSV融合→submodel fallback)
│   ├── bsv.py                         #   Board+Survival+Value 评估
│   ├── siv.py                         #   子模型集成评估
│   ├── submodel.py                    #   子模型: 场面/威胁/持续效果/触发器
│   ├── card_impact.py                 #   单卡影响度评估
│   ├── archetype_profile.py           #   原型感知评估
│   └── eval_logger.py                 #   评估日志
│
├── scorers/                           # 离线卡牌评分 (非搜索时使用)
│   ├── scoring_engine.py              #   L1→L7 评分管线
│   ├── vanilla_curve.py               #   L1 白板曲线
│   ├── keyword_interactions.py        #   L2 关键词交互
│   ├── mechanic_base_values.py        #   机制基础分值
│   └── constants.py                   #   评分常量
│
├── watcher/                           # 日志解析 & 状态追踪
│   ├── log_watcher.py                 #   文件轮询 (50ms)
│   ├── game_tracker.py                #   hslog 增量解析 [460行]
│   ├── global_tracker.py              #   跨回合状态追踪 [1550行]
│   ├── state_bridge.py                #   hslog→GameState (CLI管线)
│   ├── decision_loop.py               #   CLI 决策主循环 (搜索层缺失)
│   ├── packet_replayer.py             #   离线回放引擎
│   ├── game_log_parser.py             #   批量日志解析
│   ├── deck_provider.py               #   卡组匹配 (时间戳→卡组代码)
│   ├── deck_hot_reloader.py           #   卡组热重载
│   ├── secret_probability.py          #   奥秘概率模型
│   ├── tracker_rules.py               #   追踪规则分发
│   └── tracker_types.py               #   数据类型定义
│
├── data/                              # 数据获取 & 缓存
│   ├── fetch_hsreplay.py              #   HSReplay 数据获取
│   ├── card_effects.py                #   卡牌效果数据管线
│   └── card_roles.py                  #   卡牌角色数据
│
├── models/                            # 数据模型
│   └── game_record.py                 #   游戏记录
│
├── training/                          # [死代码] ML 训练管线，无生产消费者
│   ├── extractor.py / encoder.py
│   ├── pipeline.py / ability_tags.py
│
├── utils/                             # 工具模块
│   ├── bayesian_opponent.py           #   贝叶斯对手建模
│   ├── deck_classifier.py             #   卡组分类
│   ├── deck_pool_tracker.py           #   手牌采样池
│   ├── hero_class.py                  #   英雄职业映射
│   ├── player_name.py                 #   玩家名解析
│   ├── http.py                        #   HTTP 工具
│   └── spell_simulator.py             #   [死代码] v1 迁移 stub

tracker/                               # 叠加追踪器 (PyQt5)
├── app.py                             #   主入口
├── overlay_ui.py                      #   叠加 UI (Firestone 风格)
├── hand_predictor.py                  #   手牌预测引擎
├── log_monitor.py                     #   Power.log QThread 监控
├── game_state.py                      #   游戏状态管理
├── card_images.py                     #   卡牌图像管理
├── hsreplay_updater.py                #   HSReplay 后台更新
├── diagnostic_app.py                  #   诊断工具
├── diagnostic_engine.py               #   诊断引擎
└── verify.py                          #   端到端验证

scripts/                               # 入口脚本
├── run_live.py                        #   CLI 实时决策 (搜索层缺失)
├── run_live_cfg.py                    #   CLI 实时决策 (cfg 版)
├── run_world_tracker.py               #   世界追踪器
├── replay_game.py                     #   离线回放
├── parse_game_log.py                  #   日志解析
├── run_scoring.py                     #   评分生成
├── run_fetch.py                       #   数据获取
├── update_deck_codes.py               #   卡组代码更新
├── pool_quality_generator.py          #   发现池质量报告
├── rewind_delta_generator.py          #   抽牌预测报告
├── expand_deck_codes.py               #   [实验性] 卡组代码展开
├── deep_powerlog_analysis.py          #   [一次性] Power.log 深度分析
├── verify_tracker_pipeline.py         #   [一次性] 追踪器验证
└── (不再有损坏脚本 — run_mcts.py、full_flow_sim.py 已删除；test_*.py 已迁移至 tests/)
```

---

## 重复/相似实现分析

### 有实际重叠的

| 问题 | 文件 | 说明 | 状态 |
|------|------|------|------|
| **GameState 构建双路径** | `state_bridge.py` vs `powerlog_game_state_builder.py` | 两者都从 hslog 实体构建 GameState。StateBridge 用于 CLI 管线，PowerLogGameStateBuilder 用于 GUI 管线。后者更完整（集成 GlobalTracker），前者较简化。 | 待处理 |
| **GameState 内联构建** | `opponent_hand_mcts.py` L460-517 | 当 PowerLogGameStateBuilder 不可用时的 fallback，手动构建 GameState，与 state_bridge 重复。 | 待处理 |
| ~~对手评分逻辑重复~~ | ~~`mcts_uct.py` vs `opponent_hand_mcts.py`~~ | ~~已提取到 `analysis/engine/opponent_scoring.py`（Strategy Pattern）~~ | ✅ 已解决 |
| ~~测试在 scripts/~~ | ~~`scripts/test_*.py` (6个)~~ | ~~已迁移至 `tests/`~~ | ✅ 已解决 |
| ~~配置加载重复~~ | ~~`tracker/app.py:_load_config()`~~ | ~~实际委托给 `analysis/config.py:load_live_config()`~~ | ✅ 已对齐 |
| ~~_SafeEntityTreeExporter~~ | ~~`game_tracker.py` + `game_log_parser.py`~~ | ~~已提取为 `SafeEntityTreeExporter`（game_tracker.py 导出，game_log_parser.py 导入）~~ | ✅ 已解决 |

### 非重复（不同职责）

| 模块对 | 说明 |
|--------|------|
| `scorers/` vs `evaluators/` | scorers = 离线卡牌质量评分（构建卡组时用）；evaluators = 运行时局面评估（搜索树叶子节点用） |
| `game_tracker.py` vs `global_tracker.py` | game_tracker = hslog 协议层解析；global_tracker = 语义层跨回合追踪 |
| `deck_provider.py` vs `deck_classifier.py` vs `deck_pool_tracker.py` | 分别负责：卡组来源匹配 / 卡组风格分类 / 手牌采样池管理 |

---

## 已清理的死代码

以下死代码已在 2026-05-21 重构中清理：

| 清理项 | 操作 |
|--------|------|
| `scripts/run_mcts.py`, `scripts/full_flow_sim.py` | 删除（导入已删除模块） |
| `analysis/training/` (5 文件) | 删除（无生产消费者） |
| `tests/training/` (2 文件) | 删除（死代码关联） |
| `analysis/utils/spell_simulator.py` | 删除（迁移 stub） |
| `tests/search/` 下 25 个带 `pytest.skip` 的文件 + 2 个 conftest | 删除 |
| `tests/test_live_games.py`, `tests/test_engine_singleton.py`, `tests/test_card_index.py` | 删除 |
| `tests/search/` 下 21 个仍活动的测试 | 已迁移至 `tests/engine/` |
| `scripts/test_*.py` (6 个) | 已迁移至 `tests/` |
| `_SafeEntityTreeExporter` 重复定义 | 合并为 `SafeEntityTreeExporter`（Strategy Pattern） |
| 对手评分逻辑 (`_score_opponent_action` + `_select_best_action`) | 提取为 `analysis/engine/opponent_scoring.py` |

---

## 评分体系

| 层级 | 名称 | 说明 |
|------|------|------|
| L1 | 白板曲线 | 幂律拟合基准：期望属性 = f(费用) |
| L2 | 关键词评分 | 50+ 关键词分层评分 |
| L2.5 | 种族协同 | 随从种族 + 法术学派协同加分 |
| L3 | 文本效果 | 正则提取数值效果 |
| L5 | 条件期望 | 触发条件概率 × 效果值 |
| L7 | HSReplay 校准 | 真实胜率排名校准 |

---

## 快速开始

```bash
# 安装依赖
pip install -e .
pip install -e ".[dev]"     # 含 pytest
pip install PyQt5           # 叠加 UI (可选)

# 获取卡牌数据（首次运行）
python scripts/run_fetch.py

# 叠加追踪器（推荐）
python tracker/app.py

# CLI 实时决策 (搜索层缺失，当前不可用)
python scripts/run_live.py

# 离线回放
python scripts/replay_game.py --analyze /path/to/Power.log

# 运行测试
pytest
pytest -m "not slow"       # 跳过慢测试
```

---

## 配置

编辑 `cfg/live.cfg`：

```ini
[log]
paths =
    E:\battle\Hearthstone\Logs          # Windows
    ~/Library/Logs/Hearthstone          # macOS

[engine]
time_budget_ms = 8000    # MCTS 时间预算
num_worlds = 7           # 粒子数量
uct_constant = 0.5       # 探索常数
```

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 日志解析 | [hslog](https://github.com/HearthSim/hslog) |
| 卡牌数据库 | [python-hearthstone](https://github.com/HearthSim/python-hearthstone) |
| 数据源 | HearthstoneJSON API + HSReplay |
| 科学计算 | NumPy, SciPy |
| UI | PyQt5 (叠加窗口) |
| 测试 | pytest |

---

## 许可

本项目仅供学习研究，卡牌数据版权归 Blizzard Entertainment 所有。

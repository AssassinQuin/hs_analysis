# 炉石传说 AI 决策分析系统

> 实时解析 Power.log → 追踪游戏状态 → AI 搜索最优出牌序列 → 叠加 UI 对手手牌预测

## 项目简介

本项目是一套完整的**炉石传说 AI 决策分析系统**，覆盖从日志解析、状态追踪、卡牌评分到实时决策建议的全链路。核心能力包括：

- **实时决策**：监控 Power.log 变化，在每个回合开始时自动运行 RHEA 搜索引擎给出最优出牌建议
- **离线回放**：加载历史日志，逐回合回放并分析决策质量
- **多版本评分**：从白板曲线到 V8 上下文感知的多层评分引擎
- **对手建模**：贝叶斯卡组推断 + 奥秘概率模型 + 对手手牌追踪
- **叠加追踪**：半透明叠加 UI，实时显示对手手牌预测、多卡组切换、墓地追踪（参考 Firestone 风格）

---

## 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          用户入口 (scripts/)                                │
│  run_live.py  │  replay_game.py  │  parse_game_log.py  │  run_scoring.py  │
└──────┬────────┴────────┬──────────────┬──────────────────┴────────┬────────┘
       │                 │              │                           │
       ▼                 ▼              ▼                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     watcher/ — 日志解析 & 状态追踪层                      │
│                                                                          │
│  ┌────────────┐   ┌──────────────┐   ┌───────────────┐                  │
│  │ LogWatcher  │──▶│ GameTracker  │──▶│ GlobalTracker │                  │
│  │ (文件轮询)  │   │ (hslog增量)  │   │ (跨回合状态)  │                  │
│  └────────────┘   └──────┬───────┘   └───────┬───────┘                  │
│                          │                    │                          │
│  ┌──────────────┐   ┌────▼─────────┐   ┌─────▼──────────┐              │
│  │game_log_parser│   │StateBridge   │   │BayesianOppModel│              │
│  │(批量解析)     │   │(hslog→GS)   │   │(卡组推断)      │              │
│  └──────────────┘   └────┬─────────┘   └────────────────┘              │
│                          │                                               │
│  ┌──────────────┐   ┌──────────────┐                               │
│  │packet_replayer│  │decision_loop  │                              │
│  │(hslog回放)    │  │(实时决策主循环)│                              │
│  └──────────────┘   └──────────────┘                              │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    search/ — AI 搜索 & 模拟引擎层                         │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────┐             │
│  │  rhea/ — 滚动水平线进化算法 (核心搜索引擎)                    │             │
│  │  engine.py  simulation.py  actions.py  enumeration.py   │             │
│  └────────────────────────┬────────────────────────────────┘             │
│                           │                                              │
│  ┌────────────────────────▼────────────────────────────────┐             │
│  │  engine/ — 多因子评估管线                                    │             │
│  │  pipeline.py → strategic.py → action_pruner.py →         │             │
│  │  attack_planner.py → unified_tactical.py →               │             │
│  │  factors/ (board_control, tempo, lethal, survival, ...)  │             │
│  └──────────────────────────────────────────────────────────┘             │
│                                                                          │
│  ┌─────────────────── 机制模拟器 ───────────────────────────┐             │
│  │  discover  battlecry  deathrattle  enchantment  aura     │             │
│  │  secret   kindred   herald   imbue   corpse   quest     │             │
│  │  dormant  location  colossal  corrupt  outcast  rune    │             │
│  └──────────────────────────────────────────────────────────┘             │
│                                                                          │
│  ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌───────────────┐         │
│  │game_state│ │opponent_sim  │ │risk_assessor│ │zone_manager   │         │
│  │(游戏状态)│ │(对手模拟)     │ │(风险评估)   │ │(区域管理)     │         │
│  └──────────┘ └──────────────┘ └────────────┘ └───────────────┘         │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│              scorers/ — 多版本卡牌评分引擎                                │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────┐            │
│  │  L1 白板曲线 → L2 关键词评分 → L2.5 种族/学派协同          │            │
│  │  → L3 文本效果解析 → L5 条件期望 → L7 HSReplay 校准        │            │
│  └──────────────────────────────────────────────────────────┘            │
│  scoring_engine.py  v8_contextual.py  vanilla_curve.py                   │
│  keyword_interactions.py  mechanic_base_values.py  constants.py          │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│             evaluators/ — 状态评估器（搜索树叶子节点评估）                  │
│  composite.py (复合)  bsv.py (板面+生存+价值)  siv.py (子模型集成)         │
│  submodel.py (子模型: board/threat/lingering/trigger)                     │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│               data/ — 卡牌数据库 & 数据管线                               │
│                                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐               │
│  │ hsdb.py      │  │card_effects.py│  │card_cleaner.py   │               │
│  │ (HSCardDB)   │  │(效果解析)     │  │(数据清洗)         │               │
│  └──────┬───────┘  └──────────────┘  └──────────────────┘               │
│         │                                                                │
│  ┌──────▼───────┐  ┌──────────────┐  ┌──────────────────┐               │
│  │card_index.py │  │fetch_hsreplay│  │build_unified_db  │               │
│  │(O(1)索引查询) │  │(HSReplay API)│  │(统一数据库构建)   │               │
│  └──────────────┘  └──────────────┘  └──────────────────┘               │
└────────────────────────────────────┬─────────────────────────────────────┘
                                     │
                                     ▼
┌──────────────────────────────────────────────────────────────────────────┐
│              models/ — 核心数据模型    │    utils/ — 工具模块              │
│  card.py (卡牌)                       │  score_provider.py (评分注入)     │
│  game_record.py (游戏记录)            │  bayesian_opponent.py (贝叶斯)    │
│  phase.py (阶段枚举)                  │  hero_class.py (英雄职业映射)     │
│                                       │  player_name.py (玩家名解析)      │
│                                       │  spell_simulator.py (法术模拟)    │
└───────────────────────────────────────┴──────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────┐
│                    config.py — 全局配置                                   │
│  数据目录: card_data/240397/  │  RHEA参数  │  Phase参数  │  API密钥       │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 目录结构详解

```
analysis/
├── config.py                     # 全局配置（数据路径、RHEA参数、API密钥）
├── constants/
│   └── hs_enums.py               # 炉石枚举常量（区域、卡牌类型、关键词映射）
│
├── data/                         # ── 数据层 ──
│   ├── hsdb.py                   # HSCardDB 卡牌数据库（双语言，HSJSON+XML回退）
│   ├── card_effects.py           # 卡牌效果结构化解析（伤害、治疗、抽牌、发现等）
│   ├── card_cleaner.py           # 数据清洗管线（文本规范化、mechanics提取）
│   ├── card_index.py             # 卡牌索引（多维O(1)查询：职业/费用/种族/学派）
│   ├── fetch_hsreplay.py         # HSReplay 数据获取与缓存（SQLite）
│   ├── build_unified_db.py       # 统一标准模式数据库构建
│   └── build_wild_db.py          # 狂野模式数据库（去重）
│
├── models/                       # ── 数据模型 ──
│   ├── card.py                   # Card 统一数据模型（工厂：hsdb/cardxml/hsjson）
│   ├── game_record.py            # 游戏记录模型（PlayerInfo/DeckInfo/CardSighting）
│   └── phase.py                  # Phase 枚举（EARLY 1-4 / MID 5-7 / LATE 8+）
│
├── scorers/                      # ── 卡牌评分引擎 ──
│   ├── scoring_engine.py         # 多层评分入口（L1→L7 全链路）
│   ├── v8_contextual.py          # V8 上下文感知评分器
│   ├── vanilla_curve.py          # L1 白板曲线基准（幂律拟合）
│   ├── keyword_interactions.py   # 关键词交互评分
│   ├── mechanic_base_values.py   # 机制基础分值表
│   └── constants.py              # 评分常量（关键词层级、效果模式、条件定义）
│
├── evaluators/                   # ── 状态评估器 ──
│   ├── composite.py              # 复合评估器（多维度融合）
│   ├── bsv.py                    # BSV: Board + Survival + Value
│   ├── siv.py                    # SIV: 子模型集成评估
│   └── submodel.py               # 子模型（场面/威胁/持续效果/触发器）
│
├── search/                       # ── AI 搜索引擎 ──
│   ├── game_state.py             # GameState 完整游戏状态（支持copy用于搜索树）
│   ├── zone_manager.py           # 区域管理器（手牌/场面/牌库/奥秘分区）
│   ├── mechanics_state.py        # 机制特定状态（延迟初始化）
│   ├── keywords.py               # KeywordSet 关键词集合（位集优化）
│   ├── entity.py                 # 实体基类
│   ├── opponent_simulator.py     # 对手模拟器（随机出牌策略）
│   ├── risk_assessor.py          # 风险评估器（致死风险、返场风险）
│   ├── lethal_checker.py         # 致命检测（精确计算斩杀线）
│   ├── secret_probability.py     # 奥秘概率模型
│   ├── secret_triggers.py        # 奥秘触发模拟
│   │
│   ├── rhea/                     # ── RHEA 核心 ──
│   │   ├── engine.py             # RHEA 主引擎（进化循环、时间预算）
│   │   ├── simulation.py         # 模拟器（apply_action + 所有机制分发）
│   │   ├── actions.py            # Action 数据类 + 动作生成
│   │   ├── enumeration.py        # 合法动作枚举
│   │   └── result.py             # SearchResult 结果封装
│   │
│   ├── engine/                   # ── 多因子决策管线 ──
│   │   ├── pipeline.py           # DecisionPipeline 主入口
│   │   ├── strategic.py          # 战略层（选择决策模式：节奏/控制/斩杀等）
│   │   ├── tactical.py           # 战术规划器
│   │   ├── unified_tactical.py   # 统一战术方案
│   │   ├── action_pruner.py      # 动作剪枝（减少搜索空间）
│   │   ├── attack_planner.py     # 攻击规划器
│   │   ├── factors/              # 评估因子
│   │   │   ├── factor_base.py    # 因子基类 EvalContext
│   │   │   ├── factor_graph.py   # FactorGraphEvaluator 因子图
│   │   │   ├── board_control.py  # 场面控制因子
│   │   │   ├── tempo.py          # 节奏因子
│   │   │   ├── lethal_threat.py  # 致命威胁因子
│   │   │   ├── survival.py       # 生存因子
│   │   │   ├── value.py          # 价值因子
│   │   │   ├── resource_efficiency.py  # 资源效率因子
│   │   │   └── discover_ev.py    # 发现期望值因子
│   │   ├── mechanics/            # 管线内机制处理
│   │   │   ├── hero_card_handler.py     # 英雄牌处理
│   │   │   └── spell_target_resolver.py # 法术目标解析
│   │   └── models/               # 概率模型
│   │       ├── discover_model.py # 发现池采样模型
│   │       ├── draw_model.py     # 抽牌模型
│   │       └── rng_model.py      # RNG 模型
│   │
│   ├── mechanics/                # ── 特殊机制实现 ──
│   │   ├── quest_mechanic.py     # 任务机制
│   │   ├── kindred_mechanic.py   # 延系（种族/学派连续打出）
│   │   ├── herald_mechanic.py    # 兆示机制
│   │   ├── imbue_mechanic.py     # 灌注机制
│   │   └── corpse_mechanic.py    # 残骸（DK资源）
│   │
│   └── [独立机制模块]
│       ├── discover.py           # 发现（三选一）
│       ├── battlecry_dispatcher.py # 战吼分发器
│       ├── deathrattle.py        # 亡语处理 + 复生
│       ├── enchantment.py        # 附魔系统
│       ├── aura_engine.py        # 光环引擎（持续效果重算）
│       ├── mechanic_dispatcher.py # 机制总分发器
│       ├── kindred.py            # 延系辅助
│       ├── quest.py              # 任务追踪
│       ├── herald.py             # 兆示计数
│       ├── imbue.py              # 灌注升级
│       ├── corpse.py             # 残骸获取
│       ├── dormant.py            # 休眠随从
│       ├── location.py           # 地点
│       ├── colossal.py           # 巨型（躯干+肢体）
│       ├── corrupt.py            # 堕落升级
│       ├── outcast.py            # 流放效果
│       ├── rune.py               # 符文约束（DK）
│       ├── dark_gift.py          # 暗影之赐
│       ├── choose_one.py         # 抉择
│       ├── rewind.py             # 回溯（抽牌预测）
│       ├── shatter.py            # 碎冰
│       ├── effects.py            # 效果注册表
│       └── trigger_system.py     # 触发器系统
│
├── watcher/                      # ── 日志解析 & 状态追踪 ──
│   ├── log_watcher.py            # 文件监视器（50ms轮询 + inode轮转检测）
│   ├── game_tracker.py           # hslog增量解析器（逐行feed_line）
│   ├── global_tracker.py         # 跨回合全局状态追踪（卡牌来源分类/种族统计）
│   ├── state_bridge.py           # hslog实体树 → GameState 转换桥
│   ├── decision_loop.py          # 实时决策主循环（Watcher→Tracker→RHEA）
│   ├── packet_replayer.py        # hslog回放引擎（逐包重放+RHEA分析）
│   └── game_log_parser.py        # 批量日志解析（离线分析多场游戏）
│
└── utils/                        # ── 工具模块 ──
    ├── score_provider.py         # 评分注入（将评分加载到手牌Card对象）
    ├── bayesian_opponent.py      # 贝叶斯对手建模（卡组匹配+概率推断）
    ├── hero_class.py             # 英雄职业映射（card_id/dbfId → 职业名）
    ├── player_name.py            # 玩家名解析（BattleTag识别/匿名检测）
    └── spell_simulator.py        # 法术效果模拟器

tracker/                          # ── 叠加追踪器 ──
├── app.py                        # 主应用入口（实时/离线模式）
├── overlay_ui.py                 # 叠加 UI（PyQt5，Firestone 风格三段式布局）
├── game_state.py                 # 完整游戏状态（Single Source of Truth）
├── hand_predictor.py             # 动态手牌预测引擎（超几何分布+贝叶斯）
├── log_monitor.py                # Power.log 实时监控器（轮询+QThread）
├── card_images.py                # 卡牌图像管理器（下载+缓存+QPixmap）
├── hsreplay_updater.py           # HSReplay 数据更新器（后台线程）
└── verify.py                     # 端到端验证脚本
```

---

## 核心数据流

### 1. 实时决策管线

```
Power.log 文件
     │
     ▼  (文件变化检测)
LogWatcher (50ms 轮询)
     │  yield line
     ▼
GameTracker.feed_line(line)
     │  hslog.LogParser.read_line()
     │  → 事件检测: game_start / game_end / turn_start
     ▼  (turn_start 触发)
StateBridge.convert(game)
     │  hslog 实体树 → GameState
     ▼
load_scores_into_hand(state)
     │  评分引擎 → 手牌卡牌.score
     ▼
RHEAEngine.search(state)
     │  进化搜索: 枚举动作 → 模拟 → 评估 → 选择
     ▼
DecisionPresenter.present(result)
        输出最优出牌序列
```

### 2. 离线回放管线

```
Power.log (完整文件)
     │
     └──▶ packet_replayer.py (hslog库解析)
             逐包回放 → GlobalTracker 追踪 → RHEA 分析
```

### 3. 卡牌评分管线

```
card_data/240397/
  ├── zhCN/cards.collectible.json ─┐
  └── enUS/cards.collectible.json ─┤
                                    ▼
                            HSCardDB (hsdb.py)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              L1 白板曲线    L2 关键词评分    L3 文本效果
                    │               │               │
                    └───────┬───────┘
                            ▼
                    L5 条件期望评分
                            │
                    L7 HSReplay 校准
                            ▼
                    统一评分 → score_provider 注入
```

---

## 运行入口

| 脚本 | 用途 |
|------|------|
| `scripts/run_live.py` | **实时模式**：监控 Power.log，每回合给出决策建议 |
| `scripts/replay_game.py` | **离线回放**：加载历史 Power.log，逐回合分析 |
| `scripts/parse_game_log.py` | **日志解析**：解析游戏日志目录，提取卡组信息和对手卡牌 |
| `scripts/run_scoring.py` | **评分生成**：批量生成卡牌评分报告 |
| `scripts/run_rhea.py` | **RHEA 测试**：运行搜索引擎基准测试 |
| `scripts/run_fetch.py` | **数据获取**：从 HSJSON/HSReplay 下载最新卡牌数据 |
| `scripts/pool_quality_generator.py` | **池质量报告**：生成发现池质量分析 |
| `scripts/rewind_delta_generator.py` | **回溯报告**：生成抽牌预测准确率报告 |
| `tracker/app.py` | **叠加追踪器**：对手手牌预测叠加 UI（实时/离线） |

---

## 评分体系

| 层级 | 名称 | 说明 |
|------|------|------|
| L1 | 白板曲线 | 幂律拟合基准：期望属性 = f(费用) |
| L2 | 关键词评分 | 50+ 关键词分层评分（圣盾/冲锋/发现/战吼等） |
| L2.5 | 种族协同 | 随从种族 + 法术学派协同加分 |
| L3 | 文本效果 | 正则提取数值效果（伤害/治疗/抽牌/召唤） |
| L5 | 条件期望 | 触发条件概率 × 效果值 |
| L7 | HSReplay 校准 | 真实胜率排名校准 |

---

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 日志解析 | [hslog](https://github.com/HearthSim/hslog) (hearthstone log parser) |
| 卡牌数据库 | [python-hearthstone](https://github.com/HearthSim/python-hearthstone) (deckstrings/enums) |
| 数据源 | HearthstoneJSON API (双语言卡牌数据) |
| 数据分析 | HSReplay (对战胜率/卡组原型) |
| 科学计算 | NumPy, SciPy (曲线拟合、概率计算) |
| 数据缓存 | SQLite (HSReplay缓存) |

---

## 快速开始

```bash
# 安装依赖
pip install -e .
pip install PyQt5   # 叠加 UI 需要

# 获取卡牌数据（首次运行）
python scripts/run_fetch.py

# 实时决策模式（监控 Power.log）
python scripts/run_live.py

# 离线回放
python scripts/replay_game.py --analyze /path/to/Power.log

# 解析游戏日志
python scripts/parse_game_log.py /path/to/Hearthstone_YYYY_MM_DD_HH_MM_SS/

# 运行测试
pytest
```

---

## 叠加追踪器（对手手牌预测 UI）

基于 PyQt5 的半透明叠加窗口，参考 Firestone(火石) 风格设计，
实时显示对手手牌预测、多卡组 A/B/C 切换、墓地追踪。

### 功能特性

- **三段式布局**：手牌区 → 卡组区(A/B/C切换) → 墓地区(卡组/衍生牌分区)
- **手牌预测**：超几何分布 + 贝叶斯修正，显示概率最高的手牌预测
- **多卡组切换**：A/B/C 标签切换不同卡组原型预测，显示概率和剩余卡牌
- **墓地追踪**：区分「卡组来源牌」和「衍生牌」，标签颜色不同
- **法力水晶**：菱形渐变蓝色水晶 + 稀有度颜色编码(白/蓝/紫/橙)
- **可折叠 section**：点击标题栏折叠/展开各区域
- **动态缩放**：拖拽右下角手柄调整窗口大小，行高自适应
- **鼠标穿透**：📌/👁 按钮切换交互/穿透模式，穿透时点击穿过到游戏
- **增量刷新**：哈希对比避免无效重绘，150ms 刷新间隔

### 日志路径查找优先级

1. 命令行 `--log` / `--offline` 参数
2. `cfg/live.cfg` 配置文件 `[log]` `paths`
3. 自动检测系统标准位置
4. 项目根目录下的 `Power.log` / `Hearthstone_*/` 子目录

### 配置文件

编辑 `cfg/live.cfg` 设置日志路径：

```ini
[log]
; 支持多个候选路径，按顺序取第一个可用项
; 可用分号、逗号或换行分隔
; 每一项可填:
;   1) Power.log 文件路径
;   2) 某局目录路径(目录内含 Power.log)
;   3) Logs 根目录路径(自动选最新一局的 Power.log)
;
; === 多平台路径配置 ===
; Windows (Battle.net 默认)
;   E:\battle\Hearthstone\Logs
;   C:\Program Files (x86)\Hearthstone\Logs
; macOS
;   ~/Library/Logs/Hearthstone
; Linux / Wine
;   ~/.wine/drive_c/Program Files/Hearthstone/Logs
;
paths =
    E:\battle\Hearthstone\Logs
```

### 使用方法

#### 实时模式（游戏进行中）

```bash
# 自动检测日志路径（推荐）
python -m tracker.app

# 指定日志路径
python -m tracker.app --log "E:\battle\Hearthstone\Logs\Power.log"

# 详细输出
python -m tracker.app -v
```

启动后会在屏幕右侧显示半透明叠加窗口，自动跟随游戏进程：
- 游戏开始时自动识别对手职业
- 每回合更新对手手牌预测和卡组推断
- 点击 section 标题折叠/展开
- 点击 A/B/C 标签切换不同卡组原型
- 右下角拖拽缩放窗口
- 📌/👁 按钮切换鼠标穿透模式

#### 离线模式（分析历史日志）

```bash
# 分析项目根目录下的 Power.log
python -m tracker.app --offline Power.log

# 分析指定目录的日志
python -m tracker.app --offline Hearthstone_2026_04_23_08_43_35/Power.log
```

离线模式会一次性加载完整日志，显示最终游戏状态的预测结果。

### UI 布局说明

```
┌────────────────────────────────┐
│ [职业图标] 萨满  T5  手3 库22 📌 x│  ← 标题栏（拖拽移动）
├────────────────────────────────┤
│ 对手手牌 (3)               ▼  │  ← 可折叠
│  ◇2  闪电风暴        60%    │  ← 法力水晶 + 卡名 + 概率
│  ◇3  法力之潮图腾     确认   │
│  ◇4  妖术           35%    │
├────────────────────────────────┤
│ 对手卡组                   ▼  │  ← 可折叠
│ [A:进化萨 60%] [B:图腾萨 30%] │  ← A/B/C 卡组切换
│  ◇1  火羽精灵       x2    │  ← 法力水晶 + 卡名 + 剩余
│  ◇2  闪电箭         x2    │
│  ◇3  法力之潮图腾    x1    │  │  ← 底部小条=手牌概率
│  ...                           │
├────────────────────────────────┤
│ 墓地 (卡组3 / 衍生2)      ▼  │  ← 可折叠
│  ◇1  火羽精灵  卡组       │  ← 「卡组」标签
│  ◇2  闪电箭    卡组       │
│  ◇3  小鬼   衍生          │  ← 「衍生」标签（橙色）
│  ◇5  随从    衍生         │
└────────────────────────────────┘
```

### 数据流

```
Power.log
  ↓ (文件轮询 100ms)
LogMonitor (QThread)
  ↓ feed_line → GameTracker → GlobalTracker
  ↓ build_state_dict() → raw dict
  ↓
HandPredictor.predict(state_dict)
  ↓ DynamicProbabilityEngine (超几何分布)
  ↓ CardEffectInferenceEngine (效果推断)
  ↓ → PredictionResult
  ↓
GameStateManager.update(state_dict, prediction_result)
  ↓ → CompleteGameState
  ↓
OverlayWindow._refresh() (150ms 定时器)
  ↓ 三段式渲染: 手牌/卡组/墓地
```

---

## 数据目录

```
card_data/240397/
├── zhCN/
│   ├── cards.collectible.json    # 中文可收集卡牌
│   └── cards.json                # 中文全卡牌（含衍生物）
├── enUS/
│   ├── cards.collectible.json    # 英文可收集卡牌
│   └── cards.json                # 英文全卡牌
├── meta/
│   └── hero_class_map.json       # 英雄 dbfId → 职业 映射缓存
├── unified_standard.json         # 统一标准模式数据库
├── unified_wild.json             # 统一狂野模式数据库
└── hsreplay_cache.db             # HSReplay 数据缓存
```

---

## 许可

本项目仅供学习研究，卡牌数据版权归 Blizzard Entertainment 所有。

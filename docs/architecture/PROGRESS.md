# 项目进展日志

> 炉石传说 AI 决策引擎 — 完整开发记录
> 最后更新：2026-04-22

---

## Phase 0: 项目初始化 (2026-04-17)

### Commit `1d29a87` — 项目初始化

| 项目 | 详情 |
|------|------|
| 日期 | 2026-04-17 09:26 |
| 内容 | 项目脚手架、初始脚本、传说卡分析数据 |

- [x] README.md 项目文档
- [x] 10 个 Python 脚本整理到 scripts/
- [x] HS 卡牌 JSON 数据

---

## Phase 0.5: 数据基础设施 (2026-04-17 ~ 04-18)

### 数据源确认

| 数据源 | 状态 | 说明 |
|--------|------|------|
| HearthstoneJSON | ✅ 主数据源 | 完整标准卡牌数据 |
| iyingdi API | ⚠️ 不完整 | 缺 49 张卡，仅作辅助 |
| HSReplay | ✅ 校准源 | 卡牌使用率/胜率排名缓存 |

### 产出

- 984→1015 张标准卡入库（unified_standard.json）
- 6174 张全卡（iyingdi_all_raw.json）→ 5209 张狂野去重
- CardIndex O(1) 多维度索引
- Card cleaner：56 个关键词正则，中英文兼容
- 71 类文本分类器，100% 卡牌覆盖

---

## Phase 1: V2 评分模型 (2026-04-18)

### Commit `96b2ebf` ~ T001-T005 完成

**V2 幂律曲线拟合**: `expected_stats(mana) = 3.187 × mana^0.697 - 0.014`

| 指标 | V1 (2N+1) | V2 (幂律) | 改善 |
|------|-----------|----------|------|
| MAE | 2.22 | 0.66 | **70.1%** |
| RMSE | 2.66 | 0.87 | 67.3% |

**任务链**: T001(曲线拟合) → T002(关键词校准) → T003(文本解析) → T004(类型适配) → T005(综合评分)

---

## Phase 2: V7+ 数据驱动评分 (2026-04-18 ~ 04-19)

### 评分管线演进

```
L1(白板曲线) → L2(关键词分层) → L3(28正则文本) → L4(类型基线)
  → L5(37条件EV) → L6(HSReplay CPI混合) → L7(报告生成)
```

- **V7**: L1→L7 完整管线 + HSReplay Rankings 校准
- **V8**: 7 个上下文修正因子（回合曲线、类型上下文、池质量、亡语EV、斩杀加速、回溯EV、协同）
- **L6**: `V2 × (1-θ) + CPI × θ × max`, θ=0.3

### 数据文件

| 文件 | 内容 |
|------|------|
| v7_scoring_report.json | V7 评分全量 |
| v2_scoring_report.json | V2 评分 |
| l6_scoring_report.json | L6 评分 |
| pool_quality_report.json | 种族/类型池质量 |
| card_turn_data.json | HSReplay 平均回合 |
| rewind_delta_report.json | 回溯卡EV增量 |

---

## Phase 3: V9 RHEA 决策引擎 (2026-04-19)

### 核心组件

| 模块 | 文件 | 功能 |
|------|------|------|
| RHEA 搜索 | search/rhea_engine.py | 进化算法搜索最优出牌 |
| 斩杀检测 | search/lethal_checker.py | DFS 致命检测 |
| 游戏状态 | search/game_state.py | GameState/Minion/HeroState |
| 法术模拟 | utils/spell_simulator.py | 10 正则法术效果解析 |
| 对手模拟 | search/opponent_simulator.py | 贪心对手模型 |
| 风险评估 | search/risk_assessor.py | AoE脆弱性/超铺惩罚 |
| 动作规范 | search/action_normalize.py | 合法动作枚举+交叉修复 |

### 综合评估器

| 模块 | 文件 | 功能 |
|------|------|------|
| 复合评估 | evaluators/composite.py | 3轴加权融合 (tempo+value+survival) |
| 子模型 | evaluators/submodel.py | 场面/威胁/持续效果/触发4子模型 |
| 多目标 | evaluators/multi_objective.py | 3维Pareto + 阶段自适应标量化 |

### 集成测试

- 15 批次 HDT 真实卡组场景测试 (batch01→batch15)
- 覆盖：快速铺场、控制后期、OTK斩杀、疲劳、极端场面等
- **213→233 测试通过**

---

## Phase 4: V10 引擎大修 (2026-04-19)

### Phase 4a: 基础修复 (8 个 bug fix)

**Commit `3d1a409`**

| # | 修复 | 文件 |
|---|------|------|
| 1 | 斩杀检测：冲锋随从必须尊重嘲讽 | lethal_checker.py |
| 2 | 风怒双击：`has_attacked_once` 标记 | game_state.py + rhea_engine.py |
| 3 | 过载解析：中文正则 + PLAY时设定 + END_TURN扣减 | rhea_engine.py |
| 4 | 剧毒即杀：伤害后 target.health=0 | rhea_engine.py |
| 5 | 连击追踪：`cards_played_this_turn` 列表 | game_state.py |
| 6 | 疲劳伤害：递增计数器 | rhea_engine.py |
| 7 | 潜行打破：攻击后清除 | rhea_engine.py |
| 8 | 冰冻效果：`frozen_until_next_turn` 标记 | game_state.py + rhea_engine.py |

**设计文档**: `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### Phase 4b: 游戏规则研究

**Commit `c76e902`** — 1017 行，10 章 61 节

| 章节 | 内容 |
|------|------|
| Ch1 | 游戏区域（手牌10、场面7、奥秘5） |
| Ch2 | 法力系统（水晶增长、过载、临时法力） |
| Ch3 | 战斗系统（6阶段攻击序列、嘲讽/冲锋/突袭/风怒/圣盾/剧毒/潜行/冰冻/免疫/吸血） |
| Ch4 | 关键词机制（战吼/亡语/发现/抉择/连击/激励/过载/流放/复生/超额/腐蚀） |
| Ch5 | 触发/光环系统（Phase/Sequence、Whenever vs After、光环重算） |
| Ch6 | 奥秘系统（各职业触发条件、反制特殊规则） |
| Ch7 | 英雄技能（11职业、灌注升级路径、刷新机制） |
| Ch8 | 抽牌/疲劳（爆牌→墓地、疲劳递增1/2/3/…） |
| Ch9 | 2026特殊机制（兆示/裂变/延系/回溯/黑暗之赐/寓言/巨型/休眠/手牌定位/任务） |
| Ch10 | 附录（阶段解析、死亡创建步骤、触发队列不可变性） |

**研究来源**: wiki.gg Advanced Rulebook、Blizzard 补丁说明、outof.games

### Phase 4c: V10 状态感知评分框架设计

**Commit `788c461`**

诊断出 3 个根本缺陷：
1. **线性叠加** — 无法表达"斩杀=无限价值"
2. **静态vs动态脱节** — 评分不考虑游戏状态
3. **规则脱节** — 关键词分值无规则依据

三层架构设计：
- **CIV**（基础层）：V2→V7 离线管线 + 关键词交互 + 2026机制公式
- **SIV**（交互层）：8 个运行时状态修正器
- **BSV**（全局层）：softmax 非线性融合

**设计文档**: `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`

### Phase 4d: V10 评分实现 ✨

**Commit `a1b3221`** — 16 文件, 2758 行新增

| 模块 | 文件 | 功能 | 测试 |
|------|------|------|------|
| SIV | evaluators/siv.py | 8 状态修正器 + siv_score() 入口 | 54 |
| BSV | evaluators/bsv.py | softmax 融合 + 3轴 + 斩杀覆盖 | 24 |
| 关键词交互 | scorers/keyword_interactions.py | 8 条规则推导交互 | 168 |
| 机制基础值 | scorers/mechanic_base_values.py | 9 个2026机制CIV公式 | 含 |
| 集成 | evaluators/composite.py | V10_ENABLED 开关 + evaluate_v10() | 7 |
| A/B 对比 | evaluators/test_v10_ab_comparison.py | V10 vs legacy 验证 | 4 |
| 性能 | evaluators/test_v10_performance.py | 基准测试 | 3 |

**8 个 SIV 修正器**:

| # | 修正器 | 关键公式 | 规则章节 |
|---|--------|---------|---------|
| 1 | 斩杀感知 | `1 + (1-hp/30)² × 3.0` | Ch3 战斗 |
| 2 | 嘲讽约束 | `1 + 0.3 × 敌方嘲讽数` | Ch3.2 嘲讽 |
| 3 | 节奏窗口 | 法力曲线匹配度惩罚 | Ch2 法力 |
| 4 | 手牌位置 | 外域/裂变位置奖励 | Ch9.2 裂变 |
| 5 | 触发概率 | 铜须/瑞文/光环倍率 | Ch5 触发 |
| 6 | 种族协同 | 同族计数 × 0.1 | Ch9.3 延系 |
| 7 | 累积进度 | 灌注/兆示/任务阈值跳跃 | Ch9.1/9.7/9.10 |
| 8 | 反制感知 | 冰冻/奥秘/AoE威胁修正 | Ch6 奥秘 |

**BSV softmax 融合**:

```
raw = [tempo×w_t, value×w_v, survival×w_s]
weights = softmax(raw / 0.5)   # temperature=0.5
BSV = Σ weights[i] × raw[i]
if lethal_possible → BSV = 999.0
```

**阶段权重**: 早期(t=1.3,v=0.7,s=0.5) / 中期(1.0,1.0,1.0) / 后期(0.7,1.2,1.5)

**8 条关键词交互**（规则推导）:

| 交互 | 效果 | 规则源 |
|------|------|--------|
| 剧毒 vs 圣盾 | ×0.1 | Ch3.5+3.6 |
| 潜行+嘲讽 | 嘲讽=0 | Ch3.2+3.7 |
| 免疫+嘲讽 | 嘲讽=0 | Ch3.2+3.9 |
| 冰冻+风怒 | ×0.5 | Ch3.4+3.8 |
| 吸血 vs 圣盾敌人 | 吸血=0 | Ch3.5+3.10 |
| 复生+亡语 | ×1.5 | Ch4.2+4.9 |
| 铜须+战吼 | ×2.0 | Ch4.1 |
| 瑞文+亡语 | ×2.0 | Ch4.2 |

**测试**: 493 通过（260 新增 + 233 原有），零回归

---

## Phase 5: HDT 实时辅助决策 (2026-04-21 规划)

### 目标

将已有的 RHEA 决策引擎接入炉石传说实时游戏数据流，在玩家回合给出出牌/攻击建议。

### 技术方案

**选型**: Python 直接读取 Power.log（via python-hslog），无需 HDT 插件

```
Hearthstone Client → Power.log → LogWatcher(50ms轮询)
    → GameTracker(python-hslog增量解析) → StateBridge(Entity→GameState)
    → RHEAEngine.search() → DecisionPresenter(终端输出)
```

### 新增模块

```
hs_analysis/watcher/              # NEW
├── __init__.py
├── log_watcher.py                # 文件轮询 + 轮转检测 + 回合触发回调
├── game_tracker.py               # 封装 LogParser + EntityTreeExporter
├── state_bridge.py               # hearthstone.entities.Game → GameState 映射
└── decision_loop.py              # 主循环：串联所有模块
```

### 实施步骤

| Phase | 任务 | 文件 | 预估 |
|-------|------|------|------|
| 5a | 环境准备 | — | 1-2h |
| 5b | LogWatcher | watcher/log_watcher.py ~100行 | 3-4h |
| 5c | GameTracker | watcher/game_tracker.py ~150行 | 4-6h |
| 5d | StateBridge | watcher/state_bridge.py ~200行 | 3-4h |
| 5e | DecisionLoop | watcher/decision_loop.py ~150行 | 3-4h |
| 5f | 输出展示 | 增强 scripts/decision_presenter.py | 2-3h |
| 5g | 集成测试 | tests/test_live_integration.py | 3-4h |
| **总计** | | ~600 行新代码 | **15-21h** |

### 关键映射: python-hslog Entity → hs_analysis GameState

| python-hslog 来源 | 目标字段 |
|---|---|
| `Card.tags[GameTag.ATK]` | `Minion.attack` |
| `Card.tags[GameTag.HEALTH]` | `Minion.health` |
| `Card.tags[GameTag.ZONE]` → PLAY/HAND/DECK | 分发到 board/hand/deck |
| `Card.tags[GameTag.EXHAUSTED]` | `Minion.can_attack` |
| `Card.tags[GameTag.TAUNT/CHARGE/RUSH/...]` | `Minion.has_taunt/has_charge/...` |
| `Card.card_id` → CardIndex 查询 | `Card` 完整数据 |
| `Player.tags[GameTag.RESOURCES]` | `ManaState.available` |
| `Hero.tags[GameTag.ARMOR]` | `HeroState.armor` |

### 决策输出格式

```
═══ 回合 5 — 法力 5/5 ═══
推荐: [出牌] 瑞文的男性实验体 → 位置3, [攻击] 随从1 → 对面英雄, 结束回合
  信心度: 87% | 评分: +12.3

备选策略:
  激进: [出牌] 火焰之地信使 → 位置1, [攻击] 全部走脸, 结束回合 (评分: +10.8)
  稳健: [英雄技能], [出牌] 瑞文的男性实验体 → 位置3, 结束回合 (评分: +9.5)
```

### 关键风险

| 风险 | 缓解措施 |
|------|---------|
| macOS 不生成 Power.log | 开发调试用录制日志，生产环境需 Windows |
| python-hslog 版本滞后 | pin 版本，HearthSim 通常数天内更新 |
| Enchantment 信息不完整 | 通过 CardIndex 补充卡牌文本解析 |

### 前置研究成果

- `thoughts/archive/designs/2026-04-18-hdt-analysis-report.md` — HDT 架构分析
- `thoughts/shared/designs/2026-04-19-hdt-plugin-integration-research.md` — 三方案评估，选定方案B
- `hs_analysis/search/test_v9_hdt_batch01-16.py` — 16批次 HDT 风格集成测试（`HDTGameStateFactory` 可复用）

### 状态

✅ 已完成（2026-04-21 ~ 04-22）

**Commit `61ae4be`** — 实时 Power.log 决策管道

实现了 watcher 模块（log_watcher.py + game_tracker.py + state_bridge.py + decision_loop.py），
通过 python-hslog 增量解析 Power.log，在每个 MAIN_ACTION 决策点运行 RHEA 搜索。

**Commit `8922709`** — Power.log 审计，修复 18 个 Bug

基于真实 Power.log 回放审计，发现并修复 18 个解析/状态追踪 Bug
（P0×5 + P1×9 + P2×4）。审计报告见 `docs/architecture/BUG_REPORT_POWERLOG_AUDIT.md`。

**Commit `de0554d`** — Power.log 逐行回放系统

完整回放验证：12 个决策点全对局分析，法力曲线 1→10 正确。

---

## Phase 6: 自维护回放引擎 (2026-04-22)

### Commit `5aabadb` — 自维护回放引擎

**重大架构变更**: `game_replayer.py` 从依赖 `GameTracker`/`StateBridge`（python-hslog）
改为**自维护 entity 状态的逐行回放引擎**，直接解析 Power.log 原始格式。

### 修复的 10+ 解析 Bug

| # | Bug | 根因 | 影响 | 修复 |
|---|-----|------|------|------|
| 1 | 所有 entity card_type=0 | FULL_ENTITY 嵌套 tag 字符串值(HERO/MINION)，`int()` 失败返回 0 | 无法区分英雄/随从/法术 | 添加 `cardtype_map` 字符串→int 映射 |
| 2 | TAG_CHANGE ZONE=0 | ZONE 值(HAND/PLAY)为字符串，解析为 int→0 | 随从/手牌 zone 错误 | 添加 ZONE 字符串映射 |
| 3 | 复杂 Entity 方括号 | `Entity=[entityName=初始之火 id=89 zone=SETASIDE ...]` 含空格 | 正则只捕获部分 | 更新正则 `(\[[^\]]*\]\|\S+)` + 方括号解析 |
| 4 | Player MAXRESOURCES 丢失 | 玩家 entity 不在 `self.entities`，嵌套 tag 被跳过 | 无法获取法力上限 | PlayerState 新增 `max_mana`，特殊处理玩家嵌套 tag |
| 5 | 法力计算错误 | 用 `max_mana`(固定10) 而非 `resources`(当前水晶 1-10) | 法力永远 10/10 | 改用 `our_player.resources` |
| 6 | 游戏回合被覆盖 | 玩家级 `TURN` tag 覆盖 `game_turn`(如 6→11) | 回合号错误 | 仅处理 GameEntity 级 TURN |
| 7 | Minion() 参数错误 | `Minion` dataclass 无 `card_id` 参数 | TypeError | 移除 `card_id=` 参数 |
| 8 | 对手随从拷贝 Bug | 对手随从 append 到 `our_board` | 对手场面丢失 | 修正为 `opp_board.append()` |
| 9 | 重复 MAIN_ACTION | GameState + PowerTaskList 都触发 | 决策点重复 | 添加 `source` 参数，跳过 PowerTaskList |
| 10 | LIFESTEAL tag 值 | 误设为 238(=TAUNT) | 吸血=嘲讽 | 修正为 2145 |

### 新增功能

| 功能 | 说明 |
|------|------|
| FULL_ENTITY Updating 解析 | 1346 行 `Updating [entityName=... id=N]` 格式，更新已有 entity 的 card_id |
| 6 因子抉择质量评估 | 致命检测 + 法力效率 + 场面控制 + 策略多样性 + RHEA 分数解读 + 血量压力 |
| JSON 完整状态输出 | hand_cards / board_minions / opp_armor / opp_board_minions 写入 summary |
| 中文卡牌名缓存 | 从 `card_data/zhCN/cards.collectible.json` 加载 |
| 空手牌提示 | 早期回合卡牌在 MAIN_ACTION 后加入的提示信息 |

### 验证结果

| 指标 | 结果 |
|------|------|
| 决策点 | 13 (12 唯一回合 + 1 重复回合 23) |
| 法力曲线 | 1/1 → 2/2 → ... → 10/10 ✅ |
| 场面追踪 | 0→4→1→2→4 随从 ✅ |
| 手牌追踪 | 0→2→1→4→5→6→7→10 ✅ |
| RHEA 时间 | 136-318ms/决策 |
| 抉择评级 | ✅合理 / ⚠️次优 / 🔴致命 / ❌错误 |
| 对手场面 | 名字已知时显示中文，未知时"未知" |

---

## 整体进度总览 (2026-04-22)

### 已完成 ✅

| # | 阶段 | 产出 | 测试 |
|---|------|------|------|
| 1 | 数据管线 | 1015 标准卡 + 5209 狂野卡, CardIndex | 92 |
| 2 | V2 评分 | 幂律曲线 MAE 0.66 | 含 |
| 3 | V7 评分 | HSReplay 校准完整管线 | 16 |
| 4 | V8 评分 | 7 上下文修正因子 | 16 |
| 5 | V9 RHEA 引擎 | 搜索+斩杀+状态+模拟全套 | 150+ |
| 6 | 综合评估器 | 3轴复合 + 4子模型 + Pareto | 含 |
| 7 | V10 Phase 1 | 8 个基础 bug 修复 | 20 |
| 8 | 游戏规则 | 1017 行完整规则参考 | 0 (文档) |
| 9 | V10 评分框架设计 | 三层架构 CIV+SIV+BSV | 0 (设计) |
| 10 | V10 评分实现 | SIV+BSV+交互+机制+集成 | 260 |
| 11 | V10 Phase 2 | 附魔+触发+战吼+亡语+光环+发现+地标 | 341 |
| 12 | V10 Phase 3 | 灌注+流放+巨型+兆示+任务+回溯 | ~63 |
| 13 | V10 Feedback | 延系+尸体+符文+黑暗之赐+目标选择+狂野发现 | 107 |
| 14 | 检索优化 | CardIndex LRU + ScoreProvider 缓存 | 含 |
| 15 | Phase 5: 实时管道 | watcher 模块 + python-hslog + DecisionLoop | 含 |
| 16 | Phase 6: 自维护回放 | 逐行 Power.log 解析 + 10+ bug 修复 + 6因子评估 | 回放验证 |
| **总计** | | **34+ 源文件, 12000+ 行** | **~795 通过** |

### 进行中 🔄

无当前进行中的任务。

### 待开始 ⏳

| 优先级 | 任务 | 说明 | 前置依赖 |
|--------|------|------|---------|
| 🟡 P1 | 评分校准 | ScoreProvider scoring_report.json 缺失，所有卡牌分数默认 0.0 | 无 |
| 🟡 P1 | Token 卡牌名 | 非收藏卡(SW_108t, TIME_875t 等)显示为原始 ID | 无 |
| 🟡 P1 | 性能基准 | 75ms RHEA 目标 | 无 |
| 🟡 P1 | 狂野评分 | 5209 卡池扩展 | 无 |
| 🟢 P2 | 实战验证 | 多场 Power.log 回放对比 | Phase 6 |
| 🟢 P2 | 实时模式测试 | macOS→Windows 环境验证 | Phase 5 |
| 🟢 P3 | 裂片机制 | 进入标准池时实现 | P1 |
| 🟢 P3 | 完整回溯集成 | 2分支评估 | P1 |

---

## Git 提交历史

| Hash | 日期 | 说明 |
|------|------|------|
| `1d29a87` | 04-17 | 项目初始化 |
| `96b2ebf` | 04-18 | V2 任务工作流 |
| `6e5faa5` | 04-18 | 卡牌建模 Skill |
| `4563ca7` | 04-18 | 项目约定文件 |
| `065a203` | 04-18 | Session 启动流程 |
| *(multiple)* | 04-18~19 | T001-T005 + 数据/分析/分类 |
| `3d1a409` | 04-19 | V10 engine overhaul 设计 |
| `6d49ddf` | 04-19 | V10 Phase 1 基础修复 + 文档约定 |
| `c76e902` | 04-19 | 完整游戏规则参考文档 |
| `788c461` | 04-19 | V10 评分框架设计 + PROJECT_STATE v3.0 |
| `46f7007` | 04-19 | V10 评分实现设计 |
| `1c4c3af` | 04-19 | V10 评分实现计划 |
| `a1b3221` | 04-19 | V10 评分实现 (SIV+BSV+集成, 493测试) |
| `61ae4be` | 04-21 | 实时 Power.log 决策管道 — watcher 模块 + RHEA 集成 |
| `8922709` | 04-22 | Power.log 审计 — 修复 18 个 Bug（P0×5 + P1×9 + P2×4） |
| `de0554d` | 04-22 | Power.log 逐行回放系统 — 12 决策点全对局分析 |
| `5aabadb` | 04-22 | 自维护回放引擎 — 修复10+解析Bug，6因子抉择质量评估 |

---

## 架构决策摘要

| # | 决策 | 理由 |
|---|------|------|
| D001 | HearthstoneJSON 主数据源 | 100% 覆盖，社区维护 |
| D002 | 轻量 EV 建模 | 80% 精度 × 10% 复杂度 |
| D006 | RHEA 进化搜索 | 探索/利用平衡，75ms 预算 |
| D009 | 三阶段渐进改造 | 233 测试不回归 |
| D010 | 附魔框架关键多米诺 | 所有触发型机制的基础 |
| D014 | 三层评分 CIV+SIV+BSV | 规则→价值修正器映射 |
| D015 | softmax 非线性融合 | 线性无法表达斩杀=∞ |
| D016 | 规则推导关键词交互 | 确定性交互逻辑，非经验常数 |

完整决策记录: `thoughts/DECISIONS.md`

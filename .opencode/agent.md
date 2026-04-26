# Agent Init — 炉石传说卡牌数值分析

## ⚡ Session 启动流程

每次新 session **第一条消息前**必须执行：

1. **平台检测**：运行 `uname -s 2>/dev/null || echo "Windows"` 自动识别当前 OS
   - macOS/Darwin → 使用 POSIX 命令（`rm -rf`, `&&`, `python3`）
   - Windows → 使用 PowerShell 语法（`Remove-Item -Recurse -Force`, `; if ($?) { }`, `python`）
   - 检测结果决定后续所有 shell 命令语法
2. **环境与命令**：`memory_search(query: "environment system preferences", tags: ["environment"], limit: 5)`
3. **项目约定**：`memory_search(query: "project rules conventions", tags: ["convention"], limit: 5)`
4. **项目知识**：`memory_search(query: "hs_analysis card modeling scoring", tags: ["project-knowledge"], limit: 10)`
5. **项目状态对齐**：读取以下文件确保与最新状态同步
   - `cat thoughts/PROJECT_CHARTER.md` — 项目目标与约束（不可变）
   - `cat thoughts/PROJECT_STATE.md` — 当前进度（单一事实来源）
   - `cat thoughts/DECISIONS.md` — 架构决策记录（最近 5 条）
6. **状态声明**：确认已读取上述文件，声明「已对齐项目状态」

如果 memory 中的环境信息与当前平台不匹配，重新检测并更新。

## 🔧 工具优先级

生成文件、执行代码、搜索代码时，**严格按以下优先级选择工具**：

1. **MCP 工具**（最高优先级）— 优先使用 MCP 提供的工具
   - 文件操作：`memory_ingest`, `memory_search` 等
   - 代码搜索：`ast_grep_search`, `ast_grep_replace`
   - GitHub：`github_*` 系列
   - Web：`web_search_exa`, `web_fetch_exa`, `searxng_web_search`
2. **OpenCode 内置工具**（次优先）— MCP 无对应工具时使用
   - `bash`, `read`, `write`, `edit`, `glob`, `grep`
   - `look_at`, `batch_read`
3. **子代理**（按需）— 复杂任务分解时使用
   - `codebase-locator`, `codebase-analyzer`, `pattern-finder`

**规则：** 同一功能有 MCP 和 OpenCode 两种工具时，选 MCP。

## 📐 大文件生成策略

当需要生成超过 **500 行**的文件时：

1. **先骨架后填充** — 先生成文件结构（imports、class 骨架、method 签名、docstring），再逐步填充实现
2. **分块写入** — 每次写入一个逻辑单元（一个类、一个函数组），不超过 200 行
3. **验证再继续** — 每写完一个模块，运行相关测试确认无误后再继续
4. **标记 TODO** — 未填充的部分用 `# TODO: implement` 标记，方便后续定位

## 🔬 研究任务流程

所有研究/调研性质的任务，**必须使用项目级 skill**：

- 卡牌建模研究 → 加载 `card-modeling` skill（`.opencode/skills/card-modeling/SKILL.md`）
- 文献调研、学术参考 → 使用 skill 中的 Academic References 和方法论
- 数据分析 → 遵循 skill 中的 5-phase 科学方法论（Collect → EDA → Model → Critique → Refine）

**触发词：** "调研"、"研究"、"分析"、"文献"、"方法论"、"评分模型"、"数据探索"

## 项目定位

通过**数学建模 + 数据驱动**量化《炉石传说》卡牌价值，建立多版本评分引擎（V2→V7→V8→L6）和竞技场决策系统（RHEA 搜索 + 贝叶斯对手建模）。

## 技术栈

- **语言**: Python 3.10+
- **包管理**: pyproject.toml, `pip install -e .`
- **依赖**: numpy, scipy, requests, dataclasses
- **数据存储**: JSON 文件（card_data/）, SQLite（hsreplay_cache.db）
- **数据源**: HearthstoneJSON, HSReplay, iyingdi
- **测试**: pytest（810 测试用例，809 passed）

## 核心包结构

```
analysis/                          # 核心包 (135 files, ~31K lines)
├── config.py                     # 全局配置（路径、常量）
├── data/                         # 数据获取与处理
│   ├── card_index.py             # CardIndex + get_index() — O(1) frozenset 查询
│   ├── card_data.py              # CardDB — get_pool/discover_pool/random_pool
│   ├── card_effects.py           # CardEffects 结构化效果提取（唯一允许 regex+中文）
│   └── ...
├── models/
│   └── card.py                   # Card dataclass（text/cost/mechanics/english_text）
├── scorers/                      # 评分引擎（V2→V7→V8→L6）
│   ├── vanilla_curve.py          # 白板曲线基准
│   ├── constants.py              # 评分常量 + 机制识别正则
│   └── mechanic_base_values.py   # 机制价值公式（灌注/兆示/任务）
├── evaluators/                   # 评估器
│   ├── composite.py              # 复合评估器（board/hand/hero/fatigue/progress）
│   ├── submodel.py               # 子模型（board tempo/opponent threat/discover EV）
│   └── siv.py                    # SIV 卡牌评分 + progress_modifier
├── search/                       # 搜索引擎
│   ├── abilities/                # 三层能力系统（parser→executor→orchestrator）
│   │   ├── definition.py         # 数据类型：EffectKind/AbilityTrigger/CardAbility/EffectSpec
│   │   ├── tokens.py             # 静态映射表（mechanics→trigger/verbs→effect）
│   │   ├── extractors.py         # 纯字符串提取器（zero regex, English only）
│   │   ├── parser.py             # AbilityParser（zero regex, mechanics+EN verbs）
│   │   ├── executor.py           # 效果执行器（31 EffectKind handlers）
│   │   ├── orchestrator.py       # 编排器（trigger dispatch/spell power/Brann/lifesteal）
│   │   ├── simulation.py         # apply_action（顶层动作应用）
│   │   ├── enumeration.py        # enumerate_legal_actions（PLAY/ATTACK/HERO_POWER/END_TURN）
│   │   └── actions.py            # Action dataclass + ActionType enum
│   ├── mcts/                     # MCTS 蒙特卡洛搜索
│   │   ├── expansion.py          # 节点展开（stochastic action sampling）
│   │   ├── turn_advance.py       # 跨回合推进（贪心出牌+攻击+对手模拟）
│   │   └── ...
│   ├── engine/                   # RHEA 滚动水平线进化
│   ├── game_state.py             # GameState/HeroState/Minion/ManaState dataclasses
│   ├── discover.py               # 发现框架（pool生成+约束解析+resolve_discover）
│   ├── imbue.py                  # 灌注（hero power升级，11职业差异化）
│   ├── herald.py                 # 兆示（职业士兵召唤）
│   ├── colossal.py               # 巨型（职业附属物）
│   ├── lethal_checker.py         # 致命检测
│   ├── opponent_simulator.py     # 对手模拟器
│   └── ...
├── watcher/                      # 实时决策系统
│   ├── global_tracker.py         # 全局追踪（15+ 关注点）
│   ├── state_bridge.py           # Entity→GameState 映射
│   └── ...
└── utils/
    ├── score_provider.py         # 评分数据提供（懒加载+缓存）
    └── bayesian_opponent.py      # 贝叶斯对手建模
```

## 数据文件

| 文件 | 用途 |
|------|------|
| `card_data/` | 清洗后的标准池/狂野卡牌数据（多语言） |
| `hs_cards/hsjson_standard.json` | HearthstoneJSON 原始数据 |
| `hs_cards/hsreplay_cache.db` | HSReplay 缓存数据库 |

## 运行入口

| 脚本 | 功能 |
|------|------|
| `scripts/run_fetch.py` | 数据获取 |
| `scripts/run_rhea.py` | RHEA 引擎运行 |
| `scripts/run_score_v2.py` | V2 评分 |
| `scripts/run_score_v7.py` | V7 评分 |

## 测试

```bash
pytest                          # 全量测试（810 用例）
pytest tests/                   # 仅 tests/ 目录
```

## 能力系统架构原则（强制）

### 三层分离

| 层 | 文件 | 职责 | 规则 |
|----|------|------|------|
| Layer 1 | parser.py | 卡牌→List[CardAbility] | **零正则，零中文**，仅英文string.find()/split() |
| Layer 2 | executor.py | EffectSpec→GameState | 纯状态变更，不解析文本 |
| Layer 3 | orchestrator.py | 编排(trigger dispatch/Brann/spell power) | 不解析文本，委托executor |

### 中文卡片处理路径
中文文本 → `_supplement_with_structured()` → `card_effects.get_effects()`（唯一允许regex+中文）

### 零卡牌特殊化
- 禁止 card_id/card_name/dbf_id 硬编码匹配
- 所有卡牌效果通过 AbilityParser + card_effects 统一解析
- 只在 display/log 层使用人类可读名称

## 评分体系演进

- **V2** — 属性 + 关键词基础评分
- **V7** — 基于 HSReplay 数据驱动的实绩评分
- **V8** — 上下文感知（回合数、场面饱和度、种族协同、发现池期望）
- **L6** — 真实世界综合评分
- **Phase 5** — HDT 实时辅助决策（Power.log + python-hslog + 实时搜索）← 当前规划
- **Phase 8** — MCTS 蒙特卡洛搜索 + 贝叶斯对手威胁评估 ✅
- **Phase 9** — 模拟覆盖升级（parser 94%覆盖率 + 对手法术模拟 + 随机召唤真实卡牌）✅

## 开发约定

- 所有核心逻辑在 `analysis/` 包内，不在 `scripts/`
- `scripts/` 只放运行入口和独立工具脚本
- 数据文件通过脚本生成，不手动修改
- 测试文件放在 `tests/`
- import 路径使用 `from analysis.xxx import yyy`
- commit 格式: `feat: / fix: / docs: / cleanup: 简述`

## V10 设计生产规范

> 后续 Phase 2/3 的设计生产（设计文档 → 计划 → 实现）遵循以下流程。

### 文件结构规范

```
thoughts/
├── PROJECT_CHARTER.md          # 项目目标与约束（不可变）
├── PROJECT_STATE.md            # 当前进度（每次变更后更新）
├── DECISIONS.md                # 架构决策记录（追加写入）
└── shared/
    ├── designs/
    │   └── YYYY-MM-DD-{topic}-design.md    # 设计文档
    └── plans/
        └── YYYY-MM-DD-{topic}.md           # 实现计划
```

### 设计文档模板

每个 Phase 开始前，产出设计文档，包含以下 section（缺一不可）：

1. **Problem Statement** — 解决什么问题，影响哪些卡牌/场景
2. **Constraints** — 不可逾越的限制（向后兼容、性能、依赖）
3. **Approach** — 选定方案 + 排斥的替代方案 + 理由
4. **Architecture** — 高层结构，模块交互，数据流
5. **Components** — 新增/修改的文件，每个文件的职责
6. **Data Flow** — 数据从输入到输出的完整路径
7. **Error Handling** — 失败策略（降级、回退、日志）
8. **Testing Strategy** — 测试批次号、测试数量、覆盖场景
9. **Open Questions** — 未解决的问题（如有）

### 生产流程

```
[brainstormer]  调研 + 分析 → 设计文档
    ↓
[planner]       设计文档 → 实现计划（micro-tasks + batches）
    ↓
[executor]      实现计划 → 代码 + 测试
    ↓
[reviewer]      验证测试通过 → 更新 PROJECT_STATE.md + DECISIONS.md
```

### 计划文档规范

- 每个计划拆为 **micro-tasks**，每个 task 对应一个文件
- 独立 tasks 放同一 batch 并行执行
- 有依赖的 tasks 拆为多个 batch，串行执行
- 每个 micro-task 包含：目标、修改文件、关键实现点、验证方式

### 进度更新规范

每完成一个 Phase：
1. 更新 `PROJECT_STATE.md` — 标记 DONE 项，更新测试计数，更新 Next Actions
2. 追加 `DECISIONS.md` — 记录该 Phase 做出的关键设计决策
3. Git commit — `feat: V10 Phase N: {描述}`

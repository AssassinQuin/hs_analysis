# 成熟卡牌游戏模拟器架构调研

> **生成日期**: 2026-04-26
> **范围**: 炉石传说/卡牌游戏模拟器开源项目架构调研
> **目的**: 为 hs_analysis 重构提供架构参考

---

## 一、各成熟项目架构概览

### 1.1 MetaStone（Java）

```
metastone/
├── app/          # 应用 UI 代码和资源
├── game/         # 游戏源代码（依赖 shared 模块）
├── shared/       # app 和 game 之间的共享代码
└── cards/        # 卡牌、卡组和卡组格式数据文件
```

**架构特点：**
- **声明式卡牌定义**：卡牌通过 JSON 声明式定义，引擎负责解释执行
- **CardCatalogue** 类管理卡牌数据
- **GameContext** 包含状态、玩家代理和状态操作代码（GameLogic）
- **可扩展卡牌系统**：支持自定义卡牌

**关键设计模式：** 目录/包分离（数据cards、逻辑game、共享shared、UI app）

### 1.2 Fireplace（Python）

```
fireplace/
├── fireplace/
│   ├── cards/           # 卡牌实现（按卡组分类）
│   ├── dsl/             # 声明式 DSL（选择器、评估器等）
│   ├── actions.py       # 游戏动作系统
│   ├── game.py          # 游戏主类
│   ├── player.py        # 玩家类
│   └── entity.py        # 实体基类
└── tests/
```

**架构特点：**
- **面向对象层次**：所有游戏对象都是 Entity 的子类
- **标签系统**：实体通过 tags 字典跟踪属性，GameTag 枚举键值对
- **声明式 DSL**：Selector 支持集合操作（+、|、-）
- **事件驱动**：通过 EventListener 处理卡牌效果触发

**关键模式：** 状态机模式 + 观察者模式 + 组合模式 + 策略模式

### 1.3 SabberStone（C# .NET Core）

```
SabberStone/
├── SabberStoneCore/
│   ├── Model/           # 游戏模型
│   ├── Actions/         # 动作系统
│   ├── Tasks/           # 任务系统（SimpleTask, ComplexTask）
│   └── Triggers/        # 触发器系统
├── SabberStoneBasicAI/  # AI 实现
├── SabberStoneCoreTest/ # 单元测试
└── SabberStoneGui/      # GUI
```

**架构特点：**
- **任务系统**：SimpleTask + ComplexTask 实现卡牌效果，可重用可组合
- **洋葱系统**：分层处理实体增益效果
- **三容器标签查询**：实体非静态容器 + Card 对象 + 外部光环效果

**关键模式：** 任务模式 + 堆栈模式 + 装饰器模式 + 工厂模式

### 1.4 Hearthstone Lab（Python）

```
hearthstone-lab/
├── src/
│   ├── collector/       # 卡牌数据同步
│   ├── core/            # 游戏模型、枚举、卡组编码、规则
│   ├── db/              # 数据库会话和 ORM
│   ├── deckbuilder/     # 卡组构建器
│   ├── simulator/       # 游戏引擎、AI、事件日志
│   ├── scheduler/       # 后台任务
│   └── web/             # FastAPI 应用
└── tests/
```

**关键模式：** 分层架构 + 仓储模式 + 服务层模式

### 1.5 HearthShroud（Haskell）

**关键特点：**
- 单子 API（HearthMonad）驱动游戏引擎
- 卡牌建模为纯数据 AST（DSL）
- 类型级别约束
- 解释器模式：引擎解释卡牌，AI 解释相同的卡牌

---

## 二、共同架构模式总结

### 2.1 核心架构模式

| 模式 | 描述 | 代表项目 |
|------|------|----------|
| **实体-标签系统** | 所有游戏对象都是实体，通过标签字典存储状态 | Fireplace, SabberStone |
| **事件驱动** | 事件总线 + 监听器解耦组件 | Fireplace, MetaStone |
| **声明式卡牌定义** | 卡牌通过数据（JSON/XML/DSL）定义，引擎解释 | MetaStone, SabberStone |
| **分层架构** | 数据层→核心引擎→AI/模拟→UI/接口 | Hearthstone Lab |
| **任务/效果系统** | 效果分解为可重用可组合的任务 | SabberStone, Fireplace |

### 2.2 卡牌数据管理模式

| 模式 | 优势 | 适用场景 |
|------|------|----------|
| **外部数据文件 + 加载器** | 数据与逻辑分离，易更新 | MetaStone (JSON), SabberStone (XML) |
| **代码定义 + 自动发现** | 灵活，支持复杂逻辑 | Fireplace (Python 类) |

**最佳实践：** 静态数据从外部加载，动态效果通过代码/DSL定义，提供卡牌目录/注册表

### 2.3 效果系统模式

| 模式 | 优势 | 代表 |
|------|------|------|
| **任务系统** | 可重用、可组合 | SabberStone |
| **事件监听器** | 响应式、解耦 | Fireplace |
| **命令模式** | 可撤销、可序列化 | 多个项目 |

### 2.4 AI 架构模式

| 模式 | 描述 |
|------|------|
| **MCTS + ISMCTS** | 处理不完美信息，支持状态克隆 |
| **策略模式** | 抽象基类，可插拔策略选择 |
| **模块化评估函数** | 分离评估逻辑，支持多种评估策略 |

---

## 三、对 hs_analysis 的架构启示

### 3.1 项目定位差异

hs_analysis **不是完整的炉石模拟器**，而是一个**分析决策引擎**：
- ✅ 需要精确的卡牌效果模拟（支持 MCTS 搜索）
- ✅ 需要高效的评分/评估系统（支持多策略决策）
- ❌ 不需要完整的 UI/可视化
- ❌ 不需要完整的多人游戏支持
- ❌ 不需要卡牌编辑器

### 3.2 适用的模式

| 模式 | 适用性 | 理由 |
|------|--------|------|
| **事件驱动** | ✅ 适用 | 已有 trigger_system.py，可增强 |
| **声明式效果** | ✅ 适用 | 已有 abilities pipeline，继续深化 |
| **分层架构** | ✅ 适用 | data→abilities→search→evaluator 已有雏形 |
| **任务/效果系统** | ⚠️ 部分适用 | 已有 executor.py，但不宜过度设计 |
| **实体-标签** | ❌ 不适用 | 已有 KeywordSet，但完全迁移成本过高 |

### 3.3 不适用的模式

| 模式 | 不适用理由 |
|------|-----------|
| **不可变状态** | Python 性能限制，MCTS 需要大量状态克隆 |
| **完整 ECS** | 过度设计，项目不需要通用游戏引擎 |
| **微服务架构** | 单机分析工具，不需要服务化 |

---

## 四、参考项目信息

| 项目 | 语言 | GitHub | 关键特点 |
|------|------|--------|----------|
| MetaStone | Java | demilich1/metastone | 最完整的 Java 模拟器 |
| Fireplace | Python | jleclanche/fireplace | Python DSL，事件驱动 |
| SabberStone | C# |_HearthSim/SabberStone | 任务系统，94%覆盖率 |
| Hearthstone Lab | Python | — | FastAPI + 模拟器 |
| HearthShroud | Haskell | — | 纯函数 AST |
| hearthstone-ai | — | peter1591/hearthstone-ai | MCTS + 神经网络 |

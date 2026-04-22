---
date: 2026-04-18
topic: "Hearthstone-Deck-Tracker 项目分析与扩展方案"
status: validated
---

## 项目概述

**Hearthstone-Deck-Tracker (HDT)** 是 Windows 平台最流行的炉石传说卡组追踪器，由 HearthSim 社区维护。GitHub 地址：https://github.com/HearthSim/Hearthstone-Deck-Tracker

---

## 技术栈

| 项目 | 详情 |
|------|------|
| 语言 | C# 10 (LangVersion=10, nullable 开启) |
| 框架 | .NET Framework 4.7.2（不是 .NET Core / .NET 5+） |
| UI | WPF + MahApps.Metro 1.6.5 |
| 架构 | x86 单进程，混合 code-behind + 事件驱动 |
| 构建 | VS2019+ .sln，SDK-style csproj |
| 自动更新 | Squirrel.Windows |
| 序列化 | Newtonsoft.Json 12.0.3 |
| 其他 NuGet | HtmlAgilityPack 1.11.23, LiveCharts 0.9.7, Mono.Cecil 0.9.6.1, SharpRaven 2.4.0 |

### 预编译依赖 DLL（源码不在本仓库）

- **HearthDb.dll** — 卡牌数据库（NuGet 包）
- **HearthMirror.dll** — 进程内存读取（源码在独立仓库）
- **HSReplay.dll** — HSReplay.net API 客户端
- **BobsBuddy.dll** — 酒馆战棋战斗模拟器

---

## 开发环境准备

### 必须安装

- Visual Studio 2019+（Community 版免费）— 带 ".NET 桌面开发" 工作负载
- .NET Framework 4.7.2 SDK（VS 安装器中勾选）
- Git for Windows

### 克隆后步骤

1. 运行 `bootstrap.ps1` — 下载预编译 DLL
2. 打开 `Hearthstone Deck Tracker.sln`
3. 还原 NuGet 包
4. 构建 Release|x86 配置

### 调试要求

- 需要运行中的 Hearthstone 客户端才能测试完整追踪流程
- 日志文件位置：`%LOCALAPPDATA%\Blizzard\Hearthstone\Logs\`

---

## 架构概览

```
Hearthstone Deck Tracker/
├── Core.cs (21KB)              → 中央单例枢纽
├── GameEventHandler.cs (97KB)  → 所有游戏事件处理
├── Config.cs (36KB)            → 配置系统
├── Hearthstone/
│   ├── Card.cs (22KB)          → 卡牌数据模型
│   ├── GameV2.cs (33KB)        → 游戏状态 (Player + Opponent)
│   ├── Player.cs (34KB)        → 玩家状态 (Hand, Board, Deck, Secrets)
│   ├── Deck.cs (20KB)          → 卡组模型
│   ├── Entities/Entity.cs (11KB) → 运行时实体/Tag 封装
│   ├── Secrets/                → 秘密排除系统 (约束传播)
│   ├── EffectSystem/           → 效果追踪 (按职业分11个子目录)
│   ├── RelatedCardsSystem/     → 卡牌关联关系映射
│   └── CounterSystem/          → UI 计数器
├── LogReader/
│   ├── Handlers/PowerHandler.cs (74KB) → 日志解析核心
│   ├── Handlers/TagChangeActions.cs (47KB) → Tag 变更动作
│   └── GameTagHelper.cs        → GameTag 映射
├── BobsBuddy/
│   └── BobsBuddyInvoker.cs (44KB) → 酒馆战斗模拟集成
├── HsReplay/
│   └── ApiWrapper.cs (13KB)    → HSReplay API (胜率/留牌数据)
├── API/                        → 插件 API 接口
│   ├── GameEvents.cs           → 游戏事件钩子
│   ├── Core.cs                 → 核心 API 暴露
│   └── LogEvents.cs            → 日志事件
├── Plugins/
│   ├── IPlugin.cs              → 插件接口
│   ├── PluginManager.cs (9KB)  → 插件管理器
│   └── PluginWrapper.cs        → 插件包装
├── Utility/BoardDamage/        → 场面伤害计算
│   ├── BoardCard.cs            → 场面随从伤害
│   ├── BoardHero.cs            → 英雄伤害
│   └── BoardState.cs           → 整体场面状态
└── Stats/                      → 对局统计系统
```

---

## 游戏状态检测机制

### 双通道检测

| 方法 | 用途 | 实现 |
|------|------|------|
| **日志解析** (主) | 追踪出牌、战斗、法术 | HearthWatcher 读 debug 日志，50ms 轮询，PowerHandler 解析 |
| **内存读取** (辅) | 卡组检测、收藏、竞技场 | HearthMirror C 库，通过 PID 读 Hearthstone 进程 |

### 事件流

```
Hearthstone 日志文件
    ↓ (HearthWatcher/LogFileWatcher)
LogLine (namespace + time + content)
    ↓ (LogReader/Handlers)
PowerHandler.cs → 解析 CREATE_ENTITY, TAG_CHANGE, BLOCK 等
    ↓
GameEventHandler.cs → 更新游戏状态
    ↓
GameV2.cs → Player/Opponent 状态更新
    ↓
UI 更新 + 插件事件通知
```

---

## 卡牌数据模型 (Card.cs)

### 核心属性

| 字段 | 类型 | 说明 |
|------|------|------|
| Id | string | 卡牌 ID (如 "EX1_116") |
| DbfId | int | 数据库 ID |
| Name / EnglishText | string | 中英文名称 |
| Cost | int | 法力消耗 |
| Attack | int | 攻击力 |
| Health | int | 生命值 |
| Mechanics | List\<string\> | 关键词 (如 ["TAUNT", "BATTLECRY"]) |
| PlayerClass | string | 职业 |
| Rarity | string | 稀有度 |
| Race / RaceEnum | string/enum | 种族 |
| Type / TypeEnum | string/enum | 类型 (随从/法术/武器) |
| Set / CardSet | string/enum | 卡包 |
| Text | string | 卡牌描述文本 |
| Overload | int | 过载值 |
| Collectible | bool | 是否可收集 |
| TechLevel | int | 酒馆等级 |

### 运行时追踪字段

| 字段 | 说明 |
|------|------|
| Count | 手牌中数量 |
| InHandCount | 手牌中出现次数 |
| IsMulliganOption | 是否为起手选项 |
| CardWinrates | HSReplay 胜率数据 |
| Jousted | 是否被窥牌 |
| IsCreated | 是否由其他卡牌生成 |
| WasDiscarded | 是否被弃掉 |

### 数据来源

卡牌数据来自 **HearthDb NuGet 包**（不是本地 JSON/XML）。`Database.cs` 封装了 `HearthDb.Cards.All` 字典查找。

---

## 已有可复用功能

### ✅ 秘密排除系统 (SecretsManager)

- **文件**: `SecretsManager.cs` (14KB) + `SecretsEventHandler.cs` (16KB)
- **算法**: 约束传播 — 列出所有可能秘密，每个触发事件排除不可能选项
- **借鉴价值**: ⭐⭐⭐ 对手手牌预测可复用相同模式

### ✅ 场面伤害计算 (BoardDamage)

- **文件**: `Utility/BoardDamage/` (BoardCard, BoardHero, BoardState, PlayerBoard)
- **功能**: 计算场面总伤害、可分配伤害
- **测试**: 有完整单元测试 (`HDTTests/BoardDamage/`)
- **借鉴价值**: ⭐⭐⭐ 斩杀检测的基础组件

### ✅ 对手追踪

- **文件**: `Player.cs` 中的 Opponent 状态
- **追踪**: Hand, Board, Deck, Secrets, Graveyard, SetAside, Quests
- **特殊**: `PredictedCard.cs` — 对手卡牌预测已存在基础
- **借鉴价值**: ⭐⭐⭐ 手牌概率推断的起点

### ✅ 效果追踪系统 (EffectSystem)

- **文件**: `Hearthstone/EffectSystem/` 按职业分类
- **功能**: 追踪场上活跃效果
- **借鉴价值**: ⭐⭐ 交互可能性分析的数据源

### ✅ HSReplay API 集成

- **文件**: `HsReplay/ApiWrapper.cs` (13KB)
- **数据**: 留牌胜率、卡组胜率、酒馆统计
- **API Key**: `089b2bc6-3c26-4aab-adbe-bcfd5bb48671`
- **借鉴价值**: ⭐⭐ 外部胜率数据可用于验证 AI 评估

### ✅ 插件系统

- **接口**: `IPlugin.cs` — OnLoad/OnUnload/OnButtonPress/OnUpdate(~100ms)
- **事件**: `API/GameEvents.cs` 提供游戏事件钩子
- **借鉴价值**: ⭐⭐⭐ 方案B（Python后端）的关键桥接点

### ✅ BobsBuddy 酒馆模拟器

- **文件**: `BobsBuddyInvoker.cs` (44KB)
- **算法**: Monte Carlo 模拟 (10,000 次迭代, 多线程)
- **限制**: 仅酒馆战棋，不含构筑模式
- **借鉴价值**: ⭐⭐ 构筑模式模拟器的架构参考

---

## 不存在的功能 (必须从零构建)

| 功能 | 说明 | 优先级 |
|------|------|--------|
| 构筑模式斩杀检测 | BobsBuddy 仅限酒馆 | 🔴 最高 |
| 棋盘评分 / 局势评估 | 无位置评分函数 | 🔴 最高 |
| 出牌优先级排序 | 无决策排序逻辑 | 🔴 最高 |
| 丝血反杀概率估算 | 无概率模型 | 🟡 高 |
| 对手手牌概率推断 | 仅有基础追踪 | 🟡 高 |
| 交互可能性分析 | 无组合枚举 | 🟡 高 |
| 游戏树搜索 / MCTS | 完全空白 | 🟠 中 |
| 卡牌协同性评分 | 无关联评分 | 🟠 中 |
| 卡组推荐算法 | 无本地 AI | 🔵 低 |

---

## 扩展方案对比

### 方案 A：直接 Fork HDT

| 优势 | 劣势 |
|------|------|
| 复用完整的日志解析 | 困在 .NET Framework 4.7.2 (将弃) |
| 复用卡牌模型 | 97KB GameEventHandler 难修改 |
| 不需要自己实现状态检测 | C# 的 ML/优化库弱于 Python |
| 直接 overlay 显示 | x86 架构限制 |

### 方案 B：HDT 插件 + Python AI 后端（推荐）

| 优势 | 劣势 |
|------|------|
| Python 生态 (scipy, PyTorch) | 需要实现 IPC 通信 |
| V2 模型已在 Python | 两个进程间通信开销 |
| AI 算法独立迭代 | 需要写 HDT 插件 (~200行) |
| 不受 HDT 架构约束 | 状态同步可能有延迟 |

**推荐方案 B 的理由**：
1. V2 三层卡牌模型已经是 Python
2. 决策引擎用 Python 更灵活
3. HDT 插件 API 已提供数据桥接点
4. AI 后端可以独立测试和迭代

---

## 用户需求的扩展模块设计

### 1. 抉择分析引擎 (Decision Analyzer)

- **输入**: GameV2 当前状态
- **输出**: 所有合法操作评分排序列表
- **核心模块**: Action Generator (枚举) + Position Evaluator (评分) + Pruning (剪枝)

### 2. 斩杀检测器 (Lethal Detector) — 最高优先级

- **输入**: 场面 + 手牌 + 法力值
- **算法**: DFS/BFS 搜索所有攻击序列 + 法术组合
- **基础**: BoardDamage 已有静态计算，需加组合搜索

### 3. 丝血反杀估算 (Comeback Estimator)

- **输入**: 双方血量、场面差距、手牌数量
- **算法**: 统计模型 + 快速 Monte Carlo + 启发式评分

### 4. 对手手牌判断 (Opponent Hand Predictor)

- **算法**: 贝叶斯推断 + 卡组原型匹配 + 出牌时序分析
- **参考**: SecretsManager 的约束传播模式

### 5. 交互可能性分析 (Interaction Analyzer)

- **输入**: 场面所有实体、Tag 状态
- **输出**: 可能交互列表 (战吼、亡语、激怒等)
- **基础**: EffectSystem + RelatedCardsSystem

### 6. 统一评分框架 (Decision Ranker)

```
得分 = w1*斩杀概率 + w2*场面控制增益 + w3*反杀概率 + w4*信息优势 + w5*资源效率
```

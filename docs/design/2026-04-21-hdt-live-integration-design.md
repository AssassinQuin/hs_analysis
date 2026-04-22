---
date: 2026-04-21
topic: "HDT Live Integration — Power.log 实时决策辅助"
status: draft
references:
  - thoughts/shared/designs/2026-04-19-hdt-plugin-integration-research.md
  - thoughts/archive/designs/2026-04-18-hdt-analysis-report.md
  - hs_analysis/search/test_v9_hdt_batch01.py
---

# Phase 5: HDT Live Integration Design

## 1. Problem Statement

当前 hs_analysis 引擎 (RHEA + SIV/BSV 评分 + 斩杀检测 + 对手模拟) 已完成，但仅支持手动构建 GameState 进行离线分析。目标是接入炉石传说实时游戏数据流 (Power.log)，在玩家每个回合自动分析并输出出牌/攻击建议。

影响场景：
- 构筑模式对战实时辅助
- 每个回合给出主推荐 + 备选策略
- 检测斩杀、风险提示

## 2. Constraints

1. **平台**: Power.log 仅 Windows 版炉石生成，macOS 版不生成日志
2. **延迟**: 炉石是回合制游戏，分析延迟容忍度高 (<2s 可接受)
3. **向后兼容**: 不修改现有 GameState / RHEAEngine API，只新增 watcher 层
4. **依赖**: python-hearthstone 库 (`pip install hearthstone`)，MIT 许可
5. **测试**: 必须支持离线回放测试（用录制的 Power.log 文件）

## 3. Approach

**选定方案: Python 直接读取 Power.log (方案 B)**

排斥方案:
- ❌ HDT 插件 (方案 A/C): 需要维护 C# DLL，增加 IPC 复杂度，HDT 非必需
- ❌ 内存读取: 需要 HearthMirror C 库，复杂度极高且版本脆弱

理由:
1. python-hslog 已提供完整的 Power.log 增量解析 + 实体模型
2. 单进程架构，无需 IPC
3. 可离线回放 Power.log 进行测试
4. 已有 `HDTGameStateFactory` 作为 StateBridge 的参考实现

## 4. Architecture

```
┌─────────────────────────────────────────────────┐
│  hs_analysis (Python)                            │
│                                                  │
│  ┌──────────────┐   ┌───────────────┐            │
│  │ LogWatcher   │──→│ GameTracker   │            │
│  │ - 50ms 轮询  │   │ - LogParser   │            │
│  │ - 轮转检测   │   │ - Exporter    │            │
│  │ - 回合触发   │   │ - Game 实体树 │            │
│  └──────────────┘   └───────┬───────┘            │
│                             │                    │
│                   ┌─────────▼─────────┐          │
│                   │ StateBridge       │          │
│                   │ Game → GameState  │          │
│                   │ + CardIndex 查询  │          │
│                   └─────────┬─────────┘          │
│                             │                    │
│          ┌──────────────────┼────────────────┐   │
│          │                  │                │   │
│  ┌───────▼──────┐  ┌───────▼──────┐  ┌─────▼──────┐
│  │ load_scores  │  │ RHEAEngine   │  │ LethalChk  │
│  │ into_hand()  │  │ .search()    │  │ .check()   │
│  └──────────────┘  └──────┬───────┘  └────────────┘
│                           │                     │
│                  ┌────────▼────────┐             │
│                  │ DecisionPresenter│             │
│                  │ (终端输出)       │             │
│                  └─────────────────┘             │
└─────────────────────────────────────────────────┘
         ▲
         │ 50ms 文件轮询
         │
%LOCALAPPDATA%\Blizzard\Hearthstone\Logs\Power.log
```

## 5. Components

### 5.1 `hs_analysis/watcher/__init__.py`
包初始化。

### 5.2 `hs_analysis/watcher/log_watcher.py` (~100 行)

职责:
- 文件轮询: 50ms 间隔读取新行
- 轮转检测: `st_size < position` 时重置 parser
- 事件回调:
  - `on_new_line(line)` — 每行日志
  - `on_turn_start()` — 检测到 `STEP=MAIN_ACTION` + 当前玩家
  - `on_game_start()` — 检测到 `CREATE_GAME`
  - `on_game_end()` — 检测到游戏结束

关键实现:
```python
class LogWatcher:
    def __init__(self, log_path: str, poll_interval: float = 0.05):
        ...
    def start(self, callbacks: WatcherCallbacks) -> None:
        # 主循环: poll → read → parse → callback
    def stop(self) -> None:
        ...
    def _check_rotation(self) -> bool:
        # 文件大小 < position → 轮转
```

### 5.3 `hs_analysis/watcher/game_tracker.py` (~150 行)

职责:
- 封装 `hearthstone.hslog.parser.LogParser`
- 封装 `hearthstone.hslog.export.EntityTreeExporter`
- 增量解析: `parser.read_line(line)`
- 导出当前游戏状态: `exporter.export()`
- 高级查询接口: `get_player_entities()`, `get_opponent_entities()`

关键实现:
```python
class GameTracker:
    def __init__(self):
        self.parser = LogParser()
        self.exporter = None
        self.game = None

    def feed_line(self, line: str) -> None:
        self.parser.read_line(line)

    def export_game(self) -> Optional[Game]:
        if not self.parser.game_state_data:
            return None
        if self.exporter is None:
            self.exporter = EntityTreeExporter(self.parser.game_state_data)
        self.game = self.exporter.export()
        return self.game

    def reset(self) -> None:
        self.parser = LogParser()
        self.exporter = None
        self.game = None
```

### 5.4 `hs_analysis/watcher/state_bridge.py` (~200 行)

职责: 将 `hearthstone.entities.Game` 映射为 `hs_analysis.search.game_state.GameState`

这是最关键的模块。映射表:

| python-hslog Entity | → | hs_analysis GameState |
|---|---|---|
| `Player.tags[GameTag.RESOURCES]` | → | `ManaState.max_mana` |
| `Player.tags[GameTag.RESOURCES] - OVERLOAD_OWED` | → | `ManaState.available` |
| `Player.tags[GameTag.OVERLOAD_OWED]` | → | `ManaState.overloaded` |
| `Player.tags[GameTag.OVERLOAD_LOCKED]` | → | `ManaState.overload_next` |
| `Hero.tags[GameTag.HEALTH]` | → | `HeroState.hp` |
| `Hero.tags[GameTag.ARMOR]` | → | `HeroState.armor` |
| `Hero.tags[GameTag.CLASS]` → enum lookup | → | `HeroState.hero_class` |
| `Card.tags[GameTag.ATK]` | → | `Minion.attack` |
| `Card.tags[GameTag.HEALTH]` | → | `Minion.health` |
| `Card.tags[GameTag.COST]` | → | `Minion.cost` / `Card.cost` |
| `Card.tags[GameTag.EXHAUSTED]` → invert | → | `Minion.can_attack` |
| `Card.tags[GameTag.TAUNT]` | → | `Minion.has_taunt` |
| `Card.tags[GameTag.CHARGE]` | → | `Minion.has_charge` |
| `Card.tags[GameTag.RUSH]` | → | `Minion.has_rush` |
| `Card.tags[GameTag.DIVINE_SHIELD]` | → | `Minion.has_divine_shield` |
| `Card.tags[GameTag.STEALTH]` | → | `Minion.has_stealth` |
| `Card.tags[GameTag.WINDFURY]` | → | `Minion.has_windfury` |
| `Card.tags[GameTag.POISONOUS]` | → | `Minion.has_poisonous` |
| `Card.card_id` → CardIndex lookup | → | `Card` (full data with text, mechanics) |
| `Card.tags[GameTag.CARDTYPE]` | → | Card type dispatch (minion/spell/weapon/hero) |
| `Card.tags[GameTag.WEAPON]` / DURABILITY | → | `Weapon` |
| `Card.tags[GameTag.ZONE]` | → | 分发到 board/hand/deck |
| `Player.in_zone(Zone.HAND)` count | → | Opponent hand_count |
| Secret entities in Zone.SECRET | → | `OpponentState.secrets` |

可复用:
- `HDTGameStateFactory._entity_to_minion()` (batch01) 的 GameTag→Minion 字段映射逻辑
- `HDTGameStateFactory._entity_to_card()` 的 entity→Card 转换逻辑
- `CardIndex` 用于 card_id→完整卡牌数据查询

```python
class StateBridge:
    def __init__(self):
        self.card_index = CardIndex.get_instance()

    def game_to_state(self, game: Game) -> Optional[GameState]:
        if not game or not game.current_player:
            return None
        player = game.current_player
        opponent = player.opponent
        return GameState(
            hero=self._build_hero(player),
            mana=self._build_mana(player),
            board=self._build_board(player),
            hand=self._build_hand(player),
            opponent=self._build_opponent(opponent),
            turn_number=self._get_turn(game),
        )
```

### 5.5 `hs_analysis/watcher/decision_loop.py` (~150 行)

职责: 主循环，串联所有模块。

```python
class DecisionLoop:
    def __init__(self, log_path: str):
        self.watcher = LogWatcher(log_path)
        self.tracker = GameTracker()
        self.bridge = StateBridge()
        self.engine = RHEAEngine()
        self.presenter = DecisionPresenter()

    def on_turn_start(self):
        game = self.tracker.export_game()
        state = self.bridge.game_to_state(game)
        if state is None:
            return
        load_scores_into_hand(state)
        result = self.engine.search(state)
        self.presenter.display(result, state)

    def run(self):
        callbacks = WatcherCallbacks(
            on_new_line=self.tracker.feed_line,
            on_turn_start=self.on_turn_start,
            on_game_start=self.tracker.reset,
        )
        self.watcher.start(callbacks)
```

### 5.6 增强 `scripts/decision_presenter.py`

增加实时决策输出格式:
- 主推荐 + 信心度 + 评分
- 备选策略 (激进/稳健/价值)
- 风险提示 (AoE 脆弱性、超铺警告)
- 斩杀提示

## 6. Data Flow

```
1. Hearthstone 客户端写入 Power.log (事件→文件延迟 10-50ms)
2. LogWatcher 50ms 轮询读取新行
3. GameTracker.feed_line() 增量解析
4. 检测到 STEP=MAIN_ACTION → 触发 on_turn_start()
5. GameTracker.export_game() → hearthstone.entities.Game
6. StateBridge.game_to_state() → hs_analysis GameState
7. load_scores_into_hand(state) — 注入 V7/V8 评分
8. RHEAEngine.search(state) → SearchResult
9. DecisionPresenter.display(result, state) — 终端输出
```

总延迟预估: 60-150ms (日志) + 75ms (RHEA搜索) ≈ 150-250ms

## 7. Error Handling

| 错误场景 | 处理方式 |
|---------|---------|
| Power.log 不存在 | LogWatcher 静默等待，不崩溃 |
| 文件轮转 (新游戏) | 重置 LogParser + EntityTreeExporter |
| python-hslog 解析异常 | try/except 捕获，跳过该行，日志警告 |
| StateBridge 映射失败 | 返回 None，跳过本回合分析 |
| RHEA 超时 | 默认 time_limit 保护，返回当前最优 |
| Game 实体树不完整 | 优雅降级，缺少的字段用默认值 |

## 8. Testing Strategy

| 批次 | 场景 | 数量 |
|------|------|------|
| 集成-01 | LogWatcher 文件轮询 + 轮转检测 | 5 |
| 集成-02 | GameTracker 增量解析 + 导出 | 5 |
| 集成-03 | StateBridge Entity→GameState 映射 | 15 |
| 集成-04 | DecisionLoop 完整流程 (Power.log 回放) | 10 |
| 集成-05 | 边界情况 (空场面、满手牌、疲劳) | 5 |

测试方法: 录制 1-2 局完整对局的 Power.log，解析后验证 GameState 与实际游戏状态一致。

## 9. Open Questions

1. **python-hearthstone 版本**: 当前最新版是否支持 2026 年炉石补丁？需验证。
2. **对手手牌预测**: Power.log 不暴露对手手牌内容，只有数量。对手手牌需用 BayesianOpponent 推断。
3. **Enchantment 映射**: python-hslog 实体树中附魔信息的完整程度需验证，可能需要从卡牌文本补充解析。
4. **overlay 显示**: 终端输出是第一步；后续可考虑 HDT 插件方案在游戏内 overlay 显示。

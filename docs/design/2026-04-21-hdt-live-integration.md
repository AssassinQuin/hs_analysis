---
date: 2026-04-21
topic: "Phase 5: HDT Live Integration Implementation Plan"
depends_on: thoughts/shared/designs/2026-04-21-hdt-live-integration-design.md
estimated_effort: 15-21 hours
---

# Phase 5 Implementation Plan: HDT Live Integration

## Batch 1: 环境准备 + LogWatcher (Phase 5a-b)

**前置**: 无
**预估**: 4-6h

### Task 1.1: 安装依赖 + 验证 python-hslog

- `pip install hearthstone`
- 验证: 解析一段 Power.log 样本，确认 LogParser + EntityTreeExporter 可用
- 产出: pyproject.toml 添加 `hearthstone` 依赖
- **阻塞**: 需在 Windows 获取 Power.log 样本 (macOS 无此文件)
- 验证: `python -c "from hearthstone.hslog.parser import LogParser; print('OK')"`

### Task 1.2: 创建 `watcher/__init__.py`

- 空文件，包初始化

### Task 1.3: 实现 `watcher/log_watcher.py`

- `LogWatcher` 类:
  - `__init__(log_path, poll_interval=0.05)`
  - `start(callbacks: WatcherCallbacks)` — 主循环
  - `stop()` — 停止
  - `_check_rotation()` — 文件轮转检测
  - `_detect_turn_start(line)` — 检测 `STEP=MAIN_ACTION`
- `WatcherCallbacks` dataclass:
  - `on_new_line: Callable[[str], None]`
  - `on_turn_start: Callable[[], None]`
  - `on_game_start: Callable[[], None]`
  - `on_game_end: Callable[[], None]`
- 测试: 用临时文件模拟 Power.log 写入和轮转

---

## Batch 2: GameTracker + StateBridge (Phase 5c-d)

**前置**: Batch 1
**预估**: 7-10h

### Task 2.1: 实现 `watcher/game_tracker.py`

- `GameTracker` 类:
  - `feed_line(line)` — 增量解析
  - `export_game()` — 导出 Game 实体树
  - `reset()` — 重置 parser
  - `is_player_turn()` — 判断是否为玩家回合
  - `get_turn_number()` — 获取当前回合数
- 测试: 用 Power.log 样本验证实体树正确性

### Task 2.2: 实现 `watcher/state_bridge.py`

- `StateBridge` 类:
  - `game_to_state(game) → Optional[GameState]` — 核心映射
  - `_build_hero(player) → HeroState` — 英雄状态
  - `_build_mana(player) → ManaState` — 法力状态
  - `_build_board(player) → List[Minion]` — 友方场面
  - `_build_hand(player) → List[Card]` — 手牌 (card_id→CardIndex 查询)
  - `_build_opponent(opponent) → OpponentState` — 对手状态
  - `_entity_to_minion(entity, owner) → Minion` — 复用 HDTGameStateFactory 逻辑
  - `_entity_to_card(entity) → Card` — card_id→完整卡牌数据
  - `_get_class(hero) → str` — GameTag.CLASS → 职业字符串
  - `_get_weapon(player) → Optional[Weapon]` — 武器检测
- 关键: `_entity_to_card()` 需通过 `CardIndex` 用 card_id 查完整卡牌数据 (name, text, mechanics, rarity, race 等)
- 测试: 15 个映射用例，覆盖所有 GameTag→GameState 字段

### Task 2.3: 边界处理

- 空 Power.log (游戏未开始) → 返回 None
- 对手手牌不可见 → 只有 hand_count
- Enchantment 映射 → 从 CardIndex 补充
- 未揭示的卡牌 (SHOW_ENTITY 前的 HAND 实体) → 用 card_id 或占位符

---

## Batch 3: DecisionLoop + 输出 + 集成测试 (Phase 5e-g)

**前置**: Batch 2
**预估**: 4-5h

### Task 3.1: 实现 `watcher/decision_loop.py`

- `DecisionLoop` 类:
  - `__init__(log_path, engine_config=None)`
  - `run()` — 启动主循环
  - `stop()` — 停止
  - `_on_turn_start()` — 触发分析
  - `_on_new_line(line)` — 喂入 tracker
  - `_on_game_start()` — 重置 tracker
- 引擎配置: 支持传入自定义 RHEAEngine 参数

### Task 3.2: 增强 `scripts/decision_presenter.py`

- 实时决策输出格式:
  ```
  ═══ 回合 N — 法力 X/Y ═══
  推荐: [行动序列]
    信心度: XX% | 评分: +X.X

  备选策略:
    激进: [...] (评分: +X.X)
    稳健: [...] (评分: +X.X)

  ⚠️ 风险提示
  ```
- 支持彩色终端输出 (可选)

### Task 3.3: 集成测试

- 用录制的 Power.log 回放:
  - 验证 GameState 与实际游戏状态一致
  - 验证 RHEA 搜索不崩溃
  - 验证决策输出格式正确
- 边界: 空场面、满手牌、疲劳、满场面
- 产出: `tests/test_live_integration.py`

### Task 3.4: 入口脚本

- `scripts/run_live.py` — 启动实时分析
  - 参数: `--log-path` (默认 Windows 路径)
  - 参数: `--poll-interval` (默认 50ms)
  - 参数: `--engine-pop-size` (默认 50)

---

## 文件清单

| 新增文件 | 行数 | Batch |
|---------|------|-------|
| `hs_analysis/watcher/__init__.py` | ~5 | 1 |
| `hs_analysis/watcher/log_watcher.py` | ~100 | 1 |
| `hs_analysis/watcher/game_tracker.py` | ~150 | 2 |
| `hs_analysis/watcher/state_bridge.py` | ~200 | 2 |
| `hs_analysis/watcher/decision_loop.py` | ~150 | 3 |
| `tests/test_live_integration.py` | ~200 | 3 |
| `scripts/run_live.py` | ~40 | 3 |
| **总计** | **~845** | |

## 依赖关系

```
Batch 1 (LogWatcher)
    │
    ▼
Batch 2 (GameTracker + StateBridge)
    │
    ▼
Batch 3 (DecisionLoop + 输出 + 测试)
```

三个 Batch 串行执行，每个 Batch 内的 Tasks 可并行。

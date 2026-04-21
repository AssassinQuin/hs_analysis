---
version: 10.0
created: 2026-04-19
last_changed: 2026-04-21 (V11 engine implemented, Need-Aware Discover EV designed)
---

# Project State: hs_analysis

> Single source of truth for progress. Update after each significant change.

## Current Phase: V11 Engine Implemented — Need-Aware Discover EV Designed, HDT Planned

## ✅ DONE

### Data Infrastructure
- [x] Multi-source data pipeline (HearthstoneJSON + iyingdi + HSReplay)
- [x] 1015 standard cards in unified_standard.json (2026 Year of the Scarab)
- [x] CardIndex with O(1) multi-dimensional lookup
- [x] Card cleaner: race/mechanic/school normalization (56 keywords)
- [x] Card data model (dataclass) with full type hints
- [x] Wild format: 6174 cards fetched, 5209 wild-only after dedup

### Scoring Engines (Offline Pipeline)
- [x] V2: Power-law curve fitting (MAE 0.66, 70% improvement over V1)
- [x] V7: Data-driven scoring with HSReplay Rankings calibration
- [x] V8: 7 contextual correction factors (turn curve, type context, pool quality, etc.)
- [x] L6: Real-world composite scoring (V2 × (1-θ) + CPI × θ)

### Search & Decision (V9)
- [x] RHEA evolutionary search engine
- [x] Lethal checker (DFS-based)
- [x] Game state management (GameState, HeroState, Minion, ManaState)
- [x] Action normalization (including crossover fix)
- [x] Risk assessor (AoE vulnerability, overextension, secret threat)
- [x] Opponent simulator (greedy model)
- [x] Bayesian opponent modeling
- [x] Spell simulator (10 regex patterns)
- [x] Score provider with lazy loading + cache

### V10 Phase 1: Foundation Fixes ✅ (2026-04-19, commit `3d1a409`)
- [x] Lethal checker: charge minions now respect taunt
- [x] Windfury second attack: `has_attacked_once` flag
- [x] Overload parsing + application
- [x] Poisonous instant kill
- [x] Combo tracking: `cards_played_this_turn`
- [x] Fatigue damage: incrementing counter
- [x] Stealth break on attack
- [x] Freeze effect: `frozen_until_next_turn`
- **Design:** `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md`

### Complete Game Rules Reference ✅ (2026-04-19, commit `c76e902`)
- [x] 10章61节完整规则文档 (1017行)
- [x] Sources: wiki.gg, Blizzard patch notes, outof.games
- **Doc:** `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md`

### V10 State-Aware Scoring ✅ (2026-04-19, commit `a1b3221`)
- [x] **SIV module** (`evaluators/siv.py`): 8 state modifiers
  - Lethal awareness: `1 + (1-hp/30)² × 3.0`
  - Taunt constraint: `1 + 0.3 × count(enemy_taunts)`
  - Tempo window: curve matching penalty
  - Hand position: Outcast/Shatter position bonus
  - Trigger probability: Brann/Rivendare/aura multipliers
  - Race synergy: same-race count × 0.1
  - Progress tracker: Imbue/Herald/Quest threshold jumps
  - Counter awareness: freeze/secret/AoE threat adjustments
- [x] **BSV module** (`evaluators/bsv.py`): Non-linear 3-axis fusion
  - Tempo axis: Σ SIV(friendly) - Σ SIV(enemy) + mana efficiency
  - Value axis: Σ SIV(hand) + card advantage + resource generation
  - Survival axis: hero safety - threats - lethal exposure
  - Softmax fusion with temperature=0.5
  - Phase weights: early(1.3,0.7,0.5) / mid(1.0,1.0,1.0) / late(0.7,1.2,1.5)
  - Lethal override: BSV = 999.0 when lethal possible
- [x] **Keyword interactions** (`scorers/keyword_interactions.py`): 8 rule-derived pairs
- [x] **2026 mechanic base values** (`scorers/mechanic_base_values.py`): 9 formulas
- [x] **Composite integration** (`evaluators/composite.py`): V10_ENABLED flag + evaluate_v10()
- [x] **260 new tests**, 493 total, zero regressions
- **Design:** `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md`
- **Design (impl):** `thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-19-v10-scoring-implementation.md`

### V10 Phase 2: Enchantment Framework + Keyword Mechanics ✅ (2026-04-20, commit `f2dca83`)
- [x] **enchantment.py** — Enchantment dataclass, apply/remove/tick, stat computation helpers
- [x] **trigger_system.py** — TriggerDispatcher with 8 events, effect string protocol (`damage:random_enemy:N`)
- [x] **battlecry_dispatcher.py** — battlecry dispatch with greedy target selection, 10+ effect types
- [x] **deathrattle.py** — `resolve_deaths()` with board-ordered queue, cascade (max 5), text parsing
- [x] **aura_engine.py** — `recompute_auras()` with 7 aura sources (EN/CN registry), target filters (other_friendly, adjacent, murloc, pirate)
- [x] **discover.py** — pool generation from unified_standard.json, Chinese text constraint parsing, best-of-3 heuristic
- [x] **location.py** — Location dataclass, activate/tick cooldowns, effect resolution
- [x] **game_state.py** — added `locations` field, Minion already had `enchantments` list
- [x] **rhea_engine.py** — 4 integration points (PLAY MINION, ATTACK, SPELL, END_TURN) + ACTIVATE_LOCATION action
- [x] **pyproject.toml** — added `hs_analysis/search` to testpaths
- [x] **341 new tests** across 6 test modules, 615 total passing
- **Plan:** `thoughts/shared/plans/2026-04-20-v10-phase2.md`

### V10 Phase 3: 2026 Modern Mechanics ✅ (2026-04-20, commits `bb11feb` + `14384de` + `ffbe350`)
- [x] **imbue.py** — Hero power upgrade system with 11 class-specific upgrade paths, scaling by imbue_level
- [x] **outcast.py** — Hand position detection (leftmost/rightmost), Chinese text bonus parsing (draw, cost reduction, buff)
- [x] **colossal.py** — Colossal+N appendage summoning, per-class appendage definitions, herald upgrade scaling
- [x] **herald.py** — Herald counter + soldier summoning, per-class soldier definitions, milestone tracking
- [x] **quest.py** — QuestState tracking, progress by action type, reward dispatch on completion, constraint parsing
- [x] **rewind.py** — 2-branch evaluation helper, rewind card detection
- [x] **game_state.py** — added imbue_level (HeroState), herald_count, last_turn_races, last_turn_schools, active_quests
- [x] **rhea_engine.py** — Kindred snapshot in END_TURN, imbue dispatch, outcast check/apply, colossal+herald in PLAY MINION, quest activation+tracking
- [x] **Skipped** Kindred + Dark Gift (not in current card pool — YAGNI)
- [x] **~63 new tests** across 7 test modules

### V10 Feedback: Mechanic Gaps + Discover Enhancements ✅ (2026-04-20, 4 commits)
- [x] **Batch 1: Kindred + Corpse** (commit `8a288f9`)
  - `kindred.py` — 延系 mechanic detection via text regex, race/school intersection check
  - `corpse.py` — DK corpse resource (gain/spend/double-gen for 法瑞克), optional effect system
  - `game_state.py` — added `corpses`, `kindred_double_next`, `last_played_card` fields
  - `rhea_engine.py` — kindred dispatch after colossal, corpse gain on death, corpse effects for DK
  - 51 new tests
- [x] **Batch 2: Rune + Dark Gift** (commit `146133a`)
  - `rune.py` — DK rune mapping (spellSchool → rune type), discover filtering
  - `dark_gift.py` — 10 predefined enchantments, discover modifier, pool filtering
  - `discover.py` — integrated rune filtering + dark gift enchantment on discover options
  - 38 new tests
- [x] **Batch 3: Exhaustive Target Selection** (commit `c822950`)
  - `battlecry_dispatcher.py` — clone→apply→evaluate loop, removal bonus eval, attack-based tiebreaker
  - `_quick_eval()` — removal bonus (+10/kill), lethal detection (1000), skips dead minions
  - `_pick_damage_target(amount)` — uses actual damage amount in probe for accurate kill detection
  - 7 new tests
- [x] **Batch 4: Wild Card Pool** (commit `72cec1a`)
  - `discover.py` — `_WILD_CACHE` + `_load_wild_cards()` for unified_wild.json (5209 cards)
  - "来自过去" detection triggers wild pool in `resolve_discover()`
  - Case-insensitive class filter, Chinese type normalization (装备→WEAPON)
  - 11 new tests
- **Design:** `thoughts/shared/designs/2026-04-20-v10-feedback-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-20-v10-feedback.md`

### Retrieval Optimization ✅ (2026-04-20)
- [x] **CardIndex 增强** (`data/card_index.py`)
  - `_dbf_frozensets` 预构建索引: attribute:key → frozenset of dbfIds
  - `_pool_cache` LRU 缓存 (max 256 entries)
  - `get_pool()` 重写为 dbfId frozenset 交集 + LRU 命中 (cold 2.2µs → warm 0.8µs, 2.9x)
  - `discover_pool()` 新增: 排除 HERO/LOCATION 类型
  - `_index_card()`: cardClass 标准化大写 (修复 wild JSON Title Case)
- [x] **ScoreProvider 全局缓存** (`utils/score_provider.py`)
  - `_PROVIDERS` 模块级 dict 缓存，`_get_provider()` 工厂复用已有实例
  - `load_scores_into_hand()` 不再每次 new ScoreProvider (cache hit 0.2µs)
- [x] **discover.py 复用 CardIndex** (`search/discover.py`)
  - 删除 `_CARD_CACHE`, `_WILD_CACHE`, `_load_cards()`, `_load_wild_cards()`
  - `generate_discover_pool()` delegate 到 `CardIndex.discover_pool()`
  - 路径统一使用 config.DATA_DIR，消除不一致
- [x] **性能基准**: 卡牌数据仅加载一次 (6224 cards)，内存减少 3-4x
- [x] **test_wild_discover.py** 重写适配新架构
- **Design:** `thoughts/shared/designs/2026-04-20-retrieval-optimization-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-20-retrieval-optimization.md`

### Test Coverage
- [x] **~795 tests passing** (as of 2026-04-20, 2 known flaky RHEA stochastic tests)
- [x] Card data tests: 51+35+6 = 92
- [x] V8 contextual scorer: 16
- [x] V9 search engine + HDT batches: 150+
- [x] V10 Phase 1 mechanic tests: 20
- [x] V10 scoring (SIV+BSV+interactions+mechanics+integration): 260
- [x] V10 Phase 2 (enchant+trigger+battlecry+deathrattle+aura+discover+location): 341
- [x] V10 Phase 3 (state expansion+imbue+outcast+colossal+herald+quest+rewind): ~63
- [x] V10 Feedback (kindred+corpse+rune+dark_gift+target_selection+wild_discover): 107

### V11 Next-Gen Engine ✅ (2026-04-21, 22 files in engine_v11/)
- [x] **MechanicRegistry** — 注册表模式，15 个 Handler 包装 V10 逻辑
- [x] **FactorGraph Evaluator** — 7 个独立因子 (board_control, lethal_threat, tempo, value, survival, resource_efficiency, discover_ev)
- [x] **Hierarchical Search** — StrategicMode(LETHAL/DEFENSIVE/DEVELOPMENT) → TacticalPlanner(BFS combo) → AttackPlanner(deterministic greedy)
- [x] **ActionPruner** — 领域知识剪枝 (divine shield waste, bad trades, full board)
- [x] **Probability Models** — DrawModel, DiscoverModel, RNGModel
- [x] **DecisionPipeline** — 串联所有层，输出 Decision + FactorScores + confidence
- [x] **37 V11 tests passing**, 783/784 total (1 pre-existing flaky)
- **Design:** `thoughts/shared/designs/2026-04-21-next-gen-engine-architecture-design.md`

### Architecture & Research Documentation
- [x] 9 design documents in `thoughts/shared/designs/`
- [x] 6 implementation plans in `thoughts/shared/plans/`
- [x] PROGRESS.md — complete development log
- [x] PROJECT_STATE.md — progress tracker (this file)
- [x] DECISIONS.md — 27 architectural decisions (D001-D027)
- [x] PROJECT_CHARTER.md — immutable goals & constraints

## 🔄 WIP

(none currently)

## ⏳ TODO (by priority)

### P0: V11 Polish & A/B Validation
- [ ] V11 vs V10 A/B 对比测试（场景级别）
- [ ] FactorGraph 权重调优（phase-adaptive weights）
- [ ] 性能基准测试（100ms budget）

### P0: V11 Need-Aware Discover EV — 发现决策质量升级

**设计完成，待实现。** 替代 V11 的静态 SIV 评分发现模型：

1. **NeedAnalyzer** — 分析场面需求 (survival/removal/tempo/damage/draw)
2. **PoolSimulator** — 对池中每张牌完整模拟打出 + FactorGraph 评估
3. **OrderStatistics** — 精确计算 3 选 1 期望最大值
4. **CardClassifier** — 牌面效果分类
5. **DiscoverModelV2** — 整合以上，输出 EV + TOP 选项 + 需求分布
6. **TacticalPlanner 扩展** — 发现牌 EV 参与出牌组合比较

- [ ] Batch 1: NeedAnalyzer + CardClassifier (2h)
- [ ] Batch 2: PoolSimulator + OrderStatistics (2h)
- [ ] Batch 3: DiscoverModelV2 + TacticalPlanner 集成 (2-3h)
- [ ] Batch 4: 测试 + 文档更新 (1h)
- **Design:** `thoughts/shared/designs/2026-04-21-need-aware-discover-ev-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-21-need-aware-discover-ev.md`
- **Estimated effort:** 6-8 hours
- **Key insight:** 发现是"嵌套决策"，EV = E[max(3 random picks)] × 场面模拟评分

### P0: HDT Live Integration (Phase 5) — 实时辅助决策
- [ ] Phase 5a: 环境准备 — 安装 python-hearthstone, 获取 Power.log 样本
- [ ] Phase 5b: `watcher/log_watcher.py` — 文件轮询(50ms) + 轮转检测 + 回合触发
- [ ] Phase 5c: `watcher/game_tracker.py` — 封装 python-hslog LogParser + EntityTreeExporter
- [ ] Phase 5d: `watcher/state_bridge.py` — hearthstone.entities.Game → GameState 映射
- [ ] Phase 5e: `watcher/decision_loop.py` — 主循环串联 LogWatcher→GameTracker→StateBridge→RHEAEngine
- [ ] Phase 5f: 决策输出展示 — 终端/overlay 实时展示推荐行动 + 备选策略
- [ ] Phase 5g: 集成测试 — 用录制 Power.log 回放验证完整流程
- **Design:** `thoughts/shared/designs/2026-04-21-hdt-live-integration-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-21-hdt-live-integration.md`
- **Estimated effort:** 15-21 hours
- **Key dependency:** python-hearthstone (pip install hearthstone), Windows Power.log
- **Risk:** macOS 不生成 Power.log，开发调试需 Windows 环境或录制日志
- **Note:** 建议先完成 V11 再接入 HDT，否则实时辅助决策质量不足

### P1: Polish & Calibration
- [ ] Scoring calibration (temperature, LETHAL_SCALE, phase weights)
- [ ] Performance benchmarking (75ms RHEA target)
- [ ] Wild format scoring support (5209 cards)
- [ ] Risk assessor: additional class AoE thresholds
- [ ] Opponent simulator: consider hand size, hero power, divine shield

### P2: Future Mechanics (when cards enter standard pool)
- [ ] Shatter — card split/merge in hand

### P3: Full Rewind Integration
- [ ] Wire rewind.py into _evaluate_chromosome for true 2-branch evaluation
- [ ] Performance impact analysis (2× evaluation cost for rewind cards)

## 🚫 BLOCKED
(none currently)

## Architecture Decisions
See `thoughts/DECISIONS.md` for full details (D001-D027).

## Data Inventory

| File | Description | Size |
|------|-------------|------|
| hs_cards/unified_standard.json | Cleaned standard pool | 1015 cards |
| hs_cards/unified_wild.json | Cleaned wild-only pool | 5209 cards |
| hs_cards/v7_scoring_report.json | V7 scores | all standard |
| hs_cards/v2_scoring_report.json | V2 scores | all standard |
| hs_cards/l6_scoring_report.json | L6 scores | all standard |
| hs_cards/pool_quality_report.json | Pool quality metrics | 3 type pools |
| hs_cards/card_turn_data.json | Avg turn data | from HSReplay |
| hs_cards/rewind_delta_report.json | V7 rewind deltas | generated |
| hs_cards/hsreplay_cache.db | HSReplay SQLite cache | cached |

## Active Design Docs
- `thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md` ⭐ (engine, Phase 2+3)
- `thoughts/shared/designs/2026-04-19-v10-stateful-scoring-design.md` ⭐ (scoring framework)
- `thoughts/shared/designs/2026-04-19-v10-scoring-implementation-design.md` ⭐ (scoring impl)
- `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md` ⭐ (rules reference)

## Next Actions
1. **V11 Discover EV Batch 1: NeedAnalyzer + CardClassifier** — 场面需求分析 + 牌面分类
2. **V11 Discover EV Batch 2: PoolSimulator + OrderStatistics** — 单牌模拟 + 期望值计算
3. **V11 Discover EV Batch 3: DiscoverModelV2 + TacticalPlanner** — 整合 + 搜索集成
4. **V11 Polish & A/B Validation** — 与 V10 对比验证决策质量
5. **Phase 5: HDT Live Integration** — V11 验证后再接入实时流

---
version: 13.0
created: 2026-04-19
last_changed: 2026-04-22 (Phase 7: Bayesian opponent + spell target simulation)
---

# Project State: hs_analysis

> Single source of truth for progress. Update after each significant change.

## Current Phase: Phase 7 In Progress — 2/5 Tasks Done, 3 Remaining

## ✅ DONE

### Data Infrastructure
- [x] Multi-source data pipeline (HearthstoneJSON + iyingdi + HSReplay)
- [x] 1015 standard cards in unified_standard.json (2026 Year of the Scarab)
- [x] CardIndex with O(1) multi-dimensional lookup
- [x] Card cleaner: race/mechanic/school normalization (56 keywords)
- [x] Card data model (dataclass) with full type hints
- [x] Wild format: 6174 cards fetched, 5209 wild-only after dedup
- [x] Data source unified to cardData/240397/ (HSJSON API only)

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

### Complete Game Rules Reference ✅ (2026-04-19, commit `c76e902`)
- [x] 10章61节完整规则文档 (1017行)
- **Doc:** `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md`

### V10 State-Aware Scoring ✅ (2026-04-19, commit `a1b3221`)
- [x] **SIV module** — 8 state modifiers (lethal/taunt/tempo/position/trigger/synergy/progress/counter)
- [x] **BSV module** — Non-linear 3-axis fusion (tempo/value/survival, softmax)
- [x] **Keyword interactions** — 8 rule-derived pairs
- [x] **2026 mechanic base values** — 9 formulas
- [x] **260 new tests**, 493 total, zero regressions

### V10 Phase 2: Enchantment Framework + Keyword Mechanics ✅ (2026-04-20, commit `f2dca83`)
- [x] Enchantment + TriggerDispatcher + BattlecryDispatcher + Deathrattle + AuraEngine + Discover + Location
- [x] 341 new tests, 615 total passing

### V10 Phase 3: 2026 Modern Mechanics ✅ (2026-04-20, 3 commits)
- [x] Imbue + Outcast + Colossal + Herald + Quest + Rewind
- [x] ~63 new tests

### V10 Feedback: Mechanic Gaps + Discover Enhancements ✅ (2026-04-20, 4 commits)
- [x] Kindred + Corpse + Rune + Dark Gift + Target Selection + Wild Discover
- [x] 107 new tests

### Retrieval Optimization ✅ (2026-04-20)
- [x] CardIndex frozenset + LRU cache (2.9x speedup)
- [x] ScoreProvider global cache
- [x] discover.py reuses CardIndex

### V11 Next-Gen Engine ✅ (2026-04-21, 22 files in engine/)
- [x] **MechanicRegistry** — 15 Handlers wrapping V10 logic
- [x] **FactorGraph Evaluator** — 7 factors (board_control, lethal_threat, tempo, value, survival, resource_efficiency, discover_ev)
- [x] **Hierarchical Search** — StrategicMode(LETHAL/DEFENSIVE/DEVELOPMENT) → TacticalPlanner(BFS combo) → AttackPlanner(greedy)
- [x] **ActionPruner** — domain knowledge pruning
- [x] **Probability Models** — DrawModel, DiscoverModel, RNGModel
- [x] **DecisionPipeline** — Decision + FactorScores + confidence
- [x] **37 V11 tests passing**, ~795 total
- **Design:** `thoughts/shared/designs/2026-04-21-next-gen-engine-architecture-design.md`

### V12 Power.log Gap Analysis ✅ (2026-04-22)
- [x] **Power.log 真实对局分析** — 23回合对局 (死亡阴影瓦莉拉 vs 卡德加)
- [x] **10个复杂场面决策场景提取** — 含场面状态、实际决策、引擎行为分析
- [x] **20个引擎不足识别** — 5架构级 + 5因子 + 5搜索 + 5数据模型
- [x] **V12 详细设计文档** — 1093行, 5个Phase改进方案, 含代码示例
- [x] **V12 执行计划** — checkbox 任务清单
- [x] **文档清理** — 删除11个过期V9/V10文档, 保留13个重要文档
- **Design:** `thoughts/shared/designs/2026-04-22-v12-powerlog-driven-engine-gaps-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-22-v12-powerlog-driven-engine-plan.md`

### Phase 6.5: Opponent Card Intelligence ✅ (2026-04-22)
- [x] **6 bug fixes** — CT_LOCATION/ZONE_GRAVEYARD constants, set_controllers timing, opponent card tracking, zone filtering
- [x] **get_opp_card_breakdown()** — categorized opponent card intelligence (deck/generated/hand/type/school/race)
- [x] **TurnDecision extension** — opp_deck_cards_played, opp_generated_cards_played, opp_card_type_counts
- [x] **Categorized logging** — 对手牌库牌/衍生牌/出牌类型 instead of flat list
- [x] **JSON output** — new fields in summary JSON
- **Files**: analysis/watcher/global_tracker.py, analysis/watcher/packet_replayer.py

### Phase 7: Opponent Intelligence + Effect Simulation 🔄 (2026-04-22)
- [x] **Task 1: 对手手牌推理** — BayesianOpponentModel 集成 (hsdb bridge + deck_codes DB + tracker feed + decision output)
- [x] **Task 2: 卡牌效果模拟层** — tactical spell target enumeration + resolve_effects target passthrough
- [ ] **Task 3: 对手奥秘概率模型** — 研究完成（4职业74张奥秘），待编码
- [ ] **Task 4: 非收藏卡中文名** — python-hearthstone XML fallback 已覆盖大部分
- [ ] **Task 5: 对手卡组类型检测** — Bayesian lock 已部分覆盖
- **Files**: hsdb.py, fetch_hsreplay.py, global_tracker.py, packet_replayer.py, tactical.py, spell_simulator.py, rhea_engine.py
- **Stats**: 7 files, +451/-39 lines, 676 tests passing

### Test Coverage
- [x] **~795 tests passing** (as of 2026-04-21)
- [x] V10/V11 test suites fully passing
- [x] 1 known flaky RHEA stochastic test (pre-existing)

### Architecture & Research Documentation
- [x] 5 active design documents + 1 new V12 design
- [x] 5 active plans + 1 new V12 plan
- [x] PROJECT_CHARTER.md — immutable goals & constraints
- [x] PROJECT_STATE.md — progress tracker (this file)
- [x] DECISIONS.md — 30 architectural decisions (D001-D030)

## 🔄 WIP

(none currently)

## ⏳ TODO (by priority)

### ~~P0: 对手手牌推理~~ ✅ DONE (Phase 7 Task 1)
- [x] card_id→dbfId bridge in hsdb.py
- [x] build_archetype_db_from_deck_codes() in fetch_hsreplay.py
- [x] BayesianOpponentModel integrated in GlobalTracker
- [x] Archetype name/confidence in TurnDecision + logs + JSON

### P0: V12 Phase 1 — 卡牌效果模拟层 (致命缺陷)
- [ ] Task 1.1: BattlecryDispatcher — 战吼文本解析 + 效果分发 + 分支展开
- [ ] Task 1.2: SpellTargetResolver — 法术目标枚举
- [ ] Task 1.3: HeroCardHandler — 英雄牌替换处理 (HERO_REPLACE action)
- [ ] Task 1.4: ManaModifier — 法力修改器栈 (伺机待发/幸运币)
- [ ] Task 1.5: rhea_engine.py apply_action 扩展 (新 action types)
- **Design:** `thoughts/shared/designs/2026-04-22-v12-powerlog-driven-engine-gaps-design.md` §Phase 1
- **Estimated effort:** 8-12 hours

### P0: V12 Phase 2 — 统一行动序列 (架构缺陷)
- [ ] Task 2.1: UnifiedTacticalPlanner — 出牌+攻击穿插枚举 (beam width=5)
- [ ] Task 2.2: ActionPruner 扩展 — 新剪枝规则
- **Estimated effort:** 4-6 hours

### P1: V12 Phase 3 — 因子评估增强
- [ ] Task 3.1: BoardControlFactor 关键词组合价值 (嘲讽×1.3, 圣盾, 风怒×1.5 等)
- [ ] Task 3.2: LethalThreatFactor 英雄技能+手牌法术伤害
- [ ] Task 3.3: ValueFactor 牌质感知 (SIV加权)
- [ ] Task 3.4: SurvivalFactor 自适应阈值
- **Estimated effort:** 4-6 hours

### P1: V12 Phase 4 — 数据模型扩展
- [ ] Task 4.1: Minion 字段扩展 (magnetic/invoke/corrupt/spellburst/outcast/race/spell_school)
- [ ] Task 4.2: Action 扩展 (discover_choice_index/sub_option)
- **Estimated effort:** 2-3 hours

### P2: V12 Phase 5 — AttackPlanner 升级
- [ ] Task 5.1: Beam Search 替代纯贪心 (beam_width=3)
- [ ] Task 5.2: 多回合致命预估 (_two_turn_lethal_probability)
- **Estimated effort:** 3-4 hours

### P1: HDT Live Integration (Phase 5)
- [ ] Phase 5a-g: 完整 HDT 实时集成管线
- **Design:** `thoughts/shared/designs/2026-04-21-hdt-live-integration-design.md`
- **Plan:** `thoughts/shared/plans/2026-04-21-hdt-live-integration.md`
- **Dependency:** V12 Phase 1-2 完成后

### P2: Polish & Calibration
- [ ] V12 vs V11 A/B 对比测试
- [ ] FactorGraph 权重调优
- [ ] 性能基准测试 (<150ms budget)
- [ ] Wild format scoring support

## 🚫 BLOCKED
(none currently)

## Architecture Decisions
See `thoughts/DECISIONS.md` for full details (D001-D030).

## Data Inventory

| File | Description | Size |
|------|-------------|------|
| cardData/240397/unified_standard.json | Cleaned standard pool | 1015 cards |
| cardData/240397/unified_wild.json | Cleaned wild-only pool | 5209 cards |
| cardData/240397/zhCN.json | Raw Chinese card data | from HSJSON |
| cardData/240397/enUS.json | Raw English card data | from HSJSON |
| Power.log | Sample game log (23 turns) | 57606 lines |

## Active Design Docs
- `thoughts/shared/designs/2026-04-22-v12-powerlog-driven-engine-gaps-design.md` ⭐ (V12 design)
- `thoughts/shared/designs/2026-04-21-next-gen-engine-architecture-design.md` (V11 reference)
- `thoughts/shared/designs/2026-04-21-hdt-live-integration-design.md` (HDT integration)
- `thoughts/shared/designs/2026-04-21-need-aware-discover-ev-design.md` (Discover EV reference)
- `thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md` ⭐ (rules reference)

## Active Plans
- `thoughts/shared/plans/2026-04-22-v12-powerlog-driven-engine-plan.md` ⭐ (V12 execution)
- `thoughts/shared/plans/2026-04-21-hdt-live-integration.md` (HDT plan)
- `thoughts/shared/plans/2026-04-21-need-aware-discover-ev.md` (Discover EV plan)
- `thoughts/shared/plans/2026-04-20-retrieval-optimization.md` (retrieval opt.)

## Next Actions
1. **Task 3: 对手奥秘概率模型** — 基于职业+已触发排除推断未知奥秘
2. **V12 Phase 1: SpellTargetResolver** — 法术目标枚举
3. **V12 Phase 1: HeroCardHandler** — 英雄牌替换
4. **V12 Phase 1: ManaModifier** — 法力修改器栈
5. **Task 5: 对手卡组类型检测** — 快攻/控制/组合分类
6. **Task 4: 非收藏卡中文名** — 验证 XML fallback 覆盖率

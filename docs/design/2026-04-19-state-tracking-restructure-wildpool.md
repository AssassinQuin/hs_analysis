---
date: 2026-04-19
topic: "State Tracking + Package Cleanup + Wild Pool"
status: active
depends_on: []
estimated_effort: "3 phases, ~45 min"
---

# Implementation Plan: State Tracking + Restructure + Wild Pool

## Phase 1: Package Restructure Cleanup [Priority: HIGH]

### Micro-task 1.1: Verify migrated scripts
- Check each script in `scripts/` against its counterpart in `hs_analysis/`
- Confirm all functionality is available in the package
- List any scripts that are NOT yet migrated (keep these)

### Micro-task 1.2: Delete migrated scripts
- Remove scripts whose functionality exists in `hs_analysis/` package
- Keep `scripts/run_*.py` entry points (these are thin CLI wrappers)
- Keep `scripts/test_*.py` for now (test migration is separate)

### Micro-task 1.3: Remove __pycache__
- `find . -type d -name __pycache__ -exec rm -rf {} +`
- Verify no breakage

### Micro-task 1.4: Archive old docs
- Move completed/superseded designs from `thoughts/shared/designs/` to `thoughts/archive/designs/`
  - KEEP active: `2026-04-19-project-state-tracking-design.md`
  - Archive: `2026-04-19-card-index-and-cleanup-design.md`, `2026-04-19-package-restructure-design.md`, `2026-04-19-v9-decision-engine-v2-design.md` (these have corresponding plans or are about to be executed)
  - Actually: KEEP all 3 active designs (they reference ongoing work)
  - Only archive truly superseded ones
- Move completed plans from `thoughts/shared/plans/` to `thoughts/archive/plans/`
  - KEEP active: `2026-04-19-v9-decision-engine-v2.md`
  - Archive older plans
- Move session ledgers from `thoughts/archive/ledgers/` (already archived)

### Micro-task 1.5: Run tests
- `cd /Users/ganjie/code/personal/hs_analysis && python -m pytest tests/ scripts/ -v`
- Verify 139/140 passing (the 1 dragon pool failure is expected, will fix in Phase 3)

### Micro-task 1.6: Git commit
- `git add -A && git commit -m "chore: cleanup migrated scripts, remove __pycache__, archive old docs"`

---

## Phase 2: Create Project State Tracking Files [Priority: HIGH]

### Micro-task 2.1: Create PROJECT_CHARTER.md
Create `thoughts/PROJECT_CHARTER.md` with:

```markdown
---
version: 1.0
created: 2026-04-19
last_changed: 2026-04-19
---

# Project Charter: hs_analysis

## Mission
炉石传说卡牌数值分析工具包 — 用数学模型量化卡牌价值，支持游戏内实时决策建议。

## Core Requirements

### R1: 数据管线
- 从 iyingdi + HearthstoneJSON + HSReplay 多源获取卡牌数据
- 构建统一数据库，支持标准/狂野两种格式
- O(1) 多维度索引（mechanic/type/class/race/school/cost/format）
- **验收标准**: 1000+ 卡牌入库，索引查询 < 1ms

### R2: 多版本评分引擎
- V2: 基础幂律曲线 + 关键词分层 (L1-L5)
- V7: 扩展关键词 + 种族/学派协同 + HSReplay Rankings 校准
- V8: 7个上下文修正因子（回合曲线、类型上下文、池质量等）
- L6: 真实世界综合评分
- **验收标准**: 每个版本生成评分报告，MAE 持续降低

### R3: RHEA 进化搜索引擎
- 基于进化算法搜索最优出牌方案
- 自适应参数、阶段检测、时间预算控制
- **验收标准**: 75ms 内返回候选方案

### R4: V9 层叠决策管线
- 致命检测 → 增强 RHEA → 对手模拟 → 风险评估 → 选择
- 贝叶斯对手建模
- **验收标准**: 层叠管线完整可用，每层有独立测试

### R5: 测试覆盖
- 每个核心模块有独立测试文件
- **验收标准**: 140+ 测试通过

## Technical Constraints
- Python 3.10+ (type hints, dataclasses)
- 依赖: NumPy, SciPy, openpyxl (仅3个)
- 无 GUI，无实时游戏注入（仅分析工具包）
- 数据文件 JSON 格式，SQLite 仅用于缓存
- 所有路径通过 config.py 集中管理

## Out of Scope
- 实时游戏客户端集成（HDT 插件是 P2 远期目标）
- GUI / Web 界面
- 非 Python 语言实现
- 多人游戏支持
- 商业化 / 发行

## Change Log
| Date | Version | Change | Reason |
|------|---------|--------|--------|
| 2026-04-19 | 1.0 | Initial charter | Project kickoff |
```

### Micro-task 2.2: Create PROJECT_STATE.md
Create `thoughts/PROJECT_STATE.md` with the current accurate state. Source ground truth from PROGRESS.md (not state.json).

Key content:
- Current phase: V9 Decision Engine + Data Completion
- [DONE] items with metrics
- [WIP] items
- [TODO] items ordered by priority
- [BLOCKED] items (none currently)
- Data inventory (list all files in hs_cards/)
- Active designs section

### Micro-task 2.3: Create DECISIONS.md
Create `thoughts/DECISIONS.md` with at minimum 6 key decisions extracted from design docs and session history.

### Micro-task 2.4: Update .opencode/agent.md
Add the new bootstrap sequence:
1. Read `thoughts/PROJECT_CHARTER.md`
2. Read `thoughts/PROJECT_STATE.md`
3. Read `thoughts/DECISIONS.md` (last 5 entries)
4. State alignment declaration

### Micro-task 2.5: Git commit
- `git add -A && git commit -m "feat: add PROJECT_CHARTER, PROJECT_STATE, DECISIONS for LLM session continuity"`

---

## Phase 3: iyingdi Wild Pool Data [Priority: MEDIUM]

### Micro-task 3.1: Enhance fetch_wild.py
- Add `wild=1` parameter support (currently fetches all by omitting `standard`)
- Ensure per-card `standard` and `wild` flags are captured
- Test with a single page first to verify API response

### Micro-task 3.2: Run wild card fetch
- Execute the enhanced fetcher
- Verify data lands in `hs_cards/iyingdi_all_raw.json` and `hs_cards/iyingdi_all_normalized.json`

### Micro-task 3.3: Build wild database
- Run `build_wild_db.py` to deduplicate against standard pool
- Verify `hs_cards/unified_wild.json` (or equivalent) is created

### Micro-task 3.4: Generate race-based pool quality data
- The current `pool_quality_report.json` only has 3 type-based pools
- Generate pools for: DRAGON, DEMON, BEAST, MURLOC, MECHANICAL, ELEMENTAL, PIRATE, TOTEM, UNDEAD
- The pool quality generator needs to look for English race names (DRAGON, BEAST) not Chinese (龙, 野兽)

### Micro-task 3.5: Fix failing test
- `test_dragon_pool_avg_v7` should pass once dragon pool data exists
- Run: `python -m pytest scripts/test_pool_quality_generator.py -v`

### Micro-task 3.6: Run full test suite
- `python -m pytest tests/ scripts/ -v`
- Target: 140/140 passing

### Micro-task 3.7: Update PROJECT_STATE.md
- Mark wild pool task as [DONE]
- Update data inventory with new files
- Update next actions

### Micro-task 3.8: Git commit
- `git add -A && git commit -m "feat: wild format card fetch with wild=1, race-based pool quality, fix dragon test"`

---

## Dependency Graph

```
Phase 1 (cleanup) ──→ Phase 2 (state tracking) ──→ Phase 3 (wild pool)
                                                       │
                                                       └──→ Update STATE
```

Phase 1 and Phase 2 are independent in terms of code, but doing cleanup first means the state tracking reflects the clean structure.

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Deleting a script that wasn't actually migrated | Micro-task 1.1 verifies first. If uncertain, KEEP the script |
| iyingdi API rate limiting or blocking | Use 0.3s delay between pages (existing pattern). Test with 1 page first |
| `wild=1` parameter not behaving as expected | Compare response with `fetch_wild.py` output. Fall back to omitting `standard` |
| Race names mismatch in pool generator | Already identified: generator looks for Chinese, data has English. Fix the lookup |

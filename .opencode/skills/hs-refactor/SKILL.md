---
name: hs-refactor
description: >
  Project-level code refactoring skill for hs_analysis (Hearthstone AI analysis engine).
  Systematic 4-phase workflow: code archaeology → refactoring discovery → over-engineering pruning → implementation.
  Use when: user asks to "refactor", "clean up", "optimize", "restructure", "improve code quality",
  "eliminate duplication", "modernize", "review architecture", or mentions specific code smells.
  Also triggers on: "代码重构", "优化代码", "清理代码", "目录结构优化", "消除重复", "设计模式".
---

# HS Refactor — 4-Phase Code Refactoring Workflow

Systematic refactoring for the hs_analysis project. Each phase stores findings in memory for cross-session continuity.

## Workflow Overview

```
Pre-Flight → Phase 1 → Gate → Phase 2 → Gate → Phase 3 → Gate → Phase 4 → Final Verify
(session)     (research)       (design)        (prune)         (implement)
```

**Mandatory:**
- Memory storage at every phase (see [references/memory-conventions.md](references/memory-conventions.md))
- Tests must pass after each Phase 4 step
- Max 3 sub-agents simultaneously (see [references/sub-agent-patterns.md](references/sub-agent-patterns.md))

**Framework-First Rule:** Any file exceeding 500 lines MUST be built in two steps:
1. Generate skeleton (class defs, method signatures, docstrings, imports)
2. Fill implementation content
This ensures structural correctness before detail work.

---

## Pre-Flight: Session Resume

**Before starting any phase**, check for prior work:

```
1. memory_search(tags=["refactor"], limit=10) → what was done before?
2. memory_search(query="refactor phase-4 done", tags=["refactor", "phase-4"]) → completed work
3. Read references/completed-refactorings.md → avoid re-discovery
4. Read references/project-defects.md → known issues to reference
```

**Decision:** If a prior session completed Phase N, resume at Phase N+1. If Phase 4 was partially done, check which todo items remain and continue from there.

---

## Phase 1: Code Archaeology

**Goal:** Build a complete map of the project — what exists, what's connected, what's dead.

### Steps

1. **Retrieve prior context** — `memory_search(query="refactor phase-1", tags=["refactor", "phase-1"])`
2. **Map directory structure** — tree with line counts, identify module boundaries
3. **Build import dependency graph** — for each `.py`, trace inbound/outbound imports
4. **Run the analysis checklist** — [references/analysis-checklist.md](references/analysis-checklist.md)
5. **Store findings** — Each finding: `memory_store` with tags `refactor,phase-1,<module>,<type>`

### Key Questions

- What modules exist and what are their responsibilities?
- Which files have zero inbound imports (dead code)?
- Where is code duplicated across modules?
- What are the biggest files and do they have mixed responsibilities?

### Delegation

Launch parallel `@explorer` agents (max 3) using templates from [references/sub-agent-patterns.md](references/sub-agent-patterns.md):
- Agent A: Module map (imports, classes, functions, line counts)
- Agent B: Pattern search (duplication detection)
- Agent C: Dead code detection (zero-import files)

### Gate: Phase 1 Complete When

- [ ] All target modules mapped with line counts
- [ ] Import graph built (at least for target scope)
- [ ] Duplications catalogued
- [ ] Findings stored in memory with `phase-1` tags

---

## Phase 2: Refactoring Discovery

**Goal:** Identify what should change — duplication elimination, better patterns, missing abstractions.

### Steps

1. **Retrieve Phase 1 findings** — `memory_search(tags=["refactor", "phase-1"])`
2. **Analyze each finding** for refactoring opportunities:
   - **Duplication** → Can shared code be extracted?
   - **Missing abstractions** → Would a Protocol/Registry simplify dispatch?
   - **Reinvented wheels** → Is there a library that already does this?
   - **God objects** → Can responsibilities be split?
3. **Research solutions** — Use MCP tools per [references/mcp-tools.md](references/mcp-tools.md):
   - `exa_web_search_exa` for mature patterns
   - `github_search_code` for reference implementations
   - `zread_search_doc` for library-specific guides
4. **Write proposals** — Each: target files, pattern, benefit, risk, effort
5. **Store proposals** — `memory_store` with tags `refactor,phase-2,<module>,<category>`

### Proposal Categories

| Category | Description |
|----------|-------------|
| `duplication` | Same logic implemented multiple times |
| `pattern` | Better design pattern available |
| `dead-code` | Unused files, functions, or modules |
| `missing-abstraction` | Feature that needs a unifying interface |
| `test-gap` | Critical code lacking test coverage |

### Delegation

- `@oracle` for architecture recommendations
- `@librarian` for library research (if unfamiliar library involved)
- Run in parallel — oracle reads code, librarian reads docs

### Gate: Phase 2 Complete When

- [ ] Each Phase 1 finding has at least one proposal
- [ ] Proposals reference specific files and line ranges
- [ ] External solutions researched where applicable
- [ ] All proposals stored with `phase-2` tags

---

## Phase 3: Prune & Prioritize

**Goal:** Remove over-engineering from proposals, rank what's actually worth doing.

### Steps

1. **Retrieve all proposals** — `memory_search(tags=["refactor", "phase-2"])`
2. **Apply anti-pattern detection** — [references/anti-patterns.md](references/anti-patterns.md)
3. **Ask the 5 review questions for each proposal:**
   - Does this reduce total LOC?
   - Will >2 developers touch this?
   - Is a second consumer planned within 30 days?
   - Does this make testing easier?
   - Can a new contributor understand this in <5 min?
4. **Classify each proposal:**
   - 🔴 **Drop** — Over-engineering, no redeeming value
   - 🟡 **Simplify** — Has value but reduce scope
   - 🟢 **Keep** — Justified, proceed to implementation
5. **Store decisions** — `memory_store` with tags `refactor,phase-3,pruning,<verdict>`

### Critical Rule

**Default to simplicity.** If uncertain between "abstract" and "direct", choose direct. Refactoring should make code SHORTER and CLEARER, not more "architectural."

### No Delegation

Phase 3 requires project-specific context. Do it yourself.

### Gate: Phase 3 Complete When

- [ ] Every proposal classified (Drop/Simplify/Keep)
- [ ] "Keep" proposals sorted by priority (impact × ease)
- [ ] Decisions stored with `phase-3` tags

---

## Phase 4: Implement

**Goal:** Execute approved refactorings, one at a time, with verification.

### Steps

1. **Retrieve approved proposals** — `memory_search(tags=["refactor", "phase-3"], query="keep")`
2. **Sort by priority:** high-impact + low-risk first
3. **Pre-flight verification:**
   ```bash
   pytest tests/ -x -q          # ensure green baseline
   python -c "import analysis"   # verify imports work
   ```
4. **For each refactoring:**
   a. Create a todo item
   b. **Framework-first** if file >500 lines: write skeleton → verify imports → fill content
   c. Implement the change
   d. Run tests: `pytest tests/ -x -q`
   e. If tests pass → store record via `memory_store`
   f. If tests fail → **rollback protocol** (see below)
5. **Final verification:** Full test suite + import check
6. **Store completion** — `memory_store` with tags `refactor,phase-4,done,<module>`

### Rollback Protocol

When a refactoring breaks tests:

1. **Immediate:** `git diff` to see what changed
2. **Assess:** Is this a quick fix (<5 min) or fundamental problem?
3. **Quick fix:** Fix the test issue, re-run. Max 2 attempts.
4. **Fundamental problem:** Revert the change (`git checkout -- <files>`), store the failure as a finding, and move to the next refactoring. Revisit with a better plan.
5. **Never:** Leave tests broken at end of session.

### Delegation

- `@fixer` for mechanical multi-file changes (use templates from [references/sub-agent-patterns.md](references/sub-agent-patterns.md))
- `@oracle` for architectural review after complex changes
- Split work by folder for parallel `@fixer` instances

### Implementation Rules

- **One refactoring per commit** — atomic changes
- **Tests must pass after each change** — no "fix it later"
- **New code follows existing style** — match the project's conventions
- **Max 3 sub-agents** — avoid context thrash

### Metrics Template

For each completed refactoring, record:

```
[Done] <title>
Files changed: <list>
Tests: <N> pass / <M> fail
Lines delta: <+N/-M>
Time: <minutes>
Gotchas: <any unexpected issues>
```

---

## Cross-Phase Patterns

### Scope Control

- **Full project** — Run all phases on entire codebase
- **Single module** — Add module tag (e.g., `refactor,phase-1,search`)
- **Single issue** — Start at Phase 2 directly if problem is identified

### Delegation Strategy

| Phase | Agent | When | Template |
|-------|-------|------|----------|
| Phase 1 | `@explorer` | Parallel codebase searches | Module Map, Pattern Search |
| Phase 2 | `@oracle` | Architecture recommendations | Architecture Review, Design Decision |
| Phase 2 | `@librarian` | Library docs research | (standard research) |
| Phase 3 | Self | Pruning needs project context | — |
| Phase 4 | `@fixer` | Mechanical multi-file edits | Multi-File Edit, Extract to New File |
| Phase 4 | `@oracle` | Review after complex changes | Architecture Review |

### Resuming a Previous Session

```
1. memory_search(tags=["refactor"], limit=10)
2. Check phase tags: phase-1 done? phase-2 done? etc.
3. Read references/completed-refactorings.md for full history
4. Resume from the last completed phase's gate
```

---

## Reference Index

| File | Content | When to Read |
|------|---------|-------------|
| [memory-conventions.md](references/memory-conventions.md) | Tag taxonomy, store/retrieval patterns | Every phase (memory ops) |
| [anti-patterns.md](references/anti-patterns.md) | 8 over-engineering anti-patterns + review questions | Phase 3 (pruning) |
| [analysis-checklist.md](references/analysis-checklist.md) | Code archaeology checklist | Phase 1 (research) |
| [project-defects.md](references/project-defects.md) | Known architecture smells, duplications, test gaps | Pre-flight (avoid re-discovery) |
| [completed-refactorings.md](references/completed-refactorings.md) | R1-R11 history with LOC deltas, lessons learned | Pre-flight (avoid re-discovery) |
| [sub-agent-patterns.md](references/sub-agent-patterns.md) | Task templates for @explorer/@fixer/@oracle | Phases 1, 4 (delegation) |
| [mcp-tools.md](references/mcp-tools.md) | Available MCP tools + pain point mapping | Phase 2 (research) |

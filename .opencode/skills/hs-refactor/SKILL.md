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
Phase 1: Code Archaeology → Phase 2: Refactoring Discovery → Phase 3: Prune & Prioritize → Phase 4: Implement
   (research)               (design proposals)                (remove over-engineering)       (execute)
```

**Memory is mandatory.** Every finding, proposal, decision, and implementation record must be stored via `memory_store` following the conventions in [references/memory-conventions.md](references/memory-conventions.md).

---

## Phase 1: Code Archaeology

**Goal:** Build a complete map of the project — what exists, what's connected, what's dead.

### Steps

1. **Retrieve prior context** — `memory_search(query="refactor phase-1", tags=["refactor", "phase-1"])` to avoid repeating work
2. **Map directory structure** — tree with line counts, identify module boundaries
3. **Build import dependency graph** — for each `.py`, trace inbound/outbound imports
4. **Run the analysis checklist** — See [references/analysis-checklist.md](references/analysis-checklist.md)
5. **Store findings** — Each finding gets its own `memory_store` call with tags `refactor,phase-1,<module>,<type>`

### Key Questions to Answer

- What modules exist and what are their responsibilities?
- Which files have zero inbound imports (dead code)?
- Where is code duplicated across modules?
- What are the biggest files and do they have mixed responsibilities?

### Tools

- `@explorer` for parallel file/discovery searches (glob, grep, ast_grep)
- `memory_search` for prior findings
- `memory_store` for each finding (type: `observation`)

---

## Phase 2: Refactoring Discovery

**Goal:** Identify what should change — duplication elimination, better patterns, missing abstractions, MCP tool leverage.

### Steps

1. **Retrieve Phase 1 findings** — `memory_search(tags=["refactor", "phase-1"])`
2. **Analyze each finding** for refactoring opportunities:
   - **Duplication** → Can shared code be extracted? Is there a library that already does this?
   - **Missing abstractions** → Would a Protocol/Registry/Strategy pattern simplify dispatch?
   - **Reinvented wheels** → Check if MCP tools or standard libraries already provide the functionality
   - **God objects** → Can responsibilities be split along natural boundaries?
3. **Research MCP tools** — Check available MCP capabilities (memory, github, web search, exa, zread) for tasks currently done manually
4. **Write proposals** — Each proposal includes: target files, pattern, benefit, risk, effort estimate
5. **Store proposals** — `memory_store` with tags `refactor,phase-2,<module>,<category>`

### Categories

| Category | Description |
|----------|-------------|
| `duplication` | Same logic implemented multiple times |
| `pattern` | Better design pattern available (dispatch, strategy, etc.) |
| `dead-code` | Unused files, functions, or modules |
| `missing-abstraction` | Feature that needs a unifying interface |
| `mcp-tool` | Manual process that an MCP tool can replace |
| `test-gap` | Critical code lacking test coverage |

---

## Phase 3: Prune & Prioritize

**Goal:** Remove over-engineering from proposals, rank what's actually worth doing.

### Steps

1. **Retrieve all proposals** — `memory_search(tags=["refactor", "phase-2"])`
2. **Apply anti-pattern detection** — See [references/anti-patterns.md](references/anti-patterns.md)
3. **For each proposal, ask the 5 review questions:**
   - Does this reduce total LOC?
   - Will >2 developers touch this?
   - Is a second consumer planned within 30 days?
   - Does this make testing easier?
   - Can a new contributor understand this in <5 min?
4. **Classify each proposal:**
   - 🔴 **Drop** — Over-engineering, no redeeming value
   - 🟡 **Simplify** — Has value but reduce scope
   - 🟢 **Keep** — Justified, proceed to implementation
5. **Store decisions** — `memory_store` with tags `refactor,phase-3,pruning,<verdict>` (type: `decision`)

### Critical Rule

**Default to simplicity.** If uncertain between "abstract" and "direct", choose direct. Refactoring should make code SHORTER and CLEARER, not more "architectural."

---

## Phase 4: Implement

**Goal:** Execute approved refactorings, one at a time, with verification.

### Steps

1. **Retrieve approved proposals** — `memory_search(tags=["refactor", "phase-3"], mode="exact", query="keep")`
2. **Sort by priority:** high-impact + low-risk first
3. **For each refactoring:**
   a. Create a todo list item
   b. Implement the change
   c. Run tests (`pytest tests/ -x -q`)
   d. If tests pass → store implementation record via `memory_store`
   e. If tests fail → fix, then re-run
4. **Final verification:** Full test suite + import check
5. **Store completion record** — `memory_store` with tags `refactor,phase-4,done,<module>` (type: `note`)

### Implementation Rules

- **One refactoring per commit** — atomic changes
- **Tests must pass after each change** — no "fix it later"
- **New code follows existing style** — match the project's conventions
- **Delegate to @fixer** for mechanical multi-file changes
- **Delegate to @oracle** for architectural decisions during implementation

---

## Cross-Phase Patterns

### Resuming a Previous Session

```python
# Check what phase was last completed
memory_search(query="refactor phase", tags=["refactor"], limit=5)
# Results will show phase-1/2/3/4 tags — continue from the last one
```

### Scope Control

- **Full project** — Run all phases on the entire codebase
- **Single module** — Add module tag to narrow scope (e.g., `refactor,phase-1,search`)
- **Single issue** — Start at Phase 2 directly if the problem is already identified

### Delegation Strategy

| Phase | Delegate To | When |
|-------|-------------|------|
| Phase 1 | `@explorer` | Parallel searches across modules |
| Phase 2 | `@oracle` | Design pattern recommendations |
| Phase 2 | `@librarian` | MCP tool / library research |
| Phase 3 | Self | Pruning requires project context |
| Phase 4 | `@fixer` | Mechanical implementation tasks |
| Phase 4 | `@oracle` | Architectural review after changes |

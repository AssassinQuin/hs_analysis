---
date: 2026-04-19
topic: "Project State Tracking for LLM Sessions"
status: validated
---

## Problem Statement

When using LLM-assisted development across multiple chat sessions, the project suffers from:

1. **Requirement drift** — LLM sessions subtly change project goals without the user realizing
2. **Progress loss** — Completed work isn't tracked, leading to re-doing tasks
3. **No single source of truth** — state.json is stale, PROGRESS.md is manual, Memory DB drifts
4. **Contradictory state files** — state.json says T001 is "pending", PROGRESS.md shows it's done

The core issue: **there is no enforced mechanism to align every LLM session with the actual project goals and current progress.**

## Constraints

- Must be **file-based** (git-trackable, no external dependencies)
- Must be **LLM-friendly** (markdown, not JSON — LLMs read markdown better)
- Must be **minimal** — only 2-3 files, not a complex system
- Must integrate with existing `.opencode/agent.md` bootstrap sequence
- Must **not** replace existing design docs or session ledgers (those serve different purposes)
- Must work even if Memory MCP is unavailable

## Approach

### Three-file layered system

```
thoughts/
├── PROJECT_CHARTER.md    ← Immutable layer: goals, requirements, constraints
├── PROJECT_STATE.md      ← Mutable layer: current progress, active tasks, next steps
└── DECISIONS.md          ← Append-only log: all major decisions with rationale
```

I chose this over alternatives:
- **Single file**: Would bloat over time, mixing immutable goals with volatile progress
- **JSON-based**: LLMs parse markdown better than JSON; harder to diff in git
- **Database**: Overkill, not git-friendly, adds dependencies

## Architecture

### Layer 1: PROJECT_CHARTER.md (Project Charter) — Nearly Immutable

**Purpose**: Define WHAT this project is and WHY. This file changes only when the user explicitly changes requirements.

**Sections**:
- Project mission (1-2 sentences)
- Core requirements (numbered list, each with acceptance criteria)
- Technical constraints (stack, performance, compatibility)
- Out of scope (explicit list of what we're NOT doing)
- Change log (append-only record of requirement changes with date + reason)

**Update rule**: LLM must NEVER modify this file without user's explicit instruction. If an LLM session wants to change requirements, it must:
1. State the proposed change
2. Get user confirmation
3. Append to change log at bottom

### Layer 2: PROJECT_STATE.md (Project State) — Single Source of Truth

**Purpose**: Replace both state.json and PROGRESS.md with one accurate file.

**Sections**:
- Current phase and focus
- Completed tasks (with key results/metrics)
- In-progress tasks (with current status)
- Blocked/deferred items (with blockers)
- Next actions (ordered by priority)
- Data inventory (what data files exist, their sizes, last updated)

**Update rule**: Updated automatically after each task execution. The executor/workflow writes to this file upon completion of any micro-task.

**Format**: Markdown with status tags:
- `[DONE]` — completed with results
- `[WIP]` — actively being worked on
- `[BLOCKED]` — cannot proceed, reason listed
- `[TODO]` — not yet started
- `[DEFERRED]` — explicitly postponed

### Layer 3: DECISIONS.md (Decision Log) — Append-Only

**Purpose**: Prevent "silent" decision changes. Every significant decision is recorded with rationale.

**Format**: One line per decision:
```
### 2026-04-19 | Use power-law curve for vanilla test
- **Context**: V1 linear model had MAE 2.22, unacceptable for scoring
- **Decision**: Use `y = a * x^b + c` power-law curve fit via SciPy
- **Result**: MAE 0.66, 70.1% improvement
- **Alternatives considered**: Linear regression, polynomial, exponential
```

**Update rule**: Append only. Never delete or modify existing entries. If a decision is superseded, add a new entry referencing the old one.

## Components

### 1. PROJECT_CHARTER.md
- **Responsibility**: Define project identity and boundaries
- **Read by**: Every new LLM session (mandatory first read)
- **Written by**: User only (or LLM with explicit user approval)

### 2. PROJECT_STATE.md
- **Responsibility**: Track what's done, what's in progress, what's next
- **Read by**: Every new LLM session (mandatory second read)
- **Written by**: Executor/workflow after task completion, or manually by user

### 3. DECISIONS.md
- **Responsibility**: Prevent decision drift and re-litigation
- **Read by**: Every new LLM session (read last 5 entries)
- **Written by**: Any session that makes a significant decision

### 4. Bootstrap Update (.opencode/agent.md)
- **Responsibility**: Enforce session alignment
- **Change**: Replace memory-search bootstrap with file-read bootstrap:
  1. Read PROJECT_CHARTER.md → confirm goals
  2. Read PROJECT_STATE.md → recover progress
  3. Read DECISIONS.md (last 5 entries) → recent decisions
  4. State alignment: "Current goal is X, last completed Y, next action Z"

## Data Flow

```
New LLM Session Starts
    │
    ▼
Read PROJECT_CHARTER.md ──── Verify: "Project goal is X"
    │
    ▼
Read PROJECT_STATE.md ────── Recover: "Last did Y, next is Z"
    │
    ▼
Read DECISIONS.md (last 5) ── Context: "Recent decisions about A, B, C"
    │
    ▼
State alignment statement ── "I understand: goal=X, progress=Y, next=Z"
    │
    ▼
Begin work...
    │
    ▼
Task completes
    │
    ▼
Update PROJECT_STATE.md ──── Mark task done, update next actions
    │
    ▼
If significant decision ──── Append to DECISIONS.md
    │
    ▼
Session ends
```

## Error Handling

- **PROJECT_CHARTER.md missing**: LLM should refuse to proceed, ask user to create it
- **PROJECT_STATE.md missing**: LLM should scan codebase to reconstruct state, then create it
- **Contradiction detected** (e.g., state says X done but code doesn't have X): Flag to user, don't silently assume
- **Stale state** (file not updated in >7 days): Warn user that state may be inaccurate

## Testing Strategy

- Verify that a new session correctly reads and understands all three files
- Verify that task completion updates PROJECT_STATE.md correctly
- Verify that DECISIONS.md entries are well-formed and append-only
- Verify that requirement changes in CHARTER trigger change log entries
- End-to-end: Simulate two sessions, verify second session picks up exactly where first left off

## Migration Plan

1. Create PROJECT_CHARTER.md from PROGRESS.md + README.md content
2. Create PROJECT_STATE.md from PROGRESS.md + state.json (using PROGRESS.md as ground truth)
3. Create DECISIONS.md from existing session ledgers and design docs
4. Update .opencode/agent.md bootstrap sequence
5. Archive state.json (superseded by PROJECT_STATE.md)
6. Keep PROGRESS.md as historical reference (freeze it, no longer update)

## Open Questions

- Should we keep updating state.json in parallel during transition, or cut over immediately?
  → **Recommendation**: Cut over immediately. Dual maintenance was the original problem.
- How many recent DECISIONS.md entries should a session read?
  → **Recommendation**: Last 5 for context, full file for deep investigation.
- Should DESIGN docs also be referenced in PROJECT_STATE.md?
  → **Recommendation**: Yes, as a "Active Designs" section with links.

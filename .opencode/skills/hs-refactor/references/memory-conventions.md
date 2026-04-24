# Memory Conventions for Refactoring Workflow

## Tag Taxonomy

All refactoring-related memories use these tag prefixes:

| Prefix | Purpose | Example |
|--------|---------|---------|
| `refactor` | All refactoring memories | Every store |
| `phase-1` | Code archaeology findings | `refactor,phase-1,dead-code` |
| `phase-2` | Discovery & refactoring proposals | `refactor,phase-2,duplication` |
| `phase-3` | Pruning decisions | `refactor,phase-3,pruning,drop` |
| `phase-4` | Implementation records | `refactor,phase-4,done` |
| `<module>` | Module scope | `refactor,phase-1,search` |

## Memory Types

| Type | When to Use |
|------|-------------|
| `observation` | Facts about current code state (Phase 1 findings) |
| `reference` | Design patterns, external tool capabilities (Phase 2 research) |
| `decision` | Refactoring choices and rationale (Phase 3 pruning) |
| `note` | Implementation notes and gotchas (Phase 4 execution) |

## Storage Patterns

### Phase 1 — Finding
```python
memory_store(
    content="[<file>:<line>] <finding-type>: <description>\nImpact: <why it matters>\nEvidence: <specific lines/imports>",
    metadata={"tags": "refactor,phase-1,<module>,<finding-type>", "type": "observation"}
)
```

### Phase 2 — Proposal
```python
memory_store(
    content="[Proposal] <title>\nTarget: <files>\nPattern: <design-pattern-or-tool>\nBenefit: <quantified improvement>\nRisk: <what could go wrong>\nEffort: <S/M/L>",
    metadata={"tags": "refactor,phase-2,<module>,<category>", "type": "reference"}
)
```

### Phase 3 — Decision
```python
memory_store(
    content="[Decision] <title>: <verdict>\nReason: <why>\nAlternative: <what instead>",
    metadata={"tags": "refactor,phase-3,pruning,<verdict>", "type": "decision"}
)
```

### Phase 4 — Implementation
```python
memory_store(
    content="[Done] <title>\nFiles changed: <list>\nTests: <pass/fail count>\nLines delta: <+N/-M>",
    metadata={"tags": "refactor,phase-4,done,<module>", "type": "note"}
)
```

## Retrieval Patterns

```python
# Get all findings for a module
memory_search(query="refactor phase-1 search", tags=["refactor", "phase-1", "search"])

# Get all proposals
memory_search(query="refactor phase-2 proposal", tags=["refactor", "phase-2"])

# Get pruning decisions
memory_search(query="refactor phase-3 pruning", tags=["refactor", "phase-3"])

# Get implementation records
memory_search(query="refactor phase-4 done", tags=["refactor", "phase-4"])

# Cross-phase: all refactoring items for a module
memory_search(query="refactor search module", tags=["refactor", "search"])
```

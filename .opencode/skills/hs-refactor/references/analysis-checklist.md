# Phase 1: Code Archaeology Checklist

## Directory Structure Audit

- [ ] Map complete directory tree with line counts per file
- [ ] Identify top-level modules and their responsibilities
- [ ] Flag empty directories (ghost code from deleted migrations)
- [ ] Check for duplicate directory hierarchies (e.g., `engine/` vs `engine_v11/`)

## Import Dependency Graph

For each `.py` file:
- [ ] List all external imports (cross-module)
- [ ] List all internal imports (within same module)
- [ ] Count inbound imports (who imports this file?)
- [ ] Flag **zero-import files** (dead code candidates)
- [ ] Flag **import cycles** (A→B→A)

## Duplication Detection

- [ ] Find repeated regex patterns across files
- [ ] Find similar function signatures doing the same thing
- [ ] Find repeated dataclass definitions (overlapping fields)
- [ ] Find copy-pasted code blocks (>10 lines identical)
- [ ] Check for parallel implementations (OO wrapper vs functional)

## Architecture Smells

- [ ] God objects (files >800 lines with mixed responsibilities)
- [ ] Shotgun surgery (one concept spread across 5+ files)
- [ ] Feature envy (module A calling module B's internals excessively)
- [ ] Dead abstractions (protocols/interfaces with zero or one implementation)
- [ ] Premature abstraction (generic framework for a single use case)

## Test Coverage Gaps

- [ ] List files with zero test coverage
- [ ] List files with only smoke tests (import-only tests)
- [ ] Identify critical paths lacking integration tests

## External Tool Usage

- [ ] List all MCP tools currently used in the project
- [ ] Identify manual processes that could use MCP tools
- [ ] Check for reinvented wheels (custom implementations of what MCP/libraries provide)

## Memory Storage

Store findings using:
```
memory_store(
    content="<structured finding>",
    metadata={
        "tags": "refactor,phase-1,<module-name>,<finding-type>",
        "type": "observation"
    }
)
```

Finding types: `dead-code`, `duplication`, `architecture-smell`, `test-gap`, `missing-abstraction`, `reinvented-wheel`

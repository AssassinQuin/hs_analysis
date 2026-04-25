# Sub-Agent Delegation Patterns

> Structured task templates for delegating work to sub-agents during refactoring.

## Rules

1. **Max 3 sub-agents** running simultaneously — avoids context thrash
2. **Tasks must have bounded scope** — clear inputs, outputs, and completion criteria
3. **Tasks must be independently verifiable** — can check results without launching another agent
4. **No sub-agent should need to launch its own sub-agents** — flat delegation only
5. **Framework-first for files >500 lines** — generate skeleton, then fill content

## Agent Selection Guide

| Agent | Best For | Cost | Speed | Quality |
|-------|----------|------|-------|---------|
| `@explorer` | Codebase search, pattern discovery, file mapping | 0.5x | 2x | 0.8x |
| `@fixer` | Mechanical edits, multi-file changes, test writing | 0.5x | 2x | 0.8x |
| `@oracle` | Architecture review, design decisions, debugging | 1x | 0.8x | 1.5x |
| `@designer` | UI/UX review, visual polish | 1x | 0.8x | 1.5x |
| `@librarian` | Library docs, API references, version-specific behavior | 0.5x | 1x | 1x |
| `@council` | Critical decisions needing diverse model perspectives | 3x | 0.3x | 2x |

---

## @explorer Task Templates

### Template: Module Map

```
Task: Map the <MODULE_NAME> module structure
Scope: <directory_path>

Find and return:
1. All .py files in <scope> with line counts
2. For each file: class names, function names, import dependencies (inbound + outbound)
3. Module boundary: which files are internal vs imported by other modules
4. File relationships: shared imports, circular dependencies

Return format:
- File list with line counts
- Import graph (who imports whom)
- Module responsibility summary (1-2 sentences per file)
```

### Template: Pattern Search

```
Task: Find all instances of <PATTERN> across the codebase
Scope: <directory_path> (or project-wide)
Pattern type: <regex / AST pattern / function name / class name>

For each match, return:
1. File path and line number
2. Surrounding context (5 lines before/after)
3. Whether the pattern is: identical / similar / conceptually related

Return format:
- Match count
- Grouped by: exact duplicates / near-duplicates / conceptual matches
- Severity: how different are the implementations?
```

### Template: Dead Code Detection

```
Task: Identify potentially dead code in <scope>
Scope: <directory_path>

Check:
1. Functions/classes defined but never imported elsewhere
2. Files with zero inbound imports from outside their directory
3. Variables assigned but never read
4. Commented-out code blocks (>5 lines)

Return format:
- List of dead code candidates with evidence (0 imports, no references)
- Risk assessment: safe to remove / may be used dynamically / keep for now
```

---

## @fixer Task Templates

### Template: Multi-File Mechanical Edit

```
Task: <VERB> <WHAT> across <N> files
Scope: <list of specific files>

Changes to make:
1. <file_1>: <specific change description>
2. <file_2>: <specific change description>
...

Rules:
- Do NOT change any logic, only <VERB> (e.g., rename, move import, update reference)
- Preserve all existing behavior
- Run: pytest tests/ -x -q after changes
- If tests fail, revert and report the failure

Verification:
- grep for old name/pattern should return 0 results
- All tests pass
- No new lint errors
```

### Template: Extract to New File

```
Task: Extract <WHAT> from <source_file> to <new_file>
Source: <source_file>:<start_line>-<end_line>

Steps:
1. Create <new_file> with the extracted code
2. Add proper imports to <new_file>
3. Update <source_file> to import from <new_file>
4. Update any other files that reference the moved code
5. Run: pytest tests/ -x -q

Preserve:
- All function/class signatures
- All docstrings
- All existing behavior

Verify:
- grep -r "<old_reference>" should find no stale imports
- Tests pass
```

### Template: Test Scaffolding

```
Task: Create test file for <module>
Source: <module_path>
Test file: tests/test_<module_name>.py

Coverage targets:
1. All public functions/methods
2. Happy path + edge cases
3. Error handling paths

Test structure:
- One test class per class, or one test class per coherent function group
- pytest-style (no unittest.TestCase)
- Use fixtures for shared setup
- Mock external dependencies (network, file I/O)

Run: pytest tests/test_<module_name>.py -v
All new tests must pass.
```

---

## @oracle Task Templates

### Template: Architecture Review

```
Task: Review the architecture of <module/scope>
Scope: <files or module description>

Context:
<brief description of what this module does and why it's being reviewed>
<specific concerns or questions>

Review for:
1. Single Responsibility — does each file/class have one clear job?
2. Coupling — are dependencies minimal and one-directional?
3. Testability — can each component be tested in isolation?
4. YAGNI — is there over-engineering that should be simplified?
5. Simplicity — can a new contributor understand this in <5 min?

Return:
- Severity-rated issues (🔴 critical / 🟡 improvement / 🟢 fine)
- Specific refactoring recommendations with LOC impact estimate
- Risk assessment for each recommendation
```

### Template: Design Decision

```
Task: Recommend between options for <decision>
Context:
<what the decision is about>
<constraints and requirements>

Options to evaluate:
A: <option A description>
B: <option B description>
(C: <option C if applicable>)

Evaluate each on:
1. Simplicity — LOC delta, conceptual complexity
2. Performance — any measurable impact?
3. Maintainability — how hard to change later?
4. Test coverage — does it make testing easier or harder?

Return:
- Ranked recommendation with reasoning
- What could go wrong with each approach
- Implementation effort estimate (S/M/L)
```

### Template: Debugging Complex Issue

```
Task: Investigate <bug/symptom>
Symptom: <what's happening>
Expected: <what should happen>
Scope: <files likely involved>

Investigation approach:
1. Read the relevant code paths
2. Trace the data flow from input to symptom
3. Identify where the behavior diverges from expectation
4. Propose a fix with minimal blast radius

Return:
- Root cause analysis (1-3 sentences)
- Exact code location of the bug
- Proposed fix (specific code change)
- Risk of the fix (could it break anything else?)
```

---

## Parallel Execution Patterns

### Pattern 1: Fan-Out Search (Phase 1)

```
@explorer A: Map module X structure (imports, classes, functions)
@explorer B: Map module Y structure
@explorer C: Find duplication patterns across X and Y

→ Merge results, build dependency graph
```

### Pattern 2: Research + Implement (Phase 2-4)

```
@librarian: Research library X API for pattern Y
@fixer A: Implement change group 1 (files A, B, C)
@fixer B: Implement change group 2 (files D, E, F)

→ Verify results independently, then merge
```

### Pattern 3: Implement + Review (Phase 4)

```
@fixer: Implement the refactoring across N files
@oracle: Review the implementation for quality

→ Oracle reviews after fixer completes
```

### Anti-Pattern: Don't Do This

```
❌ @explorer A: Search X
   @explorer B: Use A's results to search Y  ← sequential dependency!
   @explorer C: Use B's results to search Z

✅ @explorer A: Search X
   @explorer B: Search Y independently
   @explorer C: Search Z independently
   → You merge all results
```

## Verification Checklist for Sub-Agent Results

Before accepting sub-agent output:

- [ ] **Completeness**: Did it cover all requested files/scopes?
- [ ] **Accuracy**: Do file paths and line numbers match reality?
- [ ] **No hallucination**: Can you verify at least 2 specific claims?
- [ ] **Test results**: If it ran tests, are results included?
- [ ] **No side effects**: Did it only change what was requested?

# Phase 3: Over-Engineering Detection Guide

## Anti-Patterns to Flag

### 1. Premature Protocol/Interface
- **Signal**: Protocol with ≤1 implementation AND no test mocking use
- **Fix**: Replace with direct function call; keep Protocol only if extensibility is planned within sprint

### 2. Enterprise Factory for 3 Classes
- **Signal**: Factory/Registry pattern for <5 concrete types
- **Fix**: Use simple dict or if/else dispatch; factory justified when types grow unbounded

### 3. Deep Inheritance/Composition Chain
- **Signal**: >3 levels of delegation (A→B→C→D) for a single operation
- **Fix**: Flatten to direct call; delegation chain adds indirection without proportional benefit

### 4. Config-Driven What Should Be Code
- **Signal**: JSON/YAML config that maps 1:1 to function calls and changes with code
- **Fix**: Keep config for truly user-tunable parameters; embed constants for developer-tuned ones

### 5. Abstract Base for Single Use Case
- **Signal**: `class AbstractX` with exactly one subclass, no test doubles
- **Fix**: Use concrete class directly; add abstraction when second use case emerges (YAGNI)

### 6. Over-Modularized Package
- **Signal**: Package with 1-2 line `__init__.py` files and <3 files, each <50 lines
- **Fix**: Merge into single module; packages add import complexity

### 7. Framework Before Feature
- **Signal**: Generic pipeline/dispatcher system built before any concrete handlers exist
- **Fix**: Build concrete handler first, then extract framework pattern if it repeats

### 8. Event Bus for Synchronous Flow
- **Signal**: Event/message queue for direct 1:1 synchronous communication
- **Fix**: Use direct function calls; event bus justified for async/fan-out scenarios

## Review Questions for Each Refactoring Proposal

1. **Does this reduce total lines of code?** If no → justify the complexity increase
2. **Will this be touched by >2 developers?** If no → simpler is better
3. **Is there a second consumer planned within 30 days?** If no → YAGNI
4. **Does this make the code easier to test?** If no → reconsider the abstraction
5. **Can a new contributor understand this in <5 minutes?** If no → simplify

## Severity Classification

| Severity | Action |
|----------|--------|
| 🔴 **Drop** | Over-engineering with no redeeming value → remove entirely |
| 🟡 **Simplify** | Has value but over-abstracted → reduce to minimum viable version |
| 🟢 **Keep** | Justified complexity → document the reasoning |

## Memory Storage

Store pruning decisions:
```
memory_store(
    content="<item>: <verdict> — <reason>",
    metadata={
        "tags": "refactor,phase-3,pruning,<verdict-type>",
        "type": "decision"
    }
)
```

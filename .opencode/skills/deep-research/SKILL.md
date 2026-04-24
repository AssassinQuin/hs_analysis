---
name: deep-research
description: "Project-level deep research skill for structured knowledge discovery and document generation. Triggers: user mentions 'research', '调研', '研究报告', 'investigate', 'deep dive', '文献', 'literature review', '技术调研', '方案调研', or requests to study/research a topic and produce a report. Also use when user asks to generate a development document, design document, or technical specification that requires both codebase knowledge and external research. Covers: summarizing existing project knowledge, online research with real sources, brainstorming, and incremental document generation with framework-first approach."
---

# Deep Research Skill

Structured research workflow: discover project knowledge → search online → synthesize → generate documents.

**Core principle:** Every claim must trace to a real source. Every source must be citable.

## Workflow Overview

```
Phase 1: Project Discovery    →  Summarize what the project already knows
Phase 2: Online Research      →  Search for supplementary knowledge (max 2 concurrent)
Phase 3: Synthesis            →  Merge findings, identify gaps, brainstorm
Phase 4: Document Generation  →  Framework first, then fill details
```

Each phase has an **output artifact** — do not proceed until the artifact is written to disk.

## Concurrency Rule

**Maximum 2 concurrent sub-agents at any time.** This applies to all phases. Queue additional work.

## Output Directory Convention

All research outputs go to:

```
docs/{research-topic-slug}/
├── 总结报告.md                    # Main summary report (Chinese)
├── 相关资料整理/                   # Collected materials
│   ├── 项目知识总结.md             # Knowledge from codebase
│   ├── 外部研究资料.md             # Online research findings
│   └── 信息源索引.md              # All sources with links
└── (topic-specific documents)     # Generated documents
```

`{research-topic-slug}` = lowercase, hyphenated topic name (e.g., `mcts-uct-algorithm`)

## Phase 1: Project Knowledge Discovery

**Goal:** Extract what the project already knows about the research topic.

### Steps

1. **Identify scope** — Clarify the research topic with the user if ambiguous
2. **Search codebase** — Use @explorer (parallel if needed, max 2) to find:
   - Related source files (grep for keywords, glob for patterns)
   - Existing docs (`docs/**/*.md`)
   - Config files, constants, enums relevant to topic
   - Test files showing expected behavior
3. **Read key files** — Prioritize by relevance, read core files directly
4. **Summarize** — Write `docs/{topic}/相关资料整理/项目知识总结.md`

### Output: `项目知识总结.md`

```markdown
# 项目知识总结: {Topic}

## 现有实现
- [file:path/to/file.py] — what it does, key functions/classes (L{start}-L{end})
- ...

## 可复用组件
- Component A: purpose → reuse as X
- ...

## 经验与约束
- Constraint 1 (from {source})
- Known limitation: ...
- Design decision: ... (rationale from {source})

## 知识空白
- Gap 1: ...
- Gap 2: ...
```

**Source citation format:** `[file:path/to/file.py:L42]` or `[docs/design/xxx.md:§Section]`

## Phase 2: Online Research

**Goal:** Fill knowledge gaps with real, citable external sources.

### Tool Selection Guide

| Need | Tool | When |
|------|------|------|
| Academic papers, general knowledge | `exa_web_search` | Semantic search, high-quality results |
| Specific documentation | `zread_search_doc` / `zread_read_file` | GitHub repo docs |
| Code examples on GitHub | `github_search_code` | Find implementation patterns |
| Broad web search | `searxng_web_search` | Diverse sources, news |
| Specific webpage content | `exa_web_fetch` / `webfetch` | Read full page from URL |
| Chinese content | `web-search-prime` | Better CN region results |

### Search Strategy

1. **Generate search queries** — From Phase 1 knowledge gaps, create 3-5 targeted queries
2. **Execute searches** — Max 2 concurrent. Use appropriate tool per query
3. **Deep-dive promising results** — Fetch full content for top 2-3 results
4. **Verify claims** — Cross-reference important facts with second source
5. **Store in memory** — Key findings via `memory_store` for future reuse
6. **Write findings** — `docs/{topic}/相关资料整理/外部研究资料.md`

### Memory Storage

Store important, reusable findings:

```
content: "Finding description with key details"
metadata: { tags: "research,{topic}", type: "reference" }
```

### Output: `外部研究资料.md`

```markdown
# 外部研究资料: {Topic}

## 来源1: {Title}
- URL: {url}
- 检索日期: {date}
- 关键发现: ...
- 可信度: 高/中 (reason)

## 来源2: {Title}
- URL: {url}
- ...

## 综合发现
- Finding A (来源1, 来源2 交叉验证)
- Finding B (来源3)
```

## Phase 3: Synthesis

**Goal:** Merge project knowledge + online research into actionable understanding.

### Steps

1. **Cross-reference** — Map external findings to project components
2. **Identify gaps** — What's still unknown? Mark as "需进一步研究"
3. **Brainstorm** — Generate 3-5 approaches/options for the research goal
4. **Compare** — Pros/cons table with evidence
5. **Write sources index** — `docs/{topic}/相关资料整理/信息源索引.md`
6. **Write summary** — `docs/{topic}/总结报告.md` (framework only at this stage)

### Output: `总结报告.md` (framework)

```markdown
# {Topic} 调研总结报告

> 生成日期: {date}
> 研究范围: {scope}

## 一、研究背景与目标
<!-- to fill -->

## 二、现有项目基础
<!-- to fill -->

## 三、外部研究综合
<!-- to fill -->

## 四、方案设计
<!-- to fill -->

## 五、实施建议
<!-- to fill -->

## 六、信息源
<!-- to fill -->
```

## Phase 4: Document Generation

**Goal:** Produce final documents with framework-first, detail-second approach.

### ⚠️ MANDATORY: Incremental Document Generation Protocol

This protocol is **non-negotiable**. Every document ≥300 lines MUST follow it. Violation = incorrect output.

```
┌─────────────────────────────────────────────────────────────┐
│  PASS 1: FRAMEWORK                                          │
│  Write: section headers + bullet outlines + TODO placeholders│
│  Deliver: file written to disk                               │
│  STOP. Do NOT continue to Pass 2 in the same response.      │
│                                                              │
│  PASS 2+: DETAIL FILL (one section per response)            │
│  For each section:                                           │
│    1. Read current file (to see full context)                │
│    2. Identify the section's TODO outline from framework     │
│    3. Fill ONLY that section's detail                        │
│    4. Replace the TODO placeholder with actual content       │
│    5. Verify: new content logically follows the outline      │
│  Deliver: updated file written to disk                       │
│  Repeat until all sections filled                            │
│                                                              │
│  PASS N: REVIEW                                              │
│  Read full document end-to-end                               │
│  Fix: transitions, inconsistencies, orphan TODOs             │
│  Deliver: final clean file                                   │
└─────────────────────────────────────────────────────────────┘
```

**Why this matters:**
- Large files generated in one pass produce incoherent, repetitive content
- Context window limitations mean later sections lose awareness of earlier ones
- Framework-first ensures the document's logical arc is set before details are added
- One-section-at-a-time ensures each section gets full attention

### Section Fill Rules (Logical Coherence)

When filling a section's detail content, observe these rules:

1. **Respect the outline**: The framework's bullet points are the contract. Fill what the outline promises, nothing unrelated.
2. **Read before write**: Always `Read` the current file state before editing. The framework may have been modified by previous fills.
3. **Consistent terminology**: Use the same terms defined in earlier sections. If §二 defines "MCTSNode", don't call it "Node" in §四.
4. **Forward/backward references**: If §三 references "see §七", ensure §七 actually covers that content.
5. **No duplicate content**: If a concept is explained in detail in §二, §五 should reference it briefly rather than re-explain.
6. **Progressive depth**: Earlier sections = higher-level overview. Later sections = implementation detail. Don't put implementation code in §一.

### Batching Strategy

Fill sections in logical batches (each batch = one response):

| Batch | Sections | Rationale |
|-------|----------|-----------|
| Batch 1 | Core concepts (§一~§二) | Foundation — everything depends on these |
| Batch 2 | Core algorithms (§三~§六) | The heart of the document |
| Batch 3 | Supporting systems (§七~§十) | Built on top of core |
| Batch 4 | Integration & config (§十一~§十二) | Depends on all above |
| Batch 5 | Tests & optimization (§十三~§十六) | Validates implementation |
| Batch 6 | Roadmap & appendix (§十七~§十八) | Synthesis of everything |

For documents <8 sections, batch size = 2-3 sections per response.

### Generation Order

1. `相关资料整理/信息源索引.md` — All sources organized (usually small, one-pass OK)
2. `相关资料整理/项目知识总结.md` — May already be complete from Phase 1
3. `相关资料整理/外部研究资料.md` — May already be complete from Phase 2
4. `总结报告.md` — Framework, then fill sections
5. Topic-specific documents — **Always framework first, then batch-fill**

### Citation Format in Documents

- Inline: `据 {Author} ({year}) 的研究，... [{source_id}]`
- Footnote: `[{source_id}]: {Title}. {URL}. 访问于 {date}.`
- Code reference: `[file:analysis/search/rhea/engine.py:L64]`

### Quality Checklist

Before finalizing any document:

- [ ] Every factual claim has a source citation
- [ ] No `<!-- TODO -->` placeholders remain
- [ ] All URLs are real and were actually visited
- [ ] Code references point to actual file paths
- [ ] Section transitions are coherent
- [ ] Chinese/English terminology consistent
- [ ] No content duplication across sections
- [ ] Forward references actually point to existing content
- [ ] Document follows a logical arc (problem → analysis → design → implementation → testing)

## Memory Usage

### When to Store

Store in memory when finding:
- Reusable domain knowledge (algorithm principles, design patterns)
- Project architecture decisions
- External library API behavior
- Benchmark data or quantitative findings

### When to Retrieve

Before starting Phase 2 (Online Research), always check memory first:

```
memory_search(query: "{topic}")
```

This avoids redundant web searches for previously researched topics.

### Memory Tags Convention

```
tags: "research,{topic-slug}"
type: "reference" | "decision" | "finding" | "architecture"
```

# MCP Tool Inventory for Refactoring

> Maps available MCP tools to refactoring pain points. Consult during Phase 2 Discovery.

## Available Tools

### Code Search & Analysis

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `ast_grep_search` | AST-aware pattern matching | Find all function definitions, class instantiations, import patterns |
| `ast_grep_replace` | AST-aware code transformation | Rename functions, update signatures, refactor patterns |
| `grep` | Content search across files | Find string literals, TODO comments, specific patterns |
| `glob` | File pattern matching | Find all test files, all Python files, files by naming convention |
| `read` | Read file/directory contents | Detailed code review, verify file structure |

### Web Research

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `searxng_web_search` | General web search | Find library docs, compare approaches, check best practices |
| `exa_web_search_exa` | Semantic web search | "Python God object refactoring patterns", "replace dynamic imports" |
| `exa_web_fetch_exa` | Read full web pages | Deep-dive into blog posts, library documentation |
| `webfetch` | Extract docs/pages | Read official documentation, API references |
| `web-search-prime` | Chinese-language search | 搜索中文重构教程, 方案对比 |

### GitHub Integration

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `github_search_code` | Search code across repos | Find how other projects solve similar problems |
| `github_get_file_contents` | Read repo files | Study reference implementations |
| `github_list_commits` | View commit history | Understand evolution of a module |
| `github_search_repositories` | Find similar projects | Find refactoring examples in similar codebases |
| `zread_search_doc` | Search repo documentation | Find library-specific refactoring guides |
| `zread_read_file` | Read GitHub file content | Study specific implementations |
| `zread_get_repo_structure` | View repo structure | Compare project organization |

### Memory & Knowledge

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `memory_store` | Store findings, proposals | Phase 1-4 record keeping |
| `memory_search` | Retrieve prior work | Resume sessions, avoid re-discovery |
| `memory_list` | Browse stored knowledge | Review all findings for a module |
| `memory_ingest` | Import documents | Load design docs into knowledge base |

### Task Management

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `task-master_*` | Structured task tracking | Break refactoring into subtasks, track progress |
| `todowrite` | Session-level task list | Track current work items |

### Image & Document Analysis

| Tool | Best For | Refactoring Use Case |
|------|----------|---------------------|
| `zai_extract_text` | OCR from screenshots | Extract error messages, code from images |
| `zai_diagnose_error` | Error analysis | Debug test failures with screenshots |

---

## Pain Point → Tool Mapping

### Pain: "I don't know how big this module really is"

```
1. glob("**/*.py", path="<module_dir>") → file list
2. bash("wc -l <files>") → line counts
3. Store as Phase 1 observation
```

### Pain: "Is this code duplicated?"

```
1. ast_grep_search("def $FUNC($$$)", lang="python") → find all function definitions
2. grep(pattern="<specific_logic>", include="*.py") → find similar implementations
3. @explorer: "Find all instances of <pattern>" template
```

### Pain: "Does a library already do this?"

```
1. exa_web_search_exa(query="Python library for <purpose>") → find libraries
2. searxng_web_search(query="<library_name> vs alternative") → compare options
3. @librarian: research the library's API and suitability
```

### Pain: "How did other projects solve this?"

```
1. github_search_code(query="<pattern> language:python") → find examples
2. github_search_repositories(query="<similar_project>") → find reference projects
3. zread_get_repo_structure("<owner>/<repo>") → compare architecture
```

### Pain: "Will this refactoring break tests?"

```
1. bash("pytest tests/ -x -q") → run tests before
2. Implement the change
3. bash("pytest tests/ -x -q") → run tests after
4. If regression: bash("git diff") → identify what changed
```

### Pain: "What did we already try?"

```
1. memory_search(tags=["refactor"], limit=20) → all refactoring memories
2. memory_search(query="refactor <module_name>", tags=["refactor"]) → module-specific
3. Read references/completed-refactorings.md → history
```

---

## Tool Selection Decision Tree

```
Need to find something?
├── Know the pattern? → ast_grep_search (AST) or grep (text)
├── Know the file name? → glob
├── Know the concept? → exa_web_search_exa (semantic search)
└── Know the library? → zread_search_doc

Need to change something?
├── Mechanical rename? → ast_grep_replace
├── Multi-file edit? → @fixer with edit tool
├── Complex refactor? → @fixer with detailed instructions
└── Need design input? → @oracle first, then implement

Need to research?
├── Library API? → @librarian
├── General approach? → exa_web_search_exa + webfetch
├── Chinese resources? → web-search-prime
└── Reference implementation? → github_search_code + zread_read_file

Need to verify?
├── Tests? → bash("pytest tests/ -x -q")
├── Code quality? → @oracle review
├── Imports valid? → bash("python -c 'import analysis'")
└── No regressions? → bash("pytest tests/ --tb=short")
```

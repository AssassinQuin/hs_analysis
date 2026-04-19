---
session: ses_266e
updated: 2026-04-17T13:20:34.715Z
---

# Session Summary

## Goal
Build a mathematical model to quantify Hearthstone card values from standard legendaries, and configure OpenCode with optimized MCP services and plugins.

## Constraints & Preferences
- Windows environment (PowerShell, paths use `C:\Users\Administrator\...`)
- Python env: `D:\Program Files\anaconda3\envs\qwen3-tts\python.exe`
- Node.js v25.6.0, npm 11.8.0
- Provider: `zai-coding-plan` only (Zhipu AI GLM models), auth at `~/.local/share/opencode/auth.json`
- User prefers Chinese responses but accepts English summaries
- Docker Desktop required for GitHub MCP

## Progress
### Done
- [x] **Hearthstone data collection**: 256 standard legendaries scraped from Blizzard CN API + HearthstoneJSON API → `hs_cards/all_standard_legendaries.json`, `hs_cards/standard_legendaries_v2.json`, `hs_cards/legendaries_simple_v2.json`
- [x] **Vanilla Test model built**: `expected_stats = mana * 2 + 1`, fixed keyword values (DIVINE_SHIELD=2.0, CHARGE=2.0, etc.), score = keyword_bonus - stat_deficit
- [x] **Full analysis script**: `scripts/full_analysis.py` outputs `hs_cards/standard_legendaries_analysis.json`
- [x] **34 unique mechanics identified** with frequency tiers; 17 regex-based card text effect patterns (mana_reduce, summon, aoe, generate, etc.)
- [x] **Class deficit ranking computed**: Neutral most under-budget (-5.9), DH over-budget (+0.8)
- [x] **Model v2 design doc written**: `thoughts/shared/designs/2026-04-17-hearthstone-card-model-v2-design.md` — Three-Layer Value Model (non-linear vanilla curve, empirical keyword calibration, card text parsing)
- [x] **MCP cleanup**: Deleted filesystem, git, playwright, sequential-thinking, fetch, desktop-commander, memory MCPs + uninstalled npm packages (`@modelcontextprotocol/server-sequential-thinking`, `mcp-git`, `@modelcontextprotocol/server-filesystem`, `@playwright/mcp`, `mcp-fetch-server`, `@wonderwhy-er/desktop-commander`, `@modelcontextprotocol/server-github`, `@z_ai/mcp-server`, `mcp-knowledge-graph`)
- [x] **Plugin cleanup**: Deleted `opencode-supermemory`, `opencode-mem` from config + uninstalled npm packages + removed from local `package.json`
- [x] **GitHub MCP added**: Docker `ghcr.io/github/github-mcp-server:latest` with PAT `github_pat_11ALXQXXI0...` → user AssassinQuin (Maic Gerace), 39 public repos
- [x] **AIVectorMemory installed**: `pip install aivectormemory` v2.4.4 with deps (jieba, sqlite-vec, onnx, onnxruntime)
- [x] **New plugins installed**: `opencode-notify`, `opencode-snip`, `@tarquinen/opencode-smart-title` (both global npm + local `~/.config/opencode/`)
- [x] **micode.json created**: Per-agent model assignments at `C:\Users\Administrator\.config\opencode\micode.json`
- [x] **opencode.json rewritten**: Full rewrite at `C:\Users\Administrator\.config\opencode\opencode.json` with correct 7 plugins + 5 MCPs
- [x] **Config verification**: context7 ✅, kindly-web-search ✅, sqlite ✅, github ✅, aivectormemory status ✅
- [x] **micode agent verification**: codebase-locator (glm-5-turbo) ✅, codebase-analyzer (glm-5.1) ✅ — model assignment confirmed working

### In Progress
- [ ] **Fix aivectormemory semantic search timeout** — `remember` ✅, `recall(tags/FTS5)` ✅, but `recall(semantic/vector)` ❌ times out due to ONNX embedding model (`multilingual-e5-small`) failing to complete inference
- [ ] **Hearthstone model v2 implementation** — design doc exists but planner was never spawned to create implementation plan

### Blocked
- **aivectormemory semantic search**: ONNX embedding model times out on every semantic recall call. Tag-based FTS5 search works as fallback. Root cause likely: missing/incomplete ONNX model files or onnxruntime configuration issue in `D:\Program Files\anaconda3\envs\qwen3-tts\` environment.
- **opencode-snip**: Engine warning `required: { node: '^24' }` vs current `v25.6.0` — may not function correctly.

## Key Decisions
- **AIVectorMemory over 6 alternatives**: Chosen for hybrid RRF search (vector+FTS5), memory evolution (contradiction detection, auto-promotion, 90-day archive), jieba Chinese tokenization, native OpenCode support. Runner-up: enhanced-mcp-memory (32⭐, too small community).
- **GLM-5.1 for heavy agents, GLM-5-turbo for fast agents**: Heavy reasoning tasks (brainstorm, plan, analyze, implement, review) need best quality; search/orchestrate/doc tasks benefit from speed. All models free under zai-coding-plan.
- **Docker GitHub MCP over npm**: Official `ghcr.io/github/github-mcp-server` provides full API coverage; npm alternatives were less maintained.
- **Deleted 8 MCPs**: Each was redundant with native OpenCode capabilities (fetch→webfetch, filesystem→read/write, git→bash+GitHub MCP) or overlapping functionality (memory systems consolidated to AIVectorMemory).
- **Temperature by agent role**: Creative agents 0.7, structured 0.5, analytical 0.3, review 0.2.

## Next Steps
1. **Diagnose and fix aivectormemory ONNX timeout** — check `onnxruntime` installation, verify model weights exist, test embedding generation directly via Python
2. **Return to Hearthstone model v2** — spawn micode planner agent to create implementation plan from design doc `thoughts/shared/designs/2026-04-17-hearthstone-card-model-v2-design.md`
3. **Implement Three-Layer Value Model** — non-linear vanilla curve, empirically calibrated keywords, card text effect parsing
4. **Validate model v2** against known card evaluations and community tier lists

## Critical Context
- **zai-coding-plan models** (12 total, from opencode-models.dev): glm-4.5-air (131K ctx, free), glm-4.5-flash (free), glm-4.5 (free), glm-4.5v (vision, free), glm-4.6 (free), glm-4.6v (vision, free), glm-4.7-flash (free), glm-4.7-flashx ($0.07/$0.40), glm-4.7 (free), glm-5-turbo (200K ctx, free), glm-5 (205K ctx, free), glm-5.1 (~200K ctx, free)
- **GitHub Issue #14333**: GLM subagents can freeze with zai-coding-plan provider — known OpenCode bug
- **Vanilla test key finding**: Stat deficit grows with mana cost — high-cost cards increasingly under-budget on stats, compensating with effects. Linear `2N+1` formula breaks at high mana.
- **Keyword calibration data**: Observed avg_score per keyword — WINDFURY +9.0, DIVINE_SHIELD +6.9, DISCOVER +5.8, BATTLECRY +5.7, DEATHRATTLE +5.6 vs model's fixed values (all 1.0-2.0) — significant underestimation
- **aivectormemory DB**: `~/.aivectormemory/memory.db` with 46 tables (vec_*, fts_*, graph_*)

## File Operations
### Read
- `C:\Users\Administrator\.config\opencode\opencode.json` — main OpenCode config (7 plugins, 5 MCPs)
- `C:\Users\Administrator\.config\opencode\micode.json` — micode per-agent model config (12 agents)
- `C:\Users\Administrator\.config\opencode\package.json` — local npm deps for plugins
- `C:\Users\Administrator\.local\share\opencode\auth.json` — zai-coding-plan API key
- `D:\code\game\.opencode\agent.md` — project agent description (Hearthstone math modeling)
- `D:\code\game\README.md` — project readme with model documentation
- `D:\code\game\thoughts\shared\designs\2026-04-17-hearthstone-card-model-v2-design.md` — model v2 design doc

### Modified
- `C:\Users\Administrator\.config\opencode\opencode.json` — rewritten: deleted 8 MCPs, 2 plugins; added 2 MCPs (github docker, aivectormemory), 3 plugins (notify, snip, smart-title)
- `C:\Users\Administrator\.config\opencode\micode.json` — created new: 12 agent model+temperature assignments
- `C:\Users\Administrator\.config\opencode\package.json` — updated deps: removed opencode-supermemory, added opencode-notify/opencode-pty/opencode-snip/opencode-smart-title
- `D:\code\game\scripts\full_analysis.py` — core analysis script (pre-existing)
- `D:\code\game\scripts\deep_analysis.py` — deep analysis script (created this session)
- `D:\code\game\scripts\quick_analysis.py` — quick analysis script (created this session)

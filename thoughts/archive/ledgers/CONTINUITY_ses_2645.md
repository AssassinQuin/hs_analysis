---
session: ses_2645
updated: 2026-04-17T14:11:27.499Z
---

# Session Summary

## Goal
Fix and enhance the user's OpenCode configuration: resolve GitHub MCP container cleanup issues, fix micode agent dead processes with large files, find loop-mode plugins, and research/install the most popular MCP servers and OpenCode plugins.

## Constraints & Preferences
- Config file: `C:\Users\Administrator\.config\opencode\opencode.json` (Windows server)
- micode config: `C:\Users\Administrator\.config\opencode\micode.json`
- User prefers Chinese language responses
- Docker-based GitHub MCP server with `--rm -i` pattern
- User has 7 plugins + 6 MCP servers already configured
- Node.js v25.6.0, Windows environment

## Progress
### Done
- [x] **GitHub MCP container cleanup fix**: Added `--init`, `--memory=512m`, `--cpus=1`, `--name opencode-github-mcp` to docker run command in `opencode.json` (b1)
- [x] **micode agent dead process fix**: Added `defaults: { maxSteps: 30, timeout: 300000 }` and per-agent maxSteps (heavy=50, medium=40, light=20, minimal=15) to `micode.json` (b1)
- [x] **Loop-mode plugin research**: No dedicated loop plugin exists. OpenCode has built-in `maxSteps` + `doom_loop` + `continue_loop_on_deny` for loop-equivalent functionality (b1)
- [x] **Comprehensive MCP & plugin research**: Cataloged popular MCP servers (GitHub, Playwright, Context7, Firecrawl, Exa, Tavily, etc.) and 60+ OpenCode plugins from awesome-opencode list, with ratings/tiering and micode vs oh-my-opencode comparison
- [x] **Read current `opencode.json`**: Confirmed current state has 7 plugins and 6 MCP servers with the GitHub MCP fix already applied
- [x] **Researched installation methods for 3 new components**: Exa Search MCP (remote URL), Agent Memory plugin (npm), Pocket Universe plugin (npm `@spoons-and-mirrors/pocket-universe@latest`)

### In Progress
- [ ] **Install Exa Search MCP + Agent Memory plugin + Pocket Universe plugin**: Research complete, need to edit `opencode.json` to add all three

### Blocked
- **Pocket Universe**: Requires OpenCode PR #9272 (async subagents, session resumption, main thread block) and PR #7725 (tool scoping for subagents) to be merged to function correctly — these are NOT yet merged. Plugin can be installed but may not work fully.

## Key Decisions
- **Exa Search as remote MCP**: Uses `type: "remote"` with URL `https://mcp.exa.ai/mcp` — no local install needed, no API key for basic usage (tools: `web_search_exa`, `web_fetch_exa`; advanced tools available via `?tools=web_search_advanced_exa`)
- **Agent Memory plugin**: npm package `opencode-agent-memory`, Letta-inspired persistent memory blocks with 3 tools (`memory_list`, `memory_set`, `memory_replace`) + optional journal feature. Stores as markdown files in `~/.config/opencode/memory/*.md` (global) and `.opencode/memory/*.md` (project)
- **Pocket Universe**: npm package `@spoons-and-mirrors/pocket-universe@latest`, provides closed-loop async subagents with 3 tools (`broadcast`, `subagent`, `recall`), git worktree isolation support, and `/pocket` command for messaging agents

## Next Steps
1. **Edit `opencode.json`** to add the 3 new components:
   - Add `"opencode-agent-memory"` and `"@spoons-and-mirrors/pocket-universe@latest"` to the `plugin` array
   - Add Exa MCP server entry: `{ "type": "remote", "url": "https://mcp.exa.ai/mcp", "enabled": true }`
2. **Optionally create `agent-memory.json`** at `~/.config/opencode/agent-memory.json` to enable journal feature: `{ "journal": { "enabled": true } }`
3. **Optionally create `pocket-universe.jsonc`** at `~/.config/opencode/pocket-universe.jsonc` for Pocket Universe config (worktree, recall, logging settings)
4. **Restart OpenCode** to load new plugins and MCP server
5. **Warn user** that Pocket Universe needs unmerged OpenCode PRs for full functionality

## Critical Context
- **Current opencode.json plugin array**: `["@tarquinen/opencode-dcp", "@zenobius/opencode-background", "micode", "opencode-pty", "opencode-notify", "opencode-snip", "@tarquinen/opencode-smart-title"]`
- **Current MCP servers**: context7, kindly-web-search, sqlite, github (fixed), aivectormemory
- **Exa remote MCP URL**: `https://mcp.exa.ai/mcp` — supports `?tools=web_search_exa,web_search_advanced_exa,web_fetch_exa` query params for enabling specific tools
- **Exa alternative local install**: `npx -y exa-mcp-server` with `EXA_API_KEY` env var (needs API key from https://dashboard.exa.ai/api-keys)
- **Agent Memory config file**: `~/.config/opencode/agent-memory.json` for journal: `{ "journal": { "enabled": true, "tags": [...] } }`
- **Pocket Universe config file**: `~/.config/opencode/pocket-universe.jsonc` (auto-created) — defaults: broadcast=true, subagent.enabled=true, subagent.max_depth=3, recall.enabled=false, worktree=false, logging=false
- **Pocket Universe dependency warning**: Needs unmerged OpenCode PRs #9272 and #7725 for full async subagent functionality
- **Plaintext secrets in opencode.json**: Lines 27-28 (GITHUB_TOKEN in kindly-web-search), lines 57-58 (GITHUB_PERSONAL_ACCESS_TOKEN in github MCP) — security concern noted

## File Operations
### Read
- `C:\Users\Administrator\.config\opencode\opencode.json` (current state with GitHub MCP fix applied)
- `C:\Users\Administrator\.config\opencode\micode.json` (12 agents, maxSteps/timeout added) (b1)

### Modified
- `C:\Users\Administrator\.config\opencode\opencode.json` — GitHub MCP docker command enhanced with `--init`, `--memory=512m`, `--cpus=1`, `--name opencode-github-mcp` (b1)
- `C:\Users\Administrator\.config\opencode\micode.json` — Added defaults `{ maxSteps: 30, timeout: 300000 }` and per-agent maxSteps (b1)

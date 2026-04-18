---
session: ses_261b
updated: 2026-04-18T01:51:55.787Z
---

# Session Summary

## Goal
Comprehensive analysis of the HearthSim/Hearthstone-Deck-Tracker GitHub repository to evaluate it as a base for forking and extending with AI decision-making features (lethal checks, play suggestions, mulligan AI, etc.)

## Constraints & Preferences
- Analysis must cover all 10 specified areas: tech stack, dev environment, project structure, architecture, plugin system, lethal check code, game state detection, card evaluation/scoring, opponent hand tracking, and AI/decision-making code
- User intends to FORK and EXTEND this project with AI features
- Need to understand what already exists vs. what must be built from scratch

## Progress
### Done
- [x] Retrieved root directory listing, README.md, .gitignore
- [x] Retrieved and parsed `Hearthstone Deck Tracker.sln` (8 projects: main app, HDTTests, HDTUpdate, HDTUninstaller, HearthWatcher, HearthWatcher.Test, Bootstrap, SignToolShim)
- [x] Retrieved and fully analyzed `Hearthstone Deck Tracker/Hearthstone Deck Tracker.csproj` (target framework, dependencies, build config)
- [x] Retrieved CONTRIBUTING.md (dev setup instructions, coding style, CLA requirements)
- [x] Retrieved nuget.config (local packages folder)
- [x] Listed all files in `Hearthstone Deck Tracker/` main project directory (~30+ subdirectories and key files)
- [x] Listed all files in `HearthWatcher/` project directory
- [x] Retrieved and analyzed `Plugins/IPlugin.cs` (full plugin interface)
- [x] Listed `Plugins/` directory (IPlugin.cs, PluginManager.cs, PluginSettings.cs, PluginWrapper.cs)
- [x] Listed `BobsBuddy/` directory (BobsBuddyInvoker.cs, BobsBuddyUtils.cs, LethalResult.cs, CombatResult.cs, etc.)
- [x] Retrieved and fully analyzed `BobsBuddy/BobsBuddyInvoker.cs` (44KB - the main simulation/lethal integration)
- [x] Listed `Hearthstone/` domain model directory (Card.cs, Deck.cs, Player.cs, GameV2.cs, Entity.cs, Watchers.cs, Secrets/, CounterSystem/, RelatedCardsSystem/, EffectSystem/, etc.)
- [x] Listed `Hearthstone/Entities/` (Entity.cs, GuessedCardState.cs)
- [x] Listed `Hearthstone/Secrets/` (Secret.cs, SecretsEventHandler.cs, SecretsManager.cs)
- [x] Listed `Hearthstone/CounterSystem/` (BaseCounter.cs, CounterManager.cs, NumericCounter.cs, StatsCounter.cs, BgCounters/, Counters/)
- [x] Listed `HearthWatcher/Providers/` (20+ provider interfaces for memory reading)
- [x] Listed `HearthWatcher/LogReader/` (LogFileWatcher.cs, LogLine.cs, LogWatcherInfo.cs)
- [x] Listed `LogReader/` in main project (HsGameState.cs, LogConstants.cs, LogWatcherManager.cs, GameTagHelper.cs, Handlers/, Interfaces/)
- [x] Listed `HsReplay/` directory (ApiWrapper.cs, MulliganGuideTrial.cs, UploadMetaDataGenerator.cs, HSReplayNetHelper.cs, etc.)
- [x] Listed `API/` directory (GameEvents.cs, Core.cs, ActionList.cs, AttackInfo.cs, PreDamageInfo.cs, DeckManagerEvents.cs, LogEvents.cs)
- [x] Listed Mulligan overlay controls (ConstructedMulliganGuide*.xaml/cs, V2/ subfolder with updated mulligan guide)
- [x] Listed `Hearthstone/RelatedCardsSystem/` (RelatedCardsManager.cs, ICard.cs, ICardGenerator.cs, ICardWithRelatedCards.cs, Cards/ subfolder)
- [x] GitHub code search for "lethal" and "simulate" was rate-limited (403) - not completed

### In Progress
- [ ] Synthesizing all gathered data into the comprehensive 10-area analysis report
- [ ] Code search for lethal/damage/simulation keywords was blocked by API rate limit

### Blocked
- GitHub code search API rate limit prevented searching for "lethal", "kill", "damage", "simulate", "combat" across the codebase (got 403 errors). However, BobsBuddyInvoker.cs was retrieved directly and contains extensive lethal/simulation code, partially compensating.

## Key Decisions
- **Fetched files directly by path instead of relying on code search**: Due to API rate limits on GitHub code search, individual files were fetched by their known/likely paths to gather the needed information
- **Prioritized BobsBuddyInvoker.cs for lethal analysis**: At 44KB, this is the single most important file for understanding existing simulation/lethal code

## Next Steps
1. Synthesize all gathered data into the comprehensive 10-area analysis covering: tech stack, dev environment, project structure, architecture, plugin system, lethal check code, game state detection, card evaluation, opponent hand tracking, AI/decision-making
2. Key findings to incorporate into the final report:

## Critical Context

### Tech Stack Findings
- **Language**: C# 10 (LangVersion=10), nullable reference types enabled
- **Framework**: .NET Framework 4.7.2 (`net472`), NOT .NET Core/.NET 5+
- **UI**: WPF (`UseWPF=true`), MahApps.Metro 1.6.5 for Metro-style UI
- **Build**: SDK-style csproj with `Microsoft.NET.Sdk.WindowsDesktop`, x86 only (PlatformTarget=x86)
- **Solution**: VS2019+ format (Version 16), 3 build configs: Debug|x86, Release|x86, Squirrel|x86
- **Updater**: Squirrel.Windows 1.9.1
- **Key NuGet packages**: Newtonsoft.Json 12.0.3, HtmlAgilityPack 1.11.23, LiveCharts 0.9.7, Mono.Cecil 0.9.6.1, SharpRaven 2.4.0
- **Key DLL references (prebuilt in lib/)**: HearthDb.dll, HearthMirror.dll, HSReplay.dll, BobsBuddy.dll — these are separate HearthSim repos, source NOT included

### Architecture Findings
- **NOT pure MVVM**: Mix of code-behind, event-driven, and some ViewModel patterns. Core.cs is a massive singleton/static hub (~21KB). GameEventHandler.cs is 97KB event handler.
- **Main entry**: `App.xaml.cs` → `Core.cs` (central orchestrator)
- **Game state**: `GameV2.cs` (33KB) is the primary game state object with `Player` and `Opponent` properties (Player.cs is 34KB)
- **Entity system**: `Hearthstone/Entities/Entity.cs` (11KB) wraps Hearthstone's internal entity/tag system
- **Event flow**: Hearthstone log files → HearthWatcher (log parsing) → GameEventHandler → GameV2 state update → UI update

### Game State Detection (Dual System)
1. **Log file reading** (primary): HearthWatcher project reads Hearthstone's debug logs (`HearthWatcher/LogReader/LogFileWatcher.cs`). HDT has its own `LogReader/` with `HsGameState.cs`, `LogWatcherManager.cs`, and `Handlers/` subdirectory for parsing different log lines (Power, Zone, etc.)
2. **Memory reading** (secondary): `HearthMirror.dll` (prebuilt, source in separate repo) reads Hearthstone process memory. Used for things logs don't provide. HearthWatcher has 20+ `I*Provider.cs` interfaces in `Providers/` that abstract memory-reading data sources.

### Plugin System
- **Interface**: `IPlugin.cs` — simple contract: Name, Description, ButtonText, Author, Version, MenuItem, OnLoad(), OnUnload(), OnButtonPress(), OnUpdate() (called ~100ms)
- **Manager**: `PluginManager.cs` (9KB) loads/unloads plugin DLLs
- **Wrapper**: `PluginWrapper.cs` wraps plugin instances
- **Limitations**: Plugin API is minimal — no direct access to game state through the interface. Plugins would need to use `API/Core.cs` which exposes some game state. `API/GameEvents.cs` provides event hooks.
- **API surface**: `API/` folder contains GameEvents.cs (game event delegates), ActionList.cs, AttackInfo.cs, PreDamageInfo.cs, LogEvents.cs, DeckManagerEvents.cs

### Existing Lethal/Simulation Code (BobsBuddy)
- **BobsBuddy is BATTLEGROUNDS ONLY** — it simulates BG combat (minion trading, hero powers, deathrattles), NOT constructed gameplay
- **External DLL**: `BobsBuddy.dll` in lib/ — the actual simulation engine is NOT in this repo. Only the integration/wrapper code is here.
- **BobsBuddyInvoker.cs** (44KB): Snapshots board state from GameV2, converts to BobsBuddy's `Input` model, runs `SimulationRunner.SimulateMultiThreaded()` with 10,000 iterations, multi-threaded
- **Key types from BobsBuddy.dll**: `Simulator`, `SimulationRunner`, `Input`, `Output`, `Minion`, `MinionCardEntity`, `SpellCardEntity`, `UnknownCardEntity`, `BloodGem`, `EnchantmentFactory`, `MinionFactory`, `TrinketFactory`
- **LethalResult.cs**: Enum with `NoOneDied`, `FriendlyDied`, `OpponentDied`
- **CombatResult.cs**: Enum with `Win`, `Loss`, `Tie`
- **Validation**: Post-combat validation checks if simulation's predicted outcome matches actual result (reports mismatches to Sentry)
- **NO constructed lethal checker exists** — this is a gap that would need to be built

### Opponent Hand Tracking
- `Player.cs` has `Hand` (List<Card>), `Board`, `Deck`, `Secrets`, `Graveyard`, `SetAside`, `Quests`, `QuestRewards`, `Trinkets`, `Objectives`
- Opponent cards tracked via log events (card played, card drawn, card returned, card stolen)
- `PredictedCard.cs` — opponent card prediction exists
- `GuessedCardState.cs` — entity state guessing for hidden cards
- `Hearthstone/RelatedCardsSystem/` — tracks card relationships (tutors, generated cards, etc.)

### Card Evaluation/Scoring
- **NO general card scoring/evaluation system exists** in this repo
- `CounterSystem/` has `BaseCounter.cs` and `CounterManager.cs` — these are UI counters (spell damage on board, etc.), NOT card value scoring
- `Hearthstone/EffectSystem/` — tracks active effects (probably for display)
- Mulligan guide data comes from HSReplay.net API (server-side stats), not local computation

### AI/Decision-Making Code
- **Mulligan suggestions**: `Controls/Overlay/Constructed/Mulligan/` — UI for displaying mulligan win% data fetched from HSReplay.net API. `MulliganGuideTrial.cs` manages trial/access. No local AI computation — all stats are server-side.
- **Arena pick helper**: `Controls/Overlay/Arena/ArenaPickHelper.xaml` — likely also HSReplay.net tier data
- **NO local AI for**: play ordering, mulligan decisions (beyond server stats), turn planning, lethal checking in constructed
- **Secrets**: `SecretsManager.cs` (14KB) and `SecretsEventHandler.cs` (16KB) — rule-based secret elimination logic (this is the closest thing to "AI" in the codebase)

### External Dependencies (Prebuilt DLLs, No Source)
- `HearthDb.dll` — Hearthstone card database
- `HearthMirror.dll` — Process memory reader for Hearthstone
- `HSReplay.dll` — HSReplay.net API client
- `BobsBuddy.dll` — Battlegrounds combat simulator
- `untapped-scry-dotnet.dll` — Untapped.gg integration
- These are fetched by `bootstrap.ps1` and `Bootstrap/` project

### Project Structure Key Paths
- `Hearthstone Deck Tracker/Core.cs` — central hub singleton
- `Hearthstone Deck Tracker/GameEventHandler.cs` — 97KB, all game event handling
- `Hearthstone Deck Tracker/IGameHandler.cs` — game handler interface
- `Hearthstone Deck Tracker/Hearthstone/GameV2.cs` — game state (Player, Opponent, Entities dict)
- `Hearthstone Deck Tracker/Hearthstone/Player.cs` — player state (Hand, Board, Deck, Hero, etc.)
- `Hearthstone Deck Tracker/Hearthstone/Entities/Entity.cs` — entity wrapper with tags
- `Hearthstone Deck Tracker/Hearthstone/Card.cs` — card model (22KB)
- `Hearthstone Deck Tracker/Hearthstone/Watchers.cs` — watcher registration
- `Hearthstone Deck Tracker/LogReader/` — log parsing (Handlers/ has sub-handlers)
- `HearthWatcher/` — separate project for log watching abstraction
- `Hearthstone Deck Tracker/API/` — plugin API surface
- `Hearthstone Deck Tracker/BobsBuddy/` — BG simulation integration
- `Hearthstone Deck Tracker/Controls/Overlay/` — overlay UI controls

## File Operations
### Read
- `Hearthstone Deck Tracker.sln`
- `README.md`
- `.gitignore`
- `CONTRIBUTING.md`
- `nuget.config`
- `Hearthstone Deck Tracker/Hearthstone Deck Tracker.csproj`
- `Hearthstone Deck Tracker/Plugins/IPlugin.cs`
- `Hearthstone Deck Tracker/BobsBuddy/BobsBuddyInvoker.cs`
- (Directory listings for ~20 directories as detailed above)

### Modified
- (none)

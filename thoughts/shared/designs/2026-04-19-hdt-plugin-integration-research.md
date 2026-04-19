---
date: 2026-04-19
topic: "HDT Plugin System & PowerLog Integration Research"
status: validated
references:
  - thoughts/archive/designs/2026-04-18-hdt-analysis-report.md
  - https://github.com/HearthSim/Hearthstone-Deck-Tracker
  - https://github.com/HearthSim/python-hearthstone
  - https://github.com/HearthSim/hearthstone-log-watcher
---

# HDT Plugin System & PowerLog Integration Research

## Executive Summary

This document evaluates three integration strategies for connecting Hearthstone Deck Tracker (HDT) game state to a Python analysis backend. After examining the HDT plugin API, the Power.log format, and the python-hearthstone library ecosystem, **Option B (Python directly watching Power.log via python-hslog)** is recommended as the primary approach, with **Option A (HDT plugin as supplementary bridge)** for enriched state access.

**Key conclusion**: The Power.log file is the canonical game state source. python-hslog already provides incremental, streaming-capable parsing with a full entity model. An HDT plugin adds marginal value (HSReplay win rates, opponent secrets deduction) but is not required for core functionality.

---

## 1. HDT Plugin Architecture

### 1.1 Plugin Interface (IPlugin.cs)

**File**: `Hearthstone Deck Tracker/Plugins/IPlugin.cs`

The plugin interface requires implementing:

```csharp
public interface IPlugin
{
    // Metadata
    string Name { get; }
    string Description { get; }
    string ButtonText { get; }
    string Author { get; }
    Version Version { get; }
    MenuItem MenuItem { get; }

    // Lifecycle
    void OnLoad();           // Called when plugin loaded
    void OnUnload();         // Called when plugin unloaded
    void OnButtonPress();    // Called when plugin button clicked
    void OnUpdate();         // Called every ~100ms (main thread)
}
```

### 1.2 Plugin Lifecycle

```
Discovery → Init → Load → Update loop (~100ms) → Unload
```

1. **Discovery**: HDT scans `%APPDATA%/HearthstoneDeckTracker/Plugins/` for DLLs implementing IPlugin
2. **Init/Load**: `OnLoad()` called — plugin registers event handlers
3. **Update**: `OnUpdate()` fires every ~100ms on the UI thread — suitable for periodic state export
4. **Unload**: `OnUnload()` called on shutdown or plugin disable

### 1.3 Game State Access via API

**File**: `Hearthstone Deck Tracker/API/Core.cs`

```csharp
// Static access to core HDT objects
public static GameV2 Game { get; }           // Full game state
public static Canvas OverlayCanvas { get; }  // Overlay rendering surface
public static Window OverlayWindow { get; }
public static MainWindow MainWindow { get; }
```

**File**: `Hearthstone Deck Tracker/API/GameEvents.cs`

```csharp
// Event hooks (static ActionList delegates)
public static class GameEvents
{
    // Player actions
    OnPlayerPlay;           // Player plays a card
    OnPlayerDraw;           // Player draws a card
    OnPlayerMulligan;       // Player mulligans
    OnPlayerPlayToDeck;     // Card returned to deck
    OnPlayerPlayToHand;     // Card returned to hand

    // Opponent actions
    OnOpponentPlay;         // Opponent plays a card
    OnOpponentSecretTriggered;
    OnOpponentDraw;

    // Game flow
    OnGameStart;
    OnGameEnd;
    OnGameWon;
    OnGameLost;
    OnTurnStart;
    OnModeChanged;          // Game mode change (menu, game, etc.)
}
```

### 1.4 Plugin Build & Deploy

- **Target**: .NET Framework 4.7.2, x86 architecture
- **Build**: Visual Studio 2019+, class library project
- **Reference**: Add reference to `HearthstoneDeckTracker.exe` (or its public API types)
- **Deploy**: Copy compiled DLL to `%APPDATA%/HearthstoneDeckTracker/Plugins/`
- **Limitation**: Plugins run on HDT's UI thread — heavy computation will freeze the overlay

### 1.5 Key Limitation

HDT plugins share the UI thread. The `OnUpdate()` callback fires every ~100ms, but any blocking operation (network I/O, file writing, computation) in OnUpdate or event handlers will cause the overlay to stutter. All heavy work must be offloaded to background threads.

---

## 2. PowerLog Real-time Reading

### 2.1 Power.log Format & Location

**Location**: `%LOCALAPPDATA%\Blizzard\Hearthstone\Logs\Power.log`

The Power.log is a text file written by the Hearthstone client. It records every game state change as structured text lines:

```
D 07:23:45.1234567 PowerTaskList.DebugPrintPower() - ACTION_START BlockType=PLAY Entity=[name=Ragnaros the Firelord id=34 zone=HAND zonePos=1 cardId=EX1_116 player=1] Target=0 SubOption=0 TriggerKeyword=0
D 07:23:45.1234567 PowerTaskList.DebugPrintPower() -   TAG_CHANGE Entity=GameEntity tag=STEP value=MAIN_ACTION
D 07:23:45.1234567 PowerTaskList.DebugPrintPower() -   FULL_ENTITY - Updating [name=Ragnaros the Firelord id=34 zone=PLAY zonePos=1 cardId=EX1_116 player=1] CardID=EX1_116
D 07:23:45.1234567 PowerTaskList.DebugPrintPower() -     tag=ATK value=8
D 07:23:45.1234567 PowerTaskList.DebugPrintPower() -     tag=HEALTH value=8
```

### 2.2 Key Packet Types

| Packet | Purpose |
|--------|---------|
| `CREATE_GAME` | Game entity initialization |
| `FULL_ENTITY` | Full entity state (all tags) |
| `SHOW_ENTITY` | Revealed entity (card played from hand) |
| `HIDE_ENTITY` | Entity hidden (card returned to deck) |
| `TAG_CHANGE` | Single tag value change |
| `BLOCK_START/END` | Action block (play, attack, etc.) |
| `META_DATA` | Metadata about preceding data |

### 2.3 Latency Characteristics

- **HearthWatcher (HDT's log reader)**: Polls every 50ms
- **Game client write frequency**: Lines appear within 10-50ms of the actual game event
- **End-to-end latency (HDT)**: Game event → file write → poll → parse → state update ≈ 60-150ms
- **For a Python watcher**: Comparable latency expected with a 50-100ms polling interval

### 2.4 File Watching Approach for Python

The standard pattern (used by HDT, Hearthstone-Log-Watcher, and others):

```python
import time
import os

class LogWatcher:
    def __init__(self, path, callback):
        self.path = path
        self.callback = callback
        self.position = 0  # track read position

    def watch(self, poll_interval=0.05):
        while True:
            if not os.path.exists(self.path):
                time.sleep(poll_interval)
                continue

            with open(self.path, 'r', encoding='utf-8') as f:
                f.seek(self.position)
                new_lines = f.readlines()
                self.position = f.tell()

            for line in new_lines:
                self.callback(line)

            time.sleep(poll_interval)
```

**Key considerations**:
- Hearthstone rotates Power.log between games (creates new file). Watcher must detect file truncation/rotation.
- Encoding: UTF-8 with BOM possible
- File locking: Hearthstone holds the file open; Python can read concurrently without issues on Windows (shared read lock)

---

## 3. python-hearthstone Library (HearthSim)

### 3.1 Overview

**Repository**: https://github.com/HearthSim/python-hearthstone
**Package**: `pip install hearthstone`

The python-hearthstone library provides:
- `hearthstone.hslog` — Power.log parser
- `hearthstone.entities` — Game state entity model
- `hearthstone.enums` — Game enums (GameTag, Zone, etc.)
- `hearthstone.cardxml` — Card database loader
- `hearthstone.dbf` — DBF card database

### 3.2 hearthstone.hslog Module

**File**: `hearthstone/hslog/parser.py`

The `LogParser` class is the core parser:

```python
from hearthstone.hslog.parser import LogParser

parser = LogParser()

# Batch parsing (whole file)
with open("Power.log", "r") as f:
    parser.read(f)

# Incremental parsing (streaming)
with open("Power.log", "r") as f:
    for line in f:
        parser.read_line(line)  # Process one line at a time
```

**Parser architecture**:
- `LogParser.read_line(line)` dispatches to module-specific handlers
- `PowerHandler` handles all Power.log lines
- `ChoicesHandler` handles choice dialogs (mulligan, discover)
- `OptionsHandler` handles available options
- Each handler maintains its own packet tree

### 3.3 Entity Tree Exporter

**File**: `hearthstone/hslog/export.py`

The `EntityTreeExporter` transforms parsed log packets into a live `hearthstone.entities.Game` object:

```python
from hearthstone.hslog.export import EntityTreeExporter

exporter = EntityTreeExporter(parser.game_state_data)
game = exporter.export()

# Access game state
game.current_player          # Current active player
game.players                 # List of Player entities
game.in_zone(Zone.PLAY)      # All entities on board
game.in_zone(Zone.HAND)      # All entities in hand
```

**Incremental export** — critical for real-time use:
```python
# Export only new packets since last checkpoint
exporter = EntityTreeExporter(parser.game_state_data)
game = exporter.export()  # Initial full export

# After processing new lines...
game = exporter.export()  # Exports only new packets, updates existing Game
```

The exporter maintains a `Game` entity tree and applies new packets incrementally. Each `export()` call processes only unprocessed packets from the `PacketTree`.

### 3.4 Entity Model

**File**: `hearthstone/entities.py`

```python
class Entity:
    id: int
    tags: dict           # {GameTag: int} — all entity properties
    game: Game           # Parent game reference

class Game(Entity):
    _entities: dict      # {entity_id: Entity} — all entities
    players: list        # [Player, Player]
    current_player: Player

    def in_zone(self, zone) -> list:
        """Filter entities by zone (PLAY, HAND, DECK, etc.)"""

class Player(Entity):
    name: str
    account_hi: int
    account_lo: int
    is_ai: bool

class Card(Entity):
    card_id: str         # e.g. "EX1_116"
    reveal()             # Card becomes visible (SHOW_ENTITY)
    hide()               # Card becomes hidden
    change(card_id)      # Card transforms
```

### 3.5 Streaming Capability Assessment

| Capability | Support | Details |
|-----------|---------|---------|
| Incremental line parsing | ✅ Yes | `LogParser.read_line()` |
| Incremental state export | ✅ Yes | `EntityTreeExporter.export()` processes new packets |
| State mutation tracking | ✅ Yes | Card.reveal/hide/change methods |
| Multi-game support | ✅ Yes | New game detected via CREATE_GAME packet |
| File rotation handling | ⚠️ Manual | Caller must detect new file and create new parser |

**Conclusion**: python-hslog fully supports real-time streaming parsing. The architecture is designed for incremental processing.

---

## 4. Integration Options

### Option A: HDT Plugin → File/Socket → Python

```
┌─────────────────────────┐         ┌──────────────────┐
│  HDT (C# Process)       │         │  Python Process   │
│                          │         │                   │
│  ┌───────────────────┐   │  JSON   │  ┌─────────────┐ │
│  │ HDT Plugin (DLL)  │──→│──file──→│  │ Analysis    │ │
│  │ OnUpdate() every  │   │ or      │  │ Backend     │ │
│  │ ~100ms, exports   │   │ socket  │  │ (scipy,     │ │
│  │ GameV2 state as   │   │         │  │  PyTorch)   │ │
│  │ JSON              │   │         │  └─────────────┘ │
│  └───────────────────┘   │         │                   │
└─────────────────────────┘         └──────────────────┘
```

**Architecture**:
1. HDT plugin implements `IPlugin`
2. `OnUpdate()` serializes `API.Core.Game` to JSON
3. Writes to named pipe / TCP socket / file
4. Python process reads and deserializes

**Pros**:
- Access to HDT's enriched state (secrets deduction, mulligan helper, deck detection)
- Access to HSReplay win rate data already fetched by HDT
- HDT handles all log parsing — Python gets clean state

**Cons**:
- Requires building and maintaining a C# DLL targeting .NET Framework 4.7.2
- Plugin runs on UI thread — must offload serialization to background thread
- Another moving part (IPC mechanism) that can fail
- HDT must be running for the bridge to work
- State serialization may be incomplete (GameV2 → JSON mapping needs manual work)

**Complexity**: Medium-High (~500 lines C# + IPC protocol design)

### Option B: Python Directly Watches Power.log (RECOMMENDED)

```
┌──────────────────────────────────────────────┐
│  Python Process                               │
│                                               │
│  ┌──────────────┐    ┌──────────────────┐    │
│  │ LogWatcher   │───→│ python-hslog     │    │
│  │ (file poll)  │    │ LogParser        │    │
│  │ 50ms interval│    │ EntityTreeExport │    │
│  └──────────────┘    └───────┬──────────┘    │
│                              │                │
│                    ┌─────────▼──────────┐     │
│                    │ hearthstone.entities│     │
│                    │ Game object         │     │
│                    │ (live game state)   │     │
│                    └─────────┬──────────┘     │
│                              │                │
│                    ┌─────────▼──────────┐     │
│                    │ Analysis Engine    │     │
│                    │ (scorers, search,  │     │
│                    │  lethal, predictor)│     │
│                    └────────────────────┘     │
│                                               │
│  Optionally: HDT Plugin (supplementary)       │
│  provides HSReplay win rates, deck detection  │
└──────────────────────────────────────────────┘
```

**Architecture**:
1. Python process polls Power.log file (50ms interval)
2. New lines fed to `LogParser.read_line()`
3. `EntityTreeExporter` maintains live `Game` entity tree
4. Analysis engine reads from `Game` object directly
5. Optionally: lightweight HDT plugin sends supplementary data (HSReplay win rates, detected deck)

**Pros**:
- No C# plugin required for core functionality
- Single-process architecture (Python only)
- python-hslog already handles all Power.log parsing
- `hearthstone.entities` provides complete game state model
- Independent of HDT — works even without HDT installed
- Simpler debugging and testing (pure Python)
- Aligns with existing hs_analysis Python codebase

**Cons**:
- No access to HDT's enriched state (secrets deduction, deck detection) unless plugin is also built
- Must handle Power.log file rotation between games
- No overlay UI (need separate display mechanism)
-python-hslog may lag behind Hearthstone patches

**Complexity**: Low-Medium (~200 lines for watcher + integration)

### Option C: HDT Plugin → HTTP API → Python

```
┌─────────────────────────┐         ┌──────────────────┐
│  HDT (C# Process)       │  HTTP   │  Python Process   │
│                          │  POST   │                   │
│  ┌───────────────────┐   │         │  ┌─────────────┐ │
│  │ HDT Plugin (DLL)  │──→│────────→│  │ FastAPI /   │ │
│  │ OnUpdate() or     │   │ :8080   │  │ Flask       │ │
│  │ GameEvents hooks  │   │         │  │ endpoint    │ │
│  │ push state as     │   │  HTTP   │  └──────┬──────┘ │
│  │ JSON              │←──│────────←│         │        │
│  │                   │   │ :8080   │  ┌──────▼──────┐ │
│  └───────────────────┘   │         │  │ Analysis    │ │
│                          │         │  │ Engine      │ │
└─────────────────────────┘         │  └─────────────┘ │
                                     └──────────────────┘
```

**Architecture**:
1. HDT plugin pushes game state to Python HTTP endpoint on each event
2. Python runs FastAPI/Flask server
3. Analysis results returned via HTTP response or separate endpoint

**Pros**:
- Clean separation of concerns
- Well-defined API contract
- Python analysis service can be remote (different machine)
- HTTP is easy to debug with curl/browser

**Cons**:
- Highest complexity — requires both C# plugin AND Python server
- HTTP overhead adds latency (1-5ms per request, significant at game speed)
- Plugin must manage HTTP client lifecycle on HDT's UI thread
- Two services must be started and managed
- Port conflicts possible

**Complexity**: High (~800 lines C# + Python server + API design)

### Option Comparison Matrix

| Criterion | Option A (Plugin→File) | Option B (Python→Log) | Option C (Plugin→HTTP) |
|-----------|----------------------|----------------------|----------------------|
| Core functionality | ✅ Full | ✅ Full | ✅ Full |
| Implementation effort | Medium-High | **Low-Medium** | High |
| Dependencies | HDT + C# toolchain | python-hslog only | HDT + C# + web framework |
| Latency | 100-200ms | 60-150ms | 150-300ms |
| Robustness | Medium (IPC can fail) | **High (single process)** | Low (many failure points) |
| HDT required? | Yes | **No** | Yes |
| Enriched state access | ✅ Yes | ❌ No (without plugin) | ✅ Yes |
| Testing ease | Hard (needs HDT running) | **Easy (replay from file)** | Hard (needs both services) |
| Overlay display | ✅ Via HDT | ❌ Separate | ✅ Via HDT |

---

## 5. Existing Projects & Prior Art

### 5.1 GitHub Search Results

**Search queries**: "hearthstone python powerlog", "hearthstone ai real-time", "hearthstone deck tracker python", "python-hslog real-time"

| Project | Stars | Status | Relevance |
|---------|-------|--------|-----------|
| HearthSim/python-hearthstone | ~400 | Active | Core dependency — log parser + entity model |
| HearthSim/hearthstone-log-watcher | ~50 | Maintained | Node.js log watcher pattern (reference for Python implementation) |
| HearthSim/Hearthstone-Deck-Tracker | ~5.5k | Active | HDT itself — plugin host |
| yellowbyte/hearthstoneAI | 3 | **Archived** | Python bot, unmaintained since 2023 |
| search: "hearthstone python real-time analysis" | — | — | No matching projects found |

### 5.2 No Existing Bridge Found

**No existing project bridges HDT to a Python analysis backend.** This is a gap that this project would fill. The closest components exist independently:
- python-hslog (parsing)
- hearthstone-log-watcher (file watching pattern, but Node.js)
- HDT plugin API (state export capability, but no Python consumer)

---

## 6. Recommended Approach

### Primary: Option B (Python Directly Watches Power.log)

**Rationale**:

1. **Minimal dependencies**: Only requires python-hearthstone (`pip install hearthstone`)
2. **Single-process**: Eliminates IPC complexity, reduces failure modes
3. **Testable**: Can replay Power.log files offline without Hearthstone or HDT running
4. **Sufficient for analysis**: Power.log contains all game state data needed for analysis (hand, board, secrets, health, mana)
5. **Already aligned**: hs_analysis project is Python-native; adding a C# component goes against the grain

### Supplementary: Lightweight HDT Plugin (Phase 2)

Add a minimal HDT plugin later for:
- HSReplay win rate data (already fetched by HDT)
- Deck archetype detection (HDT's deck recognition)
- Overlay display of analysis results
- Secrets probability (HDT's SecretsManager is more accurate than naive log parsing)

### Implementation Phases

#### Phase 1: Core Power.log Integration (1-2 days)

```
hs_analysis/
├── hs_analysis/
│   ├── watcher/                    # NEW
│   │   ├── __init__.py
│   │   ├── log_watcher.py          # File polling + rotation detection
│   │   ├── game_tracker.py         # Wraps python-hslog for live state
│   │   └── state_bridge.py         # Bridges Game entity → analysis models
│   └── ...existing modules...
├── scripts/
│   ├── run_watcher.py              # NEW: Start live analysis
│   └── ...existing scripts...
```

#### Phase 2: Analysis Engine Integration (2-3 days)

Connect game_tracker to existing scorers and search:
- `game_tracker.Game` → `scorers.v8_contextual` inputs
- `game_tracker.Game` → `search.rhea_engine` game state
- `game_tracker.Game` → `search.lethal_checker` lethal detection

#### Phase 3: HDT Plugin Bridge (3-5 days, optional)

Build a minimal C# plugin:
- Serializes enriched HDT state to JSON
- Writes to a named pipe or TCP socket
- Python reads for supplementary data

---

## 7. Architecture Diagram (Text)

```
┌──────────────────────────────────────────────────────────────────┐
│                    Hearthstone Client (Windows)                   │
│                                                                  │
│  Game Engine ──→ Power.log ──→ LoadingScreen.log                │
│                  (%LOCALAPPDATA%\Blizzard\Hearthstone\Logs\)     │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       │ File system (50ms polling)
                       │
          ┌────────────▼────────────────────────────────────┐
          │         hs_analysis (Python)                     │
          │                                                  │
          │  ┌──────────────────┐  ┌──────────────────────┐ │
          │  │  LogWatcher      │  │  GameTracker          │ │
          │  │  - polls file    │→│  - LogParser (hslog)  │ │
          │  │  - detects       │  │  - EntityTreeExporter │ │
          │  │    rotation      │  │  - Maintains Game     │ │
          │  └──────────────────┘  │    entity tree        │ │
          │                        └──────────┬───────────┘ │
          │                                   │              │
          │                        ┌──────────▼───────────┐ │
          │                        │  StateBridge          │ │
          │                        │  Game entity →        │ │
          │                        │  analysis-ready state │ │
          │                        └──────────┬───────────┘ │
          │                                   │              │
          │              ┌────────────────────┼────────────┐ │
          │              │                    │            │ │
          │  ┌───────────▼──────┐ ┌──────────▼──────┐ ┌──▼──────────────┐
          │  │ Scorers          │ │ Search Engine   │ │ Lethal Checker  │
          │  │ (V2/V7/V8/L6)   │ │ (RHEA)         │ │ (DFS/BFS)       │
          │  └──────────────────┘ └─────────────────┘ └─────────────────┘
          │              │                    │            │
          │              └────────────────────┼────────────┘
          │                          ┌───────▼────────┐
          │                          │ Decision Output │
          │                          │ (ranked actions) │
          │                          └────────────────┘
          │                                         │
          │  ┌──────────────────────────────────────┘
          │  │ Optional: HDT Plugin (Phase 3)
          │  │ ┌───────────────────┐     ┌─────────────────┐
          │  │ │ HDT Plugin (C#)  │────→│ Supplementary   │
          │  │ │ - HSReplay data  │named│ data channel    │
          │  │ │ - Deck detection │pipe │ (win rates,     │
          │  │ │ - Secrets prob   │     │  deck archetype) │
          │  │ └───────────────────┘     └─────────────────┘
          │  └───────────────────────────────────────────
          └──────────────────────────────────────────────────┘
```

---

## 8. Key Dependencies

| Dependency | Version | Purpose | Risk |
|-----------|---------|---------|------|
| `hearthstone` (python-hearthstone) | Latest | Power.log parsing, entity model | **Medium** — may lag behind Hearthstone patches |
| `hearthstone.enums` | Included in above | GameTag, Zone, etc. | Low — enums are stable |
| Python 3.11+ | — | Runtime | Low |
| Windows OS | — | Hearthstone + Power.log location | **Medium** — macOS Hearthstone doesn't produce Power.log |

### Dependency Risk: python-hearthstone Patch Lag

python-hearthstone is maintained by HearthSim, the same org that maintains HDT. It typically updates within days of a Hearthstone patch. The parser is regex-based and tolerant of unknown packets (it logs warnings but doesn't crash). **Mitigation**: Pin the library version and monitor HearthSim releases.

---

## 9. Key Risks

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|
| python-hslog breaks after HS patch | Analysis stops | Medium | Pin version; HearthSim usually updates fast |
| Power.log format changes | Parser crashes | Low | Format has been stable for years |
| File rotation not detected | Lost game state | Medium | Robust rotation detection in LogWatcher |
| Windows-only (Power.log) | macOS/Linux not supported | Certain | Document requirement; CI can test with recorded logs |
| Latency too high for real-time | Stale analysis | Low | 50-100ms polling is sufficient; HS is turn-based |
| python-hslog missing new entity types | Incomplete state | Low | Entity model is tag-based; new tags are numeric, still parsed |

---

## 10. Estimated Implementation Effort

| Phase | Component | Effort | Dependencies |
|-------|-----------|--------|-------------|
| Phase 1a | `LogWatcher` (file polling, rotation) | 3-4 hours | None |
| Phase 1b | `GameTracker` (wraps python-hslog) | 4-6 hours | python-hslog |
| Phase 1c | `StateBridge` (entity → analysis model) | 3-4 hours | Existing scorers |
| Phase 1d | `run_watcher.py` (CLI entry point) | 1-2 hours | Phase 1a-c |
| Phase 1e | Testing with recorded Power.log | 2-3 hours | Sample log files |
| **Phase 1 Total** | | **13-19 hours** | |
| Phase 2 | Analysis engine integration | 16-24 hours | Phase 1 |
| Phase 3 | HDT plugin (optional) | 24-40 hours | Phase 1+2, C# toolchain |

---

## 11. Immediate Next Steps

1. **Install python-hearthstone**: `pip install hearthstone`
2. **Get a sample Power.log**: Record a game and save the log file
3. **Prototype LogWatcher**: Basic file polling with rotation detection
4. **Prototype GameTracker**: Feed sample Power.log through LogParser → EntityTreeExporter → verify state
5. **Design StateBridge**: Map `hearthstone.entities.Game` fields to `hs_analysis.models.card.Card` + `hs_analysis.search.game_state.GameState`
6. **Validate latency**: Measure end-to-end delay from game event to analysis output

---

## Appendix A: Power.log File Rotation Detection

When Hearthstone starts a new game, it may create a fresh Power.log (or truncate the existing one). Detection strategy:

```python
import os

class LogWatcher:
    def __init__(self, path):
        self.path = path
        self.position = 0
        self.last_size = 0
        self.last_mtime = 0

    def check_rotation(self):
        """Detect file rotation by checking if file shrank."""
        if not os.path.exists(self.path):
            self.position = 0
            return True

        stat = os.stat(self.path)
        if stat.st_size < self.position:
            # File was truncated (rotation)
            self.position = 0
            return True
        return False
```

## Appendix B: python-hslog Minimal Streaming Example

```python
import time
import os
from hearthstone.hslog.parser import LogParser
from hearthstone.hslog.export import EntityTreeExporter
from hearthstone.enums import Zone

class LiveGameTracker:
    def __init__(self, log_path):
        self.log_path = log_path
        self.parser = LogParser()
        self.exporter = None
        self.game = None
        self.position = 0

    def process_new_lines(self):
        if not os.path.exists(self.log_path):
            return

        # Check rotation
        if os.path.getsize(self.log_path) < self.position:
            self.parser = LogParser()
            self.exporter = None
            self.game = None
            self.position = 0

        with open(self.log_path, "r", encoding="utf-8") as f:
            f.seek(self.position)
            for line in f:
                self.parser.read_line(line)
            self.position = f.tell()

        # Export current state
        if self.parser.game_state_data:
            if self.exporter is None:
                self.exporter = EntityTreeExporter(self.parser.game_state_data)
            self.game = self.exporter.export()

    def get_board_state(self):
        if not self.game:
            return None
        return {
            "player_board": self.game.current_player.in_zone(Zone.PLAY),
            "opponent_board": self.game.current_player.opponent.in_zone(Zone.PLAY),
            "player_hand": self.game.current_player.in_zone(Zone.HAND),
        }

    def run(self, interval=0.05):
        while True:
            self.process_new_lines()
            if self.game:
                state = self.get_board_state()
                # Feed to analysis engine...
            time.sleep(interval)
```

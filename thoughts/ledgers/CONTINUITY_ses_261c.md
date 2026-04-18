---
session: ses_261c
updated: 2026-04-18T01:44:43.816Z
---

# Session Summary

## Goal
Analyze the HSTracker GitHub repository (https://github.com/HearthSim/HSTracker) to understand its architecture, tech stack, card data models, game state detection mechanisms, and extract insights relevant to building a Hearthstone AI/mathematical modeling system.

## Constraints & Preferences
- Focus especially on: game state detection, card data sources, deck tracking/card recognition, and any algorithms for card evaluation or deck building
- No local files were modified; this was a read-only repository analysis
- User's ultimate goal appears to be building a Hearthstone AI/mathematical modeling system

## Progress
### Done
- [x] Fetched and read README.md — confirmed HSTracker is a macOS-only Hearthstone deck tracker/deck manager, part of HearthSim ecosystem, v3.5.4, MIT license
- [x] Mapped full repository structure: 20+ directories under `HSTracker/`, identified all key modules
- [x] Identified tech stack: Swift, macOS/AppKit, Realm DB, HearthMirror (C/ObjC memory reader), Mono/.NET (BobsBuddy sim), HearthstoneJSON API, HSReplay.net API, Mixpanel analytics, Travis CI + Fastlane
- [x] Analyzed dual game state detection approach: (1) HearthMirror memory reading via `HSTracker/HearthMirror/MirrorHelper.swift` using `acquireTaskportRight()` + PID-based process memory access, (2) PowerLog file parsing via `HSTracker/Logging/Parsers/PowerGameStateParser.swift` (104KB)
- [x] Read full `HSTracker/Database/Models/Card.swift` (15KB) — documented all card properties: `id`, `dbfId`, `cost`, `attack`, `health`, `text`, `playerClass`, `rarity`, `type`, `race`/`races`, `set`, `mechanics`, `collectible`, `spellSchool`, `techLevel`, `multiClassGroup`, `overload`, `isStandard`, plus runtime tracking state (`count`, `jousted`, `isStolen`, `isCreated`, `wasDiscarded`)
- [x] Read `HSTracker/Hearthstone/HearthDbConverter.swift` — converts between Mirror deck format and internal deck format
- [x] Read `HSTracker/HearthMirror/MirrorHelper.swift` — full Swift wrapper exposing 30+ mirror methods (getBattleTag, getDecks, getCollection, getArenaInfo, getGameType, isSpectating, getBattlegroundsRatingInfo, getCardChoices, getDiscoverState, etc.)
- [x] Analyzed card data source: `scripts/cards_download.sh` downloads from `https://api.hearthstonejson.com/v1/latest/{locale}/cards.json` for 13 locales, stored as `Resources/Cards/cardsDB.{locale}.json`
- [x] Mapped all 30+ enum files in `HSTracker/Logging/Enums/` — key ones: `GameTag.swift` (13KB, hundreds of tags), `CardClass.swift`, `CardType.swift`, `Race.swift`, `Rarity.swift`, `CardSet.swift`, `Zone.swift`, `SpellSchool.swift`, `PlayState.swift`
- [x] Analyzed BobsBuddy Battlegrounds simulator: `HSTracker/BobsBuddy/BobsBuddyInvoker.swift` (64KB) orchestrates Monte Carlo combat simulations via embedded Mono/.NET runtime; `HSTracker/Mono/` has 30+ proxy files for entity representation (MinionProxy, PlayerProxy, EnchantmentProxy, TrinketProxy, etc.)
- [x] Analyzed secret elimination system: `HSTracker/Hearthstone/Secrets/SecretsManager.swift` (36KB) uses constraint propagation to deduce opponent secrets
- [x] Analyzed deck serialization: `HSTracker/Importers/DeckSerializer.swift` (10KB) implements Hearthstone deckstring format (base64/Crockford Base32) with sideboard support
- [x] Identified gaps for AI: no game tree search, no card evaluation function, no mulligan optimization algorithm, no constructed combat probability calculator, no deck building algorithm

### In Progress
- [ ] (none — analysis was completed in one session)

### Blocked
- (none)

## Key Decisions
- **Analyzed v3.5.4 tag** rather than main branch: This is the latest tagged release, providing a stable snapshot of the codebase
- **Focused on Logging/ and Database/ directories**: These contain the game state detection and card data models most relevant to AI/modeling work, rather than UI code

## Next Steps
1. If building a Hearthstone AI, the most actionable next step would be to download the card JSON database from `https://api.hearthstonejson.com/v1/latest/enUS/cards.json` and design a card data model inspired by `Card.swift`
2. Study the `GameTag.swift` enum (13KB, `HSTracker/Logging/Enums/GameTag.swift`) for a complete list of all Hearthstone entity attributes — this is essential for any game state representation
3. Examine the BobsBuddy simulation approach (`HSTracker/Mono/SimulationRunner.swift` and `HSTracker/Mono/MonoHelper.swift`) as a reference for Monte Carlo combat simulation
4. Look at the HearthSim `hslog` Rust library (referenced in `scripts/compile_hslog.sh`) for a cleaner PowerLog parser implementation
5. Consider examining the sibling repository `HearthMirror` for understanding the full memory reading API

## Critical Context
- The `Game.swift` file (181KB) is the largest single file and contains the complete game state machine — too large to read in full but would be essential for understanding turn-by-turn state transitions
- `PowerGameStateParser.swift` (104KB) and `TagChangeActions.swift` (64KB) together define how every Hearthstone game event is processed — these would be the primary reference for understanding game event flow
- The HearthstoneJSON API (`api.hearthstonejson.com`) is the simplest way to get complete card data without scraping or memory reading
- `hs-build-dates.json` in repo root maps every Hearthstone build number (3140–20457) to release dates — useful for correlating game versions
- BobsBuddy is BG-only; for constructed play AI, there is no existing simulation code in this repo
- The `CardWinrates` class (`mulliganWinRate`, `baseWinrate`) suggests HSReplay.net provides per-card win rate data that could feed an AI evaluation function
- The `FakeCard` class in `Card.swift` handles cards created by other cards (e.g., "Created by Fireball") using base64-encoded JSON card IDs prefixed with "CREATED_BY_"

## File Operations
### Read
- (none — all analysis was done via GitHub API, no local file operations)

### Modified
- (none)

---
session: ses_261a
updated: 2026-04-18T02:16:17.655Z
---

# Session Summary

## Goal
Produce a deep technical analysis of jleclanche/fireplace (Hearthstone Python simulator) to determine if it can serve as a real-time game simulator for an MCTS-based AI, covering 9 specific areas: card coverage, architecture, performance, extensibility, python-hearthstone integration, AI/MCTS integration, game state serialization, missing features, and maintenance.

## Constraints & Preferences
- Must return detailed technical findings, not surface-level observations
- User needs to understand limitations for MCTS suitability specifically
- Analysis must be actionable for deciding whether to use fireplace as an MCTS simulation backend

## Progress
### Done
- [x] Fetched README.md — card coverage: 23 sets at 100% (Basic through Ashes of Outlands + Demon Hunter Initiate), patch 17.6.0.53261, Scholomance Academy only 1 of 1 card
- [x] Fetched last 30 commits — latest commit Dec 19, 2025 by shinoi2 (sole active contributor); commits include Outland cards, dormant mechanic, RNG seed support, Galakrond Invoke rewrite, Zephrys implementation
- [x] Fetched all 17 open issues — oldest from 2015, key ones: #342 (pickle support requested, open since 2016), #341 (GameState __eq__/temp_hash for AI, open), #343 (selector optimization for 2-3x speedup, open), #302 (profiling data: 0.238s per full game)
- [x] Read full `fireplace/game.py` — Game class uses multiple inheritance (MulliganRules, CoinRules, BaseGame); turn structure: begin_turn → _begin_turn (mana, draw) → end_turn → _end_turn → end_turn_cleanup; seedable Random instance; action_stack tracking; refresh_auras + process_deaths on empty stack
- [x] Read full `fireplace/actions.py` — Action metaclass with ActionArg system; GameAction (Attack, BeginTurn, EndTurn, Play, Death, etc.); TargetedAction (Buff, Damage, Heal, Draw, Summon, Morph, Destroy, Discover, Choice, etc.); EventListener ON/AFTER broadcast system; callback chaining via `.then()`
- [x] Read full `fireplace/entity.py` — BaseEntity → BuffableEntity → Entity hierarchy; tag system via Manager subclasses; boolean_property/int_property/slot_property decorators for tag access; buff stacking via _getattr chain; update_scripts generator for aura refresh
- [x] Read full `fireplace/card.py` — Card() factory dispatches by CardType to Hero/Minion/Spell/Secret/Quest/SideQuest/Enchantment/Weapon/HeroPower; zone transitions with _set_zone; PlayableCard.is_playable() checks 20+ PlayReq conditions; Minion handles dormant, divine shield, enrage, silence, reborn; Character handles attack/frozen/exhausted/stealth
- [x] Read full `fireplace/managers.py` — Manager base with GameTag→attribute map; GameManager (entity_id counter, observer notifications); PlayerManager (~30 tag mappings); CARD_ATTRIBUTE_MAP (~120 tag mappings); BaseObserver pattern for external hooks
- [x] Read full `fireplace/dsl/selector.py` — Full selector DSL: EnumSelector, ComparisonSelector, FilterSelector, FuncSelector, RandomSelector, SetOpSelector (+, |, -), SliceSelector; predefined selectors: FRIENDLY_MINIONS, ENEMY_HERO, RANDOM_MINION, CTHUN, etc.; AttrValue for ARMOR/ATK/COST/DAMAGE comparisons
- [x] Read full `fireplace/aura.py` — AuraBuff with tick-based lifecycle; Refresh class for aura tag/buff updates; TargetableByAuras mixin
- [x] Read full `fireplace/utils.py` — CardList (identity-based contains/index/remove); random_draft(); play_turn() (random bot: 50% play chance, 10% hero power); play_full_game(); game_state_to_xml() serialization
- [x] Read `setup.cfg` — dependencies: `hearthstone` and `hearthstone_data` packages; Python 3.10+
- [x] Listed card directories — 25+ set directories (blackrock, boomsday, classic, dalaran, dragons, gangs, gvg, icecrown, karazhan, kobolds, league, naxxramas, outlands, scholomance, tgt, troll, uldum, ungoro, witchwood, wog, custom, debug, game, initiate, skins, brawl)
- [x] Listed test files — 30+ test files covering all implemented sets
- [x] Searched codebase for "MCTS", "monte carlo", "tree search", "deep copy", "pickle" — **ZERO results**
- [x] Searched GitHub for "hearthstone MCTS AI fireplace simulator python" — **ZERO results**
- [x] Searched GitHub for "hearthstone AI bot MCTS language:python" — **ZERO results**

### In Progress
- [ ] Synthesize all gathered data into the 9-section technical analysis the user requested
- [ ] The actual analysis response has NOT been written yet — all data collection is complete

### Blocked
- (none)

## Key Decisions
- **Gathered data from source code directly rather than relying on documentation**: The README, wiki, and docs are minimal; actual architecture understanding required reading game.py, actions.py, entity.py, card.py, managers.py, selector.py
- **Searched for MCTS/pickle specifically**: These are critical for the user's use case; finding zero results is itself an important finding

## Next Steps
1. Write the comprehensive 9-section technical analysis synthesizing all gathered data
2. Specifically address the MCTS suitability question with evidence from profiling data (0.238s/game from issue #302), lack of pickle/deepcopy support (issue #342), lack of state hashing (issue #341), and selector performance bottleneck (issue #343)
3. Highlight the critical gap: no `__deepcopy__`, no `__eq__`, no pickle support — all explicitly requested as open issues but never implemented

## Critical Context
- **Performance baseline**: Issue #302 profiling shows a full random-vs-random game takes **0.238 seconds** (~4.2 games/sec). Top bottleneck: `selector.py:140(test)` at 0.087s cumulative, `selector.py:183(test)` at 0.025s. Selector evaluation is ~37% of total time. Issue #343 proposes filter-based selectors for 2-3x speedup but was never implemented.
- **No state copying mechanism exists**: Issue #342 (open since 2016) requests pickle support — "Last time I tried, pickle errored out." No `__deepcopy__` or `__copy__` methods anywhere in the codebase. This is a **hard blocker** for MCTS tree search.
- **No state hashing**: Issue #341 (open since 2016) requests `__eq__` and `temp_hash()` for AI state deduplication. Never implemented.
- **Seedable RNG**: `BaseGame.__init__` accepts `seed` parameter passed to `Random(seed)` — good for reproducibility but the seedable RNG is per-game, not per-action, which matters for MCTS.
- **Observer pattern exists**: `BaseObserver` in managers.py provides hooks for `action_start`, `action_end`, `new_entity`, `game_action`, `targeted_action` — potential integration point for AI.
- **game_state_to_xml()** exists in utils.py but produces XML, not a compact/fast serialization format.
- **play_turn()** in utils.py is a simple random bot — the only built-in AI, no MCTS integration anywhere.
- **Card coverage stops at Ashes of Outlands** (April 2020 set) — missing ~5 years of card sets (Scholomance through present, only 1 Scholomance card implemented).
- **Sole active contributor**: shinoi2, all commits since at least 2024. Original author jleclanche appears inactive.
- **python-hearthstone integration**: fireplace depends on `hearthstone` package (enums, cardxml) and `hearthstone_data` (card definitions). Card scripts in fireplace/cards/ override/augment the XML data with Python implementations.
- **Card effect definition pattern**: Each card set is a Python package with files per class. Cards use a script system where `data.scripts.play`, `data.scripts.deathrattle`, `data.scripts.events`, etc. contain lists of Action objects. Example pattern visible in card directory structure.

## File Operations
### Read
- `README.md` — card coverage list, patch version, dependencies
- `fireplace/game.py` — full game engine, turn structure, Game/CoinRules/MulliganRules classes
- `fireplace/actions.py` — full action system (~71KB), all GameAction and TargetedAction subclasses
- `fireplace/entity.py` — entity hierarchy, property decorators, buff system
- `fireplace/card.py` — all card type classes (~55KB), zone management, playability checks
- `fireplace/managers.py` — tag mapping system, observer pattern, BaseObserver
- `fireplace/dsl/selector.py` — full selector DSL (~23KB), all predefined selectors
- `fireplace/aura.py` — aura buff system, Refresh mechanism
- `fireplace/utils.py` — CardList, random bot, game_state_to_xml
- `setup.cfg` — package dependencies
- Commit history (last 30 commits)
- Open issues (17 total, with full text of #302 profiling data, #341, #342, #343)

### Modified
- (none)

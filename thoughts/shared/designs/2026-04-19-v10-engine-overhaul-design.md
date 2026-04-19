---
date: 2026-04-19
topic: "V10 Engine Overhaul: 2026 Mechanic Coverage & Foundation Repair"
status: draft
---

# Problem Statement

The V9 RHEA decision engine can simulate basic Hearthstone turns (attack, play minion, spell damage), but **33% of the 1015-card 2026 Standard pool has Battlecry, 14% has Deathrattle, and an entire layer of modern mechanics (Imbue, Herald, Shatter, Kindred, Rewind) is completely absent**. The engine makes decisions as if Hearthstone still had 2018-level card complexity.

**Specific failures:**
- Cards with Battlecry play as vanilla minions (334 cards affected)
- Cards with Deathrattle die without effect (139 cards affected)
- Discover is a no-op (80 cards affected)
- Spell targeting is always auto-resolved — no player choice simulation
- Hand position doesn't matter (breaks Shatter, Outcast, Hand Targeting)
- Hero power is a flat 2-mana toggle with no class-specific behavior
- No tracking of: overload, combo, fatigue, windfury second attack, quest progress

**Goal:** Build the foundation layers (enchantment framework, trigger system, hand position tracking) that make implementing every 2026 mechanic feasible, and fix the critical correctness bugs first.

---

# Constraints

1. **Backward compatibility** — All 362 existing tests must continue to pass
2. **No external dependencies** — Pure Python, no new packages
3. **Performance** — RHEA search must still complete in <250ms for typical turns
4. **Incremental** — Each phase ships independently; no "big bang" rewrite
5. **Real card data** — All tests use `DeckTestGenerator` with `unified_standard.json`
6. **Chinese regex** — Card text is in Chinese; all parsers must handle Chinese patterns

---

# Approach: Three-Phase Layered Overhaul

**Why this approach:** The engine has a solid evolutionary search core. The problem isn't the search algorithm — it's the *simulation fidelity*. We don't need a new engine; we need a richer simulation layer. This is a bottom-up repair: fix broken basics first, then add the abstraction layer that makes new mechanics plug-and-play.

**Alternatives considered:**
- **Full rewrite** — Rejected: RHEA loop, evaluation, and action normalization are solid. Rewriting risks regression on 362 passing tests.
- **Plugin architecture** — Rejected: Over-engineered for a single-player simulation. The engine doesn't need hot-swappable mechanics; it needs correct mechanics.
- **Text-to-effect ML parser** — Rejected: Too much complexity, fragile, requires training data. Regex patterns with manual dispatch work for 1000 cards.

---

# Architecture

## Phase 1: Fix Broken Foundations (Bug Fixes + Core Mechanics)

### 1.1 Lethal Checker Taunt Bug Fix

**Problem:** In `lethal_checker.py:_enumerate_damage_actions`, charge minions bypass taunt (line 126-133), but in `rhea_engine.py:enumerate_legal_actions`, charge minions must attack through taunt. The lethal checker finds "lethal" sequences that are actually illegal.

**Fix:** Align `_enumerate_damage_actions` taunt logic with `enumerate_legal_actions`. If enemy has taunt minions, all attack actions (including charge) must target taunt first.

### 1.2 Windfury Second Attack

**Problem:** After attacking, `apply_action` sets `can_attack=False` unconditionally. Windfury minions should get a second attack.

**Fix:** Add `has_attacked_once: bool = False` to `Minion`. After attack:
- If minion has windfury and `has_attacked_once == False`: set `has_attacked_once=True`, keep `can_attack=True`
- Otherwise: set `can_attack=False`

In `enumerate_legal_actions`, a minion can attack if: `can_attack OR (has_windfury AND has_attacked_once AND NOT already_attacked_this_action)`

### 1.3 Overload Parsing and Application

**Problem:** `ManaState` has `overloaded` and `overload_next` fields but they're never populated or applied.

**Fix:**
- Parse overload from card text: regex `过载[：:]\s*[（(]\s*(\d+)\s*[）)]` in `apply_action` when PLAY
- Set `mana.overload_next += parsed_value`
- At turn start (END_TURN → next turn): `mana.available -= mana.overloaded`, `mana.overloaded = mana.overload_next`, `mana.overload_next = 0`

### 1.4 Poisonous Instant Kill

**Problem:** Poisonous minions deal normal damage instead of killing outright.

**Fix:** In `apply_action` attack resolution, after damage calculation:
```
if attacker.has_poisonous and target is minion:
    target.health = 0
```
This happens BEFORE divine shield check (poisonous doesn't bypass shield — the shield absorbs the hit, and the minion survives that instance).

### 1.5 Combo Tracking

**Problem:** No tracking of cards played this turn. Combo cards never get their bonus.

**Fix:** Add `cards_played_this_turn: List[Card] = []` to `GameState`. In `apply_action` PLAY, append the card. Reset on END_TURN. In `enumerate_legal_actions`, check `len(state.cards_played_this_turn) > 0` for combo eligibility.

### 1.6 Fatigue Damage

**Problem:** Drawing from empty deck doesn't deal fatigue damage.

**Fix:** `GameState.fatigue_damage` exists but unused. When `apply_draw` is called and `deck_remaining <= 0`:
- `state.fatigue_damage += 1`
- `state.hero.hp -= state.fatigue_damage`

### 1.7 Stealth Break on Attack

**Problem:** Stealth minions can attack without losing stealth.

**Fix:** In `apply_action` attack resolution, after the attack: `attacker.has_stealth = False`

### 1.8 Freeze Effect

**Problem:** Freeze keyword stored but doesn't prevent attacks.

**Fix:** Add `frozen_until_next_turn: bool = False` to `Minion`. In `enumerate_legal_actions`, skip minions with `frozen_until_next_turn == True`. Reset on END_TURN.

---

## Phase 2: Enchantment Framework + Trigger System

### 2.1 Enchantment Data Model

**New data structure** in `game_state.py`:

```python
@dataclass
class Enchantment:
    enchantment_id: str          # Unique identifier
    name: str                    # Display name
    source_dbf_id: int           # Card that created this
    attack_delta: int = 0        # +attack modifier
    health_delta: int = 0        # +health modifier
    max_health_delta: int = 0    # +max_health modifier
    cost_delta: int = 0          # +cost modifier (for hand cards)
    keywords_added: List[str] = field(default_factory=list)
    keywords_removed: List[str] = field(default_factory=list)
    trigger_type: str = ""       # "deathrattle", "end_of_turn", "start_of_turn", "on_attack", "aura"
    trigger_effect: str = ""     # Effect description for dispatch
    duration: int = -1           # -1 = permanent, >0 = turns remaining
```

**Integration into Minion:**
```python
@dataclass
class Minion:
    # ... existing fields ...
    enchantments: List[Enchantment] = field(default_factory=list)
```

**Computed stats:** `minion.attack` becomes a property that sums `base_attack + sum(e.attack_delta for e in enchantments)`. Same for health, keywords, etc.

### 2.2 Trigger Dispatcher

**New module** `trigger_system.py`:

```python
class TriggerDispatcher:
    def on_minion_played(self, state, minion, card) -> GameState
    def on_minion_dies(self, state, minion) -> GameState
    def on_turn_end(self, state) -> GameState
    def on_turn_start(self, state) -> GameState
    def on_attack(self, state, attacker, target) -> GameState
    def on_spell_cast(self, state, card) -> GameState
    def on_damage_dealt(self, state, target, amount) -> GameState
    def on_heal(self, state, target, amount) -> GameState
```

**Integration:** Each `apply_action` call dispatches events through `TriggerDispatcher`. Deathrattles fire in `on_minion_dies`. End-of-turn effects fire in `on_turn_end`. Auras recompute in all events.

### 2.3 Battlecry Dispatcher

**New function** in `spell_simulator.py` (or new file `battlecry_dispatcher.py`):

Parse battlecry text from card and apply effects using the same regex patterns as spell effects:
- "战吼：造成N点伤害" → apply damage
- "战吼：召唤N/N" → summon
- "战吼：发现" → discover (pick best from 3 random cards)
- "战吼：抽N张牌" → draw
- "战吼：+N/+N" → buff (self or target)

**Targeting:** For battlecries that need targets, generate all valid targets and evaluate the best one (greedy: pick target that maximizes `evaluate()`).

### 2.4 Deathrattle Queue

**In `_resolve_deaths`:**

1. Collect all minions with `health <= 0` from both boards
2. For each dead minion, check if it has deathrattle (keyword OR enchantment with `trigger_type="deathrattle"`)
3. Queue deathrattles in board-position order (left to right)
4. Execute each deathrattle effect via `TriggerDispatcher.on_minion_dies`
5. Re-check for new deaths (cascade)

### 2.5 Aura Engine

**Aura = continuous enchantment that recalculates each frame.**

Implementation:
- Mark certain enchantments as `trigger_type="aura"`
- After every state change (play, attack, death), recompute all auras:
  1. Remove all aura enchantments
  2. For each minion with aura text, re-apply the enchantment to valid targets
- Aura targets: `all_friendly`, `adjacent`, `self`, `leftmost`, `rightmost`, `hand_cards`

### 2.6 Discover Framework

**Current:** Discover is a no-op keyword.

**New behavior:** When a card with DISCOVER is played:
1. Generate 3 random cards from the appropriate pool (same class + neutral, matching constraints)
2. Evaluate `state_with_card_added` for each option using `evaluate()`
3. Pick the highest-evaluated card
4. Add it to hand

**Pool selection** based on card text:
- "发现一张..." → specific type/race filter
- "发现一张法术" → spells only
- Generic discover → all collectible cards of class + neutral

### 2.7 Location Card Support

**New behavior:** Location cards are a separate card type (`card_type="LOCATION"`).
- When played, placed in a `locations: List[Location]` field on GameState (separate from board)
- Location has `durability` (number of uses) and `cooldown` (turns until next use)
- Can be activated as an action type: `HERO_POWER` → `ACTIVATE_LOCATION`
- Locations don't count toward the 7-minion board limit

---

## Phase 3: 2026 Modern Mechanics

### 3.1 Imbue (灌注) — Hero Power Upgrade System

**Mechanic:** Playing an Imbue card upgrades your hero power. Each class has a unique upgrade path.

**Implementation:**
- Add `imbue_level: int = 0` to `HeroState`
- When `apply_action` plays a card with IMBUE mechanic: `state.hero.imbue_level += 1`
- Hero power effect scales with `imbue_level`:
  - Druid: Summon a `{imbue_level}/{imbue_level}` Plant Golem
  - Hunter: Deal `{1 + imbue_level}` damage
  - Mage: etc. (class-specific lookup table)
- `enumerate_legal_actions` generates `HERO_POWER` action when `!hero_power_used AND mana >= hero_power_cost`

### 3.2 Hand Position System

**Mechanic:** Shatter, Outcast, and Hand Targeting all care about card positions in hand.

**Implementation:**
- Change `hand: List[Card]` to an indexed structure (still a list, but with position awareness)
- `hand[0]` = leftmost, `hand[-1]` = rightmost
- **Outcast check:** When playing a card with OUTCAST, check if `card_index == 0 or card_index == len(hand) - 1`
- **Shatter:** When drawing a card with SHATTER, insert two halves at positions 0 and -1 instead of the single card. Track paired halves. When halves become adjacent (no cards between them), merge into combined card.
- **Hand Targeting:** New action type `TARGET_HAND_CARD` with `source_card_index` and `target_card_index`
- **Generated cards:** Always appended to rightmost position (already the default with `hand.append()`)

### 3.3 Herald (兆示) — Progressive Upgrade Counter

**Mechanic:** Herald summons a Soldier and increments a counter. At 2 and 4 Herald uses, your Colossal and Deathwing Hero Card upgrade.

**Implementation:**
- Add `herald_count: int = 0` to `GameState`
- When playing a card with HERALD mechanic:
  - `state.herald_count += 1`
  - Summon a Soldier minion (class-specific, from a lookup table)
  - If `herald_count == 2 or herald_count == 4`: upgrade the class Colossal card in hand/deck
- Colossal appendage stats scale with upgrade level: `base_stats * (1 + herald_count // 2)`

### 3.4 Kindred (延系) — Previous Turn Race/School Tracking

**Mechanic:** Cards with Kindred get a bonus if you played a card of the same minion type or spell school on your previous turn.

**Implementation:**
- Add `last_turn_played_races: Set[str]` and `last_turn_played_schools: Set[str]` to `GameState`
- On END_TURN: snapshot the races/schools of cards played this turn into `last_turn_*`
- When evaluating a Kindred card: check if its race/school intersects `last_turn_*`
- If bonus applies: add the bonus effect (parsed from card text) to the evaluation

### 3.5 Colossal Appendage Summoning

**Mechanic:** Colossal+N minions summon N appendages when played.

**Implementation:**
- Parse "巨型+N" from card text or `COLOSSAL` mechanic with a number
- When `apply_action` plays a Colossal minion:
  - Insert the main body at the chosen position
  - Insert N appendage minions to the right of the main body
  - Appendages are class-specific minions defined in a lookup table
- If board is nearly full (e.g., 6 minions with Colossal+2), only place what fits

### 3.6 Quest Progress Tracking

**Mechanic:** Quests are 1-cost spells that start in hand. Track progress and grant reward on completion.

**Implementation:**
- Add `active_quests: List[QuestState]` to `GameState`
- `QuestState` has: `quest_card`, `progress: int`, `threshold: int`, `reward_card`
- Quest progress tracked by type: "play X spells", "summon X minions", etc.
- When `apply_action` plays a quest card: add to `active_quests`
- Each action checks and increments relevant quest progress
- When progress >= threshold: add reward card to hand, remove quest

### 3.7 Dark Gift Pool

**Mechanic:** When Discovering a minion (in DK, DH, Rogue, Warlock, Warrior), each option gets a random Dark Gift bonus.

**Implementation:**
- Define 10 Dark Gift enchantments as constant list
- In the Discover framework, when the discovering class is a Dark Gift class AND discovering a minion:
  - For each of the 3 Discover options, roll a random Dark Gift
  - Apply the enchantment to the option
  - Evaluate all 3 and pick the best combination

### 3.8 Rewind (回溯) — Branching Simulation

**Mechanic:** Play a card, then optionally rewind to try a different random outcome.

**Implementation:**
- For Rewind cards, evaluate as follows:
  1. Save state snapshot
  2. Play the card, evaluate outcome
  3. Restore snapshot, play again (different random seed), evaluate
  4. Pick the better outcome
- This is a 2-branch evaluation within the RHEA fitness function
- Each branch costs 1 fitness evaluation instead of 2 (share the state copy)

---

# Components

## New Files
- `hs_analysis/search/trigger_system.py` — TriggerDispatcher class
- `hs_analysis/search/enchantment.py` — Enchantment dataclass, aura computation
- `hs_analysis/search/battlecry_dispatcher.py` — Battlecry text parser + effect applier
- `hs_analysis/search/discover.py` — Discover pool generation, option evaluation, Dark Gift integration
- `hs_analysis/search/modern_mechanics.py` — Imbue, Herald, Kindred, Shatter, Quest, Colossal helpers
- `hs_analysis/search/location.py` — Location card support

## Modified Files
- `game_state.py` — Add Enchantment to Minion, Location to GameState, hand position awareness, new counters
- `rhea_engine.py` — Wire trigger dispatch into apply_action, add HERALD/IMBUE/KINDRED checks
- `lethal_checker.py` — Fix charge-vs-taunt bug
- `spell_simulator.py` — Refactor to registry pattern, add English patterns, extend targeting
- `risk_assessor.py` — Add class-specific AoE for DH, DK, Rogue, Shaman, Warrior
- `opponent_simulator.py` — Consider opponent hand size, hero power, windfury, divine shield in trades

---

# Data Flow (Phase 2+)

```
User plays card → apply_action()
  ├── PLAY MINION
  │   ├── Deduct mana
  │   ├── Create Minion with mechanics
  │   ├── Insert at position
  │   ├── trigger.on_minion_played()  ← NEW
  │   │   ├── Battlecry dispatch      ← NEW
  │   │   ├── Discover resolution     ← NEW
  │   │   ├── Imbue check             ← NEW (Phase 3)
  │   │   └── Herald check            ← NEW (Phase 3)
  │   └── Recompute auras             ← NEW
  ├── ATTACK
  │   ├── Resolve damage + divine shield
  │   ├── Poisonous check             ← FIXED (Phase 1)
  │   ├── Stealth break               ← FIXED (Phase 1)
  │   ├── Windfury tracking           ← FIXED (Phase 1)
  │   ├── trigger.on_attack()         ← NEW
  │   └── _resolve_deaths()
  │       └── Deathrattle queue       ← NEW
  ├── PLAY SPELL
  │   ├── Deduct mana
  │   ├── Overload parse              ← FIXED (Phase 1)
  │   ├── Spell effect dispatch       ← ENHANCED
  │   └── trigger.on_spell_cast()     ← NEW
  └── END_TURN
      ├── trigger.on_turn_end()       ← NEW
      ├── Apply overload              ← FIXED (Phase 1)
      ├── Reset frozen/fatigue        ← FIXED (Phase 1)
      └── Snapshot Kindred history    ← NEW (Phase 3)
```

---

# Error Handling Strategy

1. **Graceful degradation** — If a new mechanic can't be parsed/simulated, log a warning and treat it as vanilla. Never crash the search.
2. **Regex fallback** — If card text doesn't match any pattern, skip the effect. The card still plays (mana deducted, minion summoned) but with no special effect.
3. **Discover failure** — If Discover pool generation fails (unknown class, empty pool), add a generic 1/1 minion to hand.
4. **Aura recalculation timeout** — If aura chain exceeds 10 iterations (infinite loop detection), stop and use current values.
5. **Death cascade limit** — Max 5 death→deathrattle→death cascades to prevent infinite loops.

---

# Testing Strategy

## Phase 1 Tests (Batch 16-18, ~30 tests)
- Windfury minion attacks twice in one turn
- Poisonous minion kills regardless of damage amount
- Overload reduces available mana next turn
- Charge minions respect taunt in lethal checker
- Combo cards gain bonus when played after another card
- Fatigue damage increments on empty deck draw
- Stealth breaks when minion attacks
- Frozen minion can't attack

## Phase 2 Tests (Batch 19-22, ~40 tests)
- Battlecry damage/heal/summon on play
- Deathrattle triggers on minion death
- Deathrattle cascade (deathrattle kills another minion, which has deathrattle)
- Aura buffs recalculate after minion death
- Discover picks best of 3 options
- Location card activation and durability
- Enchantment stats compute correctly

## Phase 3 Tests (Batch 23-26, ~40 tests)
- Imbue upgrades hero power after multiple plays
- Shatter splits card on draw, merges when adjacent
- Herald counter increments and summons soldiers
- Kindred bonus triggers on matching race/school
- Colossal minion summons appendages
- Quest progress tracks and grants reward
- Dark Gift applies random bonus to Discover options

---

# Open Questions

1. **Rewind implementation scope** — Full branching simulation is expensive (2× evaluation per Rewind card). Should we limit Rewind to lethal-check phase only, or also during RHEA fitness evaluation?
2. **Shatter merge detection cost** — Checking if two Shatter halves are adjacent requires scanning the hand list each action. Is this negligible or does it slow down the search?
3. **Quest progress granularity** — Do we parse quest requirements from card text (complex regex) or hardcode the 14 known quests?
4. **Discover pool source** — Should Discover pull from `unified_standard.json` directly, or maintain a separate class-filtered pool for faster lookup?

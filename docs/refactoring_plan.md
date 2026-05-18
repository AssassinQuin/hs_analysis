# Hearthstone AI Decision Engine — Refactoring Plan

## Current Architecture Problems

| # | Problem | Location | Impact |
|---|---------|----------|--------|
| 1 | **GameState is a God Object** | `game_state.py`, 362 lines | ~25 fields, 50-line `copy()`, every new mechanic adds fields |
| 2 | **Mechanics scattered across ~25 modules** | `analysis/search/*.py` | No shared interface, each imports GameState and mutates directly |
| 3 | **Card model is static-only** | `card.py` | No runtime state, no unified Entity concept |
| 4 | **Zone management is implicit** | Lists on GameState | No ZoneManager, no transfer logic, no capacity enforcement |
| 5 | **Minion has 30+ boolean keyword fields** | `game_state.py` | Adding keywords requires dataclass changes + copy() update |
| 6 | **Effect resolution duplicated 3×** | deathrattle/trigger/location | Same string parsing logic in 3 places |
| 7 | **Enchantment system is primitive** | `enchantment.py` | No source tracking, manual duration ticking |
| 8 | **No Graveyard tracking** | Zone.GRAVEYARD enum only | Dead minions just removed, can't query "what died" |
| 9 | **Watcher layer duplicates state** | `global_tracker.py` (1027 lines) | Two parallel state representations that can drift |
| 10 | **rhea_engine.py is 2084 lines** | Monolithic file | Action enum, simulation, card play, attack all inline |

---

## Strategy: Incremental Refactoring

**Every phase leaves all tests green. No big-bang rewrite.**

---

## Phase 0: Foundation Types (1-2 days)

**Goal**: Introduce new types that don't change existing behavior.

### 0a. CardInstance — Unified Entity Identity

New file: `analysis/search/entity.py`

```python
@dataclass(frozen=True, slots=True)
class EntityId:
    """Stable identity for a card across zone transfers."""
    value: int

def next_entity_id() -> EntityId:
    """Monotonic counter. No uuid overhead."""

@dataclass(slots=True)
class CardInstance:
    """A concrete card in the game. Wraps immutable Card with runtime state."""
    entity_id: EntityId
    card: Card                    # immutable static data
    zone: Zone = Zone.INVALID
    controller: int = 0           # player index
    enchantments: list[Enchantment] = field(default_factory=list)
    current_cost: Optional[int] = None   # None = use card.cost
    current_attack: Optional[int] = None
    current_health: Optional[int] = None

    @property
    def effective_cost(self) -> int:
        return self.current_cost if self.current_cost is not None else self.card.cost
```

**Design decisions**:
- `EntityId` frozen → hashable, usable as dict keys
- `CardInstance` mutable → enchantments/cost change during simulation
- `slots=True` → 10K copies/search × hundreds of instances, memory matters

### 0b. KeywordSet — Replace 30+ Booleans

New file: `analysis/search/keywords.py`

```python
KEYWORDS = frozenset({
    'taunt', 'divine_shield', 'stealth', 'windfury', 'charge',
    'rush', 'lifesteal', 'poisonous', 'reborn', 'spellburst',
    'frenzy', 'outcast', 'corrupt', 'colossal', 'immune',
    'mega_windfury', 'cant_attack', 'ward', ...
})

@dataclass(frozen=True, slots=True)
class KeywordSet:
    """Immutable keyword set. Shared across RHEA copies."""
    _kw: frozenset = frozenset()

    def has(self, keyword: str) -> bool:
    def add(self, keyword: str) -> 'KeywordSet':       # returns new
    def remove(self, keyword: str) -> 'KeywordSet':    # returns new
    def union(self, other: 'KeywordSet') -> 'KeywordSet':
    def __contains__(self, keyword: str) -> bool:
    @classmethod
    def from_card(cls, card: 'Card') -> 'KeywordSet':
```

**Why frozen**: Keywords rarely change. On change, create new KeywordSet. RHEA's 10K copies/s share the same frozenset object.

**Migration**: None yet. Module just exists with unit tests.

---

## Phase 1: Effect Dispatch Unification (2-3 days)

**Goal**: Eliminate 3× duplicated string-based effect parsing. Highest bang-for-buck.

### New file: `analysis/search/effects.py`

```python
class EffectKind(Enum):
    DAMAGE, HEAL, SUMMON, DRAW, BUFF, ARMOR, DESTROY,
    RANDOM_DAMAGE, DISCARD, MANA, COPY, TRANSFORM, ENCHANT, AOE_DAMAGE

@dataclass(frozen=True, slots=True)
class EffectSpec:
    kind: EffectKind
    value: int = 0
    value2: int = 0
    target_filter: str = ""   # 'self', 'enemy', 'random_enemy', 'all_minions'
    card_id: int = 0

# Global registry pattern
_REGISTRY: dict[EffectKind, EffectHandler] = {}

def register(kind: EffectKind):          # decorator
def dispatch(state, spec, source=None):  # single point of dispatch
def dispatch_batch(state, specs, ...):   # execute list of effects

# Parse legacy strings → structured EffectSpec
def parse_effect(text: str) -> EffectSpec:
    """Replaces regex logic in deathrattle.py/trigger_system.py/location.py"""

# One handler per EffectKind, registered via decorator
@register(EffectKind.DAMAGE)
def handle_damage(state, spec, source=None): ...
```

### Migration (5 steps, tests green at each)

1. Add `effects.py` with full parse + dispatch + all handlers
2. Wire `deathrattle.py` → `dispatch_batch([parse_effect(e) for e in effects])`
3. Wire `trigger_system.py` → same
4. Wire `location.py` → same
5. Remove old duplicated `_apply_effect`/`_execute_effect` functions

---

## Phase 2: Mechanics Composition (3-4 days)

**Goal**: Replace ~15 scattered counter fields on GameState with `MechanicsState`.

### 2a. MechanicsState Container

New file: `analysis/search/mechanics_state.py`

```python
@dataclass(slots=True)
class CorpseState:
    spent: int = 0
    gained: int = 0
    @property
    def available(self) -> int: return self.gained - self.spent

@dataclass(slots=True)
class KindredState:
    last_turn_races: frozenset[str] = frozenset()
    last_turn_schools: frozenset[str] = frozenset()
    current_turn_races: set[str] = field(default_factory=set)
    current_turn_schools: set[str] = field(default_factory=set)

@dataclass(slots=True)
class QuestProgress:
    quest_card_id: int = 0
    progress: int = 0
    target: int = 0
    reward_card_id: int = 0
    completed: bool = False

@dataclass(slots=True)
class ImbueState:
    level: int = 0
    hero_power_id: int = 0

@dataclass(slots=True)
class MechanicsState:
    """Replaces ~15 scattered fields on GameState."""
    corpses: Optional[CorpseState] = None
    kindred: Optional[KindredState] = None
    quest: Optional[QuestProgress] = None
    imbue: Optional[ImbueState] = None
    herald_count: int = 0
    fatigue: int = 0
    rune_cost: frozenset[str] = frozenset()

    def copy(self) -> 'MechanicsState':
        """Cheap — most fields are immutable or None."""
```

### 2b. Mechanic Protocol + Dispatcher

New files: `mechanic.py`, `mechanic_dispatcher.py`

```python
class Mechanic(Protocol):
    def on_card_played(self, state, card, **ctx) -> GameState: ...
    def on_minion_died(self, state, minion, **ctx) -> GameState: ...
    def on_turn_start(self, state, player, **ctx) -> GameState: ...
    def on_turn_end(self, state, player, **ctx) -> GameState: ...
    def modify_legal_actions(self, state, actions) -> list: ...

class MechanicDispatcher:
    """Owns registered mechanics. Dispatches events."""
    def register(self, mechanic: Mechanic): ...
    def on_card_played(self, state, card, **ctx) -> GameState: ...
    def on_minion_died(self, state, minion, **ctx) -> GameState: ...
    def enumerate_extra_actions(self, state) -> list: ...
```

### 2c. Wrap Existing Modules

Each module (corpse.py, herald.py, quest.py, kindred.py, imbue.py) gets a Mechanic adapter class.

### 2d. GameState Field Migration

**Before**: `corpses`, `herald_count`, `active_quests`, `kindred_*`, `fatigue_damage`, etc. — ~15 fields
**After**: `mechanics: MechanicsState` — one field

Migration:
1. Add `mechanics` field alongside old fields
2. Update `state_bridge.py` to populate both
3. Update `rhea_engine.apply_action()` to call MechanicDispatcher
4. Remove old fields once all consumers migrated
5. Simplify `GameState.copy()` → `mechanics=self.mechanics.copy()`

---

## Phase 3: Zone Management & CardInstance (4-5 days, most invasive)

**Goal**: Proper zone transfers, unified entities, real Graveyard.

### 3a. ZoneManager

New file: `analysis/search/zone_manager.py`

```python
@dataclass(slots=True)
class ZoneManager:
    """Manages card instances across zones for one player."""
    hand: list[CardInstance] = field(default_factory=list)
    deck: list[CardInstance] = field(default_factory=list)
    board: list[CardInstance] = field(default_factory=list)
    graveyard: list[CardInstance] = field(default_factory=list)
    secrets: list[CardInstance] = field(default_factory=list)

    def move(self, entity: CardInstance, to: Zone, position: int = -1) -> CardInstance:
    def dead_minions(self) -> list[CardInstance]:
    def spawn_graveyard_minion(self, index: int) -> Optional[CardInstance]:
    def copy(self) -> 'ZoneManager':  # list.copy() is C-level fast
```

### 3b. GameState Integration

```python
@dataclass
class GameState:
    zones: tuple[ZoneManager, ZoneManager]  # replaces hand/deck/board/opponent_board
```

### 3c. Migration (6 sub-steps)

1. Add `zones` field alongside existing lists, populate both in state_bridge
2. Add `@property` accessors for backward compat (`hand`, `board`, etc.)
3. Migrate `enumerate_legal_actions()` to read from zones
4. Migrate `apply_action()` to use `zone_manager.move()`
5. Migrate deathrattle/trigger/location to zone transfers
6. Remove old fields and property shims

**Result**: `GameState.copy()` drops from ~25 field copies to ~8.

---

## Phase 4: RHEA Engine Decomposition (3-4 days)

**Goal**: Break `rhea_engine.py` (2084 lines) into focused modules.

### Target Structure

```
analysis/search/rhea/
├── engine.py          (~300 lines) RHEAEngine class, search(), _evolve()
├── actions.py         (~400 lines) Action dataclass, enumerate_legal_actions()
├── simulation.py      (~500 lines) apply_action(), state machine
├── pipeline.py        (~200 lines) LethalCheck → UTP → RHEA → MultiTurn
├── operators.py       (~150 lines) _mutate(), _crossover(), _tournament()
└── draw.py            (~100 lines) apply_draw(), deck manipulation
```

### apply_action() → Command Pattern

```python
def apply_action(state, action, mechanics) -> GameState:
    if action.type == ActionType.PLAY_CARD:
        return _apply_play_card(state, action, mechanics)
    elif action.type == ActionType.ATTACK:
        return _apply_attack(state, action)
    elif action.type == ActionType.HERO_POWER:
        return _apply_hero_power(state, action, mechanics)
    elif action.type == ActionType.END_TURN:
        return _apply_end_turn(state, action, mechanics)
```

Each `_apply_*` is 30-80 lines instead of one 500-line switch.

### Extraction Order (6 steps)

1. `Action` + `enumerate_legal_actions()` → `rhea/actions.py`
2. `apply_action()` + `apply_draw()` → `rhea/simulation.py`
3. `_mutate`, `_crossover`, `_tournament` → `rhea/operators.py`
4. Pipeline strategies → `rhea/pipeline.py`
5. `RHEAEngine` class → `rhea/engine.py`
6. Update all imports throughout codebase

---

## Phase 5: Watcher/State Bridge Dedup (2-3 days)

**Goal**: Eliminate drift between GlobalGameState and GameState.

### Strategy: Shared MechanicsState

- `global_tracker.py` populates `MechanicsState` (same type as GameState)
- `state_bridge.py`: one `mechanics.copy()` instead of 15 field transfers
- `GlobalGameState` keeps watcher-only fields (BayesianModel, KnownCard, SideStats)

---

## Phase 6: Minion/Keyword Cleanup (2-3 days)

**Goal**: Replace 30+ boolean fields with `KeywordSet`.

### New Minion

```python
@dataclass(slots=True)
class Minion:
    entity_id: EntityId
    card: Card
    keywords: KeywordSet           # replaces 30+ booleans
    current_health: int
    max_health: int
    current_attack: int
    attacks_remaining: int = 0
    turns_in_play: int = 0
    enchantments: list[Enchantment] = field(default_factory=list)

    # Backward-compat proxies
    @property
    def has_taunt(self) -> bool: return 'taunt' in self.keywords
    @property
    def has_divine_shield(self) -> bool: return 'divine_shield' in self.keywords
    # ... etc

    def with_keywords(self, add=None, remove=None) -> 'Minion':
```

### Migration

1. Add `keywords` field alongside existing booleans
2. Populate from `KeywordSet.from_card(card)` in state_bridge
3. Migrate consumers to use `keywords.has()` or proxy properties
4. Remove old boolean fields

---

## Dependency Graph

```
Phase 0 (Foundation) ←→ Phase 1 (Effects)     [parallel, no deps]
    ↓                        ↓
Phase 2 (Mechanics)    Phase 4 (RHEA Decompose) [after Phase 1]
    ↓
Phase 3 (Zones) ← needs Phase 0 + 2
    ↓
Phase 5 (Watcher Dedup) ← needs Phase 2
Phase 6 (Keywords) ← needs Phase 3
```

**Critical path**: 0 → 2 → 3 (entity/zone model). This is the architectural backbone.

**Parallel opportunity**: Phase 0 + Phase 1 can start simultaneously. Phase 4 can start after Phase 1.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| GameState.copy() perf regression | Benchmark before/after each phase. Target: <5% regression |
| Watcher bridge drift | Phase 5 makes drift structurally impossible via shared MechanicsState |
| 10K RHEA copies OOM | `slots=True` on sub-components saves ~40% memory. KeywordSet frozen = shared |
| Test regressions | Full suite after every sub-phase. `@property` shims for backward compat |
| String effect parsing breakage | `parse_effect()` tested against all existing patterns before switch |

---

## What NOT To Do

1. **No ECS** — ~5 entity types don't justify Entity-Component-System complexity
2. **No `__slots__` on GameState** — Python 3.10 `dataclasses.replace()` doesn't work with slots (fixed 3.12)
3. **Don't eliminate string-based card text parsing** — card DB limitation, out of scope
4. **Don't rewrite rhea_engine.py in one shot** — 6-step decomposition keeps tests green

---

## Estimated Timeline

| Phase | Duration | Cumulative |
|-------|----------|-----------|
| 0. Foundation Types | 1-2 days | 1-2 days |
| 1. Effect Unification | 2-3 days | 3-5 days |
| 2. Mechanics Composition | 3-4 days | 6-9 days |
| 3. Zone Management | 4-5 days | 10-14 days |
| 4. RHEA Decomposition | 3-4 days | 13-18 days |
| 5. Watcher Dedup | 2-3 days | 15-21 days |
| 6. Keyword Cleanup | 2-3 days | 17-24 days |

**Total: ~17-24 working days** (with Phase 0+1 parallel, Phase 4 starting after Phase 1)

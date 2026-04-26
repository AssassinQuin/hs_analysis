# Card Effect Parsing & Simulation — Research-Based Design Standard

> Generated: 2026-04-26
> Status: Active Standard — all card-specific detection must follow these rules

## 1. Research Foundation

### 1.1 Metastone/Spellsource (Java, Production)

**Core model**: Spell → Condition → Filter → ValueProvider

- Cards defined as JSON with `"class": "DamageSpell"` → Java class dispatch
- `SpellArg.TARGET` → `"target"` in JSON (type-safe enum keys)
- `AttributeValueProvider`, `RandomValueProvider`, `EntityCountValueProvider` for dynamic values
- `ConditionalEffectSpell` wraps spells with `Condition` objects
- **Key insight**: Card behavior is **declared**, not detected from text at runtime

### 1.2 Fireplace (Python, 100%+ coverage)

**Core model**: Selector → Evaluator → LazyNum → Action

- `Selector` with set operations: `IN_PLAY + MINION + ENEMY - DORMANT`
- `Evaluator` for conditions: `Dead(selector)`, `Find(selector, count)`
- `LazyNum` for deferred values: `Count()`, `Attr(selector, tag)`
- **Key insight**: All text parsing happens at card **load time**, not at simulation time

### 1.3 Hearthbreaker (Python, to BRM)

**Core model**: Action → Selector → Condition → Event

- Card definitions via JSON with effect classes
- `MinionEffect.apply(game, target)` / `.unapply(game, target)`
- Event listeners for triggers: `on_play`, `on_death`, etc.
- **Key insight**: Effect classes separate **what** happens from **when** it happens

### 1.4 SabberStone (C#, 94% Standard)

**Core model**: ISimpleTask stack-based system

- `ComplexTask.Create(IncludeTask, FilterStackTask, CountTask, DrawNumberTask)`
- Stack-based data passing between tasks
- `Power` object holds `PowerTask`, `DeathrattleTask`, `ComboTask`
- **Key insight**: Composable tasks with stack data flow

### 1.5 Key Pattern Summary

| Pattern | Used By | Applicability to hs_analysis |
|---------|---------|-----|
| **Declare effects via mechanics/tags** | All | ✅ Our `mechanics` field + `CardAbility` system |
| **Dispatch via type-safe registry** | Metastone, Hearthbreaker | ✅ Our `EffectKind` → `_exec_*` dispatch |
| **Separate detection from execution** | All | ✅ parser.py → executor.py pipeline |
| **Composable conditions** | Fireplace, SabberStone | ✅ Our `ConditionSpec` |
| **Lazy/dynamic values** | Fireplace, SabberStone | ✅ Our `LazyValue` |
| **No runtime text parsing in executor** | All | ⚠️ Currently violated (CN regex in executor) |

---

## 2. Design Standards for hs_analysis

### Standard 1: English-Only Logic Layer

**Rule**: All logic-layer code (detection, dispatch, condition checking) uses **English text only**.

| Layer | CN Allowed? | EN Allowed? | Mechanisms Tag Only? |
|-------|:-----------:|:-----------:|:-------------------:|
| `data/card_effects.py` (regex extraction) | ✅ Yes | ✅ Yes | N/A |
| `engine/mechanics/spell_target_resolver.py` | ✅ Yes | ✅ Yes | N/A |
| `search/abilities/*.py` (parsing) | ❌ No | ✅ Yes | ✅ Yes |
| `search/*.py` (simulation/orchestration) | ❌ No | ❌ No | ✅ **Mechanics/ability tags only** |
| `search/mcts/*.py` (search) | ❌ No | ❌ No | ✅ **Mechanics/ability tags only** |
| `evaluators/*.py` (evaluation) | ❌ No | ✅ Read-only | ✅ Yes |
| `constants/*.py` (keywords) | ✅ Text patterns | ✅ Text patterns | N/A |

**Rationale**: Following Metastone/Fireplace pattern — text parsing happens at **card load/parse time**, simulation uses structured data only.

### Standard 2: Mechanics-Based Detection, Not Card Names

**Rule**: Detect card behavior via `mechanics` tags, `english_text` patterns, or `CardAbility` structs — never via card name strings.

| ❌ BAD | ✅ GOOD |
|--------|---------|
| `'brann' in card.name` | `'BATTLECRY' in mechanics and 'trigger twice' in english_text` |
| `'fandral' in card.name` | `'CHOOSE_ONE' in mechanics and 'both' in english_text` |
| `card.dbf_id == 12345` | `'DARK_GIFT' in mechanics` |
| `re.search(r'亡语.*?黑暗', text)` | `'deathrattle' in english_text.lower() and 'dark gift' in english_text.lower()` |

**Pattern from Metastone**: Cards declare their behavior via tags. The engine never inspects card names.

### Standard 3: Data-Driven Pools, Not Hardcoded Lists

**Rule**: Effect pools, token pools, and enchantment pools should be defined in data files or derived from card databases, not hardcoded in Python logic.

| ❌ BAD | ✅ GOOD |
|--------|---------|
| `DARK_GIFT_ENCHANTMENTS = [DarkGiftEnchantment(name=...), ...]` | Load from card database where `mechanics` contains `"DARK_GIFT"` |
| `_TOKEN_DB = {"CATA_527t2": {...}}` | `card_index.get_pool(mechanics="TOKEN")` |
| `_NAGA_POOL = [minion1, minion2, ...]` | `card_index.get_pool(race="NAGA", type="MINION")` |

**Pattern from Fireplace/SabberStone**: Card pools are queries against the card database, not hardcoded lists.

### Standard 4: Constraint Parsing via Structured Data

**Rule**: When parsing card constraints (e.g., "discover a Deathrattle minion"), use the `english_text` field with structured keyword matching, not CN regex.

**Example — Dark Gift constraint**:
```python
# ❌ BAD: CN regex in logic layer
m = re.search(r'具有.*?黑暗之赐.*?的\s*(\S+?)\s*牌', card_text)
if m and "亡语" in m.group(1): ...

# ✅ GOOD: EN text keyword matching
en = (english_text or "").lower()
if "dark gift" in en:
    for keyword, constraint in DARK_GIFT_CONSTRAINT_MAP:
        if keyword in en:
            return constraint
```

**Pattern from Hearthbreaker**: Conditions are first-class objects that evaluate structured card properties, not regex matches on localized text.

### Standard 5: Zero Regex in Simulation Layer

**Rule**: `analysis/search/abilities/orchestrator.py`, `simulation.py`, `executor.py`, and all mechanic modules must contain **zero regex operations**. All parsing happens in `parser.py` or `card_effects.py`.

---

## 3. Specific Refactoring Items

### 3.1 dark_gift.py — Complete Overhaul

**Current problems**:
1. `parse_dark_gift_constraint()` L153-161: CN regex `r'具有.*?黑暗之赐.*?的\s*(\S+?)\s*牌'` with Chinese "亡语"/"龙" if/elif
2. `has_dark_gift_discover()` L168: checks `"黑暗之赐"` in CN text
3. `DARK_GIFT_ENCHANTMENTS` hardcoded list of 9 enchantments (not data-driven)
4. `filter_dark_gift_pool()` uses mechanics checks correctly ✅ but constraint parsing is wrong

**Target design** (based on Hearthbreaker Action/Condition model):

```python
# Constraint map — declarative, not regex
_DARK_GIFT_CONSTRAINT_MAP = [
    ("deathrattle", "DEATHRATTLE"),
    ("dragon", "DRAGON"),
    ("demon", "DEMON"),
    ("undead", "UNDEAD"),
    ("elemental", "ELEMENTAL"),
    ("beast", "BEAST"),
    ("murloc", "MURLOC"),
    ("pirate", "PIRATE"),
]

def parse_dark_gift_constraint(english_text: str) -> str:
    """Parse constraint from English text. No CN, no regex."""
    en = (english_text or "").lower()
    if "dark gift" not in en:
        return ""
    for keyword, constraint in _DARK_GIFT_CONSTRAINT_MAP:
        if keyword in en:
            return constraint
    return ""

def has_dark_gift_discover(english_text: str) -> bool:
    """Check via English text only."""
    return "dark gift" in (english_text or "").lower()
```

**Enchantment pool**: Should be moved to a data file or generated from card database. Short-term: keep as Python list with EN-only names (already done).

### 3.2 orchestrator.py `_has_battlecry_doubler()`

**Current fix** (V1): `card_ref.english_text` contains `'battlecry' and 'trigger twice'`

**Assessment**: This is **acceptable as intermediate fix** — it uses EN text pattern matching, not card names. Ideally, this would be a `mechanics` tag check (e.g., `BATTLECRY_TRIGGER_TWICE` in mechanics), but Hearthstone API doesn't provide this tag. The EN text pattern is the correct fallback per Standard 2.

**Future improvement**: When card data includes enchantment aura descriptions, detect `"Your Battlecries trigger twice"` from structured aura data.

### 3.3 choose_one.py `has_fandral()`

**Current fix** (V2): `card_ref.english_text` contains `'choose one' and 'both effects'`

**Assessment**: Same as V1 — acceptable EN text pattern matching. The Hearthstone API provides `CHOOSE_ONE` mechanic but not "both effects" modifier. EN text is the correct fallback.

### 3.4 Constants Keyword Files

`analysis/constants/effect_keywords.py` — contains both CN and EN keyword frozensets.

**Rule**: CN keywords are allowed **only** in the constants layer, because they're used by `data/card_effects.py` for text extraction from raw card text. They must NEVER be imported into the simulation/orchestration layer.

---

## 4. Verification Checklist

Every refactoring must pass:

- [ ] No `import re` in simulation/orchestrator/executor
- [ ] No CN string literals (`"亡语"`, `"龙"`, `"黑暗之赐"`, `"布莱恩"`, etc.) in logic layer
- [ ] No `card.name` or `card.dbf_id` comparison for behavior detection
- [ ] All constraint parsing uses EN text or mechanics tags
- [ ] All tests pass: `python -m pytest tests/ -x -q --tb=short -k "not (live_games or powerlog_mcts or powerlog_scenario or game5 or game7 or watcher or scenario_integration or engine_v1)"`

---

## 5. Reference: Completed Refactorings (R1-R13, P4-P6)

| ID | Description | Date |
|----|-------------|------|
| R1-R12 | Card data consolidation, scoring, http, load_json, except narrowing | 2026-04-24~25 |
| R13 | Abilities architecture unification (definition+tokens+executor+orchestrator) | 2026-04-25 |
| P4-A~E | orchestrator DRY, simulation legacy cleanup, enumeration private imports, parser data-driven | 2026-04-26 |
| P5 | God methods split (attack/play/enumerate), flush_deaths, GameState.copy, _pick_target decouple | 2026-04-26 |
| P6-1~2 | Dead code removal, keyword deduplication (effect_keywords.py) | 2026-04-26 |
| V1-V3 | Hardcoding cleanup (Brann/Fandral/Dark Gift) — **needs redo per this standard** | 2026-04-26 |

---

## 6. Research Sources

- **Metastone/Spellsource**: JSON card definitions, Spell-Condition-Filter-ValueProvider model
- **Fireplace**: Python DSL with Selector/Evaluator/LazyNum/Action
- **Hearthbreaker**: Python with Action/Selector/Condition/Event + JSON
- **SabberStone**: C# ISimpleTask stack system, 94% Standard coverage
- **Hearthshroud**: Haskell pure data AST, monadic API
- **CardScript**: Rascal CDDL for generic card games (FDG 2023)
- **Lark parser research**: Hybrid grammar+fallback for semi-structured card text
- **Compiler theory**: Grammar PoC failed for Hearthstone text (too rigid), but design patterns still apply

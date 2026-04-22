# V9 Decision Engine — Implementation Plan (Phase A)

## Overview

| Batch | Tasks | Parallelism | Depends On |
|-------|-------|-------------|------------|
| 1 | 1.1 + 1.2 + 1.3 | 3 parallel | None |
| 2 | 2.1 | 1 sequential | Batch 1 |
| 3 | 3.1 + 3.2 + 3.3 | 3 parallel | Batch 2 |
| 4 | 4.1 | Sequential | Batch 3 |

---

## Batch 1: Foundation (3 parallel implementers)

### Task 1.1: Response Catalog Generator
- **Files**: `scripts/response_catalog_generator.py` (NEW), `scripts/test_response_catalog_generator.py` (NEW)
- **Output data**: `hs_cards/response_catalog.json`

**What it does**: Offline generator that reads `hs_cards/unified_standard.json` (1015 cards) and classifies cards by class × response type. Outputs a JSON catalog used by the V9 Risk Assessor.

**Classes to create**:
- `ResponseCatalogGenerator` — main generator class
  - `__init__(cards_path)`: load unified_standard.json
  - `classify_aoe(card) -> dict | None`: regex `所有|全部|敌方随从` in text + damage pattern `造成\s*(\d+)\s*点伤害`. Returns `{"name", "damage", "cost", "freeze": bool}`
  - `classify_single_removal(card) -> dict | None`: regex `消灭|造成\s*(\d+)\s*点伤害` (targeted damage ≥4 or destroy). Returns `{"name", "damage", "cost"}`
  - `classify_burst(card) -> dict | None`: spells with `造成.*点伤害` + cost ≤ targeted mana. Returns `{"name", "damage", "cost"}`
  - `classify_healing(card) -> dict | None`: regex `恢复\s*(\d+)\s*点`. Returns `{"name", "heal", "cost"}`
  - `classify_secrets(card) -> dict | None`: cardType=SPELL + mechanics includes "SECRET". Returns `{"name", "trigger", "effect"}`
  - `classify_taunt_minions(card) -> dict | None`: cardType=MINION + mechanics includes "TAUNT". Returns `{"name", "cost", "health"}`
  - `generate() -> dict`: groups all cards by `cardClass`, produces per-class catalog
  - `save(output_path)`: writes JSON

**Output JSON structure**:
```json
{
  "MAGE": {
    "aoe": [{"name": "暴风雪", "damage": 2, "cost": 6, "freeze": true}],
    "single_removal": [{"name": "火球术", "damage": 6, "cost": 4}],
    "burst_spells": [{"name": "炎爆术", "damage": 10, "cost": 10}],
    "healing": [],
    "secrets": [{"name": "法术反制", "trigger": "play_spell", "effect": "counter"}],
    "taunt_minions": []
  },
  "_metadata": {"class_count": 11, "total_cards_classified": 800}
}
```

**Reference**: Follow same pattern as `scripts/pool_quality_generator.py` (offline data generator + test).

**Test file** (`test_response_catalog_generator.py`): 8 tests:
1. Test generator loads unified_standard.json successfully
2. Test AOE classification finds known AOE cards
3. Test single_removal finds known removal spells
4. Test burst classification filters by damage threshold
5. Test secrets classified per class
6. Test taunt minions classified
7. Test output JSON has all 11 classes
8. Test save() writes valid JSON to temp file

**Verification**: `cd scripts && python -m pytest test_response_catalog_generator.py -v`

---

### Task 1.2: V9 Risk Assessor
- **Files**: `scripts/v9_risk_assessor.py` (NEW), `scripts/test_v9_risk_assessor.py` (NEW)

**What it does**: Runtime module that quantifies the danger of reaching a given game state. Called by V9 fitness function.

**Functions to implement**:

1. `load_response_catalog(path) -> dict`: Loads `hs_cards/response_catalog.json`. Returns empty dict with defaults if file missing (graceful degradation).

2. `aoe_vulnerability(state: GameState, opponent_class: str, catalog: dict) -> float`:
   - `board_value = sum(m.attack + m.health for m in state.board)`
   - `p_aoe = _estimate_aoe_probability(opponent_class, catalog)` — count AOE cards in class / total class cards, floor 0.1, ceil 0.8
   - Returns `board_value * p_aoe`

3. `retaliation_danger(state: GameState, opponent_class: str, catalog: dict) -> float`:
   - `burst = sum(m.attack for m in state.opponent.board) + _estimate_spell_burst(opponent_class, catalog)`
   - `gap = burst - state.hero.hp - state.hero.armor`
   - `urgency = 3.0 if gap > -5 else 1.0`
   - Returns `max(0, gap) * urgency`

4. `secret_threat(state: GameState, catalog: dict) -> float`:
   - For each secret in `state.opponent.secrets`: look up class secrets, compute avg damage
   - If no secrets: returns 0.0
   - Returns `len(secrets) * avg_secret_damage * 0.3`

5. `overextension_penalty(state: GameState, opponent_class: str, catalog: dict) -> float`:
   - `n = len(state.board)`
   - If n <= 3: returns 0.0
   - `p_aoe = _estimate_aoe_probability(opponent_class, catalog)`
   - Returns `n * (n - 3) * p_aoe * 0.1`

6. `assess_risk(state: GameState, opponent_class: str = "", catalog: dict = None) -> float`:
   - If catalog is None: load default
   - `risk = 0.3 * aoe_vulnerability(...) + 0.4 * retaliation_danger(...) + 0.2 * secret_threat(...) + 0.1 * overextension_penalty(...)`
   - Returns negative float (penalty)

**Helper**: `_estimate_aoe_probability(class_name, catalog)` — returns len(catalog[class]["aoe"]) / max(1, total_spells_in_class). Hardcoded fallback per class if catalog empty.

**Reference**: Follow pattern of `scripts/submodel_evaluator.py` (pure functions, state in, float out).

**Test file** (`test_v9_risk_assessor.py`): 10 tests:
1. Test load_response_catalog with valid file
2. Test graceful degradation when catalog missing (returns empty dict)
3. Test aoe_vulnerability: 0 minions → 0.0
4. Test aoe_vulnerability: 4 minions vs MAGE → positive penalty
5. Test aoe_vulnerability: 4 minions vs HUNTER → lower penalty
6. Test retaliation_danger: safe HP → 0.0
7. Test retaliation_danger: low HP + enemy board → large penalty
8. Test secret_threat: no secrets → 0.0
9. Test overextension_penalty: 3 minions → 0.0, 6 minions → positive
10. Test assess_risk combines all components with correct weights

**Verification**: `cd scripts && python -m pytest test_v9_risk_assessor.py -v`

---

### Task 1.3: V9 Action Enumerator
- **Files**: `scripts/v9_action_enumerator.py` (NEW), `scripts/test_v9_action_enumerator.py` (NEW)

**What it does**: Expanded version of `rhea_engine.py:enumerate_legal_actions()` (line 69) with new action types. Does NOT replace the original function — provides a new one that the RHEA engine can opt into.

**Functions to implement**:

1. `enumerate_legal_actions_v9(state: GameState) -> List[Action]`: Same as original `enumerate_legal_actions` PLUS new action types below.

2. **New action: WEAPON_ATTACK**:
   - Legal when `state.hero.weapon` is not None and `state.hero.weapon.health > 0`
   - Targets: enemy hero (target_index=0) or enemy minions (1-indexed)
   - Must respect taunt (same logic as minion ATTACK at rhea_engine.py:99)
   - Uses `action_type="WEAPON_ATTACK"`, `source_index=-1` (hero), `target_index` per target

3. **New action: USE_LOCATION**:
   - Iterate hand for cards with `card_type.upper() == "LOCATION"` and `card.health > 0` (health = charges) and `card.cost <= state.mana.available`
   - Creates `Action(action_type="USE_LOCATION", card_index=idx)`
   - No position needed (locations don't go on board)

4. **New action: HERO_POWER_TARGETED**:
   - Legal when `not state.hero.hero_power_used` and `state.mana.available >= 2`
   - For targeted classes (MAGE, PRIEST, HUNTER): generate one action per target (enemy hero, enemy minions, friendly minions for PRIEST heal)
   - For non-targeted classes: single `Action(action_type="HERO_POWER")` (same as current)
   - Uses `action_type="HERO_POWER_TARGETED"`, `target_index` per target

5. **Overload parsing helper**: `parse_overload(card_text: str) -> int`:
   - Regex: `过载[：:]\s*[（(]\s*(\d+)\s*[）)]`
   - Returns overload amount or 0

6. **All original actions preserved**: PLAY minion, PLAY spell, PLAY weapon, ATTACK (minion), HERO_POWER (non-targeted), END_TURN — copy logic from `rhea_engine.py:69-148`.

**Reference**: Direct copy of logic from `rhea_engine.py:69-148` with additions. Same `Action` dataclass from `rhea_engine.py:39`.

**Test file** (`test_v9_action_enumerator.py`): 12 tests:
1. Test basic PLAY minion actions generated (same as original)
2. Test basic PLAY spell actions generated
3. Test WEAPON_ATTACK generated when weapon equipped
4. Test WEAPON_ATTACK NOT generated when no weapon
5. Test WEAPON_ATTACK respects taunt
6. Test USE_LOCATION generated for location card with charges
7. Test USE_LOCATION NOT generated for location with 0 charges
8. Test HERO_POWER_TARGETED generated for MAGE (per target)
9. Test HERO_POWER_TARGETED NOT generated when already used
10. Test END_TURN always present
11. Test parse_overload extracts overload value from card text
12. Test parse_overload returns 0 for cards without overload

**Verification**: `cd scripts && python -m pytest test_v9_action_enumerator.py -v`

---

## Batch 2: Fitness Function (1 implementer)

### Task 2.1: V9 Fitness Function
- **Files**: `scripts/v9_fitness.py` (NEW), `scripts/test_v9_fitness.py` (NEW)
- **Depends on**: 1.1 (response_catalog), 1.2 (risk_assessor), 1.3 (action_enumerator)

**What it does**: Replaces `composite_evaluator.evaluate()` and `evaluate_delta()` with a risk-aware fitness function. This is the core of V9.

**Imports from existing modules**:
- `from multi_objective_evaluator import evaluate as mo_evaluate, EvaluationResult` (line 134 of multi_objective_evaluator.py)
- `from v8_contextual_scorer import hand_contextual_value` (v8_contextual_scorer.py)
- `from v9_risk_assessor import assess_risk, load_response_catalog` (new Task 1.2)
- `from game_state import GameState` (game_state.py:97)

**Functions to implement**:

1. `v9_evaluate(state: GameState, weights: dict = None, opponent_class: str = "", catalog: dict = None) -> float`:
   ```
   # Phase-adaptive weights (from multi_objective_evaluator.py:36-47)
   turn = state.turn_number
   if turn <= 4:   wt, wv, ws, wr = 1.2, 0.8, 0.6, 0.15
   elif turn <= 7: wt, wv, ws, wr = 1.0, 1.0, 1.0, 0.25
   else:           wt, wv, ws, wr = 0.8, 1.2, 1.5, 0.35
   
   # Get 3D evaluation from existing multi_objective_evaluator
   result = mo_evaluate(state)  # returns EvaluationResult(v_tempo, v_value, v_survival)
   
   # Risk assessment from v9_risk_assessor
   risk = assess_risk(state, opponent_class, catalog)
   
   # Combined score
   return wt * result.v_tempo + wv * result.v_value + ws * result.v_survival + wr * risk
   ```

2. `v9_evaluate_delta(before: GameState, after: GameState, weights: dict = None, opponent_class: str = "", catalog: dict = None) -> float`:
   - Returns `v9_evaluate(after, ...) - v9_evaluate(before, ...)`
   - Same interface as `composite_evaluator.evaluate_delta()` (line 128) for drop-in replacement

3. `v9_quick_eval(state: GameState, opponent_class: str = "", catalog: dict = None) -> float`:
   - Fast path: uses V8 hand quality + simple threat (no full multi_objective eval)
   - `hand_q = hand_contextual_value(state)`
   - `threat = -(max(0, 30 - state.hero.hp - state.hero.armor) * 0.5)`
   - `risk = assess_risk(state, opponent_class, catalog) * 0.25`  # reduced weight for quick path
   - Returns `hand_q + 1.5 * threat + 0.25 * risk`

4. `load_default_catalog() -> dict`: Loads `hs_cards/response_catalog.json`, returns empty on failure.

**Key design decisions**:
- **Wraps, not replaces**: Uses existing `mo_evaluate()` and `hand_contextual_value()` internally. V9 adds the risk layer on top.
- **opponent_class parameter**: Extracted from `state.opponent.hero.hero_class` if not provided.
- **Backward compatible**: If catalog is None or empty, `assess_risk` returns ~0, and V9 degrades to V8-equivalent evaluation.

**Test file** (`test_v9_fitness.py`): 10 tests:
1. Test v9_evaluate returns float for empty state
2. Test v9_evaluate returns float for populated state
3. Test v9_evaluate_delta computes difference correctly
4. Test v9_evaluate_delta: same state → ~0.0
5. Test v9_quick_eval returns float
6. Test risk-aware: state with many minions vs MAGE has lower score than vs HUNTER
7. Test risk-aware: state with low hero HP gets survival penalty
8. Test phase-adaptive: turn 3 weights tempo higher than turn 9
9. Test backward compat: no catalog → still returns valid float
10. Test load_default_catalog handles missing file gracefully

**Verification**: `cd scripts && python -m pytest test_v9_fitness.py -v`

---

## Batch 3: Integration (3 parallel implementers)

### Task 3.1: GameState Updates
- **File**: `scripts/game_state.py` (MODIFY)

**What to change**:

1. **Add `deck_list` field to GameState** (after line 107):
   ```python
   deck_list: list = field(default_factory=list)  # Optional: full deck for draw EV
   ```

2. **Add `hero_class` field to HeroState** — CHECK: already exists at line 68 (`hero_class: str = ""`). No change needed.

3. **No changes to Card, Minion, Weapon, ManaState, OpponentState** — they already have the fields V9 needs.

4. **Verify copy() still works**: `copy()` at line 117 uses `copy.deepcopy(self)`. The new `deck_list` field will be deep-copied automatically. No change needed.

**IMPORTANT**: Keep changes minimal. Only add `deck_list`. All other fields needed by V9 already exist.

**Verification**: `cd scripts && python game_state.py` (existing self-test must still pass)

---

### Task 3.2: RHEA Engine V9 Wiring
- **File**: `scripts/rhea_engine.py` (MODIFY)
- **Depends on**: 2.1 (v9_fitness), 1.3 (action_enumerator)

**What to change** (6 modifications to existing file):

**Mod 1**: Add imports at top of file (after existing imports around line 30):
```python
from v9_action_enumerator import enumerate_legal_actions_v9, parse_overload
from v9_fitness import v9_evaluate_delta, v9_quick_eval, load_default_catalog
```

**Mod 2**: Add parameters to `RHEAEngine.__init__()` (after line 358 `max_chromosome_length`):
```python
use_v9: bool = True,
opponent_class: str = "",
```
Store as `self.use_v9`, `self.opponent_class`.
Load catalog: `self._response_catalog = load_default_catalog() if use_v9 else None`

**Mod 3**: In `search()` method (line 378), after score loading (line 387):
- If `self.use_v9`: use `enumerate_legal_actions_v9` instead of `enumerate_legal_actions` everywhere in search
- Store `self._action_enumerator = enumerate_legal_actions_v9 if use_v9 else enumerate_legal_actions`

**Mod 4**: In `_evaluate_chromosome()` (line 600), change fitness call (line 623):
```python
# Was: return evaluate_delta(initial_state, current, weights)
if self.use_v9:
    return v9_evaluate_delta(initial_state, current, weights, self.opponent_class, self._response_catalog)
else:
    return evaluate_delta(initial_state, current, weights)
```

**Mod 5**: In `_random_chromosome()` (line 566) and `_mutate()` (line 695):
- Change `enumerate_legal_actions(state)` → `self._action_enumerator(state)`
- This ensures new action types (WEAPON_ATTACK, USE_LOCATION, HERO_POWER_TARGETED) are discovered during search

**Mod 6**: In `apply_action()` (line 163), add handlers for new action types (after line 257, before return):

```python
elif action.action_type == "WEAPON_ATTACK":
    weapon = s.hero.weapon
    if weapon is None or weapon.health <= 0:
        return s
    tgt_idx = action.target_index
    if tgt_idx == 0:
        # Attack enemy hero - consume armor first
        damage = weapon.attack
        if s.opponent.hero.armor > 0:
            absorbed = min(damage, s.opponent.hero.armor)
            s.opponent.hero.armor -= absorbed
            damage -= absorbed
        s.opponent.hero.hp -= damage
    else:
        # Attack enemy minion
        enemy_idx = tgt_idx - 1
        if enemy_idx >= len(s.opponent.board):
            return s
        target = s.opponent.board[enemy_idx]
        if target.has_divine_shield:
            target.has_divine_shield = False
        else:
            target.health -= weapon.attack
        s.opponent.board = [m for m in s.opponent.board if m.health > 0]
    weapon.health -= 1  # lose durability
    if weapon.health <= 0:
        s.hero.weapon = None

elif action.action_type == "USE_LOCATION":
    card_idx = action.card_index
    if card_idx < 0 or card_idx >= len(s.hand):
        return s
    card = s.hand[card_idx]
    s.mana.available -= card.cost
    s.hand.pop(card_idx)
    # Location effects parsed by spell_simulator
    try:
        from spell_simulator import resolve_effects
        s = resolve_effects(s, card)
    except Exception:
        pass

elif action.action_type == "HERO_POWER_TARGETED":
    s.mana.available -= 2
    s.hero.hero_power_used = True
    # Targeted effect is class-specific, not simulated in detail
```

**Also add overload handling** in PLAY branch (after line 174 `s.mana.available -= card.cost`):
```python
# Parse and queue overload
overload = parse_overload(card.text)
if overload > 0:
    s.mana.overload_next = s.mana.overload_next + overload
```

**Verification**: `cd scripts && python rhea_engine.py` (existing sanity check must pass)

---

### Task 3.3: Integration Tests
- **File**: `scripts/test_integration.py` (MODIFY)

**What to add**: 5 new test functions appended to existing test file.

1. `test_v9_risk_assessor_integration()`:
   - Create a state with 5 friendly minions vs MAGE opponent
   - Load response catalog
   - Call `assess_risk(state, "MAGE", catalog)`
   - Assert risk > 0 (AOE vulnerability detected)

2. `test_v9_fitness_beats_v8_for_risky_state()`:
   - Create state A: 6 minions, hero HP=10, opponent MAGE with 3 minions
   - Create state B: 2 minions, hero HP=25, opponent MAGE with 1 minion
   - Assert `v9_evaluate(B, ...) > v9_evaluate(A, ...)` for same board value (B is safer)

3. `test_v9_action_enumerator_weapon_attack()`:
   - Create state with weapon equipped
   - Call `enumerate_legal_actions_v9(state)`
   - Assert WEAPON_ATTACK actions present
   - Assert weapon attack targets include enemy hero and minions

4. `test_v9_action_enumerator_location()`:
   - Create state with LOCATION card in hand (card_type="LOCATION", health=2, cost=0)
   - Call `enumerate_legal_actions_v9(state)`
   - Assert USE_LOCATION action present

5. `test_v9_full_search_returns_valid_result()`:
   - Build demo state using existing `_build_demo_state()` helper pattern
   - Set `use_v9=True, opponent_class="MAGE"`
   - Run `RHEAEngine(use_v9=True, opponent_class="MAGE", time_limit=50).search(state)`
   - Assert SearchResult returned with non-empty best_chromosome
   - Assert all actions are valid types

**Verification**: `cd scripts && python test_integration.py` (all existing 14 + 5 new = 19 tests pass)

---

## Batch 4: Full Verification

### Task 4.1: Run all test suites

Run these commands in sequence. All must pass:

```bash
# New V9 tests
cd /Users/ganjie/code/personal/hs_analysis/scripts
python -m pytest test_response_catalog_generator.py -v   # 8 tests
python -m pytest test_v9_risk_assessor.py -v              # 10 tests
python -m pytest test_v9_action_enumerator.py -v           # 12 tests
python -m pytest test_v9_fitness.py -v                     # 10 tests

# Existing tests (regression check)
python game_state.py                                       # self-test
python composite_evaluator.py                              # self-test
python multi_objective_evaluator.py                        # self-test
python rhea_engine.py                                      # sanity check
python test_integration.py                                 # 19 tests (14 old + 5 new)

# Existing V8 tests (must still pass)
python -m pytest test_score_provider.py -v                 # 11 tests
python -m pytest test_pool_quality_generator.py -v          # 8 tests
python -m pytest test_rewind_delta_generator.py -v          # 6 tests
python -m pytest test_v8_contextual_scorer.py -v            # 16 tests
```

**Expected total**: 8+10+12+10+19+11+8+6+16 = 100 tests
**All must pass with 0 failures.**

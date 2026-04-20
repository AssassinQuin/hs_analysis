---
date: 2026-04-20
topic: "V10 Feedback: Kindred + DK Systems + Dark Gift + Target Selection + Wild Pool"
status: validated
---

## Problem Statement

User provided 4 feedback items after V10 Phase 3 completion:
1. Kindred/延系 mechanic DOES exist (29 cards) — was incorrectly skipped
2. Target selection should enumerate ALL valid targets + evaluate outcomes, not greedy
3. Death Knight rune + corpse systems need implementation
4. Wild card pool should be used for discover expectation calculation

Additionally, Dark Gift/黑暗之赐 (20 cards) was also incorrectly skipped and needs implementation.

## Constraints

- 689 existing tests must pass (zero regression)
- 1 known flaky test: test_v9_hdt_batch02_deck_random::test_09_multi_deck_lethal (~20% failure from RHEA stochastic)
- Files >500 lines: skeleton first, fill in ≤200 line chunks
- Pure Python, no new dependencies
- Graceful degradation: try/except on all dispatch points
- Chinese regex patterns for card text parsing
- Commit format: feat: / fix: / cleanup: 简述
- Platform: macOS Darwin

## Approach

Four batches ordered by dependencies:

| Batch | Items | New Modules |
|-------|-------|-------------|
| 1 | Kindred + Corpse | kindred.py, corpse.py |
| 2 | Rune + Dark Gift | rune.py, dark_gift.py |
| 3 | Target Selection redesign | (modify battlecry_dispatcher.py, spell_simulator.py) |
| 4 | Wild pool for discover | (modify discover.py) |

### Why this order
- Kindred and Corpse are standalone resource systems with no cross-dependencies
- Rune is needed before Dark Gift (some Dark Gift cards discover rune cards)
- Dark Gift depends on discover.py + corpse.py (some cards spend corpses to grant Dark Gift)
- Target selection is cross-cutting — do after mechanics are stable
- Wild pool is last — only affects discover probability breadth

## Architecture

### Batch 1: Kindred/延系 — kindred.py

**Kindred is a conditional bonus mechanic**: when you play a card with "延系：..." text, if the card shares a race or spellSchool with a card you played last turn, the bonus effect triggers.

**GameState integration** (already exists):
- `last_turn_races: set[str]` — races of cards played last turn
- `last_turn_schools: set[str]` — spellSchools of cards played last turn
- These are snapshotted at END_TURN in rhea_engine.py

**kindred.py responsibilities**:
1. `has_kindred(card_text: str) -> bool` — detect "延系" in card text
2. `parse_kindred_bonus(card_text: str) -> str` — extract bonus effect string after "延系："
3. `check_kindred_active(state: GameState, card: dict) -> bool` — check if card's race/school intersects last_turn_races/last_turn_schools
4. `apply_kindred(state: GameState, card: dict) -> GameState` — if active, parse bonus and dispatch effect

**Special case**: 蛮鱼挑战者 "你的下一个延系效果会触发两次" — need `kindred_double_next: bool = False` in GameState. When this minion's battlecry fires, set flag. When kindred triggers, check flag: if True, apply twice and clear flag.

**Effect dispatch**: reuse battlecry_dispatcher's effect parsing — same protocol ("damage:random_enemy:N", "buff:allies:ATK:HEALTH", etc.)

**rhea_engine.py integration**: after PLAY MINION inserts the minion and resolves colossal, but before battlecry:
```
insert minion → colossal → kindred check → battlecry → herald → trigger → aura → imbue → outcast → quest
```

For SPELL cards with kindred (like 潜踪掠食), same check before spell resolution.

**Test file**: test_kindred.py — test detection, condition check, bonus parsing, double trigger, integration with existing state

### Batch 1: Corpse/残骸 — corpse.py

**Corpse is a DK-exclusive resource**: DK gains corpses when friendly minions die, spends corpses for card effects.

**GameState changes**:
- Add `corpses: int = 0` to GameState dataclass

**corpse.py responsibilities**:
1. `parse_corpse_cost(card_text: str) -> list[CorpseEffect]` — parse "消耗N份残骸" patterns, returning structured cost+effect pairs
2. `parse_corpse_gain(card_text: str) -> int` — parse "获得N份残骸" / "获得一份残骸"
3. `can_afford_corpses(state: GameState, cost: int) -> bool` — check availability
4. `spend_corpses(state: GameState, cost: int) -> GameState` — deduct corpses
5. `gain_corpses(state: GameState, amount: int) -> GameState` — add corpses
6. `has_double_corpse_gen(state: GameState) -> bool` — check if 法瑞克 is on board

**CorpseEffect dataclass**:
```
CorpseEffect:
  cost: int
  is_optional: bool  # "消耗2份残骸，再获得+1/+1" is optional
  effect_text: str   # the effect that the corpse purchase enables
```

**rhea_engine.py integration**:
- In `_apply_card_effects()`: check corpse cost, spend if available, apply bonus effect
- In deathrattle flow: when a friendly minion dies, `gain_corpses(state, 1)` (or 2 if 法瑞克 on board)
- In `_can_play_card()` gate: NOT gating playability by corpse cost (cards are always playable, corpse effects are optional bonuses)

**Card text patterns**:
- `消耗N份残骸` — spend N corpses
- `消耗最多N份残骸` — spend up to N corpses (凉心农场: spend 1-8 corpses for different outcomes)
- `获得一份残骸` / `获得N份残骸` — gain corpses
- `残骸量为正常的两倍` — 法瑞克 passive

**Test file**: test_corpse.py — test parsing, gain/spend, double generation, optional effects, integration

### Batch 2: DK Rune/符文 — rune.py

**Rune types are a discover filter and conditional trigger**: DK cards have rune affiliations (Blood/Frost/Unholy) used for discover targeting and conditional effects.

**Rune mapping strategy**:
- Primary: `spellSchool` field on DK spells → FROST→冰霜, SHADOW→邪恶, FIRE→鲜血
- Secondary: hardcoded lookup for known minion/weapon rune affiliations (5 cards)
- Fallback: empty — most cards have no explicit rune type

**rune.py responsibilities**:
1. `RUNE_MAP: dict[str, str]` — spellSchool → rune name mapping
2. `get_rune_type(card: dict) -> str | None` — determine rune type from spellSchool or lookup
3. `filter_by_rune(pool: list[dict], rune_name: str) -> list[dict]` — filter discover pool to cards with given rune type
4. `check_last_played_rune(state: GameState, rune_name: str) -> bool` — for conditional effects like 畸怪符文剑

**GameState changes**:
- Add `rune_types: set[str]` to HeroState — populated from deck at game start (not needed for arena simulation, but useful for discover filtering)

**discover.py integration**: when card text says "发现一张冰霜符文牌", filter the pool using `filter_by_rune(pool, "冰霜符文")`

**rhea_engine.py integration**: for conditional effects like 畸怪符文剑 "如果你使用的上一张牌拥有邪恶符文", track `last_played_card` in GameState, check its rune type.

**Test file**: test_rune.py — test mapping, filtering, conditional checks

### Batch 2: Dark Gift/黑暗之赐 — dark_gift.py

**Dark Gift is a discover modifier**: when discovering a card with Dark Gift, a random enchantment from a fixed pool is applied to it.

**DARK_GIFT_ENCHANTMENTS**: a list of ~10 predefined enchantments:
- Stat buffs: +2/+2, +1/+3, +3/+1
- Keywords: 风怒 (Windfury), 吸血 (Lifesteal), 圣盾 (Divine Shield), 嘲讽 (Taunt)
- Effects: 亡语: deal 2 damage to a random enemy, 战吼: draw a card

**dark_gift.py responsibilities**:
1. `DARK_GIFT_ENCHANTMENTS: list[dict]` — constant pool of possible enchantments
2. `apply_dark_gift(card: dict) -> dict` — select random enchantment, return modified card
3. `has_dark_gift_in_hand(hand: list[dict]) -> bool` — for hand-check effects
4. `filter_dark_gift_pool(pool: list[dict], constraint: str) -> list[dict]` — filter discover pool to cards that CAN have dark gift (typically specific types like 亡语 minions, 龙, etc.)

**discover.py integration**: when card text says "发现一张具有黑暗之赐的XX牌":
1. Filter pool by type constraint (亡语, 龙, etc.)
2. For each discover option, call `apply_dark_gift(card)` to apply random enchantment
3. Evaluate the modified card (enchantment included) for best-of-3 selection

**battlecry_dispatcher.py integration**: for cards like 燃薪之剑 "如果手牌中有具有黑暗之赐的随从牌，获得+3攻击力":
1. Check `has_dark_gift_in_hand(state.hand)`
2. If True, apply bonus stat buff

**Note**: Dark Gift enchantments on discovered cards are tracked via the enchantment system — use existing `enchantment.py` to attach the buff.

**Test file**: test_dark_gift.py — test enchantment application, hand detection, discover integration

### Batch 3: Target Selection Redesign

**Problem**: Current greedy target selection in battlecry_dispatcher picks "best" target heuristically (highest attack enemy, lowest health friendly). This misses synergies and non-obvious optimal plays.

**Solution**: Exhaustive enumeration with state evaluation.

**New function in battlecry_dispatcher.py**:
```
select_best_target(state, card, valid_targets, effect) -> target:
    best_score = -inf
    best_target = None
    for target in valid_targets:
        sim_state = deep_copy(state)
        apply_effect(sim_state, effect, target)
        score = evaluate_state(sim_state)
        if score > best_score:
            best_score = score
            best_target = target
    return best_target
```

**Key decisions**:
- Use existing `_evaluate_state()` from rhea_engine.py as scoring function
- Only enumerate when valid_targets ≤ 7 (board size) — guaranteed in Hearthstone
- For random effects (random_enemy, random_minion), keep current behavior — can't enumerate stochastic outcomes efficiently
- Deep copy cost is acceptable: GameState is ~20 fields, mostly primitives and small lists
- Import _evaluate_state from rhea_engine (or expose as public function)

**Apply same pattern to spell_simulator.py** for single-target spell effects (伤害, 变形, etc.)

**Performance consideration**: max 7 evaluations per target selection call. Each evaluation is O(1) (simple heuristic). Total overhead: negligible compared to RHEA's existing ~200 chromosome evaluations.

**Test file**: test_target_selection.py — test exhaustive vs greedy on constructed scenarios, verify best target is chosen

### Batch 4: Wild Card Pool for Discover

**Problem**: Current discover pool only uses unified_standard.json (1015 cards). Some discover effects reference past/wild cards, and wild pool provides better expectation modeling for "what can this discover solve?"

**discover.py changes**:
1. Load `unified_wild.json` (5209 cards) as `WILD_POOL` at module level
2. Add `use_wild_pool: bool = False` parameter to pool generation functions
3. When card text contains "来自过去" or references rotated sets, set `use_wild_pool=True`
4. For expectation calculation (probability of finding lethal, removal, etc.), use wild pool to compute broader probabilities
5. For actual discover simulation (best-of-3 selection), continue using standard pool for most arena scenarios

**Rationale**: Wild pool is 5x larger, but most arena discover stays standard. Using wild pool only when explicitly triggered keeps performance reasonable while improving discover expectation accuracy.

**Test file**: test_discover.py extension — test wild pool loading, pool filtering with wild cards, expectation calculation

## Components Summary

| Module | New/Modified | Lines (est.) | Batch |
|--------|-------------|--------------|-------|
| kindred.py | New | ~180 | 1 |
| corpse.py | New | ~150 | 1 |
| test_kindred.py | New | ~120 | 1 |
| test_corpse.py | New | ~100 | 1 |
| game_state.py | Modified | +15 (corpses, kindred_double_next) | 1 |
| rhea_engine.py | Modified | +30 (kindred integration, corpse gain on death) | 1 |
| rune.py | New | ~120 | 2 |
| dark_gift.py | New | ~150 | 2 |
| test_rune.py | New | ~80 | 2 |
| test_dark_gift.py | New | ~100 | 2 |
| discover.py | Modified | +20 (rune filtering, dark gift integration) | 2 |
| battlecry_dispatcher.py | Modified | +60 (exhaustive target selection) | 3 |
| spell_simulator.py | Modified | +40 (exhaustive spell targeting) | 3 |
| test_target_selection.py | New | ~100 | 3 |
| discover.py | Modified | +30 (wild pool loading) | 4 |
| test_discover.py | Modified | +40 (wild pool tests) | 4 |

**Total estimated**: ~5 new modules, ~6 modified modules, ~800 new lines of code, ~540 new test lines

## Data Flow

### Kindred Flow (on PLAY MINION)
```
1. rhea_engine: PLAY MINION → insert minion to board
2. colossal.py: summon appendages if colossal
3. kindred.py: check has_kindred(card.text)
   → if True: check_kindred_active(state, card) — race/school intersection
   → if Active: parse_kindred_bonus(card.text) → dispatch effect via battlecry effect protocol
   → check kindred_double_next flag: if True, dispatch twice, clear flag
4. battlecry_dispatcher: resolve battlecry
5. herald → trigger → aura → imbue → outcast → quest
```

### Corpse Flow
```
On friendly minion death:
1. deathrattle.py: resolve deathrattle
2. corpse.py: gain_corpses(state, 1) [or 2 if 法瑞克 on board]

On playing DK card with corpse cost:
1. corpse.py: parse_corpse_cost(card.text)
2. For each CorpseEffect:
   → if optional: check can_afford_corpses, if True: spend + apply effect
   → if mandatory: check can_afford_corpses (gate), spend + apply
```

### Dark Gift + Discover Flow
```
1. battlecry_dispatcher: card text says "发现一张具有黑暗之赐的XX牌"
2. discover.py: generate pool filtered by type constraint (亡语, 龙, etc.)
3. dark_gift.py: apply_dark_gift to each candidate (random enchantment)
4. discover.py: best-of-3 selection from modified candidates
5. Return selected card with enchantment attached
```

### Target Selection Flow
```
1. battlecry_dispatcher: needs to pick target for "对一个XX造成N点伤害"
2. Collect all valid targets (≤7)
3. For each target:
   → deep_copy(state)
   → apply damage/效果 to copy
   → score = evaluate_state(copy)
4. Pick target with highest score
5. Apply effect to ORIGINAL state with chosen target
```

## Error Handling

- All new modules follow graceful degradation: try/except on every dispatch point
- If kindred parsing fails, log warning and skip bonus (search continues)
- If corpse cost parsing fails, treat as 0 cost (no effect)
- If dark gift enchantment fails, discover card without bonus
- If target enumeration fails, fall back to greedy selection
- If wild pool loading fails, use standard pool only

## Testing Strategy

- Each new module gets its own test file with unit tests
- Test kindred: detection regex, condition matching, bonus parsing, double trigger, edge cases
- Test corpse: parsing patterns, gain/spend, double generation, optional effects
- Test rune: mapping accuracy, pool filtering, conditional checks
- Test dark gift: enchantment selection, hand detection, discover integration
- Test target selection: exhaustive vs greedy comparison, edge cases (0 targets, 1 target, 7 targets)
- Test wild pool: loading, filtering, expectation calculation
- All 689 existing tests must pass after each batch
- Run full test suite after each batch before committing

## Open Questions

1. **Kindred bonus parsing**: Some kindred effects are complex ("且会获得圣盾" on 温泉踏浪鱼人 modifies the PREVIOUS effect, not an independent one). May need context-aware parsing.
2. **Corpse scaling effects**: 凉心农场 "消耗最多8份残骸" summons a minion whose cost matches corpses spent — need dynamic summoning logic.
3. **Rune data gaps**: Only ~30 DK cards have identifiable rune types via spellSchool. For discover filtering, this may mean incomplete pools.
4. **Dark Gift enchantment list**: The exact 10 enchantments need to be confirmed from game data — current list is estimated.
5. **Wild pool performance**: 5209 cards is 5x larger. Need to benchmark discover pool generation with wild cards.

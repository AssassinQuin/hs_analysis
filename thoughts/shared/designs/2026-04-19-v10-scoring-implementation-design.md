---
date: 2026-04-19
topic: "V10 Scoring Implementation (SIV + BSV + Integration)"
status: validated
---

## Problem Statement

The current scoring pipeline uses linear weighted sums (`V = w1*a + w2*b + w3*c + ...`) which cannot capture non-linear game dynamics like lethal proximity (where 1 damage at 1 HP is infinitely more valuable than at 30 HP) or keyword interactions (where Poisonous is useless vs Divine Shield). The V10 design specifies a three-layer architecture (CIV → SIV → BSV) to fix this, but only the design exists — zero implementation code has been written.

## Constraints

- **233 existing tests must stay green** — no modifications to existing scorer files (v8_contextual.py, composite.py sub-models, etc.)
- **Performance budget** — each SIV modifier <0.1ms; total SIV+BSV <1ms per evaluation
- **Graceful degradation** — missing state fields → return 1.0 (no crash); missing JSON data → skip that modifier
- **All card text is Chinese** — regex patterns must handle Chinese characters (过载, 召唤, 造成, 抽牌, etc.)
- **SIV clamping** — output range [0.01, 100.0] to prevent numerical overflow
- **Division by zero guard** — `max(denominator, 0.001)` everywhere

## Approach

**Parallel file approach**: Create SIV, BSV, keyword interactions, and mechanic base values as entirely new files. The existing V8 scorer becomes the CIV base layer unchanged. Only `composite.py` gets a lightweight modification to optionally use the new BSV fusion instead of its current linear weighted sum.

**Why this over alternatives:**
- **Modify-in-place** was rejected because it risks breaking 233 tests and prevents A/B comparison
- **Full rewrite** was rejected because V8's 7 adjustors already work well as the CIV layer — we're adding state-awareness on top, not replacing fundamentals

## Architecture

```
                    ┌─────────────────────────────┐
                    │    composite.py (modified)    │
                    │   evaluate() →                │
                    │     if V10_ENABLED:           │
                    │       bsv_fusion(state)       │
                    │     else:                     │
                    │       legacy weighted sum     │
                    └──────────┬──────────────────┘
                               │
                    ┌──────────┴──────────────────┐
                    │   NEW: bsv.py                │
                    │   Board State Value           │
                    │   - eval_tempo_v10(state)     │
                    │   - eval_value_v10(state)     │
                    │   - eval_survival_v10(state)  │
                    │   - softmax_fusion(axes, temp)│
                    │   - lethal_override()         │
                    └──────────┬──────────────────┘
                               │ consumes
                    ┌──────────┴──────────────────┐
                    │   NEW: siv.py                │
                    │   State Interaction Value     │
                    │   siv_score(card, state) →    │
                    │     CIV(card) ×               │
                    │     × lethal_modifier         │
                    │     × taunt_modifier           │
                    │     × curve_modifier           │
                    │     × position_modifier        │
                    │     × trigger_modifier         │
                    │     × synergy_modifier         │
                    │     × progress_modifier        │
                    │     × counter_modifier         │
                    └──────────┬──────────────────┘
                               │ consumes
               ┌───────────────┼───────────────┐
               │               │               │
    ┌──────────┴──────┐ ┌─────┴──────┐ ┌──────┴─────────────┐
    │ NEW: keyword_   │ │ NEW:       │ │ EXISTING:          │
    │ interactions.py │ │ mechanic_  │ │ v8_contextual.py   │
    │                 │ │ base_      │ │ (unchanged CIV)    │
    │ 8 interaction   │ │ values.py  │ │                    │
    │ rules → value   │ │            │ │ contextual_score() │
    │ multipliers     │ │ 9 mechanic │ │ = CIV base         │
    └─────────────────┘ │ formulas   │ └────────────────────┘
                        └────────────┘
```

## Components

### 1. SIV Module (`hs_analysis/evaluators/siv.py`)

**Responsibility**: Apply 8 multiplicative state modifiers to a card's CIV base value.

**Entry point**: `siv_score(card: Card, state: GameState) -> float`

**8 Modifiers** (each returns a float multiplier, default 1.0):

1. **Lethal Awareness** — Reads `state.opponent.hero.hp + armor`. Damage-dealing cards get `1 + (1 - enemy_hp/30)² × 3.0` multiplier. Applied to spells with damage text, charge/rush minions, and weapons.

2. **Taunt Constraint** — Reads `state.opponent.board` for taunt minions. Cards with silence/destroy effects get +0.5 bonus. Poisonous gets +0.3. Base: `1 + 0.3 × count(enemy_taunts)`.

3. **Tempo Window (Curve)** — Reads `state.mana.available` and `card.cost`. On-curve = 1.0×, 1 mana off = 0.9×, further = 0.8 - 0.05 per overflow mana. Also penalizes cards that cost more than `turn_number + 1`.

4. **Hand Position** — Reads hand index. Outcast cards get bonus at edges. Shatter cards get merge probability bonus. Default = 1.0.

5. **Trigger Probability** — Reads board for Brann (battlecry ×2), Rivendare (deathrattle ×2), Drakkari (end-of-turn ×2), and race aura (+1.3×). Checks `card.mechanics` list.

6. **Race Synergy** — Counts same-race minions on board + in hand. `synergy_multiplier = 1 + 0.1 × count`. Kindred cards get additional bonus if last-turn race matches.

7. **Progress Tracker** — Tracks Imbue level (diminishing: `1 + 0.3 × (1 - 0.15 × level)`), Herald count (threshold jumps at 1,3), and Quest progress (quadratic: `1 + pct² × 2.0`).

8. **Counter Awareness** — Adjusts for opponent threats: freeze classes penalize key minions (-0.1), secrets penalize battlecry (-0.05) and high-attack (-0.1), AoE potential boosts stealth value (+0.2).

**Output clamping**: `max(0.01, min(100.0, result))`

### 2. BSV Module (`hs_analysis/evaluators/bsv.py`)

**Responsibility**: Replace linear weighted sum with non-linear 3-axis softmax fusion.

**Entry points**:
- `bsv_fusion(state: GameState) -> float` — main entry for composite.py
- `eval_tempo_v10(state) -> float`
- `eval_value_v10(state) -> float`
- `eval_survival_v10(state) -> float`

**Three Axes**:

- **Tempo**: `Σ SIV(friendly_minions) × 1.0 - Σ SIV(enemy_minions) × 1.2 + mana_efficiency × 5.0 + weapon_value`
- **Value**: `Σ SIV(hand_cards) + card_advantage × 2.0 + resource_generation + discover_pool_ev`
- **Survival**: `(hero_hp + armor) / 30.0 × 10.0 - enemy_damage × 0.5 - lethal_threat × 50.0 + heal_potential × 0.3`

**Softmax Fusion**:
- Apply phase weights (early/mid/late) to raw axes
- `weights = softmax([weighted_t, weighted_v, weighted_s] / temperature)`
- `BSV = Σ weights[i] × raw[i]`
- Temperature = 0.5 (emphasizes dominant dimension)
- **Lethal override**: if lethal possible → `BSV = ABSOLUTE_LETHAL_VALUE (999.0)`

**Phase Weights**:
| Phase | Tempo | Value | Survival |
|-------|-------|-------|----------|
| Early (≤4) | 1.3 | 0.7 | 0.5 |
| Mid (5-7) | 1.0 | 1.0 | 1.0 |
| Late (≥8) | 0.7 | 1.2 | 1.5 |

### 3. Keyword Interactions (`hs_analysis/scorers/keyword_interactions.py`)

**Responsibility**: Static lookup table for keyword-vs-keyword value multipliers derived from rules analysis.

**8 Interactions**:
- Poisonous vs Divine Shield → ×0.1
- Stealth + Taunt → taunt value = 0
- Immune + Taunt → taunt value = 0
- Freeze + Windfury → ×0.5
- Lifesteal + Divine Shield enemy → lifesteal = 0
- Reborn + Deathrattle → ×1.5
- Brann + Battlecry → ×2.0
- Rivendare + Deathrattle → ×2.0

**API**: `get_interaction_multiplier(card_keywords: List[str], target_keywords: List[str]) -> float`

### 4. Mechanic Base Values (`hs_analysis/scorers/mechanic_base_values.py`)

**Responsibility**: CIV base value formulas for 2026 mechanics.

**9 Mechanics**:
- Imbue: `Σ(k=1..∞) base_hp × 0.8^(k-1)` (diminishing marginal)
- Herald: `soldier_value × 1 + jump(floor(n/2))` (threshold jumps)
- Shatter: `(half_value × 2) × merge_bonus`
- Kindred: `base_value × P(match_race_or_school)`
- Rewind: `max(branch_A_value, branch_B_value)`
- Dark Gift: `avg(all_10_gift_values)`
- Colossal+N: `(body + N × appendage) × space_penalty`
- Dormant: `awakened_value × P(survive_dormant)`
- Quest: `reward_value × P(complete)`

**API**: `get_mechanic_base_value(mechanic: str, params: dict) -> float`

### 5. Composite Integration (`hs_analysis/evaluators/composite.py` — minimal change)

**Responsibility**: Switch between legacy and V10 evaluation paths.

**Change**: Add a module-level flag `V10_ENABLED = False` and a new function `evaluate_v10(state)` that calls `bsv_fusion(state)`. The existing `evaluate()` function remains unchanged. The RHEA engine can opt-in by setting the flag.

## Data Flow

```
Card + GameState
       │
       ▼
  ┌─ CIV Layer (existing, unchanged) ─────────────┐
  │ card.v7_score ← L1→L2→L3→L4→L5→L6→L7 pipeline │
  │ contextual_score(card, state) from V8          │
  │ + keyword_interactions lookup                  │
  │ + mechanic_base_values for 2026 cards          │
  └───────────────┬────────────────────────────────┘
                  │ CIV value (float)
                  ▼
  ┌─ SIV Layer (new) ──────────────────────────────┐
  │ siv_score(card, state) =                       │
  │   CIV × lethal × taunt × curve × position     │
  │        × trigger × synergy × progress × counter│
  └───────────────┬────────────────────────────────┘
                  │ SIV value (float, clamped [0.01, 100.0])
                  ▼
  ┌─ BSV Layer (new) ──────────────────────────────┐
  │ Tempo axis = Σ SIV(friendly) - Σ SIV(enemy)... │
  │ Value axis = Σ SIV(hand) + card_advantage...   │
  │ Survival axis = hero_safety - threats...        │
  │                                                 │
  │ BSV = softmax_fusion(tempo, value, survival)   │
  │ + lethal override if applicable                 │
  └───────────────┬────────────────────────────────┘
                  │ final board state value (float)
                  ▼
            RHEA fitness
```

## Error Handling

- **Missing modifier state** → each modifier returns 1.0 (no effect), never crashes
- **Missing JSON data** → pool_quality, rewind_deltas, turn_data all optional; skip that modifier
- **Numerical overflow** → SIV clamped to [0.01, 100.0]; softmax naturally handles large values
- **Division by zero** → `max(denominator, 0.001)` in all division operations
- **Performance timeout** → each modifier <0.1ms budget; if exceeded, return 1.0
- **Invalid mechanic params** → `get_mechanic_base_value` returns 0.0 with warning log
- **Empty board/hand** → sum over empty list = 0.0, no special casing needed

## Testing Strategy

- **Unit tests per modifier** — 8 test files, one per SIV modifier, testing boundary conditions (0 HP enemy, full HP enemy, empty board, full board, etc.)
- **BSV fusion tests** — verify softmax produces correct weights; verify lethal override; verify phase weight switching
- **Keyword interaction tests** — verify all 8 interaction pairs; verify no-interaction returns 1.0
- **Mechanic base value tests** — verify each of 9 mechanics with sample params
- **Integration test** — `siv_score(card, state)` → `bsv_fusion(state)` → scalar output, compared against expected ranges
- **Regression guard** — run full 233-test suite after implementation; all must pass
- **A/B comparison** — `V10_ENABLED=True` vs `V10_ENABLED=False` on sample game states to verify V10 produces different (and theoretically better) scores
- **Performance test** — benchmark `siv_score` and `bsv_fusion` to confirm <1ms total

## Open Questions

- **Temperature tuning** — 0.5 is the initial value; may need calibration against real game replays
- **LETHAL_SCALE** — 3.0 is from design; may need adjustment after testing
- **V10_ENABLED flag** — should this be a config file setting or runtime flag? Currently planning as runtime flag
- **Mechanic base value calibration** — formulas are theoretical; need empirical validation against HSReplay data

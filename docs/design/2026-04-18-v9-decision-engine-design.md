---
date: 2026-04-18
topic: "V9 Decision-Theoretic Engine"
status: draft
---

# V9 Decision-Theoretic Engine — Design Document

## Problem Statement

The current AI decision pipeline has a fundamental gap: **it scores cards, not decisions**.

V2→V8 produce increasingly sophisticated *static card quality ratings*. The RHEA engine searches over action sequences within a single turn. But the evaluation function (`composite_evaluator`) is a weighted sum of sub-scores that **cannot reason about**:

- **Opponent responses**: "If I play these 3 minions, opponent's AOE clears everything"
- **Resource trade-offs**: "Using my weapon to clear saves mana but puts me in lethal range"
- **Card draw value**: "Drawing card X from my remaining 8-card deck has probability 12.5%"
- **Discover expected outcomes**: "Discovering a Beast from a pool with avg quality 4.2 gives EV = 4.2"
- **Multi-turn planning**: "This turn I set up lethal for next turn"
- **Secret play-around**: "Opponent is Hunter with 2 secrets, attacking face might trigger Explosive Trap"

The user's vision is a **decision-theoretic model** that evaluates complete action plans against all game context, producing maximum expected value decisions.

### What We're Building

A **3-phase enhancement** to the existing RHEA engine:

1. **Phase A — Expanded Action Space + Risk-Aware Evaluation**: New action types, opponent modeling integration, risk assessment
2. **Phase B — Multi-Turn Lookahead**: Opponent turn simulation, 2-3 turn planning, draw probability
3. **Phase C — Scenario Test Generator**: Comprehensive test infrastructure with realistic game states

---

## Constraints

### Non-Negotiable
- **Backward compatible**: All existing tests must continue passing
- **Time budget**: RHEA search must complete within 200ms (currently 75ms, expanding to allow richer evaluation)
- **No external API calls at runtime**: All data must be pre-loaded (JSON/SQLite)
- **Python-only**: No C extensions, no GPU requirements
- **Graceful degradation**: Missing data files → fall back to simpler evaluation

### Technical Limits
- **Deck lists**: HSReplay only provides 8 signature cards per archetype, not full 30-card lists. We must synthesize remaining 22 cards from class card pool + play_rate data.
- **Opponent prediction**: Bayesian model can identify archetype (~60% confidence after 3-4 cards seen) but cannot predict specific card choices.
- **Secret simulation**: We can estimate secret probabilities but cannot know which secret is active.
- **Discover outcomes**: We can compute pool expected value but cannot enumerate all possible choices in real-time.

### Performance Budget
- Action enumeration: < 5ms
- State evaluation: < 2ms per state
- RHEA full search: < 200ms
- Multi-turn lookahead: < 50ms additional

---

## Approach

### Why Evolutionary Search (RHEA) Over Monte Carlo Tree Search

I considered three approaches:

1. **MCTS** — Full game tree search with UCB1 selection. Rejected because: (a) branching factor in Hearthstone is 50-200 per state (each card play × each target × each position), (b) most rollouts would be random and uninformative, (c) our simulation is incomplete (no deathrattles, no secrets, no battlecries).

2. **Minimax with alpha-beta pruning** — Classic game tree search. Rejected because: (a) opponent's moves are probabilistic not adversarial, (b) hidden information (opponent hand) makes pruning unreliable, (c) same branching factor problem as MCTS.

3. **Enhanced RHEA (CHOSEN)** — Keep evolutionary search but dramatically improve the fitness function. **Why**: (a) RHEA naturally handles variable-length action sequences, (b) the population maintains diversity of plans, (c) the main weakness was the evaluation function, not the search algorithm, (d) we can add risk-aware evaluation without changing the search structure.

**The key insight**: The problem isn't search — it's evaluation. RHEA explores action space well. What's missing is that the evaluation function can't distinguish "great board state but I'm dead to opponent's AOE" from "great board state and I'm safe."

---

## Architecture

### High-Level System Diagram

```
                    ┌─────────────────────────────────────┐
                    │         V9 Decision Engine           │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         RHEA Search Core             │
                    │  (evolutionary, same algorithm)      │
                    └──────────────┬──────────────────────┘
                                   │ evaluates chromosomes
                    ┌──────────────▼──────────────────────┐
                    │      V9 Fitness Function             │
                    │                                      │
                    │  V(state_after) - V(state_before)    │
                    │  - Risk(transition)                  │
                    └────┬──────┬──────┬──────┬───────────┘
                         │      │      │      │
              ┌──────────┘      │      │      └──────────┐
              ▼                 ▼      ▼                  ▼
    ┌─────────────────┐ ┌──────────┐ ┌─────────┐ ┌──────────────┐
    │  Value Evaluator│ │  Risk    │ │ Opponent │ │ Multi-Turn   │
    │  (enhanced V8)  │ │ Assessor │ │ Model    │ │ Lookahead    │
    │                 │ │          │ │          │ │              │
    │ tempo + value + │ │ AOE risk │ │ Bayesian │ │ 1-turn ahead │
    │ survival +      │ │ lethal   │ │ deck     │ │ opponent sim │
    │ draw EV +       │ │ risk     │ │ predict  │ │ + draw prob  │
    │ discover EV     │ │ secret   │ │          │ │ + lethal     │
    │                 │ │ play-    │ │ response │ │ setup bonus  │
    │                 │ │ around   │ │ catalog  │ │              │
    └─────────────────┘ └──────────┘ └─────────┘ └──────────────┘
              │                 │          │            │
              ▼                 ▼          ▼            ▼
    ┌────────────────────────────────────────────────────────────┐
    │                     Data Layer                             │
    │                                                            │
    │  v7_scoring_report.json    pool_quality_report.json        │
    │  unified_standard.json     rewind_delta_report.json         │
    │  hsreplay_cache.db         card_turn_data.json              │
    │  response_catalog.json (NEW)                                │
    └────────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Game Start:
   Deck list → GameState(deck_list=[Card, ...30 cards])
   BayesianOpponentModel(opponent_class) → loaded

2. Each Turn:
   GameState captured → RHEA.search(state, time_budget=200ms)
     │
     ├─ enumerate_legal_actions(state) → List[Action]
     │   Includes: PLAY, ATTACK, WEAPON_ATTACK, HERO_POWER_TARGETED,
     │             USE_LOCATION, END_TURN
     │
     ├─ For each chromosome (action sequence):
     │   │
     │   ├─ apply_action() × N → state_after
     │   │   (expanded: overload, weapon attacks, location use)
     │   │
     │   └─ fitness = v9_evaluate(state_before, state_after)
     │       │
     │       ├─ V(state) = v9_value(state)  [tempo+value+survival+draw_EV]
     │       │
     │       ├─ Risk = v9_risk(state, opponent_model)
     │       │   [AOE vulnerability, retaliation, secret danger]
     │       │
     │       └─ Lookahead = v9_lookahead(state_after, opponent_model)
     │           [opponent response, draw probability, lethal setup]
     │
     └─ Return best chromosome → action sequence

3. Opponent Plays Card:
   BayesianOpponentModel.update(seen_card_dbfId) → updated posteriors
```

---

## Components

### Component 1: Expanded Action Enumerator

**Purpose**: Generate all legal action types, not just the current 4.

**New action types**:

| Action | Trigger | Data |
|--------|---------|------|
| `WEAPON_ATTACK` | Hero has weapon equipped | `target_index`: enemy hero or minion |
| `USE_LOCATION` | Hand contains LOCATION card with charges > 0 | `card_index`, optional `target_index` |
| `HERO_POWER_TARGETED` | Class requires target (Mage, Priest, Hunter HP) | `target_index` |
| `DISCOVER_PICK` | Previous action generated discover | `pick_index`: 0-2 (from pool top-3 by EV) |

**Location action**: Location cards have `health` = charges. Each use costs 1 charge. Location effects are parsed from card text (same regex patterns as spell effects). A location action is legal when: card is in hand, `health > 0`, mana available (locations typically cost 0-2 but we check card cost).

**Weapon attack**: Legal when `hero.weapon` is not None and weapon has `health > 0`. Creates mutual damage: weapon loses 1 durability, target takes `weapon.attack` damage.

**Discover pick**: This is a *composite action*. When a card with discover is played, instead of immediately resolving the discover, we generate a single "best EV pick" based on pool quality data. This avoids branching the search tree 3 ways for every discover.

### Component 2: Overload Resolution

**Purpose**: Track and apply overload costs across the turn boundary.

**Current state**: `ManaState.overloaded` and `overload_next` exist but are never used. Card text contains overload values (e.g., "过载：(X)").

**Implementation**: When `apply_action(PLAY)` is called for a card with overload:
1. Parse overload value from card text (regex: `过载[：:]\s*[（(]\s*(\d+)\s*[）)]`)
2. Add to `state.mana.overload_next`
3. In multi-turn lookahead, `next_turn_available = min(max_mana + 1, 10) - overload_next`

### Component 3: V9 Value Evaluator

**Purpose**: Replace the flat `composite_evaluator.evaluate()` with a context-aware value function.

**Formula**:
```
V9(state) = w_t × Tempo(state) + w_v × Value(state) + w_s × Survival(state) + w_d × DrawEV(state)
```

Where weights are phase-adaptive (using existing `multi_objective_evaluator` scalarize logic):

| Phase | w_t | w_v | w_s | w_d |
|-------|-----|-----|-----|-----|
| Early (1-4) | 1.2 | 0.8 | 0.6 | 0.3 |
| Mid (5-7) | 1.0 | 1.0 | 1.0 | 0.5 |
| Late (8+) | 0.8 | 1.2 | 1.5 | 0.7 |

**Tempo**: Existing `eval_tempo()` from multi_objective_evaluator. Measures board control + mana efficiency + burst potential.

**Value**: V8 hand quality (`hand_contextual_value`) + resource generation + card advantage. Now also considers **draw EV** (see below).

**Survival**: Existing `eval_survival()` but enhanced with opponent burst estimation (see Risk Assessor).

**DrawEV (NEW)**: Expected value of future draws from remaining deck.

```
DrawEV = Σ_{card in deck} P(draw card in next N turns) × delta_value(card)
```

Where:
- `deck` = known deck list (30 cards - drawn cards)
- `P(draw card in next turn)` = `count_in_deck / deck_remaining`
- `delta_value(card)` = `card.v7_score - avg_hand_quality` (value improvement from drawing)
- This is computed at a **hand level**, not per-card, as a bonus for "hand improvement potential"

### Component 4: Risk Assessor

**Purpose**: Quantify the danger of reaching a given game state.

**Formula**:
```
Risk(state, opponent_model) = -(
    α × AOE_Vulnerability +
    β × Retaliation_Danger +
    γ × Secret_Threat +
    δ × Overextension_Penalty
)
```

**AOE Vulnerability**:
```
AOE_Vuln = board_total_value × P(opponent_has_AOE)
```
- `board_total_value` = Σ minion (attack + health + keyword bonuses) for friendly minions
- `P(opponent_has_AOE)` = estimated from opponent's class + Bayesian archetype prediction
- Pre-computed **response catalog**: per-class AOE cards with their damage amounts
- If opponent is predicted to be Control, P(AOE) is higher; if Aggro, P(AOE) is lower

**Retaliation Danger**:
```
Retaliation = max(0, opponent_burst_potential - hero_hp - hero_armor) × lethal_urgency
```
- `opponent_burst_potential` = opponent board attack + estimated spell damage from archetype
- `lethal_urgency` = 1.0 normally, scales to 3.0 when gap < 5 HP
- This subsumes the existing `eval_threat()` logic but adds opponent archetype awareness

**Secret Threat**:
```
Secret_Threat = Σ_{secret in opponent.secrets} P(secret_type) × damage_if_triggered
```
- For each unknown secret, estimate probability of each secret type based on opponent class
- Pre-computed **secret catalog**: per-class secret list with trigger conditions and damage
- If attacking with a minion and opponent has Hunter secret: P(Explosive Trap) × 2 damage × number of minions
- If playing a minion and opponent has Mage secret: P(Counterspell) × card cost wasted

**Overextension Penalty**:
```
Overextension = board_count × (board_count - 3) × P(opponent_has_AOE) × 0.1
```
- Kicks in when board has >3 minions (diminishing returns from more minions)
- Multiplied by AOE probability (if opponent unlikely to have AOE, overextension is cheap)
- Replaces the V8 fixed 0.7× multiplier with a dynamic risk-based penalty

### Component 5: Opponent Response Catalog

**Purpose**: Pre-computed database of per-class responses (AOE, removal, burst, healing).

**Data structure** (new file: `hs_cards/response_catalog.json`):

```
{
  "MAGE": {
    "aoe": [
      {"name": "Blizzard", "damage": 2, "cost": 6, "freeze": true},
      ...
    ],
    "single_removal": [
      {"name": "Fireball", "damage": 6, "cost": 4},
      ...
    ],
    "burst_spells": [
      {"name": "Pyroblast", "damage": 10, "cost": 10},
      ...
    ],
    "healing": [],
    "taunt_minions": [...],
    "secrets": [
      {"name": "Counterspell", "trigger": "play_spell", "effect": "counter"},
      {"name": "Explosive Runes", "trigger": "play_minion", "damage": 6},
      ...
    ]
  },
  ...
}
```

**Generated offline** by filtering `unified_standard.json` by class + card type + text regex patterns. This is a one-time generation step, similar to `pool_quality_generator.py`.

### Component 6: Bayesian Opponent Integration

**Purpose**: Wire the existing `BayesianOpponentModel` into the RHEA search pipeline.

**Current gap**: The model exists in `bayesian_opponent.py` but is never imported by `rhea_engine.py`.

**Integration points**:

1. **RHEAEngine.__init__**: Accept optional `opponent_model: BayesianOpponentModel` parameter. If provided, use it for risk assessment. If not, use class-level heuristics.

2. **Risk Assessor queries**: When computing `P(opponent_has_AOE)`, the risk assessor asks the opponent model for `predict_next_actions(n=5)` and checks if any predicted cards are AOE effects.

3. **Opponent burst estimation**: `predict_next_actions()` returns signature cards with probabilities. Sum damage values of predicted spell cards weighted by probability.

4. **Confidence gating**: Only use opponent model predictions when `get_lock()` confidence > 0.30 (matching existing gating thresholds in `bayesian_opponent.py`). Below this threshold, fall back to class-level heuristics.

### Component 7: Multi-Turn Lookahead

**Purpose**: Evaluate not just the current turn, but the likely state 1-2 turns ahead.

**Algorithm** (lightweight, not full MCTS):

```
For the top-K chromosomes from RHEA search:
  1. Simulate opponent's next turn (simplified):
     a. Predict opponent's best play using archetype + class heuristics
     b. Apply opponent play to state_after → state_opponent_turn
  2. Evaluate state_opponent_turn:
     a. How much mana do I have next turn? min(max_mana+1, 10) - overload
     b. What can I do with that mana? (quick scan of hand + expected draw)
     c. Is lethal setup possible? (burst_potential >= opponent_hp)
  3. Lookahead bonus = f(V(state_opponent_turn)) - f(V(state_after))
```

**Opponent turn simulation** is deliberately simplified:
- **Opponent draws 1 card** (unknown, estimated by archetype avg card quality)
- **Opponent plays cards** using greedy heuristic: play highest-cost affordable card from predicted hand
- **Opponent attacks** using simple rule: trade if favorable, go face if not
- **No branching**: single most-likely opponent play, not a tree

**Draw probability for multi-turn planning**:
```
P(drawing specific card in next 2 turns) = 1 - (1 - count/deck_remaining)^2
```
For "any card with v7_score > X":
```
P(good_draw) = count(good_cards) / deck_remaining
```

### Component 8: Scenario Test Generator

**Purpose**: Generate realistic game states for comprehensive testing.

**Architecture**:

```
ScenarioGenerator
├── DeckBuilder
│   ├── from_archetype(archetype_id) → 30-card deck
│   └── from_class(class_name) → random meta deck
├── StateBuilder
│   ├── at_turn(turn, deck, going_first) → GameState
│   ├── with_hand(cards) → GameState (fluent)
│   ├── with_board(minions) → GameState (fluent)
│   ├── with_opponent(state) → GameState (fluent)
│   └── with_mechanics(quest进度, imbue进度, etc) → GameState (fluent)
└── ScenarioTemplate
    ├── aggro_vs_control
    ├── midrange_mirror
    ├── lethal_setup
    ├── resource_advantage
    ├── discover_decision
    ├── removal_choice
    ├── overextension_test
    └── multi_turn_planning
```

**Deck construction** from partial data:
- Start with 8 signature cards from archetype
- Fill remaining 22 cards from class + neutral pool using:
  - `card_stats.play_rate` as selection weight (meta-representative)
  - Class filter matches archetype class
  - Duplicate up to 2 copies per card
  - Ensure mana curve balance (use `avg_turns` to distribute)

**State generation per Hearthstone rules**:

| Parameter | First Player | Second Player (Coin) |
|-----------|-------------|---------------------|
| Turn T starting hand | 3 + T-1 draws - cards played | 4 + T-1 draws - cards played + coin |
| Max hand size | 10 | 10 |
| Mana available | min(T, 10) - overload | min(T+1, 10) - overload (coin doesn't affect mana) |
| Second player gets | — | "The Coin" (cost 0, gain 1 mana) |
| Starting HP | 30 | 30 |
| Starting deck | 30 - starting hand | 30 - starting hand |

Wait — correction: second player in HS gets 4 cards + The Coin. Mana is same as first player (turn-based, not hand-based). The Coin is a 0-cost spell that gives 1 mana.

**Health simulation**: Use `avg_turns` data to estimate HP loss per turn:
- Rough model: HP_loss_per_turn = 3-5 in early game, 5-8 in mid game, 8-15 in late game
- Adjusted by opponent class (aggro = higher, control = lower)

**Board simulation**: Generate realistic board states:
- Turn 1-2: 0-1 minions per side
- Turn 3-4: 1-2 minions per side
- Turn 5-7: 2-4 minions per side
- Turn 8+: 2-5 minions per side (or empty if board clears happened)

**Mechanic progress generators**:

| Mechanic | Generation Rule |
|----------|----------------|
| Quest progress | Random 0-3 steps out of quest requirement |
| Imbue progress | Random 0-2 imbues |
| Location charges | health - random(0, health) used charges |
| Secrets | Random 0-2 class-appropriate secrets |
| Discovered cards | Random card from appropriate pool |

---

## Data Flow — End to End

### Phase A: Pre-computation (offline, one-time)

```
1. response_catalog_generator.py
   Input: unified_standard.json
   Output: hs_cards/response_catalog.json (11 classes × response types)

2. Existing generators (unchanged):
   pool_quality_generator.py → pool_quality_report.json
   rewind_delta_generator.py → rewind_delta_report.json
```

### Phase B: Game Setup (once per game)

```
1. Load deck list (30 Card objects)
2. Load BayesianOpponentModel(opponent_class)
3. RHEAEngine(opponent_model=model, deck_list=deck)
4. Load response_catalog.json into memory
5. Pre-compute deck composition: {dbfId: count_in_deck}
```

### Phase C: Each Turn (runtime, <200ms budget)

```
1. Capture current GameState
2. Update opponent model with any newly seen cards
3. RHEA.search(state, budget_ms=200)
   │
   ├─ Population initialization (50 chromosomes)
   │   └─ enumerate_legal_actions(state) → expanded action set
   │
   ├─ For each generation (up to 200):
   │   ├─ For each chromosome:
   │   │   ├─ apply_actions() → state_after (with overload, weapon attacks)
   │   │   ├─ v9_evaluate(state_before, state_after, opponent_model)
   │   │   │   ├─ V9_value(state_after) [tempo+value+survival+draw_EV]
   │   │   │   ├─ Risk(state_after, opponent_model) [AOE+retaliation+secret]
   │   │   │   └─ Lookahead(state_after, opponent_model) [1-turn ahead]
   │   │   └─ fitness = V(after) - V(before) - Risk + Lookahead_bonus
   │   ├─ Selection + crossover + mutation
   │   └─ Track best individual
   │
   └─ Return best chromosome → action sequence
```

---

## Error Handling Strategy

### Missing Data
- **No response catalog**: Fall back to class-level AOE probability heuristics (hardcoded: MAGE=0.7, WARLOCK=0.5, HUNTER=0.2, etc.)
- **No pool quality data**: V8 already handles this (returns raw v7_score)
- **No Bayesian model**: Fall back to class-level opponent heuristics
- **No deck list**: DrawEV defaults to 0, deck_remaining treated as unknown

### Invalid States
- **Board full + minion play attempt**: Already handled in enumerator (rejects PLAY_MINION when board_full())
- **Negative mana**: Checked in enumerator (card.cost > available)
- **Weapon break during attack**: apply_action decrements weapon durability; if reaches 0, clear weapon
- **Overload exceeds next turn mana**: Capped at next turn mana (can't go below 0 available)

### Timeout Safety
- RHEA already has time budget enforcement at `rhea_engine.py:404`
- Enhanced evaluation increases per-evaluation cost by ~3x (from ~0.5ms to ~1.5ms)
- Population size reduced from 50 to 30 to compensate
- Generation limit reduced from 200 to 100
- Early termination if best fitness hasn't improved in 20 generations

---

## Testing Strategy

### Unit Tests (per component)

| Component | Test Count | Key Assertions |
|-----------|-----------|----------------|
| Expanded Action Enumerator | 12 | Weapon attack generated, location use generated, targeted hero power, overload resolution |
| Risk Assessor | 15 | AOE vulnerability increases with board size, retaliation danger scales with HP, secret threat computed per class |
| Response Catalog Generator | 10 | All 11 classes have entries, AOE cards correctly classified, damage values parsed |
| Draw EV Calculator | 8 | Known deck → exact probability, empty deck → 0, single card → 1/N |
| Bayesian Integration | 6 | Lock confidence gates predictions, no model → heuristics, model predicts AOE cards |
| Multi-Turn Lookahead | 8 | Opponent turn simulated, overload applied, lethal setup detected, draw probability computed |

### Integration Tests (cross-component)

| Test | What It Verifies |
|------|-----------------|
| Full game turn | RHEA search with all new components produces valid action sequence |
| Risk-adjusted trade | Engine prefers safe trade over risky face attack when opponent has burst |
| AOE awareness | Engine avoids playing 5th minion when opponent is Mage with predicted AOE |
| Discover decision | Engine correctly evaluates discover EV vs playing a guaranteed card |
| Overload planning | Engine accounts for overload penalty in multi-turn evaluation |
| Weapon vs spell removal | Engine weighs weapon HP cost against spell mana cost correctly |

### Scenario Tests (end-to-end)

| Scenario | Classes | Turn | Key Decision |
|----------|---------|------|-------------|
| Aggro mirror | HUNTER vs HUNTER | 5 | Face vs trade decision |
| Control vs aggro | WARRIOR vs HUNTER | 7 | Stabilize vs develop |
| Lethal setup | ROGUE vs MAGE | 9 | Go face now or set up guaranteed lethal |
| Discover choice | PRIEST vs WARLOCK | 6 | Discover heal vs discover removal |
| Overextension risk | DRUID vs MAGE | 8 | Play 7th minion or hold back |
| Resource planning | WARLOCK vs PRIEST | 10 | Tap for card vs play on-curve |
| Secret play-around | Any vs HUNTER | 4 | Attack into potential Explosive Trap |
| Weapon decision | WARRIOR vs ROGUE | 6 | Weapon clear (take damage) vs spell clear |
| Quest reward turn | HUNTER vs Any | 8 | Quest completes — plan the reward turn |
| Multi-turn lethal | MAGE vs Any | 7 | Set up 2-turn lethal with spell hand |

---

## Open Questions

1. **Deck list availability**: The test generator needs full 30-card deck lists. We only have 8 signature cards per archetype. The proposed approach (fill from class pool using play_rate) will produce *plausible* but not *accurate* decks. Is this acceptable, or should we scrape full deck lists from an external source?

2. **Discover branching**: The current design uses "best EV pick" for discover (no branching). An alternative is to create 3 child states (one per discover option) and evaluate each. This increases search space by 3x per discover card. Worth the cost?

3. **Opponent turn simulation depth**: The multi-turn lookahead simulates 1 opponent turn with a single most-likely play. Should we try 2-3 opponent scenarios (optimistic/pessimistic/average) for more robust planning?

4. **Secret resolution**: The current design estimates secret probabilities per class. An alternative is to track which secrets have already been seen this game (excluded from probability). This requires game-level memory across turns.

5. **Performance budget**: Expanding from 75ms to 200ms is a significant increase. Should we benchmark first and adjust the budget, or is 200ms an acceptable hard limit?

6. **Location card effects**: Locations have complex effects (choose a minion, discover a spell, etc.). The simplified model treats them like spells. Is this sufficient, or do we need location-specific simulation?

---

## Phased Delivery

### Phase A: Action Space + Risk (highest value, ~60% of the impact)

| Deliverable | New/Modified | Description |
|-------------|-------------|-------------|
| `v9_action_enumerator.py` | NEW | Expanded action types (weapon attack, location, targeted HP) |
| `v9_risk_assessor.py` | NEW | AOE vulnerability, retaliation danger, secret threat |
| `response_catalog_generator.py` | NEW | Offline generator for per-class response database |
| `v9_fitness.py` | NEW | V9 fitness function combining value + risk + lookahead |
| `rhea_engine.py` | MODIFIED | Wire V9 fitness, accept opponent_model, expanded actions |
| `apply_action()` expansion | MODIFIED | Weapon attacks, overload resolution, location use |
| `game_state.py` | MODIFIED | Add `deck_list: List[Card]` field, weapon durability tracking |
| Tests | NEW | 30+ unit tests for new components |

### Phase B: Multi-Turn Lookahead (medium value, ~25% of the impact)

| Deliverable | New/Modified | Description |
|-------------|-------------|-------------|
| `v9_lookahead.py` | NEW | Opponent turn simulation, draw probability, lethal setup |
| `v9_deck_tracker.py` | NEW | Track remaining deck, compute draw probabilities |
| `bayesian_opponent.py` | MODIFIED | Add `predict_response()` method for opponent turn sim |
| Tests | NEW | 15+ unit tests |

### Phase C: Scenario Generator (enabling, ~15% direct impact but critical for validation)

| Deliverable | New/Modified | Description |
|-------------|-------------|-------------|
| `scenario_generator.py` | NEW | DeckBuilder + StateBuilder + ScenarioTemplate |
| `test_scenarios.py` | NEW | 10+ end-to-end scenario tests |
| `test_scenario_generator.py` | NEW | Tests for the generator itself |

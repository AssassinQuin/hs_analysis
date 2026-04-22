---
date: 2026-04-18
topic: "V3 Decision Engine Upgrade — Multi-Objective Evaluation + Particle Filter Opponent Model"
status: validated
---

# V3 Decision Engine Upgrade Design

## Problem Statement

The current V2 engine has several critical gaps preventing it from achieving the goal of **multi-turn lethal planning using all available resources**:

1. **No spell/hero power effect simulation** — spells simply leave hand, dealing no damage/healing/draw
2. **Single-turn myopia** — RHEA only plans the current turn, cannot set up multi-turn lethal sequences
3. **Linear weighted evaluation** — cannot capture non-linear interactions between resources (mana curve, hand size, board synergies)
4. **Brittle opponent model** — greedy heuristic that hurts RHEA performance when wrong (Goodman & Lucas 2020)
5. **Double-counting of board stats** — minion attack/health counted in both v2_adj and eval_board
6. **Broken crossover** — uniform crossover produces illegal action sequences
7. **No deathrattle/aura/secret effects** — major card effects completely ignored

## Constraints

- Decision time < 3 seconds per turn
- Memory < 50 MB
- No external ML framework dependencies (maintain interpretability)
- Must work with existing V2/L6 card scoring as foundation
- Python-only implementation (no C++/GPU)
- Target: Bronze-to-Diamond rank play (not competitive AI)

## Approach

### Chosen: Three-Phase Upgrade

**Phase 1: Fix Critical Bugs + Core Improvements** (repair + enhance)
**Phase 2: Multi-Objective Pareto Evaluation** (replace linear weights)
**Phase 3: Particle Filter Opponent Model** (replace single-deck locking)

**Rejected alternatives:**
- Full neural network evaluator — too opaque, needs training infrastructure we don't have
- Complete MCTS replacement of RHEA — research shows ISMCTS underperforms heuristics in complex card games (Malla 2025)
- AlphaZero-style self-play — requires game simulator we explicitly avoid

## Architecture

### Component Overview

```
GameState (fixed)
    ↓
BeliefState (NEW — Particle Filter)
    ↓
RHEA Search (improved — adaptive mutation, sequence crossover)
    ↓
MultiObjectiveEvaluator (NEW — replaces CompositeEvaluator)
    ├─ V_tempo(board_control + mana_efficiency + burst_potential)
    ├─ V_value(hand_quality + resource_generation + card_advantage)
    └─ V_survival(hero_safety + threat_reduction + lethal_defense)
    ↓
ParetoSelector (NEW — selects Pareto-optimal action sequences)
    ↓
DecisionPresenter (unchanged)
```

### Data Flow

```
1. Game state arrives (from log parser or manual input)
2. BeliefState.initialize(particles=10)
   - Each particle = (deck_id, hand_sample, weight)
   - Weights from Bayesian posterior P(deck_i | seen_cards)
3. RHEA.search(state, belief, time_budget=3000ms)
   - Enumerate legal actions (with spell effects!)
   - Evolve population with improved operators
   - Evaluate each chromosome against ALL weighted particles
4. MultiObjectiveEvaluator.evaluate(state_after)
   - Returns (V_tempo, V_value, V_survival) tuple
5. ParetoSelector.filter(population)
   - Keep only Pareto-optimal chromosomes
   - Rank remaining by scalarized score with game-phase-adaptive weights
6. DecisionPresenter.format(top_3)
```

## Components

### C1: Spell/Effect Simulator (Fix)

**Responsibility:** Apply card effects during action simulation, not just remove cards from hand.

**Effect categories to simulate:**
- Direct damage: reduce target HP by N
- Heal: increase friendly hero/minion HP by N
- Draw: add N random cards from deck pool to hand
- Summon: place N/M minion on board
- Buff: modify attack/health of target minion
- AOE: reduce all enemy minion HP by N
- Weapon: equip weapon with attack/durability
- Armor: increase hero armor by N
- Destroy: remove target minion regardless of HP
- Silence: remove all keywords and enchantments from target

**Effect resolution from card text parsing:**
- Reuse existing L3 text parser patterns (19 regex patterns)
- Map each pattern to a StateMutator function
- Apply mutations to lightweight state copies during RHEA search

### C2: Multi-Objective Evaluator (New)

**Responsibility:** Replace linear weighted sum with three independent objective functions.

**V_tempo(state):**
```
V_tempo = board_control + mana_efficiency + burst_potential

board_control = Σ(m.attack + m.health) for friendly minions
              - Σ(m.attack × threat_weight(m)) for enemy minions

mana_efficiency = mana_spent / mana_available  (ideal = 1.0)

burst_potential = Σ(card.direct_damage) for damage cards in hand
                + Σ(m.attack × can_attack_factor(m)) for friendly minions
```

**V_value(state):**
```
V_value = hand_quality + resource_generation + card_advantage

hand_quality = Σ(c.l6_score) for cards in hand

resource_generation = cards_drawn + cards_generated + cards_discovered

card_advantage = (hand_size + board_count + deck_remaining)
               - (opp_hand_count + opp_board_count + opp_deck_remaining)
```

**V_survival(state):**
```
V_survival = hero_safety + threat_reduction + lethal_defense

hero_safety = (hero.hp + hero.armor) / 30  (normalized)

threat_reduction = -Σ(m.attack × urgency(m)) for enemy minions
  where urgency(m) = m.attack × (has_charge ? 1.5 : has_rush ? 1.2 : 0.7)

lethal_defense = -50 if opponent has lethal on board, else 0
```

**Game-phase adaptive weights for Pareto scalarization:**

| Phase | Turns | V_tempo weight | V_value weight | V_survival weight |
|-------|-------|---------------|---------------|------------------|
| Early | 1-4 | 1.2 | 0.8 | 0.6 |
| Mid | 5-7 | 1.0 | 1.0 | 1.0 |
| Late | 8+ | 0.8 | 1.2 | 1.5 |

### C3: Particle Filter Opponent Model (New)

**Responsibility:** Replace single-deck Bayesian locking with weighted particle ensemble.

**Particle representation:**
```
Particle = {
    deck_id: str,           # archetype ID from HSReplay
    deck_cards: List[int],  # 30 card IDs
    played_cards: Set[int], # cards seen from opponent
    weight: float,          # P(deck_id | observations)
    remaining_cards: List[int]  # deck_cards - played_cards - on_board
}
```

**Algorithm:**
```
Initialize: K=10 particles, weights from HSReplay usage rates

On each opponent play:
  For each particle p:
    likelihood = count(card_in_deck) / remaining_cards_count
    p.weight *= likelihood
  Normalize weights so Σ w_k = 1.0
  If effective_sample_size < K/2:
    Resample (systematic resampling)

During RHEA evaluation:
  For chromosome c:
    For each particle p with weight > 0.05:  # skip low-weight particles
      S_opp = sample_opponent_response(state_after_c, p)
      fitness += p.weight × V(S_opp)
```

**Confidence gating** (Goodman & Lucas 2020):
```
max_weight = max(p.weight for p in particles)

if max_weight > 0.60:
    # Strong deck identification — use detailed opponent model
    use_opponent_model = True
elif max_weight > 0.30:
    # Moderate confidence — use weighted ensemble (weaker modeling)
    use_opponent_model = True  
    # But reduce fitness influence by confidence
else:
    # Low confidence — NO opponent model (better than wrong model for RHEA)
    use_opponent_model = False
```

### C4: Improved RHEA Operators (Enhancement)

**Sequence-preserving crossover:**
```
# Instead of gene-by-gene swapping, swap contiguous subsequences
n_point_crossover(parent1, parent2, n=2):
    crossover_points = sorted(random.sample(range(min(len1, len2)), n))
    child = parent1[0:points[0]] + parent2[points[0]:points[1]] + ...
    # Validate and repair if needed
```

**Adaptive mutation rate:**
```
diversity = std(fitness_values) / mean(fitness_values)
target_diversity = 0.5

if diversity < target_diversity * 0.5:
    mutation_rate *= 2.0    # Population converged — increase exploration
elif diversity > target_diversity * 2.0:
    mutation_rate *= 0.5    # Too diverse — focus exploitation
```

**Lethal-aware fitness:**
```
if state_after.opponent_hero.hp <= 0:
    fitness = 10000.0       # Immediate lethal — highest priority
elif can_lethal_next_turn(state_after):
    fitness = 5000.0        # Set up lethal — very high priority
```

### C5: Multi-Turn Setup Planning (New)

**Responsibility:** Enable multi-turn lethal setup planning.

**Approach:** Two-phase search

```
Phase A: Current turn search (RHEA as before)
  - Find best action sequence for current turn
  - Evaluate with multi-objective evaluator

Phase B: Next-turn evaluation (lightweight lookahead)
  - For top-3 chromosomes from Phase A:
    - Simulate opponent's most likely response
    - Enumerate OUR next-turn legal actions (using predicted draw)
    - Evaluate best possible next turn
  - Bonus fitness for setups that enable next-turn lethal
```

**Lethal setup detection:**
```
can_lethal_next_turn(state):
    predicted_draw = random card from remaining deck
    available_mana_next = min(state.mana.max + 1, 10)
    
    burst_damage = 0
    for card in state.hand + [predicted_draw]:
        if card has direct_damage and card.cost <= available_mana_next:
            burst_damage += card.damage
    for minion in state.board:
        if minion.can_attack_next_turn:
            burst_damage += minion.attack
    if state.hero.weapon:
        burst_damage += state.hero.weapon.attack
    
    return burst_damage >= opponent.hp + opponent.armor
```

## Error Handling

- **Particle filter degeneracy:** If all particles have near-zero weight, reset to HSReplay priors
- **Illegal chromosome from crossover:** Discard and generate new random chromosome
- **Spell effect parsing failure:** Fall back to "remove from hand" (current behavior)
- **RHEA timeout:** Return best chromosome found so far (elite preservation)
- **Empty evaluation result:** Return (0, 0, 0) tuple with warning

## Testing Strategy

### Unit Tests

| Test | What it verifies |
|------|-----------------|
| Spell damage simulation | Direct damage reduces target HP correctly |
| Heal simulation | Healing increases HP without exceeding max_health |
| Draw simulation | Cards added to hand, deck count decremented |
| Buff simulation | Minion stats modified correctly |
| AOE simulation | All enemy minions take damage |
| Deathrattle trigger | Dead minions trigger effects before removal |
| Divine shield interaction | Shield absorbs first hit, then removed |

### Integration Tests

| Test | What it verifies |
|------|-----------------|
| Multi-turn lethal setup | Engine finds 2-turn lethal over immediate suboptimal play |
| Particle filter update | Weights update correctly when opponent plays cards |
| Confidence gating | Opponent model disabled at low confidence |
| Pareto selection | Pareto-optimal actions selected over dominated ones |
| Phase-adaptive weights | Early game favors tempo, late game favors survival |

### Performance Tests

| Metric | Target |
|--------|--------|
| Full RHEA search | < 3 seconds |
| Single evaluation | < 100 µs |
| Particle filter update | < 1 ms |
| Memory usage | < 50 MB |

## Open Questions

1. **Spell target selection** — many spells require choosing a target. How to enumerate reasonable targets without exponential blowup?
2. **Deathrattle chain resolution** — deathrattles can trigger other deathrattles. How deep to recurse?
3. **Draw prediction** — predicting next draw from deck is pure random. Use expected value of deck or sample top card?
4. **Pareto scalarization weights** — the phase-adaptive weights still need tuning. Can we calibrate from HSReplay data?
5. **Particle count K** — more particles = better modeling but slower search. K=10 a good default?

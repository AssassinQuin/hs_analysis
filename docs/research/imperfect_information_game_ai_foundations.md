# Theoretical Foundations for Optimal Decision-Making in Turn-Based Card Games with Imperfect Information

## 1. POMDP Formalism for Card Games

### 1.1 What is a POMDP?

A **Partially Observable Markov Decision Process** (POMDP) is defined as a tuple `(S, A, O, T, Z, R, γ, b₀)` where:

- **S**: set of true game states (e.g., all cards in all locations, both players' hands, deck order)
- **A**: actions available (play card X, attack with minion Y, use hero power, end turn)
- **O**: observations the agent receives (own hand, board state, opponent's visible actions)
- **T(s'|s,a)**: transition probability — how the game state changes given an action
- **Z(o|a,s')**: observation probability — what you observe after an action
- **R(s,a)**: reward function
- **γ**: discount factor
- **b₀**: initial belief over states

### 1.2 Formalizing Hearthstone as a POMDP

**State Space (S):** The full game state includes:
- Both players' hands (cards, order)
- Both players' decks (cards, order)
- Board state (minions, positions, buffs, enchantments)
- Both heroes (HP, armor, weapon, hero power availability)
- Secrets in play
- Active effects (auras, triggers)
- Game phase (mulligan, main, combat)

This state space is astronomically large. For a typical constructed deck with 30 unique cards, the number of possible deck orderings alone is 30! ≈ 2.65 × 10³².

**Observation Space (O):** What a player can see:
- Own hand (exact cards)
- Board state (fully observable)
- Opponent's hand size (card count, not identity)
- Cards drawn from deck (revealed as they enter hand)
- Cards played by opponent (revealed upon play)
- Mulligan decisions
- Damage numbers (revealing some card effects)

**Belief State (b):** A probability distribution over all possible true states. In Hearthstone:
- What cards remain in opponent's deck?
- What cards is the opponent holding?
- What secrets might the opponent have?
- What order do cards appear in decks?

### 1.3 Belief State Representation

**Exact belief** is intractable for Hearthstone. The belief is a probability distribution over all possible opponent hands × deck orderings × secrets.

**Practical approaches:**

1. **Particle Filter Belief**: Represent belief as a set of weighted particles (state samples). Each particle is one possible "true state" consistent with observations. For Hearthstone:
   - Sample possible opponent hands from remaining card pool
   - Weight particles by how consistent they are with observed opponent behavior
   - Resample when observations deviate

2. **Card Probability Tracking**: Maintain a probability distribution over each unknown card. Track:
   - Cards seen (played, revealed, discovered)
   - Cards in known deck list (if available)
   - Bayesian update based on opponent actions (e.g., "didn't play AoE on turn 4 → less likely to have AoE")

3. **Opponent Action Model**: Augment belief with a model of opponent behavior:
   - What would a rational opponent keep in mulligan?
   - What turns are certain cards typically played?
   - Bayesian inference from opponent's action sequence

### 1.4 POMDP Solvers

**POMCP (Partially Observable Monte Carlo Planning)** — Silver & Veness, 2010:
- Online solver that extends MCTS to POMDPs
- Each node in the search tree corresponds to an **action-observation history**
- Uses particle filtering for belief representation
- At each decision point:
  1. Sample a state from the current belief
  2. Run MCTS simulation from that state
  3. Update belief based on the observation received
  4. Repeat for budget iterations
- **Key advantage**: No direct dependence on state space size
- **Complexity**: O(budget × depth × avg_branching)

**DESPOT (Determinized Sparse Partially Observable Tree)** — Somani et al., 2013:
- Pre-computes a set of "determinized" scenarios (fixed random seeds)
- Builds a sparse search tree over these scenarios
- Better worst-case performance bounds than POMCP
- More amenable to GPU parallelization
- **DESPOT-α** variant uses alpha-vectors for value function approximation

**POMCP-winner (used in AlphaGo-style systems)**:
- In Go, the "observation" is the board state (nearly perfect information)
- AlphaGo/AlphaZero use MCTS with neural network priors, effectively a "POMCP-lite" where observations are nearly deterministic
- For imperfect information games, the core idea is: **use neural networks to provide strong priors for both action selection and belief updating**

### 1.5 The POSG Extension

For two-player games, the POMDP becomes a **Partially Observable Stochastic Game (POSG)**:

- Both players have partial observations
- The solution concept shifts from "optimal policy" to **Nash equilibrium**
- Counterfactual Regret Minimization (CFR) finds Nash equilibria in extensive-form games
- **Recent breakthrough (Becker & Sunberg, 2024)**: CDIT (Conditional Distribution Information Set Tree) combines:
  - POMDP-inspired particle filtering for belief approximation
  - EFG-inspired information sets for multi-agent reasoning
  - External Sampling CFR (ESCFR) for equilibrium finding
  - **Key result**: No direct computational complexity dependence on state space size

**Architecture Implication for Hearthstone AI:**
```
┌─────────────────────────────────────┐
│          Belief State Layer          │
│  ┌───────┐  ┌───────┐  ┌───────┐   │
│  │Particle│  │Card   │  │Opponent│  │
│  │Filter  │  │Prob.  │  │Model   │  │
│  └───────┘  └───────┘  └───────┘   │
├─────────────────────────────────────┤
│          Search Layer               │
│  ┌──────────────────────────────┐   │
│  │ MCTS / POMCP over belief     │   │
│  │ states, with NN priors       │   │
│  └──────────────────────────────┘   │
├─────────────────────────────────────┤
│          Evaluation Layer           │
│  ┌───────┐  ┌───────────────────┐  │
│  │Neural  │  │Heuristic eval     │  │
│  │Network │  │(board control,    │  │
│  │Value   │  │ tempo, card adv.) │  │
│  └───────┘  └───────────────────┘  │
└─────────────────────────────────────┘
```

---

## 2. MCTS Variants for Large Action Spaces

### 2.1 Standard MCTS Limitations

Standard UCT (Upper Confidence bounds applied to Trees) has problems when:
- **Action space > 1000**: UCT requires visiting each action at least once before meaningful statistics accumulate. With 10,000 possible actions and a budget of 1,000 simulations, most actions never get explored.
- **Combinatorial action ordering**: In Hearthstone, playing cards in different orders creates different states. With N cards in hand and M minions, the action space per turn is O(N! × M! × 2^M × ...).
- **Variable-length action sequences**: A single "turn" in Hearthstone is a sequence of actions (play card, play card, attack, play card, end turn). The action tree grows exponentially with turn depth.

**Concrete Hearthstone Example:**
- 7 cards in hand, 3 minions on board, hero power available
- Possible actions per step: 7 (play card) + 3 (attack with minion) + 1 (hero power) + 1 (end turn) = 12
- But after each action, new actions become available
- A single turn could be: play → play → attack → attack → attack → hero power → end turn
- The full tree for one turn can easily have **millions** of leaf nodes

### 2.2 Progressive Widening

**Single Progressive Widening (SPW):**
- At each node, only consider a subset of actions initially
- As the node is visited more, gradually add more actions
- The number of actions considered grows as: `k × N^α` where N = visit count, α ∈ (0, 1], k is a constant
- **Typical values**: α = 0.5 (sqrt of visits), k = 1

```
Visits: 1  → consider top 1 action
Visits: 4  → consider top 2 actions  
Visits: 9  → consider top 3 actions
Visits: 100 → consider top 10 actions
```

**Double Progressive Widening (DPW):**
- Applies progressive widening to **both** actions AND state transitions
- Essential for stochastic games where each action can lead to many possible outcomes
- For Hearthstone: Widens actions (which card to play) AND outcomes (which card is drawn next, RNG effects like Yogg-Saron)

**Implementation details from the JuliaPOMDP MCTS.jl library:**
```julia
# DPW parameters
k_action = 10.0      # action widening factor
alpha_action = 0.5   # action widening exponent  
k_state = 10.0       # state widening factor
alpha_state = 0.5    # state widening exponent

# Number of actions to consider at node with N visits:
n_actions = floor(k_action * N^alpha_action)
# Number of state transitions to consider:
n_states = floor(k_state * N^alpha_state)
```

### 2.3 Action Elimination / Prior Knowledge Pruning

**Heuristic Pruning:**
- Remove obviously bad actions before MCTS begins
- Examples: Don't consider attacking a 1/1 into an 8/8 (unless there's a strategic reason)
- Remove actions that are strictly dominated (e.g., playing a worse card when a better one achieves the same effect)

**Neural Network Prior Pruning (AlphaZero-style):**
- A policy network outputs a probability distribution over actions
- Only consider actions with probability above a threshold
- Or: limit to top-K actions by policy probability
- AlphaZero typically considers **all** legal moves but heavily weights exploration toward NN-recommended moves

**Action Abstraction:**
- Group similar actions together (e.g., "play any damage spell on enemy hero" vs individual spells)
- Search over abstract actions, then refine
- Particularly useful when many actions are near-equivalent

**Hierarchical Action Decomposition:**
```
Turn Action
├── Phase 1: Play Cards
│   ├── Which card? (C choose k)
│   └── Which target? (if targeted)
├── Phase 2: Attacks  
│   ├── Which minion attacks?
│   └── Which target?
├── Phase 3: Hero Power
│   └── Target (if applicable)
└── End Turn
```

### 2.4 How AlphaZero Handles Large Action Spaces

AlphaZero doesn't fundamentally solve large action spaces — it **avoids** them:

1. **Chess/Shogi/Go have moderate action spaces**: ~35-200 legal moves per position. UCT can handle this.
2. **Policy network as strong prior**: The NN outputs a probability for each action. UCB exploration uses this as a prior, so the search focuses on promising moves.
3. **Dirichlet noise for exploration**: Added only at the root node to ensure diversity.
4. **Temperature parameter**: Controls exploration vs exploitation in action selection.

**For Hearthstone-scale action spaces, AlphaZero alone is insufficient.** You need:

1. **Action space reduction** (progressive widening, top-K selection)
2. **Hierarchical decomposition** (phase-based search)
3. **Strong priors** (from either neural networks or handcrafted heuristics)
4. **Move ordering** (explore promising actions first to get better statistics faster)

**Practical recommendation for card games:**

| Technique | When to Use | Complexity |
|-----------|------------|------------|
| Full UCT | <100 actions | O(N × A × D) |
| Progressive Widening | 100-10,000 actions | O(N × A^α × D) |
| Top-K + UCT | >10,000 actions | O(N × K × D) |
| Hierarchical MCTS | Variable-length sequences | O(Σ phases N_i × K_i × D_i) |

---

## 3. Determinization in Imperfect Information Games

### 3.1 Perfect Information Monte Carlo (PIMC) Sampling

**PIMC Algorithm** (Levy, 1989; popularized by GIB for Bridge):

```
function PIMC(information_set I, budget N):
    for each action a in legal_actions(I):
        score[a] = 0
    
    for i = 1 to N:
        w = sample_world_from(I)    # Determinize: fill in hidden info
        for each action a in legal_actions(w):
            w' = w.apply(a)
            score[a] += perfect_info_value(w')  # Solve with full info
    
    return argmax(score)
```

**How it works:**
1. Take your current information set (what you know)
2. Sample a complete world state (guess opponent's hand, deck order, secrets)
3. Solve the resulting **perfect information** game (much easier!)
4. Repeat many times, average results
5. Choose the action with highest average value

**Strengths:**
- Simple to implement
- Can reuse strong perfect-information solvers
- **State-of-the-art in Bridge and Skat** for decades
- Scales well with parallelism

**Weaknesses:**
- **Strategy Fusion**: Each determinization is solved independently, allowing different strategies per world. In reality, you must play the same strategy across indistinguishable worlds.
- **Non-locality**: Actions early in the game should account for information revealed later, but PIMC ignores this.
- **No theoretical guarantees**: PIMC can play arbitrarily badly in pathological games.

**Strategy Fusion Example:**
In Rock-Paper-Scissors (with hidden opponent choice):
- PIMC determinizes: "If opponent plays Rock, I play Paper. If opponent plays Scissors, I play Rock."
- But you can't see their choice! PIMC "cheats" by using different strategies per world.
- The actual optimal strategy is 1/3 each — PIMC will never find this.

**When PIMC works well** (Long et al., 2010):
- Games where information is **progressively revealed** (like trick-taking card games)
- The "information gap" shrinks as the game progresses
- In Bridge, after a few tricks, most cards are known — strategy fusion matters less
- **In Hearthstone**: Much of the hidden information is revealed over time (opponent's cards become known as they're played), so PIMC-style approaches can work, especially for short-term tactical decisions.

### 3.2 Information Set MCTS (ISMCTS)

**ISMCTS** (Cowling, Powley, Whitehouse, 2012):

Rather than determinizing and searching separate trees, ISMCTS builds **one tree over information sets**.

```
function ISMCTS(information_set I, budget N):
    root = Node(representing information set I)
    
    for i = 1 to N:
        w = sample_world_from(I)    # Determinize
        select(root, w)              # Tree policy, matching info sets
        expand(selected_node, w)     # Add children consistent with w
        result = simulate(w)         # Random playout from w
        backpropagate(result)        # Update statistics
    
    return best_child(root)
```

**Key difference from PIMC**: The tree is built over **information sets** (groups of indistinguishable states), not over individual states. This partially addresses strategy fusion.

**Single-Observer ISMCTS (SO-ISMCTS):**
- Builds one tree from the current player's perspective
- Nodes represent information sets
- Each determinization traverses the same tree, contributing to the same statistics
- Naturally handles games where different determinizations have different legal actions

**Multiple-Observer ISMCTS (MO-ISMCTS):**
- Builds separate trees for each player
- More theoretically correct but computationally expensive
- Needed when opponent modeling matters

**ISMCTS variants for Hearthstone:**
- **Determinized MCTS**: Each simulation uses a different opponent hand/deck sample, but results are aggregated in a single tree
- **Semi-Determinized MCTS (SDMCTS)** (Bard et al., 2018): Combines ISMCTS with opponent action prediction
  - Uses a trained model to predict opponent actions
  - Improves simulation quality by replacing random opponent play with predicted play
  - Significant improvement in practice

### 3.3 Extended PIMC (EPIMC) — State of the Art (2024)

**EPIMC** (Arjonilla, Saffidine, Cazenave, 2024) — the latest evolution:

**Key insight**: Postpone the perfect information resolution to depth d, reducing strategy fusion.

```
function EPIMC(depth d, information_set I, budget N):
    Create subgame U
    for i = 1 to N:
        w = sample_world_from(I)
        query(U, root, w, d)      # Build subgame to depth d
    
    return solve_subgame_without_strategy_fusion(U)

function query(U, node, world, d):
    if d == 0 or terminal(world):
        node.value += perfect_info_eval(world)
        return
    a = random_action(world)
    child = get_or_create_child(node, a)
    update_dynamics(U, child)
    query(U, child, world.apply(a), d-1)
```

**Results from the EPIMC paper:**
- Depth 1 = standard PIMC
- Depth 2-3 significantly outperforms PIMC in games with private observations
- In Dark Chess: 80%/65%/45% win rate at depths 3/2/1 (vs PIMC opponent)
- In games with mostly public observations, increasing depth has minimal effect
- **Theoretical guarantee**: Increasing depth never increases strategy fusion (Proposition 1); for finite games, there exists a depth that eliminates it entirely (Proposition 3)

### 3.4 Practical Determinization for Hearthstone

**Recommended approach — Hybrid Determinized MCTS:**

```
1. Sample K opponent hands from belief distribution
2. For each sample:
   a. Run MCTS with full game state
   b. Use neural network / heuristics for evaluation
   c. Use opponent action model for opponent turns
3. Aggregate results across samples
4. Choose action with highest average value
```

**Number of samples**: 
- Real-time play: 10-100 samples, shallow search per sample
- Offline analysis: 1000+ samples, deeper search per sample

**Hearthstone-specific considerations:**
- Opponent's deck is often **known** (tournament play, deck tracker) — reduces hidden information
- Secrets are a small, enumerable set — can be partially determinized
- Draw order is the main source of randomness — handle via multiple samples
- Discover effects create new hidden information mid-game — expand the determinization

---

## 4. State Machines vs Behavior Trees vs GOAP for Game AI

### 4.1 Finite State Machines (FSMs)

**Structure**: Set of states with transitions triggered by conditions/events.

```
┌──────────┐   "enemy low"   ┌──────────────┐
│  IDLE    │ ──────────────→ │  AGGRESSIVE  │
└──────────┘                  └──────────────┘
     ↑                              │
     │ "no threats"          "own HP low"
     │                              ↓
┌──────────┐              ┌──────────────┐
│ DEFENSIVE│ ←──────────── │  RETREAT     │
└──────────┘  "safe"       └──────────────┘
```

**Pros:**
- Simple to understand and implement
- Fast execution (O(1) state lookup)
- Predictable behavior
- Easy to debug

**Cons:**
- **State explosion**: Adding states requires updating all transitions
- **Transition creep**: For N states with reactivity, need O(N²) transitions
- **Not modular**: Adding a new behavior may require changes to every state
- **Hard to scale**: Complex agents become unmaintainable

**When FSMs are the right choice** (from Iovino et al., 2024):
- Simple agents with few states (<10)
- Linear/sequential behavior patterns
- When transitions are simple and predictable
- Performance-critical code where overhead matters
- Prototyping and rapid iteration

### 4.2 Behavior Trees (BTs)

**Structure**: Hierarchical tree with control flow nodes (Sequence, Fallback/Selector, Parallel) and execution nodes (Action, Condition).

```
         [Sequence]
        /          \
  [Fallback]    [Attack Enemy]
   /       \
[HP Low?]  [Patrol]
   |
[Retreat]
```

**Node types:**
- **Sequence (→)**: Execute children left-to-right; succeed if ALL succeed
- **Fallback/Selector (→)**: Execute children left-to-right; succeed if ANY succeeds  
- **Parallel (⇉)**: Execute children simultaneously; succeed based on policy
- **Action**: Perform an action, return Running/Success/Failure
- **Condition**: Check a condition, return Success/Failure

**Pros** (from rigorous comparison by Iovino et al., 2024):
- **Modular**: Adding/removing subtrees is O(1) — doesn't affect other parts
- **Reactive**: Tree is re-evaluated every tick; running actions can be preempted
- **Readable**: Visual structure maps naturally to behavior logic
- **Scalable**: Complexity scales linearly with number of behaviors (vs quadratically for FSMs)

**Quantitative comparison** (Iovino et al., Table I):

| Metric | BT | FSM | HFSM |
|--------|----|-----|------|
| Add/remove modularity | O(1) | O(n) | O(k) |
| Edit distance (add behavior) | 2n* | 4+n | 4n*+8 |
| Graphical elements | ~7M-1 | ~5M+4+Tfc | ~36M-3 |
| Active elements per tick | ~3.5M | ~5M+4+Tfc | ~29M-3 |

Where M = number of action nodes, Tfc = fully-connected transitions

**Cons:**
- More complex implementation
- Slight overhead per tick (full tree traversal)
- Less expressive than FSMs for state-dependent memory
- "Blackboard" pattern needed for inter-node communication (which can break modularity)

**When BTs are the right choice:**
- Complex agents with many behaviors (>5)
- When behaviors need to be added/removed frequently
- When reactivity is important (preempt current action for higher priority)
- When multiple team members work on the same AI
- When debugging/visualization matters

### 4.3 GOAP (Goal-Oriented Action Planning)

**Structure**: Define a world state, a goal state, and a set of actions with preconditions and effects. Use a planner (usually A*) to find a sequence of actions from current state to goal.

```
Actions:
  - PlayCard(card):   requires {mana ≥ cost, card_in_hand}, effects {mana -= cost, card_on_board}
  - Attack(minion, target): requires {minion_on_board, target_valid}, effects {target_damaged}
  
Goal: {enemy_hero_dead}
Current: {enemy_HP: 30, mana: 10, hand: [Fireball(4), ...]}
  
Plan: PlayCard(Fireball) → Attack(minion1, face) → ...
```

**Pros:**
- **Emergent behavior**: No scripted sequences — plans emerge from goals
- **Flexible**: Same planner handles novel situations
- **No explicit state transitions**: The planner discovers them

**Cons:**
- **Expensive**: A* planning at runtime is costly
- **Unpredictable**: Hard to guarantee specific behaviors
- **Hard to tune**: Debugging "why did it choose that plan?" is difficult
- **Not real-time friendly**: Planning can take variable time

### 4.4 Applicability to Hearthstone AI

**Recommendation: Hybrid approach**

For a Hearthstone AI bot, different components benefit from different architectures:

| Component | Recommended Architecture | Why |
|-----------|------------------------|-----|
| High-level strategy | **Behavior Tree** | Reactive, modular, handles "if lethal → kill; else if threatened → defend; else → develop board" |
| Tactical decisions | **MCTS/Search** | Too complex for scripted approaches |
| Lethal check | **Special-purpose algorithm** | Must be exhaustive, not heuristic |
| Mulligan | **Simple rules/FSM** | Small decision space, well-understood heuristics |
| Target selection | **Utility system** | Score each target, pick highest |
| Opponent modeling | **Separate module** | Bayesian inference, not decision architecture |

**Example Behavior Tree for Hearthstone:**

```
[Root: Sequence]
├── [Fallback: Check Lethal]
│   ├── [Condition: Lethal exists?]
│   └── [Action: Execute lethal sequence]
├── [Fallback: Emergency Defense]
│   ├── [Condition: Will die next turn?]
│   └── [Action: Find defensive play]
├── [Action: Run MCTS for best play]
└── [Action: Execute chosen actions]
```

**GOAP for Hearthstone?**
- Not recommended as the primary decision-making architecture
- The action space is too large and the planning horizon too short
- MCTS dominates GOAP for this type of problem
- GOAP could be useful for **deck-building** (planning a sequence of card selections toward a strategic goal)

---

## 5. Ensuring Decision Correctness

### 5.1 The Lethal Check Problem

**Definition**: Given the current game state, determine whether there exists a sequence of actions that reduces the opponent's hero to 0 HP this turn.

**Why this matters:**
- Missing lethal is the single most impactful mistake a card game AI can make
- A greedy/heuristic approach might miss lethal because the optimal play is non-obvious
- Hearthstone lethal puzzles routinely require unintuitive sequences (e.g., attacking your own minion to trigger an effect)

**Why it's hard:**
- Action sequences can be long (10+ actions in a turn)
- Order matters (play card before attacking, etc.)
- Position matters (minion placement, targeting)
- Interactions between cards create emergent effects
- Board state changes after each action, enabling new possibilities

### 5.2 Exhaustive Enumeration

**Approach**: Try every possible sequence of actions and check if any reduces opponent HP to 0.

```
function find_lethal(state):
    if opponent_hp(state) <= 0:
        return []  # Already dead
    
    for each action a in legal_actions(state):
        state' = state.apply(a)
        result = find_lethal(state')
        if result is not None:
            return [a] + result
    
    return None  # No lethal found
```

**Complexity**: O(A^D) where A = actions per step, D = max turn depth

**For a typical mid-game state:**
- 7 cards in hand, 5 minions, hero power
- ~15 actions per decision point
- Turn depth ~8 (play 3 cards, attack 5 times)
- Total: 15^8 ≈ 2.56 billion states

**This is too slow for real-time play but feasible for offline analysis.**

### 5.3 Pruning for Lethal Checks

**Pruning strategies to make exhaustive search feasible:**

1. **Maximum Damage Pruning**: 
   - Calculate maximum possible damage from current state
   - If max_damage < opponent HP, no lethal exists → prune entire subtree
   - Update max_damage estimate as actions are applied
   - **This is the most effective pruning strategy**

2. **Mana Pruning**:
   - If remaining mana + temporary mana < cost of any remaining damage source → prune
   - Track mana spent, prune branches that can't afford remaining cards

3. **Action Ordering**:
   - Try damage-dealing actions first
   - Try high-damage actions before low-damage
   - Try cards that enable other cards (e.g., cost-reduction effects) early

4. **Symmetry Pruning**:
   - Attacking minion A then minion B is same as B then A (if order doesn't matter)
   - Playing two non-interacting cards in either order gives the same result

5. **Early Termination**:
   - As soon as lethal is found, return immediately
   - Don't need the OPTIMAL lethal, just ANY lethal

6. **Incremental Damage Tracking**:
   - Rather than recomputing from scratch, incrementally update opponent HP
   - Track "damage so far" + "remaining potential damage"

**Optimized lethal check algorithm:**

```
function has_lethal(state, max_dmg_remaining):
    if opponent_hp(state) <= 0:
        return true
    
    if opponent_hp(state) > max_dmg_remaining:
        return false  # Can't possibly do enough damage
    
    # Calculate max possible damage from current state
    dmg_potential = calc_max_damage(state)
    if dmg_potential < opponent_hp(state):
        return false
    
    # Order actions: damage first, then enablers, then other
    actions = sort_by_damage_potential(legal_actions(state))
    
    for a in actions:
        state' = state.apply(a)
        new_max = max_dmg_remaining - action_cost(a) + action_gain(a)
        if has_lethal(state', new_max):
            return true
    
    return false
```

### 5.4 Recursive Action Sequence Validation

For non-lethal scenarios, validating that a sequence of actions is legal:

```
function validate_action_sequence(state, actions):
    current = copy(state)
    for a in actions:
        if not is_legal(current, a):
            return false, "Action {a} illegal in state {current}"
        current = apply(current, a)
    return true, current
```

**Key validations:**
- Mana cost check (including cost modifications)
- Target validity (minion vs hero, friendly vs enemy)
- Attack availability (summoning sickness, already attacked)
- Card availability (in hand, not already played)
- Phase correctness (can't attack during card play phase in some implementations)
- Effect resolution order (death processing, trigger order)

### 5.5 "Greedy is Good Enough" vs "Need Optimal Play"

**Spectrum of decision quality:**

| Level | Approach | Speed | Quality | When to Use |
|-------|----------|-------|---------|-------------|
| 1 | Random | Instant | Terrible | Baseline only |
| 2 | Greedy/heuristic | Fast | Decent | Early game, simple boards |
| 3 | Shallow search (depth 2-3) | Fast | Good | Most situations |
| 4 | Deep search (MCTS, 1000+ sims) | Moderate | Very good | Critical turns |
| 5 | Exhaustive lethal check | Slow | Perfect (for lethal) | When lethal might exist |
| 6 | Full POMDP optimal | Intractable | Optimal | Never (intractable) |

**Practical recommendation — Tiered approach:**

```
1. ALWAYS check for lethal first (exhaustive with pruning)
2. If lethal exists → execute it
3. If no lethal → run MCTS with time budget
4. If time budget < threshold → fall back to heuristic
5. For mulligan → use handcrafted rules + opponent model
```

**The lethal check must be exhaustive.** Missing lethal is catastrophic. Other decisions can be approximate.

---

## 6. Recent Advances (2023-2025)

### 6.1 LLM-Based Game AI

**"Language-Driven Play"** (Bateni & Whitehead, FDG 2024):
- Tested GPT-3.5 and GPT-4 as game-playing agents for Slay the Spire (similar to Hearthstone)
- **Key findings**:
  - LLMs with chain-of-thought prompting perform surprisingly well
  - LLMs excel at **long-term planning** (understanding delayed effects)
  - LLMs struggle with **short-term optimization** (exact damage calculations)
  - GPT-3.5 outperformed GPT-4 in speed (and sometimes quality) for this task
  - Anonymizing card names improved performance (prevents reliance on training data)
  - LLM agents are **not competitive with search-based agents** for tactical play

**"Integrating LLMs with RL for Hearthstone"** (AAMAS 2025):
- Combines LLM reasoning with reinforcement learning
- LLM provides high-level strategic guidance
- RL handles tactical execution
- Addresses the challenge of continuously expanding card pools

**"Suspicion-Agent"** (COLM 2024):
- GPT-4 playing imperfect information games with Theory of Mind
- Shows LLMs can reason about hidden information
- But performance is far below specialized AI

**LLM Bottom Line for Hearthstone AI:**
- LLMs are useful for **game understanding** and **natural language interfaces**
- LLMs are NOT competitive with MCTS/search for actual gameplay
- LLMs can serve as **priors** or **opponent models** for search algorithms
- Best use: LLM as a component, not the main decision engine

### 6.2 Neural Network Guided Search for Card Games

**AlphaZero-like baselines for imperfect information games** (Frontiers in AI, 2023):
- "AlphaZero*" paper: applies AlphaZero framework to games with hidden information
- **Key challenge**: Standard AlphaZero assumes perfect information
- **Solutions explored**:
  - Determinized AlphaZero: train on determinized states
  - Belief-state AlphaZero: augment input with belief distribution
  - Information set AlphaZero: tree search over information sets

**DouZero / Deep Monte-Carlo (DMC)** for DouDiZhu (Chinese card game):
- State-of-the-art AI for a 3-player imperfect information card game
- Uses deep Monte-Carlo method (model-free, value-based RL)
- Trained via self-play with distributed training
- **Improved DMC (2024)**: Better learning efficiency for complex card games
  - Uses action masking for large action spaces
  - Card embedding networks for generalization across cards

**Look-ahead Search on Top of Policy Networks** (IJCAI 2024):
- Performs search at test time on top of trained RL policies
- Addresses the gap between policy network output and optimal play
- **Key insight**: Even in imperfect information games, search at test time significantly improves policy quality
- Uses determinized search with neural network evaluation

**Efficiently Training Neural Networks for Imperfect Information Games** (ECAI 2024):
- Problem: Accessing hidden information trivially reveals it, creating a "cheating" oracle
- Solution: Train with careful information masking
- Uses public belief state representations
- Demonstrates that proper training regimes can close the gap between perfect-info and imperfect-info oracles

### 6.3 Breakthrough Papers (2023-2025)

**Most significant recent advances:**

1. **EPIMC (Extended PIMC)** — Arjonilla et al., 2024
   - Extends PIMC with deferred perfect information resolution
   - Provable strategy fusion reduction with increasing depth
   - State-of-the-art for online play in imperfect information games

2. **CDIT + ESCFR** — Becker & Sunberg, 2024
   - Bridges POMDP and extensive-form game approaches
   - First algorithm to combine particle filtering with Nash equilibrium finding
   - No state-space size dependence in complexity

3. **Look-ahead Search on Policy Networks** — IJCAI 2024
   - Shows that test-time search improves imperfect info game play
   - Practical recipe for combining trained networks with search

4. **AAMAS 2024 Imperfect-Information Card Games Competition**
   - Established benchmark for card game AI
   - Includes multiple game variants with different hidden information structures

5. **Neural Fictitious Self-Play (NFSP) improvements**
   - Better convergence for multi-player imperfect information games
   - Applied to various card game domains

### 6.4 Architecture Recommendations Based on Recent Research

**For a Hearthstone AI in 2025, the recommended architecture is:**

```
┌──────────────────────────────────────────────────┐
│                   Game State Layer                │
│  Full state tracker, action validator, simulator  │
├──────────────────────────────────────────────────┤
│                  Belief State Layer               │
│  - Opponent hand/deck probability distribution    │
│  - Secret tracking (enumerate possibilities)      │
│  - Opponent action model (predict opponent plays) │
├──────────────────────────────────────────────────┤
│                 Decision Engine                   │
│  ┌─────────────────────────────────────────────┐ │
│  │ Tier 1: Exhaustive Lethal Check              │ │
│  │ (pruned BFS/DFS over action sequences)       │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ Tier 2: Determinized MCTS                    │ │
│  │ - Sample K worlds from belief                │ │
│  │ - MCTS per world with NN priors              │ │
│  │ - Progressive widening for large action space│ │
│  │ - Aggregate results across samples           │ │
│  └─────────────────────────────────────────────┘ │
│  ┌─────────────────────────────────────────────┐ │
│  │ Tier 3: Heuristic Fallback                   │ │
│  │ (board control, tempo, card advantage)        │ │
│  └─────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────┤
│                  Evaluation Layer                 │
│  - Neural network value function                 │
│  - Handcrafted features as fallback              │
│  - Opponent model for simulation                 │
└──────────────────────────────────────────────────┘
```

**Key design decisions:**

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Search algorithm | Determinized MCTS | Best balance of quality and speed for card games |
| Hidden info handling | PIMC-style sampling | Proven in Bridge/Skat/Hearthstone; simple and effective |
| Large action spaces | Progressive widening + top-K | Handles combinatorial explosion |
| Lethal check | Exhaustive with pruning | Must never miss lethal |
| Opponent model | Predictive NN + Bayesian | Improves simulation quality |
| Evaluation | Neural network + heuristics | NN for board state, heuristics for edge cases |
| Architecture pattern | Behavior tree for strategy, MCTS for tactics | Leverages strengths of each |

---

## References

### Core Algorithms
- Silver, D. & Veness, J. (2010). "Monte-Carlo Planning in Large POMDPs." *NeurIPS*.
- Cowling, P.I., Powley, E.J., & Whitehouse, D. (2012). "Information Set Monte Carlo Tree Search." *IEEE TCIAIG*.
- Browne, C. et al. (2012). "A Survey of Monte Carlo Tree Search Methods." *IEEE TCIAIG*.
- Long, J.R. et al. (2010). "Understanding the Success of Perfect Information Monte Carlo Sampling in Game Tree Search." *AAAI*.

### Recent Advances (2023-2025)
- Arjonilla, J., Saffidine, A., & Cazenave, T. (2024). "Perfect Information Monte Carlo with Postponing Reasoning." *arXiv:2408.02380*.
- Becker, T. & Sunberg, Z. (2024). "Bridging the Gap between POSGs and Sparse POMDP Methods." *arXiv:2405.18703*.
- Iovino, M. et al. (2024). "Comparison between Behavior Trees and Finite State Machines." *arXiv:2405.16137*.
- Bateni, B. & Whitehead, J. (2024). "Language-Driven Play: LLMs as Game-Playing Agents in Slay the Spire." *FDG 2024*.
- "Look-ahead Search on Top of Policy Networks in Imperfect Information Games." *IJCAI 2024*.
- "Efficiently Training Neural Networks for Imperfect Information Games." *ECAI 2024*.
- "Improved Learning Efficiency of Deep Monte-Carlo for Complex Imperfect Information Card Games." *Applied Soft Computing, 2024*.
- "Integrating Large Language Models with Reinforcement Learning for Hearthstone Agents." *AAMAS 2025*.

### Foundational Works
- Furtak, T. & Buro, M. (2013). "Recursive Monte Carlo Search for Imperfect Information Games." *IEEE CIG*.
- Frank, I. & Basin, D. (1998). "Search in Games with Incomplete Information: A Case Study Using Bridge Card Play." *AIJ*.
- Santos, C.A. et al. (2017). "Improving Hearthstone AI by Combining MCTS and Supervised Learning."
- Bard, N. et al. (2018). "Combining Prediction of Human Decisions with ISMCTS in Imperfect Information Games." *AAMAS*.

### Hearthstone AI Specific
- peter1591/hearthstone-ai: AlphaGo-inspired Hearthstone AI with MCTS + neural nets (C++)
- Hearthstone AI competitions (2017-2023): Multiple papers on MCTS, evolutionary algorithms, and supervised learning approaches
- Symbolic Reasoning for Hearthstone (Glasgow School of Art): Rule-based vs MCTS comparison

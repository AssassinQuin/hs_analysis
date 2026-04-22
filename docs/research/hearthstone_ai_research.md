# Hearthstone AI & Card Game AI: Comprehensive Research Summary

## 1. Top Hearthstone AI Bots and Their Algorithms

### 1.1 SilverFish (Open Source, Most Influential)
- **GitHub**: https://github.com/ChuckHearthstone/SilverFish, https://github.com/noHero123/silverfish
- **Algorithm**: **Exhaustive greedy search with board state scoring**
  - Enumerates ALL possible actions in the current turn
  - Scores each resulting board state using a weighted evaluation function
  - Sorts the top 100 best boards and simulates the best one
  - Uses deterministic evaluation: no tree search, no randomness
- **Key approach**: 
  - Simulates every possible action sequence within the turn
  - Uses a hand-tuned scoring function evaluating board control, health, mana efficiency
  - Includes lethal detection (checks if any action sequence kills the opponent)
  - Configurable per-deck settings (different config files for different deck archetypes)
- **Integration**: Plugs into HearthRanger and HearthBuddy as a "Custom Class" via Open API SDK
- **Performance**: Considered the strongest open-source HS AI for many years

### 1.2 peter1591's Hearthstone AI (AlphaGo-inspired)
- **GitHub**: https://github.com/peter1591/hearthstone-ai
- **Algorithm**: **Monte Carlo Tree Search (MCTS) + Neural Networks**
  - Inspired by AlphaGo architecture
  - Uses **MOMCTS** (Multiple Observer MCTS) for two-player hidden information
  - Two SOMCTS (Single Observer MCTS) instances, one per player
  - Neural network for state value estimation during simulation phase
  - Handles randomness via "redirect nodes" in the search tree (BoardNodeMap)
- **Architecture details**:
  - Selection phase: UCB or neural network-guided action selection
  - Simulation phase: Multiple policies available:
    - RandomPlayouts (baseline)
    - RandomCutoff (random + early termination)
    - RandomPlayoutWithHeuristicEarlyCutoffPolicy (random + NN cutoff)
    - HeuristicPlayoutWithHeuristicEarlyCutoffPolicy (heuristic + NN cutoff)
  - NN input features: mana, hero HP/armor, minion stats, hand info, card costs
  - Written in modern C++ with high-performance game engine
- **Key innovation**: Extends MCTS for imperfect information games using multiple observers

### 1.3 HearthRanger (Commercial Bot)
- **Website**: hearthranger.com
- **Algorithm**: Default AI is rule-based/heuristic; supports external AI plugins
- **Open API SDK**: Allows plugging in SilverFish or custom AI modules
- **Default AI approach**: 
  - Priority-based action selection
  - Greedy board evaluation

### 1.4 Smartbot (Commercial)
- **Website**: smartbot.ws
- **Algorithm**: Proprietary, marketed as "best AI on the market"
- **Little public information** on internal algorithm

### 1.5 Hearthbuddy (The Noob Bot / HB)
- **Algorithm**: Similar to HearthRanger - supports external AI via plugin system
- **Integration**: SilverFish works as a Custom Class plugin

---

## 2. Academic Papers on Hearthstone AI

### 2.1 MCTS Applied to Hearthstone

#### Paper 1: "Monte Carlo Tree Search Experiments in Hearthstone" (CIG 2017)
- **Authors**: André Miguel Leitão Santos
- **Link**: IEEE Xplore (10.1109/CIG.2017.8080446)
- **Key findings**:
  - First systematic application of MCTS to Hearthstone
  - Addresses challenges: uncertainty, randomness, large action space
  - Proposes determinization for handling hidden information
  - MCTS outperforms greedy/heuristic approaches significantly

#### Paper 2: "Improving Hearthstone AI by Combining MCTS and Supervised Learning Algorithms" (CIG 2018)
- **Authors**: Maciej Świechowski, Tomasz Tajmajer, Andrzej Janusz
- **arXiv**: 1808.04794
- **Key findings**:
  - Combines MCTS with supervised neural networks
  - Even simple NNs trained on game state data improve MCTS performance
  - NN used for leaf evaluation in simulation phase
  - Demonstrated: guidance to search heuristic → better win rate + fewer computations
  - Used in the Silverfish AI system

#### Paper 3: "Enhancing Monte Carlo Tree Search for Playing Hearthstone" (IEEE CoG 2020)
- **Link**: ieee-cog.org/2020/papers2019/paper_257.pdf
- **Key findings**:
  - Explores MCTS with approaches to handle the extremely large branching factor
  - Hearthstone's branching factor is "extremely large" compared to other games
  - Proposes pruning and simulation improvements

#### Paper 4: "GP-MCTS for HearthStone" (SSCI 2020)
- **Authors**: Tsung-Che Chiang
- **Key findings**:
  - Integrates rule-based agent into MCTS framework
  - Genetic Programming generates rollout policies for MCTS
  - Compared against three particular baseline agents

#### Paper 5: "Hearthstone Battleground: An AI Assistant with Monte Carlo Tree Search"
- **Link**: easychair.org/publications/paper/Kftf/open
- **Key findings**:
  - Applies "Information Set" MCTS (ISMCTS) to Hearthstone Battlegrounds
  - Uses information sets (subsets of game tree with all possible hidden state outcomes)
  - Adapts to randomness in minion selection

#### Paper 6: "Programming a Hearthstone agent using Monte Carlo Tree Search" (NTNU Master's Thesis)
- **Link**: ntnuopen.ntnu.no/ntnu-xmlui/handle/11250/2420367
- **Key findings**: Detailed thesis on adapting MCTS to hidden information + stochastic elements

### 2.2 POMDP and Imperfect Information Approaches

#### Information Set MCTS (ISMCTS) - The Key Technique
- **Paper**: "Information Set Monte Carlo Tree Search" (IEEE 2012)
- **Link**: ieeexplore.ieee.org/document/6203567
- **Three ISMCTS variants**:
  1. **SO-ISMCTS** (Single Observer): Searches from one player's perspective
  2. **MO-ISMCTS** (Multiple Observer): Maintains separate trees for each player
  3. **OO-ISMCTS** (Opponent Observer): Considers opponent's hidden information
- **Core idea**: Instead of searching minimax trees of determinized games independently, ISMCTS builds a single search tree that represents ALL possible states consistent with observed information
- **Application**: Used in Pokémon TCG, Hanabi, Secret Hitler, and card games generally

#### POMDP Approaches
- **Paper**: "Bridging the Gap between POSGs and POMDPs" (AAMAS 2025)
  - Integrates imperfect information game methods with POMDP-based distribution approximations
  - Enables low-exploitability solutions
- **Counterfactual Regret Minimization (CFR)**: The dominant approach for imperfect-information games
  - Iteratively learns from past decision regrets
  - Used in poker AI (Libratus, ReBeL)
- **Deep Monte-Carlo (DMC)** for imperfect-information card games
  - Opponent Model predicts hidden information
  - Improves training efficiency

#### Survey: "Artificial Intelligence for Imperfect-Information Card Games"
- **Link**: techrxiv.org/doi/10.36227/techrxiv.177281409.97588134
- Comprehensive survey covering all major approaches

### 2.3 Evolutionary Algorithms for Hearthstone AI

#### Paper 7: "Optimizing Hearthstone Agents using an Evolutionary Algorithm" (Knowledge-Based Systems)
- **Authors**: P. García-Sánchez, Alberto Tonda, Antonio J. Fernández-Leiva, Carlos Cotta
- **arXiv**: 2410.19681
- **Key findings**:
  - Uses **Evolutionary Strategy (ES)** with (μ+λ) selection
  - Optimizes 21 weighted parameters of a scoring function
  - **Competitive coevolution**: agents play against each other during evolution (no external opponent needed)
  - **Result**: Runner-up (2nd out of 33) in CIG 2018 Hearthstone AI Competition
  - **Beats MCTS-based agents** despite being a simpler approach!
  - Agent evaluates each possible action's impact on game state using weighted scoring:
    - Hero health/attack changes
    - Minion health/attack/appeared/killed
    - Secret removed/appeared
    - Mana consumed
    - Minion abilities (Charge, Deathrattle, Divine Shield, Taunt, Windfury, Poison, etc.)
  - Key insight: **EA-optimized simple scoring can rival complex tree search**

#### Paper 8: "Decision-Making in Hearthstone Based on Evolutionary Algorithm" (ICAART 2023)
- **Authors**: Eiji Sakurai, Koji Hasebe (University of Tsukuba)
- **Key findings**:
  - Proposes EA for real-time turn decision-making
  - Addresses the problem that game tree search is too slow for full turn optimization
  - Uses evolutionary approach to find good action sequences within time constraints

#### Paper 9: "Evolutionary Algorithms for Strategic Card Games" (2019)
- **Authors**: Jakub Kowalski
- **Key findings**:
  - Analyzes CCG-specific challenges: imperfect information, randomness, long-term planning, large action space
  - Proposes EA-based approaches for deck building and play strategy

### 2.4 AlphaZero-Style Approaches for Card Games

#### Paper 10: "Applying AlphaZero to Develop AI in Turn-Based Card Games" (GDC 2021)
- **Link**: GDC Vault (media.gdcvault.com)
- **Key findings**:
  - Direct application of AlphaZero to turn-based card games
  - Challenges: model must be updated when cards change
  - Enables AI to predict player's hand and deck
  - Needs automation for card updates

#### Paper 11: "AlphaZero** : AlphaZero-like baselines for imperfect information games" (Frontiers in AI 2023)
- **Link**: frontiersin.org/articles/10.3389/frai.2023.1014561
- **Key findings**:
  - Novel algorithm based solely on reinforcement learning
  - AlphaZero-based framework adapted for imperfect information
  - Shows that naive AlphaZero fails in IIGs; modifications needed

#### Paper 12: "ReBeL: Combining Deep RL and Search for Imperfect Information Games" (NeurIPS 2020)
- **Authors**: Brown et al. (Facebook AI/Noam Brown)
- **Link**: arxiv.org/abs/2007.13544
- **Key findings**:
  - **Public Belief State (PBS)**: The key innovation for IIG search
  - Provably converges to Nash equilibrium in two-player zero-sum games
  - Superhuman in no-limit Texas Hold'em poker
  - Uses far less domain knowledge than prior poker bots
  - **Reduces to AlphaZero in perfect-information games** → unified framework
  - **The state of the art for combining search + learning in IIGs**

#### Paper 13: "Student of Games" (Science 2023)
- **Link**: science.org/doi/10.1126/sciadv.adg3256
- **Key findings**:
  - Unified learning algorithm for both perfect and imperfect information games
  - Combines self-play, search, and policy/value networks

---

## 3. State of the Art for Turn-Based Card Game AI

### 3.1 How They Handle Enormous Action Space

#### The Core Problem
Hearthstone's action space per turn is combinatorially explosive:
- Multiple minions can attack (each can target multiple enemies)
- Multiple cards can be played (in various orders)
- Hero power, weapon attacks
- Order matters: playing a card before attacking changes the board state
- With 7 minions on board + cards in hand + hero power: **thousands to millions of possible turn sequences**

#### Approaches Used:

**1. Full Enumeration (SilverFish approach)**
- Enumerate ALL possible action sequences within the turn
- Score each resulting board state
- Pick the best scoring sequence
- Works because within a single turn, the state space is bounded
- Practical limit: ~100-1000 boards evaluated per turn
- Uses pruning: skips obviously bad sequences

**2. MCTS with Action Pruning (Academic approach)**
- **Paper**: "Pruning Stochastic Game Trees Using Neural Networks" (MDPI Mathematics 2022)
  - Two pruning MCTS variants based on action reward distributions
  - Neural network learns which actions to prune
  - **GitHub**: https://github.com/ails-lab/hearthstone_ai
  - Agents: MCTSxgb (XGBoost for pruning), MCTSnet, MCTSxgbPruningNets
- **Key technique**: Train a classifier to predict which actions are worth exploring
- Reduces branching factor from O(thousands) to O(tens)

**3. Greedy Sequential Action Selection (EA-optimized)**
- Evaluate each SINGLE action (not full sequences)
- Pick the best action, execute it, re-evaluate
- Repeat until "end turn" is the best option
- Much simpler than full tree search
- EA-optimized weights make this surprisingly competitive

**4. Simulation Budget Control**
- Time-limited MCTS: run as many iterations as possible within time budget
- Progressive widening: initially explore few actions, gradually expand
- UCB1 for balancing exploration vs exploitation

### 3.2 Handling Hidden Information

#### Approaches (Ranked by Sophistication):

**1. Determinization (Simplest)**
- Assume you know the opponent's hand and deck
- Sample random consistent states
- Search each determinized state
- Average results
- Problem: "Strategy fusion" - can play differently knowing hidden cards

**2. Information Set MCTS (ISMCTS)**
- Build a single tree over ALL possible states consistent with observations
- Each node represents an "information set" (set of indistinguishable states)
- Three variants: SO-ISMCTS, MO-ISMCTS, OO-ISMCTS
- Avoids strategy fusion problem
- **Best practical approach for card games**

**3. Public Belief State (ReBeL/SOTA)**
- Model the probability distribution over opponent's private information
- Use counterfactual regret minimization to find approximate Nash equilibrium
- Most theoretically sound but computationally expensive
- Requires significant offline training

**4. Opponent Modeling via Prediction**
- **Bursztein's approach**: Statistics-based prediction of opponent's next cards
- High accuracy for early game, decreases as options expand
- Can be combined with any search method

### 3.3 Ensuring Decision Correctness

#### The Challenge
- Must never miss lethal (winning play)
- Must never attempt illegal actions
- Must handle complex card interactions (Battlecries, Deathrattles, triggers)
- Must handle action order dependencies

#### Solutions:

**1. Simulator-Based Verification**
- Use a faithful game simulator (MetaStone, SabberStone, fireplace)
- Every action is simulated before being recommended
- Illegal actions are caught by the simulator
- Ensures correctness by construction

**2. Action Enumeration via Game State Queries**
- Ask the simulator: "What are all legal actions right now?"
- For each legal action, simulate it and get the new state
- Recurse for the next action in the sequence
- This guarantees no illegal actions

**3. Lethal Detection (SilverFish approach)**
- Before evaluating strategic options, check ALL action sequences for lethal
- If lethal exists, play it immediately (overrides all other considerations)
- Implemented as a fast path in the action enumeration

**4. Trigger Resolution**
- Deathrattles, secrets, and other triggers create complex state changes
- Must be resolved fully between each action
- Simulator handles this; custom implementations must be very careful

---

## 4. State Machines vs Other Approaches

### 4.1 Finite State Machines (FSMs)
- **Good for**: Simple behavior patterns, reactive AI
- **Used in**: Early game bots, companion AI
- **Problems for card games**:
  - State explosion: too many game states to enumerate
  - Hard to maintain: transitions become spaghetti
  - No look-ahead: purely reactive
  - Not suitable for strategic decision-making

### 4.2 Behavior Trees (BTs)
- **Good for**: Modular decision-making, easy to extend
- **Used in**: RTS games, RPG companion AI
- **Advantage over FSMs**: 
  - More modular and reusable
  - Easier to add new behaviors
  - Better at handling priority and fallback behaviors
- **Paper**: "Comparison between Behavior Trees and Finite State Machines" (arXiv 2405.16137)
  - BTs originated in game industry for AI behavior modeling
  - Mathematically proven to be at least as expressive as FSMs
  - Better for complex, hierarchical behaviors

### 4.3 Hierarchical FSMs (HFSMs)
- FSMs organized in layers to manage complexity
- Better than flat FSMs but still lack look-ahead

### 4.4 What Card Game AI Actually Uses
**None of the above directly.** Card game AI uses:
- **Tree Search** (MCTS, minimax) for look-ahead
- **Evaluation Functions** (weighted scoring, neural networks) for state assessment
- **Action Generators** for legal move enumeration
- **State Machines** only for high-level game flow (mulligan phase → play phase → end game), NOT for in-turn decisions

### 4.5 Hybrid Approach (Practical)
For a production Hearthstone AI, a **layered architecture** makes sense:
1. **Game Flow FSM**: Manages phases (mulligan, play, end)
2. **Decision Engine**: MCTS or greedy search for action selection
3. **Action Enumerator**: Generates all legal actions from current state
4. **State Evaluator**: NN or weighted function for board scoring
5. **Lethal Checker**: Fast exhaustive search for winning plays

---

## 5. Action Space Representation

### 5.1 How to Enumerate All Possible Actions Efficiently

#### Action Types in Hearthstone
1. **Play a card** from hand → may require target selection
2. **Attack with a minion** → requires attacker + target selection  
3. **Attack with weapon/hero** → requires target selection
4. **Use Hero Power** → may require target selection
5. **End Turn** (always available)

#### Efficient Enumeration Strategy

```
function enumerateActions(state):
    actions = [EndTurn]
    
    for card in hand:
        if canPlay(card, state.mana):
            targets = getValidTargets(card, state)
            if targets.isEmpty():
                actions.add(PlayCard(card))
            else:
                for target in targets:
                    actions.add(PlayCard(card, target))
    
    for minion in friendlyMinions:
        if canAttack(minion):
            targets = getValidAttackTargets(minion, state)
            for target in targets:
                actions.add(Attack(minion, target))
    
    if hasWeapon(hero) and canAttack(hero):
        targets = getValidAttackTargets(hero, state)
        for target in targets:
            actions.add(HeroAttack(target))
    
    if canUseHeroPower(state):
        targets = getHeroPowerTargets(state)
        if targets.isEmpty():
            actions.add(HeroPower())
        else:
            for target in targets:
                actions.add(HeroPower(target))
    
    return actions
```

#### Key Optimizations:

**1. Mana Pruning**
- Skip cards that cost more than current available mana
- After playing a card, recalculate available mana before next enumeration

**2. Symmetry Reduction**
- If two minions have identical stats and effects, attacking with either is equivalent
- Skip duplicate board states

**3. Taunt Filtering**
- If enemy has Taunt minions, only those are valid attack targets
- Dramatically reduces attack options

**4. Order Independence Detection**
- Some actions commute (e.g., attacking with two unrelated minions)
- Can avoid exploring both orderings

**5. Progressive Deepening**
- Start with "obvious" actions (lethal check, board clears)
- Only expand to complex sequences if needed

### 5.2 Turn-Level Action Sequence Enumeration

The full turn optimization requires considering SEQUENCES of actions:

```
function findBestTurn(state):
    bestScore = -infinity
    bestSequence = []
    
    function dfs(currentState, actionSequence):
        nonlocal bestScore, bestSequence
        
        score = evaluateState(currentState)
        if score > bestScore:
            bestScore = score
            bestSequence = copy(actionSequence)
        
        actions = enumerateActions(currentState)
        for action in actions:
            if action == EndTurn:
                continue  // already scored above
            newState = simulate(currentState, action)
            if newState is game over:
                if newState.weWon:
                    return actionSequence + [action]  // LETHAL!
            dfs(newState, actionSequence + [action])
    
    dfs(state, [])
    return bestSequence
```

#### Practical Bounds:
- Typical turn: 5-30 legal actions per decision point
- Average turn depth: 3-8 actions before end turn
- Total sequences: typically 100-10,000 (manageable with pruning)
- Worst case (full board + full hand): can reach millions → need time limits

### 5.3 Representing Actions as Objects/Commands

```python
class Action:
    type: Enum  # PLAY_CARD, ATTACK, HERO_POWER, END_TURN
    source: Entity  # card/minion/hero
    target: Optional[Entity]
    
class TurnPlan:
    actions: List[Action]
    estimatedScore: float
```

This allows:
- Easy serialization and logging
- Undo/redo for simulation
- Comparison of different plans
- Progressive refinement

---

## 6. Open Source Simulators (Critical Infrastructure)

| Simulator | Language | Link | Notes |
|-----------|----------|------|-------|
| **SabberStone** | C# | gitlab.com/x2v3/SabberStone | Fastest, used in EA paper |
| **MetaStone** | Java | github.com/demilich1/metastone | Full rules, used in competitions |
| **fireplace** | Python | github.com/jleclanche/fireplace | Python-based, good for ML |
| **HearthSim** | ? | hearthsim.info | Community project |
| **Hearthbreaker** | Python | danielyule.github.io/hearthbreaker | ML-focused |
| **peter1591's engine** | C++ | github.com/peter1591/hearthstone-ai | Purpose-built for MCTS |

---

## 7. Hearthstone AI Competition

- **Held at**: CIG (Computational Intelligence in Games) conference
- **Platform**: Uses MetaStone simulator
- **Evaluation**: Simulate all matchups for 100+ games, average win-rate
- **2018 Results**: 
  - 33 contestants
  - EA-optimized agent (Paper 7) finished 2nd (best 6%)
  - Beat MCTS-based agents despite simpler approach
- **Competition rules**: https://hearthstoneai.github.io/rules.html

---

## 8. Key Technical Insights for Building a Hearthstone AI

### 8.1 Architecture Recommendation
1. **Use a simulator** (SabberStone or custom) - never trust manual state tracking
2. **Layer 1: Fast lethal check** - exhaustive search for winning play
3. **Layer 2: MCTS or greedy search** - for strategic decision when no lethal
4. **Layer 3: Evaluation function** - weighted scoring or neural network
5. **Layer 4: Opponent modeling** - predict hidden information for better decisions

### 8.2 Performance Requirements
- Decision time budget: ~30 seconds (human-like) or unlimited (bot)
- SilverFish evaluates ~100-1000 boards per turn
- MCTS can do 1000-10000 iterations with good engine
- C++ engine is ~100x faster than Python for simulation

### 8.3 Most Promising Approaches (Ranked)
1. **MCTS + Neural Network** (peter1591's approach) - best theoretical foundation
2. **EA-optimized greedy scoring** (García-Sánchez approach) - best bang for buck
3. **ISMCTS** - best for handling hidden information properly
4. **ReBeL-style PBS search** - state of the art but very complex to implement
5. **Full enumeration + scoring** (SilverFish) - proven in practice, no ML needed

### 8.4 Practical Lessons
- Simple approaches with good evaluation can beat complex search
- Card interactions are THE hard problem - use a proven simulator
- Hidden information handling matters less than good board evaluation
- Lethal detection is non-negotiable - must never miss wins
- Deck-specific tuning significantly improves performance

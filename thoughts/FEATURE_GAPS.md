# Feature Gaps — V9 Decision Engine

> Mechanics and interactions not yet implemented in the RHEA search engine.
> Tests that exercise these gaps still PASS — gaps are logged as informational prints.

## Card Mechanics (Not Simulated)

| Mechanic | Status | Notes |
|----------|--------|-------|
| DISCOVER | ❌ Not simulated | Cards with DISCOVER are played as vanilla; no choice logic |
| BATTLECRY effects | ❌ Not simulated | Battlecry keyword is propagated to Minion but no effect triggers |
| DEATHRATTLE triggers | ❌ Not simulated | Deathrattle keyword stored but never triggers on minion death |
| QUEST rewards | ❌ Not simulated | Quest cards play as normal spells; no progress tracking |
| OUTCAST position bonus | ❌ Not simulated | Outcast cards play regardless of hand position |
| FREEZE | ❌ Not simulated | Freeze keyword stored but doesn't prevent attacks |
| LIFESTEAL | ❌ Not simulated | Lifesteal damage doesn't heal hero |
| SPELL_DAMAGE | ❌ Not simulated | Spell damage bonus not applied |
| CHOOSE_ONE | ❌ Not simulated | Choose One cards have no branching logic |
| INFUSE | ❌ Not simulated | Infuse mechanic not tracked |
| LOCATION | ❌ Not playable | Location cards filtered out of hand generation |
| COLOSSAL | ❌ Not simulated | Colossal appendage summoning not implemented |
| TRIGGER_VISUAL | ❌ Not simulated | Trigger effects not simulated |
| START_OF_GAME | ❌ Not simulated | Start of game effects not applied |
| IMMUNE | ❌ Not simulated | Immune keyword stored but not enforced |
| 激活 (Innervate) temp mana | ❌ Not simulated | 0-cost spell plays but doesn't grant temp mana |

## Position-Based Mechanics (位置机制)

| Mechanic | Status | Notes |
|----------|--------|-------|
| OUTCAST (流放) | ❌ Not simulated | Cards played from leftmost or rightmost hand position get bonus effects. Engine treats all hand positions identically. Hand position tracking not implemented. |
| Generated card positioning (生成牌位置) | ❌ Not enforced | Cards generated during a turn (Discover, Battlecry, etc.) should be added to **rightmost** position in hand. Engine adds dummy cards without position awareness. |
| Summon positioning (召唤位置) | ✅ Correct | Random/token summons appear at **rightmost** position on board. `apply_summon` appends to end of board list — this IS rightmost. |
| Board adjacency (场面邻接) | ❌ Not modeled | Board is a flat list; position doesn't matter. In real HS: dormant minions/locations create barriers, adjacency buffs only affect neighbors, position-targeted effects require index awareness. |
| Side-based attack buffs (位置增益) | ❌ Not modeled | Buffs like "+2 attack to leftmost/rightmost minion" depend on board position. Current buff system applies `all_friendly` without position filtering. |

### Key Implementation Needs

1. **Hand position tracking**: Add slot index to each card in hand; OUTCAST checks index 0 or last.
2. **Generated cards rightmost**: Ensure `hand.append()` is used explicitly for generated cards (currently incidental).
3. **Board position index**: Add position to Minion; support adjacency queries with barrier awareness.
4. **Position-aware buffs**: Extend `apply_buff` and `resolve_effects` to support `leftmost`, `rightmost`, `adjacent` targeting.

## Game Rules (Not Enforced)

| Rule | Status | Notes |
|------|--------|-------|
| STEALTH breaks on attack | ❌ Not enforced | Stealth minions can attack without losing stealth |
| STEALTH targeting protection | ❌ Not enforced | Enemy can target stealth minions in attack enumeration (B10 confirmed) |
| Weapon attack enumeration | ❌ Not in enumerate_legal_actions | Weapon attacks handled via mutation in search, not enumerated |
| Deathrattle on death | ❌ Not triggered | When minions die, deathrattle effects don't fire |
| Overload mana tracking | ❌ Not parsed | Engine doesn't parse 过载 text or set overload_next (B10 confirmed) |
| Fatigue damage | ❌ Not tracked | Drawing from empty deck doesn't increment fatigue_damage or deal damage (B10 confirmed) |
| Poisonous instant kill | ❌ Not implemented | Engine deals normal attack damage instead of instant kill (B10 confirmed) |
| Windfury second attack | ❌ Not tracked | can_attack set to False after first attack, no windfury tracking (B10 confirmed) |
| AOE damage simulation | Partial | Basic spell_simulator exists but limited |

## Tracked by Batch

- **Batch 01** (10 tests): Taunt blocking, charge/rush rules, divine shield, lethal detection, mana efficiency
- **Batch 02** (10 tests): Real deck data, weapon play, stealth minions, discover/battlecry gaps
- **Batch 03** (10 tests): Hero power, windfury, armor, secrets, poisonous, hero card, overload
- **Batch 04** (10 tests): Spell damage, AoE, card draw, summon, death cleanup, opponent sim, Pareto front
- **Batch 05** (10 tests): Edge cases, multi-action sequences, complex board states
- **Batch 06** (10 tests): Quest+discover play, weapon-then-attack sequence, RUSH propagation, taunt defense, stealth behavior, deathrattle play, outcast play, 0-cost spell chain, complex late-game
- **Batch 07** (10 tests): Lethal paths, death chains, mana boundaries, taunt-through-lethal, spell destroy/armor, engine edge cases
- **Batch 08** (10 tests): Position-awareness tests (summon rightmost, OUTCAST, generated card positioning, taunt multi-minion, board reindexing)
- **Batch 09** (10 tests): Position strategy (PLAY position variants, insert leftmost/between/rightmost, death cleanup reindex, deathrattle inheritance gap)
- **Batch 10** (10 tests): Weapon replacement durability reset, overload mana tracking gap, fatigue damage gap, stealth targeting protection gap, poisonous instant kill gap, windfury second attack gap, Hunter deck T5 search, Warlock deck T6 search, risk assessor class-specific AoE, combined lethal through taunt with spell
- **Batch 11** (10 tests): T4 lethal push, T5 discover resource mgmt, T7 druid ramp, T8 AoE decision, T3 DH tempo, T6 stealth combo, T9 full board 7v7, T7 near-death defense, T6 discover+draw chain, T12 fatigue endgame
- **Batch 12** (10 tests): T6 board recovery after wipe, T5 weapon durability mgmt, T4 divine shield trade, T6 mana squeeze, T7 lethal threat risk, T8 multi-spell combo, T5 taunt placement, T15 resource exhaustion, T7 draw+discover chain, T6 Pareto tempo vs value
- **Batch 13** (10 tests): High-complexity stress tests — max actions T10, cascading deaths, 5-source lethal, weapon break mid-combo, draw fatigue boundary, taunt death unlocks face, chromosome normalization, opponent sim worst-case, spell buff chain, multi-objective conflict
- **Batch 14** (10 tests): Complex real-deck scenario tests — Hunter T3 aggro push, Warlock Quest T5 discover chain, Warlock Dragon T8 charge finisher, DH T4 weapon+rush tempo, Druid T7 ramp big turn, Rogue-style Warlock T6 stealth+weapon, full 7v7 late-game T9, near-death taunt save T6, Hunter T4 deathrattle+rush combo, Druid T5 innervate big play
- **Batch 15** (10 tests): Extreme complexity — DH vs Warlock Dragon cross-deck T6 with weapon+CHARGE, Hunter vs Druid aggro race T5 with TAUNT, Warlock discover vs stealth T7, Druid full 7v7 board T10 no-play constraint, lethal through single taunt T8, low HP risk assessment T5, multi-weapon sequence T5 with replacement, discover-heavy 6-card hand T4, mixed-deck lethal calculation T9, endgame resource scarcity T12

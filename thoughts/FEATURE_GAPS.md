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

## Game Rules (Not Enforced)

| Rule | Status | Notes |
|------|--------|-------|
| STEALTH breaks on attack | ❌ Not enforced | Stealth minions can attack without losing stealth |
| STEALTH targeting protection | ❌ Not enforced | Enemy can target stealth minions in attack enumeration |
| Weapon attack enumeration | ❌ Not in enumerate_legal_actions | Weapon attacks handled via mutation in search, not enumerated |
| Deathrattle on death | ❌ Not triggered | When minions die, deathrattle effects don't fire |
| AOE damage simulation | Partial | Basic spell_simulator exists but limited |

## Tracked by Batch

- **Batch 01** (10 tests): Taunt blocking, charge/rush rules, divine shield, lethal detection, mana efficiency
- **Batch 02** (10 tests): Real deck data, weapon play, stealth minions, discover/battlecry gaps
- **Batch 03** (10 tests): Hero power, windfury, armor, secrets, poisonous, hero card, overload
- **Batch 04** (10 tests): Spell damage, AoE, card draw, summon, death cleanup, opponent sim, Pareto front
- **Batch 05** (10 tests): Edge cases, multi-action sequences, complex board states
- **Batch 06** (10 tests): Quest+discover play, weapon-then-attack sequence, RUSH propagation, taunt defense, stealth behavior, deathrattle play, outcast play, 0-cost spell chain, complex late-game

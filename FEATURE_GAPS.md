# Feature Gaps — V9 Decision Engine

> Known limitations and unsupported features discovered during integration testing.

## Lethal Checker

### Weapon attacks not in `enumerate_legal_actions`
- `enumerate_legal_actions` does not generate ATTACK actions with `source_index=-1` (hero weapon attack)
- The lethal checker's `_enumerate_damage_actions` does generate weapon attacks
- But the DFS legality check uses `enumerate_legal_actions`, which rejects weapon attacks
- **Impact**: `check_lethal` cannot find lethal paths involving weapon attacks
- **Workaround**: `max_damage_bound` correctly counts weapon damage; engine RHEA search finds weapon lethals

## Card Mechanics — Not Supported
- Discover, Infuse, Teach/Foretelling, Quest, Location
- Deathrattle (no trigger on minion death)
- Spell Damage (+N to spell damage)
- Lifesteal
- Enchantment system
- Cost modification effects
- Battlecry choice effects

## Spell Simulator — Limitations
- Target selection is automatic (highest-attack enemy minion), no player choice
- No multi-target resolution for complex spell text
- "Destroy" always targets first enemy minion
- Random effects are deterministic (pick one target)

## Engine — Known Behaviors
- RHEA is stochastic; tests use small populations for speed, may miss optimal plays
- Phase detection adjusts population size; tests verify valid results, not specific actions
- Multi-turn lethal setup bonus may not trigger in all cases

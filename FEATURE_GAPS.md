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

## Position-Based Mechanics (位置机制)

> Position-dependent rules not modeled in the current engine.

1. **OUTCAST (流放)**: Cards played from leftmost or rightmost hand position get bonus effects. Current engine treats all hand positions identically. Hand position tracking not implemented.

2. **Generated card positioning (生成牌位置)**: Cards generated during a turn (from Discover, Battlecry, etc.) should be added to the **rightmost** position in hand. Current engine adds dummy cards without position awareness.

3. **Summon positioning (召唤位置)**: Random/token summons should appear at the **rightmost** position on board. Current `apply_summon` appends to end of board list, which IS rightmost — this is correct.

4. **Board adjacency (场面邻接)**: Minions separated by dormant minions or locations cannot attack minions on the other side. Board is NOT a flat list — position matters for:
   - Attack range (can only attack adjacent enemies or enemies with clear path)
   - Adjacency buffs (e.g., "相邻的随从获得+1攻击力")
   - Position-targeted effects

5. **Side-based attack buffs**: Buffs like "+2 attack to leftmost/rightmost minion" depend on board position. Current buff system applies to "all_friendly" without position filtering.

## Engine — Known Behaviors
- RHEA is stochastic; tests use small populations for speed, may miss optimal plays
- Phase detection adjusts population size; tests verify valid results, not specific actions
- Multi-turn lethal setup bonus may not trigger in all cases

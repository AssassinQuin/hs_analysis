# V9 Decision Engine — Feature Gap Tracking

> Tracks supported, partially supported, and unsupported Hearthstone mechanics
> in the RHEA decision engine. Updated with each test batch.

## Status Legend

| Status | Meaning |
|--------|---------|
| ✅ SUPPORTED | Fully modeled in game state, legal actions, and evaluation |
| ⚠️ PARTIAL | Modeled in some layers but not end-to-end |
| ❌ NOT SUPPORTED | Not modeled; engine ignores this mechanic |
| 🔬 TESTED | Covered by integration tests (batch number noted) |

## Feature Matrix

### Core Mechanics

| Feature | Status | Tested | Notes |
|---------|--------|--------|-------|
| Basic minion attack | ✅ | B01 | Minion-to-minion and minion-to-hero combat |
| Weapon attack | ✅ | B01 | Hero weapon attacks with durability tracking |
| Taunt blocking | ✅ | B01 | Forces attacks on taunt minions before other targets |
| Charge | ✅ | B01 | Charge minions can attack face on play turn (when on board) |
| Rush | ✅ | B01 | Rush minions can attack minions but NOT face |
| Divine Shield | ✅ | B01 | Absorbs one hit of damage |
| Mana system | ✅ | B01 | Available/overloaded/max mana tracking |
| Lethal detection | ✅ | B01 | Board damage exact lethal found by engine |
| Board size limit (7) | ✅ | B01, B05 | `board_full()` prevents 8th minion; summon blocked when full (B05) |
| Divine Shield pop | ✅ | B01, B05 | Shield absorbs damage, pops without HP loss; counter-attack still occurs (B05) |
| Weapon replacement | ✅ | B05 | Playing a weapon replaces existing weapon on hero |
| Multi-attack sequence | ✅ | B05 | Sequential ATTACK actions with death cleanup between steps |
| Spell buff attack | ✅ | B05 | "+N 攻击力" parsed by EffectParser, applied via apply_buff |
| Empty hand end turn | ✅ | B05 | Engine finds ATTACK + END_TURN with no PLAY actions |

### Partially Supported

| Feature | Status | Tested | Notes |
|---------|--------|--------|-------|
| Charge from hand | ✅ | B01 | `apply_action` propagates mechanics to Minion fields |
| Rush from hand | ✅ | B01 | Mechanic propagated via `apply_action` |
| Hero Power | ✅ | B03 | Generates HERO_POWER action, deducts 2 mana, sets used flag |
| Windfury | ✅ | B03 | `has_attacked_once` tracking for second attack |
| Stealth | ✅ | B01 | Stealth breaks on attack; targeting rules enforced |
| Secret | ✅ | B03 | Tracked + trigger logic via `secret_triggers.py` (common secrets) |
| Overload | ✅ | B03 | Parsed from card text, applied in `apply_action` |
| Armor (opponent) | ✅ | B04 | `apply_damage` goes through armor before HP |
| Poisonous | ✅ | B03 | Instant kill on damage if attacker has poisonous |
| Hero card play | ⚠️ | B03 | Type recognized, card removed from hand, but hero replacement effect is no-op |
| Card draw | ✅ | B04 | Spell draw via resolve_effects, adds cards to hand |
| Spell direct damage | ✅ | B04 | resolve_effects + spell power bonus |
| Spell AoE damage | ✅ | B04 | Applies to all enemy minions, death cleanup |
| Spell summon | ⚠️ | B04, B05 | summon_stats parses stats but multi-summon count not parsed |
| Spell armor | ✅ | B04 | resolve_effects applies armor gain correctly |
| Spell heal | ⚠️ | B04 | Heals hero HP but does NOT cap at 30 |
| Death cleanup (combat) | ✅ | B04 | Both attacker and defender cleaned up when HP ≤ 0 |
| Next-turn lethal check | ✅ | B04 | Correctly sums board + spell burst + weapon vs opponent HP+armor |
| Risk-adjusted eval | ✅ | B04 | evaluate_with_risk reduces score by risk_penalty × 0.3 |
| Opponent simulator | ✅ | B04 | Applies resilience + lethal-exposure penalties |
| Battlecry | ✅ | B06 | `battlecry_dispatcher.py` handles 10+ effect types |
| Deathrattle | ✅ | B06 | `deathrattle.py` with cascade resolution |
| Discover | ✅ | B06 | `discover.py` with pool generation and best-pick |
| Lifesteal | ✅ | — | Heal hero for damage dealt (minion + spell) |
| Spell Damage +N | ✅ | — | `spell_power` on Minion, bonus added to spell damage |
| Reborn | ✅ | — | Dead minions with reborn resummon as 1/1 |
| Rewind | ✅ | — | Two-branch evaluation (normal vs double-effect) |
| Choose One (抉择) | ✅ | — | Best-option evaluation + Fandral both-effects |
| Immune | ✅ | — | Prevents all damage (minion + hero), cleared at end of turn |
| Can't Attack | ✅ | — | Minion cannot attack (e.g. Watcher) |
| Overdraw | ✅ | — | Cards burned when hand > 10 |
| Mana cap >10 | ✅ | — | `max_mana_cap` field, default 10, can be raised |
| Shatter (裂变) | ✅ | — | Card splits into 2 halved copies on draw |
| Dormant (休眠) | ✅ | — | Can't attack for N turns, awakens after countdown |
| Corrupt (腐蚀) | ✅ | — | Hand card upgrades when higher-cost played |
| Hero card replacement | ✅ | — | Armor, hero class, hero power reset |
| Cost Modification | ✅ | — | `cost_reduce` pattern in spell_simulator |
| Hand targeting | ✅ | — | `discard`, `hand_buff`, `cost_reduce` patterns |
| Dark Gift + Discover | ✅ | — | Auto-attach dark gift in discover pool |

### Not Supported (TODO)

| Feature | Status | Notes |
|---------|--------|-------|
| Inspire (激励) | ❌ TODO | Hero power triggers — low priority |
| Overkill (超杀) | ❌ TODO | Excess damage triggers — low priority |
| Enchantment effects | ⚠️ PARTIAL | Enchantment data model exists but limited runtime effect application |

### Position-Based Mechanics (位置机制)

| Feature | Status | Notes |
|---------|--------|-------|
| OUTCAST (流放) | ❌ | Cards played from leftmost or rightmost hand position get bonus effects. Current engine treats all hand positions identically. Hand position tracking not implemented. |
| Generated card positioning (生成牌位置) | ❌ | Cards generated during a turn (from Discover, Battlecry, etc.) should be added to the **rightmost** position in hand. Current engine adds dummy cards without position awareness. |
| Summon positioning (召唤位置) | ✅ | Random/token summons appear at the **rightmost** position on board. Current `apply_summon` appends to end of board list, which IS rightmost — correct behavior. |
| Board adjacency (场面邻接) | ❌ | Minions separated by dormant minions or locations cannot attack minions on the other side. Board is NOT a flat list — position matters for attack range, adjacency buffs, position-targeted effects. |
| Side-based attack buffs (位置增益) | ❌ | Buffs like "+2 attack to leftmost/rightmost minion" depend on board position. Current buff system applies to `all_friendly` without position filtering. |

**Details:**

1. **OUTCAST**: Hand position must be tracked per card. Leftmost (index 0) and rightmost (last index) are "outcast positions". When a card with OUTCAST mechanic is played from these positions, its bonus effect triggers. The engine currently has no concept of hand slot index.

2. **Generated card positioning**: The `resolve_effects` and spell simulation paths add cards to hand via `hand.append()`, which happens to place them rightmost — but this is incidental, not intentional position-aware logic. If hand ever becomes position-aware, generated cards must explicitly go to the rightmost slot.

3. **Summon positioning**: `apply_summon` uses `board.append()`, which is equivalent to rightmost position on board. This is correct per Hearthstone rules. No change needed.

4. **Board adjacency**: This is a significant gap. The current `board` is a flat `list[Minion]`. In real Hearthstone:
   - Dormant minions and locations create positional barriers
   - Adjacency buffs (e.g., "相邻的随从获得+1攻击力") buff only immediate neighbors
   - Position-targeted effects (e.g., "leftmost minion") require index-aware targeting
   - Attack range across dormant/location barriers is blocked
   Requires: Minion position index on board, barrier-aware adjacency queries, position-based buff targeting.

5. **Side-based attack buffs**: The current `apply_buff` and effect resolution use broad targeting (`all_friendly`, `all_enemy`). No path supports "leftmost minion" or "rightmost minion" targeting. Requires: position-aware buff targets in `resolve_effects` and `apply_buff`.

### Discovered in Batch 02

| Feature | Status | Notes |
|---------|--------|-------|
| CHOOSE_ONE | ❌ | Cards like 生命火花 have choose-one, not modeled |
| OUTCAST | ❌ | Cards like 伊利达雷研习 have outcast, not modeled (see Position-Based Mechanics above for full analysis) |
| COLOSSAL | ❌ | Cards like 柳牙 have colossal appendage, not modeled |
| TRIGGER_VISUAL | ❌ | Triggered effects not simulated |
| START_OF_GAME | ❌ | Start-of-game effects not relevant for in-game decisions |
| DEATHRATTLE on weapons | ❌ | 迷时战刃 has DEATHRATTLE on a weapon, not simulated |

## Batch Coverage

| Batch | File | Tests | Features Covered |
|-------|------|-------|------------------|
| B01 | `test_v9_hdt_batch01.py` | 10 | Weapon, taunt, lethal, divine shield, charge, rush, mana, overextension |
| B02 | `test_v9_hdt_batch02_deck_random.py` | 10 | Real deck data, multi-class (DH/Warlock/Hunter/Rogue/Druid), weapon+spells, charge finisher, stealth, big minions, lethal detection, defense |
| B03 | `test_v9_hdt_batch03.py` | 10 | Hero power, windfury, armor, secrets, poisonous, hero card, innervate, overload, full hand, spell-only hand |
| B04 | `test_v9_hdt_batch04.py` | 10 | Spell direct damage, AoE clear, draw cards, summon minions, death cleanup, opponent sim, next-turn lethal, Pareto front, risk-adjusted eval, armor/heal |
| B05 | `test_v9_hdt_batch05.py` | 10 | Summon board limits (full/near-full/multi-summon), AoE+summon combo, weapon replacement, divine shield pop, multi-attack sequence, spell buff, empty-hand end turn, deathrattle gap |
| B06 | `test_v9_hdt_batch06.py` | 10 | Real deck data-driven: quest+discover, weapon-attack, RUSH propagation, taunt defense, stealth, deathrattle, outcast, 0-cost chain, complex late-game |
| B07 | `test_v9_hdt_batch07.py` | 10 | Advanced combat: lethal paths, death chains, mana boundaries, taunt-through-lethal, spell destroy/armor, engine edge cases |
| B08 | `test_v9_hdt_batch08.py` | 10 | Position-awareness: summon rightmost ✅, OUTCAST positions (left/mid/right FEATURE_GAP), generated card rightmost ✅, taunt multi-minion ✅, board reindexing ✅, heal no-cap (B04 confirmed), complex multi-mechanic, hand order preservation ✅ |
| B09 | `test_v9_hdt_batch09.py` | 10 | Position strategy: PLAY position variants (empty/3-minion/6-minion boards) ✅, insert leftmost/between/rightmost ✅, death cleanup reindex ✅, deathrattle position inheritance gap ❌, engine position search ✅, full board boundary ✅, multi-death reindex chain ✅ |
| B10 | `test_v9_hdt_batch10.py` | 10 | Advanced scenarios: weapon replacement, overload gap, fatigue gap, stealth targeting gap, poisonous gap, windfury gap, Hunter deck T5, Warlock deck T6, risk AoE, lethal-through-taunt |
| B11 | `test_v9_hdt_batch11.py` | 10 | Complex real-game: T4 lethal push, T5 discover, T7 druid ramp, T8 AoE decision, T3 DH tempo, T6 stealth combo, T9 full board 7v7, T7 near-death defense, T6 discover+draw chain, T12 fatigue endgame |
| B12 | `test_v9_hdt_batch12.py` | 10 | Complex round 2: T6 board recovery, T5 weapon durability, T4 divine shield trade, T6 mana squeeze, T7 lethal threat risk, T8 multi-spell combo, T5 taunt placement, T15 resource exhaustion, T7 draw+discover chain, T6 Pareto tempo vs value |
| B13 | `test_v9_hdt_batch13.py` | 10 | High-complexity stress: max actions T10, cascading deaths, 5-source lethal, weapon break mid-combo, draw fatigue boundary, taunt death unlocks face, chromosome normalization, opponent sim worst-case, spell buff chain, multi-objective conflict |

## Key Engine Limitations Discovered

### 1. ~~Card → Minion Mechanic Propagation~~ ✅ FIXED

**Issue**: `apply_action()` in `rhea_engine.py` creates Minion objects with hardcoded
`can_attack=False` and does NOT copy `has_charge`, `has_rush`, `has_divine_shield`,
`has_taunt`, `has_windfury`, or `has_poisonous` from the Card's `mechanics` field.

**Fix applied**: `apply_action` now reads `card.mechanics` and propagates all mechanic
flags (CHARGE, RUSH, TAUNT, DIVINE_SHIELD, WINDFURY, STEALTH, POISONOUS) to the Minion.
Charge minions played from hand correctly get `can_attack=True`.

### 2. ~~Rush + Taunt Interaction~~ ✅ FIXED

**Issue**: When enemy has taunt, the engine allowed charge minions to attack face
(bypassing taunt). In real Hearthstone, charge doesn't bypass taunt — only the
charge minion itself ignores summoning sickness, not taunt rules.

**Fix applied**: Removed the charge-can-go-face exception in `enumerate_legal_actions`.
All minions (including charge) must attack taunt minions when opponent has taunt.

### 3. ~~Weapon Attack Source Index~~ ✅ FIXED

Weapon attacks with `source_index=-1` are now properly enumerated in `enumerate_legal_actions`
and handled in `apply_action`. The `describe()` method shows "英雄武器 攻击" for clarity.

### 4. Windfury Second Attack (Discovered B03)

**Issue**: After a minion attacks, `apply_action` sets `can_attack=False` unconditionally.
Windfury minions should be able to attack twice, but the engine has no tracking
for "has attacked once this turn" vs "has attacked twice".

**Workaround needed**: Track windfury attacks separately; allow second attack if
`has_windfury` and minion has attacked exactly once this turn.

### 5. Armor Damage Absorption (Discovered B03)

**Issue**: `apply_action` subtracts damage directly from `opponent.hero.hp`, ignoring
`opponent.hero.armor`. In real Hearthstone, armor absorbs damage before HP.

**Fix**: Before `hp -= damage`, check `armor > 0` and absorb what armor can, then
subtract remainder from HP.

### 6. Poisonous Combat (Discovered B03)

**Issue**: `apply_action` deals normal `source.attack` damage to target. If source
has `has_poisonous=True`, the target should be destroyed regardless of remaining health.
Current engine doesn't check poisonous flag during combat.

### 7. Overload Not Applied (Discovered B03)

**Issue**: `ManaState.overload_next` field exists but `apply_action` never sets it
when playing a card with OVERLOAD mechanic. The overload amount would need to be
parsed from card text or added as a separate field on Card.

### 8. Hero Card No-Op (Discovered B03)

**Issue**: Card type "HERO" is recognized in `enumerate_legal_actions` and the card
is removed from hand in `apply_action`, but no hero replacement effect is applied.
Hero cards should change hero_class, HP, armor, and replace hero power.

---

### Discovered in Batch 09

| Feature | Status | Notes |
|---------|--------|-------|
| PLAY position variants | ✅ SUPPORTED | `enumerate_legal_actions` generates one action per valid board position (0..len(board)). `apply_action` uses `insert(pos, minion)` for correct placement. |
| Board insert at position | ✅ SUPPORTED | Leftmost (pos=0), between, rightmost (pos=len(board)) all work correctly via `list.insert()` |
| Death cleanup reindex | ✅ SUPPORTED | List comprehension `[m for m in board if m.health > 0]` correctly reindexes surviving minions |
| board_full() boundary | ✅ SUPPORTED | 6 minions → 7 positions legal; after play, board_full() returns True |
| Deathrattle position inheritance | ❌ NOT SUPPORTED | When minion with deathrattle dies, no token is summoned at the inherited position. Engine just removes dead minion; no deathrattle effect fires. |

### Discovered in Batch 13

| Feature | Status | Notes |
|---------|--------|-------|
| AoE + manual death cleanup | ⚠️ PARTIAL | `EffectApplier.apply_aoe` does NOT call `_resolve_deaths` internally. Must call manually after AoE to clean dead minions. `resolve_effects` DOES call it automatically. |
| Spell buff target (all_friendly) | ⚠️ PARTIAL | `buff_atk` in `resolve_effects` applies to ALL friendly minions — no single-target buff support. FEATURE_GAP: no position-aware or single-target buff targeting. |
| Fatigue damage not tracked | ❌ NOT SUPPORTED | `apply_draw` caps `deck_remaining` at `max(0, ...)` but never increments `fatigue_damage` counter or deals fatigue damage. |
| Weapon ATTACK not enumerated | ✅ FIXED | `enumerate_legal_actions` now generates ATTACK with `source_index=-1` for hero weapon. Matches lethal checker convention. |
| Spell auto-targeting face vs minions | ⚠️ PARTIAL | `resolve_effects` auto-targets highest-attack enemy minion for damage spells. With empty enemy board, targets face. This limits spell-based lethal setups when enemy has minions. |
| Multi-objective tension | ✅ SUPPORTED | `mo_evaluate` correctly shows low `v_survival` for low-HP states while `v_tempo` can be high. Engine prioritizes lethal (fitness=10000) when found. |

*Last updated: Batch 13 (342 total tests across B01–B13) — High-complexity stress tests verified, AoE death cleanup and fatigue gaps documented*

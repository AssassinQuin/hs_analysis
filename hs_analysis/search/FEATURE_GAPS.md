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
| Board size limit (7) | ✅ | B01 | `board_full()` prevents 8th minion |

### Partially Supported

| Feature | Status | Tested | Notes |
|---------|--------|--------|-------|
| Charge from hand | ⚠️ | B01 | `apply_action` doesn't propagate CHARGE from Card.mechanics to Minion.has_charge; charge minions played from hand get `can_attack=False` |
| Rush from hand | ⚠️ | B01 | Same issue as Charge — mechanic not propagated during play |
| Windfury | ⚠️ | — | Minion field exists but attack tracking not implemented |
| Stealth | ⚠️ | — | Minion field exists but targeting rules not enforced |
| Secret | ⚠️ | — | Tracked in OpponentState.secrets but no simulation |
| Overload | ⚠️ | — | ManaState tracks overload_next but cards don't declare overload |
| Card draw | ⚠️ | — | No draw simulation in action space |

### Not Supported

| Feature | Status | Notes |
|---------|--------|-------|
| Discover | ❌ | No choice simulation |
| Infuse | ❌ | No infuse counter tracking |
| Teach/Foretelling | ❌ | No delayed hand effect model |
| Quest | ❌ | No quest progress tracking |
| Location | ❌ | Not in card_type handling |
| Deathrattle | ❌ | No death effect simulation |
| Spell Damage | ❌ | No spell power bonus calculation |
| Lifesteal | ❌ | No heal-on-damage mechanic |
| Enchantment | ❌ | Tracked as empty list on Minion but no effect application |
| Cost Modification | ❌ | No dynamic cost adjustment |
| Battlecry effects | ❌ | No targeted battlecry selection |
| Hero cards | ❌ | No hero power replacement |
| Poisonous | ❌ | Field exists but destroy-on-damage not implemented |
| Freeze | ❌ | Not modeled |
| Immune | ❌ | Not modeled |
| Can't Attack | ❌ | Not modeled |

## Batch Coverage

| Batch | File | Tests | Features Covered |
|-------|------|-------|------------------|
| B01 | `test_v9_hdt_batch01.py` | 10 | Weapon, taunt, lethal, divine shield, charge, rush, mana, overextension |

## Key Engine Limitations Discovered

### 1. Card → Minion Mechanic Propagation (Priority: HIGH)

**Issue**: `apply_action()` in `rhea_engine.py` creates Minion objects with hardcoded
`can_attack=False` and does NOT copy `has_charge`, `has_rush`, `has_divine_shield`,
`has_taunt`, `has_windfury`, or `has_poisonous` from the Card's `mechanics` field.

**Impact**: Charge/Rush minions played from hand cannot attack on the turn they're played,
violating core Hearthstone rules.

**Fix**: Add mechanic propagation in `apply_action`:
```python
if card.card_type.upper() == "MINION":
    mechanics = card.mechanics or []
    new_minion = Minion(
        ...
        can_attack="CHARGE" in mechanics,
        has_charge="CHARGE" in mechanics,
        has_rush="RUSH" in mechanics,
        has_divine_shield="DIVINE_SHIELD" in mechanics,
        has_taunt="TAUNT" in mechanics,
        ...
    )
```

### 2. Rush + Taunt Interaction

**Issue**: When enemy has taunt, the engine allows charge minions to attack face
(bypassing taunt). In real Hearthstone, charge doesn't bypass taunt — only the
charge minion itself ignores summoning sickness, not taunt rules.

**Current code** (`enumerate_legal_actions`):
```python
if enemy_taunts:
    if minion.has_charge and not minion.has_rush:
        # Charge can attack enemy hero directly
        actions.append(Action(...target_index=0))
```

**Fix**: Charge minions should also be forced to attack taunt minions first.

### 3. Weapon Attack Source Index

**Issue**: Weapon attacks use `source_index=-1`, which is a convention not clearly
documented. This works but could be error-prone for future features.

---

*Last updated: Batch 01 (10 tests)*

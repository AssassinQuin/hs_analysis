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
| Charge from hand | ✅ | B01 | `apply_action` now propagates CHARGE/RUSH/TAUNT/DIVINE_SHIELD/WINDFURY/STEALTH/POISONOUS from Card.mechanics to Minion fields |
| Rush from hand | ✅ | B01 | Mechanic propagated via `apply_action` — same fix as Charge from hand |
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

### Discovered in Batch 02

| Feature | Status | Notes |
|---------|--------|-------|
| CHOOSE_ONE | ❌ | Cards like 生命火花 have choose-one, not modeled |
| OUTCAST | ❌ | Cards like 伊利达雷研习 have outcast, not modeled |
| COLOSSAL | ❌ | Cards like 柳牙 have colossal appendage, not modeled |
| TRIGGER_VISUAL | ❌ | Triggered effects not simulated |
| START_OF_GAME | ❌ | Start-of-game effects not relevant for in-game decisions |
| DEATHRATTLE on weapons | ❌ | 迷时战刃 has DEATHRATTLE on a weapon, not simulated |

## Batch Coverage

| Batch | File | Tests | Features Covered |
|-------|------|-------|------------------|
| B01 | `test_v9_hdt_batch01.py` | 10 | Weapon, taunt, lethal, divine shield, charge, rush, mana, overextension |
| B02 | `test_v9_hdt_batch02_deck_random.py` | 10 | Real deck data, multi-class (DH/Warlock/Hunter/Rogue/Druid), weapon+spells, charge finisher, stealth, big minions, lethal detection, defense |

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

### 3. Weapon Attack Source Index

**Issue**: Weapon attacks use `source_index=-1`, which is a convention not clearly
documented. This works but could be error-prone for future features.

---

*Last updated: Batch 02 (20 total tests across B01+B02)*

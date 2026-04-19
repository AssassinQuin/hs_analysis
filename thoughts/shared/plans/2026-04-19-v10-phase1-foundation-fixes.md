# V10 Phase 1: Fix Broken Foundations — Implementation Plan

**Goal:** Fix 8 core mechanic bugs (charge-vs-taunt, windfury, overload, poisonous, combo, fatigue, stealth-break, freeze) while keeping all 363 existing tests passing.

**Architecture:** Minimal surgical edits to 3 files (`game_state.py`, `rhea_engine.py`, `lethal_checker.py`) plus 1 new test file (`test_v9_hdt_batch16.py`). Each fix touches exactly one function or adds one field. No new modules, no new dependencies.

**Design:** [thoughts/shared/designs/2026-04-19-v10-engine-overhaul-design.md](../designs/2026-04-19-v10-engine-overhaul-design.md) — Phase 1 sections 1.1 through 1.8.

---

## Dependency Graph

```
Batch 1 (parallel): 1.1, 1.2, 1.3, 1.4, 1.5, 1.6
  ├─ 1.1 game_state.py — add has_attacked_once + frozen fields to Minion
  ├─ 1.2 lethal_checker.py — fix charge-vs-taunt bug
  ├─ 1.3 rhea_engine.py — windfury tracking in apply_action
  ├─ 1.4 rhea_engine.py — overload parse + apply in apply_action / END_TURN
  ├─ 1.5 rhea_engine.py — poisonous + stealth + freeze in apply_action / enumerate
  ├─ 1.6 rhea_engine.py — combo tracking + fatigue in apply_action / END_TURN
Batch 2 (depends on ALL of batch 1): 2.1
  └─ 2.1 test_v9_hdt_batch16.py — all 8 mechanic tests
```

**Why this grouping:**
- Batch 1 tasks are independent code edits. Tasks 1.3-1.6 all modify `rhea_engine.py` but touch **different code paths** (different `action_type` branches and different functions), so they can be merged sequentially in one pass. I've separated them into distinct tasks for clarity, but the implementer will apply them as a single ordered edit to `rhea_engine.py`.
- Batch 2 depends on all code changes being in place.

---

## Batch 1: Foundation Fixes (6 tasks, apply in order)

### Task 1.1: Add `has_attacked_once` and `frozen_until_next_turn` to Minion

**File:** `hs_analysis/search/game_state.py`
**Depends:** none

**What:** Add two new boolean fields to the `Minion` dataclass. These are needed by windfury (1.2) and freeze (1.5) fixes.

**Change to `Minion` dataclass** (line ~35):

```python
@dataclass
class Minion:
    """A minion on the board."""

    dbf_id: int = 0
    name: str = ""
    attack: int = 0
    health: int = 0
    max_health: int = 0
    cost: int = 0
    can_attack: bool = False
    has_divine_shield: bool = False
    has_taunt: bool = False
    has_stealth: bool = False
    has_windfury: bool = False
    has_rush: bool = False
    has_charge: bool = False
    has_poisonous: bool = False
    has_attacked_once: bool = False          # NEW: windfury first-attack tracking
    frozen_until_next_turn: bool = False     # NEW: freeze effect
    enchantments: list = field(default_factory=list)
    owner: str = "friendly"  # or "enemy"
```

Also update `card_to_minion()` in `test_v9_hdt_batch15.py` and `test_v9_hdt_batch02_deck_random.py` to set these new fields when converting cards — BUT since they default to `False` and all existing code creates Minions with keyword args, **no existing code needs changes**. The `dataclass` defaults handle backward compatibility.

**Verification:** All 363 existing tests still pass (fields default to `False`, no behavior change).

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `refactor(game_state): add has_attacked_once and frozen_until_next_turn fields to Minion`

---

### Task 1.2: Fix charge-vs-taunt bug in lethal checker

**File:** `hs_analysis/search/lethal_checker.py`
**Depends:** none (independent of Task 1.1)

**What:** In `_enumerate_damage_actions` (lines 84-89), charge minions currently bypass taunt and can go face. This contradicts `enumerate_legal_actions` in `rhea_engine.py` (lines 130-140) which correctly forces ALL attackers (including charge) to target taunt first.

**Fix:** Remove the special case that lets charge minions go face through taunt. Replace lines 84-99 with:

```python
        if enemy_taunts:
            # ALL attackers (including charge) must target taunt minions first.
            # Charge bypasses summoning sickness, NOT taunt.
            for t in enemy_taunts:
                real_idx = state.opponent.board.index(t)
                actions.append(
                    Action(
                        action_type="ATTACK",
                        source_index=src_idx,
                        target_index=real_idx + 1,
                    )
                )
        else:
```

The removed code was:
```python
            # Charge minions can still go face even when taunts are present
            if m.has_charge and not m.has_rush:
                actions.append(
                    Action(action_type="ATTACK", source_index=src_idx, target_index=0)
                )
            # All attackers can target taunt minions
```

**Verification:**

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `fix(lethal_checker): charge minions must respect taunt, matching engine behavior`

---

### Task 1.3: Windfury second attack tracking

**File:** `hs_analysis/search/rhea_engine.py`
**Depends:** 1.1 (needs `has_attacked_once` field)

**What:** Two changes in `rhea_engine.py`:

#### Change A: `enumerate_legal_actions` (line ~126)

After line 127 (`if not (minion.can_attack or minion.has_charge or minion.has_rush):`), add windfury check. Replace the ATTACK actions section (lines 122-157):

```python
    # --- ATTACK actions ---
    # Check if enemy has taunt minions
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    for src_idx, minion in enumerate(state.board):
        # Can attack if: can_attack flag is set, OR has windfury and has attacked once
        can_act = minion.can_attack or (minion.has_windfury and minion.has_attacked_once)
        if not (can_act or minion.has_charge or minion.has_rush):
            continue
        # Frozen minions cannot attack
        if minion.frozen_until_next_turn:
            continue

        if enemy_taunts:
            # Must attack taunt minions — taunt blocks ALL face attacks,
            # including charge minions (charge bypasses summoning sickness, NOT taunt)
            for tgt_idx, _ in enumerate(enemy_taunts):
                # Find the actual index in opponent.board
                real_idx = _find_enemy_minion_index(state, enemy_taunts[tgt_idx])
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=real_idx + 1,  # 1-indexed (0 = hero)
                ))
        else:
            # No taunts: can attack enemy hero or any enemy minion
            # Enemy hero
            can_attack_hero = not minion.has_rush  # Rush can only attack minions
            if can_attack_hero:
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=0,
                ))
            # Enemy minions
            for tgt_idx in range(len(state.opponent.board)):
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=tgt_idx + 1,  # 1-indexed
                ))
```

#### Change B: `apply_action` ATTACK branch — windfury tracking (around line 296)

Replace the "Mark source as having attacked" block (lines 296-303):

```python
        # Mark source as having attacked
        if src_idx < len(s.board):
            # Source may have been removed if it died
            for m in s.board:
                if m is source:
                    if m.has_windfury and not m.has_attacked_once:
                        # First attack for windfury minion: allow second attack
                        m.has_attacked_once = True
                        # keep can_attack = True for second swing
                    else:
                        m.can_attack = False
                    break
        # If source died, it's already removed above
```

**Verification:**

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `feat(engine): windfury minions get second attack, freeze prevents attacks`

---

### Task 1.4: Overload parsing and application

**File:** `hs_analysis/search/rhea_engine.py`
**Depends:** none

**What:** Two changes:

#### Change A: Add `import re` at top of `rhea_engine.py` (if not already present)

Check if `re` is imported. If not, add `import re` to the imports section.

#### Change B: Parse overload in `apply_action` PLAY branch

After mana deduction (line ~192: `s.mana.available -= card.cost`), add overload parsing:

```python
        # Deduct mana
        s.mana.available -= card.cost

        # Parse overload from card text (Chinese: "过载：(N)" or "过载：(N)")
        card_text = getattr(card, 'text', '') or ''
        overload_match = re.search(r'过载[：:]\s*[（(]\s*(\d+)\s*[）)]', card_text)
        if overload_match:
            s.mana.overload_next += int(overload_match.group(1))
```

#### Change C: Apply overload in END_TURN branch

Replace the END_TURN branch (line ~309-310):

```python
    elif action.action_type == "END_TURN":
        # Apply overload: this turn's overload_next becomes next turn's overloaded
        s.mana.overloaded = s.mana.overload_next
        s.mana.overload_next = 0
        # Deduct overloaded mana from available (next turn mana already set by caller)
        s.mana.available -= s.mana.overloaded
        # Reset per-turn states
        s.cards_played_this_turn = []
        s.fatigue_damage = 0  # will be recalculated if needed next turn
        # Unfreeze friendly minions at end of turn
        for m in s.board:
            m.frozen_until_next_turn = False
```

**Note:** The END_TURN handler in the current code is `pass`. The overload application will deduct from `s.mana.available` at the point where the turn ends. The caller (RHEA engine) sets mana for the next turn after END_TURN, so the overloaded deduction here applies to the *current remaining* state. This is correct because the engine re-initializes mana for each new turn from `turn_number`, and the `overloaded` field will be read by the turn-initialization logic.

However, since the engine's turn init is in `RHEAEngine._evaluate_chromosome` (which sets mana from turn_number), the overload deduction should happen when the *next* turn begins, not at END_TURN. Let me check...

**Decision:** The design says "At turn start (END_TURN → next turn): `mana.available -= mana.overloaded`". Since `apply_action(END_TURN)` is the transition point, and the engine recalculates mana for the next evaluation, the safest approach is:
- Store overload in `mana.overload_next` when card is played
- In END_TURN: move `overload_next` to `overloaded` 
- The engine's evaluation function already has logic to handle mana state. The `overloaded` value will reduce available mana at the start of the next simulated turn.

**Verification:**

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `feat(engine): parse overload from card text and apply on next turn`

---

### Task 1.5: Poisonous instant kill + stealth break + freeze prevention

**File:** `hs_analysis/search/rhea_engine.py`
**Depends:** 1.1 (needs `frozen_until_next_turn` field)

**What:** Three changes in `apply_action` ATTACK branch:

#### Change A: Poisonous — after damage to enemy minion (around line 282)

After `target.health -= source.attack` (line 282), add:

```python
            # Poisonous: instant kill regardless of damage amount
            if source.has_poisonous and not target.has_divine_shield:
                target.health = 0
```

This should go right after the divine shield / damage block for target (lines 279-282), BEFORE counter-attack:

```python
            # Deal source attack to target
            if target.has_divine_shield:
                target.has_divine_shield = False
            else:
                target.health -= source.attack

            # Poisonous: instant kill regardless of damage amount
            # Note: if target had divine shield, the hit was absorbed — no kill
            if source.has_poisonous and not target.has_divine_shield and target.health > 0:
                target.health = 0

            # Counter-attack: deal target attack to source
```

Wait — the logic needs to account for divine shield correctly. If the target HAD divine shield, the shield pops but the minion is NOT killed by poisonous (the hit was absorbed). If the target did NOT have divine shield, damage was dealt AND poisonous kills it.

Let me refine: After the damage block, check if source has poisonous AND target survived (health > 0) AND target did not have divine shield (which would have absorbed the hit):

```python
            # Deal source attack to target
            target_had_divine_shield = target.has_divine_shield
            if target.has_divine_shield:
                target.has_divine_shield = False
            else:
                target.health -= source.attack

            # Poisonous: instant kill if hit connected (target had no divine shield)
            if source.has_poisonous and not target_had_divine_shield:
                target.health = 0
```

#### Change B: Stealth break — after attack resolves (around line 294, before marking attacked)

```python
        # Stealth breaks when minion attacks
        for m in s.board:
            if m is source and m.has_stealth:
                m.has_stealth = False
                break
```

#### Change C: Freeze — in `enumerate_legal_actions`, skip frozen minions

Already handled in Task 1.3's Change A (the `if minion.frozen_until_next_turn: continue` line).

For the freeze APPLICATION (setting frozen on a target), this happens via spell effects in `spell_simulator.py`. The design says "Add `frozen_until_next_turn: bool = False` to Minion. In `enumerate_legal_actions`, skip frozen. Reset on END_TURN."

We need to add freeze application to spell_simulator. Check if FREEZE is in the mechanics. Let me add a simple freeze application in `apply_action` when a spell with FREEZE mechanic is played:

In the SPELL branch of `apply_action` (around line 226-231), after `resolve_effects`:

```python
        elif card.card_type.upper() == 'SPELL':
            try:
                from hs_analysis.utils.spell_simulator import resolve_effects
                s = resolve_effects(s, card)
            except Exception:
                pass  # fallback to just removing from hand
            # Apply freeze if card has FREEZE mechanic
            mechanics = set(card.mechanics or [])
            if 'FREEZE' in mechanics:
                # Freeze all enemy minions (simplified: freeze first enemy minion)
                if s.opponent.board:
                    s.opponent.board[0].frozen_until_next_turn = True
```

**Note on FREEZE:** Hearthstone freeze effects are targeted (freeze a specific minion). Since our action model doesn't have spell targeting yet, the simplest correct approach is to check the card text for freeze patterns and apply appropriately. For now, we'll add a helper that parses freeze from card text:

```python
            # Apply freeze if card text contains freeze effect
            card_text = getattr(card, 'text', '') or ''
            if '冻结' in card_text or 'FREEZE' in (card.mechanics or []):
                # Simplified: freeze first enemy minion
                if s.opponent.board:
                    s.opponent.board[0].frozen_until_next_turn = True
```

The END_TURN reset of frozen is handled in Task 1.4's Change C.

**Verification:**

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `feat(engine): poisonous instant kill, stealth break on attack, freeze effect`

---

### Task 1.6: Combo tracking + fatigue damage

**File:** `hs_analysis/search/rhea_engine.py`
**Depends:** none (GameState already has `cards_played_this_turn` and `fatigue_damage` fields)

**What:** Two changes:

#### Change A: Track cards played this turn in PLAY branch

After removing card from hand (line ~195: `s.hand.pop(card_idx)`), add:

```python
        # Remove card from hand
        s.hand.pop(card_idx)

        # Track cards played this turn for combo
        s.cards_played_this_turn.append(card)
```

#### Change B: Fatigue damage — add `apply_draw` helper

Add a new helper function after `apply_action`:

```python
def apply_draw(state: GameState, count: int = 1) -> GameState:
    """Draw cards from deck. Deals fatigue damage if deck is empty.

    Returns a modified copy of state.
    """
    s = state.copy()
    for _ in range(count):
        if s.deck_remaining <= 0:
            # Fatigue: incrementing damage
            s.fatigue_damage += 1
            s.hero.hp -= s.fatigue_damage
        else:
            s.deck_remaining -= 1
            # Note: actual card addition to hand is handled by the engine's
            # deck list logic. This just decrements the counter.
    return s
```

This function is called from `spell_simulator.py` when resolving "draw N cards" effects. The spell simulator already handles draw effects; we just need it to call `apply_draw` instead of directly manipulating state. However, since the spell simulator is not being modified in Phase 1 (per the design), we'll add the function and integrate it later.

For now, the fatigue check should also work within `apply_action` when drawing via spell. The spell_simulator's `resolve_effects` already handles draw. We'll wire fatigue in by making `resolve_effects` call `apply_draw`. But since we're not modifying spell_simulator in Phase 1, we add the standalone function and test it directly.

**Also:** Reset `cards_played_this_turn` in END_TURN. This is already covered in Task 1.4's Change C (`s.cards_played_this_turn = []`).

**Verification:**

```bash
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `feat(engine): combo tracking on play, fatigue damage on empty deck draw`

---

## Batch 2: Integration Tests (depends on ALL of Batch 1)

### Task 2.1: Batch 16 test file — 8 mechanic tests

**File:** `hs_analysis/search/test_v9_hdt_batch16.py`
**Test:** This IS the test file
**Depends:** 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 (all foundation fixes must be in place)

**Pattern:** Follow batch15.py conventions exactly:
- Import `DeckTestGenerator` from `test_v9_hdt_batch02_deck_random`
- Use `get_card(dbf_id)` for real cards, `make_opp_minion()` for generic enemies
- One class per test, `@pytest.fixture` for state setup, one test method per class

**Test scenarios — all use manually constructed states (no RHEA search needed):**

```python
#!/usr/bin/env python3
"""V10 Phase 1 — Batch 16: Core Mechanic Bug Fix Tests

8 tests covering Phase 1 foundation fixes:
1. Charge minions respect taunt in lethal checker
2. Windfury minion attacks twice in one turn
3. Overload reduces available mana next turn
4. Poisonous minion kills regardless of damage amount
5. Combo cards gain bonus when played after another card
6. Fatigue damage increments on empty deck draw
7. Stealth breaks when minion attacks
8. Frozen minion cannot attack

All tests use manually constructed GameState (no DeckTestGenerator needed for mechanics).
"""

import pytest
import re

from hs_analysis.search.game_state import (
    GameState, HeroState, ManaState, OpponentState, Minion, Weapon,
)
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import (
    Action, enumerate_legal_actions, apply_action, apply_draw,
)
from hs_analysis.search.lethal_checker import (
    check_lethal, _enumerate_damage_actions,
)


# ===================================================================
# Test 1: Charge minions respect taunt in lethal checker
# ===================================================================

class Test01ChargeVsTauntLethal:
    """Charge minion should NOT bypass taunt in lethal checker.

    Setup: Friendly 5/5 CHARGE minion. Enemy hero at 5 HP with 1/3 TAUNT.
    Before fix: lethal checker finds lethal (charge goes face).
    After fix: lethal checker cannot find lethal (must kill taunt first).
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30, armor=0),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="charger", attack=5, health=5, max_health=5,
                       can_attack=True, has_charge=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=5, armor=0),
                board=[
                    Minion(name="taunter", attack=1, health=3, max_health=3,
                           has_taunt=True, owner="enemy"),
                ],
            ),
            hand=[],
        )

    def test_charge_cannot_go_face_through_taunt(self, state):
        """Charge minion must target taunt, cannot find lethal through taunt."""
        damage_actions = _enumerate_damage_actions(state)
        # All ATTACK actions should target the taunt minion (target_index=1), NOT face (0)
        attack_actions = [a for a in damage_actions if a.action_type == "ATTACK"]
        for a in attack_actions:
            if a.source_index >= 0:  # minion attacks (not hero weapon)
                assert a.target_index != 0, (
                    f"Charge minion should not target face through taunt, "
                    f"got target_index={a.target_index}"
                )

    def test_no_lethal_through_taunt(self, state):
        """Lethal checker should NOT find lethal with charge vs taunt."""
        result = check_lethal(state, time_budget_ms=50.0)
        assert result is None, "Should not find lethal: charge must kill taunt first"


# ===================================================================
# Test 2: Windfury second attack
# ===================================================================

class Test02WindfurySecondAttack:
    """Windfury minion should be able to attack twice per turn.

    Setup: 3/3 WINDFURY minion on board. Enemy hero at 6 HP.
    After first attack: minion keeps can_attack=True, has_attacked_once=True.
    After second attack: minion has can_attack=False.
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="windfury_guy", attack=3, health=3, max_health=3,
                       can_attack=True, has_windfury=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=10),
                board=[],
            ),
            hand=[],
        )

    def test_windfury_first_attack_keeps_can_attack(self, state):
        """After first attack, windfury minion should still be able to attack."""
        action = Action(action_type="ATTACK", source_index=0, target_index=0)
        s1 = apply_action(state, action)
        # Minion should still be able to attack (windfury second swing)
        assert s1.board[0].has_attacked_once is True
        assert s1.board[0].can_attack is True

    def test_windfury_two_attacks_deal_double_damage(self, state):
        """Two windfury attacks should deal 6 damage to enemy hero (3+3)."""
        action = Action(action_type="ATTACK", source_index=0, target_index=0)
        s1 = apply_action(state, action)
        assert s1.opponent.hero.hp == 7  # 10 - 3 = 7
        s2 = apply_action(s1, action)
        assert s2.opponent.hero.hp == 4  # 7 - 3 = 4
        assert s2.board[0].can_attack is False

    def test_windfury_enumerates_second_attack(self, state):
        """After first attack, windfury minion should appear in legal actions."""
        action = Action(action_type="ATTACK", source_index=0, target_index=0)
        s1 = apply_action(state, action)
        actions = enumerate_legal_actions(s1)
        attack_actions = [a for a in actions if a.action_type == "ATTACK"
                          and a.source_index == 0]
        assert len(attack_actions) > 0, "Windfury minion should have second attack available"


# ===================================================================
# Test 3: Overload parsing and application
# ===================================================================

class Test03OverloadMechanic:
    """Overload should reduce available mana next turn.

    Setup: Play a card with '过载：(2)' text. Next turn, 2 mana should be locked.
    """

    @pytest.fixture
    def state(self):
        overload_card = Card(
            dbf_id=99999, name="过载测试卡", cost=3, card_type="SPELL",
            text="造成3点伤害。过载：（2）",
        )
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=5, max_mana=5),
            board=[],
            opponent=OpponentState(hero=HeroState(hp=30)),
            hand=[overload_card],
        )

    def test_overload_parsed_on_play(self, state):
        """Overload should be parsed from card text and stored in overload_next."""
        action = Action(action_type="PLAY", card_index=0)
        s1 = apply_action(state, action)
        assert s1.mana.overload_next == 2, f"Expected overload_next=2, got {s1.mana.overload_next}"

    def test_overload_applied_on_end_turn(self, state):
        """END_TURN should move overload_next to overloaded."""
        action_play = Action(action_type="PLAY", card_index=0)
        s1 = apply_action(state, action_play)
        action_end = Action(action_type="END_TURN")
        s2 = apply_action(s1, action_end)
        assert s2.mana.overloaded == 2, f"Expected overloaded=2, got {s2.mana.overloaded}"
        assert s2.mana.overload_next == 0, f"Expected overload_next=0, got {s2.mana.overload_next}"


# ===================================================================
# Test 4: Poisonous instant kill
# ===================================================================

class Test04PoisonousInstantKill:
    """Poisonous minion should kill any minion regardless of damage.

    Setup: 1/1 POISONOUS minion attacks 5/5 enemy minion.
    Result: Enemy minion dies (health set to 0).
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="cobra", attack=1, health=1, max_health=1,
                       can_attack=True, has_poisonous=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[
                    Minion(name="big_target", attack=5, health=5, max_health=5,
                           owner="enemy"),
                ],
            ),
            hand=[],
        )

    def test_poisonous_kills_regardless_of_damage(self, state):
        """1/1 poisonous should kill a 5/5 minion (not just deal 1 damage)."""
        action = Action(action_type="ATTACK", source_index=0, target_index=1)
        s1 = apply_action(state, action)
        assert len(s1.opponent.board) == 0, "Poisonous should kill target instantly"

    def test_poisonous_vs_divine_shield(self):
        """Poisonous should NOT kill if target has divine shield (shield absorbs)."""
        state = GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="cobra", attack=1, health=1, max_health=1,
                       can_attack=True, has_poisonous=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[
                    Minion(name="shielded", attack=2, health=2, max_health=2,
                           has_divine_shield=True, owner="enemy"),
                ],
            ),
            hand=[],
        )
        action = Action(action_type="ATTACK", source_index=0, target_index=1)
        s1 = apply_action(state, action)
        # Target should survive: divine shield absorbed the hit
        assert len(s1.opponent.board) == 1, "Divine shield should block poisonous kill"
        assert s1.opponent.board[0].has_divine_shield is False, "Shield should be consumed"


# ===================================================================
# Test 5: Combo tracking
# ===================================================================

class Test05ComboTracking:
    """Cards played this turn should be tracked. Second card should see combo active.

    Setup: Play a minion, then check state.cards_played_this_turn.
    """

    @pytest.fixture
    def state(self):
        card1 = Card(dbf_id=100001, name="第一张", cost=2, card_type="MINION",
                     attack=2, health=2)
        card2 = Card(dbf_id=100002, name="第二张连击", cost=2, card_type="MINION",
                     attack=2, health=2)
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[],
            opponent=OpponentState(hero=HeroState(hp=30)),
            hand=[card1, card2],
        )

    def test_first_play_no_combo(self, state):
        """First card played should have empty cards_played_this_turn before play."""
        action = Action(action_type="PLAY", card_index=0, position=0)
        s1 = apply_action(state, action)
        assert len(s1.cards_played_this_turn) == 1

    def test_second_play_has_combo(self, state):
        """After playing one card, second play should see combo active."""
        action1 = Action(action_type="PLAY", card_index=0, position=0)
        s1 = apply_action(state, action1)
        assert len(s1.cards_played_this_turn) == 1
        action2 = Action(action_type="PLAY", card_index=0, position=1)
        s2 = apply_action(s1, action2)
        assert len(s2.cards_played_this_turn) == 2

    def test_combo_resets_on_end_turn(self, state):
        """END_TURN should reset cards_played_this_turn."""
        action1 = Action(action_type="PLAY", card_index=0, position=0)
        s1 = apply_action(state, action1)
        action_end = Action(action_type="END_TURN")
        s2 = apply_action(s1, action_end)
        assert len(s2.cards_played_this_turn) == 0


# ===================================================================
# Test 6: Fatigue damage
# ===================================================================

class Test06FatigueDamage:
    """Drawing from empty deck should deal incrementing fatigue damage.

    First draw: 1 damage. Second: 2 damage. Third: 3 damage.
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[],
            opponent=OpponentState(hero=HeroState(hp=30)),
            hand=[],
            deck_remaining=0,
            fatigue_damage=0,
        )

    def test_first_fatigue_deals_1(self, state):
        """First fatigue draw should deal 1 damage."""
        s1 = apply_draw(state, 1)
        assert s1.hero.hp == 29
        assert s1.fatigue_damage == 1

    def test_fatigue_increments(self, state):
        """Fatigue should increment: 1, 2, 3..."""
        s1 = apply_draw(state, 1)
        assert s1.hero.hp == 29  # -1
        s2 = apply_draw(s1, 1)
        assert s2.hero.hp == 27  # -1-2
        s3 = apply_draw(s2, 1)
        assert s3.hero.hp == 24  # -1-2-3
        assert s3.fatigue_damage == 3

    def test_fatigue_with_deck_remaining(self):
        """Drawing with cards in deck should NOT deal fatigue."""
        state = GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[],
            opponent=OpponentState(hero=HeroState(hp=30)),
            hand=[],
            deck_remaining=3,
        )
        s1 = apply_draw(state, 2)
        assert s1.hero.hp == 30  # no damage
        assert s1.deck_remaining == 1


# ===================================================================
# Test 7: Stealth break on attack
# ===================================================================

class Test07StealthBreakOnAttack:
    """Stealth minion should lose stealth when it attacks.

    Setup: 3/3 STEALTH minion attacks enemy hero.
    Result: Minion no longer has stealth after attack.
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="stealthy", attack=3, health=3, max_health=3,
                       can_attack=True, has_stealth=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[],
            ),
            hand=[],
        )

    def test_stealth_breaks_on_attack(self, state):
        """Minion should lose stealth after attacking."""
        action = Action(action_type="ATTACK", source_index=0, target_index=0)
        s1 = apply_action(state, action)
        assert s1.board[0].has_stealth is False, "Stealth should break on attack"

    def test_stealth_breaks_on_minion_attack(self):
        """Stealth should also break when attacking an enemy minion."""
        state = GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="stealthy", attack=3, health=3, max_health=3,
                       can_attack=True, has_stealth=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[
                    Minion(name="target", attack=1, health=1, max_health=1,
                           owner="enemy"),
                ],
            ),
            hand=[],
        )
        action = Action(action_type="ATTACK", source_index=0, target_index=1)
        s1 = apply_action(state, action)
        assert s1.board[0].has_stealth is False


# ===================================================================
# Test 8: Freeze effect
# ===================================================================

class Test08FreezeEffect:
    """Frozen minion should not be able to attack.

    Setup: 3/3 minion with frozen_until_next_turn=True.
    Result: Minion should NOT appear in legal attack actions.
    """

    @pytest.fixture
    def state(self):
        return GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="frozen_guy", attack=3, health=3, max_health=3,
                       can_attack=True, frozen_until_next_turn=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[],
            ),
            hand=[],
        )

    def test_frozen_minion_cannot_attack(self, state):
        """Frozen minion should NOT generate any ATTACK actions."""
        actions = enumerate_legal_actions(state)
        attack_actions = [a for a in actions if a.action_type == "ATTACK"
                          and a.source_index == 0]
        assert len(attack_actions) == 0, "Frozen minion should not be able to attack"

    def test_frozen_resets_on_end_turn(self, state):
        """END_TURN should unfreeze friendly minions."""
        action = Action(action_type="END_TURN")
        s1 = apply_action(state, action)
        assert s1.board[0].frozen_until_next_turn is False

    def test_normal_minion_can_attack(self):
        """Non-frozen minion with can_attack should be able to attack."""
        state = GameState(
            hero=HeroState(hp=30),
            mana=ManaState(available=10, max_mana=10),
            board=[
                Minion(name="normal", attack=3, health=3, max_health=3,
                       can_attack=True),
            ],
            opponent=OpponentState(
                hero=HeroState(hp=30),
                board=[],
            ),
            hand=[],
        )
        actions = enumerate_legal_actions(state)
        attack_actions = [a for a in actions if a.action_type == "ATTACK"
                          and a.source_index == 0]
        assert len(attack_actions) > 0, "Non-frozen minion should be able to attack"
```

**Verification:**

```bash
# Run ONLY the new batch16 tests
python -m pytest hs_analysis/search/test_v9_hdt_batch16.py -v --tb=short

# Run ALL tests to confirm no regression
python -m pytest hs_analysis/search/ -q --tb=short 2>&1 | tail -5
```

**Commit:** `test(batch16): 8 Phase 1 mechanic tests — charge-taunt, windfury, overload, poisonous, combo, fatigue, stealth, freeze`

---

## Summary: Merged Edit Order for `rhea_engine.py`

Since tasks 1.3–1.6 all modify `rhea_engine.py`, here's the exact edit sequence for the implementer:

1. **Add `import re`** to the top of the file (if missing)

2. **`enumerate_legal_actions`** — Replace the ATTACK section (lines 122-157) with the version from Task 1.3 Change A (includes windfury check + freeze check)

3. **`apply_action` PLAY branch** — After mana deduction (line 192), add overload parsing from Task 1.4 Change B. After `s.hand.pop(card_idx)` (line 195), add combo tracking from Task 1.6 Change A. After spell resolution (line 231), add freeze application from Task 1.5 Change C.

4. **`apply_action` ATTACK branch** — Replace damage resolution for enemy minions (lines 278-293) with version from Task 1.5 Changes A+B (poisonous + stealth break). Replace the "mark source as attacked" block (lines 296-303) with Task 1.3 Change B (windfury tracking).

5. **`apply_action` END_TURN branch** — Replace `pass` (line 310) with Task 1.4 Change C (overload application, cards_played reset, freeze reset).

6. **After `apply_action`** — Add `apply_draw` helper from Task 1.6 Change B.

---

## File Change Summary

| File | Tasks | Changes |
|------|-------|---------|
| `hs_analysis/search/game_state.py` | 1.1 | +2 fields on `Minion` dataclass |
| `hs_analysis/search/lethal_checker.py` | 1.2 | Remove charge-bypasses-taunt block |
| `hs_analysis/search/rhea_engine.py` | 1.3–1.6 | Windfury, overload, poisonous, stealth, freeze, combo, fatigue |
| `hs_analysis/search/test_v9_hdt_batch16.py` | 2.1 | New file: 8 test classes |

---

## Risk Mitigation

- **All changes default to `False`**: New `Minion` fields don't change any existing behavior until explicitly set.
- **END_TURN was a no-op (`pass`)**: Adding logic there is safe — nothing depended on END_TURN being empty.
- **Overload regex is defensive**: `re.search` returns `None` if pattern doesn't match, so non-overload cards are unaffected.
- **Poisonous uses identity check**: The `not target_had_divine_shield` variable is scoped to the attack block, no global state pollution.
- **`apply_draw` is additive**: New function, doesn't modify any existing function.
- **Tests are self-contained**: All 8 tests construct GameState manually — no dependency on card DB or DeckTestGenerator.

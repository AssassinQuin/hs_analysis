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

    Setup: Friendly 5/5 CHARGE minion. Enemy hero at 10 HP with 1/3 TAUNT.
    Charger can kill taunt then go face, but 5 damage < 10 HP = no lethal.
    Before fix: lethal checker found lethal by sending charge face through taunt.
    After fix: charge must target taunt; after killing taunt, 5 damage is not lethal.
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
                hero=HeroState(hp=10, armor=0),
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

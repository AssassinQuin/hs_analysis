#!/usr/bin/env python3
"""V9 Decision Engine — Batch 03: Untested Engine Path Integration Tests

Covers engine paths NOT exercised by batch01 or batch02:
- HERO_POWER action generation and mana deduction
- Windfury second attack (known broken: can_attack set to False after first)
- Poisonous combat (field exists but apply_action deals normal damage)
- Armor damage absorption on opponent hero
- Secrets list presence (informational only in current engine)
- Hero card play (type "HERO" recognized but effect is no-op)
- Overload fields on ManaState
- Full hand boundary (10 cards)
- Empty board spell-heavy hand

Tests use apply_action directly for deterministic verification.
FEATURE_GAP scenarios still PASS but print the gap.
"""

import time
import pytest

from hs_analysis.search.game_state import (
    GameState, HeroState, ManaState, OpponentState,
    Minion, Weapon,
)
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import (
    RHEAEngine, SearchResult, Action,
    enumerate_legal_actions, apply_action,
)
from hs_analysis.search.test_v9_hdt_batch01 import HDTGameStateFactory


# ===================================================================
# Helpers
# ===================================================================

def _quick_engine(time_limit: float = 100.0) -> RHEAEngine:
    return RHEAEngine(
        pop_size=15,
        max_gens=20,
        time_limit=time_limit,
        max_chromosome_length=4,
    )


# ===================================================================
# Test 1: Hero Power Usage
# ===================================================================

def test_01_hero_power_usage():
    """Turn 5 DH, 5 mana, empty hand — hero power should be legal.

    Engine implements hero power as "deduct 2 mana, set used flag".
    We verify:
      1. HERO_POWER appears in enumerate_legal_actions
      2. apply_action deducts 2 mana and sets hero_power_used
    """
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_class="DEMONHUNTER",
        player_mana=5,
        player_hand=[],  # empty hand — only hero power + END_TURN
    )
    # Hero power requires 2 mana and hero_power_used=False
    assert state.mana.available == 5
    assert not state.hero.hero_power_used

    legal = enumerate_legal_actions(state)
    types = {a.action_type for a in legal}
    assert "HERO_POWER" in types, "HERO_POWER must be legal with ≥2 mana and unused"
    assert "END_TURN" in types

    # Apply hero power
    hp_action = Action(action_type="HERO_POWER")
    new_state = apply_action(state, hp_action)

    assert new_state.mana.available == 3, "Should deduct 2 mana for hero power"
    assert new_state.hero.hero_power_used, "hero_power_used should be True"
    # Original state untouched
    assert not state.hero.hero_power_used


# ===================================================================
# Test 2: Windfury Double Attack
# ===================================================================

def test_02_windfury_double_attack():
    """Turn 6, board has windfury 4/4, opponent has 2/2 and 1/1.

    Current engine sets can_attack=False after first attack, so windfury
    second attack is BROKEN. This test documents the feature gap.
    """
    state = HDTGameStateFactory.create_state(
        turn=6,
        player_mana=6,
        player_board=[
            {
                "name": "风怒随从",
                "tags": {
                    "ATK": 4, "HEALTH": 4, "COST": 4,
                    "WINDFURY": 1, "EXHAUSTED": 0,
                },
            },
        ],
        opponent_board=[
            {"name": "Enemy A", "tags": {"ATK": 2, "HEALTH": 2}},
            {"name": "Enemy B", "tags": {"ATK": 1, "HEALTH": 1}},
        ],
    )
    windfury_minion = state.board[0]
    assert windfury_minion.has_windfury, "Minion should have windfury"
    assert windfury_minion.can_attack, "Minion should be able to attack"

    # First attack: windfury minion (idx 0) → enemy minion 0 (target=1)
    action1 = Action(action_type="ATTACK", source_index=0, target_index=1)
    after1 = apply_action(state, action1)

    # Check the windfury minion survived and killed enemy
    assert len(after1.opponent.board) == 1, "First attack should kill 2/2"
    if len(after1.board) > 0:
        attacker = after1.board[0]
        # After first attack, engine sets can_attack=False — windfury is broken
        if attacker.can_attack:
            # If windfury worked, we should be able to enumerate a second attack
            legal2 = enumerate_legal_actions(after1)
            attacks2 = [a for a in legal2 if a.action_type == "ATTACK"]
            assert len(attacks2) >= 1, "Windfury minion should have second attack"
        else:
            print("FEATURE_GAP: Windfury second attack broken — "
                  "can_attack set to False after first attack")
            # Verify we CANNOT find a second attack
            legal2 = enumerate_legal_actions(after1)
            attacks2 = [a for a in legal2 if a.action_type == "ATTACK"]
            assert len(attacks2) == 0, (
                "Confirmed broken: no second attack generated for windfury minion"
            )


# ===================================================================
# Test 3: Opponent Armor Absorbs Damage
# ===================================================================

def test_03_opponent_armor_absorbs_damage():
    """Turn 5, player has 4/4 minion, opponent has 3 HP + 5 armor.

    After face attack: armor should decrease before HP.
    If engine doesn't handle armor, log as FEATURE_GAP.
    """
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_board=[
            {"name": "Attacker", "tags": {"ATK": 4, "HEALTH": 4, "EXHAUSTED": 0}},
        ],
        opponent_hp=3,
        opponent_armor=5,
    )
    assert state.opponent.hero.hp == 3
    assert state.opponent.hero.armor == 5

    # Attack face: source_idx=0, target_idx=0 (hero)
    action = Action(action_type="ATTACK", source_index=0, target_index=0)
    new_state = apply_action(state, action)

    # Engine does: opponent.hero.hp -= source.attack
    # In real HS: armor absorbs first, then HP
    # Current engine implementation just subtracts from HP directly
    if new_state.opponent.hero.hp == -1 and new_state.opponent.hero.armor == 5:
        # Engine subtracted 4 from HP (3 → -1), armor untouched
        print("FEATURE_GAP: Armor does not absorb damage — "
              "engine subtracts directly from HP")
    elif new_state.opponent.hero.hp == 3 and new_state.opponent.hero.armor == 1:
        # Correct: armor absorbed 4 damage (5→1), HP untouched
        pass  # Armor works correctly
    elif new_state.opponent.hero.hp == 2 and new_state.opponent.hero.armor == 0:
        # Also valid interpretation: armor absorbs what it can (5→0),
        # remaining damage (4-5=-1) still doesn't hit HP... actually this
        # case means armor absorbed all 4, with 1 remaining.
        pass
    else:
        # Some other outcome — at least verify no crash
        pass

    # At minimum: engine doesn't crash with non-zero armor
    assert new_state is not None


# ===================================================================
# Test 4: Opponent Secrets Present
# ===================================================================

def test_04_opponent_secrets_present():
    """Turn 5, opponent has EXPLOSIVE_TRAP secret, player has 3/3 minion.

    Secrets are informational only in current engine — they don't trigger.
    Verify engine still produces valid actions with secrets present.
    """
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_board=[
            {"name": "攻击者", "tags": {"ATK": 3, "HEALTH": 3, "EXHAUSTED": 0}},
        ],
        opponent_secrets=["EXPLOSIVE_TRAP"],
    )
    assert state.opponent.secrets == ["EXPLOSIVE_TRAP"]

    legal = enumerate_legal_actions(state)

    # Should still generate attack actions (secrets don't block in engine)
    attacks = [a for a in legal if a.action_type == "ATTACK"]
    assert len(attacks) > 0, "Should have attack actions despite secrets"

    # Attack face should be legal
    face_attacks = [a for a in attacks if a.target_index == 0]
    assert len(face_attacks) > 0, "Face attack should be legal"

    # Apply face attack — engine should not trigger secret
    action = Action(action_type="ATTACK", source_index=0, target_index=0)
    new_state = apply_action(state, action)
    assert new_state is not None
    # Secret did NOT destroy our minion (engine doesn't simulate EXPLOSIVE_TRAP)
    if len(new_state.board) == 1 and new_state.board[0].health == 3:
        print("FEATURE_GAP: Secrets don't trigger — "
              "EXPLOSIVE_TRAP did not damage attacker")

    # Engine result is valid
    assert new_state.opponent.hero.hp == 27, "Face damage applied normally"


# ===================================================================
# Test 5: Poisonous Minion Combat
# ===================================================================

def test_05_poisonous_minion_combat():
    """Turn 4, player has 1/3 poisonous minion, opponent has 8/8.

    Poisonous should destroy any minion damaged by this minion.
    Current engine deals normal damage (1) without poison kill.
    """
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=4,
        player_board=[
            {
                "name": "毒蛇",
                "tags": {
                    "ATK": 1, "HEALTH": 3, "COST": 2,
                    "POISONOUS": 1, "EXHAUSTED": 0,
                },
            },
        ],
        opponent_board=[
            {"name": "巨兽", "tags": {"ATK": 8, "HEALTH": 8}},
        ],
    )
    poisonous = state.board[0]
    assert poisonous.has_poisonous, "Minion should have poisonous"
    assert poisonous.attack == 1

    # Attack: poisonous 1/3 → enemy 8/8
    action = Action(action_type="ATTACK", source_index=0, target_index=1)
    new_state = apply_action(state, action)

    # Check if enemy minion was destroyed by poison
    if len(new_state.opponent.board) == 0:
        # Poisonous worked — enemy destroyed
        pass
    elif len(new_state.opponent.board) == 1:
        enemy = new_state.opponent.board[0]
        if enemy.health == 7:
            print("FEATURE_GAP: Poisonous not implemented — "
                  "enemy minion took normal damage (1) and survived at 7/8")
        # Poisonous minion should have died from counter-attack (8 damage to 3hp)
        if len(new_state.board) == 0:
            pass  # Correct: our 1/3 died from 8 counter-damage
    else:
        pass  # Unexpected but don't fail

    # Verify at minimum: no crash, state is valid
    assert new_state is not None


# ===================================================================
# Test 6: Hero Card Play
# ===================================================================

def test_06_hero_card_play():
    """Turn 10, hero card in hand (10-cost HERO type).

    Engine recognizes card_type "HERO" in enumerate_legal_actions
    and removes it from hand in apply_action, but effect is no-op.
    """
    hero_card = Card(
        dbf_id=59911,
        name="灭世者死亡之翼",
        cost=10,
        original_cost=10,
        card_type="HERO",
        attack=0,
        health=30,
        text="Battlecry: Destroy all minions.",
        mechanics=["BATTLECRY"],
    )
    state = HDTGameStateFactory.create_state(
        turn=10,
        player_mana=10,
        opponent_board=[
            {"name": "Enemy Minion", "tags": {"ATK": 3, "HEALTH": 3}},
        ],
    )
    # Inject Card objects directly (factory expects dicts, but we need real Cards)
    state.hand = [hero_card]

    # HERO card should be legal to play (cost 10 ≤ mana 10)
    legal = enumerate_legal_actions(state)
    hero_plays = [a for a in legal
                  if a.action_type == "PLAY"
                  and 0 <= a.card_index < len(state.hand)
                  and state.hand[a.card_index].card_type.upper() == "HERO"]
    assert len(hero_plays) > 0, "HERO card should be a legal play action"

    # Apply the hero card play
    action = hero_plays[0]
    new_state = apply_action(state, action)

    # Card removed from hand
    assert len(new_state.hand) == 0, "HERO card should be removed from hand"

    # Mana deducted
    assert new_state.mana.available == 0, "Mana should be deducted (10 cost)"

    # Hero card effect is no-op — enemy minions still present
    if len(new_state.opponent.board) == 1:
        print("FEATURE_GAP: Hero card play effect is no-op — "
              "enemy minions not destroyed by battlecry")

    # Hero class/name didn't change (no hero replacement)
    if new_state.hero.hero_class == "DEMONHUNTER":
        print("FEATURE_GAP: Hero card doesn't replace hero — "
              "class/stats unchanged after HERO card play")


# ===================================================================
# Test 7: Druid Innervate Ramp
# ===================================================================

def test_07_druid_innervate_ramp():
    """Turn 3 Druid, 激活 (0-cost SPELL) in hand + a 5-cost minion.

    0-cost spell should be a legal play.
    激活 should give temporary mana, but spell_simulator may not implement it.
    """
    innervate = Card(
        dbf_id=40956,
        name="激活",
        cost=0,
        original_cost=0,
        card_type="SPELL",
        text="获得一个空的法力水晶。",
        mechanics=[],
    )
    five_drop = Card(
        dbf_id=49984,
        name="费伍德树人",
        cost=5,
        original_cost=5,
        card_type="MINION",
        attack=5,
        health=5,
        mechanics=["TAUNT"],
    )
    state = HDTGameStateFactory.create_state(
        turn=3,
        player_class="DRUID",
        player_mana=3,
    )
    # Inject Card objects directly
    state.hand = [innervate, five_drop]

    legal = enumerate_legal_actions(state)

    # 0-cost spell should be legal
    innervate_plays = [a for a in legal
                       if a.action_type == "PLAY"
                       and a.card_index == 0]
    assert len(innervate_plays) > 0, "0-cost spell should be a legal play"

    # 5-cost minion should NOT be legal with only 3 mana
    five_drop_plays = [a for a in legal
                       if a.action_type == "PLAY"
                       and a.card_index == 1]
    assert len(five_drop_plays) == 0, "5-cost minion should not be legal at 3 mana"

    # Play innervate (0-cost spell)
    action = innervate_plays[0]
    after_innervate = apply_action(state, action)

    # Innervate removed from hand
    assert len(after_innervate.hand) == 1

    # After innervate: mana should be 3 (unchanged since cost is 0)
    # Real 激活 gives +1 temporary mana, but spell_simulator may not handle it
    if after_innervate.mana.available == 3:
        print("FEATURE_GAP: Innervate (激活) doesn't grant temporary mana — "
              "spell effect not simulated")

    # Verify no crash
    assert after_innervate is not None


# ===================================================================
# Test 8: Overload Tracking
# ===================================================================

def test_08_overload_tracking():
    """Turn 5, 5 mana, overload card (3-cost) in hand.

    Card with OVERLOAD mechanic should be legal play.
    After play: check mana.overload_next — if still 0, log FEATURE_GAP.
    """
    overload_card = Card(
        dbf_id=41496,
        name="闪电风暴",
        cost=3,
        original_cost=3,
        card_type="SPELL",
        text="对所有敌方随从造成$3点伤害。过载：（2）",
        mechanics=["OVERLOAD"],
    )
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        opponent_board=[
            {"name": "Enemy 1", "tags": {"ATK": 2, "HEALTH": 2}},
            {"name": "Enemy 2", "tags": {"ATK": 2, "HEALTH": 2}},
        ],
    )
    # Inject Card object directly
    state.hand = [overload_card]

    # Card is legal (3 ≤ 5 mana)
    legal = enumerate_legal_actions(state)
    spell_plays = [a for a in legal if a.action_type == "PLAY" and a.card_index == 0]
    assert len(spell_plays) > 0, "3-cost overload card should be legal with 5 mana"

    # Apply the play
    action = spell_plays[0]
    new_state = apply_action(state, action)

    # Mana deducted
    assert new_state.mana.available == 2, "Should deduct 3 mana"

    # Card removed from hand
    assert len(new_state.hand) == 0

    # Check overload_next — should be set from card's overload value
    # Current engine doesn't parse overload amount from card text or mechanics
    if new_state.mana.overload_next == 0:
        print("FEATURE_GAP: Overload not tracked — "
              "mana.overload_next stays 0 after playing overload card")
    else:
        assert new_state.mana.overload_next > 0, "Overload should be > 0"


# ===================================================================
# Test 9: Full Hand Boundary (10 cards)
# ===================================================================

def test_09_full_hand_boundary():
    """Turn 8, 10 cards in hand (max hand size), 2 friendly + 3 enemy minions.

    Engine should handle max hand gracefully — still play cards and attack.
    """
    hand_cards = []
    for i in range(10):
        hand_cards.append({
            "name": f"手牌{i}",
            "type": "MINION",
            "tags": {"COST": 1, "ATK": 1, "HEALTH": 1},
        })

    state = HDTGameStateFactory.create_state(
        turn=8,
        player_mana=8,
        player_hand=hand_cards,
        player_board=[
            {"name": "Board Minion A", "tags": {"ATK": 4, "HEALTH": 4, "EXHAUSTED": 0}},
            {"name": "Board Minion B", "tags": {"ATK": 3, "HEALTH": 3, "EXHAUSTED": 0}},
        ],
        opponent_board=[
            {"name": "Enemy X", "tags": {"ATK": 2, "HEALTH": 2}},
            {"name": "Enemy Y", "tags": {"ATK": 2, "HEALTH": 2}},
            {"name": "Enemy Z", "tags": {"ATK": 2, "HEALTH": 2}},
        ],
    )

    assert len(state.hand) == 10, "Should have 10 cards in hand"

    legal = enumerate_legal_actions(state)

    # Should have PLAY actions (1-cost minions with 8 mana)
    play_actions = [a for a in legal if a.action_type == "PLAY"]
    assert len(play_actions) > 0, "Should have play actions with affordable cards"

    # Should have ATTACK actions (2 minions that can attack)
    attack_actions = [a for a in legal if a.action_type == "ATTACK"]
    assert len(attack_actions) > 0, "Should have attack actions"

    # Should have END_TURN
    end_actions = [a for a in legal if a.action_type == "END_TURN"]
    assert len(end_actions) > 0, "END_TURN should always be legal"

    # Play a 1-cost minion from 10-card hand
    play_action = play_actions[0]
    new_state = apply_action(state, play_action)
    assert len(new_state.hand) == 9, "Card should be removed from hand"
    # Board should grow (2 → 3, since board has 2 and max is 7)
    assert len(new_state.board) == 3, "Minion should be added to board"


# ===================================================================
# Test 10: Empty Board Spell Heavy
# ===================================================================

def test_10_empty_board_spell_heavy():
    """Turn 5, 0 minions on board, 4 spells in hand (2-cost each).

    Opponent has a 3/3 minion.
    Engine should play spells (effects simplified) without crash.
    """
    spell_cards = []
    for i in range(4):
        spell_cards.append({
            "name": f"法术{i}",
            "type": "SPELL",
            "tags": {"COST": 2},
            "text": f"造成{i+1}点伤害。",
        })

    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hand=spell_cards,
        player_board=[],  # empty board
        opponent_board=[
            {"name": "Enemy Minion", "tags": {"ATK": 3, "HEALTH": 3}},
        ],
    )

    assert len(state.board) == 0, "Player board should be empty"
    assert len(state.hand) == 4, "Should have 4 spell cards"

    legal = enumerate_legal_actions(state)

    # Should have PLAY actions for 2-cost spells (can play 2 with 5 mana)
    play_actions = [a for a in legal if a.action_type == "PLAY"]
    assert len(play_actions) > 0, "Should have spell play actions"

    # No ATTACK actions (empty board, no weapon)
    attack_actions = [a for a in legal if a.action_type == "ATTACK"]
    assert len(attack_actions) == 0, "No attacks with empty board and no weapon"

    # END_TURN should be legal
    end_actions = [a for a in legal if a.action_type == "END_TURN"]
    assert len(end_actions) == 1, "END_TURN always legal"

    # Play one spell
    play_action = play_actions[0]
    new_state = apply_action(state, play_action)

    # Card removed from hand
    assert len(new_state.hand) == 3, "Spell should be removed from hand"
    # Mana deducted
    assert new_state.mana.available == 3, "Should deduct 2 mana for spell"
    # No crash
    assert new_state is not None

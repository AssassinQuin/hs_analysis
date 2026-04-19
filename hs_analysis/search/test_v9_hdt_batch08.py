#!/usr/bin/env python3
"""V9 Decision Engine HDT-style Integration Tests — Batch 08

Position-related mechanics and real-game scenarios.

Tests cover:
- Summon token goes to rightmost board position
- OUTCAST card position (leftmost, rightmost, middle) — FEATURE_GAP
- Generated card goes to rightmost hand position
- Taunt blocks face when multiple opponent minions
- Board reindexing after minion kill
- Spell heal hero from low HP (no 30-cap, known from B04)
- Complex multi-mechanic board state evaluation
- Hand card order preserved on play

Tracked features:
- [SUPPORTED] Summon rightmost positioning (board.append)
- [SUPPORTED] Generated card rightmost in hand (hand.append)
- [SUPPORTED] Taunt enforcement with multiple minions
- [SUPPORTED] Board reindexing after death cleanup
- [SUPPORTED] Hand order preservation via pop()
- [FEATURE_GAP] OUTCAST position awareness (B08)
- [FEATURE_GAP] Heal no-cap at 30 HP (B04, confirmed B08)
"""

import pytest

from hs_analysis.search.test_v9_hdt_batch01 import HDTGameStateFactory
from hs_analysis.search.test_v9_hdt_batch02_deck_random import DeckTestGenerator
from hs_analysis.search.rhea_engine import (
    RHEAEngine, Action, apply_action, enumerate_legal_actions,
    next_turn_lethal_check,
)
from hs_analysis.utils.spell_simulator import resolve_effects, EffectApplier
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState, Minion, HeroState, ManaState, OpponentState, Weapon,
)
from hs_analysis.search.lethal_checker import check_lethal, max_damage_bound


# ===================================================================
# Test 1: Summon goes to rightmost board position
# ===================================================================

def test_01_summon_goes_to_rightmost():
    """Board has 3 minions; summon spell adds token at index 3 (rightmost)."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hand=[
            {
                "name": "召唤术",
                "type": "SPELL",
                "text": "召唤一个 2/2 的随从",
                "tags": {"COST": 2},
            },
        ],
        player_board=[
            {"name": "随从A", "tags": {"ATK": 1, "HEALTH": 1, "EXHAUSTED": 0}},
            {"name": "随从B", "tags": {"ATK": 2, "HEALTH": 2, "EXHAUSTED": 0}},
            {"name": "随从C", "tags": {"ATK": 3, "HEALTH": 3, "EXHAUSTED": 0}},
        ],
    )

    # Before: 3 minions on board
    assert len(state.board) == 3
    print(f"  Before: board = [{', '.join(m.name for m in state.board)}]")

    # Play summon spell (index 0 in hand)
    action = Action(action_type="PLAY", card_index=0)
    result = apply_action(state, action)

    # After: 4 minions, new one at index 3 (rightmost)
    assert len(result.board) == 4, (
        f"Expected 4 minions after summon, got {len(result.board)}"
    )
    assert result.board[0].name == "随从A", "Original pos 0 preserved"
    assert result.board[1].name == "随从B", "Original pos 1 preserved"
    assert result.board[2].name == "随从C", "Original pos 2 preserved"

    # New summoned token at rightmost (index 3)
    new_minion = result.board[3]
    print(f"  After: board = [{', '.join(m.name for m in result.board)}]")
    print(f"  New minion at index 3: {new_minion.name}, ATK={new_minion.attack}, HP={new_minion.health}")

    # Summoned minion should have 2/2 stats from the spell text
    assert new_minion.attack == 2, f"Summoned token should have 2 attack, got {new_minion.attack}"
    assert new_minion.health == 2, f"Summoned token should have 2 health, got {new_minion.health}"


# ===================================================================
# Test 2: OUTCAST card at leftmost position
# ===================================================================

def test_02_outcast_card_leftmost_position():
    """OUTCAST card at leftmost hand position (index 0) — bonus should activate.

    FEATURE_GAP: Engine has no position tracking. Card is legal to play
    but OUTCAST bonus is ignored.
    """
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=3,
        player_hand=[
            {
                "name": "伊利达雷研习",
                "type": "SPELL",
                "text": "流放：抽两张牌。造成 1 点伤害。",
                "tags": {"COST": 2},
            },
            {"name": "填充牌A", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌B", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌C", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌D", "type": "SPELL", "tags": {"COST": 1}},
        ],
    )

    # Card is at index 0 (leftmost) — OUTCAST should activate
    print(f"  Hand size: {len(state.hand)}, OUTCAST card at index 0 (leftmost)")

    # Card should be a legal play
    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == 0]
    assert len(play_actions) > 0, "OUTCAST card at leftmost should be legal to play"

    # FEATURE_GAP: Position check not implemented
    # In real HS, this position (index 0) would trigger OUTCAST bonus
    # Engine treats it as a normal spell — no position awareness
    print("  FEATURE_GAP: OUTCAST position bonus not checked (leftmost = should activate)")

    # Verify card can be played (no crash)
    action = play_actions[0]
    result = apply_action(state, action)
    assert len(result.hand) == 4, (
        f"After play, hand should have 4 cards, got {len(result.hand)}"
    )


# ===================================================================
# Test 3: OUTCAST card at rightmost position
# ===================================================================

def test_03_outcast_card_rightmost_position():
    """OUTCAST card at rightmost hand position (last index) — bonus should activate.

    FEATURE_GAP: Same as test_02 — no position tracking.
    """
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=3,
        player_hand=[
            {"name": "填充牌A", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌B", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌C", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌D", "type": "SPELL", "tags": {"COST": 1}},
            {
                "name": "伊利达雷研习",
                "type": "SPELL",
                "text": "流放：抽两张牌。造成 1 点伤害。",
                "tags": {"COST": 2},
            },
        ],
    )

    outcast_idx = len(state.hand) - 1  # index 4 (rightmost)
    print(f"  Hand size: {len(state.hand)}, OUTCAST card at index {outcast_idx} (rightmost)")

    # Card should be a legal play
    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == outcast_idx]
    assert len(play_actions) > 0, "OUTCAST card at rightmost should be legal to play"

    # FEATURE_GAP: Position check not implemented
    print("  FEATURE_GAP: OUTCAST position bonus not checked (rightmost = should activate)")

    # Verify card can be played (no crash)
    result = apply_action(state, play_actions[0])
    assert len(result.hand) == 4, (
        f"After play, hand should have 4 cards, got {len(result.hand)}"
    )


# ===================================================================
# Test 4: OUTCAST card at middle position
# ===================================================================

def test_04_outcast_card_middle_position():
    """OUTCAST card at middle hand position — bonus should NOT activate.

    FEATURE_GAP: Even without position tracking, card is still legal.
    In real HS, middle position means no OUTCAST bonus.
    """
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=3,
        player_hand=[
            {"name": "填充牌A", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌B", "type": "SPELL", "tags": {"COST": 1}},
            {
                "name": "伊利达雷研习",
                "type": "SPELL",
                "text": "流放：抽两张牌。造成 1 点伤害。",
                "tags": {"COST": 2},
            },
            {"name": "填充牌C", "type": "SPELL", "tags": {"COST": 1}},
            {"name": "填充牌D", "type": "SPELL", "tags": {"COST": 1}},
        ],
    )

    outcast_idx = 2  # middle position
    print(f"  Hand size: {len(state.hand)}, OUTCAST card at index {outcast_idx} (middle)")

    # Card should still be a legal play (just without bonus)
    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == outcast_idx]
    assert len(play_actions) > 0, "OUTCAST card at middle should still be legal to play"

    # FEATURE_GAP: No way to distinguish bonus vs no-bonus play
    print("  FEATURE_GAP: Cannot distinguish OUTCAST bonus vs non-bonus play")

    # Verify play works
    result = apply_action(state, play_actions[0])
    assert len(result.hand) == 4


# ===================================================================
# Test 5: Generated card goes to rightmost in hand
# ===================================================================

def test_05_generated_card_rightmost_in_hand():
    """Drawn/generated card goes to rightmost hand position (append behavior)."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hand=[
            {"name": "原有A", "type": "SPELL", "tags": {"COST": 2}},
            {"name": "原有B", "type": "SPELL", "tags": {"COST": 3}},
            {"name": "抽牌术", "type": "SPELL", "text": "抽 1 张牌", "tags": {"COST": 2}},
        ],
    )
    # Default deck_remaining is 15, which is plenty for a draw

    # Before draw: hand has 3 cards
    assert len(state.hand) == 3
    print(f"  Before: hand = [{', '.join(c.name for c in state.hand)}]")

    # Play the draw spell (index 2)
    action = Action(action_type="PLAY", card_index=2)
    result = apply_action(state, action)

    # After: original 2 cards + drawn card at rightmost (index 2)
    assert len(result.hand) == 3, (
        f"After draw: 2 original + 1 drawn = 3, got {len(result.hand)}"
    )

    # Original cards should still be at 0, 1
    assert result.hand[0].name == "原有A", (
        f"hand[0] should be '原有A', got '{result.hand[0].name}'"
    )
    assert result.hand[1].name == "原有B", (
        f"hand[1] should be '原有B', got '{result.hand[1].name}'"
    )

    # Drawn card at rightmost (index 2)
    drawn = result.hand[2]
    print(f"  After: hand = [{', '.join(c.name for c in result.hand)}]")
    print(f"  Drawn card at index 2: {drawn.name}")

    # EffectApplier.apply_draw creates a Card named "Drawn Card"
    assert drawn.name == "Drawn Card", (
        f"Rightmost card should be 'Drawn Card', got '{drawn.name}'"
    )


# ===================================================================
# Test 6: Taunt blocks face when multiple opponent minions
# ===================================================================

def test_06_taunt_blocks_face_when_multiple_minions():
    """Opponent has taunt + non-taunt minions: only taunt is targetable."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_board=[
            {"name": "攻方4/4", "tags": {"ATK": 4, "HEALTH": 4, "EXHAUSTED": 0}},
        ],
        opponent_hp=20,
        opponent_armor=0,
        opponent_board=[
            {"name": "嘲讽3/3", "tags": {"ATK": 3, "HEALTH": 3, "TAUNT": 1}},
            {"name": "普通5/5", "tags": {"ATK": 5, "HEALTH": 5}},
            {"name": "普通2/2", "tags": {"ATK": 2, "HEALTH": 2}},
        ],
    )

    actions = enumerate_legal_actions(state)
    attack_actions = [a for a in actions if a.action_type == "ATTACK"]

    print(f"  Total legal actions: {len(actions)}")
    print(f"  Attack actions: {len(attack_actions)}")
    for a in attack_actions:
        print(f"    source={a.source_index} → target={a.target_index}")

    # All ATTACK actions should only target the taunt minion (target_index=1,
    # which is 1-indexed for opponent board position 0)
    assert len(attack_actions) > 0, "Should have at least one attack action"

    # Taunt is at opponent board index 0 → target_index = 1 (1-indexed)
    for a in attack_actions:
        assert a.target_index == 1, (
            f"With taunt present, all attacks should target taunt (target_index=1), "
            f"got target_index={a.target_index}"
        )

    # No attacks on face (target_index=0) or non-taunt minions
    face_attacks = [a for a in attack_actions if a.target_index == 0]
    assert len(face_attacks) == 0, "Should not be able to attack face when taunt is up"


# ===================================================================
# Test 7: Attack after kill reindexes opponent board
# ===================================================================

def test_07_attack_after_kill_reindexes():
    """Kill index 0, board reindexes, second attack targets correctly."""
    state = HDTGameStateFactory.create_state(
        turn=6,
        player_mana=6,
        player_board=[
            {"name": "大怪5/5", "tags": {"ATK": 5, "HEALTH": 5, "EXHAUSTED": 0}},
        ],
        opponent_hp=20,
        opponent_armor=0,
        opponent_board=[
            {"name": "小怪2/2", "tags": {"ATK": 2, "HEALTH": 2}},
            {"name": "中怪4/4", "tags": {"ATK": 4, "HEALTH": 4}},
            {"name": "微怪1/1", "tags": {"ATK": 1, "HEALTH": 1}},
        ],
    )

    print(f"  Initial opponent board: [{', '.join(m.name for m in state.opponent.board)}]")
    print(f"    Index 0: {state.opponent.board[0].name} (2/2)")
    print(f"    Index 1: {state.opponent.board[1].name} (4/4)")
    print(f"    Index 2: {state.opponent.board[2].name} (1/1)")

    # Step 1: Attack index 0 (小怪2/2) — target_index=1 (1-indexed)
    # 5 damage kills 2/2 → death cleanup removes it
    action1 = Action(
        action_type="ATTACK",
        source_index=0,
        target_index=1,  # opponent board index 0 → target_index=1
    )
    result1 = apply_action(state, action1)

    # After kill: board should be [中怪4/4, 微怪1/1] — reindexed
    assert len(result1.opponent.board) == 2, (
        f"After killing index 0, opponent should have 2 minions, "
        f"got {len(result1.opponent.board)}"
    )
    print(f"  After kill index 0: [{', '.join(m.name for m in result1.opponent.board)}]")
    assert result1.opponent.board[0].name == "中怪4/4", (
        f"After reindex, index 0 should be '中怪4/4', "
        f"got '{result1.opponent.board[0].name}'"
    )
    assert result1.opponent.board[1].name == "微怪1/1", (
        f"After reindex, index 1 should be '微怪1/1', "
        f"got '{result1.opponent.board[1].name}'"
    )

    # Step 2: Attack the new index 0 (中怪4/4, was at index 1)
    # target_index=1 (still 1-indexed for new index 0)
    action2 = Action(
        action_type="ATTACK",
        source_index=0,
        target_index=1,
    )
    result2 = apply_action(result1, action2)

    # 中怪4/4 takes 5 → 4-5 = -1 → dead
    # 微怪1/1 remains
    assert len(result2.opponent.board) == 1, (
        f"After second kill, opponent should have 1 minion, "
        f"got {len(result2.opponent.board)}"
    )
    print(f"  After kill reindexed index 0: [{', '.join(m.name for m in result2.opponent.board)}]")
    assert result2.opponent.board[0].name == "微怪1/1", (
        f"Remaining minion should be '微怪1/1', "
        f"got '{result2.opponent.board[0].name}'"
    )
    assert result2.opponent.board[0].health == 1, "微怪 should still be at 1 HP"


# ===================================================================
# Test 8: Spell heal hero from low HP (no 30-cap)
# ===================================================================

def test_08_spell_heal_hero_from_low_hp():
    """Heal spell restores HP without capping at 30 (known gap from B04)."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hp=10,
        player_hand=[
            {
                "name": "治疗术",
                "type": "SPELL",
                "text": "恢复 8 点生命值",
                "tags": {"COST": 2},
            },
        ],
    )

    print(f"  Before heal: player HP = {state.hero.hp}")

    # Resolve heal effect directly
    heal_card = Card(
        dbf_id=9998,
        name="治疗术",
        cost=2,
        card_type="SPELL",
        text="恢复 8 点生命值",
    )
    result = resolve_effects(state, heal_card)

    # HP should be 10 + 8 = 18
    assert result.hero.hp == 18, (
        f"Expected HP 18 (10+8), got {result.hero.hp}"
    )
    print(f"  After heal: player HP = {result.hero.hp}")

    # FEATURE_GAP: No cap at 30 (confirmed from B04)
    # If HP was 25 and heal was 8 → would be 33, exceeding 30
    state_high = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hp=25,
    )
    result_high = resolve_effects(state_high, heal_card)
    print(f"  HP 25 + heal 8 = {result_high.hero.hp} (no cap at 30)")
    assert result_high.hero.hp == 33, (
        f"Known gap: heal should cap at 30 but engine gives {result_high.hero.hp}"
    )


# ===================================================================
# Test 9: Complex board state evaluation
# ===================================================================

def test_09_complex_board_state_evaluation():
    """Complex state with taunt, divine shield, rush, weapon — no crash, valid fitness."""
    state = HDTGameStateFactory.create_state(
        turn=8,
        player_mana=8,
        player_hp=20,
        player_weapon={"name": "战刃", "attack": 3, "durability": 2},
        player_board=[
            {
                "name": "嘲讽4/4",
                "tags": {"ATK": 4, "HEALTH": 4, "TAUNT": 1, "EXHAUSTED": 0},
            },
            {
                "name": "圣盾3/1",
                "tags": {
                    "ATK": 3, "HEALTH": 1,
                    "DIVINE_SHIELD": 1, "EXHAUSTED": 0,
                },
            },
            {
                "name": "突袭2/2",
                "tags": {"ATK": 2, "HEALTH": 2, "RUSH": 1, "EXHAUSTED": 0},
            },
        ],
        opponent_hp=12,
        opponent_armor=0,
        opponent_board=[
            {"name": "嘲讽5/5", "tags": {"ATK": 5, "HEALTH": 5, "TAUNT": 1}},
            {"name": "普通3/3", "tags": {"ATK": 3, "HEALTH": 3}},
            {"name": "普通2/2", "tags": {"ATK": 2, "HEALTH": 2}},
        ],
    )

    print(f"  Player: [{', '.join(m.name for m in state.board)}] + weapon 3/2")
    print(f"  Opponent: [{', '.join(m.name for m in state.opponent.board)}], 12 HP")

    # Run full engine search
    engine = RHEAEngine(
        pop_size=20,
        max_gens=50,
        time_limit=150.0,
    )
    result = engine.search(state)

    # Should not crash
    assert result is not None, "Engine should return a result"

    # Should have a best chromosome (list of Actions)
    best = result.best_chromosome
    assert best is not None, "Should have a best chromosome"

    # Should have a fitness value (stored on SearchResult, not chromosome)
    fitness = result.best_fitness
    assert fitness is not None, "Should have best_fitness on result"
    print(f"  Best fitness: {fitness}")

    # max_damage_bound should account for board + weapon
    bound = max_damage_bound(state)
    # 4 (taunt) + 3 (shield) + 2 (rush) + 3 (weapon) = 12 from minions/weapon
    assert bound >= 12, (
        f"max_damage_bound should be >= 12 (board + weapon), got {bound}"
    )
    print(f"  max_damage_bound: {bound}")

    # With 12 opponent HP and 12+ bound, lethal should be possible
    # (assuming taunt can be cleared through combat)
    lethal = check_lethal(state, time_budget_ms=50.0)
    print(f"  Lethal found: {lethal is not None}")

    # Legal actions should include attacks and end turn
    actions = enumerate_legal_actions(state)
    action_types = set(a.action_type for a in actions)
    print(f"  Legal action types: {action_types}")

    assert "ATTACK" in action_types, "Should have attack actions"
    assert "END_TURN" in action_types, "Should have END_TURN action"

    # Verify taunt enforcement: attacks should only target opponent taunts
    attack_actions = [a for a in actions if a.action_type == "ATTACK"]
    for a in attack_actions:
        # target_index=1 means opponent board index 0 (the 5/5 taunt)
        assert a.target_index == 1, (
            f"With taunt present, attacks must target taunt (target_index=1), "
            f"got {a.target_index}"
        )


# ===================================================================
# Test 10: Hand card order preserved on play
# ===================================================================

def test_10_hand_card_order_preserved_on_play():
    """Playing card from middle of hand preserves order of remaining cards."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_hand=[
            {"name": "卡牌A", "type": "SPELL", "tags": {"COST": 3}},
            {"name": "卡牌B", "type": "SPELL", "tags": {"COST": 2}},
            {"name": "卡牌C", "type": "SPELL", "tags": {"COST": 4}},
        ],
    )

    # Verify initial order
    assert state.hand[0].name == "卡牌A"
    assert state.hand[1].name == "卡牌B"
    assert state.hand[2].name == "卡牌C"
    print(f"  Before: [{', '.join(c.name for c in state.hand)}]")

    # Play card at index 1 (卡牌B, cost=2)
    action = Action(action_type="PLAY", card_index=1)
    result = apply_action(state, action)

    # After: hand should be [卡牌A, 卡牌C] — A stays at 0, C shifts to 1
    assert len(result.hand) == 2, (
        f"After play, hand should have 2 cards, got {len(result.hand)}"
    )
    print(f"  After play index 1: [{', '.join(c.name for c in result.hand)}]")

    assert result.hand[0].name == "卡牌A", (
        f"hand[0] should be '卡牌A', got '{result.hand[0].name}'"
    )
    assert result.hand[1].name == "卡牌C", (
        f"hand[1] should be '卡牌C' (shifted from index 2), "
        f"got '{result.hand[1].name}'"
    )

    # Original state unchanged
    assert len(state.hand) == 3, "Original state should not be mutated"
    assert state.hand[1].name == "卡牌B"

#!/usr/bin/env python3
"""V9 Decision Engine HDT-style Integration Tests — Batch 09

Board position as a decision variable and death cleanup + deathrattle position inheritance.

Key discovery: the engine ALREADY supports position-aware PLAY actions:
- enumerate_legal_actions generates one action per valid board position
- apply_action uses insert(pos, minion) not append
- The RHEA search can naturally explore different placement positions

Tests cover:
- PLAY action generates correct position variants (empty board, 3-minion board)
- Insert at leftmost, between, rightmost positions
- Death cleanup reindexes surviving minions correctly
- Deathrattle position inheritance gap (FEATURE_GAP)
- RHEA engine explores positions via search
- Full board position boundary (7 minions)
- Multi-death reindex chain (sequential combat)

Tracked features:
- [SUPPORTED] Position-aware enumerate_legal_actions (0..len(board) inclusive)
- [SUPPORTED] Position-aware apply_action (insert at position)
- [SUPPORTED] Death cleanup reindexing via list comprehension
- [SUPPORTED] board_full() boundary check
- [FEATURE_GAP] Deathrattle position inheritance (B09)
"""

import pytest

from hs_analysis.search.rhea_engine import (
    RHEAEngine, Action, apply_action, enumerate_legal_actions,
)
from hs_analysis.search.game_state import (
    GameState, Minion, HeroState, ManaState, OpponentState, Weapon,
)
from hs_analysis.models.card import Card
from hs_analysis.search.test_v9_hdt_batch01 import HDTGameStateFactory


# ===================================================================
# Helpers
# ===================================================================

def _make_minion(name: str, attack: int, health: int, **kwargs) -> Minion:
    """Create a minion with given stats."""
    return Minion(
        name=name,
        attack=attack,
        health=health,
        max_health=health,
        can_attack=kwargs.get("can_attack", True),
        has_taunt=kwargs.get("has_taunt", False),
        has_charge=kwargs.get("has_charge", False),
        has_rush=kwargs.get("has_rush", False),
    )


def _make_minion_card(name: str, cost: int, attack: int, health: int,
                      mechanics=None) -> Card:
    """Create a MINION card."""
    return Card(
        name=name,
        cost=cost,
        original_cost=cost,
        card_type="MINION",
        attack=attack,
        health=health,
        mechanics=mechanics or [],
    )


def _make_state_with_board(board_minions, hand_cards=None, mana=10):
    """Build a minimal GameState with given board and hand."""
    board = [_make_minion(n, a, h) for n, a, h in board_minions]
    hand = hand_cards or []
    return GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=mana, max_mana=mana),
        board=board,
        hand=hand,
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


# ===================================================================
# Test 1: Play minion generates position variants (empty board)
# ===================================================================

def test_01_play_minion_generates_position_variants():
    """Empty board + one 3/3 minion in hand → exactly ONE PLAY action with position=0."""
    card = _make_minion_card("测试随从", 3, 3, 3)
    state = _make_state_with_board([], [card], mana=10)

    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == 0]

    # Empty board: only position=0 is valid
    assert len(play_actions) == 1, (
        f"Expected exactly 1 PLAY action on empty board, got {len(play_actions)}"
    )
    assert play_actions[0].position == 0, (
        f"Expected position=0 on empty board, got position={play_actions[0].position}"
    )

    # Verify Action has position field
    assert hasattr(play_actions[0], "position"), "Action must have a 'position' field"
    print(f"  Empty board: 1 PLAY action, position={play_actions[0].position} ✅")


# ===================================================================
# Test 2: Play minion with 3 existing minions → 4 position variants
# ===================================================================

def test_02_play_minion_three_existing_positions():
    """Board: [A, B, C] (3 minions). Hand: one 3/3.
    
    enumerate_legal_actions should generate 4 PLAY positions:
    [0, 1, 2, 3] — left of A, between A-B, between B-C, right of C.
    """
    card = _make_minion_card("新随从", 3, 3, 3)
    state = _make_state_with_board(
        [("随从A", 2, 2), ("随从B", 3, 3), ("随从C", 4, 4)],
        [card],
        mana=10,
    )

    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == 0]
    positions = sorted(a.position for a in play_actions)

    assert positions == [0, 1, 2, 3], (
        f"Expected positions [0,1,2,3], got {positions}"
    )
    print(f"  3-minion board: {len(play_actions)} PLAY actions at positions {positions} ✅")


# ===================================================================
# Test 3: Play minion insert at leftmost (position=0)
# ===================================================================

def test_03_play_minion_insert_at_leftmost():
    """Board: [3/3 A, 4/4 B]. Play new 2/2 at position=0 → [2/2 new, 3/3 A, 4/4 B]."""
    card = _make_minion_card("新随从", 2, 2, 2)
    state = _make_state_with_board(
        [("随从A", 3, 3), ("随从B", 4, 4)],
        [card],
        mana=10,
    )

    action = Action(action_type="PLAY", card_index=0, position=0)
    result = apply_action(state, action)

    assert len(result.board) == 3, (
        f"Expected 3 minions after play, got {len(result.board)}"
    )
    # Leftmost = new minion
    assert result.board[0].attack == 2 and result.board[0].health == 2, (
        f"Expected new minion (2/2) at idx 0, got ({result.board[0].attack}/{result.board[0].health})"
    )
    assert result.board[1].attack == 3, f"Expected A (3/3) at idx 1, got atk={result.board[1].attack}"
    assert result.board[2].attack == 4, f"Expected B (4/4) at idx 2, got atk={result.board[2].attack}"

    print(f"  Insert at pos 0: [{result.board[0].name}, {result.board[1].name}, {result.board[2].name}]")
    print(f"  Attack values: [{result.board[0].attack}, {result.board[1].attack}, {result.board[2].attack}] ✅")


# ===================================================================
# Test 4: Play minion insert between (position=1)
# ===================================================================

def test_04_play_minion_insert_between():
    """Board: [3/3 A, 4/4 B]. Play new 2/2 at position=1 → [3/3 A, 2/2 new, 4/4 B]."""
    card = _make_minion_card("新随从", 2, 2, 2)
    state = _make_state_with_board(
        [("随从A", 3, 3), ("随从B", 4, 4)],
        [card],
        mana=10,
    )

    action = Action(action_type="PLAY", card_index=0, position=1)
    result = apply_action(state, action)

    assert len(result.board) == 3, (
        f"Expected 3 minions after play, got {len(result.board)}"
    )
    assert result.board[0].attack == 3, f"Expected A (3/3) at idx 0"
    assert result.board[1].attack == 2 and result.board[1].health == 2, (
        f"Expected new (2/2) at idx 1, got ({result.board[1].attack}/{result.board[1].health})"
    )
    assert result.board[2].attack == 4, f"Expected B (4/4) at idx 2"

    print(f"  Insert at pos 1: attack values = [{result.board[0].attack}, {result.board[1].attack}, {result.board[2].attack}] ✅")


# ===================================================================
# Test 5: Play minion insert at rightmost (position=2)
# ===================================================================

def test_05_play_minion_insert_at_rightmost():
    """Board: [3/3 A, 4/4 B]. Play new 2/2 at position=2 → [3/3 A, 4/4 B, 2/2 new]."""
    card = _make_minion_card("新随从", 2, 2, 2)
    state = _make_state_with_board(
        [("随从A", 3, 3), ("随从B", 4, 4)],
        [card],
        mana=10,
    )

    action = Action(action_type="PLAY", card_index=0, position=2)
    result = apply_action(state, action)

    assert len(result.board) == 3, (
        f"Expected 3 minions after play, got {len(result.board)}"
    )
    assert result.board[0].attack == 3, f"Expected A (3/3) at idx 0"
    assert result.board[1].attack == 4, f"Expected B (4/4) at idx 1"
    assert result.board[2].attack == 2 and result.board[2].health == 2, (
        f"Expected new (2/2) at idx 2, got ({result.board[2].attack}/{result.board[2].health})"
    )

    print(f"  Insert at pos 2: attack values = [{result.board[0].attack}, {result.board[1].attack}, {result.board[2].attack}] ✅")


# ===================================================================
# Test 6: Death cleanup reindexes correctly
# ===================================================================

def test_06_death_cleanup_reindexes_correctly():
    """Opponent board: [2/2, 3/3, 1/1]. Attack and kill idx 1 (3/3 dies).
    
    After death cleanup: board should be [2/2 at idx 0, 1/1 at idx 1].
    """
    # Build state with 3/3 attacker on player board and 3 enemy minions
    state = GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        board=[_make_minion("攻击者", 3, 3, can_attack=True)],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                _make_minion("敌方A", 2, 2),
                _make_minion("敌方B", 3, 3),  # idx 1, will die
                _make_minion("敌方C", 1, 1),
            ],
        ),
    )

    # Attack: player minion (idx 0) → enemy minion idx 1 (target_index=2, 1-indexed)
    action = Action(action_type="ATTACK", source_index=0, target_index=2)
    result = apply_action(state, action)

    # EnemyB (3/3) attacked by 3/3 → health=0, dies. EnemyB deals 3 to attacker → attacker health=0, dies too
    # Enemy board: [敌方A (2/2), 敌方C (1/1)] after cleanup
    assert len(result.opponent.board) == 2, (
        f"Expected 2 enemy minions after kill, got {len(result.opponent.board)}"
    )
    assert result.opponent.board[0].attack == 2, (
        f"Expected 敌方A (2/2) at idx 0, got atk={result.opponent.board[0].attack}"
    )
    assert result.opponent.board[1].attack == 1, (
        f"Expected 敌方C (1/1) at idx 1, got atk={result.opponent.board[1].attack}"
    )
    # Verify surviving minion shifted left (was idx 2, now idx 1)
    assert result.opponent.board[1].name == "敌方C", (
        f"Expected '敌方C' at idx 1, got '{result.opponent.board[1].name}'"
    )

    print(f"  After kill idx 1: enemy board = [{', '.join(m.name for m in result.opponent.board)}]")
    print(f"  Surviving minion shifted left: 敌方C now at idx 1 ✅")


# ===================================================================
# Test 7: Deathrattle position inheritance gap
# ===================================================================

def test_07_deathrattle_position_inheritance_gap():
    """Board: [A, deathrattle_minion (idx 1), B (idx 2)].
    
    deathrattle_minion dies → should summon token at idx 1 (inherited position).
    
    FEATURE_GAP: Current engine uses list comprehension to remove dead minions,
    so [A, B] with B at idx 1. No deathrattle effect fires.
    Test documents this gap — the test PASSES because we're testing current behavior.
    """
    dr_minion = _make_minion("亡语随从", 3, 1)
    dr_minion.enchantments = ["DEATHRATTLE"]

    state = GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        board=[_make_minion("随从A", 2, 2), dr_minion, _make_minion("随从B", 4, 4)],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[_make_minion("敌方攻击者", 5, 5, can_attack=True)],
        ),
    )

    # Simulate death: set deathrattle minion health to 0
    state_copy = state.copy()
    state_copy.board[1].health = 0

    # Current engine cleanup: list comprehension removes dead minions
    surviving = [m for m in state_copy.board if m.health > 0]

    assert len(surviving) == 2, f"Expected 2 survivors, got {len(surviving)}"
    assert surviving[0].name == "随从A", f"Expected 随从A at idx 0, got {surviving[0].name}"
    assert surviving[1].name == "随从B", f"Expected 随从B at idx 1, got {surviving[1].name}"

    # FEATURE_GAP: deathrattle should have summoned a token at idx 1 (the gap position)
    # Current behavior: [随从A, 随从B] with no deathrattle token
    print(f"  FEATURE_GAP: deathrattle position inheritance not implemented")
    print(f"  Current behavior: surviving = [{', '.join(m.name for m in surviving)}]")
    print(f"  Expected (real HS): [随从A, <deathrattle token>, 随从B] at inherited position idx 1")
    print(f"  Gap: no death effect fires, no token summoned at gap position ⚠️")


# ===================================================================
# Test 8: Engine chooses position via search
# ===================================================================

def test_08_engine_chooses_position_via_search():
    """Board: [2/2 taunt]. Hand: one 4/4 minion, 4 mana.
    
    Run RHEAEngine.search() with small params.
    Search explores positions [0, 1] for the play action.
    Both positions are valid — engine can choose either.
    Verify result.best_chromosome contains a PLAY action.
    """
    card = _make_minion_card("强力随从", 4, 4, 4)
    taunt_minion = _make_minion("嘲讽随从", 2, 2, has_taunt=True)

    state = GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        board=[taunt_minion],
        hand=[card],
        opponent=OpponentState(hero=HeroState(hp=30)),
    )

    engine = RHEAEngine(pop_size=15, max_gens=30, time_limit=100.0)
    result = engine.search(state)

    # Search must return valid result
    assert result is not None, "Search returned None"
    assert isinstance(result.best_chromosome, list), "best_chromosome must be a list"

    # Verify at least one PLAY action in best chromosome
    play_actions = [a for a in result.best_chromosome if a.action_type == "PLAY"]
    assert len(play_actions) >= 1, (
        f"Expected at least 1 PLAY action in best chromosome, got {play_actions}"
    )

    # The PLAY action should have a valid position (0 or 1)
    for pa in play_actions:
        assert pa.position in (0, 1), (
            f"Expected position 0 or 1 for PLAY on 1-minion board, got {pa.position}"
        )

    print(f"  Search result: {len(result.best_chromosome)} actions in best chromosome")
    print(f"  PLAY actions: {[(a.card_index, a.position) for a in play_actions]}")
    print(f"  Fitness: {result.best_fitness:+.2f}")
    print(f"  Engine explored positions [0, 1] — chose position(s) above ✅")


# ===================================================================
# Test 9: Position matters for full board (7 minions)
# ===================================================================

def test_09_position_matters_for_full_board():
    """Board: 6 minions (almost full). Hand: one 3/3 minion.
    
    enumerate_legal_actions should generate 7 PLAY positions (0 through 6).
    Play at position 3 → board becomes 7 minions, new one in the middle.
    board_full() returns True after.
    """
    card = _make_minion_card("补充随从", 3, 3, 3)
    board_minions = [
        (f"随从{i}", i + 1, i + 2) for i in range(6)
    ]
    state = _make_state_with_board(board_minions, [card], mana=10)

    # 6 minions on board → 7 position variants (0..6)
    assert len(state.board) == 6, f"Expected 6 initial board minions, got {len(state.board)}"
    assert not state.board_full(), "Board should NOT be full with 6 minions"

    actions = enumerate_legal_actions(state)
    play_actions = [a for a in actions if a.action_type == "PLAY" and a.card_index == 0]
    positions = sorted(a.position for a in play_actions)

    assert positions == [0, 1, 2, 3, 4, 5, 6], (
        f"Expected 7 positions [0..6], got {positions}"
    )

    # Play at position 3 (middle)
    action = Action(action_type="PLAY", card_index=0, position=3)
    result = apply_action(state, action)

    assert len(result.board) == 7, f"Expected 7 minions after play, got {len(result.board)}"
    assert result.board_full(), "Board should be full with 7 minions"

    # Verify new minion is in the middle (idx 3)
    assert result.board[3].attack == 3 and result.board[3].health == 3, (
        f"Expected new 3/3 at idx 3, got ({result.board[3].attack}/{result.board[3].health})"
    )

    print(f"  6-minion board: {len(play_actions)} position variants {positions}")
    print(f"  After play at pos 3: board size = {len(result.board)}, board_full = {result.board_full()}")
    print(f"  New minion at idx 3: ({result.board[3].attack}/{result.board[3].health}) ✅")


# ===================================================================
# Test 10: Multi-death reindex chain (sequential combat)
# ===================================================================

def test_10_multi_death_reindex_chain():
    """Opponent board: [2/1 at idx 0, 3/1 at idx 1, 4/2 at idx 2, 1/1 at idx 3].
    
    Use direct combat:
    1) Attack with 3/3 into 2/1 (idx 0) → 2/1 dies, reindex: [3/1, 4/2, 1/1]
    2) Attack with another 3/3 into 3/1 (now idx 0) → 3/1 dies, reindex: [4/2, 1/1]
    
    Verify step-by-step reindexing after each kill.
    """
    # Player board: two 3/3 attackers
    state = GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        board=[
            _make_minion("攻击者A", 3, 3, can_attack=True),
            _make_minion("攻击者B", 3, 3, can_attack=True),
        ],
        hand=[],
        opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                _make_minion("敌方_2_1", 2, 1),  # idx 0
                _make_minion("敌方_3_1", 3, 1),  # idx 1
                _make_minion("敌方_4_2", 4, 2),  # idx 2
                _make_minion("敌方_1_1", 1, 1),  # idx 3
            ],
        ),
    )

    # Step 1: Attack with 攻击者A (idx 0) → 敌方_2_1 (target_index=1, 1-indexed)
    print(f"  Initial enemy board: [{', '.join(f'{m.name}({m.attack}/{m.health})' for m in state.opponent.board)}]")

    action1 = Action(action_type="ATTACK", source_index=0, target_index=1)
    result1 = apply_action(state, action1)

    # 2/1 takes 3 damage → health=-2 → dies
    # 3/3 takes 2 counter-damage → health=1 → survives
    # Enemy board reindexes: [3/1 (was idx1), 4/2 (was idx2), 1/1 (was idx3)]
    assert len(result1.opponent.board) == 3, (
        f"After first kill: expected 3 enemy minions, got {len(result1.opponent.board)}"
    )
    assert result1.opponent.board[0].name == "敌方_3_1", (
        f"After reindex: idx 0 should be 敌方_3_1, got {result1.opponent.board[0].name}"
    )
    assert result1.opponent.board[1].name == "敌方_4_2", (
        f"After reindex: idx 1 should be 敌方_4_2, got {result1.opponent.board[1].name}"
    )
    assert result1.opponent.board[2].name == "敌方_1_1", (
        f"After reindex: idx 2 should be 敌方_1_1, got {result1.opponent.board[2].name}"
    )
    print(f"  Step 1: killed 敌方_2_1 → enemy board reindexed to "
          f"[{', '.join(m.name for m in result1.opponent.board)}]")

    # Step 2: Attack with 攻击者B (now idx 0 — 攻击者A survived with 1 HP)
    # Target: 敌方_3_1 (now at idx 0, target_index=1)
    # Note: After first attack, source (攻击者A) has health=1, still at board[0].
    # But can_attack was set to False. 攻击者B is at board[1] and can attack.
    action2 = Action(action_type="ATTACK", source_index=1, target_index=1)
    result2 = apply_action(result1, action2)

    # 3/1 takes 3 damage → health=-2 → dies
    # 3/3 takes 3 counter-damage → health=0 → also dies!
    # So friendly board: [攻击者A (1HP)] (攻击者B died from counter)
    # Enemy board reindexes: [4/2, 1/1]
    assert len(result2.opponent.board) == 2, (
        f"After second kill: expected 2 enemy minions, got {len(result2.opponent.board)}"
    )
    assert result2.opponent.board[0].name == "敌方_4_2", (
        f"After reindex: idx 0 should be 敌方_4_2, got {result2.opponent.board[0].name}"
    )
    assert result2.opponent.board[1].name == "敌方_1_1", (
        f"After reindex: idx 1 should be 敌方_1_1, got {result2.opponent.board[1].name}"
    )

    print(f"  Step 2: killed 敌方_3_1 → enemy board reindexed to "
          f"[{', '.join(m.name for m in result2.opponent.board)}]")
    print(f"  Friendly survivors: {len(result2.board)} "
          f"[{', '.join(f'{m.name}({m.health}HP)' for m in result2.board)}]")

    # Verify the 4/2 minion survived both waves
    surviving_4_2 = result2.opponent.board[0]
    assert surviving_4_2.attack == 4 and surviving_4_2.health == 2, (
        f"Expected 敌方_4_2 unchanged (4/2), got ({surviving_4_2.attack}/{surviving_4_2.health})"
    )

    print(f"  Multi-death reindex chain verified: 4 enemies → 3 → 2 ✅")

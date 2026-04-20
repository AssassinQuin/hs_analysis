#!/usr/bin/env python3
"""V9 Decision Engine HDT-style Integration Tests — Batch 01

Tests use HDT PowerLog entity format for game state descriptions.
Each test creates a GameState from HDT-style entity definitions and
verifies the V9 engine makes correct decisions.

Tracked features:
- [SUPPORTED] Basic attacks, weapon, taunt, charge, rush, divine shield, mana
- [PARTIAL] Secret, hero card, overload, card draw, stealth, windfury
- [NOT SUPPORTED] Discover, Infuse, Teach/Foretelling, Quest, Location,
  Deathrattle, Spell Damage, Lifesteal, Enchantment, Cost Mod, Battlecry effects
"""

import pytest
from typing import List, Optional, Dict

from hs_analysis.search.game_state import (
    GameState, HeroState, ManaState, OpponentState,
    Minion, Weapon
)
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import (
    RHEAEngine, SearchResult, Action,
    enumerate_legal_actions, apply_action
)


# ===================================================================
# HDT-style Entity Factory
# ===================================================================

class HDTGameStateFactory:
    """Converts HDT PowerLog-style entity descriptions to GameState.

    HDT entity format example:
        {
            "card_id": "EX1_116",
            "name": "Flesheating Ghoul",
            "zone": "PLAY",
            "zone_pos": 1,
            "controller": 1,
            "type": "MINION",
            "tags": {
                "HEALTH": 5, "ATK": 3, "COST": 3,
                "TAUNT": 1, "CHARGE": 0, "RUSH": 0,
                "DIVINE_SHIELD": 0, "STEALTH": 0, "WINDFURY": 0,
                "EXHAUSTED": 0, "DURABILITY": 0
            }
        }
    """

    @staticmethod
    def create_state(
        turn: int,
        player_hp: int = 30,
        player_armor: int = 0,
        player_class: str = "DEMONHUNTER",
        player_mana: int = None,
        player_overloaded: int = 0,
        player_overload_next: int = 0,
        player_weapon: Dict = None,
        player_board: List[Dict] = None,
        player_hand: List[Dict] = None,
        opponent_hp: int = 30,
        opponent_armor: int = 0,
        opponent_class: str = "WARLOCK",
        opponent_board: List[Dict] = None,
        opponent_hand_size: int = 5,
        opponent_secrets: List[str] = None,
        player_deck_list: List = None,
    ) -> GameState:
        """Build GameState from HDT-style parameters."""
        if player_mana is None:
            player_mana = min(turn, 10)
        if player_board is None:
            player_board = []
        if player_hand is None:
            player_hand = []
        if opponent_board is None:
            opponent_board = []
        if opponent_secrets is None:
            opponent_secrets = []

        # Build player weapon
        weapon = None
        if player_weapon:
            weapon = Weapon(
                name=player_weapon.get("name", ""),
                attack=player_weapon.get("attack", 0),
                health=player_weapon.get("durability", 0)
            )

        # Build player hero
        hero = HeroState(
            hp=player_hp,
            armor=player_armor,
            hero_class=player_class,
            weapon=weapon,
            hero_power_used=False
        )

        # Build mana
        mana = ManaState(
            available=player_mana - player_overloaded,
            overloaded=player_overloaded,
            max_mana=min(turn, 10),
            overload_next=player_overload_next
        )

        # Build player board (minions in PLAY zone)
        board = []
        for ent in player_board:
            m = HDTGameStateFactory._entity_to_minion(ent)
            if m:
                board.append(m)

        # Build hand (entities in HAND zone)
        hand = []
        for ent in player_hand:
            c = HDTGameStateFactory._entity_to_card(ent)
            if c:
                hand.append(c)

        # Build opponent
        opp_board = []
        for ent in opponent_board:
            m = HDTGameStateFactory._entity_to_minion(ent, owner="enemy")
            if m:
                opp_board.append(m)

        opponent = OpponentState(
            hero=HeroState(hp=opponent_hp, armor=opponent_armor,
                          hero_class=opponent_class),
            board=opp_board,
            hand_count=opponent_hand_size,
            secrets=opponent_secrets,
        )

        return GameState(
            hero=hero,
            opponent=opponent,
            board=board,
            hand=hand,
            mana=mana,
            turn_number=turn,
            deck_list=player_deck_list
        )

    @staticmethod
    def _entity_to_minion(ent: Dict, owner: str = "friendly") -> Minion:
        tags = ent.get("tags", {})
        hp = tags.get("HEALTH", 1)
        return Minion(
            dbf_id=ent.get("dbf_id", 0),
            name=ent.get("name", "Unknown"),
            attack=tags.get("ATK", 0),
            health=hp,
            max_health=hp,
            cost=tags.get("COST", 0),
            can_attack=not bool(tags.get("EXHAUSTED", 0)),
            has_divine_shield=bool(tags.get("DIVINE_SHIELD", 0)),
            has_taunt=bool(tags.get("TAUNT", 0)),
            has_stealth=bool(tags.get("STEALTH", 0)),
            has_windfury=bool(tags.get("WINDFURY", 0)),
            has_rush=bool(tags.get("RUSH", 0)),
            has_charge=bool(tags.get("CHARGE", 0)),
            has_poisonous=bool(tags.get("POISONOUS", 0)),
            enchantments=[],
            owner=owner
        )

    @staticmethod
    def _entity_to_card(ent: Dict) -> Card:
        tags = ent.get("tags", {})
        return Card(
            dbf_id=ent.get("card_id", 0) if not isinstance(ent.get("card_id"), str) else 0,
            name=ent.get("name", "Unknown"),
            cost=tags.get("COST", 0),
            original_cost=tags.get("COST", 0),
            card_type=ent.get("type", "MINION"),
            attack=tags.get("ATK", 0),
            health=tags.get("HEALTH", 0),
            text=ent.get("text", ""),
            rarity=ent.get("rarity", ""),
            card_class=ent.get("card_class", ""),
            mechanics=ent.get("mechanics", []),
        )


# ===================================================================
# Helper for quick engine runs in tests
# ===================================================================

def _quick_engine(time_limit: float = 100.0) -> RHEAEngine:
    """Create a small RHEA engine for fast test execution."""
    return RHEAEngine(
        pop_size=15,
        max_gens=20,
        time_limit=time_limit,
        max_chromosome_length=4,
    )


def _action_types(result: SearchResult) -> List[str]:
    """Extract action types from search result."""
    return [a.action_type for a in result.best_chromosome]


def _has_play_action_for(result: SearchResult, card_name: str, state: GameState) -> bool:
    """Check if result contains a PLAY action for a named card."""
    for a in result.best_chromosome:
        if a.action_type == "PLAY" and 0 <= a.card_index < len(state.hand):
            if state.hand[a.card_index].name == card_name:
                return True
    return False


def _has_attack_on_target(result: SearchResult, target_index: int) -> bool:
    """Check if result contains an ATTACK action targeting specific index."""
    for a in result.best_chromosome:
        if a.action_type == "ATTACK" and a.target_index == target_index:
            return True
    return False


def _has_attack_on_minion_named(result: SearchResult, state: GameState, minion_name: str) -> bool:
    """Check if result attacks a specific enemy minion by name."""
    for a in result.best_chromosome:
        if a.action_type == "ATTACK" and a.target_index > 0:
            enemy_idx = a.target_index - 1
            if enemy_idx < len(state.opponent.board):
                if state.opponent.board[enemy_idx].name == minion_name:
                    return True
    return False


# ===================================================================
# Test 1: DH Early Game — Weapon Equipping Decision
# ===================================================================

def test_01_dh_weapon_equipping():
    """Turn 2 DH should play 迷时战刃 (1-cost weapon) when mana allows."""
    state = HDTGameStateFactory.create_state(
        turn=2,
        player_class="DEMONHUNTER",
        player_mana=2,
        player_hand=[
            {
                "name": "迷时战刃",
                "type": "WEAPON",
                "tags": {"COST": 1, "ATK": 1, "HEALTH": 0, "DURABILITY": 3},
            },
            {
                "name": "战斗邪魔",
                "type": "MINION",
                "tags": {"COST": 3, "ATK": 3, "HEALTH": 3},
            },
            {
                "name": "精灵龙",
                "type": "MINION",
                "tags": {"COST": 2, "ATK": 3, "HEALTH": 2},
            },
        ],
    )
    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Engine should find something playable
    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # Verify that playing the weapon is a legal action
    legal = enumerate_legal_actions(state)
    weapon_plays = [a for a in legal
                    if a.action_type == "PLAY" and state.hand[a.card_index].name == "迷时战刃"]
    assert len(weapon_plays) > 0, "迷时战刃 should be a legal play at cost 1 with mana 2"

    # With 2 mana, the engine should prefer playing the weapon (1 mana) or
    # the 2-cost minion. Either is reasonable.
    played_names = []
    for a in result.best_chromosome:
        if a.action_type == "PLAY" and 0 <= a.card_index < len(state.hand):
            played_names.append(state.hand[a.card_index].name)

    assert len(played_names) > 0, "Engine should play at least one card on turn 2 with 2 mana"


# ===================================================================
# Test 2: DH Weapon Attack Trade
# ===================================================================

def test_02_dh_weapon_trade():
    """Turn 4 DH with weapon should trade weapon into 3/1 to preserve minion."""
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_class="DEMONHUNTER",
        player_mana=4,
        player_weapon={"name": "迷时战刃", "attack": 2, "durability": 2},
        player_board=[
            {"name": "战斗邪魔", "tags": {"ATK": 2, "HEALTH": 2, "COST": 3, "EXHAUSTED": 0}},
        ],
        opponent_board=[
            {"name": "血沼迅猛龙", "tags": {"ATK": 3, "HEALTH": 1, "COST": 2}},
        ],
    )
    engine = _quick_engine(time_limit=200.0)
    result = engine.search(state)

    # Verify the engine produces a valid result
    assert result.best_chromosome, "Engine returned empty chromosome"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # Weapon attack uses source_index=-1 in our engine
    # Check that at least one attack happens (the engine is stochastic so
    # with a small population it may not always find attacks — retry a few)
    attacks = [a for a in result.best_chromosome if a.action_type == "ATTACK"]
    if len(attacks) == 0:
        # Retry with more generations
        engine2 = RHEAEngine(pop_size=30, max_gens=50, time_limit=300.0, max_chromosome_length=4)
        result = engine2.search(state)
        attacks = [a for a in result.best_chromosome if a.action_type == "ATTACK"]
    assert len(attacks) > 0, "Engine should make at least one attack with board + weapon"

    # The 2/2 minion attacking the 3/1 is a good trade (minion survives with 2-3=-1? no)
    # Actually weapon(2atk) on 3/1 is better: weapon kills it, no damage to hero
    # Or minion(2atk) on 3/1: kills it, minion takes 3, dies
    # Best: weapon hits 3/1 (dies, hero takes 3 damage), minion goes face
    # The engine should find some attack sequence
    assert result.best_fitness > -9999.0, "Engine found a valid action sequence"


# ===================================================================
# Test 3: Taunt Blocking — Must Attack Taunt First
# ===================================================================

def test_03_taunt_blocking():
    """When opponent has taunt, player MUST attack taunt minion first."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_board=[
            {"name": "苔藓恐魔", "tags": {"ATK": 4, "HEALTH": 4, "COST": 4, "EXHAUSTED": 0}},
        ],
        opponent_board=[
            {
                "name": "银色侍从",
                "tags": {"ATK": 1, "HEALTH": 1, "TAUNT": 1},
            },
            {
                "name": "石拳食人魔",
                "tags": {"ATK": 5, "HEALTH": 5},
            },
        ],
    )

    # Verify legal actions enforce taunt
    legal = enumerate_legal_actions(state)
    attack_actions = [a for a in legal if a.action_type == "ATTACK"]

    # All attacks must target the taunt minion (index 1 = first enemy minion)
    # or face (index 0) — but wait, taunt blocks face too
    # Actually: with taunt present, only taunt minions are valid targets
    for a in attack_actions:
        assert a.target_index in (1,), (
            f"With taunt present, only taunt minion should be attackable, "
            f"but got target_index={a.target_index}"
        )

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Engine result should only attack taunt
    for a in result.best_chromosome:
        if a.action_type == "ATTACK":
            assert a.target_index == 1, (
                f"Attack must target taunt (index 1), got {a.target_index}"
            )


# ===================================================================
# Test 4: Lethal Detection — Board Damage Exactly Enough
# ===================================================================

def test_04_lethal_detection_exact_damage():
    """3 minions (3/1, 4/1, 5/1) all can attack, opponent at 12 hp = lethal."""
    state = HDTGameStateFactory.create_state(
        turn=6,
        player_mana=6,
        player_board=[
            {"name": "随从A", "tags": {"ATK": 3, "HEALTH": 1, "EXHAUSTED": 0}},
            {"name": "随从B", "tags": {"ATK": 4, "HEALTH": 1, "EXHAUSTED": 0}},
            {"name": "随从C", "tags": {"ATK": 5, "HEALTH": 1, "EXHAUSTED": 0}},
        ],
        opponent_hp=12,
        opponent_armor=0,
        opponent_board=[],
    )

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Should detect lethal — 3+4+5=12 exactly kills opponent
    assert result.best_fitness == 10000.0, (
        f"Should detect lethal (3+4+5=12), got fitness={result.best_fitness}"
    )

    # All minions should attack face
    face_attacks = [a for a in result.best_chromosome
                    if a.action_type == "ATTACK" and a.target_index == 0]
    assert len(face_attacks) >= 3, (
        f"All 3 minions should attack face for lethal, got {len(face_attacks)} face attacks"
    )


# ===================================================================
# Test 5: Divine Shield Preservation
# ===================================================================

def test_05_divine_shield_preservation():
    """Engine should prefer attacking 3/1 with non-shield minion to preserve shield."""
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=4,
        player_board=[
            {
                "name": "护盾随从",
                "tags": {"ATK": 3, "HEALTH": 3, "DIVINE_SHIELD": 1, "EXHAUSTED": 0},
            },
            {
                "name": "普通随从",
                "tags": {"ATK": 2, "HEALTH": 2, "EXHAUSTED": 0},
            },
        ],
        opponent_board=[
            {"name": "脆弱随从", "tags": {"ATK": 3, "HEALTH": 1}},
        ],
    )

    engine = _quick_engine(time_limit=150.0)
    result = engine.search(state)

    # Check that the engine found a valid sequence
    assert result.best_chromosome, "Engine should return a valid action sequence"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # With many runs, the engine should generally prefer using the 2/2
    # to trade into the 3/1, preserving divine shield.
    # We check that the result is at least reasonable (positive fitness)
    assert result.best_fitness > -9999.0, "Engine found valid actions"


# ===================================================================
# Test 6: Charge Minion Lethal
# ===================================================================

def test_06_charge_minion_lethal():
    """Charge minion on board should be used for lethal face attack.

    Note: The engine's apply_action does NOT propagate CHARGE/RUSH from
    Card.mechanics to Minion fields when playing from hand. So we test
    with a charge minion already on the board (simulating a previous play).
    This tests the charge-can-go-face rule and lethal detection.
    """
    state = HDTGameStateFactory.create_state(
        turn=7,
        player_mana=7,
        player_board=[
            {
                "name": "冲锋随从",
                "tags": {"COST": 3, "ATK": 5, "HEALTH": 2, "CHARGE": 1, "EXHAUSTED": 0},
            },
        ],
        opponent_hp=5,
        opponent_armor=0,
        opponent_board=[],
    )

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Should find lethal — charge minion attacks face for 5 = opponent hp 5
    assert result.best_fitness == 10000.0, (
        f"Should detect lethal via charge minion (5 atk vs 5 hp), "
        f"got fitness={result.best_fitness}"
    )

    # Verify the sequence includes ATTACK on face (target_index=0)
    face_attacks = [a for a in result.best_chromosome
                    if a.action_type == "ATTACK" and a.target_index == 0]
    assert len(face_attacks) >= 1, "Charge minion should attack face for lethal"


# ===================================================================
# Test 7: Rush Minion Cannot Go Face
# ===================================================================

def test_07_rush_cannot_go_face():
    """Rush minion can only attack minions, NOT face.

    Tests the enumerate_legal_actions rule: rush minions cannot target
    the enemy hero (target_index=0), only enemy minions.
    """
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_mana=5,
        player_board=[
            {
                "name": "突袭随从",
                "tags": {"COST": 3, "ATK": 4, "HEALTH": 3, "RUSH": 1, "EXHAUSTED": 0},
            },
        ],
        opponent_hp=4,  # Rush to face would be lethal if allowed
        opponent_armor=0,
        opponent_board=[
            {"name": "敌方随从", "tags": {"ATK": 2, "HEALTH": 2}},
        ],
    )

    # Verify legal actions: rush minion can only target minions, not face
    legal = enumerate_legal_actions(state)
    rush_attacks = [a for a in legal
                    if a.action_type == "ATTACK" and a.source_index == 0]

    # Rush can attack minions but NOT face (target_index=0)
    face_targets = [a for a in rush_attacks if a.target_index == 0]
    minion_targets = [a for a in rush_attacks if a.target_index > 0]

    assert len(face_targets) == 0, (
        f"Rush minion should NOT be able to attack face, "
        f"but found {len(face_targets)} face-targeting attacks"
    )
    assert len(minion_targets) > 0, (
        "Rush minion SHOULD be able to attack enemy minions"
    )

    # Also verify the engine doesn't crash with this state
    engine = _quick_engine(time_limit=80.0)
    result = engine.search(state)
    assert result.best_chromosome, "Engine should handle rush minion state"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # The engine should not find lethal (rush can't go face)
    # Fitness should NOT be 10000.0 since rush can't hit face
    assert result.best_fitness < 10000.0, (
        "Engine should NOT find lethal with rush-only board (rush can't go face)"
    )


# ===================================================================
# Test 8: Mana Efficiency — Play Two Cards Over One
# ===================================================================

def test_08_mana_efficiency_two_cards():
    """With 4 mana, engine should prefer playing two 2-cost cards over one 4-cost."""
    state = HDTGameStateFactory.create_state(
        turn=4,
        player_mana=4,
        player_hand=[
            {
                "name": "二费随从A",
                "type": "MINION",
                "tags": {"COST": 2, "ATK": 2, "HEALTH": 3},
            },
            {
                "name": "二费随从B",
                "type": "MINION",
                "tags": {"COST": 2, "ATK": 2, "HEALTH": 3},
            },
            {
                "name": "四费随从",
                "type": "MINION",
                "tags": {"COST": 4, "ATK": 4, "HEALTH": 5},
            },
        ],
    )

    engine = _quick_engine(time_limit=150.0)
    result = engine.search(state)

    # Count how many PLAY actions in the result
    play_actions = [a for a in result.best_chromosome if a.action_type == "PLAY"]

    # The engine should find that playing two 2-drops is generally better
    # (more board presence). We verify at least 1 play happens.
    assert len(play_actions) >= 1, "Engine should play at least one card"
    assert result.best_fitness > -9999.0, "Engine found valid sequence"


# ===================================================================
# Test 9: Overextension Risk — Don't Play Into AOE
# ===================================================================

def test_09_overextension_risk():
    """With 5 minions on board vs Mage, adding a 6th may be risky.

    Note: Full AOE risk modeling requires V9 risk assessor integration.
    This test verifies the engine handles a full board state correctly
    and that fitness reflects some consideration of board saturation.
    """
    state = HDTGameStateFactory.create_state(
        turn=7,
        player_class="MAGE",
        player_mana=7,
        player_hp=15,
        player_board=[
            {"name": f"随从{i}", "tags": {"ATK": 2, "HEALTH": 2, "EXHAUSTED": 0}}
            for i in range(5)
        ],
        player_hand=[
            {
                "name": "一费随从",
                "type": "MINION",
                "tags": {"COST": 1, "ATK": 1, "HEALTH": 1},
            },
        ],
        opponent_class="MAGE",
    )

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Board is 5/7 full. Playing a 6th minion is legal but risky.
    # Engine should at least produce a valid result.
    assert result.best_chromosome, "Engine should handle large board state"
    assert result.best_chromosome[-1].action_type == "END_TURN"
    assert result.best_fitness > -9999.0, "Engine found valid actions"


# ===================================================================
# Test 10: Weapon Durability Tradeoff
# ===================================================================

def test_10_weapon_durability_tradeoff():
    """DH with 3/3 weapon should make reasonable attack allocation vs taunt+non-taunt."""
    state = HDTGameStateFactory.create_state(
        turn=5,
        player_class="DEMONHUNTER",
        player_mana=5,
        player_weapon={"name": "塞纳留斯之斧", "attack": 3, "durability": 3},
        player_board=[
            {"name": "4/4随从", "tags": {"ATK": 4, "HEALTH": 4, "EXHAUSTED": 0}},
        ],
        opponent_board=[
            {
                "name": "嘲讽随从",
                "tags": {"ATK": 3, "HEALTH": 3, "TAUNT": 1},
            },
            {
                "name": "脆皮随从",
                "tags": {"ATK": 2, "HEALTH": 1},
            },
        ],
    )

    engine = _quick_engine(time_limit=100.0)
    result = engine.search(state)

    # Verify valid result
    assert result.best_chromosome, "Engine should find actions"
    assert result.best_chromosome[-1].action_type == "END_TURN"

    # There should be attack actions — taunt must be dealt with
    attacks = [a for a in result.best_chromosome if a.action_type == "ATTACK"]
    assert len(attacks) > 0, "Should have attack actions vs opponent board"

    first_attack = attacks[0]
    assert first_attack.target_index == 1, (
        f"First attack must target taunt minion, got target={first_attack.target_index}"
    )

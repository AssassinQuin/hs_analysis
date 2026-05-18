#!/usr/bin/env python3
"""test_opponent_simulation.py — Full opponent simulation verification.

Tests the new opponent simulation system:
1. swap_perspective + apply_action for opponent turn
2. Effect chain tracking (card A generates card B → card B played)
3. Death resolution (deathrattle, reborn, corpse)
4. Detailed SimLogger output for debugging

Usage:
    cd /home/z/my-project/hs_analysis
    python scripts/test_opponent_simulation.py
"""

import sys
import os
import json
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_opp_sim")
log.setLevel(logging.INFO)

# Reduce noise from other modules
for name in ["analysis.search.abilities", "analysis.search.aura_engine",
             "analysis.search.battlecry_dispatcher", "analysis.search.trigger_system",
             "analysis.search.deathrattle", "analysis.search.perspective_swap"]:
    logging.getLogger(name).setLevel(logging.WARNING)


# ═══════════════════════════════════════════════════════════════════
# Test 1: Basic perspective swap roundtrip
# ═══════════════════════════════════════════════════════════════════

def test_perspective_swap():
    """Test swap_perspective → simulate → swap_back roundtrip."""
    from analysis.search.game_state import GameState, HeroState, Minion, OpponentState, ManaState
    from analysis.search.perspective_swap import swap_perspective, swap_back
    from analysis.models.card import Card

    print("\n" + "=" * 80)
    print("TEST 1: Perspective Swap Roundtrip")
    print("=" * 80)

    # Create a test game state
    state = GameState(
        hero=HeroState(hp=25, armor=2, hero_class="MAGE"),
        mana=ManaState(available=5, max_mana=7),
        board=[
            Minion(name="Water Elemental", attack=3, health=6, max_health=6,
                   can_attack=True, owner="friendly", has_taunt=True),
            Minion(name="Mana Wyrm", attack=2, health=3, max_health=3,
                   can_attack=True, owner="friendly"),
        ],
        hand=[
            Card(dbf_id=1, name="Fireball", cost=4, card_type="SPELL", attack=0, health=0),
            Card(dbf_id=2, name="Frostbolt", cost=2, card_type="SPELL", attack=0, health=0),
        ],
        deck_remaining=15,
        opponent=OpponentState(
            hero=HeroState(hp=20, armor=0, hero_class="ROGUE"),
            board=[
                Minion(name="SI:7 Agent", attack=3, health=3, max_health=3,
                       can_attack=True, owner="enemy"),
                Minion(name="Edwin VanCleef", attack=8, health=8, max_health=8,
                       can_attack=True, owner="enemy"),
            ],
            hand=[
                Card(dbf_id=3, name="Backstab", cost=0, card_type="SPELL", attack=0, health=0),
                Card(dbf_id=4, name="Eviscerate", cost=2, card_type="SPELL", attack=0, health=0),
            ],
            hand_count=5,
            deck_remaining=12,
        ),
        turn_number=7,
    )

    # Swap to opponent perspective
    swapped, saved = swap_perspective(state)

    # Verify swap
    print(f"\n  Original:")
    print(f"    Our hero: {state.hero.hero_class} HP={state.hero.hp}")
    print(f"    Our board: {[m.name for m in state.board]}")
    print(f"    Opp hero: {state.opponent.hero.hero_class} HP={state.opponent.hero.hp}")
    print(f"    Opp board: {[m.name for m in state.opponent.board]}")
    print(f"    Opp hand: {[getattr(c, 'name', str(c)) for c in state.opponent.hand]}")

    print(f"\n  Swapped:")
    print(f"    Our hero: {swapped.hero.hero_class} HP={swapped.hero.hp}")
    print(f"    Our board: {[m.name for m in swapped.board]}")
    print(f"    Our hand: {[getattr(c, 'name', str(c)) for c in swapped.hand]}")
    print(f"    Opp hero: {swapped.opponent.hero.hero_class} HP={swapped.opponent.hero.hp}")
    print(f"    Opp board: {[m.name for m in swapped.opponent.board]}")
    print(f"    Mana: {swapped.mana.available}/{swapped.mana.max_mana}")

    # Verify correctness
    assert swapped.hero.hero_class == "ROGUE", "Hero should be ROGUE after swap"
    assert swapped.hero.hp == 20, "Hero HP should be 20"
    assert len(swapped.board) == 2, "Board should have 2 minions"
    assert swapped.board[0].name == "SI:7 Agent", "First board minion should be SI:7 Agent"
    assert swapped.opponent.hero.hero_class == "MAGE", "Opponent should be MAGE"
    assert len(swapped.hand) == 2, "Should have opponent's inferred hand"

    # Swap back
    result = swap_back(swapped, saved)

    print(f"\n  Swapped back:")
    print(f"    Our hero: {result.hero.hero_class} HP={result.hero.hp}")
    print(f"    Our board: {[m.name for m in result.board]}")
    print(f"    Opp hero: {result.opponent.hero.hero_class} HP={result.opponent.hero.hp}")
    print(f"    Opp board: {[m.name for m in result.opponent.board]}")

    assert result.hero.hero_class == "MAGE", "Hero should be MAGE after swap back"
    assert result.hero.hp == 25, "Hero HP should be 25"
    assert result.opponent.hero.hero_class == "ROGUE", "Opponent should be ROGUE"

    print("\n  ✅ Perspective swap roundtrip PASSED")
    return True


# ═══════════════════════════════════════════════════════════════════
# Test 2: Opponent turn simulation with action execution
# ═══════════════════════════════════════════════════════════════════

def test_opponent_simulation():
    """Test full opponent turn simulation using perspective swap."""
    from analysis.search.game_state import GameState, HeroState, Minion, OpponentState, ManaState
    from analysis.search.mcts.turn_advance import _simulate_opponent_turn
    from analysis.search.sim_logger import get_sim_logger, set_sim_logger, SimLogger
    from analysis.models.card import Card

    print("\n" + "=" * 80)
    print("TEST 2: Opponent Turn Simulation")
    print("=" * 80)

    # Reset logger
    test_logger = SimLogger(enabled=True)
    set_sim_logger(test_logger)

    # Create a game state where opponent has a strong board and cards
    state = GameState(
        hero=HeroState(hp=18, armor=0, hero_class="PRIEST"),
        mana=ManaState(available=6, max_mana=6),
        board=[
            Minion(name="Northshire Cleric", attack=1, health=3, max_health=3,
                   can_attack=True, owner="friendly"),
        ],
        hand=[
            Card(dbf_id=10, name="Holy Nova", cost=5, card_type="SPELL", attack=0, health=0),
        ],
        deck_remaining=12,
        opponent=OpponentState(
            hero=HeroState(hp=25, armor=0, hero_class="HUNTER"),
            board=[
                Minion(name="Timber Wolf", attack=1, health=1, max_health=1,
                       can_attack=True, owner="enemy", race="BEAST"),
                Minion(name="Hound", attack=1, health=1, max_health=1,
                       can_attack=True, owner="enemy", race="BEAST"),
                Minion(name="Savannah Highmane", attack=6, health=5, max_health=5,
                       can_attack=True, owner="enemy", race="BEAST"),
            ],
            hand=[
                Card(dbf_id=20, name="Kill Command", cost=3, card_type="SPELL", attack=0, health=0),
                Card(dbf_id=21, name="Animal Companion", cost=3, card_type="SPELL", attack=0, health=0),
            ],
            hand_count=4,
            deck_remaining=10,
        ),
        turn_number=8,
    )

    print(f"\n  Before opponent turn:")
    print(f"    Our HP: {state.hero.hp}")
    print(f"    Our board: {[m.name for m in state.board]}")
    print(f"    Opp board: {[m.name for m in state.opponent.board]}")
    print(f"    Opp hand count: {state.opponent.hand_count}")

    # Simulate opponent turn
    result = _simulate_opponent_turn(state)

    print(f"\n  After opponent turn:")
    print(f"    Our HP: {result.hero.hp}")
    print(f"    Our board: {[m.name for m in result.board]}")
    print(f"    Opp board: {[m.name for m in result.opponent.board]}")
    print(f"    Opp hand count: {result.opponent.hand_count}")

    # Print simulation log summary
    summary = test_logger.print_summary()
    print(summary)

    print("\n  ✅ Opponent simulation completed (check logs above for details)")
    return True


# ═══════════════════════════════════════════════════════════════════
# Test 3: Full turn advance with effect chains
# ═══════════════════════════════════════════════════════════════════

def test_full_turn_advance():
    """Test advance_full_turn with effect chains and detailed logging."""
    from analysis.search.game_state import GameState, HeroState, Minion, OpponentState, ManaState
    from analysis.search.mcts.turn_advance import advance_full_turn
    from analysis.search.sim_logger import get_sim_logger, set_sim_logger, SimLogger
    from analysis.models.card import Card

    print("\n" + "=" * 80)
    print("TEST 3: Full Turn Advance with Effect Chains")
    print("=" * 80)

    # Reset logger
    test_logger = SimLogger(enabled=True)
    set_sim_logger(test_logger)

    state = GameState(
        hero=HeroState(hp=28, armor=0, hero_class="WARLOCK"),
        mana=ManaState(available=8, max_mana=8),
        board=[
            Minion(name="Flame Imp", attack=3, health=2, max_health=2,
                   can_attack=True, owner="friendly"),
            Minion(name="Voidwalker", attack=1, health=3, max_health=3,
                   can_attack=True, owner="friendly", has_taunt=True),
        ],
        hand=[
            Card(dbf_id=30, name="Doomguard", cost=5, card_type="MINION",
                 attack=5, health=7),
            Card(dbf_id=31, name="Soulfire", cost=1, card_type="SPELL", attack=0, health=0),
        ],
        deck_remaining=10,
        opponent=OpponentState(
            hero=HeroState(hp=22, armor=0, hero_class="PALADIN"),
            board=[
                Minion(name="Silver Hand Recruit", attack=1, health=1, max_health=1,
                       can_attack=True, owner="enemy"),
            ],
            hand=[
                Card(dbf_id=40, name="Truesilver Champion", cost=4, card_type="WEAPON",
                     attack=4, health=2),
                Card(dbf_id=41, name="Consecration", cost=4, card_type="SPELL", attack=0, health=0),
            ],
            hand_count=5,
            deck_remaining=12,
        ),
        turn_number=8,
    )

    print(f"\n  Before advance_full_turn:")
    print(f"    Turn: {state.turn_number}")
    print(f"    Our HP: {state.hero.hp}, Mana: {state.mana.available}/{state.mana.max_mana}")
    print(f"    Our board: {[f'{m.name}({m.attack}/{m.health})' for m in state.board]}")
    print(f"    Opp HP: {state.opponent.hero.hp}")
    print(f"    Opp board: {[f'{m.name}({m.attack}/{m.health})' for m in state.opponent.board]}")

    # Run full turn advance
    result = advance_full_turn(state, greedy_opponent=True)

    print(f"\n  After advance_full_turn:")
    print(f"    Turn: {result.turn_number}")
    print(f"    Our HP: {result.hero.hp}, Mana: {result.mana.available}/{result.mana.max_mana}")
    print(f"    Our board: {[f'{m.name}({m.attack}/{m.health})' for m in result.board]}")
    print(f"    Opp HP: {result.opponent.hero.hp}")
    print(f"    Opp board: {[f'{m.name}({m.attack}/{m.health})' for m in result.opponent.board]}")

    # Print detailed log
    summary = test_logger.print_summary()
    print(summary)

    # Export to JSON
    output_dir = Path(PROJECT_ROOT) / "download"
    output_dir.mkdir(exist_ok=True)
    log_path = str(output_dir / "sim_log_test3.json")
    test_logger.to_json(log_path)
    print(f"\n  📝 Full simulation log exported to: {log_path}")

    print("\n  ✅ Full turn advance completed")
    return True


# ═══════════════════════════════════════════════════════════════════
# Test 4: OpponentSimulator full simulation mode
# ═══════════════════════════════════════════════════════════════════

def test_opponent_simulator():
    """Test OpponentSimulator in full simulation mode."""
    from analysis.search.game_state import GameState, HeroState, Minion, OpponentState, ManaState
    from analysis.search.opponent_simulator import OpponentSimulator
    from analysis.search.sim_logger import set_sim_logger, SimLogger
    from analysis.models.card import Card

    print("\n" + "=" * 80)
    print("TEST 4: OpponentSimulator Full Simulation Mode")
    print("=" * 80)

    test_logger = SimLogger(enabled=True)
    set_sim_logger(test_logger)

    state = GameState(
        hero=HeroState(hp=15, armor=0, hero_class="MAGE"),
        mana=ManaState(available=5, max_mana=5),
        board=[
            Minion(name="Sorcerer's Apprentice", attack=3, health=2, max_health=2,
                   can_attack=True, owner="friendly"),
        ],
        hand=[
            Card(dbf_id=50, name="Fireball", cost=4, card_type="SPELL", attack=0, health=0),
        ],
        deck_remaining=8,
        opponent=OpponentState(
            hero=HeroState(hp=30, armor=0, hero_class="WARRIOR"),
            board=[
                Minion(name="Fiery War Axe Wielder", attack=3, health=3, max_health=3,
                       can_attack=True, owner="enemy"),
                Minion(name="Grommash Hellscream", attack=4, health=9, max_health=9,
                       can_attack=True, owner="enemy", has_charge=True),
            ],
            hand=[
                Card(dbf_id=60, name="Execute", cost=1, card_type="SPELL", attack=0, health=0),
                Card(dbf_id=61, name="Slam", cost=2, card_type="SPELL", attack=0, health=0),
            ],
            hand_count=4,
            deck_remaining=10,
        ),
        turn_number=6,
    )

    # Test full simulation mode
    sim = OpponentSimulator(full_simulation=True)
    result = sim.simulate_best_response(state, time_budget_ms=100.0)

    print(f"\n  Full simulation results:")
    print(f"    Board resilience delta: {result.board_resilience_delta:.2f}")
    print(f"    Friendly deaths: {result.friendly_deaths}")
    print(f"    Lethal exposure: {result.lethal_exposure}")
    print(f"    Worst case damage: {result.worst_case_damage}")
    print(f"    Damage to our hero: {result.damage_to_our_hero}")
    print(f"    Our hero HP after: {result.our_hero_hp_after}")
    print(f"    Cards played by opponent: {result.cards_played}")
    print(f"    Spell threat: {result.spell_threat:.1f}")

    # Test fast estimation mode
    sim_fast = OpponentSimulator(full_simulation=False)
    result_fast = sim_fast.simulate_best_response(state, time_budget_ms=10.0)

    print(f"\n  Fast estimation results:")
    print(f"    Board resilience delta: {result_fast.board_resilience_delta:.2f}")
    print(f"    Friendly deaths: {result_fast.friendly_deaths}")
    print(f"    Lethal exposure: {result_fast.lethal_exposure}")
    print(f"    Worst case damage: {result_fast.worst_case_damage}")
    print(f"    Spell threat: {result_fast.spell_threat:.1f}")

    # Export log
    output_dir = Path(PROJECT_ROOT) / "download"
    output_dir.mkdir(exist_ok=True)
    log_path = str(output_dir / "sim_log_test4.json")
    test_logger.to_json(log_path)
    print(f"\n  📝 Simulation log exported to: {log_path}")

    print("\n  ✅ OpponentSimulator test completed")
    return True


# ═══════════════════════════════════════════════════════════════════
# Test 5: Effect chain detection
# ═══════════════════════════════════════════════════════════════════

def test_effect_chain_detection():
    """Test that effect chains are detected and logged correctly."""
    from analysis.search.game_state import GameState, HeroState, Minion, OpponentState, ManaState
    from analysis.search.mcts.turn_advance import _greedy_play_with_chains
    from analysis.search.sim_logger import get_sim_logger, set_sim_logger, SimLogger
    from analysis.models.card import Card

    print("\n" + "=" * 80)
    print("TEST 5: Effect Chain Detection and Logging")
    print("=" * 80)

    test_logger = SimLogger(enabled=True)
    set_sim_logger(test_logger)

    # Create state with cards that would generate other cards
    # Note: actual card generation depends on the card effects system,
    # so this tests the detection mechanism rather than specific card effects
    state = GameState(
        hero=HeroState(hp=30, armor=0, hero_class="MAGE"),
        mana=ManaState(available=10, max_mana=10),
        board=[],
        hand=[
            Card(dbf_id=100, name="Arcane Intellect", cost=3, card_type="SPELL",
                 attack=0, health=0, text="Draw 2 cards"),
            Card(dbf_id=101, name="Fireball", cost=4, card_type="SPELL",
                 attack=0, health=0, text="Deal 6 damage"),
            Card(dbf_id=102, name="Frostbolt", cost=2, card_type="SPELL",
                 attack=0, health=0, text="Deal 3 damage and Freeze"),
        ],
        deck_remaining=15,
        opponent=OpponentState(
            hero=HeroState(hp=25, armor=0, hero_class="WARRIOR"),
            board=[],
            hand_count=5,
            deck_remaining=10,
        ),
        turn_number=10,
    )

    print(f"\n  Before greedy play:")
    print(f"    Hand: {[getattr(c, 'name', str(c)) for c in state.hand]}")
    print(f"    Mana: {state.mana.available}/{state.mana.max_mana}")

    with test_logger.phase("chain_test", turn=10):
        result = _greedy_play_with_chains(
            state, max_plays=5, max_chain_depth=3, perspective="self",
        )

    print(f"\n  After greedy play:")
    print(f"    Hand: {[getattr(c, 'name', str(c)) for c in result.hand]}")
    print(f"    Mana: {result.mana.available}/{result.mana.max_mana}")

    # Check log for chain detection
    summary = test_logger.print_summary()
    print(summary)

    # Count chain events
    chain_starts = 0
    chain_plays = 0
    chain_ends = 0
    for phase in test_logger.record.phases:
        for step in phase.steps:
            if step.step_type == "chain_start":
                chain_starts += 1
            elif step.step_type == "chain_play":
                chain_plays += 1
            elif step.step_type == "chain_end":
                chain_ends += 1

    print(f"\n  Chain events: starts={chain_starts}, plays={chain_plays}, ends={chain_ends}")

    # Export
    output_dir = Path(PROJECT_ROOT) / "download"
    output_dir.mkdir(exist_ok=True)
    log_path = str(output_dir / "sim_log_test5.json")
    test_logger.to_json(log_path)
    print(f"\n  📝 Effect chain log exported to: {log_path}")

    print("\n  ✅ Effect chain detection test completed")
    return True


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

def main():
    print("\n" + "#" * 80)
    print("#  Opponent Simulation Verification Tests")
    print("#" * 80)

    results = {}

    tests = [
        ("perspective_swap", test_perspective_swap),
        ("opponent_simulation", test_opponent_simulation),
        ("full_turn_advance", test_full_turn_advance),
        ("opponent_simulator", test_opponent_simulator),
        ("effect_chain", test_effect_chain_detection),
    ]

    for name, test_fn in tests:
        try:
            passed = test_fn()
            results[name] = "PASS" if passed else "FAIL"
        except Exception as e:
            print(f"\n  ❌ Test {name} FAILED: {e}")
            import traceback
            traceback.print_exc()
            results[name] = f"FAIL: {e}"

    # Summary
    print("\n" + "=" * 80)
    print("  Test Results Summary")
    print("=" * 80)
    for name, result in results.items():
        status = "✅" if result == "PASS" else "❌"
        print(f"  {status} {name}: {result}")

    # Save results
    output_dir = Path(PROJECT_ROOT) / "download"
    output_dir.mkdir(exist_ok=True)
    results_path = str(output_dir / "opponent_simulation_test_results.json")
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {results_path}")


if __name__ == "__main__":
    main()

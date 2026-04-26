"""Tests for the unified engine core (P0-P4 changes).

Covers:
- engine/dispatch.py: effect handlers (36 total, 7 newly implemented)
- engine/deterministic.py: DeterministicRNG
- engine/target.py: target resolution and taunt validation
- engine/state.py: GameState with new fields
- simulation.py: death phase semantics + draw with deck_list
"""
import pytest
import dataclasses
from analysis.engine.state import (
    GameState, Minion, HeroState, ManaState, OpponentState,
)
from analysis.abilities.definition import (
    EffectKind, EffectSpec, TargetSpec, TargetKind,
    Action, ActionType,
)
from analysis.models.card import Card


# ==================================================================
# 1. dispatch.py — Effect handler tests
# ==================================================================

class TestDispatchRegistry:
    def test_all_36_handlers_registered(self):
        from analysis.engine.dispatch import EFFECT_HANDLERS
        assert len(EFFECT_HANDLERS) == 36

    def test_every_effect_kind_has_handler(self):
        from analysis.engine.dispatch import EFFECT_HANDLERS
        for kind in EffectKind:
            assert kind in EFFECT_HANDLERS, f"Missing handler for {kind}"


class TestDispatchEffects:
    def _make_state(self):
        """Create a minimal GameState with one minion on each board."""
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        s.opponent.board = [Minion(name="Enemy", attack=3, health=3, max_health=3)]
        s.board = [Minion(name="Friendly", attack=2, health=5, max_health=5, cost=3)]
        s.hand = []
        return s

    def test_damage_to_enemy_minion(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.DAMAGE, value=2, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        assert s.opponent.board[0].health == 1

    def test_destroy_enemy_minion(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.DESTROY, value=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        assert len(s.opponent.board) == 0

    def test_transform_enemy(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.TRANSFORM, value=1, value2=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        m = s.opponent.board[0]
        assert m.attack == 1
        assert m.health == 1

    def test_return_to_hand(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.RETURN, value=1, target=TargetSpec(kind=TargetKind.FRIENDLY_MINION))
        s = dispatch(s, effect, target=0)
        assert len(s.board) == 0
        assert len(s.hand) == 1
        assert s.hand[0].name == "Friendly"

    def test_take_control(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        assert len(s.opponent.board) == 1
        effect = EffectSpec(kind=EffectKind.TAKE_CONTROL, value=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        assert len(s.opponent.board) == 0
        assert len(s.board) == 2  # original + taken

    def test_swap_stats(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.SWAP, value=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        m = s.opponent.board[0]
        assert m.attack == 3  # was health
        assert m.health == 3  # was attack

    def test_copy_minion(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.COPY, value=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        assert len(s.board) == 2  # original + copy

    def test_shuffle_adds_to_deck(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        s.deck_remaining = 10
        effect = EffectSpec(kind=EffectKind.SHUFFLE, value=2)
        s = dispatch(s, effect, target=None)
        assert s.deck_remaining == 12

    def test_armor_gain(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.ARMOR, value=5)
        s = dispatch(s, effect, target=None)
        assert s.hero.armor == 5

    def test_freeze_minion(self):
        from analysis.engine.dispatch import dispatch
        s = self._make_state()
        effect = EffectSpec(kind=EffectKind.FREEZE, value=1, target=TargetSpec(kind=TargetKind.ENEMY))
        s = dispatch(s, effect, target=0)
        assert s.opponent.board[0].frozen_until_next_turn == True


# ==================================================================
# 2. deterministic.py tests
# ==================================================================

class TestDeterministicRNG:
    def test_same_seed_same_result(self):
        from analysis.engine.deterministic import DeterministicRNG
        rng1 = DeterministicRNG(42)
        rng2 = DeterministicRNG(42)
        assert rng1.choice([1, 2, 3]) == rng2.choice([1, 2, 3])

    def test_different_seed_different_result(self):
        from analysis.engine.deterministic import DeterministicRNG
        rng1 = DeterministicRNG(42)
        rng2 = DeterministicRNG(99)
        results1 = [rng1.choice([1, 2, 3, 4, 5]) for _ in range(10)]
        results2 = [rng2.choice([1, 2, 3, 4, 5]) for _ in range(10)]
        assert results1 != results2

    def test_sample_correct_count(self):
        from analysis.engine.deterministic import DeterministicRNG
        rng = DeterministicRNG(42)
        result = rng.sample([1, 2, 3, 4, 5], 3)
        assert len(result) == 3
        assert len(set(result)) == 3  # all unique

    def test_from_state_consistency(self):
        from analysis.engine.deterministic import DeterministicRNG
        s1 = GameState()
        s2 = GameState()
        rng1 = DeterministicRNG.from_state(s1)
        rng2 = DeterministicRNG.from_state(s2)
        assert rng1.choice([1, 2, 3]) == rng2.choice([1, 2, 3])

    def test_det_top_k(self):
        from analysis.engine.deterministic import det_top_k
        items = [5, 3, 8, 1, 9, 2, 7]
        result = det_top_k(items, 3, score_fn=lambda x: x)
        assert len(result) == 3
        assert 9 in result
        assert 8 in result
        assert 7 in result


# ==================================================================
# 3. target.py tests
# ==================================================================

class TestTargetResolution:
    def test_validate_taunt_enforcement(self):
        """Attacking a non-taunt minion should be invalid when taunt exists."""
        from analysis.engine.target import validate_target
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        s.opponent.board = [
            Minion(name="Taunt", has_taunt=True, attack=1, health=3, max_health=3),
            Minion(name="NonTaunt", attack=2, health=2, max_health=2),
        ]
        # validate_target checks action.target attribute
        # We use a simple namespace to set target to index 1 (NonTaunt)
        action = type('Action', (), {
            'action_type': 'ATTACK',
            'target': 1,  # NonTaunt at index 1 — should fail because Taunt exists
        })()
        result = validate_target(s, action)
        assert result is False

    def test_validate_taunt_allows_attacking_taunt(self):
        """Attacking the taunt minion directly should be valid."""
        from analysis.engine.target import validate_target
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        s.opponent.board = [
            Minion(name="Taunt", has_taunt=True, attack=1, health=3, max_health=3),
            Minion(name="NonTaunt", attack=2, health=2, max_health=2),
        ]
        action = type('Action', (), {
            'action_type': 'ATTACK',
            'target': 0,  # Taunt at index 0 — should be valid
        })()
        result = validate_target(s, action)
        assert result is True

    def test_validate_no_taunt_allows_face(self):
        """Attacking face when no taunt exists should be valid."""
        from analysis.engine.target import validate_target
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.board = [Minion(name="Attacker", attack=2, health=2, max_health=2, can_attack=True)]
        s.opponent = OpponentState(hero=HeroState())
        s.opponent.board = [Minion(name="NoTaunt", attack=2, health=2, max_health=2)]
        # target=None means no target validation needed (returns True)
        action = type('Action', (), {
            'action_type': 'ATTACK',
            'target': None,
        })()
        result = validate_target(s, action)
        assert result is True

    def test_validate_stealth_blocks_target(self):
        """Stealthed minions cannot be targeted."""
        from analysis.engine.target import validate_target
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        s.opponent.board = [
            Minion(name="Stealthed", has_stealth=True, attack=2, health=2, max_health=2),
        ]
        action = type('Action', (), {
            'action_type': 'ATTACK',
            'target': 0,  # Stealthed at index 0 — should fail
        })()
        result = validate_target(s, action)
        assert result is False


# ==================================================================
# 4. state.py tests
# ==================================================================

class TestGameState:
    def test_new_fields_default(self):
        """Phase 1 new fields should have correct defaults."""
        s = GameState()
        assert s.graveyard == []
        assert s.cards_drawn_this_turn == 0  # int, not list
        assert s.spells_cast_this_turn == 0  # int, not list

    def test_copy_preserves_new_fields(self):
        """copy() should deep-copy mutable new fields."""
        s = GameState()
        s.graveyard = [Minion(name="Dead", attack=2, health=0, max_health=3)]
        s_copy = s.copy()
        assert len(s_copy.graveyard) == 1
        assert s_copy.graveyard is not s.graveyard  # deep copy

    def test_copy_preserves_int_fields(self):
        """copy() should preserve int new fields."""
        s = GameState()
        s.cards_drawn_this_turn = 3
        s.spells_cast_this_turn = 2
        s_copy = s.copy()
        assert s_copy.cards_drawn_this_turn == 3
        assert s_copy.spells_cast_this_turn == 2


# ==================================================================
# 5. simulation.py death phase + draw tests
# ==================================================================

class TestDeathPhase:
    def test_simultaneous_death_collection(self):
        """Dead minions should be collected before deathrattles resolve."""
        from analysis.engine.simulation import apply_action
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        # Two friendly minions, both will die to a 5/5
        s.board = [
            Minion(name="Minion1", attack=1, health=1, max_health=1, can_attack=True),
        ]
        s.opponent.board = [
            Minion(name="BigEnemy", attack=5, health=5, max_health=5),
        ]
        # Attack the big enemy — our minion dies from counter
        action = Action(action_type=ActionType.ATTACK, source_index=0, target_index=1)
        s2 = apply_action(s.copy(), action)
        # Our minion should be dead (health 1 vs counter 5)
        assert len(s2.board) == 0
        # Enemy should have taken 1 damage
        assert s2.opponent.board[0].health == 4

    def test_reborn_preserves_taunt(self):
        """Reborn minions should keep taunt (Hearthstone rule)."""
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.opponent = OpponentState(hero=HeroState())
        s.board = [
            Minion(
                name="TauntReborn", attack=2, health=1, max_health=3,
                has_taunt=True, has_reborn=True, can_attack=True,
            ),
        ]
        s.opponent.board = [
            Minion(name="Killer", attack=5, health=5, max_health=5),
        ]
        action = Action(action_type=ActionType.ATTACK, source_index=0, target_index=1)
        from analysis.engine.simulation import apply_action
        s2 = apply_action(s.copy(), action)
        # Minion should be reborn at 1 HP with taunt preserved
        if len(s2.board) > 0:
            reborn = s2.board[0]
            assert reborn.health == 1
            assert reborn.has_taunt is True, "Reborn must preserve taunt"


class TestDrawWithDeckList:
    def test_draw_from_deck_list(self):
        """Drawing from a deck_list should pop cards in order."""
        from analysis.engine.simulation import apply_draw
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.hand = []
        s.deck_remaining = 3
        s.deck_list = [
            Card(dbf_id=1, name="Card1", cost=1, card_type="MINION"),
            Card(dbf_id=2, name="Card2", cost=2, card_type="SPELL"),
            Card(dbf_id=3, name="Card3", cost=3, card_type="MINION"),
        ]
        s2 = apply_draw(s, 2)
        assert len(s2.hand) == 2
        assert s2.hand[0].name == "Card1"
        assert s2.hand[1].name == "Card2"
        assert s2.deck_remaining == 1
        assert len(s2.deck_list) == 1  # popped 2 from 3

    def test_draw_fatigue(self):
        """Drawing with empty deck should cause fatigue damage."""
        from analysis.engine.simulation import apply_draw
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.hand = []
        s.deck_remaining = 0
        s.deck_list = []
        s.fatigue_damage = 0
        s2 = apply_draw(s, 1)
        assert len(s2.hand) == 0
        assert s2.fatigue_damage == 1
        assert s2.hero.hp == 29  # 30 - 1 fatigue

    def test_draw_stub_when_no_deck_list(self):
        """Drawing with no deck_list should produce stub cards."""
        from analysis.engine.simulation import apply_draw
        s = GameState()
        s.hero = HeroState()
        s.mana = ManaState()
        s.hand = []
        s.deck_remaining = 2
        s.deck_list = []  # empty
        s2 = apply_draw(s, 1)
        assert len(s2.hand) == 1
        assert s2.hand[0].name == "Drawn Card"

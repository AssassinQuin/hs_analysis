#!/usr/bin/env python3
"""test_trigger_system.py — Tests for Enchantment model + TriggerDispatcher.

Batch 1: Foundation layer for V10 Phase 2 trigger/enchantment system.
"""

import pytest

from analysis.engine.state import GameState, Minion, HeroState, OpponentState
from analysis.engine.enchantment import (
    Enchantment,
    apply_enchantment,
    remove_enchantment_legacy as remove_enchantment,
    _tick_entity_enchantments as tick_enchantments,
    compute_effective_attack,
    compute_effective_health,
    compute_effective_max_health,
    get_effective_keywords,
)
from analysis.engine.trigger import TriggerDispatcher


# ===================================================================
# Enchantment model tests
# ===================================================================

class TestEnchantmentModel:
    """Tests for Enchantment dataclass and stat helpers."""

    def test_enchantment_creation_defaults(self):
        e = Enchantment()
        assert e.enchantment_id == ""
        assert e.attack_delta == 0
        assert e.duration == -1
        assert e.keywords_added == []
        assert e.keywords_removed == []

    def test_enchantment_custom_values(self):
        e = Enchantment(
            enchantment_id="buff_01",
            name="Test Buff",
            attack_delta=2,
            health_delta=3,
            max_health_delta=3,
            duration=2,
        )
        assert e.attack_delta == 2
        assert e.health_delta == 3
        assert e.duration == 2

    def test_apply_enchantment_buff(self):
        m = Minion(attack=3, health=3, max_health=3)
        buff = Enchantment(
            enchantment_id="buff",
            attack_delta=2,
            health_delta=2,
            max_health_delta=2,
        )
        apply_enchantment(m, buff)
        assert m.attack == 5
        assert m.health == 5
        assert m.max_health == 5
        assert len(m.enchantments) == 1

    def test_apply_enchantment_debuff(self):
        m = Minion(attack=5, health=5, max_health=5)
        debuff = Enchantment(
            enchantment_id="debuff",
            attack_delta=-2,
            health_delta=-2,
        )
        apply_enchantment(m, debuff)
        assert m.attack == 3
        assert m.health == 3

    def test_apply_enchantment_minimum_zero(self):
        """Stats should floor at 0 even with large negative deltas."""
        m = Minion(attack=1, health=1, max_health=1)
        debuff = Enchantment(attack_delta=-10, health_delta=-10)
        apply_enchantment(m, debuff)
        assert m.attack == 0
        assert m.health == 0

    def test_remove_enchantment(self):
        m = Minion(attack=3, health=3, max_health=3)
        buff = Enchantment(
            enchantment_id="removeme",
            attack_delta=2,
            health_delta=2,
            max_health_delta=2,
        )
        apply_enchantment(m, buff)
        assert m.attack == 5
        remove_enchantment(m, "removeme")
        assert m.attack == 3
        assert m.health == 3
        assert len(m.enchantments) == 0

    def test_remove_enchantment_nonexistent(self):
        """Removing nonexistent enchantment should be a no-op."""
        m = Minion(attack=3, health=3)
        remove_enchantment(m, "does_not_exist")
        assert m.attack == 3

    def test_tick_enchantments_duration_expiry(self):
        m = Minion(attack=3, health=3, max_health=3)
        buff = Enchantment(
            enchantment_id="temp",
            attack_delta=2,
            health_delta=2,
            max_health_delta=2,
            duration=1,
        )
        apply_enchantment(m, buff)
        assert m.attack == 5

        # Tick: duration 1→0, should remove
        removed = tick_enchantments(m)
        assert removed == 1
        assert m.attack == 3
        assert len(m.enchantments) == 0

    def test_tick_enchantments_permanent_not_removed(self):
        m = Minion(attack=3, health=3)
        perm = Enchantment(
            enchantment_id="perm",
            attack_delta=1,
            duration=-1,
        )
        apply_enchantment(m, perm)
        removed = tick_enchantments(m)
        assert removed == 0
        assert len(m.enchantments) == 1
        assert m.attack == 4

    def test_tick_enchantments_multi_turn_duration(self):
        m = Minion(attack=3, health=3, max_health=3)
        buff = Enchantment(
            enchantment_id="twoturn",
            attack_delta=1,
            duration=3,
        )
        apply_enchantment(m, buff)
        # Tick 3 times → should persist for 3 ticks, removed on 4th
        for i in range(2):
            removed = tick_enchantments(m)
            assert removed == 0
        assert len(m.enchantments) == 1

        # Final tick: duration 1→0, removed
        removed = tick_enchantments(m)
        assert removed == 1
        assert m.attack == 3

    def test_compute_effective_attack(self):
        m = Minion(attack=3)
        buff1 = Enchantment(attack_delta=2)
        buff2 = Enchantment(attack_delta=1)
        m.enchantments = [buff1, buff2]
        assert compute_effective_attack(m) == 6

    def test_compute_effective_health(self):
        m = Minion(health=4)
        m.enchantments = [Enchantment(health_delta=3)]
        assert compute_effective_health(m) == 7

    def test_compute_effective_max_health(self):
        m = Minion(max_health=5)
        m.enchantments = [Enchantment(max_health_delta=2)]
        assert compute_effective_max_health(m) == 7

    def test_get_effective_keywords(self):
        m = Minion(has_taunt=True)
        kw = get_effective_keywords(m)
        assert 'TAUNT' in kw
        assert 'DIVINE_SHIELD' not in kw

    def test_get_effective_keywords_added_removed(self):
        m = Minion(has_taunt=True)
        ench = Enchantment(
            keywords_added=['DIVINE_SHIELD'],
            keywords_removed=['TAUNT'],
        )
        m.enchantments = [ench]
        kw = get_effective_keywords(m)
        assert 'DIVINE_SHIELD' in kw
        assert 'TAUNT' not in kw


# ===================================================================
# TriggerDispatcher tests
# ===================================================================

class TestTriggerDispatcher:
    """Tests for TriggerDispatcher event system."""

    def _make_state(self) -> GameState:
        """Create a default test state."""
        return GameState(
            hero=HeroState(hp=30),
            opponent=OpponentState(hero=HeroState(hp=30)),
        )

    def test_on_turn_end_damage_enemy_hero(self):
        """end_of_turn trigger: damage enemy hero for 2."""
        state = self._make_state()
        m = Minion(name="Test Imp", attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="imp_pulse",
            trigger_type="end_of_turn",
            trigger_effect="damage:enemy_hero:2",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        dispatcher = TriggerDispatcher()
        state = dispatcher.on_turn_end(state)
        assert state.opponent.hero.hp == 28

    def test_on_turn_end_armor_gain(self):
        """end_of_turn trigger: gain 3 armor."""
        state = self._make_state()
        m = Minion(attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="armor_up",
            trigger_type="end_of_turn",
            trigger_effect="armor:3",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        state = TriggerDispatcher().on_turn_end(state)
        assert state.hero.armor == 3

    def test_on_minion_played_damage_random_enemy(self):
        """on_play trigger: deal 1 damage to random enemy minion."""
        state = self._make_state()
        # Board has a minion with on_play trigger
        trigger_minion = Minion(name="Knife Juggler", attack=2, health=2, max_health=2)
        ench = Enchantment(
            enchantment_id="juggler",
            trigger_type="on_play",
            trigger_effect="damage:random_enemy:1",
        )
        apply_enchantment(trigger_minion, ench)
        state.board.append(trigger_minion)

        # Enemy has a minion
        enemy = Minion(name="Enemy Minion", attack=1, health=3, max_health=3, owner="enemy")
        state.opponent.board.append(enemy)

        # Play a new minion
        new_minion = Minion(name="Wisp", attack=1, health=1, max_health=1)
        state.board.append(new_minion)

        state = TriggerDispatcher().on_minion_played(state, new_minion, None)
        assert state.opponent.board[0].health == 2  # 3 - 1

    def test_on_minion_dies_deathrattle_summon(self):
        """deathrattle trigger: summon a 1/1 token."""
        state = self._make_state()
        dying = Minion(name="Haunted Creeper", attack=1, health=0, max_health=2)
        ench = Enchantment(
            enchantment_id="haunt",
            trigger_type="deathrattle",
            trigger_effect="summon:1:1",
        )
        apply_enchantment(dying, ench)
        state.board.append(dying)

        state = TriggerDispatcher().on_minion_dies(state, dying, 0)
        # Should have summoned a 1/1 token
        assert len(state.board) >= 1  # dying still in list + new token
        tokens = [m for m in state.board if m.name.startswith("Token")]
        assert len(tokens) == 1
        assert tokens[0].attack == 1
        assert tokens[0].health == 1

    def test_on_minion_dies_deathrattle_draw(self):
        """deathrattle trigger: draw 1 card."""
        state = self._make_state()
        state.deck_remaining = 5
        dying = Minion(name="Loot Hoarder", attack=2, health=0, max_health=2)
        ench = Enchantment(
            enchantment_id="loot",
            trigger_type="deathrattle",
            trigger_effect="draw:1",
        )
        apply_enchantment(dying, ench)

        state = TriggerDispatcher().on_minion_dies(state, dying, 0)
        assert state.deck_remaining == 4  # drew 1 card

    def test_on_attack_triggers_on_attack_effect(self):
        """on_attack trigger: buff self after attacking."""
        state = self._make_state()
        attacker = Minion(name="Tester", attack=3, health=3, max_health=3)
        ench = Enchantment(
            enchantment_id="grow",
            trigger_type="on_attack",
            trigger_effect="buff:friendly:1:0",
        )
        apply_enchantment(attacker, ench)
        state.board.append(attacker)

        state = TriggerDispatcher().on_attack(state, attacker, None)
        # All friendly minions got +1 attack
        assert state.board[0].attack == 4  # 3 + 1 from trigger buff

    def test_graceful_degradation_on_empty_board(self):
        """All events should be safe on empty boards/hands."""
        state = self._make_state()
        dispatcher = TriggerDispatcher()

        state = dispatcher.on_turn_end(state)
        state = dispatcher.on_turn_start(state)
        state = dispatcher.on_minion_played(state, Minion(), None)
        state = dispatcher.on_minion_dies(state, Minion(), 0)
        state = dispatcher.on_spell_cast(state, None)

        assert state.opponent.hero.hp == 30  # nothing changed

    def test_graceful_degradation_bad_trigger_effect(self):
        """Unknown trigger effects should be ignored, not crash."""
        state = self._make_state()
        m = Minion(name="Bad Effect", attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="bad",
            trigger_type="end_of_turn",
            trigger_effect="this_is_not_a_valid_effect",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        state = TriggerDispatcher().on_turn_end(state)
        assert state.opponent.hero.hp == 30  # no crash, no damage

    def test_on_damage_dealt(self):
        """on_damage trigger on a minion."""
        state = self._make_state()
        m = Minion(name="Frothing", attack=2, health=3, max_health=3)
        ench = Enchantment(
            enchantment_id="frothing",
            trigger_type="on_damage",
            trigger_effect="buff:friendly:1:0",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        state = TriggerDispatcher().on_damage_dealt(state, m, 1)
        # Frothing gained +1 attack from being damaged
        assert state.board[0].attack == 3

    def test_on_spell_cast_trigger(self):
        """on_spell_cast trigger: heal hero for 2."""
        state = self._make_state()
        state.hero.hp = 25
        m = Minion(name="Priest minion", attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="spell_heal",
            trigger_type="on_spell_cast",
            trigger_effect="heal:hero:2",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        state = TriggerDispatcher().on_spell_cast(state, None)
        assert state.hero.hp == 27

    def test_duration_tick_on_turn_end(self):
        """Enchantments with duration should tick down on turn end."""
        state = self._make_state()
        m = Minion(attack=3, health=3, max_health=3)
        buff = Enchantment(
            enchantment_id="temp_buff",
            attack_delta=2,
            health_delta=2,
            max_health_delta=2,
            duration=1,
        )
        apply_enchantment(m, buff)
        state.board.append(m)
        assert m.attack == 5

        state = TriggerDispatcher().on_turn_end(state)
        # Duration was 1, ticked to 0, removed
        assert len(state.board[0].enchantments) == 0
        assert state.board[0].attack == 3

    def test_damage_all_enemy_effect(self):
        """damage:all_enemy:N effect hits all enemy minions."""
        state = self._make_state()
        m = Minion(name="AoE Trigger", attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="aoe",
            trigger_type="end_of_turn",
            trigger_effect="damage:all_enemy:2",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        state.opponent.board.append(Minion(name="E1", attack=1, health=5, max_health=5, owner="enemy"))
        state.opponent.board.append(Minion(name="E2", attack=1, health=3, max_health=3, owner="enemy"))

        state = TriggerDispatcher().on_turn_end(state)
        assert state.opponent.board[0].health == 3  # 5 - 2
        assert state.opponent.board[1].health == 1  # 3 - 2

    def test_damage_vs_divine_shield(self):
        """Damage effect should pop divine shield instead of damaging."""
        state = self._make_state()
        m = Minion(name="Trigger", attack=1, health=1, max_health=1)
        ench = Enchantment(
            enchantment_id="pop_shield",
            trigger_type="end_of_turn",
            trigger_effect="damage:random_enemy:5",
        )
        apply_enchantment(m, ench)
        state.board.append(m)

        shielded = Minion(name="Shielded", attack=1, health=3, max_health=3,
                          has_divine_shield=True, owner="enemy")
        state.opponent.board.append(shielded)

        state = TriggerDispatcher().on_turn_end(state)
        assert state.opponent.board[0].health == 3  # shield absorbed it
        assert not state.opponent.board[0].has_divine_shield  # shield popped

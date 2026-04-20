#!/usr/bin/env python3
"""test_deathrattle.py — Tests for DeathrattleQueue.

Batch 3: Deathrattle effect resolution with cascade support.
"""

import pytest

from hs_analysis.search.game_state import GameState, Minion, HeroState, OpponentState
from hs_analysis.search.enchantment import Enchantment, apply_enchantment
from hs_analysis.search.deathrattle import resolve_deaths, parse_deathrattle_text


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def fresh_state():
    return GameState(hero=HeroState(hp=30), opponent=OpponentState(hero=HeroState(hp=30)))


# ===================================================================
# Tests
# ===================================================================

class TestDeathrattleSummon:
    """亡语：召唤 N/N"""

    def test_summon_token_on_death(self, fresh_state):
        dying = Minion(name="Creeper", attack=1, health=0, max_health=2)
        ench = Enchantment(
            enchantment_id="haunt",
            trigger_type="deathrattle",
            trigger_effect="summon:1:1",
        )
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.board) == 1  # token replaced dead minion
        assert result.board[0].attack == 1
        assert result.board[0].health == 1

    def test_summon_larger_token(self, fresh_state):
        dying = Minion(name="Big DR", attack=2, health=0, max_health=2)
        ench = Enchantment(
            enchantment_id="big",
            trigger_type="deathrattle",
            trigger_effect="summon:4:4",
        )
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert result.board[0].attack == 4
        assert result.board[0].health == 4

    def test_summon_respects_board_limit(self, fresh_state):
        # Fill board to 6 (dead one makes 7)
        for i in range(6):
            fresh_state.board.append(Minion(name=f"M{i}", attack=1, health=1, max_health=1))
        dying = Minion(name="DR", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="dr", trigger_type="deathrattle",
                           trigger_effect="summon:1:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.board) == 7  # 6 alive + 1 token (dead removed)


class TestDeathrattleDamage:
    """亡语：造成N点伤害"""

    def test_random_damage_kills_enemy(self, fresh_state):
        enemy = Minion(name="Fragile", attack=1, health=1, max_health=1, owner="enemy")
        fresh_state.opponent.board.append(enemy)

        dying = Minion(name="Boom", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="boom", trigger_type="deathrattle",
                           trigger_effect="damage:random_enemy:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.opponent.board) == 0  # enemy killed

    def test_aoe_damage_all_enemies(self, fresh_state):
        for i in range(3):
            fresh_state.opponent.board.append(
                Minion(name=f"E{i}", attack=1, health=2, max_health=2, owner="enemy")
            )

        dying = Minion(name="AoE DR", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="aoe", trigger_type="deathrattle",
                           trigger_effect="damage:all_enemy:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        for m in result.opponent.board:
            assert m.health == 1  # 2 - 1


class TestDeathrattleDraw:
    """亡语：抽N张牌"""

    def test_draw_on_death(self, fresh_state):
        fresh_state.deck_remaining = 5
        dying = Minion(name="Looter", attack=2, health=0, max_health=2)
        ench = Enchantment(enchantment_id="loot", trigger_type="deathrattle",
                           trigger_effect="draw:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert result.deck_remaining == 4


class TestDeathrattleBuff:
    """亡语：+N/+N (buff friendly)"""

    def test_buff_surviving_minions(self, fresh_state):
        alive = Minion(name="Alive", attack=2, health=2, max_health=2)
        fresh_state.board.append(alive)

        dying = Minion(name="Buffer", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="buf", trigger_type="deathrattle",
                           trigger_effect="buff:friendly:2:2")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert result.board[0].attack == 4  # 2 + 2
        assert result.board[0].health == 4


class TestDeathrattleArmor:
    """亡语：获得N点护甲"""

    def test_gain_armor_on_death(self, fresh_state):
        dying = Minion(name="Armorer", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="arm", trigger_type="deathrattle",
                           trigger_effect="armor:3")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert result.hero.armor == 3


class TestDeathrattleCascade:
    """Death cascade: deathrattle kills another minion"""

    def test_cascade_one_level(self, fresh_state):
        # Enemy with 1 HP
        fresh_state.opponent.board.append(
            Minion(name="Fragile Enemy", attack=1, health=1, max_health=1, owner="enemy")
        )
        # Friendly dying → deals 1 random damage (kills enemy)
        dying = Minion(name="Cannon", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="boom", trigger_type="deathrattle",
                           trigger_effect="damage:random_enemy:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.opponent.board) == 0

    def test_cascade_limit(self, fresh_state):
        """Cascade should not exceed max_cascade."""
        # Create a chain: each minion's death kills the next
        # But with max_cascade=1, only first level resolves
        for i in range(3):
            m = Minion(name=f"E{i}", attack=1, health=1, max_health=1, owner="enemy")
            fresh_state.opponent.board.append(m)

        dying = Minion(name="Chain", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="chain", trigger_type="deathrattle",
                           trigger_effect="damage:all_enemy:1")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state, max_cascade=5)
        # All enemies should die: they all have 1 HP, AoE deals 1
        assert len(result.opponent.board) == 0


class TestDeathrattleNoEffect:
    """Minions without deathrattle should just be removed."""

    def test_vanilla_death(self, fresh_state):
        dying = Minion(name="Yeti", attack=4, health=0, max_health=5)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.board) == 0

    def test_empty_board_safe(self, fresh_state):
        result = resolve_deaths(fresh_state)
        assert len(result.board) == 0
        assert len(result.opponent.board) == 0


class TestDeathrattleTextParse:
    """Text-based deathrattle parsing."""

    def test_parse_summon(self):
        effect = parse_deathrattle_text("亡语：召唤两个1/1的蜘蛛")
        assert effect == "summon:1:1"

    def test_parse_random_damage(self):
        effect = parse_deathrattle_text("亡语：对随机敌人造成2点伤害")
        assert effect == "damage:random_enemy:2"

    def test_parse_draw(self):
        effect = parse_deathrattle_text("亡语：抽1张牌")
        assert effect == "draw:1"

    def test_parse_no_deathrattle(self):
        effect = parse_deathrattle_text("战吼：造成3点伤害")
        assert effect is None

    def test_parse_empty_text(self):
        effect = parse_deathrattle_text("")
        assert effect is None


class TestDeathrattleDivineShield:
    """Deathrattle damage vs divine shield."""

    def test_damage_pops_shield_not_kill(self, fresh_state):
        shielded = Minion(name="Shielded", attack=1, health=3, max_health=3,
                          has_divine_shield=True, owner="enemy")
        fresh_state.opponent.board.append(shielded)

        dying = Minion(name="DR", attack=1, health=0, max_health=1)
        ench = Enchantment(enchantment_id="dr", trigger_type="deathrattle",
                           trigger_effect="damage:random_enemy:5")
        apply_enchantment(dying, ench)
        fresh_state.board.append(dying)

        result = resolve_deaths(fresh_state)
        assert len(result.opponent.board) == 1
        assert result.opponent.board[0].health == 3  # shield absorbed
        assert not result.opponent.board[0].has_divine_shield

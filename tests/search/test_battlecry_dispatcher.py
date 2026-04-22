#!/usr/bin/env python3
"""test_battlecry_dispatcher.py — Tests for BattlecryDispatcher.

Batch 2: Battlecry effect parsing and application.
"""

import pytest

from analysis.search.game_state import GameState, Minion, HeroState, OpponentState
from analysis.models.card import Card
from analysis.search.battlecry_dispatcher import BattlecryDispatcher, dispatch_battlecry


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture
def fresh_state():
    return GameState(hero=HeroState(hp=30), opponent=OpponentState(hero=HeroState(hp=30)))


@pytest.fixture
def dispatcher():
    return BattlecryDispatcher()


def _bc_card(text: str, mechanics=None) -> Card:
    return Card(
        dbf_id=1, name="Test Card", cost=3, card_type="MINION",
        attack=2, health=2, text=text,
        mechanics=mechanics or ["BATTLECRY"],
    )


# ===================================================================
# Tests
# ===================================================================

class TestBattlecryDamage:
    """战吼：造成N点伤害"""

    def test_damage_kills_enemy_minion(self, fresh_state, dispatcher):
        fresh_state.opponent.board.append(
            Minion(name="Enemy", attack=3, health=3, max_health=3, owner="enemy")
        )
        card = _bc_card("战吼：造成3点伤害")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.board[0].health == 0  # killed

    def test_damage_targets_highest_attack_minion(self, fresh_state, dispatcher):
        fresh_state.opponent.board.append(
            Minion(name="Weak", attack=1, health=5, max_health=5, owner="enemy")
        )
        fresh_state.opponent.board.append(
            Minion(name="Strong", attack=7, health=7, max_health=7, owner="enemy")
        )
        card = _bc_card("战吼：造成2点伤害")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        # Should target the Strong minion (highest attack)
        assert result.opponent.board[1].health == 5  # 7 - 2
        assert result.opponent.board[0].health == 5  # untouched

    def test_damage_goes_to_hero_if_no_minions(self, fresh_state, dispatcher):
        card = _bc_card("战吼：造成3点伤害")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.hero.hp == 27  # 30 - 3


class TestBattlecryHeal:
    """战吼：恢复N点生命"""

    def test_heal_hero(self, fresh_state, dispatcher):
        fresh_state.hero.hp = 25
        card = _bc_card("战吼：恢复5点生命")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.hp == 30  # healed to max


class TestBattlecrySummon:
    """战吼：召唤 N/N"""

    def test_summon_token(self, fresh_state, dispatcher):
        card = _bc_card("战吼：召唤2/2的衍生物")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        # Should have 2 minions now (original + summoned)
        assert len(result.board) == 2

    def test_summon_respects_board_limit(self, fresh_state, dispatcher):
        # Fill board to 7
        for i in range(7):
            fresh_state.board.append(Minion(name=f"M{i}", attack=1, health=1, max_health=1))

        card = _bc_card("战吼：召唤1/1")
        minion = fresh_state.board[-1]
        result = dispatcher.dispatch(fresh_state, card, minion)
        assert len(result.board) == 7  # no room


class TestBattlecryDraw:
    """战吼：抽N张牌"""

    def test_draw_two_cards(self, fresh_state, dispatcher):
        fresh_state.deck_remaining = 10
        card = _bc_card("战吼：抽2张牌")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.deck_remaining == 8


class TestBattlecryBuff:
    """战吼：+N攻击力 (buff self)"""

    def test_buff_self(self, fresh_state, dispatcher):
        card = _bc_card("战吼：+2攻击力")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].attack == 4  # 2 + 2


class TestBattlecryArmor:
    """战吼：获得N点护甲"""

    def test_gain_armor(self, fresh_state, dispatcher):
        card = _bc_card("战吼：获得3点护甲")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.armor == 3


class TestBattlecryExtraEffects:
    """Battlecry-specific effects beyond spell_simulator."""

    def test_freeze_enemy(self, fresh_state, dispatcher):
        fresh_state.opponent.board.append(
            Minion(name="Enemy", attack=3, health=3, max_health=3, owner="enemy")
        )
        card = _bc_card("战吼：冻结一个敌人")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.board[0].frozen_until_next_turn is True

    def test_give_divine_shield(self, fresh_state, dispatcher):
        card = _bc_card("战吼：获得圣盾")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].has_divine_shield is True

    def test_give_taunt(self, fresh_state, dispatcher):
        card = _bc_card("战吼：获得嘲讽")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.board[0].has_taunt is True

    def test_silence_enemy(self, fresh_state, dispatcher):
        enemy = Minion(name="Enemy", attack=5, health=5, max_health=5,
                       has_taunt=True, has_divine_shield=True, owner="enemy")
        fresh_state.opponent.board.append(enemy)
        card = _bc_card("战吼：沉默一个随从")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        silenced = result.opponent.board[0]
        assert silenced.has_taunt is False
        assert silenced.has_divine_shield is False

    def test_destroy_enemy_minion(self, fresh_state, dispatcher):
        fresh_state.opponent.board.append(
            Minion(name="Big Threat", attack=8, health=8, max_health=8, owner="enemy")
        )
        card = _bc_card("战吼：消灭一个随从")
        minion = Minion(name="Test", attack=2, health=2, max_health=2)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert len(result.opponent.board) == 0


class TestBattlecryNoEffect:
    """Cards without battlecry should be safe."""

    def test_vanilla_card_no_effect(self, fresh_state, dispatcher):
        card = _bc_card("", mechanics=[])
        minion = Minion(name="Yeti", attack=4, health=5, max_health=5)
        fresh_state.board.append(minion)

        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.opponent.hero.hp == 30
        assert len(result.board) == 1

    def test_empty_text_safe(self, fresh_state, dispatcher):
        card = _bc_card("")
        minion = Minion(name="Vanilla", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)
        result = dispatcher.dispatch(fresh_state, card, minion)
        assert result.hero.hp == 30

    def test_module_level_dispatch(self, fresh_state):
        """Module-level convenience function works."""
        card = _bc_card("战吼：造成1点伤害")
        minion = Minion(name="Test", attack=1, health=1, max_health=1)
        fresh_state.board.append(minion)
        result = dispatch_battlecry(fresh_state, card, minion)
        assert result.opponent.hero.hp == 29

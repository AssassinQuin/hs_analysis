#!/usr/bin/env python3
"""test_game_state.py — Tests for game state data model."""

import pytest

from hs_analysis.search.game_state import (
    Weapon,
    Minion,
    HeroState,
    ManaState,
    OpponentState,
    GameState,
)


# ------------------------------------------------------------------
# Weapon
# ------------------------------------------------------------------

def test_weapon_defaults():
    """Weapon with default values."""
    w = Weapon()
    assert w.attack == 0
    assert w.health == 0
    assert w.name == ""


# ------------------------------------------------------------------
# Minion
# ------------------------------------------------------------------

def test_minion_defaults():
    """Minion default flags are correct."""
    m = Minion()
    assert m.can_attack is False
    assert m.has_taunt is False
    assert m.has_divine_shield is False
    assert m.has_charge is False
    assert m.has_rush is False
    assert m.has_windfury is False
    assert m.has_stealth is False
    assert m.has_poisonous is False
    assert m.enchantments == []
    assert m.owner == "friendly"


# ------------------------------------------------------------------
# HeroState
# ------------------------------------------------------------------

def test_hero_state_defaults():
    """HeroState with defaults."""
    h = HeroState()
    assert h.hp == 30
    assert h.armor == 0
    assert h.weapon is None
    assert h.hero_power_used is False


# ------------------------------------------------------------------
# ManaState
# ------------------------------------------------------------------

def test_mana_state_defaults():
    """ManaState defaults."""
    m = ManaState()
    assert m.available == 0
    assert m.overloaded == 0
    assert m.max_mana == 0
    assert m.overload_next == 0


# ------------------------------------------------------------------
# OpponentState
# ------------------------------------------------------------------

def test_opponent_state_secrets():
    """OpponentState has secrets list."""
    opp = OpponentState()
    assert isinstance(opp.secrets, list)
    assert opp.secrets == []


def test_opponent_secrets_field():
    """secrets field exists and is a list on OpponentState."""
    opp = OpponentState(secrets=['ICE_BLOCK'])
    assert opp.secrets == ['ICE_BLOCK']


# ------------------------------------------------------------------
# GameState
# ------------------------------------------------------------------

def test_game_state_copy_deep():
    """copy() produces a deep copy; modifying copy doesn't affect original."""
    state = GameState(
        hero=HeroState(hp=25, armor=3),
        board=[Minion(name='Test', attack=3, health=3, max_health=3)],
        mana=ManaState(available=5, max_mana=7),
    )
    copy = state.copy()

    # Modify copy
    copy.hero.hp = 1
    copy.board[0].attack = 99
    copy.mana.available = 0

    # Original unchanged
    assert state.hero.hp == 25
    assert state.board[0].attack == 3
    assert state.mana.available == 5


def test_is_lethal_true():
    """Opponent hp <= 0 → is_lethal() True."""
    state = GameState(opponent=OpponentState(hero=HeroState(hp=0)))
    assert state.is_lethal() is True


def test_is_lethal_false():
    """Opponent hp > 0 → is_lethal() False."""
    state = GameState(opponent=OpponentState(hero=HeroState(hp=1)))
    assert state.is_lethal() is False


def test_is_lethal_with_armor():
    """Opponent hp=0 but armor=5 → is_lethal() False."""
    state = GameState(
        opponent=OpponentState(hero=HeroState(hp=0, armor=5))
    )
    assert state.is_lethal() is False


def test_board_full_true():
    """7 minions → board_full() True."""
    board = [Minion(name=f'M{i}') for i in range(7)]
    state = GameState(board=board)
    assert state.board_full() is True


def test_board_full_false():
    """3 minions → board_full() False."""
    board = [Minion(name=f'M{i}') for i in range(3)]
    state = GameState(board=board)
    assert state.board_full() is False


def test_has_taunt():
    """Minion with taunt → has_taunt_on_board() True."""
    state = GameState(board=[Minion(has_taunt=True)])
    assert state.has_taunt_on_board() is True


def test_no_taunt():
    """No taunt minions → has_taunt_on_board() False."""
    state = GameState(board=[Minion(has_taunt=False)])
    assert state.has_taunt_on_board() is False


def test_get_total_attack():
    """Sum of minion attacks + weapon."""
    state = GameState(
        board=[
            Minion(attack=3),
            Minion(attack=5),
        ],
        hero=HeroState(weapon=Weapon(attack=4)),
    )
    assert state.get_total_attack() == 12  # 3 + 5 + 4


def test_deck_list_field():
    """deck_list field exists and is Optional[List]."""
    state = GameState()
    assert state.deck_list is None
    state2 = GameState(deck_list=['card1', 'card2'])
    assert state2.deck_list == ['card1', 'card2']

import pytest
pytest.skip("Deleted module", allow_module_level=True)
# -*- coding: utf-8 -*-
"""Tests for ZoneManager — zone-based card instance management."""
import pytest

from analysis.card.models.card import Card
from analysis.search.entity import Zone, CardInstance, EntityId, next_entity_id
from analysis.search.zone_manager import ZoneManager


# ── Helpers ───────────────────────────────────────────────────────────

def _minion(**overrides) -> Card:
    """Create a minimal MINION card."""
    defaults = dict(dbf_id=1, name="Test Minion", cost=2, card_type="MINION",
                    attack=3, health=3)
    defaults.update(overrides)
    return Card(**defaults)


def _spell(**overrides) -> Card:
    """Create a minimal SPELL card."""
    defaults = dict(dbf_id=2, name="Test Spell", cost=1, card_type="SPELL")
    defaults.update(overrides)
    return Card(**defaults)


def _location(**overrides) -> Card:
    """Create a minimal LOCATION card."""
    defaults = dict(dbf_id=3, name="Test Location", cost=1, card_type="LOCATION",
                    health=3)
    defaults.update(overrides)
    return Card(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────

class TestZoneManagerCreation:
    def test_empty_creation(self):
        zm = ZoneManager()
        assert zm.hand == []
        assert zm.deck == []
        assert zm.board == []
        assert zm.graveyard == []
        assert zm.secrets == []
        assert zm.setaside == []
        assert zm.deck_size == 0
        assert zm.hand_size == 0


class TestAddToHand:
    def test_add_to_hand_from_card(self):
        zm = ZoneManager()
        card = _minion()
        ci = zm.add_to_hand(card)
        assert zm.hand_size == 1
        assert isinstance(ci, CardInstance)
        assert ci.zone == Zone.HAND
        assert ci.card is card
        assert ci in zm.hand

    def test_add_to_hand_from_instance(self):
        zm = ZoneManager()
        card = _minion()
        ci = CardInstance(entity_id=next_entity_id(), card=card, zone=Zone.DECK)
        returned = zm.add_to_hand(ci)
        assert returned is ci
        assert ci.zone == Zone.HAND
        assert zm.hand_size == 1


class TestAddToDeck:
    def test_add_to_deck(self):
        zm = ZoneManager()
        card = _minion()
        ci = zm.add_to_deck(card)
        assert zm.deck_size == 1
        assert ci.zone == Zone.DECK
        assert ci.card is card

    def test_add_to_deck_from_instance(self):
        zm = ZoneManager()
        card = _minion()
        ci = CardInstance(entity_id=next_entity_id(), card=card)
        returned = zm.add_to_deck(ci)
        assert returned is ci
        assert ci.zone == Zone.DECK
        assert zm.deck_size == 1


class TestSummonToBoard:
    def test_summon_to_board(self):
        zm = ZoneManager()
        card = _minion()
        ci = zm.summon_to_board(card)
        assert len(zm.board) == 1
        assert ci.zone == Zone.PLAY
        assert ci.card is card
        assert not zm.board_full()

    def test_summon_to_board_full(self):
        zm = ZoneManager()
        for i in range(7):
            ci = zm.summon_to_board(_minion(dbf_id=i, name=f"M{i}"))
            assert ci is not None
        assert zm.board_full()
        result = zm.summon_to_board(_minion())
        assert result is None
        assert len(zm.board) == 7

    def test_summon_to_board_at_position(self):
        zm = ZoneManager()
        c0 = zm.summon_to_board(_minion(name="A"))
        c1 = zm.summon_to_board(_minion(name="B"))
        c2 = zm.summon_to_board(_minion(name="C"), position=0)
        assert zm.board[0].name == "C"
        assert zm.board[1].name == "A"
        assert zm.board[2].name == "B"


class TestDraw:
    def test_draw(self):
        zm = ZoneManager()
        card = _minion(name="DrawMe")
        zm.add_to_deck(card)
        assert zm.deck_size == 1

        drawn = zm.draw()
        assert drawn is not None
        assert drawn.card.name == "DrawMe"
        assert drawn.zone == Zone.HAND
        assert zm.deck_size == 0

    def test_draw_empty_deck(self):
        zm = ZoneManager()
        result = zm.draw()
        assert result is None


class TestMove:
    def test_move_hand_to_play(self):
        zm = ZoneManager()
        card = _minion()
        ci = zm.add_to_hand(card)
        assert ci.zone == Zone.HAND
        assert zm.hand_size == 1

        moved = zm.move(ci, Zone.PLAY)
        assert moved is ci
        assert ci.zone == Zone.PLAY
        assert zm.hand_size == 0
        assert len(zm.board) == 1
        assert ci in zm.board

    def test_move_with_position(self):
        zm = ZoneManager()
        c0 = zm.summon_to_board(_minion(name="A"))
        c1 = zm.summon_to_board(_minion(name="B"))
        ci = zm.add_to_hand(_minion(name="C"))

        zm.move(ci, Zone.PLAY, position=0)
        assert len(zm.board) == 3
        assert zm.board[0].name == "C"
        assert zm.board[1].name == "A"
        assert zm.board[2].name == "B"


class TestDestroyMinion:
    def test_destroy_minion(self):
        zm = ZoneManager()
        ci = zm.summon_to_board(_minion(name="Doomed"))
        assert len(zm.board) == 1

        destroyed = zm.destroy_minion(ci.entity_id)
        assert destroyed is ci
        assert ci.zone == Zone.GRAVEYARD
        assert len(zm.board) == 0
        assert ci in zm.graveyard


class TestCopyIsolation:
    def test_copy_isolation(self):
        zm = ZoneManager()
        zm.add_to_hand(_minion(name="H1"))
        zm.add_to_deck(_minion(name="D1"))
        zm.summon_to_board(_minion(name="B1"))

        zm_copy = zm.copy()
        # Mutate the copy
        zm_copy.add_to_hand(_minion(name="H2"))

        assert zm_copy.hand_size == 2
        assert zm.hand_size == 1  # original unchanged


class TestFilters:
    def test_dead_minions_filter(self):
        zm = ZoneManager()
        minion = _minion(name="DeadMinion")
        spell = _spell(name="DeadSpell")

        m_ci = zm.add_to_hand(minion)
        s_ci = zm.add_to_hand(spell)
        zm.graveyard.append(m_ci)
        zm.graveyard.append(s_ci)
        m_ci.zone = Zone.GRAVEYARD
        s_ci.zone = Zone.GRAVEYARD

        dead = zm.dead_minions()
        assert len(dead) == 1
        assert dead[0].card.name == "DeadMinion"

    def test_board_minions_and_locations(self):
        zm = ZoneManager()
        zm.summon_to_board(_minion(name="M1"))
        zm.summon_to_board(_location(name="L1"))
        zm.summon_to_board(_minion(name="M2"))

        assert len(zm.board_minions()) == 2
        assert len(zm.board_locations()) == 1
        assert zm.board_minions()[0].name == "M1"
        assert zm.board_locations()[0].name == "L1"


class TestHasTaunt:
    def test_has_taunt_true(self):
        zm = ZoneManager()
        taunt_card = _minion(name="Tank", mechanics=["TAUNT"])
        zm.summon_to_board(taunt_card)
        assert zm.has_taunt() is True

    def test_has_taunt_false(self):
        zm = ZoneManager()
        plain = _minion(name="NoTaunt", mechanics=[])
        zm.summon_to_board(plain)
        assert zm.has_taunt() is False

    def test_has_taunt_empty_board(self):
        zm = ZoneManager()
        assert zm.has_taunt() is False


class TestRemoveById:
    def test_remove_by_id(self):
        zm = ZoneManager()
        ci = zm.add_to_hand(_minion(name="RemoveMe"))
        assert zm.hand_size == 1

        removed = zm._remove_by_id(ci.entity_id)
        assert removed is ci
        assert zm.hand_size == 0

    def test_remove_by_id_not_found(self):
        zm = ZoneManager()
        fake_id = EntityId(99999)
        result = zm._remove_by_id(fake_id)
        assert result is None


class TestRepr:
    def test_repr(self):
        zm = ZoneManager()
        zm.add_to_hand(_minion())
        zm.add_to_deck(_minion())
        zm.summon_to_board(_minion())
        r = repr(zm)
        assert "hand=1" in r
        assert "deck=1" in r
        assert "board=1" in r
        assert "graveyard=0" in r
        assert "secrets=0" in r
        assert r.startswith("ZoneManager(")

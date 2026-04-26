"""V10 Phase 3 Batch 1 tests — GameState + HeroState expansion."""

import pytest
from analysis.engine.state import GameState, HeroState, Minion
from analysis.models.card import Card
from analysis.search.abilities import apply_action, Action, ActionType


def _make_card(**kw):
    defaults = dict(dbf_id=1, name="TestCard", cost=1, card_type="MINION")
    defaults.update(kw)
    return Card(**defaults)


def _make_state(**kw):
    defaults = dict()
    defaults.update(kw)
    return GameState(**defaults)


class TestHeroStateExpansion:
    def test_imbue_level_field_exists(self):
        h = HeroState()
        assert hasattr(h, 'imbue_level')
        assert h.imbue_level == 0

    def test_imbue_level_custom_value(self):
        h = HeroState(imbue_level=5)
        assert h.imbue_level == 5


class TestGameStateExpansion:
    def test_herald_count_field(self):
        gs = GameState()
        assert hasattr(gs, 'herald_count')
        assert gs.herald_count == 0

    def test_last_turn_races_field(self):
        gs = GameState()
        assert hasattr(gs, 'last_turn_races')
        assert gs.last_turn_races == set()

    def test_last_turn_schools_field(self):
        gs = GameState()
        assert hasattr(gs, 'last_turn_schools')
        assert gs.last_turn_schools == set()

    def test_active_quests_field(self):
        gs = GameState()
        assert hasattr(gs, 'active_quests')
        assert gs.active_quests == []

    def test_copy_deep_copies_new_fields(self):
        gs = GameState()
        gs.herald_count = 3
        gs.last_turn_races = {'DRAGON'}
        gs.last_turn_schools = {'FIRE'}
        gs.active_quests = ['q1']
        gs.hero.imbue_level = 2

        gs2 = gs.copy()

        # Modify original
        gs.herald_count = 99
        gs.last_turn_races.add('BEAST')
        gs.last_turn_schools.add('FROST')
        gs.active_quests.append('q2')
        gs.hero.imbue_level = 99

        # Copy should be independent
        assert gs2.herald_count == 3
        assert gs2.last_turn_races == {'DRAGON'}
        assert gs2.last_turn_schools == {'FIRE'}
        assert gs2.active_quests == ['q1']
        assert gs2.hero.imbue_level == 2


class TestEndTurnKindredSnapshot:
    def test_end_turn_snapshots_races(self):
        card1 = _make_card(name="DragonCard", race='DRAGON')
        card2 = _make_card(name="BeastCard", race='BEAST')
        gs = _make_state()
        gs.mana.available = 10
        gs.mana.max_mana = 10
        gs.hand = [card1, card2]

        # Play two minions
        gs2 = apply_action(gs, Action(action_type=ActionType.PLAY, card_index=0, position=0))
        gs3 = apply_action(gs2, Action(action_type=ActionType.PLAY, card_index=0, position=1))
        # End turn
        gs4 = apply_action(gs3, Action(action_type=ActionType.END_TURN))

        assert 'DRAGON' in gs4.last_turn_races
        assert 'BEAST' in gs4.last_turn_races

    def test_end_turn_clears_races_if_no_cards(self):
        gs = _make_state()
        gs.last_turn_races = {'DRAGON'}
        gs.last_turn_schools = {'FIRE'}
        gs2 = apply_action(gs, Action(action_type=ActionType.END_TURN))

        # No cards played this turn, so races/schools should be empty
        assert gs2.last_turn_races == set()
        assert gs2.last_turn_schools == set()

    def test_end_turn_snapshots_spell_schools(self):
        card = _make_card(name="FireSpell", cost=1, card_type='SPELL')
        card.spell_school = 'FIRE'
        gs = _make_state()
        gs.mana.available = 10
        gs.mana.max_mana = 10
        gs.hand = [card]

        gs2 = apply_action(gs, Action(action_type=ActionType.PLAY, card_index=0))
        gs3 = apply_action(gs2, Action(action_type=ActionType.END_TURN))

        assert 'FIRE' in gs3.last_turn_schools

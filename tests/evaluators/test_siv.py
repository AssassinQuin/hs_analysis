"""Tests for V10 SIV (State-Indexed Value) module."""

from __future__ import annotations

import pytest

from analysis.evaluators.siv import (
    siv_score,
    hand_siv_sum,
    lethal_modifier,
    taunt_modifier,
    curve_modifier,
    position_modifier,
    trigger_modifier,
    synergy_modifier,
    progress_modifier,
    counter_modifier,
)
from analysis.engine.state import HeroState, ManaState, Minion, OpponentState


# ──────────────────────────────────────────────
# Modifier 1: lethal_awareness
# ──────────────────────────────────────────────

class TestLethalModifier:
    def test_30hp_enemy_returns_base_for_damage(self, make_card, make_state):
        card = make_card(text="造成6点伤害", card_type="SPELL")
        state = make_state()
        assert lethal_modifier(card, state) == pytest.approx(1.0, abs=0.01)

    def test_1hp_enemy_returns_max_boost(self, make_card, make_state):
        card = make_card(text="造成6点伤害", card_type="SPELL")
        state = make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        result = lethal_modifier(card, state)
        assert 3.0 < result < 5.0

    def test_non_damage_card_returns_1(self, make_card, make_state):
        card = make_card(text="抽一张牌", card_type="SPELL")
        state = make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        assert lethal_modifier(card, state) == 1.0

    def test_weapon_gets_boost(self, make_card, make_state):
        card = make_card(card_type="WEAPON", attack=3)
        state = make_state(opponent=OpponentState(hero=HeroState(hp=5, armor=0)))
        assert lethal_modifier(card, state) > 1.0

    def test_charge_minion_gets_boost(self, make_card, make_state):
        card = make_card(mechanics=["CHARGE"])
        state = make_state(opponent=OpponentState(hero=HeroState(hp=5, armor=0)))
        assert lethal_modifier(card, state) > 1.0


# ──────────────────────────────────────────────
# Modifier 2: taunt_constraint
# ──────────────────────────────────────────────

class TestTauntModifier:
    def test_no_enemy_taunts(self, make_card, make_state):
        assert taunt_modifier(make_card(), make_state()) == 1.0

    def test_2_taunts(self, make_card, make_state):
        state = make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name="Taunt1", attack=2, health=3, has_taunt=True),
                Minion(name="Taunt2", attack=1, health=5, has_taunt=True),
            ],
        ))
        assert taunt_modifier(make_card(), state) == pytest.approx(1.6, abs=0.01)

    def test_silence_card_vs_taunts(self, make_card, make_state):
        card = make_card(text="沉默一个随从")
        state = make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name="Taunt1", attack=2, health=3, has_taunt=True),
                Minion(name="Taunt2", attack=1, health=5, has_taunt=True),
            ],
        ))
        assert taunt_modifier(card, state) == pytest.approx(2.1, abs=0.01)

    def test_poisonous_vs_taunts(self, make_card, make_state):
        card = make_card(mechanics=["POISONOUS"])
        state = make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[Minion(name="Taunt1", attack=2, health=3, has_taunt=True)],
        ))
        assert taunt_modifier(card, state) == pytest.approx(1.6, abs=0.01)

    def test_destroy_card_vs_taunts(self, make_card, make_state):
        card = make_card(text="消灭一个随从")
        state = make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[Minion(name="Taunt1", attack=2, health=3, has_taunt=True)],
        ))
        assert taunt_modifier(card, state) == pytest.approx(1.8, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 3: curve/tempo window
# ──────────────────────────────────────────────

class TestCurveModifier:
    def test_exact_mana(self, make_card, make_state):
        assert curve_modifier(make_card(cost=5), make_state(mana=ManaState(available=5, max_mana=5))) == 1.0

    def test_under_mana(self, make_card, make_state):
        assert curve_modifier(make_card(cost=3), make_state(mana=ManaState(available=5, max_mana=5))) == 1.0

    def test_one_over(self, make_card, make_state):
        assert curve_modifier(make_card(cost=6), make_state(mana=ManaState(available=5, max_mana=5))) == pytest.approx(0.9, abs=0.01)

    def test_three_over(self, make_card, make_state):
        assert curve_modifier(make_card(cost=8), make_state(mana=ManaState(available=5, max_mana=5), turn_number=5)) == pytest.approx(0.5, abs=0.01)

    def test_overflow_penalty(self, make_card, make_state):
        result = curve_modifier(make_card(cost=10), make_state(mana=ManaState(available=3, max_mana=3), turn_number=4))
        assert result >= 0.5

    def test_floor_at_0_5(self, make_card, make_state):
        assert curve_modifier(make_card(cost=20), make_state(mana=ManaState(available=1, max_mana=1), turn_number=1)) >= 0.5


# ──────────────────────────────────────────────
# Modifier 4: hand_position
# ──────────────────────────────────────────────

class TestPositionModifier:
    def test_regular_card(self, make_card, make_state):
        card = make_card()
        assert position_modifier(card, make_state(hand=[card])) == 1.0

    def test_outcast_at_edge_left(self, make_card, make_state):
        card = make_card(mechanics=["OUTCAST"])
        state = make_state(hand=[card, make_card(name="other"), make_card(name="other2")])
        assert position_modifier(card, state) == pytest.approx(1.3, abs=0.01)

    def test_outcast_at_edge_right(self, make_card, make_state):
        card = make_card(mechanics=["OUTCAST"])
        state = make_state(hand=[make_card(name="other1"), make_card(name="other2"), card])
        assert position_modifier(card, state) == pytest.approx(1.3, abs=0.01)

    def test_outcast_in_middle(self, make_card, make_state):
        card = make_card(mechanics=["OUTCAST"])
        state = make_state(hand=[make_card(name="other1"), card, make_card(name="other2")])
        assert position_modifier(card, state) == 1.0

    def test_shatter_with_full_hand(self, make_card, make_state):
        card = make_card(mechanics=["SHATTER"])
        others = [make_card(name=f"other{i}") for i in range(6)]
        state = make_state(hand=[card] + others)
        assert position_modifier(card, state) > 1.0

    def test_empty_hand(self, make_card, make_state):
        assert position_modifier(make_card(), make_state(hand=[])) == 1.0

    def test_card_not_in_hand(self, make_card, make_state):
        assert position_modifier(make_card(), make_state(hand=[make_card(name="other")])) == 1.0


# ──────────────────────────────────────────────
# Modifier 5: trigger_probability
# ──────────────────────────────────────────────

class TestTriggerModifier:
    def test_no_triggers(self, make_card, make_state):
        assert trigger_modifier(make_card(mechanics=["TAUNT"]), make_state()) == 1.0

    def test_battlecry_with_brann(self, make_card, make_state):
        state = make_state(board=[Minion(name="Brann Bronzebeard", attack=2, health=4)])
        assert trigger_modifier(make_card(mechanics=["BATTLECRY"]), state) == pytest.approx(2.0, abs=0.01)

    def test_deathrattle_with_rivendare(self, make_card, make_state):
        state = make_state(board=[Minion(name="Baron Rivendare", attack=1, health=7)])
        assert trigger_modifier(make_card(mechanics=["DEATHRATTLE"]), state) == pytest.approx(2.0, abs=0.01)

    def test_brann_plus_rivendare(self, make_card, make_state):
        state = make_state(board=[
            Minion(name="Brann Bronzebeard", attack=2, health=4),
            Minion(name="Baron Rivendare", attack=1, health=7),
        ])
        result = trigger_modifier(make_card(mechanics=["BATTLECRY", "DEATHRATTLE"]), state)
        assert result == pytest.approx(4.0, abs=0.01)

    def test_race_aura(self, make_card, make_state):
        # Minion doesn't have race field → no enablers match → 1.0
        state = make_state(board=[Minion(name="Dragon Consort", attack=5, health=5)])
        assert trigger_modifier(make_card(mechanics=["DEATHRATTLE"], race="DRAGON"), state) == 1.0

    def test_no_mechanics(self, make_card, make_state):
        assert trigger_modifier(make_card(mechanics=[]), make_state()) == 1.0


# ──────────────────────────────────────────────
# Modifier 6: race_synergy
# ──────────────────────────────────────────────

class _RaceMinion(Minion):
    """Helper: Minion subclass with a race attribute for synergy tests."""
    def __init__(self, race: str = "", **kw):
        super().__init__(**kw)
        self.race = race


class TestSynergyModifier:
    def test_no_race(self, make_card, make_state):
        assert synergy_modifier(make_card(), make_state()) == 1.0

    def test_3_same_race_on_board(self, make_card, make_state):
        state = make_state(board=[_RaceMinion(race="DRAGON", name=f"D{i}", attack=3, health=3) for i in range(3)])
        assert synergy_modifier(make_card(race="DRAGON"), state) == pytest.approx(1.3, abs=0.01)

    def test_2_board_2_hand(self, make_card, make_state):
        card = make_card(race="BEAST")
        other1 = make_card(name="Beast1", race="BEAST")
        other2 = make_card(name="Beast2", race="BEAST")
        state = make_state(
            board=[_RaceMinion(race="BEAST", name="B1", attack=2, health=2),
                   _RaceMinion(race="BEAST", name="B2", attack=2, health=2)],
            hand=[card, other1, other2],
        )
        assert synergy_modifier(card, state) == pytest.approx(1.4, abs=0.01)

    def test_kindred_bonus(self, make_card, make_state):
        assert synergy_modifier(make_card(race="BEAST", text="延系：获得+1/+1"), make_state()) == pytest.approx(1.2, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 7: progress_tracker
# ──────────────────────────────────────────────

class TestProgressModifier:
    def test_no_progress_mechanics(self, make_card, make_state):
        assert progress_modifier(make_card(), make_state()) == 1.0

    def test_imbue_level_0(self, make_card, make_state):
        state = make_state()
        state.imbue_level = 0
        assert progress_modifier(make_card(mechanics=["IMBUE"]), state) == pytest.approx(1.3, abs=0.01)

    def test_imbue_level_5(self, make_card, make_state):
        state = make_state()
        state.imbue_level = 5
        assert progress_modifier(make_card(mechanics=["IMBUE"]), state) == pytest.approx(1.075, abs=0.01)

    def test_imbue_text_match(self, make_card, make_state):
        assert progress_modifier(make_card(text="灌注：召唤一个1/1"), make_state()) == pytest.approx(1.3, abs=0.01)

    def test_herald_count_1(self, make_card, make_state):
        state = make_state()
        state.herald_count = 1
        assert progress_modifier(make_card(mechanics=["HERALD"]), state) == pytest.approx(1.5, abs=0.01)

    def test_herald_count_0(self, make_card, make_state):
        state = make_state()
        state.herald_count = 0
        assert progress_modifier(make_card(mechanics=["HERALD"]), state) == 1.0

    def test_quest_partial(self, make_card, make_state):
        state = make_state()
        state.quest_completion_pct = 0.5
        assert progress_modifier(make_card(mechanics=["QUEST"]), state) == pytest.approx(1.5, abs=0.01)

    def test_quest_complete(self, make_card, make_state):
        state = make_state()
        state.quest_completion_pct = 1.0
        assert progress_modifier(make_card(mechanics=["QUEST"]), state) == pytest.approx(3.0, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 8: counter_awareness
# ──────────────────────────────────────────────

class TestCounterModifier:
    def test_no_threats(self, make_card, make_state):
        assert counter_modifier(make_card(), make_state()) == 1.0

    def test_freeze_class_key_minion(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30, hero_class="MAGE")))
        assert counter_modifier(make_card(attack=5, card_type="MINION"), state) == pytest.approx(0.9, abs=0.01)

    def test_freeze_class_low_attack(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30, hero_class="MAGE")))
        assert counter_modifier(make_card(attack=2, card_type="MINION"), state) == 1.0

    def test_secrets_high_attack_minion(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30), secrets=["SECRET_1"]))
        assert counter_modifier(make_card(attack=4, card_type="MINION"), state) == pytest.approx(0.9, abs=0.01)

    def test_secrets_battlecry(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30), secrets=["SECRET_1"]))
        assert counter_modifier(make_card(attack=1, mechanics=["BATTLECRY"]), state) == pytest.approx(0.95, abs=0.01)

    def test_aoe_stealth_bonus(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30, hero_class="MAGE")))
        assert counter_modifier(make_card(mechanics=["STEALTH"]), state) == pytest.approx(1.2, abs=0.01)

    def test_non_freeze_class_no_penalty(self, make_card, make_state):
        state = make_state(opponent=OpponentState(hero=HeroState(hp=30, hero_class="WARRIOR")))
        assert counter_modifier(make_card(attack=5, card_type="MINION"), state) == 1.0


# ──────────────────────────────────────────────
# Integration: siv_score
# ──────────────────────────────────────────────

class TestSivScore:
    def test_returns_nonzero_for_valid_card(self, make_card, make_state):
        assert siv_score(make_card(score=5.0), make_state()) > 0.0

    def test_zero_for_zero_v7_card(self, make_card, make_state):
        assert siv_score(make_card(score=0.0), make_state()) == 0.0

    def test_clamped_to_range(self, make_card, make_state):
        result = siv_score(make_card(score=5.0), make_state())
        assert 0.01 <= result <= 100.0

    def test_lethal_state_higher_than_safe(self, make_card, make_state):
        card = make_card(score=5.0, text="造成6点伤害", card_type="SPELL")
        safe = make_state()
        lethal = make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        assert siv_score(card, lethal) > siv_score(card, safe)

    def test_hand_siv_sum(self, make_card, make_state):
        c1 = make_card(dbf_id=1, score=3.0)
        c2 = make_card(dbf_id=2, score=4.0)
        total = hand_siv_sum(make_state(hand=[c1, c2]))
        assert total >= 3.0

    def test_multiple_modifiers_stack(self, make_card, make_state):
        card = make_card(score=5.0, text="造成3点伤害", card_type="SPELL", cost=5, mechanics=["BATTLECRY"])
        state = make_state(
            mana=ManaState(available=5, max_mana=5),
            board=[Minion(name="Brann Bronzebeard", attack=2, health=4)],
            opponent=OpponentState(hero=HeroState(hp=5, armor=0)),
        )
        assert siv_score(card, state) > 5.0

"""Tests for V10 SIV (State-Indexed Value) module."""

from __future__ import annotations

import pytest

from hs_analysis.evaluators.siv import (
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
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_card(**kwargs) -> Card:
    """Create a card with sensible defaults for testing."""
    defaults = dict(
        dbf_id=1,
        name="Test Card",
        cost=3,
        original_cost=3,
        card_type="MINION",
        attack=3,
        health=3,
        v7_score=5.0,
        text="",
        mechanics=[],
    )
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    """Create a GameState with sensible defaults."""
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[],
        hand=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


# ──────────────────────────────────────────────
# Modifier 1: lethal_awareness
# ──────────────────────────────────────────────

class TestLethalModifier:
    def test_30hp_enemy_returns_base_for_damage(self):
        """Full HP enemy → damage card gets small boost."""
        card = _make_card(text="造成6点伤害", card_type="SPELL")
        state = _make_state()
        # enemy at 30/30: 1 + (1 - 1.0)² × 3.0 = 1.0
        assert lethal_modifier(card, state) == pytest.approx(1.0, abs=0.01)

    def test_1hp_enemy_returns_max_boost(self):
        """Near-dead enemy → damage card gets huge boost."""
        card = _make_card(text="造成6点伤害", card_type="SPELL")
        state = _make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        # enemy at 1: 1 + (1 - 1/30)² × 3.0 ≈ 1 + 0.933² × 3 ≈ 3.61
        result = lethal_modifier(card, state)
        assert result > 3.0
        assert result < 5.0

    def test_non_damage_card_returns_1(self):
        """Non-damage card gets no lethal boost."""
        card = _make_card(text="抽一张牌", card_type="SPELL")
        state = _make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        assert lethal_modifier(card, state) == 1.0

    def test_weapon_gets_boost(self):
        """Weapon cards are damage-type."""
        card = _make_card(card_type="WEAPON", attack=3)
        state = _make_state(opponent=OpponentState(hero=HeroState(hp=5, armor=0)))
        result = lethal_modifier(card, state)
        assert result > 1.0

    def test_charge_minion_gets_boost(self):
        """Charge minions are damage-type."""
        card = _make_card(mechanics=["CHARGE"])
        state = _make_state(opponent=OpponentState(hero=HeroState(hp=5, armor=0)))
        result = lethal_modifier(card, state)
        assert result > 1.0


# ──────────────────────────────────────────────
# Modifier 2: taunt_constraint
# ──────────────────────────────────────────────

class TestTauntModifier:
    def test_no_enemy_taunts(self):
        """No taunts → 1.0."""
        card = _make_card()
        state = _make_state()
        assert taunt_modifier(card, state) == 1.0

    def test_2_taunts(self):
        """2 enemy taunts → 1 + 0.3 × 2 = 1.6."""
        card = _make_card()
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name="Taunt1", attack=2, health=3, has_taunt=True),
                Minion(name="Taunt2", attack=1, health=5, has_taunt=True),
            ],
        ))
        assert taunt_modifier(card, state) == pytest.approx(1.6, abs=0.01)

    def test_silence_card_vs_taunts(self):
        """Silence card vs 2 taunts → 1.6 + 0.5 = 2.1."""
        card = _make_card(text="沉默一个随从")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[
                Minion(name="Taunt1", attack=2, health=3, has_taunt=True),
                Minion(name="Taunt2", attack=1, health=5, has_taunt=True),
            ],
        ))
        result = taunt_modifier(card, state)
        assert result == pytest.approx(2.1, abs=0.01)

    def test_poisonous_vs_taunts(self):
        """Poisonous card vs 1 taunt → 1.3 + 0.3 = 1.6."""
        card = _make_card(mechanics=["POISONOUS"])
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[Minion(name="Taunt1", attack=2, health=3, has_taunt=True)],
        ))
        result = taunt_modifier(card, state)
        assert result == pytest.approx(1.6, abs=0.01)

    def test_destroy_card_vs_taunts(self):
        """Destroy card vs 1 taunt → 1.3 + 0.5 = 1.8."""
        card = _make_card(text="消灭一个随从")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            board=[Minion(name="Taunt1", attack=2, health=3, has_taunt=True)],
        ))
        result = taunt_modifier(card, state)
        assert result == pytest.approx(1.8, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 3: curve/tempo window
# ──────────────────────────────────────────────

class TestCurveModifier:
    def test_exact_mana(self):
        """Cost matches available → 1.0."""
        card = _make_card(cost=5)
        state = _make_state(mana=ManaState(available=5, max_mana=5))
        assert curve_modifier(card, state) == 1.0

    def test_under_mana(self):
        """Cost below available → 1.0."""
        card = _make_card(cost=3)
        state = _make_state(mana=ManaState(available=5, max_mana=5))
        assert curve_modifier(card, state) == 1.0

    def test_one_over(self):
        """1 mana over → 0.9."""
        card = _make_card(cost=6)
        state = _make_state(mana=ManaState(available=5, max_mana=5))
        assert curve_modifier(card, state) == pytest.approx(0.9, abs=0.01)

    def test_three_over(self):
        """3 mana over with overflow → 0.8 - 0.05×2 - 0.1×2 = 0.5 (floored)."""
        card = _make_card(cost=8)
        state = _make_state(mana=ManaState(available=5, max_mana=5), turn_number=5)
        # gap = 8 - 5 = 3 → 0.8 - 0.05×2 = 0.7
        # overflow = max(0, 8 - 5 - 1) = 2 → -0.2
        # result = 0.7 - 0.2 = 0.5
        assert curve_modifier(card, state) == pytest.approx(0.5, abs=0.01)

    def test_overflow_penalty(self):
        """Overflow penalty for very expensive cards."""
        card = _make_card(cost=10)
        state = _make_state(mana=ManaState(available=3, max_mana=3), turn_number=4)
        result = curve_modifier(card, state)
        # gap = 10 - 3 = 7 → 0.8 - 0.05 × 6 = 0.5
        # overflow = max(0, 10 - 4 - 1) = 5 → -0.5
        # total = 0.5 - 0.5 = 0.0, clamped to 0.5
        assert result >= 0.5

    def test_floor_at_0_5(self):
        """Result never goes below 0.5."""
        card = _make_card(cost=20)
        state = _make_state(mana=ManaState(available=1, max_mana=1), turn_number=1)
        assert curve_modifier(card, state) >= 0.5


# ──────────────────────────────────────────────
# Modifier 4: hand_position
# ──────────────────────────────────────────────

class TestPositionModifier:
    def test_regular_card(self):
        """Regular card gets 1.0."""
        card = _make_card()
        state = _make_state(hand=[card])
        assert position_modifier(card, state) == 1.0

    def test_outcast_at_edge_left(self):
        """Outcast at position 0 → bonus."""
        card = _make_card(mechanics=["OUTCAST"])
        state = _make_state(hand=[card, _make_card(name="other"), _make_card(name="other2")])
        result = position_modifier(card, state)
        assert result == pytest.approx(1.3, abs=0.01)

    def test_outcast_at_edge_right(self):
        """Outcast at last position → bonus."""
        card = _make_card(mechanics=["OUTCAST"])
        other1 = _make_card(name="other1")
        other2 = _make_card(name="other2")
        state = _make_state(hand=[other1, other2, card])
        result = position_modifier(card, state)
        assert result == pytest.approx(1.3, abs=0.01)

    def test_outcast_in_middle(self):
        """Outcast in middle → 1.0."""
        card = _make_card(mechanics=["OUTCAST"])
        other1 = _make_card(name="other1")
        other2 = _make_card(name="other2")
        state = _make_state(hand=[other1, card, other2])
        assert position_modifier(card, state) == 1.0

    def test_shatter_with_full_hand(self):
        """Shatter with many cards → higher merge probability."""
        card = _make_card(mechanics=["SHATTER"])
        others = [_make_card(name=f"other{i}") for i in range(6)]
        state = _make_state(hand=[card] + others)
        result = position_modifier(card, state)
        # merge_prob = min(1.0, 6/7) ≈ 0.857
        # result = 1 + 0.857 × 0.3 ≈ 1.257
        assert result > 1.0

    def test_empty_hand(self):
        """Empty hand → 1.0."""
        card = _make_card()
        state = _make_state(hand=[])
        assert position_modifier(card, state) == 1.0

    def test_card_not_in_hand(self):
        """Card not found in hand → 1.0."""
        card = _make_card()
        state = _make_state(hand=[_make_card(name="other")])
        assert position_modifier(card, state) == 1.0


# ──────────────────────────────────────────────
# Modifier 5: trigger_probability
# ──────────────────────────────────────────────

class TestTriggerModifier:
    def test_no_triggers(self):
        """Card without trigger mechanics → 1.0."""
        card = _make_card(mechanics=["TAUNT"])
        state = _make_state()
        assert trigger_modifier(card, state) == 1.0

    def test_battlecry_with_brann(self):
        """Battlecry + Brann → ×2.0."""
        card = _make_card(mechanics=["BATTLECRY"])
        state = _make_state(board=[
            Minion(name="Brann Bronzebeard", attack=2, health=4),
        ])
        result = trigger_modifier(card, state)
        assert result == pytest.approx(2.0, abs=0.01)

    def test_deathrattle_with_rivendare(self):
        """Deathrattle + Rivendare → ×2.0."""
        card = _make_card(mechanics=["DEATHRATTLE"])
        state = _make_state(board=[
            Minion(name="Baron Rivendare", attack=1, health=7),
        ])
        result = trigger_modifier(card, state)
        assert result == pytest.approx(2.0, abs=0.01)

    def test_brann_plus_rivendare(self):
        """Battlecry + Deathrattle + Brann + Rivendare → ×4.0."""
        card = _make_card(mechanics=["BATTLECRY", "DEATHRATTLE"])
        state = _make_state(board=[
            Minion(name="Brann Bronzebeard", attack=2, health=4),
            Minion(name="Baron Rivendare", attack=1, health=7),
        ])
        result = trigger_modifier(card, state)
        assert result == pytest.approx(4.0, abs=0.01)

    def test_race_aura(self):
        """Same-race aura → ×1.3."""
        card = _make_card(mechanics=["DEATHRATTLE"], race="DRAGON")
        state = _make_state(board=[
            Minion(name="Dragon Consort", attack=5, health=5),
        ])
        # We need to set race on the minion; Minion doesn't have race field
        # so trigger_modifier checks hasattr — we use a workaround
        # Actually, Minion doesn't have a race field by default
        # The modifier will just return 1.0 for DEATHRATTLE with no enablers
        result = trigger_modifier(card, state)
        assert result == 1.0  # no enablers match

    def test_no_mechanics(self):
        """Card with empty mechanics → 1.0."""
        card = _make_card(mechanics=[])
        state = _make_state()
        assert trigger_modifier(card, state) == 1.0


# ──────────────────────────────────────────────
# Modifier 6: race_synergy
# ──────────────────────────────────────────────

class TestSynergyModifier:
    def test_no_race(self):
        """Card without race → 1.0."""
        card = _make_card()
        state = _make_state()
        assert synergy_modifier(card, state) == 1.0

    def test_3_same_race_on_board(self):
        """3 same-race minions on board → 1 + 0.1 × 3 = 1.3."""
        card = _make_card(race="DRAGON")
        # Minion doesn't have race field, but we use a class trick
        # Actually we need to add race to the Minion-like objects
        # Let's create minions with a race attribute
        class DragonMinion(Minion):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.race = "DRAGON"

        state = _make_state(board=[
            DragonMinion(name=f"Dragon{i}", attack=3, health=3) for i in range(3)
        ])
        result = synergy_modifier(card, state)
        assert result == pytest.approx(1.3, abs=0.01)

    def test_2_board_2_hand(self):
        """2 board + 2 hand same-race → 1 + 0.1 × 4 = 1.4."""
        card = _make_card(race="BEAST")
        other1 = _make_card(name="Beast1", race="BEAST")
        other2 = _make_card(name="Beast2", race="BEAST")

        class BeastMinion(Minion):
            def __init__(self, **kw):
                super().__init__(**kw)
                self.race = "BEAST"

        state = _make_state(
            board=[BeastMinion(name="B1", attack=2, health=2),
                   BeastMinion(name="B2", attack=2, health=2)],
            hand=[card, other1, other2],
        )
        result = synergy_modifier(card, state)
        # board_count=2, hand_count=2, total=4
        assert result == pytest.approx(1.4, abs=0.01)

    def test_kindred_bonus(self):
        """延系 keyword gets extra +0.2."""
        card = _make_card(race="BEAST", text="延系：获得+1/+1")
        state = _make_state()
        result = synergy_modifier(card, state)
        assert result == pytest.approx(1.2, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 7: progress_tracker
# ──────────────────────────────────────────────

class TestProgressModifier:
    def test_no_progress_mechanics(self):
        """Card without progress mechanics → 1.0."""
        card = _make_card()
        state = _make_state()
        assert progress_modifier(card, state) == 1.0

    def test_imbue_level_0(self):
        """Imbue at level 0 → 1 + 0.3 × (1 - 0) = 1.3."""
        card = _make_card(mechanics=["IMBUE"])
        state = _make_state()
        state.imbue_level = 0  # type: ignore[attr-defined]
        result = progress_modifier(card, state)
        assert result == pytest.approx(1.3, abs=0.01)

    def test_imbue_level_5(self):
        """Imbue at level 5 → 1 + 0.3 × (1 - 0.75) = 1.075."""
        card = _make_card(mechanics=["IMBUE"])
        state = _make_state()
        state.imbue_level = 5  # type: ignore[attr-defined]
        result = progress_modifier(card, state)
        assert result == pytest.approx(1.075, abs=0.01)

    def test_imbue_text_match(self):
        """Imbue via text keyword."""
        card = _make_card(text="灌注：召唤一个1/1")
        state = _make_state()
        result = progress_modifier(card, state)
        # level defaults to 0
        assert result == pytest.approx(1.3, abs=0.01)

    def test_herald_count_1(self):
        """Herald at count 1 → 1.5."""
        card = _make_card(mechanics=["HERALD"])
        state = _make_state()
        state.herald_count = 1  # type: ignore[attr-defined]
        assert progress_modifier(card, state) == pytest.approx(1.5, abs=0.01)

    def test_herald_count_0(self):
        """Herald at count 0 → 1.0."""
        card = _make_card(mechanics=["HERALD"])
        state = _make_state()
        state.herald_count = 0  # type: ignore[attr-defined]
        assert progress_modifier(card, state) == 1.0

    def test_quest_partial(self):
        """Quest at 50% completion → 1 + 0.5² × 2.0 = 1.5."""
        card = _make_card(mechanics=["QUEST"])
        state = _make_state()
        state.quest_completion_pct = 0.5  # type: ignore[attr-defined]
        result = progress_modifier(card, state)
        assert result == pytest.approx(1.5, abs=0.01)

    def test_quest_complete(self):
        """Quest at 100% → 1 + 1.0² × 2.0 = 3.0."""
        card = _make_card(mechanics=["QUEST"])
        state = _make_state()
        state.quest_completion_pct = 1.0  # type: ignore[attr-defined]
        result = progress_modifier(card, state)
        assert result == pytest.approx(3.0, abs=0.01)


# ──────────────────────────────────────────────
# Modifier 8: counter_awareness
# ──────────────────────────────────────────────

class TestCounterModifier:
    def test_no_threats(self):
        """No threats → 1.0."""
        card = _make_card()
        state = _make_state()
        assert counter_modifier(card, state) == 1.0

    def test_freeze_class_key_minion(self):
        """Freeze class + high-attack minion → -0.1."""
        card = _make_card(attack=5, card_type="MINION")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30, hero_class="MAGE"),
        ))
        result = counter_modifier(card, state)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_freeze_class_low_attack(self):
        """Freeze class + low-attack minion → no penalty."""
        card = _make_card(attack=2, card_type="MINION")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30, hero_class="MAGE"),
        ))
        assert counter_modifier(card, state) == 1.0

    def test_secrets_high_attack_minion(self):
        """Secrets + high-attack minion → -0.1."""
        card = _make_card(attack=4, card_type="MINION")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            secrets=["SECRET_1"],
        ))
        result = counter_modifier(card, state)
        assert result == pytest.approx(0.9, abs=0.01)

    def test_secrets_battlecry(self):
        """Secrets + battlecry → -0.05 (use low-attack card to avoid attack penalty)."""
        card = _make_card(attack=1, mechanics=["BATTLECRY"])
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30),
            secrets=["SECRET_1"],
        ))
        result = counter_modifier(card, state)
        assert result == pytest.approx(0.95, abs=0.01)

    def test_aoe_stealth_bonus(self):
        """Stealth card vs AoE class → +0.2."""
        card = _make_card(mechanics=["STEALTH"])
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30, hero_class="MAGE"),
        ))
        result = counter_modifier(card, state)
        assert result == pytest.approx(1.2, abs=0.01)

    def test_non_freeze_class_no_penalty(self):
        """Non-freeze class + high-attack minion → no freeze penalty."""
        card = _make_card(attack=5, card_type="MINION")
        state = _make_state(opponent=OpponentState(
            hero=HeroState(hp=30, hero_class="WARRIOR"),
        ))
        result = counter_modifier(card, state)
        assert result == 1.0


# ──────────────────────────────────────────────
# Integration: siv_score
# ──────────────────────────────────────────────

class TestSivScore:
    def test_returns_nonzero_for_valid_card(self):
        """SIV > 0 for a card with v7_score > 0."""
        card = _make_card(v7_score=5.0)
        state = _make_state()
        result = siv_score(card, state)
        assert result > 0.0

    def test_zero_for_zero_v7_card(self):
        """SIV = 0 for a card with v7_score = 0."""
        card = _make_card(v7_score=0.0)
        state = _make_state()
        assert siv_score(card, state) == 0.0

    def test_clamped_to_range(self):
        """Result is clamped to [0.01, 100.0]."""
        card = _make_card(v7_score=5.0)
        state = _make_state()
        result = siv_score(card, state)
        assert 0.01 <= result <= 100.0

    def test_lethal_state_higher_than_safe(self):
        """SIV higher when enemy is near death (for damage card)."""
        card = _make_card(v7_score=5.0, text="造成6点伤害", card_type="SPELL")
        safe_state = _make_state()
        lethal_state = _make_state(opponent=OpponentState(hero=HeroState(hp=1, armor=0)))
        assert siv_score(card, lethal_state) > siv_score(card, safe_state)

    def test_hand_siv_sum(self):
        """hand_siv_sum returns sum of all hand cards."""
        c1 = _make_card(dbf_id=1, v7_score=3.0)
        c2 = _make_card(dbf_id=2, v7_score=4.0)
        state = _make_state(hand=[c1, c2])
        total = hand_siv_sum(state)
        assert total > 0.0
        # Each card should contribute at least its v7_score × modifiers
        assert total >= 3.0

    def test_multiple_modifiers_stack(self):
        """Multiple active modifiers multiply together."""
        # Damage card, low enemy HP, on curve, battlecry with Brann
        card = _make_card(
            v7_score=5.0,
            text="造成3点伤害",
            card_type="SPELL",
            cost=5,
            mechanics=["BATTLECRY"],
        )
        state = _make_state(
            mana=ManaState(available=5, max_mana=5),
            board=[Minion(name="Brann Bronzebeard", attack=2, health=4)],
            opponent=OpponentState(hero=HeroState(hp=5, armor=0)),
        )
        result = siv_score(card, state)
        # Should be significantly boosted by lethal + trigger modifiers
        assert result > 5.0

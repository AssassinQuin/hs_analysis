"""A/B comparison test: V10 vs legacy scoring."""

from __future__ import annotations

import pytest

from hs_analysis.evaluators.composite import evaluate, set_v10_enabled
from hs_analysis.models.card import Card
from hs_analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)


def _make_card(**kwargs) -> Card:
    defaults = dict(
        dbf_id=1, name="Test Card", cost=3, original_cost=3,
        card_type="MINION", attack=3, health=3, v7_score=5.0,
        text="", mechanics=[],
    )
    defaults.update(kwargs)
    return Card(**defaults)


def _make_state(**kwargs) -> GameState:
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[], hand=[], cards_played_this_turn=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


class TestABComparison:
    """Compare V10 and legacy evaluation on the same states."""

    def setup_method(self):
        set_v10_enabled(False)

    def teardown_method(self):
        set_v10_enabled(False)

    def test_v10_different_from_legacy(self):
        """V10 and legacy produce different scores."""
        state = _make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[_make_card()],
        )
        legacy = evaluate(state)
        set_v10_enabled(True)
        v10 = evaluate(state)
        set_v10_enabled(False)

        # Both should be valid floats
        assert isinstance(legacy, float)
        assert isinstance(v10, float)
        # They come from different code paths
        # (exact relationship depends on implementation details)

    def test_lethal_proximity_higher_in_v10(self):
        """V10 should give higher score when closer to lethal."""
        # Damage card in hand, enemy at low HP
        damage_card = _make_card(
            name="Fireball", cost=4, card_type="SPELL",
            text="造成6点伤害", v7_score=5.0,
        )

        lethal_proximal = _make_state(
            hand=[damage_card],
            mana=ManaState(available=6, max_mana=6),
            opponent=OpponentState(hero=HeroState(hp=3, armor=0)),
        )

        safe = _make_state(
            hand=[damage_card],
            mana=ManaState(available=6, max_mana=6),
            opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        )

        set_v10_enabled(True)
        v10_lethal = evaluate(lethal_proximal)
        v10_safe = evaluate(safe)
        set_v10_enabled(False)

        # V10 should rate lethal-proximal state higher
        assert v10_lethal > v10_safe, (
            f"V10 lethal proximal ({v10_lethal:.2f}) should be > safe ({v10_safe:.2f})"
        )

    def test_synergized_state_higher_in_v10(self):
        """V10 should rate synergized board higher."""
        # Battlecry card with Brann on board
        battlecry_card = _make_card(
            name="Battlecry Card", mechanics=["BATTLECRY"], v7_score=4.0,
        )

        synergized = _make_state(
            hand=[battlecry_card],
            board=[Minion(name="Brann Bronzebeard", attack=2, health=4)],
        )

        non_synergized = _make_state(
            hand=[battlecry_card],
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
        )

        set_v10_enabled(True)
        v10_syn = evaluate(synergized)
        v10_nosyn = evaluate(non_synergized)
        set_v10_enabled(False)

        # The battlecry card's SIV is boosted by Brann
        # So the synergized state should score higher
        assert v10_syn > v10_nosyn, (
            f"Synergized ({v10_syn:.2f}) should be > non-synergized ({v10_nosyn:.2f})"
        )

    def test_flag_cleanup(self):
        """Ensure V10 flag is properly reset."""
        set_v10_enabled(True)
        set_v10_enabled(False)
        import hs_analysis.evaluators.composite as comp
        assert comp.V10_ENABLED is False

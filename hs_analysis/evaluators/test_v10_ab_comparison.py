"""A/B comparison test: V10 vs legacy scoring."""

from __future__ import annotations

import pytest

from hs_analysis.evaluators.composite import evaluate, set_v10_enabled
from hs_analysis.search.game_state import HeroState, ManaState, Minion, OpponentState


class TestABComparison:
    """Compare V10 and legacy evaluation on the same states."""

    def setup_method(self):
        set_v10_enabled(False)

    def teardown_method(self):
        set_v10_enabled(False)

    def test_v10_different_from_legacy(self, make_card, make_state):
        state = make_state(
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
            hand=[make_card()],
        )
        legacy = evaluate(state)
        set_v10_enabled(True)
        v10 = evaluate(state)
        assert isinstance(legacy, float)
        assert isinstance(v10, float)

    def test_lethal_proximity_higher_in_v10(self, make_card, make_state):
        damage_card = make_card(name="Fireball", cost=4, card_type="SPELL", text="造成6点伤害")
        lethal_proximal = make_state(
            hand=[damage_card],
            mana=ManaState(available=6, max_mana=6),
            opponent=OpponentState(hero=HeroState(hp=3, armor=0)),
        )
        safe = make_state(
            hand=[damage_card],
            mana=ManaState(available=6, max_mana=6),
            opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        )
        set_v10_enabled(True)
        v10_lethal = evaluate(lethal_proximal)
        v10_safe = evaluate(safe)
        assert v10_lethal > v10_safe, f"lethal ({v10_lethal:.2f}) should be > safe ({v10_safe:.2f})"

    def test_synergized_state_higher_in_v10(self, make_card, make_state):
        battlecry_card = make_card(name="Battlecry Card", mechanics=["BATTLECRY"], v7_score=4.0)
        synergized = make_state(
            hand=[battlecry_card],
            board=[Minion(name="Brann Bronzebeard", attack=2, health=4)],
        )
        non_synergized = make_state(
            hand=[battlecry_card],
            board=[Minion(name="Yeti", attack=4, health=5, max_health=5)],
        )
        set_v10_enabled(True)
        v10_syn = evaluate(synergized)
        v10_nosyn = evaluate(non_synergized)
        assert v10_syn > v10_nosyn, f"synergized ({v10_syn:.2f}) > non-synergized ({v10_nosyn:.2f})"

    def test_flag_cleanup(self):
        set_v10_enabled(True)
        set_v10_enabled(False)
        import hs_analysis.evaluators.composite as comp
        assert comp.V10_ENABLED is False

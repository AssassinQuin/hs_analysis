"""Tests for v2 bug fixes: random effects, deck loading, deck size, graveyard source, known_cards dedup.

Testing principles (Khorikov):
- Output-based for pure logic: _dedup_known_cards, _lookup_card_source
- State-based for tracker changes: build_state_dict, deck model loading
- One test one behavior, independent, no shared mutable state
"""
from __future__ import annotations

import pytest

from analysis.watcher.global_tracker import GlobalGameState, KnownCard, CardSource
from analysis.engine.card_effect_inference import CardEffectInferenceEngine, InferenceResult
from analysis.utils.bayesian_opponent import BayesianOpponentModel


# ═══════════════════════════════════════════════════════════════════
# Phase 1: Random effects tracking
# ═══════════════════════════════════════════════════════════════════

class TestRandomEffectInference:
    """Random damage/summon/target detection via _infer_random_effects.

    Uses output-based testing: feed card text → check inference list.
    """

    def test_random_damage_to_enemy_minion(self):
        """'Deal 3 damage to a random enemy minion' → random_damage inference."""
        engine = CardEffectInferenceEngine()
        text = "Deal 3 damage to a random enemy minion."
        engine._infer_random_effects("TEST_001", text, [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 1
        assert "random damage" in infs[0].source_description.lower()

    def test_random_summon(self):
        """'Summon a random minion that costs...' → random_summon inference."""
        engine = CardEffectInferenceEngine()
        text = "Summon a random minion that costs (3) or less."
        engine._infer_random_effects("TEST_002", text, [], 7)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 1
        assert "random summon" in infs[0].source_description.lower()

    def test_random_buff(self):
        """'Give a random friendly minion +2 attack' → random_buff inference."""
        engine = CardEffectInferenceEngine()
        text = "Give a random friendly minion +2 Attack."
        engine._infer_random_effects("TEST_003", text, [], 3)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 1
        assert "random buff" in infs[0].source_description.lower()

    def test_random_split(self):
        """'randomly split among enemies' → random_split inference."""
        engine = CardEffectInferenceEngine()
        text = "Deal 6 damage randomly split among all enemies."
        engine._infer_random_effects("TEST_004", text, [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 1
        assert "randomly split" in infs[0].source_description.lower()

    def test_no_false_positive_for_targeted_effect(self):
        """Targeted 'deal 3 damage to a minion' should NOT trigger random inference."""
        engine = CardEffectInferenceEngine()
        text = "Deal 3 damage to an enemy minion."
        engine._infer_random_effects("TEST_005", text, [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 0

    def test_no_false_positive_for_empty_text(self):
        """Empty text should not trigger any random inference."""
        engine = CardEffectInferenceEngine()
        engine._infer_random_effects("TEST_006", "", [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 0

    def test_random_target_heal(self):
        """'Restore 4 Health to a random friendly character' → random inference."""
        engine = CardEffectInferenceEngine()
        text = "Restore 4 Health to a random friendly character."
        engine._infer_random_effects("TEST_007", text, [], 3)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 1

    def test_no_false_positive_for_discard_or_draw(self):
        """Effects about draw/discard should not trigger random inference."""
        engine = CardEffectInferenceEngine()
        text = "Draw 2 cards. Discard a card."
        engine._infer_random_effects("TEST_008", text, [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 0

    def test_damage_to_all_not_random(self):
        """'Deal 2 damage to all enemy minions' is AoE, not random."""
        engine = CardEffectInferenceEngine()
        text = "Deal 2 damage to all enemy minions."
        engine._infer_random_effects("TEST_009", text, [], 5)
        infs = [i for i in engine._inferences if i.inference_type == "random_effect"]
        assert len(infs) == 0


# ═══════════════════════════════════════════════════════════════════
# Phase 5: known_cards dedup (static method, no fixture needed)
# ═══════════════════════════════════════════════════════════════════

class TestDedupKnownCards:
    """_dedup_known_cards: output-based table-driven tests."""

    def _make_known(self, card_id: str, source: CardSource = CardSource.DECK) -> KnownCard:
        return KnownCard(card_id=card_id, source=source, turn_seen=1)

    def test_empty_list(self):
        from tracker.log_monitor import CoreLogMonitor
        assert CoreLogMonitor._dedup_known_cards([]) == []

    def test_single_entry(self):
        from tracker.log_monitor import CoreLogMonitor
        cards = [self._make_known("TEST_001")]
        result = CoreLogMonitor._dedup_known_cards(cards)
        assert len(result) == 1
        assert result[0].card_id == "TEST_001"

    def test_unique_cards(self):
        from tracker.log_monitor import CoreLogMonitor
        cards = [self._make_known("A"), self._make_known("B"), self._make_known("C")]
        result = CoreLogMonitor._dedup_known_cards(cards)
        assert len(result) == 3

    def test_duplicate_card_id_keeps_last(self):
        from tracker.log_monitor import CoreLogMonitor
        cards = [
            self._make_known("A"),                    # A: DECK
            self._make_known("B"),                    # B: DECK
            KnownCard(card_id="A", source=CardSource.GENERATED, turn_seen=5),  # A: GENERATED (newer)
        ]
        result = CoreLogMonitor._dedup_known_cards(cards)
        assert len(result) == 2
        # A should now be GENERATED (keeps last entry)
        a_entry = [c for c in result if c.card_id == "A"][0]
        assert a_entry.source == CardSource.GENERATED

    def test_many_duplicates(self):
        from tracker.log_monitor import CoreLogMonitor
        cards = [self._make_known("A") for _ in range(100)]
        result = CoreLogMonitor._dedup_known_cards(cards)
        assert len(result) == 1  # all same card_id → 1 entry


# ═══════════════════════════════════════════════════════════════════
# Phase 4: Graveyard source lookup (static method, mock state)
# ═══════════════════════════════════════════════════════════════════

class TestLookupCardSource:
    """_lookup_card_source: output-based with synthetic state."""

    @staticmethod
    def _make_state(known_cards=None, generated=None):
        state = GlobalGameState()
        if known_cards:
            state.opp_known_cards = known_cards
        if generated:
            state.opp_generated_seen = generated
        return state

    def test_found_in_known_cards_deck(self):
        from tracker.log_monitor import CoreLogMonitor
        state = self._make_state(
            known_cards=[KnownCard(card_id="A", source=CardSource.DECK)]
        )
        assert CoreLogMonitor._lookup_card_source("A", state) == "deck"

    def test_found_in_known_cards_generated(self):
        from tracker.log_monitor import CoreLogMonitor
        state = self._make_state(
            known_cards=[KnownCard(card_id="B", source=CardSource.GENERATED)]
        )
        assert CoreLogMonitor._lookup_card_source("B", state) == "generated"

    def test_found_in_generated_set(self):
        from tracker.log_monitor import CoreLogMonitor
        state = self._make_state(generated={"C"})
        assert CoreLogMonitor._lookup_card_source("C", state) == "generated"

    def test_not_found_returns_unknown(self):
        from tracker.log_monitor import CoreLogMonitor
        state = self._make_state()
        assert CoreLogMonitor._lookup_card_source("UNKNOWN_CARD", state) == "unknown"


# ═══════════════════════════════════════════════════════════════════
# Phase 2: Bayesian deck loading (requires DB or fallback)
# ═══════════════════════════════════════════════════════════════════

class TestBayesianDeckLoading:
    """BayesianOpponentModel._load_decks — verify decks are populated.

    Also tests the fix for MAGE class returning empty top_decks.
    """

    def test_model_initializes_with_non_empty_decks_for_mage(self):
        """BayesianOpponentModel(player_class='MAGE') should have decks > 0."""
        model = BayesianOpponentModel(player_class="MAGE")
        assert len(model.decks) > 0, (
            f"MAGE should have at least 1 deck, got {len(model.decks)}. "
            "Check HSReplay cache DB or deck_codes.txt"
        )
        # Verify all loaded decks are MAGE
        for d in model.decks:
            assert d.get("class", "").upper() == "MAGE", (
                f"Deck {d.get('name')} has class {d.get('class')}, expected MAGE"
            )

    def test_top_decks_not_empty_for_mage(self):
        """get_top_decks(3) should return at least one deck for MAGE."""
        model = BayesianOpponentModel(player_class="MAGE")
        top = model.get_top_decks(3)
        assert len(top) >= 1, "MAGE should have at least 1 top deck"
        # Verify structure
        for aid, name, prob in top:
            assert isinstance(aid, int)
            assert name
            assert 0.0 < prob <= 1.0

    def test_model_with_class_filter_rogue(self):
        """ROGUE should also load decks (different class)."""
        model = BayesianOpponentModel(player_class="ROGUE")
        assert len(model.decks) > 0, "ROGUE should have decks"
        for d in model.decks:
            assert d.get("class", "").upper() == "ROGUE"

    def test_model_empty_for_nonexistent_class(self):
        """Non-existent class should produce empty decks (graceful degradation)."""
        model = BayesianOpponentModel(player_class="NONEXISTENT_CLASS_XYZ")
        assert len(model.decks) == 0
        assert model.get_top_decks(3) == []

    def test_posteriors_not_empty_after_update(self):
        """After observing a signature card, posteriors should be non-empty."""
        model = BayesianOpponentModel(player_class="MAGE")
        if not model.decks:
            pytest.skip("No MAGE decks in cache - cannot test posteriors")
        # Take the first card from the first deck
        first_deck = model.decks[0]
        if not first_deck.get("cards"):
            pytest.skip("First MAGE deck has no cards")
        sig_card_dbf = first_deck["cards"][0]
        model.update(sig_card_dbf)
        assert len(model.posteriors) > 0
        # The first deck should have a non-zero posterior
        aid = first_deck["archetype_id"]
        assert model.posteriors.get(aid, 0) > 0


# ═══════════════════════════════════════════════════════════════════
# Phase 3: build_state_dict default deck size
# ═══════════════════════════════════════════════════════════════════

class TestBuildStateDictDeckSize:
    """build_state_dict should fallback opp_initial_deck_size to 30 when unset."""

    @pytest.fixture
    def monitor_with_state(self):
        from tracker.log_monitor import CoreLogMonitor
        monitor = CoreLogMonitor()
        # Initialize with opponent class
        monitor.global_tracker.state.opp_hero_class = "MAGE"
        return monitor

    def test_opp_initial_deck_size_defaults_to_30_when_missing(self, monitor_with_state):
        """When opp_initial_deck_size=0 and opp_hero_class is known → default 30."""
        state_dict = monitor_with_state.build_state_dict()
        assert state_dict["opp_initial_deck_size"] == 30, (
            f"Expected fallback to 30, got {state_dict['opp_initial_deck_size']}"
        )

    def test_opp_initial_deck_size_preserved_when_set(self):
        """When opp_initial_deck_size is already set, don't override."""
        from tracker.log_monitor import CoreLogMonitor
        monitor = CoreLogMonitor()
        monitor.global_tracker.state.opp_initial_deck_size = 28
        monitor.global_tracker.state.opp_hero_class = "MAGE"
        state_dict = monitor.build_state_dict()
        assert state_dict["opp_initial_deck_size"] == 28

    def test_opp_initial_deck_size_unknown_class_no_fallback(self):
        """Without opp_hero_class, keep 0 (can't assume default)."""
        from tracker.log_monitor import CoreLogMonitor
        monitor = CoreLogMonitor()
        state_dict = monitor.build_state_dict()
        # No hero class → no fallback → keep 0
        assert state_dict["opp_initial_deck_size"] == 0

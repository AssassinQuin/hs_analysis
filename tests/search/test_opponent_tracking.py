"""Tests for opponent tracking features.

Covers:
- GlobalTracker shuffle-into-deck tracking (ZONE_SETASIDE→ZONE_DECK transitions)
- GlobalTracker corrupt upgrade detection (card_id changes in opponent hand)
- OpponentState new fields (corpses, herald, quests, shuffled, corrupted, weapon)
- StateBridge enrichment from GlobalGameState
- BayesianOpponentModel.conditional_evidence
"""

from __future__ import annotations

import pytest

from analysis.watcher.global_tracker import (
    CardSource,
    GlobalGameState,
    GlobalTracker,
    KnownCard,
)
from analysis.watcher.state_bridge import StateBridge
from analysis.search.game_state import GameState, OpponentState
from analysis.utils.bayesian_opponent import BayesianOpponentModel


# Zone constants (from analysis.constants.hs_enums)
ZONE_PLAY = 1
ZONE_DECK = 2
ZONE_HAND = 3
ZONE_GRAVEYARD = 4
ZONE_SETASIDE = 6


# ---------------------------------------------------------------------------
# TestShuffleIntoDeck
# ---------------------------------------------------------------------------


class TestShuffleIntoDeck:
    """Tests for GlobalTracker.on_zone_change() shuffle-into-deck tracking.

    When new_zone == ZONE_DECK and card_id is provided, the card_id is
    appended to the appropriate list (opp or player shuffled_into_deck).
    """

    def test_opponent_shuffle_into_deck(self):
        """Opponent shuffles a card into deck (SETASIDE→DECK)."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_zone_change(
            entity_id=100,
            controller=2,
            old_zone=ZONE_SETASIDE,
            new_zone=ZONE_DECK,
            card_id="CFM_621",
        )

        assert tracker.state.opp_shuffled_into_deck == ["CFM_621"]
        assert tracker.state.player_shuffled_into_deck == []

    def test_player_shuffle_into_deck(self):
        """Player shuffles a card into deck (SETASIDE→DECK)."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_zone_change(
            entity_id=101,
            controller=1,
            old_zone=ZONE_SETASIDE,
            new_zone=ZONE_DECK,
            card_id="CFM_621",
        )

        assert tracker.state.player_shuffled_into_deck == ["CFM_621"]
        assert tracker.state.opp_shuffled_into_deck == []

    def test_no_card_id_ignored(self):
        """Zone change with empty card_id does not append to list."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # First: valid shuffle
        tracker.on_zone_change(
            entity_id=100,
            controller=2,
            old_zone=ZONE_SETASIDE,
            new_zone=ZONE_DECK,
            card_id="CFM_621",
        )
        # Second: no card_id
        tracker.on_zone_change(
            entity_id=102,
            controller=2,
            old_zone=ZONE_GRAVEYARD,
            new_zone=ZONE_DECK,
            card_id="",
        )

        assert len(tracker.state.opp_shuffled_into_deck) == 1
        assert tracker.state.opp_shuffled_into_deck == ["CFM_621"]

    def test_multiple_shuffles_tracked(self):
        """Multiple shuffles are all tracked in order."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_zone_change(
            entity_id=100,
            controller=2,
            old_zone=ZONE_SETASIDE,
            new_zone=ZONE_DECK,
            card_id="CFM_621",
        )
        tracker.on_zone_change(
            entity_id=101,
            controller=2,
            old_zone=ZONE_GRAVEYARD,
            new_zone=ZONE_DECK,
            card_id="CFM_621",
        )
        tracker.on_zone_change(
            entity_id=102,
            controller=2,
            old_zone=ZONE_SETASIDE,
            new_zone=ZONE_DECK,
            card_id="LOE_077",
        )

        assert tracker.state.opp_shuffled_into_deck == ["CFM_621", "CFM_621", "LOE_077"]


# ---------------------------------------------------------------------------
# TestCorruptTracking
# ---------------------------------------------------------------------------


class TestCorruptTracking:
    """Tests for GlobalTracker.on_show_entity() corrupt upgrade detection.

    When an entity_id already exists in opp_hand_card_ids and the new
    card_id differs while the zone is still HAND, a corrupt upgrade is
    recorded.
    """

    def test_corrupt_upgrade_detected(self):
        """Card in opponent hand changes card_id → corrupt upgrade."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        # First: SHOW_ENTITY reveals card in opponent hand
        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230",
            controller=2,
            zone=ZONE_HAND,
        )
        assert tracker.state.opp_hand_card_ids[50] == ("SCH_230", ZONE_HAND)

        # Second: Same entity revealed again with corrupt-upgraded card_id
        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230t",
            controller=2,
            zone=ZONE_HAND,
        )

        assert tracker.state.opp_corrupted_cards == ["SCH_230"]
        assert tracker.state.opp_corrupted_upgrades == {"SCH_230": "SCH_230t"}

    def test_same_card_id_no_corrupt(self):
        """Same entity, same card_id, same zone → no corrupt recorded."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230",
            controller=2,
            zone=ZONE_HAND,
        )
        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230",
            controller=2,
            zone=ZONE_HAND,
        )

        assert tracker.state.opp_corrupted_cards == []
        assert tracker.state.opp_corrupted_upgrades == {}

    def test_zone_change_no_corrupt(self):
        """Card moves to PLAY zone → not a corrupt upgrade (zone != HAND)."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230",
            controller=2,
            zone=ZONE_HAND,
        )
        # Zone changed to PLAY — should NOT trigger corrupt
        tracker.on_show_entity(
            entity_id=50,
            card_id="SCH_230t",
            controller=2,
            zone=ZONE_PLAY,
        )

        assert tracker.state.opp_corrupted_cards == []
        assert tracker.state.opp_corrupted_upgrades == {}

    def test_first_show_entity_registers_in_hand(self):
        """First SHOW_ENTITY for an opponent card registers in opp_hand_card_ids."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=51,
            card_id="EX1_001",
            controller=2,
            zone=ZONE_HAND,
        )

        assert 51 in tracker.state.opp_hand_card_ids
        assert tracker.state.opp_hand_card_ids[51] == ("EX1_001", ZONE_HAND)


# ---------------------------------------------------------------------------
# TestOpponentStateFields
# ---------------------------------------------------------------------------


class TestOpponentStateFields:
    """Tests for OpponentState new dataclass fields and defaults."""

    def test_default_values(self):
        """All new fields have correct defaults (0, [], '')."""
        opp = OpponentState()

        assert opp.opp_corpses == 0
        assert opp.opp_herald_count == 0
        assert opp.opp_quests == []
        assert opp.opp_shuffled_into_deck == []
        assert opp.opp_corrupted_cards == []
        assert opp.opp_weapon_card_id == ""

    def test_custom_values(self):
        """Custom values are stored correctly."""
        opp = OpponentState(
            opp_corpses=5,
            opp_herald_count=3,
            opp_quests=[{"card_id": "QUEST_001", "progress": 2}],
            opp_shuffled_into_deck=["CFM_621"],
            opp_corrupted_cards=["SCH_230"],
            opp_weapon_card_id="CS3_015",
        )

        assert opp.opp_corpses == 5
        assert opp.opp_herald_count == 3
        assert len(opp.opp_quests) == 1
        assert opp.opp_quests[0]["card_id"] == "QUEST_001"
        assert opp.opp_shuffled_into_deck == ["CFM_621"]
        assert opp.opp_corrupted_cards == ["SCH_230"]
        assert opp.opp_weapon_card_id == "CS3_015"

    def test_lists_are_independent_per_instance(self):
        """Default list fields are not shared across instances."""
        opp1 = OpponentState()
        opp2 = OpponentState()

        opp1.opp_shuffled_into_deck.append("TEST_001")
        opp1.opp_corrupted_cards.append("TEST_002")
        opp1.opp_quests.append({"card_id": "TEST_003"})

        assert opp2.opp_shuffled_into_deck == []
        assert opp2.opp_corrupted_cards == []
        assert opp2.opp_quests == []


# ---------------------------------------------------------------------------
# TestStateBridgeEnrichment
# ---------------------------------------------------------------------------


class TestStateBridgeEnrichment:
    """Tests for StateBridge._enrich_from_global_state() populating
    opponent mechanics from GlobalGameState."""

    def _make_global_state(self) -> GlobalGameState:
        """Build a GlobalGameState with populated opponent tracking data."""
        ggs = GlobalGameState()
        ggs.opp_corpses = 5
        ggs.opp_herald_count = 3
        ggs.opp_shuffled_into_deck = ["CFM_621"]
        ggs.opp_corrupted_cards = ["SCH_230"]
        ggs.opp_weapon = "CS3_015"
        ggs.opp_known_cards = [KnownCard(card_id="TEST_001", turn_seen=3)]
        ggs.opp_generated_seen = {"GEN_001"}
        ggs.opp_secrets = ["EX1_132"]
        ggs.player_herald_count = 2
        ggs.player_corpses = 4
        return ggs

    def test_enrich_from_global_state_populates_opp_fields(self):
        """_enrich_from_global_state copies opponent data from GlobalGameState."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = self._make_global_state()

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert opp.opp_corpses == 5
        assert opp.opp_herald_count == 3
        assert opp.opp_shuffled_into_deck == ["CFM_621"]
        assert opp.opp_corrupted_cards == ["SCH_230"]
        assert opp.opp_weapon_card_id == "CS3_015"

    def test_enrich_populates_secrets(self):
        """_enrich_from_global_state copies active secrets."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = self._make_global_state()

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert opp.secrets == ["EX1_132"]

    def test_enrich_populates_known_cards(self):
        """_enrich_from_global_state serializes KnownCard objects."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = self._make_global_state()

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert len(opp.opp_known_cards) == 1
        assert opp.opp_known_cards[0]["card_id"] == "TEST_001"
        assert opp.opp_known_cards[0]["turn_seen"] == 3

    def test_enrich_populates_player_mechanics(self):
        """_enrich_from_global_state sets player-side fields on GameState."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = self._make_global_state()

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert gs.herald_count == 2
        assert gs.corpses == 4

    def test_enrich_with_empty_global_state(self):
        """_enrich_from_global_state with empty GlobalGameState → defaults."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = GlobalGameState()

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert opp.opp_corpses == 0
        assert opp.opp_herald_count == 0
        assert opp.opp_shuffled_into_deck == []
        assert opp.opp_corrupted_cards == []
        assert opp.opp_weapon_card_id == ""
        assert opp.secrets == []

    def test_enrich_generated_count(self):
        """_enrich_from_global_state sets opp_generated_count."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = GlobalGameState()
        ggs.opp_generated_seen = {"GEN_001", "GEN_002", "GEN_003"}

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert opp.opp_generated_count == 3

    def test_enrich_deck_remaining(self):
        """_enrich_from_global_state sets deck_remaining."""
        bridge = StateBridge(card_lookup=lambda _: None)
        opp = OpponentState()
        gs = GameState()
        ggs = GlobalGameState()
        ggs.opp_deck_remaining = 12

        bridge._enrich_from_global_state(opp, gs, ggs)

        assert opp.deck_remaining == 12


# ---------------------------------------------------------------------------
# TestConditionalEvidence
# ---------------------------------------------------------------------------


class TestConditionalEvidence:
    """Tests for BayesianOpponentModel.conditional_evidence().

    Without real archetype data loaded, the model returns empty posteriors.
    These tests verify the method exists, accepts correct arguments, and
    returns a dict.
    """

    def test_method_exists_and_returns_dict(self):
        """conditional_evidence() exists and returns a dict."""
        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = []
        model.posteriors = {}
        model.cards_by_dbf = {}
        model.locked = None
        model._seen_cards = []
        model.player_class = None

        result = model.conditional_evidence("HOLDING_RACE", "DRAGON")
        assert isinstance(result, dict)

    def test_returns_empty_when_no_decks(self):
        """With no decks loaded, returns empty dict."""
        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = []
        model.posteriors = {}
        model.cards_by_dbf = {}
        model.locked = None
        model._seen_cards = []
        model.player_class = None

        result = model.conditional_evidence("HOLDING_RACE", "DRAGON")
        assert result == {}

    def test_returns_posteriors_when_locked(self):
        """When locked (deck already identified), returns current posteriors."""
        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = []
        model.posteriors = {1: 0.8, 2: 0.2}
        model.cards_by_dbf = {}
        model.locked = (1, 0.8)
        model._seen_cards = []
        model.player_class = None

        result = model.conditional_evidence("HOLDING_RACE", "DRAGON")
        assert result == {1: 0.8, 2: 0.2}

    def test_unsupported_evidence_type_returns_posteriors(self):
        """Evidence type without matching handler returns posteriors unchanged."""
        model = BayesianOpponentModel.__new__(BayesianOpponentModel)
        model.decks = []
        model.posteriors = {}
        model.cards_by_dbf = {}
        model.locked = None
        model._seen_cards = []
        model.player_class = None

        result = model.conditional_evidence("UNKNOWN_TYPE", "value")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestFastResolvingSpell (GRAVEYARD zone on SHOW_ENTITY)
# ---------------------------------------------------------------------------


class TestFastResolvingSpell:
    """Tests for opponent spells that resolve so quickly that SHOW_ENTITY and
    TAG_CHANGE GRAVEYARD appear in the same log batch.

    When this happens, the entity_cache zone is already GRAVEYARD by the time
    _bridge_new_entities processes the entity. The on_show_entity handler must
    still recognise the card as "played" even though zone != PLAY.

    Regression test for: 对手使用永时火焰箭也没识别
    """

    CT_SPELL = 5  # CardType.SPELL

    def test_spell_in_graveyard_zone_recognised_as_played(self):
        """Opponent spell revealed directly in GRAVEYARD is recorded as played."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=200,
            card_id="END_025",  # 永时火焰箭
            controller=2,
            zone=ZONE_GRAVEYARD,
            card_type=self.CT_SPELL,
        )

        # Card should be in opp_known_cards
        assert len(tracker.state.opp_known_cards) == 1
        assert tracker.state.opp_known_cards[0].card_id == "END_025"

        # Card should be in opp_graveyard_seen
        assert "END_025" in tracker.state.opp_graveyard_seen

        # Stats: spells_played should be incremented
        assert tracker.state.opp_stats.spells_played == 1

    def test_enchantment_in_graveyard_not_played(self):
        """Enchantments in GRAVEYARD are NOT recorded as played (type filter)."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=201,
            card_id="ENCHANT_001",
            controller=2,
            zone=ZONE_GRAVEYARD,
            card_type=6,  # CT_ENCHANTMENT
        )

        assert len(tracker.state.opp_known_cards) == 0
        assert "ENCHANT_001" not in tracker.state.opp_graveyard_seen

    def test_spell_in_play_zone_still_works(self):
        """Normal path: spell revealed in PLAY zone is still recognised."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=202,
            card_id="CS2_029",  # 火球术
            controller=2,
            zone=ZONE_PLAY,
            card_type=self.CT_SPELL,
        )

        assert len(tracker.state.opp_known_cards) == 1
        assert tracker.state.opp_known_cards[0].card_id == "CS2_029"

    def test_spell_in_graveyard_not_added_to_board(self):
        """Spell in GRAVEYARD should NOT appear on opp_board_minions."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=203,
            card_id="END_025",
            controller=2,
            zone=ZONE_GRAVEYARD,
            card_type=self.CT_SPELL,
        )

        assert tracker.state.opp_board_minions == []

    def test_no_card_id_in_graveyard_ignored(self):
        """Entity in GRAVEYARD without card_id should not crash or record."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=204,
            card_id="",
            controller=2,
            zone=ZONE_GRAVEYARD,
            card_type=self.CT_SPELL,
        )

        assert len(tracker.state.opp_known_cards) == 0

    def test_duplicate_graveyard_entry_prevented(self):
        """Same card_id not duplicated in opp_graveyard_seen."""
        tracker = GlobalTracker(our_controller=1, opp_controller=2)

        tracker.on_show_entity(
            entity_id=205,
            card_id="END_025",
            controller=2,
            zone=ZONE_GRAVEYARD,
            card_type=self.CT_SPELL,
        )

        # Simulate zone change handler also trying to add
        tracker.state.opp_graveyard_seen.append("END_025")

        # Count should be 2 (once from on_show_entity, once from simulated add)
        # but our fix prevents duplicate from on_show_entity itself
        assert tracker.state.opp_graveyard_seen.count("END_025") >= 1

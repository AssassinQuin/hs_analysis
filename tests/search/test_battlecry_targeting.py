"""Tests for extended TargetResolver: MINION battlecry and LOCATION activation targeting.

Covers:
- SpellTargetResolver.resolve_targets() for MINION and LOCATION card types
- enumerate_legal_actions() generating PLAY_WITH_TARGET for battlecry minions
- Target encoding: 0=enemy hero, 1..N=enemy minion (1-indexed), -1..-M=friendly minion
"""

from __future__ import annotations

import pytest

from analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)
from analysis.search.engine.mechanics.spell_target_resolver import (
    SpellTargetResolver,
    TargetEntityType,
    TargetSide,
)
from analysis.search.abilities.actions import ActionType
from analysis.models.card import Card
from analysis.search.abilities.enumeration import enumerate_legal_actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCard:
    """Minimal card-like object for resolver tests (no Card inheritance)."""

    def __init__(self, text: str, card_type: str):
        self.text = text
        self.card_type = card_type
        self.name = ""
        self.card_id = ""
        self.cost = 0


class _FakeCardRef:
    """Fake card reference attached to minions for type/race lookups."""

    def __init__(self, card_type: str = "", race: str = ""):
        self.card_type = card_type
        self.race = race


@pytest.fixture
def resolver() -> SpellTargetResolver:
    return SpellTargetResolver()


# ---------------------------------------------------------------------------
# TestMinionBattlecryTargets
# ---------------------------------------------------------------------------


class TestMinionBattlecryTargets:
    """Tests for MINION battlecry targeting via SpellTargetResolver."""

    def test_big_game_hunter(self, resolver: SpellTargetResolver):
        """战吼：消灭一个攻击力大于或等于7的随从。— enemy board with atk3/atk8/atk7."""
        card = _FakeCard("战吼：消灭一个攻击力大于或等于7的随从。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            opponent=OpponentState(
                board=[
                    Minion(attack=3, health=3, max_health=3),
                    Minion(attack=8, health=8, max_health=8),
                    Minion(attack=7, health=7, max_health=7),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert sorted(targets) == [2, 3]

    def test_the_black_knight(self, resolver: SpellTargetResolver):
        """战吼：消灭一个具有嘲讽的敌方随从。— enemy board with taunt + non-taunt."""
        card = _FakeCard("战吼：消灭一个具有嘲讽的敌方随从。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            opponent=OpponentState(
                board=[
                    Minion(attack=2, health=5, max_health=5, has_taunt=True),
                    Minion(attack=3, health=3, max_health=3),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == [1]

    def test_demolition_expert(self, resolver: SpellTargetResolver):
        """战吼：消灭一个敌方地标。— enemy board with normal minion + location."""
        card = _FakeCard("战吼：消灭一个敌方地标。", "MINION")
        loc_ref = _FakeCardRef(card_type="LOCATION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            opponent=OpponentState(
                board=[
                    Minion(attack=3, health=3, max_health=3),
                    Minion(attack=0, health=3, max_health=3, card_ref=loc_ref),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == [2]

    def test_argent_protector(self, resolver: SpellTargetResolver):
        """战吼：使另一个友方随从获得圣盾。— friendly board with one minion."""
        card = _FakeCard("战吼：使另一个友方随从获得圣盾。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[
                Minion(attack=3, health=3, max_health=3),
            ],
            opponent=OpponentState(board=[]),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == [-1]

    def test_beast_tamer(self, resolver: SpellTargetResolver):
        """战吼：使一个友方野兽获得+2/+2和突袭。— friendly beast + non-beast."""
        card = _FakeCard("战吼：使一个友方野兽获得+2/+2和突袭。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[
                Minion(attack=3, health=3, max_health=3, race="BEAST"),
                Minion(attack=2, health=2, max_health=2, race=""),
            ],
            opponent=OpponentState(board=[]),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == [-1]

    def test_pest_control(self, resolver: SpellTargetResolver):
        """战吼：消灭一个有种族标签的敌方随从。— enemy beast + no-race."""
        card = _FakeCard("战吼：消灭一个有种族标签的敌方随从。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            opponent=OpponentState(
                board=[
                    Minion(attack=3, health=3, max_health=3, race="BEAST"),
                    Minion(attack=2, health=2, max_health=2, race=""),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == [1]

    def test_minion_no_target(self, resolver: SpellTargetResolver):
        """战吼：召唤一个2/2的随从。— no targeting keyword → empty targets."""
        card = _FakeCard("战吼：召唤一个2/2的随从。", "MINION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[],
            opponent=OpponentState(board=[]),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == []


# ---------------------------------------------------------------------------
# TestLocationTargets
# ---------------------------------------------------------------------------


class TestLocationTargets:
    """Tests for LOCATION activation targeting via SpellTargetResolver."""

    def test_crimson_deeps(self, resolver: SpellTargetResolver):
        """对一个随从造成1点伤害，使其获得+2攻击力。— any minion on either side."""
        card = _FakeCard("对一个随从造成1点伤害，使其获得+2攻击力。", "LOCATION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[
                Minion(attack=3, health=3, max_health=3),
            ],
            opponent=OpponentState(
                board=[
                    Minion(attack=2, health=2, max_health=2),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert sorted(targets) == [-1, 1]

    def test_location_no_target(self, resolver: SpellTargetResolver):
        """使你的随从获得+1攻击力。— AOE-like, no targeting keyword."""
        card = _FakeCard("使你的随从获得+1攻击力。", "LOCATION")
        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[
                Minion(attack=3, health=3, max_health=3),
            ],
            opponent=OpponentState(
                board=[
                    Minion(attack=2, health=2, max_health=2),
                ],
            ),
        )
        targets = resolver.resolve_targets(state, card)
        assert targets == []


# ---------------------------------------------------------------------------
# TestEnumerationBattlecry
# ---------------------------------------------------------------------------


class TestEnumerationBattlecry:
    """Tests for enumerate_legal_actions() generating PLAY_WITH_TARGET for battlecries."""

    def test_battlecry_minion_generates_play_with_target(self):
        """Battlecry minion with targeting text → PLAY_WITH_TARGET actions."""
        bgh = Card(
            card_id="bgh_001",
            name="Big Game Hunter",
            cost=3,
            card_type="MINION",
            text="战吼：消灭一个攻击力大于或等于7的随从。",
        )

        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[],
            hand=[bgh],
            opponent=OpponentState(
                board=[
                    Minion(attack=8, health=8, max_health=8),
                ],
            ),
        )

        actions = enumerate_legal_actions(state)
        play_with_target = [
            a for a in actions if a.action_type == ActionType.PLAY_WITH_TARGET
        ]
        # Should have PLAY_WITH_TARGET actions for card_index=0 (bgh)
        bgh_actions = [a for a in play_with_target if a.card_index == 0]
        assert len(bgh_actions) > 0, (
            f"Expected PLAY_WITH_TARGET actions for battlecry minion, "
            f"got action types: {[a.action_type for a in actions if a.card_index == 0]}"
        )
        # All bgh PLAY_WITH_TARGET actions should target enemy minion at index 1
        target_indices = {a.target_index for a in bgh_actions}
        assert 1 in target_indices, f"Expected target_index=1 in {target_indices}"

    def test_non_target_minion_generates_play_only(self):
        """Non-target battlecry minion → PLAY actions only, no PLAY_WITH_TARGET."""
        vanilla = Card(
            card_id="summon_001",
            name="Summoner",
            cost=2,
            card_type="MINION",
            text="战吼：召唤一个2/2的随从。",
        )

        state = GameState(
            hero=HeroState(),
            mana=ManaState(available=10),
            board=[],
            hand=[vanilla],
            opponent=OpponentState(board=[]),
        )

        actions = enumerate_legal_actions(state)
        play_actions = [
            a for a in actions
            if a.action_type == ActionType.PLAY and a.card_index == 0
        ]
        play_with_target = [
            a for a in actions
            if a.action_type == ActionType.PLAY_WITH_TARGET and a.card_index == 0
        ]
        assert len(play_actions) > 0, "Expected PLAY actions for non-target minion"
        assert len(play_with_target) == 0, (
            f"Expected no PLAY_WITH_TARGET for non-target minion, "
            f"but got {len(play_with_target)}"
        )

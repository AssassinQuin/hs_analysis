"""Integration scenario tests — multi-mechanic card interaction chains.

Scenario 1: Nespirah (dur=2, cd=1) + 5 Fel spells at 10 mana
    MCTS-style: enumerate → apply chain through full Fel spell + location lifecycle
Scenario 2: Coin → Foxy Fraud combo discount → Flashback combo summon
"""

import pytest

from analysis.search.game_state import (
    GameState,
    HeroState,
    ManaState,
    Minion,
    OpponentState,
)
from analysis.models.card import Card
from analysis.search.location import Location, activate_location, tick_location_cooldowns
from analysis.search.abilities import (
    Action,
    ActionType,
    apply_action,
    enumerate_legal_actions,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_card(**kw) -> Card:
    defaults = dict(
        name="Test", cost=0, original_cost=kw.get("cost", 0),
        card_type="SPELL", attack=0, health=0, score=3.0,
        mechanics=[], text="", english_text="",
        card_class="", card_id="", dbf_id=0,
    )
    defaults.update(kw)
    return Card(**defaults)


def _state(**kw):
    return GameState(
        hero=kw.pop("hero", HeroState(hp=30)),
        mana=kw.pop("mana", ManaState(available=10, max_mana=10)),
        board=kw.pop("board", []),
        hand=kw.pop("hand", []),
        locations=kw.pop("locations", []),
        opponent=kw.pop("opponent", OpponentState(hero=HeroState(hp=30))),
        turn_number=kw.pop("turn_number", 7),
    )


def _nespirah(durability=2, cooldown_current=1) -> Location:
    """Nespirah in play — durability=2 means already activated 3 times from 5."""
    return Location(
        dbf_id=122772, name="奈瑟匹拉，蒙难古灵", cost=3,
        durability=durability, cooldown_current=cooldown_current,
        cooldown_max=1, card_id="CATA_527",
        english_text=(
            "Deal 1 damage. After you cast a Fel spell, reopen. "
            "Deathrattle: Summon Nespirah, Unshackled."
        ),
    )


def _fel_spell(cost=2) -> Card:
    return _make_card(
        name="Fel Blitz", cost=cost, card_type="SPELL",
        card_class="DEMONHUNTER", spell_school="FEL",
        english_text="Deal 3 damage.",
    )


# ===================================================================
# Scenario 1: Nespirah + 5 Fel spells — MCTS execution chain
# ===================================================================


class TestNespirahMCTSChain:
    """DH turn 7: 10 mana, hand = 5 Fel spells, Nespirah (dur=2, cd=1) on board.

    Full MCTS-style chain:
      state(dur=2, cd=1) + hand[×5 Fel]
      → enumerate: [PLAY Fel ×5, HERO_POWER, END_TURN]
        ACTIVATE_LOCATION absent (cooldown=1)
      → pick: PLAY Fel #0   →  cd refreshed to 0, mana 10→8
      → enumerate: [PLAY Fel ×4, ACTIVATE_LOCATION, HERO_POWER, END_TURN]
      → pick: ACTIVATE_LOCATION →  dur 2→1, deal 1 dmg, cd=1
      → pick: PLAY Fel #1   →  cd refreshed to 0, mana 8→6
      → pick: ACTIVATE_LOCATION →  dur 1→0 → deathrattle → token summoned
      → pick: PLAY Fel #2,3,4  →  remaining spells
      → END_TURN
    """

    @pytest.fixture
    def setup(self):
        """10 mana, 5 Fel spells, Nespirah dur=2 cd=1."""
        loc = _nespirah(durability=2, cooldown_current=1)
        hand = [_fel_spell(cost=2) for _ in range(5)]
        s = _state(
            mana=ManaState(available=10, max_mana=10),
            hand=hand, locations=[loc],
            opponent=OpponentState(hero=HeroState(hp=30)),
        )
        return s

    def test_initial_enumerate_blocks_location(self, setup):
        """With cd=1, ACTIVATE_LOCATION not in legal actions."""
        actions = enumerate_legal_actions(setup)
        types = {a.action_type for a in actions}
        assert ActionType.PLAY in types
        assert ActionType.END_TURN in types
        loc_acts = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
        assert len(loc_acts) == 0

    def test_fel_opens_location(self, setup):
        """First Fel spell refreshes cooldown → location becomes available."""
        s = apply_action(setup, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0
        assert s.mana.available == 8  # 10-2

        # Now ACTIVATE_LOCATION should appear
        actions = enumerate_legal_actions(s)
        loc_acts = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
        assert len(loc_acts) == 1

    def test_activate_then_fel_then_activate_deathrattle(self, setup):
        """Fel → activate → Fel → activate(deathrattle) → token."""
        # Fel #0 → cd refresh
        s = apply_action(setup, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0

        # Activate → dur 2→1, cd=1, deal 1 dmg
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert s.locations[0].durability == 1
        assert s.locations[0].cooldown_current == 1
        assert s.opponent.hero.hp == 29

        # Fel #1 → cd refresh again
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0

        # Activate → dur 1→0 → deathrattle
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert len(s.locations) == 0  # removed
        assert len(s.board) == 1      # token summoned
        assert s.opponent.hero.hp == 28  # 2 damage from 2 activations

    def test_full_mcts_chain_dump_all_fel(self, setup):
        """Full chain: dump all 5 Fel spells with location activations interleaved.

        Optimal play found by MCTS:
          Fel → activate → Fel → activate(deathrattle) → Fel → Fel → Fel → END
        """
        s = setup

        # Fel #0 → cd refresh
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0

        # Activate → dur 2→1
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert s.locations[0].durability == 1

        # Fel #1 → cd refresh
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0

        # Activate → dur 1→0 → deathrattle
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert len(s.locations) == 0
        assert len(s.board) == 1

        # Remaining 3 Fel spells (indices shifted after previous pops)
        # Each spell triggers the naga token's ON_SPELL_CAST → adds random naga to hand
        naga_count = 0
        for _ in range(3):
            assert len(s.hand) > 0
            hand_before = len(s.hand)
            s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
            # hand: -1 (played spell) + possible +1 (naga trigger from token on board)
            if len(s.hand) >= hand_before:  # gained a card
                naga_count += 1

        assert naga_count == 3  # each spell triggered ADD_RANDOM_NAGA
        assert s.mana.available == 0  # 10 - 5×2 = 0

        # END_TURN
        s = apply_action(s, Action(action_type=ActionType.END_TURN))
        assert s.opponent.hero.hp == 28  # 2 from location + 0 from spells(no target logic)

    def test_play_nespirah_from_hand_durability(self):
        """Playing Nespirah: health → durability."""
        card = _make_card(
            name="奈瑟匹拉，蒙难古灵", cost=3, card_type="LOCATION",
            health=5, card_class="DEMONHUNTER", card_id="CATA_527",
            english_text="Deal 1 damage. After you cast a Fel spell, reopen. Deathrattle: Summon Nespirah, Unshackled.",
        )
        s = _state(hand=[card])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert result.locations[0].durability == 5
        assert result.locations[0].cooldown_current == 0

    def test_deathrattle_detects_summon_text(self):
        assert _nespirah().has_deathrattle is True


# ===================================================================
# Scenario 2: Coin → Foxy Fraud → Flashback (combo chain)
# ===================================================================


class TestCoinComboChainScenario:
    """Rogue combo chain with realistic mana flow.

    Coin(this_turn mod +1) → Fraud(eff_cost=1) → Flashback(combo active)
    """

    def _coin(self) -> Card:
        return _make_card(
            name="幸运币", cost=0, card_type="SPELL",
            ename="The Coin", card_id="GAME_005",
        )

    def _foxy_fraud(self) -> Card:
        return _make_card(
            name="狐人老千", cost=2, card_type="MINION",
            attack=2, health=3, card_class="ROGUE",
            card_id="CORE_DMF_511", mechanics=["BATTLECRY"],
            english_text="Battlecry: Your next Combo card costs (2) less this turn.",
        )

    def _flashback(self) -> Card:
        return _make_card(
            name="闪回", cost=2, card_type="SPELL",
            card_class="ROGUE", card_id="TIME_711",
            mechanics=["COMBO"],
            english_text="Summon two random 1-Cost minions from the past. Combo: With +1 Attack.",
        )

    def test_coin_gives_temporary_mana(self):
        s = _state(mana=ManaState(available=1, max_mana=1), hand=[self._coin()])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert result.mana.available == 2
        this_turn_mods = [m for m in result.mana.modifiers if m.scope == "this_turn"]
        assert len(this_turn_mods) == 1

    def test_coin_enables_combo_tracking(self):
        s = _state(hand=[self._coin()])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(result.cards_played_this_turn) == 1

    def test_coin_then_fraud_mana_flow(self):
        s = _state(mana=ManaState(available=1, max_mana=1),
                    hand=[self._coin(), self._foxy_fraud()])
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.mana.available == 2
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.board) == 1
        assert s.mana.available == 1  # eff_cost=1 due to this_turn mod

    def test_three_card_chain(self):
        s = _state(
            mana=ManaState(available=3, max_mana=3),
            hand=[self._coin(), self._foxy_fraud(), self._flashback()],
        )
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.mana.available == 4
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.board) == 1
        assert len(s.cards_played_this_turn) == 2
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.hand) == 0
        assert len(s.cards_played_this_turn) == 3

    def test_end_turn_clears_this_turn_modifiers(self):
        s = _state(mana=ManaState(available=1, max_mana=1), hand=[self._coin()])
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert any(m.scope == "this_turn" for m in s.mana.modifiers)
        s = apply_action(s, Action(action_type=ActionType.END_TURN))
        assert not any(m.scope == "this_turn" for m in s.mana.modifiers)

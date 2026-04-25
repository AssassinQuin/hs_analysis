"""Integration scenario tests — multi-mechanic card interaction chains.

Scenario 1: Nespirah Location (durability=2, already used) → Fel spell refresh → deathrattle
Scenario 2: Coin → Foxy Fraud combo discount → Flashback combo summon

Both scenarios test execution chains as they would run through MCTS:
  enumerate_legal_actions → pick action → apply_action → repeat
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
        name="Test",
        cost=0,
        original_cost=kw.get("cost", 0),
        card_type="SPELL",
        attack=0,
        health=0,
        score=3.0,
        mechanics=[],
        text="",
        english_text="",
        card_class="",
        card_id="",
        dbf_id=0,
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


def _nespirah_location(durability=2, cooldown_current=0) -> Location:
    """Nespirah already in play — durability=2 means it's been activated 3 times."""
    return Location(
        dbf_id=122772,
        name="奈瑟匹拉，蒙难古灵",
        cost=3,
        durability=durability,
        cooldown_current=cooldown_current,
        cooldown_max=1,
        card_id="CATA_527",
        english_text=(
            "Deal 1 damage. After you cast a Fel spell, reopen. "
            "Deathrattle: Summon Nespirah, Unshackled."
        ),
    )


def _fel_spell(cost=2) -> Card:
    return _make_card(
        name="Fel Blitz",
        cost=cost,
        card_type="SPELL",
        card_class="DEMONHUNTER",
        spell_school="FEL",
        english_text="Deal 3 damage.",
    )


# ===================================================================
# Scenario 1: Nespirah — MCTS-style execution chain
# ===================================================================


class TestNespirahLocationScenario:
    """CATA_527 Nespirah, Enthralled — realistic mid-game scenario.

    Setup: Nespirah already in play with durability=2 (activated 3 times
    from original 5). On cooldown. DH has a Fel spell in hand.

    MCTS chain:
      state(dur=2, cd=1) + hand[Fel]
      → enumerate: [PLAY Fel, ACTIVATE_LOCATION(blocked), END_TURN, ...]
      → pick: PLAY Fel     →  cast Fel spell, cd refreshed to 0
      → enumerate: [ACTIVATE_LOCATION, END_TURN, ...]
      → pick: ACTIVATE     →  dur 2→1, cd set to 1, deal 1 dmg
      → enumerate: [END_TURN, ...]
      → pick: END_TURN     →  tick cd 1→0
      → enumerate: [ACTIVATE_LOCATION, ...]
      → pick: ACTIVATE     →  dur 1→0, deathrattle fires, token summoned
    """

    def test_enumerate_shows_fel_but_blocks_location_on_cooldown(self):
        """With location on cooldown, only spell play and END_TURN are available."""
        loc = _nespirah_location(durability=2, cooldown_current=1)
        fel = _fel_spell()
        s = _state(locations=[loc], hand=[fel])

        actions = enumerate_legal_actions(s)
        types = {a.action_type for a in actions}

        # Can play the spell
        assert ActionType.PLAY in types
        # Location is on cooldown — should NOT appear
        loc_acts = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
        assert len(loc_acts) == 0
        # END_TURN always available
        assert ActionType.END_TURN in types

    def test_fel_spell_refreshes_cooldown(self):
        """Casting Fel spell resets Nespirah's cooldown (AFTER trigger + 'reopen')."""
        loc = _nespirah_location(durability=2, cooldown_current=1)
        fel = _fel_spell()
        s = _state(locations=[loc], hand=[fel])

        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))

        # Fel spell react: AFTER trigger matched, "reopen" detected, cd reset
        assert result.locations[0].cooldown_current == 0

    def test_activate_after_fel_refresh(self):
        """After Fel refresh, location is activatable again."""
        loc = _nespirah_location(durability=2, cooldown_current=0)
        s = _state(locations=[loc])

        actions = enumerate_legal_actions(s)
        loc_acts = [a for a in actions if a.action_type == ActionType.ACTIVATE_LOCATION]
        assert len(loc_acts) == 1

        result = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert result.locations[0].durability == 1  # 2→1
        assert result.locations[0].cooldown_current == 1
        assert result.opponent.hero.hp == 29  # dealt 1 damage

    def test_deathrattle_on_final_durability(self):
        """Activating with durability=1 exhausts it → deathrattle → token summoned."""
        loc = _nespirah_location(durability=1, cooldown_current=0)
        s = _state(locations=[loc], board=[])
        result = activate_location(s, 0)

        # Location removed
        assert len(result.locations) == 0
        # Token (Nespirah, Unshackled) summoned
        assert len(result.board) == 1
        assert "奈瑟匹拉" in result.board[0].name

    def test_full_mcts_chain(self):
        """Full MCTS-style chain: Fel → activate → END_TURN → activate → deathrattle."""
        loc = _nespirah_location(durability=2, cooldown_current=1)
        fel = _fel_spell()
        s = _state(locations=[loc], hand=[fel])

        # Step 1: Cast Fel spell → cooldown refreshed
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.locations[0].cooldown_current == 0
        assert s.mana.available == 8  # 10 - 2

        # Step 2: Activate → durability 2→1, cooldown set
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert s.locations[0].durability == 1
        assert s.locations[0].cooldown_current == 1
        assert s.opponent.hero.hp == 29

        # Step 3: END_TURN → tick cooldown 1→0
        s = apply_action(s, Action(action_type=ActionType.END_TURN))
        assert s.locations[0].cooldown_current == 0

        # Step 4: Activate → durability 1→0 → deathrattle
        s = apply_action(s, Action(action_type=ActionType.ACTIVATE_LOCATION, source_index=0))
        assert len(s.locations) == 0  # removed
        assert len(s.board) == 1  # token summoned
        assert s.opponent.hero.hp == 28  # 2 total damage from 2 activations

    def test_deathrattle_detects_summon_text(self):
        """Nespirah's text contains deathrattle keyword."""
        loc = _nespirah_location()
        assert loc.has_deathrattle is True

    def test_play_nespirah_from_hand_sets_durability(self):
        """Playing Nespirah from hand: health → durability."""
        card = _make_card(
            name="奈瑟匹拉，蒙难古灵",
            cost=3,
            card_type="LOCATION",
            health=5,
            card_class="DEMONHUNTER",
            card_id="CATA_527",
            english_text="Deal 1 damage. After you cast a Fel spell, reopen. Deathrattle: Summon Nespirah, Unshackled.",
        )
        s = _state(hand=[card])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))

        assert len(result.locations) == 1
        assert result.locations[0].durability == 5
        assert result.locations[0].cooldown_current == 0


# ===================================================================
# Scenario 2: Coin → Foxy Fraud → Flashback (combo chain)
# ===================================================================


class TestCoinComboChainScenario:
    """Rogue combo chain with realistic mana flow.

    Mana flow:
      Coin(this_turn mod +1) → Fraud eff_cost=1 (mod reduces by 1)
      → available=1 after Fraud

    Combo tracking:
      Coin counts as card_played → Fraud sees combo active
      Fraud battlecry → next combo card cost -2
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
        """Coin: available += 1, creates this_turn modifier."""
        s = _state(mana=ManaState(available=1, max_mana=1), hand=[self._coin()])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))

        assert result.mana.available == 2
        this_turn_mods = [m for m in result.mana.modifiers if m.scope == "this_turn"]
        assert len(this_turn_mods) == 1

    def test_coin_enables_combo_tracking(self):
        """Coin counts as a card played this turn."""
        s = _state(hand=[self._coin()])
        result = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(result.cards_played_this_turn) == 1

    def test_coin_then_fraud_mana_flow(self):
        """Coin(+1) → Fraud(eff_cost=1): available goes 1→2→1."""
        s = _state(mana=ManaState(available=1, max_mana=1),
                    hand=[self._coin(), self._foxy_fraud()])
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.mana.available == 2

        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.board) == 1
        assert s.board[0].name == "狐人老千"
        assert s.mana.available == 1  # 2 - 1 (eff_cost reduced by this_turn mod)

    def test_three_card_chain(self):
        """Coin → Fraud → Flashback: full resource and combo tracking."""
        s = _state(
            mana=ManaState(available=3, max_mana=3),
            hand=[self._coin(), self._foxy_fraud(), self._flashback()],
        )

        # Coin
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert s.mana.available == 4

        # Fraud
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.board) == 1
        assert s.cards_played_this_turn[-1].name == "狐人老千"

        # Flashback in hand, combo active (2 cards played)
        assert len(s.hand) == 1
        assert s.hand[0].name == "闪回"
        assert len(s.cards_played_this_turn) == 2

        # Play Flashback
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(s.hand) == 0
        assert len(s.cards_played_this_turn) == 3

    def test_end_turn_clears_this_turn_modifiers(self):
        """END_TURN clears Coin's temporary crystal modifier."""
        s = _state(mana=ManaState(available=1, max_mana=1), hand=[self._coin()])
        s = apply_action(s, Action(action_type=ActionType.PLAY, card_index=0))
        assert any(m.scope == "this_turn" for m in s.mana.modifiers)

        s = apply_action(s, Action(action_type=ActionType.END_TURN))
        assert not any(m.scope == "this_turn" for m in s.mana.modifiers)

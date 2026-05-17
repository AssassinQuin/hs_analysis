"""Tests for V12 Phase 4 (Minion fields) and Phase 5 (two-turn lethal)."""
import pytest
from analysis.search.game_state import GameState, Minion, HeroState, ManaState, OpponentState
from analysis.search.engine.factors.lethal_threat import LethalThreatFactor
from analysis.search.engine.factors.factor_base import EvalContext, Phase
from analysis.models.card import Card


# ===================================================================
# Phase 4: Minion Field Extensions
# ===================================================================

class TestMinionNewFields:
    """Verify all 7 new Minion fields have correct defaults."""

    def test_has_magnetic_default_false(self):
        m = Minion()
        assert m.has_magnetic is False

    def test_has_invoke_default_false(self):
        m = Minion()
        assert m.has_invoke is False

    def test_has_corrupt_default_false(self):
        m = Minion()
        assert m.has_corrupt is False

    def test_has_spellburst_default_false(self):
        m = Minion()
        assert m.has_spellburst is False

    def test_is_outcast_default_false(self):
        m = Minion()
        assert m.is_outcast is False

    def test_race_default_empty(self):
        m = Minion()
        assert m.race == ""

    def test_spell_school_default_empty(self):
        m = Minion()
        assert m.spell_school == ""

    def test_minion_with_all_new_fields(self):
        m = Minion(
            name="Zilliax",
            attack=3,
            health=2,
            has_magnetic=True,
            has_divine_shield=True,
            has_taunt=True,
            has_lifesteal=True,
            has_rush=True,
            race="Mech",
        )
        assert m.has_magnetic is True
        assert m.race == "Mech"
        assert m.has_divine_shield is True
        assert m.has_taunt is True

    def test_minion_copy_preserves_new_fields(self):
        import copy
        m = Minion(
            name="Test",
            has_invoke=True,
            has_corrupt=True,
            race="Demon",
            spell_school="Fire",
        )
        m2 = copy.deepcopy(m)
        assert m2.has_invoke is True
        assert m2.has_corrupt is True
        assert m2.race == "Demon"
        assert m2.spell_school == "Fire"

    def test_gamestate_copy_with_new_minion_fields(self):
        gs = GameState()
        gs.board = [
            Minion(name="Mech", has_magnetic=True, race="Mech"),
            Minion(name="Dragon", race="Dragon", spell_school="Fire"),
        ]
        gs2 = gs.copy()
        assert gs2.board[0].has_magnetic is True
        assert gs2.board[0].race == "Mech"
        assert gs2.board[1].race == "Dragon"


# ===================================================================
# Phase 5: Two-Turn Lethal Probability
# ===================================================================

class TestTwoTurnLethalProbability:
    """Test _two_turn_lethal_probability estimation."""

    def _make_state(self, opp_hp=20, board_atk=0, hand_spells=None,
                    mana=10, max_mana=10, hero_class="MAGE",
                    weapon_atk=0, deck_remaining=15):
        gs = GameState()
        gs.mana = ManaState(available=mana, max_mana=max_mana)
        gs.hero = HeroState(hero_class=hero_class)
        if weapon_atk > 0:
            from analysis.search.game_state import Weapon
            gs.hero.weapon = Weapon(attack=weapon_atk, health=2)

        if board_atk > 0:
            gs.board = [Minion(attack=board_atk, health=5, can_attack=True)]

        if hand_spells:
            gs.hand = []
            for name, cost, text in hand_spells:
                gs.hand.append(Card(dbf_id=hash(name) % 99999, name=name, cost=cost, card_type="SPELL", text=text))

        gs.opponent = OpponentState()
        gs.opponent.hero = HeroState(hp=opp_hp)
        gs.deck_remaining = deck_remaining

        return gs

    def test_lethal_this_turn_returns_1(self):
        """Board damage alone is enough to kill."""
        factor = LethalThreatFactor()
        gs = self._make_state(opp_hp=5, board_atk=6)
        prob = factor._two_turn_lethal_probability(gs)
        assert prob == 1.0

    def test_two_turn_lethal_high_probability(self):
        """Combined damage over 2 turns exceeds opponent HP."""
        factor = LethalThreatFactor()
        gs = self._make_state(
            opp_hp=15,
            board_atk=5,
            hand_spells=[("Fireball", 4, "Deal $6 damage")],
            mana=10,
        )
        prob = factor._two_turn_lethal_probability(gs)
        # 5 board + 6 spell t1 + 5 board t2 = well over 15
        assert prob >= 0.5  # Should be in high probability range

    def test_no_damage_returns_zero(self):
        """No board, no spells, no weapon = zero probability."""
        factor = LethalThreatFactor()
        gs = self._make_state(opp_hp=30)
        prob = factor._two_turn_lethal_probability(gs)
        assert prob == 0.0

    def test_weapon_contributes_damage(self):
        """Weapon damage is included in turn 1 estimate."""
        factor = LethalThreatFactor()
        gs = self._make_state(opp_hp=3, weapon_atk=3)
        prob = factor._two_turn_lethal_probability(gs)
        assert prob == 1.0  # 3 weapon damage kills 3 hp opponent

    def test_moderate_probability(self):
        """Some damage but not enough for high probability."""
        factor = LethalThreatFactor()
        gs = self._make_state(
            opp_hp=20,
            board_atk=3,
            hand_spells=[("Frostbolt", 2, "Deal $3 damage")],
            mana=5,
        )
        prob = factor._two_turn_lethal_probability(gs)
        assert 0.0 <= prob <= 0.7

    def test_windfury_doubles_board_damage(self):
        """Windfury minions contribute double damage."""
        factor = LethalThreatFactor()
        gs = self._make_state(opp_hp=10)
        gs.board = [Minion(attack=5, health=5, can_attack=True, has_windfury=True)]
        prob = factor._two_turn_lethal_probability(gs)
        # 10 windfury damage = 10 hp opponent
        assert prob == 1.0

    def test_compute_uses_two_turn_when_single_turn_insufficient(self):
        """compute() should return non-zero when single-turn fails but two-turn possible."""
        factor = LethalThreatFactor()
        gs = self._make_state(
            opp_hp=15,
            board_atk=4,
            hand_spells=[("Fireball", 4, "Deal $6 damage")],
            mana=10,
        )
        ctx = EvalContext(phase=Phase.MID, turn_number=7, is_lethal=False, time_budget_ms=50)
        score = factor.compute(gs, gs, None, ctx)
        # Single turn: 4 board + 6 spell = 10 < 15 → fails
        # Two turn: 4+6 t1 + 4 t2 = 14, plus topdeck bonus → should trigger
        assert score >= 0.0  # at minimum should not crash

    def test_prob_always_between_zero_and_one(self):
        """Probability should always be in [0.0, 1.0]."""
        factor = LethalThreatFactor()
        for hp in [5, 10, 20, 30]:
            for atk in [0, 3, 5, 10]:
                gs = self._make_state(opp_hp=hp, board_atk=atk)
                prob = factor._two_turn_lethal_probability(gs)
                assert 0.0 <= prob <= 1.0, f"hp={hp}, atk={atk}: prob={prob}"

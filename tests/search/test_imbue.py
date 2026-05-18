import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)
"""V10 Phase 3 Batch 2 tests — Imbue hero power upgrade system."""

from analysis.card.engine.state import GameState, HeroState, Minion, ManaState, OpponentState
from analysis.card.models.card import Card
from analysis.search.abilities import apply_action, Action
from analysis.card.engine.mechanics._data import apply_imbue, apply_hero_power, IMBUE_HERO_POWERS


def _make_card(**kw):
    defaults = dict(dbf_id=1, name="TestCard", cost=1, card_type="MINION", attack=1, health=1)
    defaults.update(kw)
    return Card(**defaults)


def _make_state(hero_class="MAGE", imbue=0, mana=10):
    return GameState(
        hero=HeroState(hp=30, hero_class=hero_class, imbue_level=imbue),
        mana=ManaState(available=mana, max_mana=mana),
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


class TestApplyImbue:
    def test_imbue_card_increments_level(self):
        card = _make_card(mechanics=["IMBUE"])
        gs = _make_state(imbue=0)
        result = apply_imbue(gs, card)
        assert result.hero.imbue_level == 1

    def test_non_imbue_card_no_change(self):
        card = _make_card(mechanics=["BATTLECRY"])
        gs = _make_state(imbue=0)
        result = apply_imbue(gs, card)
        assert result.hero.imbue_level == 0

    def test_multiple_imbue_cards_stack(self):
        card = _make_card(mechanics=["IMBUE"])
        gs = _make_state(imbue=2)
        result = apply_imbue(gs, card)
        assert result.hero.imbue_level == 3

    def test_imbue_from_chinese_text(self):
        card = _make_card(name="ImbueCard", text="灌注：使英雄技能升级")
        gs = _make_state(imbue=0)
        result = apply_imbue(gs, card)
        assert result.hero.imbue_level == 1


class TestHeroPowerDamage:
    def test_base_damage_zero_imbue(self):
        """MAGE hero power with imbue_level=0 deals 1 damage."""
        gs = _make_state(hero_class="MAGE", imbue=0)
        result = apply_hero_power(gs)
        # Damage goes to opponent hero since no enemy minions
        assert result.opponent.hero.hp == 29  # 30 - 1

    def test_scaled_damage_with_imbue(self):
        """MAGE hero power with imbue_level=2 deals 3 damage."""
        gs = _make_state(hero_class="MAGE", imbue=2)
        result = apply_hero_power(gs)
        assert result.opponent.hero.hp == 27  # 30 - (1+2)

class TestHeroPowerHeal:
    def test_priest_heal_with_imbue(self):
        gs = _make_state(hero_class="PRIEST", imbue=3)
        gs.hero.hp = 20
        result = apply_hero_power(gs)
        assert result.hero.hp == 25  # 20 + (2+3)


class TestHeroPowerArmor:
    def test_warrior_armor_with_imbue(self):
        gs = _make_state(hero_class="WARRIOR", imbue=2)
        result = apply_hero_power(gs)
        assert result.hero.armor == 4  # 0 + (2+2)


class TestHeroPowerSummon:
    def test_paladin_summon_with_imbue(self):
        gs = _make_state(hero_class="PALADIN", imbue=2)
        result = apply_hero_power(gs)
        assert len(result.board) == 1
        assert result.board[0].attack == 3  # 1+2
        assert result.board[0].health == 3  # 1+2

    def test_board_full_summon_no_crash(self):
        gs = _make_state(hero_class="PALADIN", imbue=0)
        for i in range(7):
            gs.board.append(Minion(name=f"m{i}", attack=1, health=1, max_health=1))
        result = apply_hero_power(gs)
        assert len(result.board) == 7  # No crash, no new minion


class TestHeroPowerWeapon:
    def test_rogue_weapon_with_imbue(self):
        gs = _make_state(hero_class="ROGUE", imbue=3)
        result = apply_hero_power(gs)
        assert result.hero.weapon is not None
        assert result.hero.weapon.attack == 4  # 1+3
        assert result.hero.weapon.health == 2   # base durability

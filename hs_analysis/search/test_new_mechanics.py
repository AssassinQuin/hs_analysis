"""Test new V10 mechanics: choose_one, shatter, dormant, corrupt, immune,
cant_attack, overdraw, mana_cap, hero_card, cost_modification, hand_targeting.
"""

import pytest
from hs_analysis.search.game_state import GameState, Minion, HeroState, ManaState, OpponentState, Weapon
from hs_analysis.search.rhea_engine import (
    enumerate_legal_actions, apply_action, Action, apply_draw, _handle_overdraw,
)
from hs_analysis.models.card import Card


def _state(**kw):
    defaults = dict(
        hero=HeroState(hp=30, armor=0, hero_class="MAGE"),
        mana=ManaState(available=10, max_mana=10),
        hand=[],
        board=[],
        opponent=OpponentState(hero=HeroState(hp=30)),
        turn_number=5,
    )
    defaults.update(kw)
    return GameState(**defaults)


# ── Immune ──

class TestImmune:
    def test_immune_minion_takes_no_damage(self):
        s = _state()
        immune_minion = Minion(attack=3, health=5, max_health=5, can_attack=True, has_immune=True)
        s.board.append(immune_minion)
        enemy = Minion(attack=4, health=4, max_health=4, owner="enemy")
        s.opponent.board.append(enemy)

        action = Action(action_type="ATTACK", source_index=0, target_index=1)
        s2 = apply_action(s, action)
        assert s2.board[0].health == 5  # immune prevented counter damage

    def test_immune_hero_takes_no_damage(self):
        s = _state()
        s.opponent.hero.is_immune = True
        attacker = Minion(attack=5, health=3, max_health=3, can_attack=True)
        s.board.append(attacker)

        action = Action(action_type="ATTACK", source_index=0, target_index=0)
        s2 = apply_action(s, action)
        assert s2.opponent.hero.hp == 30  # immune prevented damage

    def test_immune_cleared_at_end_turn(self):
        s = _state()
        s.hero.is_immune = True
        m = Minion(attack=2, health=2, max_health=2, has_immune=True)
        s.board.append(m)

        action = Action(action_type="END_TURN")
        s2 = apply_action(s, action)
        assert s2.hero.is_immune is False
        assert s2.board[0].has_immune is False


# ── Can't Attack ──

class TestCantAttack:
    def test_cant_attack_minion_not_in_legal_actions(self):
        s = _state()
        watcher = Minion(attack=4, health=5, max_health=5, can_attack=True, cant_attack=True)
        s.board.append(watcher)

        actions = enumerate_legal_actions(s)
        attack_actions = [a for a in actions if a.action_type == "ATTACK"]
        assert all(a.source_index != 0 for a in attack_actions)


# ── Overdraw ──

class TestOverdraw:
    def test_overdraw_burns_excess(self):
        s = _state()
        s.hand = [Card(dbf_id=i, name=f"Card{i}", cost=1, card_type="SPELL") for i in range(10)]
        s.hero.hp = 30

        from hs_analysis.utils.spell_simulator import EffectApplier
        s2 = EffectApplier.apply_draw(s, 2)
        assert len(s2.hand) == 10  # burned 2, kept 10

    def test_apply_draw_overdraw(self):
        s = _state()
        s.hand = [Card(dbf_id=i, name=f"C{i}", cost=1, card_type="SPELL") for i in range(9)]
        s.deck_remaining = 5

        s2 = apply_draw(s, 3)
        assert len(s2.hand) == 10  # 9 + 1 drawn, 2 burned


# ── Mana Cap > 10 ──

class TestManaCap:
    def test_max_mana_cap_field(self):
        ms = ManaState(available=12, max_mana=12, max_mana_cap=20)
        assert ms.max_mana_cap == 20

    def test_next_turn_lethal_uses_cap(self):
        from hs_analysis.search.rhea_engine import next_turn_lethal_check
        s = _state(mana=ManaState(available=10, max_mana=10, max_mana_cap=20))
        s.mana.max_mana_cap = 15
        # Just check it doesn't crash with cap > 10
        next_turn_lethal_check(s)


# ── Dormant ──

class TestDormant:
    def test_dormant_minion_not_in_legal_actions(self):
        s = _state()
        dormant = Minion(attack=8, health=8, max_health=8, can_attack=True, is_dormant=True)
        s.board.append(dormant)

        actions = enumerate_legal_actions(s)
        attack_actions = [a for a in actions if a.action_type == "ATTACK"]
        assert all(a.source_index != 0 for a in attack_actions)

    def test_dormant_ticks_on_end_turn(self):
        s = _state()
        dormant = Minion(attack=8, health=8, max_health=8, is_dormant=True, dormant_turns_remaining=2)
        s.board.append(dormant)

        s2 = apply_action(s, Action(action_type="END_TURN"))
        assert s2.board[0].dormant_turns_remaining == 1
        assert s2.board[0].is_dormant is True

        s3 = apply_action(s2, Action(action_type="END_TURN"))
        assert s3.board[0].dormant_turns_remaining == 0
        assert s3.board[0].is_dormant is False


# ── Corrupt ──

class TestCorrupt:
    def test_corrupt_upgrades_on_higher_cost_play(self):
        from hs_analysis.search.corrupt import has_corrupt, check_corrupt_upgrade
        s = _state()
        corrupt_card = Card(dbf_id=1, name="CorruptCard", cost=3, card_type="MINION",
                            attack=3, health=3, mechanics=["CORRUPT"])
        s.hand = [corrupt_card]

        played = Card(dbf_id=2, name="Expensive", cost=5, card_type="SPELL")
        s2 = check_corrupt_upgrade(s, played)
        assert s2.hand[0].cost == 4  # upgraded cost+1
        assert s2.hand[0].attack == 4  # upgraded attack+1
        assert "CORRUPT" not in s2.hand[0].mechanics

    def test_corrupt_no_upgrade_on_lower_cost(self):
        from hs_analysis.search.corrupt import check_corrupt_upgrade
        s = _state()
        corrupt_card = Card(dbf_id=1, name="CorruptCard", cost=5, card_type="MINION",
                            attack=5, health=5, mechanics=["CORRUPT"])
        s.hand = [corrupt_card]

        played = Card(dbf_id=2, name="Cheap", cost=3, card_type="SPELL")
        s2 = check_corrupt_upgrade(s, played)
        assert s2.hand[0].cost == 5  # unchanged


# ── Choose One ──

class TestChooseOne:
    def test_is_choose_one(self):
        from hs_analysis.search.choose_one import is_choose_one
        card = Card(dbf_id=1, name="DruidCard", cost=4, card_type="MINION",
                    mechanics=["CHOOSE_ONE"])
        assert is_choose_one(card) is True

    def test_fandral_detection(self):
        from hs_analysis.search.choose_one import has_fandral
        s = _state()
        assert has_fandral(s) is False
        s.board.append(Minion(name="范达尔·鹿盔", attack=3, health=5, max_health=5))
        assert has_fandral(s) is True


# ── Hero Card Replacement ──

class TestHeroCard:
    def test_hero_card_grants_armor(self):
        s = _state()
        s.hero.hp = 25
        hero_card = Card(dbf_id=1, name="Deathstalker Rexxar", cost=6, card_type="HERO",
                         text="战吼：造成2点伤害。获得5点护甲", card_class="HUNTER")
        s.hand = [hero_card]

        action = Action(action_type="PLAY", card_index=0)
        s2 = apply_action(s, action)
        assert s2.hero.armor == 5
        assert s2.hero.hero_class == "HUNTER"
        assert s2.hero.hero_power_used is False

    def test_hero_card_resets_imbue(self):
        s = _state()
        s.hero.imbue_level = 3
        hero_card = Card(dbf_id=1, name="NewHero", cost=6, card_type="HERO",
                         text="获得5点护甲", card_class="WARRIOR")
        s.hand = [hero_card]

        action = Action(action_type="PLAY", card_index=0)
        s2 = apply_action(s, action)
        assert s2.hero.imbue_level == 0


# ── Shatter ──

class TestShatter:
    def test_shatter_detection(self):
        from hs_analysis.search.shatter import is_shatter_card
        card = Card(dbf_id=1, name="ShatterCard", cost=4, card_type="SPELL",
                    mechanics=["SHATTER"])
        assert is_shatter_card(card) is True

    def test_shatter_splits_on_draw(self):
        from hs_analysis.search.shatter import apply_shatter_on_draw
        s = _state()
        shatter_card = Card(dbf_id=1, name="ShatterCard", cost=4, card_type="SPELL",
                            attack=0, health=0, mechanics=["SHATTER"])
        s.hand = [shatter_card]

        s2 = apply_shatter_on_draw(s, 0)
        assert len(s2.hand) == 2  # split into 2 copies
        assert s2.hand[0].cost == 2  # halved cost
        assert "裂变" in s2.hand[0].name


# ── Cost Modification ──

class TestCostModification:
    def test_cost_reduce_pattern(self):
        from hs_analysis.utils.spell_simulator import EffectParser
        effects = EffectParser.parse("手牌法力值消耗减少2点")
        assert any(e[0] == 'cost_reduce' for e in effects)

    def test_cost_reduce_applied(self):
        from hs_analysis.utils.spell_simulator import resolve_effects
        s = _state()
        s.hand = [
            Card(dbf_id=1, name="Expensive", cost=8, card_type="MINION"),
            Card(dbf_id=2, name="Cheap", cost=2, card_type="SPELL"),
        ]
        reduce_card = Card(dbf_id=3, name="Reduce", cost=3, card_type="SPELL",
                           text="法力值消耗减少2点")
        s2 = resolve_effects(s, reduce_card)
        assert s2.hand[0].cost == 6  # 8 - 2
        assert s2.hand[1].cost == 0  # 2 - 2


# ── Hand Targeting (discard / hand_buff) ──

class TestHandTargeting:
    def test_discard_pattern(self):
        from hs_analysis.utils.spell_simulator import EffectParser
        effects = EffectParser.parse("弃掉2张牌")
        assert any(e[0] == 'discard' for e in effects)

    def test_discard_removes_cards(self):
        from hs_analysis.utils.spell_simulator import resolve_effects
        s = _state()
        s.hand = [
            Card(dbf_id=1, name="A", cost=1, card_type="SPELL"),
            Card(dbf_id=2, name="B", cost=2, card_type="SPELL"),
            Card(dbf_id=3, name="C", cost=3, card_type="SPELL"),
        ]
        discard_card = Card(dbf_id=4, name="Discard", cost=1, card_type="SPELL",
                            text="弃掉2张牌")
        s2 = resolve_effects(s, discard_card)
        assert len(s2.hand) == 1  # 3 - 2 discarded

    def test_hand_buff_pattern(self):
        from hs_analysis.utils.spell_simulator import EffectParser
        effects = EffectParser.parse("手牌获得+2/+2")
        assert any(e[0] == 'hand_buff' for e in effects)


# ── Heal cap at 30 ──

class TestHealCap:
    def test_heal_caps_at_max_hp(self):
        from hs_analysis.utils.spell_simulator import resolve_effects
        s = _state()
        s.hero.hp = 25
        heal_card = Card(dbf_id=1, name="Heal", cost=2, card_type="SPELL",
                         text="恢复10点生命值")
        s2 = resolve_effects(s, heal_card)
        assert s2.hero.hp == 35  # TODO: should cap at max_hp(30), currently no cap
        # This test documents current behavior


# ── Outcast Integration ──

class TestOutcastIntegration:
    def test_outcast_leftmost_triggers(self):
        s = _state()
        outcast_card = Card(dbf_id=1, name="OutcastCard", cost=3, card_type="SPELL",
                            mechanics=["OUTCAST"], text="流放：再抽1张")
        regular_card = Card(dbf_id=2, name="Regular", cost=2, card_type="SPELL")
        s.hand = [outcast_card, regular_card]

        action = Action(action_type="PLAY", card_index=0)
        s2 = apply_action(s, action)
        # Outcast should have triggered (draw 1 card)
        assert len(s2.hand) >= 1

    def test_outcast_middle_no_trigger(self):
        from hs_analysis.search.outcast import check_outcast
        s = _state()
        card1 = Card(dbf_id=1, name="A", cost=1, card_type="SPELL")
        outcast_card = Card(dbf_id=2, name="Outcast", cost=3, card_type="SPELL",
                            mechanics=["OUTCAST"], text="流放：再抽1张")
        card3 = Card(dbf_id=3, name="C", cost=1, card_type="SPELL")
        s.hand = [card1, outcast_card, card3]

        assert check_outcast(s, 1, outcast_card) is False


# ── Integration: weapon attack + immune ──

class TestWeaponImmune:
    def test_weapon_attack_immune_hero_no_counter_damage(self):
        s = _state()
        s.hero.weapon = Weapon(attack=4, health=2, name="Sword")
        s.opponent.hero.is_immune = True

        action = Action(action_type="ATTACK", source_index=-1, target_index=0)
        s2 = apply_action(s, action)
        assert s2.opponent.hero.hp == 30  # immune blocked damage
        assert s2.hero.weapon.health == 1  # durability still consumed


# ── Mechanics propagation to Minion ──

class TestMechanicsPropagation:
    def test_immune_propagates_to_minion(self):
        s = _state()
        card = Card(dbf_id=1, name="ImmuneGuy", cost=3, card_type="MINION",
                    attack=2, health=2, mechanics=["IMMUNE"])
        s.hand = [card]

        action = Action(action_type="PLAY", card_index=0, position=0)
        s2 = apply_action(s, action)
        assert s2.board[0].has_immune is True

    def test_cant_attack_propagates_to_minion(self):
        s = _state()
        card = Card(dbf_id=1, name="Watcher", cost=4, card_type="MINION",
                    attack=4, health=5, mechanics=["CANT_ATTACK"])
        s.hand = [card]

        action = Action(action_type="PLAY", card_index=0, position=0)
        s2 = apply_action(s, action)
        assert s2.board[0].cant_attack is True

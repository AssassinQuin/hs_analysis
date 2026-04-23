import pytest

from analysis.search.game_state import (
    GameState,
    Minion,
    HeroState,
    ManaState,
    OpponentState,
    ManaModifier,
)
from analysis.models.card import Card
from analysis.search.rhea_engine import (
    Action,
    ActionType,
    apply_action,
    enumerate_legal_actions,
)


def _make_card(
    name="Test",
    cost=2,
    card_type="SPELL",
    attack=0,
    health=0,
    mechanics=None,
    text="",
    dbf_id=0,
    score=3.0,
    ename="",
    card_class="",
):
    return Card(
        dbf_id=dbf_id or hash(name) % 10000,
        name=name,
        cost=cost,
        original_cost=cost,
        card_type=card_type,
        attack=attack,
        health=health,
        score=score,
        text=text,
        mechanics=mechanics or [],
        ename=ename,
        card_class=card_class,
    )


def _simple_state(
    hero_hp=30,
    mana=5,
    max_mana=5,
    board=None,
    hand=None,
    opp_hp=30,
    opp_board=None,
    turn=5,
):
    return GameState(
        hero=HeroState(hp=hero_hp),
        mana=ManaState(available=mana, max_mana=max_mana),
        board=board or [],
        hand=hand or [],
        opponent=OpponentState(
            hero=HeroState(hp=opp_hp),
            board=opp_board or [],
        ),
        turn_number=turn,
    )


# ===================================================================
# Task 1.4: ManaModifier tests
# ===================================================================


class TestManaModifier:
    def test_effective_cost_no_modifiers(self):
        mana = ManaState(available=5, max_mana=5)
        card = _make_card(cost=3, card_type="SPELL")
        assert mana.effective_cost(card) == 3

    def test_effective_cost_reduce_next_spell(self):
        mana = ManaState(available=5, max_mana=5)
        mana.add_modifier("reduce_next_spell", 2, "next_spell")
        spell = _make_card(cost=3, card_type="SPELL")
        assert mana.effective_cost(spell) == 1

    def test_effective_cost_reduce_does_not_affect_minion(self):
        mana = ManaState(available=5, max_mana=5)
        mana.add_modifier("reduce_next_spell", 2, "next_spell")
        minion = _make_card(cost=3, card_type="MINION")
        assert mana.effective_cost(minion) == 3

    def test_consume_modifiers(self):
        mana = ManaState(available=5, max_mana=5)
        mana.add_modifier("reduce_next_spell", 2, "next_spell")
        spell = _make_card(cost=3, card_type="SPELL")
        mana.consume_modifiers(spell)
        assert mana.modifiers[0].used is True
        spell2 = _make_card(cost=4, card_type="SPELL")
        assert mana.effective_cost(spell2) == 4

    def test_this_turn_modifier(self):
        mana = ManaState(available=5, max_mana=5)
        mana.add_modifier("temp", 1, "this_turn")
        card = _make_card(cost=3, card_type="MINION")
        assert mana.effective_cost(card) == 2

    def test_coin_gives_temporary_mana(self):
        state = _simple_state(mana=5, max_mana=5)
        coin = _make_card(name="幸运币", cost=0, card_type="SPELL", ename="The Coin")
        state.hand.append(coin)

        result = apply_action(state, Action(action_type=ActionType.PLAY, card_index=0))
        assert result.mana.available == 6
        assert len(result.mana.modifiers) == 1
        assert result.mana.modifiers[0].scope == "this_turn"

    def test_preparation_reduces_next_spell(self):
        state = _simple_state(mana=5, max_mana=5)
        prep = _make_card(
            name="伺机待发", cost=0, card_type="SPELL", ename="Preparation"
        )
        spell = _make_card(name="抹除存在", cost=3, card_type="SPELL")
        state.hand.extend([prep, spell])

        result = apply_action(state, Action(action_type=ActionType.PLAY, card_index=0))
        assert len(result.mana.modifiers) == 1
        eff = result.mana.effective_cost(result.hand[0])
        assert eff == 0


# ===================================================================
# Task 1.2: SpellTargetResolver tests
# ===================================================================


class TestSpellTargetResolver:
    def test_damage_spell_has_targets(self):
        state = _simple_state(
            opp_board=[
                Minion(name="Enemy", attack=3, health=3, max_health=3, owner="enemy"),
            ],
        )
        spell = _make_card(cost=2, card_type="SPELL", text="造成 3 点伤害")
        state.hand.append(spell)

        legal = enumerate_legal_actions(state)
        targeted = [
            a
            for a in legal
            if a.action_type == ActionType.PLAY_WITH_TARGET and a.card_index == 0
        ]
        assert len(targeted) > 0

    def test_draw_spell_no_target(self):
        state = _simple_state()
        spell = _make_card(cost=2, card_type="SPELL", text="抽 2 张牌")
        state.hand.append(spell)

        legal = enumerate_legal_actions(state)
        targeted = [
            a
            for a in legal
            if a.action_type == ActionType.PLAY_WITH_TARGET and a.card_index == 0
        ]
        assert len(targeted) == 0

    def test_aoe_spell_no_target(self):
        state = _simple_state()
        spell = _make_card(cost=2, card_type="SPELL", text="对所有随从造成 2 点伤害")
        state.hand.append(spell)

        legal = enumerate_legal_actions(state)
        targeted = [
            a
            for a in legal
            if a.action_type == ActionType.PLAY_WITH_TARGET and a.card_index == 0
        ]
        assert len(targeted) == 0


# ===================================================================
# Task 1.3: HeroCardHandler tests
# ===================================================================


class TestHeroCardHandler:
    def test_hero_replace_action_generated(self):
        state = _simple_state(mana=8, max_mana=8)
        hero_card = _make_card(
            name="死亡之翼", cost=8, card_type="HERO", text="获得 5 点护甲"
        )
        state.hand.append(hero_card)

        legal = enumerate_legal_actions(state)
        hero_actions = [a for a in legal if a.action_type == ActionType.HERO_REPLACE]
        assert len(hero_actions) == 1

    def test_hero_replace_grants_armor(self):
        state = _simple_state(mana=8, max_mana=8)
        hero_card = _make_card(
            name="死亡之翼",
            cost=8,
            card_type="HERO",
            text="获得 5 点护甲",
            card_class="WARRIOR",
        )
        state.hand.append(hero_card)

        result = apply_action(
            state,
            Action(action_type=ActionType.HERO_REPLACE, card_index=0),
        )
        assert result.hero.armor == 5
        assert result.hero.hero_class == "WARRIOR"
        assert result.hero.is_hero_card is True

    def test_hero_card_resets_power(self):
        state = _simple_state(mana=8, max_mana=8)
        state.hero.hero_power_used = True
        hero_card = _make_card(
            name="Test Hero", cost=8, card_type="HERO", text="获得 5 点护甲"
        )
        state.hand.append(hero_card)

        result = apply_action(
            state,
            Action(action_type=ActionType.HERO_REPLACE, card_index=0),
        )
        assert result.hero.hero_power_used is False


# ===================================================================
# Task 1.5: apply_action new action types
# ===================================================================


class TestNewActionTypes:
    def test_transform_action(self):
        state = _simple_state(
            opp_board=[
                Minion(
                    name="Big Threat",
                    attack=8,
                    health=8,
                    max_health=8,
                    has_taunt=True,
                    has_divine_shield=True,
                    owner="enemy",
                ),
            ]
        )
        result = apply_action(
            state,
            Action(action_type=ActionType.TRANSFORM, target_index=1),
        )
        assert result.opponent.board[0].attack == 1
        assert result.opponent.board[0].health == 1
        assert result.opponent.board[0].has_taunt is False
        assert result.opponent.board[0].has_divine_shield is False

    def test_play_with_target_spell(self):
        state = _simple_state(mana=5, max_mana=5, opp_hp=10)
        spell = _make_card(
            name="Fireball", cost=4, card_type="SPELL", text="造成 6 点伤害"
        )
        state.hand.append(spell)

        result = apply_action(
            state,
            Action(
                action_type=ActionType.PLAY_WITH_TARGET,
                card_index=0,
                target_index=0,
            ),
        )
        assert result.opponent.hero.hp == 4
        assert len(result.hand) == 0

    def test_end_turn_clears_modifiers(self):
        state = _simple_state(mana=5, max_mana=5)
        state.mana.add_modifier("temp", 1, "this_turn")
        assert len(state.mana.modifiers) == 1

        result = apply_action(state, Action(action_type=ActionType.END_TURN))
        assert len(result.mana.modifiers) == 0

    def test_hero_power_uses_dynamic_cost(self):
        state = _simple_state(mana=3, max_mana=5)
        state.hero.hero_class = "PRIEST"
        state.hero.hero_power_cost = 1
        state.hero.hero_power_damage = 0
        state.hero.hp = 25

        result = apply_action(state, Action(action_type=ActionType.HERO_POWER))
        assert result.mana.available == 2
        assert result.hero.hero_power_used is True

    def test_action_describe_new_types(self):
        a1 = Action(action_type=ActionType.HERO_REPLACE, card_index=0)
        assert "替换英雄" in a1.describe()

        a2 = Action(action_type=ActionType.TRANSFORM, target_index=1)
        assert "变形" in a2.describe()

        a3 = Action(
            action_type=ActionType.PLAY_WITH_TARGET,
            card_index=0,
            target_index=1,
        )
        assert "定向打出" in a3.describe()

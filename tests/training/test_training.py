"""Tests for analysis/training/ package"""

import os
import tempfile
import pytest

from analysis.card.engine.state import GameState, Minion, HeroState, ManaState, OpponentState, Weapon
from analysis.card.engine.tags import GameTag
from analysis.card.abilities.definition import Action, ActionType
from analysis.card.models.card import Card
from analysis.training.ability_tags import (
    encode_ability_tag, pool_ability_tags, effect_to_tag, ABILITY_TAG_DIM
)
from analysis.training.encoder import StateEncoder, ActionEncoder
from analysis.training.extractor import TrainingDataExtractor, TrainingSample
from analysis.training.pipeline import TrainingPipeline


class TestAbilityTags:
    def test_tag_dimensions(self):
        tag = encode_ability_tag("DAMAGE:ALL_ENEMY:3")
        assert len(tag) == ABILITY_TAG_DIM == 52

    def test_zero_value_tag(self):
        tag = encode_ability_tag("HEAL:FRIENDLY_HERO:0")
        assert tag[7] == 1.0  # HEAL is at index 7 in _PRIMARY_EFFECT_KINDS

    def test_pool_ability_tags(self):
        tags = ["DAMAGE:ALL_ENEMY:3", "SUMMON:FRIENDLY_MINION:1"]
        pooled = pool_ability_tags(tags)
        assert len(pooled) == 52

    def test_empty_pool(self):
        pooled = pool_ability_tags([])
        assert len(pooled) == 52
        assert all(v == 0.0 for v in pooled)

    def test_effect_to_tag(self):
        tag = effect_to_tag({"effect_kind": "DAMAGE", "target_kind": "ALL_ENEMY", "value": 3})
        assert tag == "DAMAGE:ALL_ENEMY:3"

    def test_effect_to_tag_none(self):
        tag = effect_to_tag({})
        assert tag is None


class TestStateEncoder:
    def setup_method(self):
        self.enc = StateEncoder()

    def test_default_state(self):
        vec = self.enc.encode(GameState())
        assert len(vec) == 294

    def test_populated_state(self):
        state = GameState(
            hero=HeroState(hp=25, armor=5),
            board=[Minion(attack=5, health=3, tags={GameTag.TAUNT: 1})],
            deck_remaining=20,
        )
        vec = self.enc.encode(state)
        assert len(vec) == 294
        # Hero HP feature should be 25/30
        assert abs(vec[0] - 25/30) < 0.01
        # Armor feature should be 5/30
        assert abs(vec[1] - 5/30) < 0.01

    def test_minion_encoding(self):
        m = Minion(attack=7, health=5, tags={GameTag.DIVINE_SHIELD: 1, GameTag.RUSH: 1})
        vec = self.enc._encode_minion(m)
        assert len(vec) == 15
        assert abs(vec[0] - 0.7) < 0.01  # attack/10
        assert abs(vec[1] - 0.5) < 0.01  # health/10
        assert vec[3] == 0.0  # can_attack (default False)
        assert vec[5] == 1.0  # has_divine_shield
        assert vec[7] == 1.0  # has_rush

    def test_full_board(self):
        state = GameState(board=[Minion(attack=i+1) for i in range(7)])
        vec = self.enc.encode(state)
        assert len(vec) == 294

    def test_weapon_encoding(self):
        state = GameState(hero=HeroState(weapon=Weapon(attack=3, health=2)))
        vec = self.enc.encode(state)
        assert abs(vec[2] - 0.3) < 0.01  # weapon_attack/10
        assert abs(vec[3] - 0.2) < 0.01  # weapon_durability/10


class TestActionEncoder:
    def setup_method(self):
        self.enc = ActionEncoder()

    def test_play_action(self):
        a = Action(action_type=ActionType.PLAY, card_index=3)
        vec = self.enc.encode(a)
        assert len(vec) == 13
        assert vec[0] == 1.0  # PLAY is first in ACTION_TYPES

    def test_attack_action(self):
        a = Action(action_type=ActionType.ATTACK, source_index=2, target_index=5)
        vec = self.enc.encode(a)
        assert len(vec) == 13
        assert vec[2] == 1.0  # ATTACK is third in ACTION_TYPES

    def test_end_turn(self):
        a = Action(action_type=ActionType.END_TURN)
        vec = self.enc.encode(a)
        assert len(vec) == 13
        assert vec[9] == 1.0  # END_TURN is tenth

    def test_batch(self):
        actions = [
            Action(action_type=ActionType.PLAY, card_index=0),
            Action(action_type=ActionType.END_TURN),
        ]
        batch = self.enc.encode_batch(actions)
        assert len(batch) == 2
        assert len(batch[0]) == 13


class TestTrainingDataExtractor:
    def setup_method(self):
        self.ext = TrainingDataExtractor()

    def test_reward_win(self):
        reward = self.ext.extract_action_reward(
            GameState(), Action(action_type=ActionType.END_TURN), GameState(), 1.0
        )
        assert -1.0 <= reward <= 1.0
        assert reward > 0  # win should be positive

    def test_reward_loss(self):
        reward = self.ext.extract_action_reward(
            GameState(), Action(action_type=ActionType.END_TURN), GameState(), -1.0
        )
        assert reward < 0  # loss should be negative

    def test_jsonl_roundtrip(self):
        samples = [
            TrainingSample(
                state_vector=[0.0]*294,
                action_vector=[0.0]*13,
                reward=0.75,
                meta={"game_id": "test", "turn": 3}
            )
        ]
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            path = f.name
        try:
            self.ext.to_jsonl(samples, path)
            loaded = self.ext.from_jsonl(path)
            assert len(loaded) == 1
            assert abs(loaded[0].reward - 0.75) < 0.01
            assert loaded[0].meta["game_id"] == "test"
        finally:
            os.unlink(path)

    def test_board_value(self):
        # Friendly advantage should have positive value
        good_state = GameState(
            hero=HeroState(hp=30),
            board=[Minion(attack=5, health=5)],
            opponent=OpponentState(hero=HeroState(hp=20)),
        )
        bad_state = GameState(
            hero=HeroState(hp=10),
            opponent=OpponentState(hero=HeroState(hp=30), board=[Minion(attack=5, health=5)]),
        )
        good_val = self.ext._board_value(good_state)
        bad_val = self.ext._board_value(bad_state)
        assert good_val > bad_val

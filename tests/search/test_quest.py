"""V10 Phase 3 Batch 5 tests — Quest progress tracking."""

import pytest
from types import SimpleNamespace
from analysis.search.game_state import GameState, HeroState, ManaState, OpponentState
from analysis.models.card import Card
from analysis.search.quest import (
    QuestState, parse_quest, track_quest_progress,
    _parse_threshold, _parse_constraint, _determine_quest_type,
)


def _make_card(**kw):
    defaults = dict(dbf_id=1, name="TestCard", cost=1, card_type="MINION", attack=1, health=1)
    defaults.update(kw)
    return Card(**defaults)


def _make_state():
    return GameState(
        hero=HeroState(hp=30),
        mana=ManaState(available=10, max_mana=10),
        opponent=OpponentState(hero=HeroState(hp=30)),
    )


class TestParseQuest:
    def test_identifies_quest_mechanic_card(self):
        """parse_quest identifies QUEST mechanic card."""
        card = _make_card(
            dbf_id=121159, name="征战时光之末",
            mechanics=["QUEST"],
            text="<b>任务：</b>填满你的手牌，然后清空。<b>奖励：</b>提克和托克。",
        )
        result = parse_quest(card)
        assert result is not None
        assert result.quest_name == "征战时光之末"
        assert result.quest_dbf_id == 121159

    def test_extracts_threshold_from_text(self):
        """parse_quest extracts threshold from text."""
        # "总计3张" → threshold 3
        card = _make_card(
            name="围攻城门",
            mechanics=["QUEST", "SIDE_QUEST"],
            text="<b>支线任务：</b>使用亡灵或野兽牌，总计3张。<b>奖励：</b>制造一个自定义的僵尸兽",
        )
        result = parse_quest(card)
        assert result is not None
        assert result.threshold == 3

        # "施放4个" → threshold 4
        card2 = _make_card(
            name="寻求平衡",
            mechanics=["QUEST"],
            text="<b>任务：</b>施放4个神圣法术。<b>奖励：</b>生命之息",
        )
        result2 = parse_quest(card2)
        assert result2 is not None
        assert result2.threshold == 4

    def test_identifies_side_quest(self):
        """parse_quest identifies SIDE_QUEST."""
        card = _make_card(
            name="围攻城门",
            mechanics=["QUEST", "SIDE_QUEST"],
            text="<b>支线任务：</b>使用亡灵或野兽牌，总计3张。<b>奖励：</b>制造",
        )
        result = parse_quest(card)
        assert result is not None
        assert result.is_side_quest is True

    def test_returns_none_for_non_quest_card(self):
        """parse_quest returns None for non-quest card."""
        card = _make_card(mechanics=["BATTLECRY"], text="战吼：造成2点伤害")
        result = parse_quest(card)
        assert result is None


class TestQuestTracking:
    def test_quest_activation(self):
        """Playing quest spell adds to active_quests."""
        card = _make_card(
            dbf_id=120648, name="围攻城门",
            card_type="SPELL",
            mechanics=["QUEST", "SIDE_QUEST"],
            text="<b>支线任务：</b>使用亡灵或野兽牌，总计3张。<b>奖励：</b>制造",
        )
        quest = parse_quest(card)
        assert quest is not None
        state = _make_state()
        state.active_quests.append(quest)
        assert len(state.active_quests) == 1
        assert state.active_quests[0].quest_name == "围攻城门"

    def test_quest_progress_matching_card(self):
        """Playing matching card increments progress."""
        quest = QuestState(
            quest_name="围攻城门",
            quest_type="play_cards",
            threshold=3,
            quest_constraint="UNDEAD,BEAST",
        )
        state = _make_state()
        state.active_quests.append(quest)

        undead_card = _make_card(race="UNDEAD", card_type="MINION")
        state = track_quest_progress(state, "PLAY", undead_card)
        assert state.active_quests[0].progress == 1

    def test_quest_progress_non_matching_card(self):
        """Non-matching card doesn't increment progress."""
        quest = QuestState(
            quest_name="围攻城门",
            quest_type="play_cards",
            threshold=3,
            quest_constraint="UNDEAD,BEAST",
        )
        state = _make_state()
        state.active_quests.append(quest)

        dragon_card = _make_card(race="DRAGON", card_type="MINION")
        state = track_quest_progress(state, "PLAY", dragon_card)
        assert state.active_quests[0].progress == 0

    def test_quest_completion_reward(self):
        """Quest completion: progress reaches threshold → reward added to hand."""
        quest = QuestState(
            quest_name="围攻城门",
            quest_type="play_cards",
            progress=2,
            threshold=3,
            reward_name="奖励卡牌",
            quest_constraint="UNDEAD,BEAST",
        )
        state = _make_state()
        state.active_quests.append(quest)

        undead_card = _make_card(race="UNDEAD", card_type="MINION")
        state = track_quest_progress(state, "PLAY", undead_card)
        assert state.active_quests[0].completed is True
        assert len(state.hand) == 1
        assert state.hand[0].name == "奖励卡牌"

    def test_quest_completion_hand_full(self):
        """Quest completion: hand full → reward not added (no crash)."""
        quest = QuestState(
            quest_name="围攻城门",
            quest_type="play_cards",
            progress=2,
            threshold=3,
            reward_name="奖励卡牌",
        )
        state = _make_state()
        # Fill hand to 10 (max)
        state.hand = [_make_card() for _ in range(10)]
        state.active_quests.append(quest)

        matching_card = _make_card()
        state = track_quest_progress(state, "PLAY", matching_card)
        assert state.active_quests[0].completed is True
        assert len(state.hand) == 10  # No crash, no extra card

    def test_multiple_quests_independent(self):
        """Multiple quests tracked independently."""
        quest1 = QuestState(quest_name="Quest1", quest_type="play_cards", threshold=3)
        quest2 = QuestState(quest_name="Quest2", quest_type="cast_spells", threshold=2)
        state = _make_state()
        state.active_quests.extend([quest1, quest2])

        # Play a minion — should increment quest1 but not quest2
        minion_card = _make_card(card_type="MINION")
        state = track_quest_progress(state, "PLAY", minion_card)
        assert state.active_quests[0].progress == 1
        assert state.active_quests[1].progress == 0

        # Play a spell — should increment quest2
        spell_card = _make_card(card_type="SPELL")
        state = track_quest_progress(state, "PLAY", spell_card)
        assert state.active_quests[0].progress == 2  # quest1 also counts play_cards
        assert state.active_quests[1].progress == 1

    def test_completed_quest_no_further_progress(self):
        """Completed quest doesn't track further progress."""
        quest = QuestState(
            quest_name="Done",
            quest_type="play_cards",
            progress=3,
            threshold=3,
            completed=True,
        )
        state = _make_state()
        state.active_quests.append(quest)

        card = _make_card()
        state = track_quest_progress(state, "PLAY", card)
        assert state.active_quests[0].progress == 3  # No increment

    def test_cast_spells_only_counts_spells(self):
        """cast_spells quest only counts spells, not minions."""
        quest = QuestState(quest_name="Spell Quest", quest_type="cast_spells", threshold=4)
        state = _make_state()
        state.active_quests.append(quest)

        # Play a minion — should NOT increment
        minion_card = _make_card(card_type="MINION")
        state = track_quest_progress(state, "PLAY", minion_card)
        assert state.active_quests[0].progress == 0

        # Play a spell — should increment
        spell_card = _make_card(card_type="SPELL")
        state = track_quest_progress(state, "PLAY", spell_card)
        assert state.active_quests[0].progress == 1

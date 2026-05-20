"""quest.py — Quest progress tracking system.

Tracks quest card activation, progress, and completion.
Parses quest card text to determine quest type, threshold, and constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from analysis.card.abilities.definition import ActionKind as ActionType

_QUEST_THRESHOLD_EN = re.compile(r"(\d+)\s*(?:cards?|spells?|minions?)")
_QUEST_REWARD_EN = re.compile(
    r"Reward[：:]\s*</?b?>\s*(.+?)(?:<|$)", re.IGNORECASE
)

# English race/spell school names for constraint detection
_RACE_NAMES = frozenset(
    {
        "DRAGON", "UNDEAD", "BEAST", "DEMON", "MECHANICAL",
        "ELEMENTAL", "MURLOC", "PIRATE", "TOTEM", "ELF", "TREANT",
    }
)
_SPELL_SCHOOL_NAMES = frozenset(
    {
        "HOLY", "FIRE", "SHADOW", "FROST", "ARCANE", "FEL",
        "NATURE", "VOID", "BLOOD", "AIR", "EARTH", "WATER",
    }
)


# ===================================================================
# QuestState dataclass
# ===================================================================


@dataclass
class QuestState:
    """Tracks state of a single active quest."""

    quest_name: str = ""
    quest_dbf_id: int = 0
    quest_type: str = ""
    progress: int = 0
    threshold: int = 3
    reward_name: str = ""
    reward_dbf_id: int = 0
    is_side_quest: bool = False
    completed: bool = False
    quest_constraint: str = ""


# ===================================================================
# Constraint parsing helpers
# ===================================================================


def _parse_constraint(text: str, english_text: str = "") -> str:
    """Extract quest constraint (race or spell school) from English card text."""
    constraints = []
    en_lower = english_text.lower()
    for name in _RACE_NAMES:
        if name.lower() in en_lower:
            constraints.append(name)
    for name in _SPELL_SCHOOL_NAMES:
        if name.lower() in en_lower:
            constraints.append(name)
    return ",".join(constraints)


def _parse_threshold(
    text: str, structured_value: Optional[int] = None
) -> int:
    if structured_value is not None:
        return structured_value
    m = _QUEST_THRESHOLD_EN.search(text)
    if m:
        return int(m.group(1))
    return 3


def _determine_quest_type(text: str, english_text: str = "") -> str:
    """Determine quest type from English card text patterns."""
    en = english_text.lower()
    if "draw" in en and "discard" in en:
        return "draw_discard"
    if "cast" in en and "spell" in en:
        return "cast_spells"
    if "summon" in en:
        return "summon_minions"
    if "play" in en:
        return "play_cards"
    return "generic"


def _parse_reward_name(
    text: str, structured_reward: Optional[str] = None
) -> str:
    if structured_reward:
        return structured_reward
    m = _QUEST_REWARD_EN.search(text)
    if m:
        name = m.group(1).strip().rstrip(".")
        if name:
            return name
    return "Quest Reward"


# ===================================================================
# parse_quest
# ===================================================================


def parse_quest(card) -> Optional[QuestState]:
    mechanics = getattr(card, "mechanics", None) or []
    has_quest = "QUEST" in mechanics or "SIDEBQUEST" in mechanics
    if not has_quest:
        text = getattr(card, "text", "") or ""
        if not text:
            return None
        has_quest = "quest" in text.lower()
    if not has_quest:
        return None

    text = getattr(card, "text", "") or ""
    english_text = getattr(card, "english_text", "") or ""
    name = getattr(card, "name", "") or ""
    dbf_id = getattr(card, "dbf_id", 0) or getattr(card, "dbfId", 0)
    quest_progress_total = getattr(card, "quest_progress_total", None)
    quest_reward = getattr(card, "quest_reward", None)

    quest_type = _determine_quest_type(text, english_text=english_text)

    return QuestState(
        quest_name=name,
        quest_dbf_id=dbf_id,
        quest_type=quest_type,
        threshold=_parse_threshold(
            text, structured_value=quest_progress_total
        ),
        reward_name=_parse_reward_name(text, structured_reward=quest_reward),
        is_side_quest="SIDEBQUEST" in mechanics or "SIDE_QUEST" in mechanics,
        quest_constraint=_parse_constraint(text, english_text=english_text),
    )


# ===================================================================
# track_quest_progress
# ===================================================================


def track_quest_progress(state, action_type, card=None):
    """Update quest progress for all active (non-completed) quests.

    Called after a PLAY action in apply_action. Returns modified state.
    When a quest reaches its threshold, it is marked completed and
    a reward card is added to hand (if hand is not full, max 10 cards).
    """
    if isinstance(action_type, ActionType):
        action_type = action_type.name

    play_action = ActionType.PLAY.name

    for quest in state.active_quests:
        if quest.completed:
            continue

        should_increment = False

        if quest.quest_type == "play_cards" and action_type == play_action:
            if not quest.quest_constraint:
                should_increment = True
            elif card is not None:
                card_race = (getattr(card, "race", "") or "").upper()
                card_type_cat = (
                    getattr(card, "card_type", "") or ""
                ).upper()
                constraints = set(quest.quest_constraint.split(","))
                if card_race in constraints or card_type_cat in constraints:
                    should_increment = True

        elif (
            quest.quest_type == "cast_spells"
            and action_type == play_action
            and card is not None
        ):
            card_type_cat = (
                getattr(card, "card_type", "") or ""
            ).upper()
            if card_type_cat == "SPELL":
                if not quest.quest_constraint:
                    should_increment = True
                else:
                    card_school = (
                        getattr(card, "spell_school", "")
                        or getattr(card, "spellSchool", "")
                        or ""
                    ).upper()
                    constraints = set(quest.quest_constraint.split(","))
                    if card_school in constraints:
                        should_increment = True

        elif (
            quest.quest_type == "summon_minions"
            and action_type == play_action
            and card is not None
        ):
            card_type_cat = (
                getattr(card, "card_type", "") or ""
            ).upper()
            if card_type_cat == "MINION":
                should_increment = True

        elif quest.quest_type == "generic" and action_type == play_action:
            should_increment = True

        elif (
            quest.quest_type == "draw_discard"
            and action_type == play_action
        ):
            should_increment = True

        if should_increment:
            quest.progress += 1

        if quest.progress >= quest.threshold and not quest.completed:
            quest.completed = True
            if len(state.hand) < 10:
                from types import SimpleNamespace

                reward = SimpleNamespace(
                    name=quest.reward_name or "Quest Reward",
                    cost=0,
                    card_type="SPELL",
                    dbf_id=quest.reward_dbf_id,
                    attack=0,
                    health=0,
                    text="",
                    mechanics=[],
                )
                state.hand.append(reward)

    return state

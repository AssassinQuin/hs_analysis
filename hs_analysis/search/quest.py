"""quest.py — Quest progress tracking system.

V10 Phase 3: Tracks quest card activation, progress, and completion.
Parses quest card text to determine quest type, threshold, and constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ===================================================================
# QuestState dataclass
# ===================================================================

@dataclass
class QuestState:
    """Tracks state of a single active quest."""

    quest_name: str = ""
    quest_dbf_id: int = 0
    quest_type: str = ""           # "play_cards", "cast_spells", "summon_minions", "draw_discard", "generic"
    progress: int = 0
    threshold: int = 3
    reward_name: str = ""
    reward_dbf_id: int = 0
    is_side_quest: bool = False
    completed: bool = False
    quest_constraint: str = ""     # "UNDEAD", "BEAST", "HOLY", "SHADOW" etc.


# ===================================================================
# Constraint parsing helpers
# ===================================================================

# Map Chinese race/type names to uppercase English constants
_RACE_MAP = {
    "亡灵": "UNDEAD",
    "野兽": "BEAST",
    "恶魔": "DEMON",
    "龙": "DRAGON",
    "鱼人": "MURLOC",
    "机械": "MECHANICAL",
    "元素": "ELEMENTAL",
    "海盗": "PIRATE",
    "图腾": "TOTEM",
    "全部": "ALL",
}

_SPELL_SCHOOL_MAP = {
    "神圣": "HOLY",
    "暗影": "SHADOW",
    "火焰": "FIRE",
    "冰霜": "FROST",
    "自然": "NATURE",
    "奥术": "ARCANE",
    "邪能": "FEL",
}


def _parse_constraint(text: str) -> str:
    """Extract quest constraint (race or spell school) from card text.

    Returns comma-separated uppercase constraint string, e.g. 'UNDEAD,BEAST'.
    """
    constraints = []
    for cn_name, eng_name in _RACE_MAP.items():
        if cn_name in text:
            constraints.append(eng_name)
    for cn_name, eng_name in _SPELL_SCHOOL_MAP.items():
        if cn_name in text:
            constraints.append(eng_name)
    return ",".join(constraints)


def _parse_threshold(text: str, structured_value: Optional[int] = None) -> int:
    if structured_value is not None:
        return structured_value
    m = re.search(r'(\d+)\s*(?:cards?|spells?|minions?)', text)
    if m:
        return int(m.group(1))
    m = re.search(r'总计(\d+)张', text)
    if m:
        return int(m.group(1))
    m = re.search(r'施放(\d+)个', text)
    if m:
        return int(m.group(1))
    m = re.search(r'(\d+)张', text)
    if m:
        return int(m.group(1))
    return 3


def _determine_quest_type(text: str) -> str:
    """Determine quest type from card text patterns."""
    if "填满" in text and "清空" in text:
        return "draw_discard"
    if "施放" in text and "法术" in text:
        return "cast_spells"
    if "召唤" in text:
        return "summon_minions"
    if "使用" in text:
        return "play_cards"
    return "generic"


def _parse_reward_name(text: str, structured_reward: Optional[str] = None) -> str:
    if structured_reward:
        return structured_reward
    m = re.search(r'Reward[：:]\s*</?b?>\s*(.+?)(?:<|$)', text, re.IGNORECASE)
    if m:
        name = m.group(1).strip().rstrip('.')
        if name:
            return name
    m = re.search(r'奖励[：:]</b>([^<]+)', text)
    if m:
        name = m.group(1).strip().rstrip('。')
        if name:
            return name
    m = re.search(r'奖励[：:](.+?)(?:<|$)', text)
    if m:
        name = m.group(1).strip().rstrip('。')
        if name:
            return name
    return "奖励卡牌"


# ===================================================================
# parse_quest
# ===================================================================

def parse_quest(card) -> Optional[QuestState]:
    mechanics = getattr(card, 'mechanics', None) or []
    has_quest = "QUEST" in mechanics or "SIDEBQUEST" in mechanics
    if not has_quest:
        text = getattr(card, 'text', '') or ''
        if not text:
            return None
        has_quest = "quest" in text.lower() or "任务" in text
    if not has_quest:
        return None

    text = getattr(card, 'text', '') or ''
    name = getattr(card, 'name', '') or ''
    dbf_id = getattr(card, 'dbf_id', 0) or getattr(card, 'dbfId', 0)
    quest_progress_total = getattr(card, 'quest_progress_total', None)
    quest_reward = getattr(card, 'quest_reward', None)

    quest_type = _determine_quest_type(text) if not mechanics else _determine_quest_type(text)

    return QuestState(
        quest_name=name,
        quest_dbf_id=dbf_id,
        quest_type=quest_type,
        threshold=_parse_threshold(text, structured_value=quest_progress_total),
        reward_name=_parse_reward_name(text, structured_reward=quest_reward),
        is_side_quest="SIDEBQUEST" in mechanics or "SIDE_QUEST" in mechanics,
        quest_constraint=_parse_constraint(text),
    )


# ===================================================================
# track_quest_progress
# ===================================================================

def track_quest_progress(state, action_type: str, card=None):
    """Update quest progress for all active (non-completed) quests.

    Called after a PLAY action in apply_action. Returns modified state.
    When a quest reaches its threshold, it is marked completed and
    a reward card is added to hand (if hand is not full, max 10 cards).
    """
    for quest in state.active_quests:
        if quest.completed:
            continue

        should_increment = False

        if quest.quest_type == "play_cards" and action_type == "PLAY":
            if not quest.quest_constraint:
                should_increment = True
            elif card is not None:
                # Check if card matches any constraint
                card_race = (getattr(card, 'race', '') or '').upper()
                card_type = (getattr(card, 'card_type', '') or '').upper()
                constraints = set(quest.quest_constraint.split(','))
                if card_race in constraints or card_type in constraints:
                    should_increment = True

        elif quest.quest_type == "cast_spells" and action_type == "PLAY" and card is not None:
            card_type = (getattr(card, 'card_type', '') or '').upper()
            if card_type == "SPELL":
                if not quest.quest_constraint:
                    should_increment = True
                else:
                    # Check spell school match
                    card_school = (
                        getattr(card, 'spell_school', '')
                        or getattr(card, 'spellSchool', '')
                        or ''
                    ).upper()
                    # Also try to infer from card text
                    card_text = getattr(card, 'text', '') or ''
                    constraints = set(quest.quest_constraint.split(','))
                    if card_school in constraints:
                        should_increment = True
                    else:
                        # Check Chinese text for spell school keywords
                        from hs_analysis.search.quest import _SPELL_SCHOOL_MAP
                        for cn_name, eng_name in _SPELL_SCHOOL_MAP.items():
                            if eng_name in constraints and cn_name in card_text:
                                should_increment = True
                                break

        elif quest.quest_type == "summon_minions" and action_type == "PLAY" and card is not None:
            card_type = (getattr(card, 'card_type', '') or '').upper()
            if card_type == "MINION":
                should_increment = True

        elif quest.quest_type == "generic" and action_type == "PLAY":
            should_increment = True

        elif quest.quest_type == "draw_discard" and action_type == "PLAY":
            # Simplified: any PLAY action counts toward draw/discard quests
            should_increment = True

        if should_increment:
            quest.progress += 1

        # Check completion
        if quest.progress >= quest.threshold and not quest.completed:
            quest.completed = True
            # Add reward card to hand if not full (max 10)
            if len(state.hand) < 10:
                from types import SimpleNamespace
                reward = SimpleNamespace(
                    name=quest.reward_name or "奖励卡牌",
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

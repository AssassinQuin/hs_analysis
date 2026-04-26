#!/usr/bin/env python3
"""actions.py — Action dataclass and ActionType enum for the search engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState


class ActionType(Enum):
    PLAY = auto()
    PLAY_WITH_TARGET = auto()
    ATTACK = auto()
    HERO_POWER = auto()
    ACTIVATE_LOCATION = auto()
    HERO_REPLACE = auto()
    DISCOVER_PICK = auto()
    CHOOSE_ONE = auto()
    TRANSFORM = auto()
    END_TURN = auto()


@dataclass
class Action:
    """A single action in a Hearthstone turn."""

    action_type: ActionType
    card_index: int = -1
    position: int = -1
    source_index: int = -1
    target_index: int = -1
    data: int = 0
    discover_choice_index: int = -1
    step_order: int = 0
    meta_tags: frozenset[str] = frozenset()

    def describe(self, state: Optional[GameState] = None) -> str:
        if self.action_type == ActionType.PLAY:
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            tgt = ""
            if self.target_index > 0:
                tgt = f" → 目标#{self.target_index}"
            return f"手牌[{self.card_index}] 打出 [{card_name}]{tgt}"
        elif self.action_type == ActionType.PLAY_WITH_TARGET:
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            return f"手牌[{self.card_index}] 定向打出 [{card_name}] → 目标#{self.target_index}"
        elif self.action_type == ActionType.ATTACK:
            if self.source_index == -1:
                return f"英雄武器 攻击 目标#{self.target_index}"
            return f"随从#{self.source_index} 攻击 目标#{self.target_index}"
        elif self.action_type == ActionType.HERO_POWER:
            return "使用英雄技能"
        elif self.action_type == ActionType.END_TURN:
            return "结束回合"
        elif self.action_type == ActionType.ACTIVATE_LOCATION:
            return f"激活地标#{self.source_index}"
        elif self.action_type == ActionType.HERO_REPLACE:
            card_name = "未知英雄牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = state.hand[self.card_index].name or "英雄牌"
            return f"手牌[{self.card_index}] 替换英雄 [{card_name}]"
        elif self.action_type == ActionType.DISCOVER_PICK:
            return f"发现选择#{self.discover_choice_index}"
        elif self.action_type == ActionType.TRANSFORM:
            return f"变形 目标#{self.target_index}"
        elif self.action_type == ActionType.CHOOSE_ONE:
            return f"抉择#{self.data} 选择#{self.discover_choice_index}"
        return f"未知动作({self.action_type})"


def action_key(action: Action) -> tuple:
    """Return a hashable key for action comparison.

    Includes card_name for PLAY actions so that different cards at the same
    hand index produce distinct keys (e.g., Coin at idx 0 vs Foxy at idx 0
    after Coin is played).

    meta_tags are intentionally excluded to keep legality checks compatible.
    """
    card_name = getattr(action, '_card_name', '') or ''
    return (
        action.action_type,
        action.card_index,
        action.position,
        action.source_index,
        action.target_index,
        card_name,
    )


def action_in_list(action: Action, legal: list) -> bool:
    """Check if *action* matches any action in *legal* (by key)."""
    ak = action_key(action)
    return any(action_key(la) == ak for la in legal)

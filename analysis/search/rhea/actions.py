#!/usr/bin/env python3
"""actions.py — Action dataclass for the RHEA search engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState


@dataclass
class Action:
    """A single action in a Hearthstone turn."""

    action_type: str
    card_index: int = -1
    position: int = -1
    source_index: int = -1
    target_index: int = -1
    data: int = 0
    discover_choice_index: int = -1
    step_order: int = 0

    def describe(self, state: Optional[GameState] = None) -> str:
        if self.action_type == "PLAY":
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            tgt = ""
            if self.target_index > 0:
                tgt = f" → 目标#{self.target_index}"
            return f"手牌[{self.card_index}] 打出 [{card_name}]{tgt}"
        elif self.action_type == "PLAY_WITH_TARGET":
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = (
                    state.hand[self.card_index].name or f"卡牌#{self.card_index}"
                )
            return f"手牌[{self.card_index}] 定向打出 [{card_name}] → 目标#{self.target_index}"
        elif self.action_type == "ATTACK":
            if self.source_index == -1:
                return f"英雄武器 攻击 目标#{self.target_index}"
            return f"随从#{self.source_index} 攻击 目标#{self.target_index}"
        elif self.action_type == "HERO_POWER":
            return "使用英雄技能"
        elif self.action_type == "END_TURN":
            return "结束回合"
        elif self.action_type == "ACTIVATE_LOCATION":
            return f"激活地标#{self.source_index}"
        elif self.action_type == "HERO_REPLACE":
            card_name = "未知英雄牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = state.hand[self.card_index].name or "英雄牌"
            return f"手牌[{self.card_index}] 替换英雄 [{card_name}]"
        elif self.action_type == "DISCOVER_PICK":
            return f"发现选择#{self.discover_choice_index}"
        elif self.action_type == "TRANSFORM":
            return f"变形 目标#{self.target_index}"
        return f"未知动作({self.action_type})"


def action_key(action: Action) -> tuple:
    """Return a hashable key for action comparison."""
    return (
        action.action_type,
        action.card_index,
        action.position,
        action.source_index,
        action.target_index,
    )


def action_in_list(action: Action, legal: list) -> bool:
    """Check if *action* matches any action in *legal* (by key)."""
    ak = action_key(action)
    return any(action_key(la) == ak for la in legal)

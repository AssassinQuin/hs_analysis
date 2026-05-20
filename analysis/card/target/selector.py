"""target/selector.py — 目标选择器系统。

TargetSelector 枚举 + TargetResolver 解析引擎。
从 SabberStone/Spellsource 枚举设计借鉴。
"""
from __future__ import annotations

import random
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState


# ═══════════════════════════════════════════════════════════════
# TargetSelector — 24枚举选择器
# ═══════════════════════════════════════════════════════════════

class TargetSelector(Enum):
    """目标选择器枚举。

    命名约定:
      - 全大写
      - FRIENDLY/ENEMY 前缀表示阵营
      - CHARACTER = HERO + MINION
    """

    # ── 单一目标 ──
    SELF = auto()                       # 施法者自己（随从/英雄）
    TARGET = auto()                     # 玩家指定的目标
    FRIENDLY_HERO = auto()              # 友方英雄
    ENEMY_HERO = auto()                 # 敌方英雄

    # ── 全体范围 ──
    ALL_MINIONS = auto()                # 所有随从
    ALL_CHARACTERS = auto()             # 所有角色（英雄+随从）
    ALL_ENEMY_CHARACTERS = auto()       # 所有敌方角色
    ALL_FRIENDLY_CHARACTERS = auto()    # 所有友方角色
    FRIENDLY_MINIONS = auto()           # 所有友方随从
    ENEMY_MINIONS = auto()              # 所有敌方随从
    OTHER_FRIENDLY_MINIONS = auto()     # 除自己外的友方随从

    # ── 随机目标 ──
    RANDOM_ENEMY_CHARACTER = auto()     # 随机敌方角色
    RANDOM_ENEMY_MINION = auto()        # 随机敌方随从
    RANDOM_FRIENDLY_CHARACTER = auto()  # 随机友方角色
    RANDOM_FRIENDLY_MINION = auto()     # 随机友方随从
    RANDOM_ALL_CHARACTERS = auto()      # 随机任意角色

    # ── 特化 ──
    ANY = auto()                        # 任意角色（有 target 用 target，无则全部）
    NONE = auto()                       # 无目标

    # ── 位置相关 ──
    ADJACENT_MINIONS = auto()           # 相邻随从
    LEFT_MINION = auto()                # 左边随从
    RIGHT_MINION = auto()               # 右边随从

    # ── 数值条件 ──
    MOST_DAMAGED_CHARACTER = auto()     # 血量最低的角色
    MOST_DAMAGED_FRIENDLY = auto()      # 血量最低的友方
    MOST_DAMAGED_ENEMY = auto()         # 血量最低的敌方


# ═══════════════════════════════════════════════════════════════
# 字符串 ↔ enum 映射
# ═══════════════════════════════════════════════════════════════

_SELECTOR_ALIASES: Dict[str, TargetSelector] = {
    "SELF": TargetSelector.SELF,
    "TARGET": TargetSelector.TARGET,
    "FRIENDLY_HERO": TargetSelector.FRIENDLY_HERO,
    "ENEMY_HERO": TargetSelector.ENEMY_HERO,
    "ALL_MINIONS": TargetSelector.ALL_MINIONS,
    "ALL_CHARACTERS": TargetSelector.ALL_CHARACTERS,
    "ALL_ENEMY_CHARACTERS": TargetSelector.ALL_ENEMY_CHARACTERS,
    "ALL_FRIENDLY_CHARACTERS": TargetSelector.ALL_FRIENDLY_CHARACTERS,
    "FRIENDLY_MINION": TargetSelector.FRIENDLY_MINIONS,
    "FRIENDLY_MINIONS": TargetSelector.FRIENDLY_MINIONS,
    "ENEMY_MINION": TargetSelector.ENEMY_MINIONS,
    "ENEMY_MINIONS": TargetSelector.ENEMY_MINIONS,
    "OTHER_FRIENDLY_MINIONS": TargetSelector.OTHER_FRIENDLY_MINIONS,
    "RANDOM_ENEMY_CHARACTER": TargetSelector.RANDOM_ENEMY_CHARACTER,
    "RANDOM_ENEMY_MINION": TargetSelector.RANDOM_ENEMY_MINION,
    "RANDOM_FRIENDLY_CHARACTER": TargetSelector.RANDOM_FRIENDLY_CHARACTER,
    "RANDOM_FRIENDLY_MINION": TargetSelector.RANDOM_FRIENDLY_MINION,
    "RANDOM_ALL_CHARACTERS": TargetSelector.RANDOM_ALL_CHARACTERS,
    "ANY": TargetSelector.ANY,
    "NONE": TargetSelector.NONE,
    "ADJACENT_MINIONS": TargetSelector.ADJACENT_MINIONS,
    "LEFT_MINION": TargetSelector.LEFT_MINION,
    "RIGHT_MINION": TargetSelector.RIGHT_MINION,
    "MOST_DAMAGED_CHARACTER": TargetSelector.MOST_DAMAGED_CHARACTER,
    "MOST_DAMAGED_FRIENDLY": TargetSelector.MOST_DAMAGED_FRIENDLY,
    "MOST_DAMAGED_ENEMY": TargetSelector.MOST_DAMAGED_ENEMY,
}


def parse_selector(name: Optional[str]) -> Optional[TargetSelector]:
    """将字符串解析为 TargetSelector，失败返回 None。"""
    if not name:
        return None
    return _SELECTOR_ALIASES.get(name.upper().strip())


# ═══════════════════════════════════════════════════════════════
# TargetResolver — 解析引擎
# ═══════════════════════════════════════════════════════════════

class TargetResolver:
    """将 TargetSelector 解析为实体列表。

    用法:
        targets = TargetResolver.resolve(selector, state, source, action_target)
    """

    @staticmethod
    def resolve(
        selector: TargetSelector,
        state: GameState,
        source: Any = None,
        action_target: Any = None,
    ) -> List[Any]:
        """返回匹配选择器的实体列表。"""
        board = list(state.board) if state.board else []
        opp_board = list(state.opponent.board) if state.opponent.board else []

        handler = _RESOLVERS.get(selector)
        if handler is None:
            return []
        return handler(state, source, action_target, board, opp_board)


# ── 各选择器的解析函数 ──

def _self(state, source, action_target, board, opp_board):
    return [source] if source else []

def _target(state, source, action_target, board, opp_board):
    return [action_target] if action_target else []

def _friendly_hero(state, source, action_target, board, opp_board):
    return [state.hero]

def _enemy_hero(state, source, action_target, board, opp_board):
    return [state.opponent.hero]

def _all_minions(state, source, action_target, board, opp_board):
    return board + opp_board

def _all_characters(state, source, action_target, board, opp_board):
    return [state.hero] + board + [state.opponent.hero] + opp_board

def _all_enemy_characters(state, source, action_target, board, opp_board):
    return [state.opponent.hero] + opp_board

def _all_friendly_characters(state, source, action_target, board, opp_board):
    return [state.hero] + board

def _friendly_minions(state, source, action_target, board, opp_board):
    return board

def _enemy_minions(state, source, action_target, board, opp_board):
    return opp_board

def _other_friendly_minions(state, source, action_target, board, opp_board):
    if source in board:
        return [m for m in board if m is not source]
    return board

def _random_enemy_character(state, source, action_target, board, opp_board):
    pool = [state.opponent.hero] + opp_board
    return [random.choice(pool)] if pool else []

def _random_enemy_minion(state, source, action_target, board, opp_board):
    return [random.choice(opp_board)] if opp_board else []

def _random_friendly_character(state, source, action_target, board, opp_board):
    pool = [state.hero] + board
    return [random.choice(pool)] if pool else []

def _random_friendly_minion(state, source, action_target, board, opp_board):
    return [random.choice(board)] if board else []

def _random_all_characters(state, source, action_target, board, opp_board):
    pool = [state.hero, state.opponent.hero] + board + opp_board
    return [random.choice(pool)] if pool else []

def _any(state, source, action_target, board, opp_board):
    if action_target:
        return [action_target]
    return [state.hero] + board + [state.opponent.hero] + opp_board

def _adjacent_minions(state, source, action_target, board, opp_board):
    """相邻随从：根据 source 在 board 中的位置取左右。"""
    if source is None or source not in board:
        return []
    idx = board.index(source)
    result = []
    if idx > 0:
        result.append(board[idx - 1])
    if idx < len(board) - 1:
        result.append(board[idx + 1])
    return result

def _left_minion(state, source, action_target, board, opp_board):
    if source is None or source not in board:
        return []
    idx = board.index(source)
    return [board[idx - 1]] if idx > 0 else []

def _right_minion(state, source, action_target, board, opp_board):
    if source is None or source not in board:
        return []
    idx = board.index(source)
    return [board[idx + 1]] if idx < len(board) - 1 else []

def _most_damaged(entity_list):
    """从列表中找出血量百分比最低的实体。"""
    if not entity_list:
        return []
    best = min(
        entity_list,
        key=lambda e: (
            getattr(e, 'hp', getattr(e, 'health', 30))
            / max(getattr(e, 'max_hp', getattr(e, 'max_health', 30)), 1)
        ),
    )
    return [best]

def _most_damaged_character(state, source, action_target, board, opp_board):
    pool = [state.hero, state.opponent.hero] + board + opp_board
    return _most_damaged(pool)

def _most_damaged_friendly(state, source, action_target, board, opp_board):
    pool = [state.hero] + board
    return _most_damaged(pool)

def _most_damaged_enemy(state, source, action_target, board, opp_board):
    pool = [state.opponent.hero] + opp_board
    return _most_damaged(pool)


_RESOLVERS = {
    TargetSelector.SELF: _self,
    TargetSelector.TARGET: _target,
    TargetSelector.FRIENDLY_HERO: _friendly_hero,
    TargetSelector.ENEMY_HERO: _enemy_hero,
    TargetSelector.ALL_MINIONS: _all_minions,
    TargetSelector.ALL_CHARACTERS: _all_characters,
    TargetSelector.ALL_ENEMY_CHARACTERS: _all_enemy_characters,
    TargetSelector.ALL_FRIENDLY_CHARACTERS: _all_friendly_characters,
    TargetSelector.FRIENDLY_MINIONS: _friendly_minions,
    TargetSelector.ENEMY_MINIONS: _enemy_minions,
    TargetSelector.OTHER_FRIENDLY_MINIONS: _other_friendly_minions,
    TargetSelector.RANDOM_ENEMY_CHARACTER: _random_enemy_character,
    TargetSelector.RANDOM_ENEMY_MINION: _random_enemy_minion,
    TargetSelector.RANDOM_FRIENDLY_CHARACTER: _random_friendly_character,
    TargetSelector.RANDOM_FRIENDLY_MINION: _random_friendly_minion,
    TargetSelector.RANDOM_ALL_CHARACTERS: _random_all_characters,
    TargetSelector.ANY: _any,
    TargetSelector.NONE: lambda *a: [],
    TargetSelector.ADJACENT_MINIONS: _adjacent_minions,
    TargetSelector.LEFT_MINION: _left_minion,
    TargetSelector.RIGHT_MINION: _right_minion,
    TargetSelector.MOST_DAMAGED_CHARACTER: _most_damaged_character,
    TargetSelector.MOST_DAMAGED_FRIENDLY: _most_damaged_friendly,
    TargetSelector.MOST_DAMAGED_ENEMY: _most_damaged_enemy,
}


# ═══════════════════════════════════════════════════════════════
# 便捷接口: 字符串也可直接解析
# ═══════════════════════════════════════════════════════════════

def resolve_target(
    target_spec: Optional[str],
    state: GameState,
    source: Any = None,
    action_target: Any = None,
) -> List[Any]:
    """字符串 → TargetResolver 的便捷接口。

    兼容旧版调用方式 (resolve_target("ALL_ENEMY_CHARACTERS", ...))。
    """
    sel = parse_selector(target_spec)
    if sel is None:
        return []
    return TargetResolver.resolve(sel, state, source, action_target)

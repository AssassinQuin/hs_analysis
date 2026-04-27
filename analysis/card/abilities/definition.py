#!/usr/bin/env python3
"""definition.py — Core data types for the unified card ability system.

All enums and data classes are derived from real data analysis of 7898
collectible cards in cards.collectible.json (enUS).

Architecture:
  Layer 1: Types (this file)
  Layer 2: Parsing (parser.py, effect_parser.py)
  Layer 3: Execution (executor.py)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, List, Optional, Union


# ──────────────────────────────────────────────────────────────
# Trigger — when does this ability fire?
# ──────────────────────────────────────────────────────────────

class AbilityTrigger(Enum):
    BATTLECRY = "BATTLECRY"
    DEATHRATTLE = "DEATHRATTLE"
    SECRET = "SECRET"
    INSPIRE = "INSPIRE"
    CHOOSE_ONE = "CHOOSE_ONE"
    COMBO = "COMBO"
    OUTCAST = "OUTCAST"
    SPELLBURST = "SPELLBURST"
    INFUSE = "INFUSE"
    CORRUPT = "CORRUPT"
    QUEST = "QUEST"
    TURN_START = "TURN_START"
    TURN_END = "TURN_END"
    WHENEVER = "WHENEVER"
    AFTER = "AFTER"
    ON_ATTACK = "ON_ATTACK"
    ON_DAMAGE = "ON_DAMAGE"
    ON_SPELL_CAST = "ON_SPELL_CAST"
    ON_FEL_SPELL_CAST = "ON_FEL_SPELL_CAST"
    ON_DEATH = "ON_DEATH"
    AURA = "AURA"
    PASSIVE_COST = "PASSIVE_COST"
    ACTIVATE = "ACTIVATE"
    TRIGGER_VISUAL = "TRIGGER_VISUAL"
    # ── Keyword triggers (detected from card text) ──
    HERALD = "HERALD"           # 兆示: increment herald counter, summon soldier
    IMBUE = "IMBUE"             # 灌注: upgrade hero power
    KINDRED = "KINDRED"         # 延系: conditional bonus if race/school matches
    COLOSSAL = "COLOSSAL"       # 巨型: summon appendage minions
    CORPSE_SPEND = "CORPSE_SPEND"  # 残骸: spend corpse resource for bonus
    CORPSE_GAIN = "CORPSE_GAIN"    # 获得残骸
    DORMANT = "DORMANT"         # 休眠: enter dormant for N turns


# ──────────────────────────────────────────────────────────────
# Effect — what does this ability do?
# ──────────────────────────────────────────────────────────────

class EffectKind(Enum):
    DAMAGE = "DAMAGE"
    SUMMON = "SUMMON"
    DRAW = "DRAW"
    GAIN = "GAIN"
    GIVE = "GIVE"
    DESTROY = "DESTROY"
    COPY = "COPY"
    HEAL = "HEAL"
    SHUFFLE = "SHUFFLE"
    REDUCE_COST = "REDUCE_COST"
    TRANSFORM = "TRANSFORM"
    RETURN = "RETURN"
    TAKE_CONTROL = "TAKE_CONTROL"
    DISCARD = "DISCARD"
    SWAP = "SWAP"
    WEAPON_EQUIP = "WEAPON_EQUIP"
    DISCOVER = "DISCOVER"
    FREEZE = "FREEZE"
    SILENCE = "SILENCE"
    CAST_SPELL = "CAST_SPELL"
    ENCHANT = "ENCHANT"
    # ── Bridged from effects.py (P8 adapter) ──
    BUFF = "BUFF"                    # Give stats to friendly minions
    ARMOR = "ARMOR"                  # Gain armor
    RANDOM_DAMAGE = "RANDOM_DAMAGE"  # Damage random enemy
    AOE_DAMAGE = "AOE_DAMAGE"        # Damage all enemies
    MANA = "MANA"                    # Gain/modify mana
    # ── Keyword effects (from standalone modules) ──
    HERALD_SUMMON = "HERALD_SUMMON"         # summon class-specific soldier
    IMBUE_UPGRADE = "IMBUE_UPGRADE"         # hero.imbue_level += 1
    COMBO_DISCOUNT = "COMBO_DISCOUNT"       # next combo card costs N less
    OUTCAST_DRAW = "OUTCAST_DRAW"           # draw N (outcast position bonus)
    OUTCAST_BUFF = "OUTCAST_BUFF"           # buff +N/+N (outcast position bonus)
    OUTCAST_COST = "OUTCAST_COST"           # cost override (outcast position bonus)
    COLOSSAL_SUMMON = "COLOSSAL_SUMMON"     # summon N appendage minions
    KINDRED_BUFF = "KINDRED_BUFF"           # conditional race-matched bonus
    CORRUPT_UPGRADE = "CORRUPT_UPGRADE"     # upgrade card in hand if higher-cost played
    CORPSE_EFFECT = "CORPSE_EFFECT"         # spend/gain corpse resource + bonus


# ──────────────────────────────────────────────────────────────
# Condition — when is this ability active?
# ──────────────────────────────────────────────────────────────

class ConditionKind(Enum):
    HOLDING_RACE = "HOLDING_RACE"
    THIS_TURN = "THIS_TURN"
    FOR_EACH = "FOR_EACH"
    HAS_KEYWORD = "HAS_KEYWORD"
    PLAYED_THIS_TURN = "PLAYED_THIS_TURN"
    COST_COMPARISON = "COST_COMPARISON"
    HEALTH_THRESHOLD = "HEALTH_THRESHOLD"
    BOARD_STATE = "BOARD_STATE"
    HAND_POSITION = "HAND_POSITION"   # card at leftmost/rightmost in hand (Outcast)
    RACE_MATCH = "RACE_MATCH"         # card race/school matches last turn plays (Kindred)
    RESOURCE_SUFFICIENT = "RESOURCE_SUFFICIENT"  # enough corpses/etc for effect


# ──────────────────────────────────────────────────────────────
# Target — who/what does this ability affect?
# ──────────────────────────────────────────────────────────────

class TargetKind(Enum):
    SINGLE_MINION = "SINGLE_MINION"
    RANDOM = "RANDOM"
    FRIENDLY_HERO = "FRIENDLY_HERO"
    FRIENDLY_MINION = "FRIENDLY_MINION"
    RANDOM_ENEMY = "RANDOM_ENEMY"
    ALL_MINIONS = "ALL_MINIONS"
    ENEMY = "ENEMY"
    ALL_ENEMY = "ALL_ENEMY"
    ALL_FRIENDLY = "ALL_FRIENDLY"
    DAMAGED = "DAMAGED"
    UNDAMAGED = "UNDAMAGED"
    SELF = "SELF"
    ALL = "ALL"


# ══════════════════════════════════════════════════════════════
# LazyValue — deferred numeric evaluation
# ══════════════════════════════════════════════════════════════

class LazyValue:
    """A numeric value that is resolved at execution time, not parse time.

    Supports:
      - Literal: LazyValue(3)  → always 3
      - Attribute: LazyValue.attr("attack")  → source.attack at runtime
      - Count: LazyValue.count("hand")  → len(state.hand) at runtime
      - Arithmetic: LazyValue.attr("attack") * 2

    Usage:
        amount = LazyValue.attr("attack") + 1
        result = amount.resolve(state, source)  # int
    """

    def __init__(self, literal: Optional[int] = None):
        self._literal = literal
        self._op: Optional[str] = None
        self._operand: Optional[Union[int, 'LazyValue']] = None
        self._source_attr: Optional[str] = None
        self._count_field: Optional[str] = None

    @classmethod
    def attr(cls, name: str) -> 'LazyValue':
        """Resolve to source.<name> at runtime (e.g. source.attack)."""
        lv = cls()
        lv._source_attr = name
        return lv

    @classmethod
    def count(cls, field_name: str) -> 'LazyValue':
        """Resolve to count of entities in a state field."""
        lv = cls()
        lv._count_field = field_name
        return lv

    def resolve(self, state: Any = None, source: Any = None) -> int:
        """Evaluate this lazy value to a concrete integer."""
        if self._literal is not None:
            base = self._literal
        elif self._source_attr:
            base = int(getattr(source, self._source_attr, 0) or 0)
        elif self._count_field:
            collection = getattr(state, self._count_field, [])
            base = len(collection) if collection else 0
        else:
            base = 0

        if self._op and self._operand is not None:
            operand = (
                self._operand.resolve(state, source)
                if isinstance(self._operand, LazyValue)
                else self._operand
            )
            if self._op == '+':
                base = base + operand
            elif self._op == '-':
                base = base - operand
            elif self._op == '*':
                base = base * operand
            elif self._op == '//':
                base = base // max(operand, 1)

        return max(base, 0)

    def __add__(self, other: Union[int, 'LazyValue']) -> 'LazyValue':
        lv = LazyValue()
        lv._op = '+'
        lv._operand = other
        # Chain: if self has a literal, keep it; otherwise chain from source
        if self._literal is not None:
            lv._literal = self._literal
        elif self._source_attr:
            lv._source_attr = self._source_attr
        elif self._count_field:
            lv._count_field = self._count_field
        return lv

    def __mul__(self, other: Union[int, 'LazyValue']) -> 'LazyValue':
        lv = LazyValue()
        lv._op = '*'
        lv._operand = other
        if self._literal is not None:
            lv._literal = self._literal
        elif self._source_attr:
            lv._source_attr = self._source_attr
        elif self._count_field:
            lv._count_field = self._count_field
        return lv

    def __repr__(self):
        if self._literal is not None:
            base = str(self._literal)
        elif self._source_attr:
            base = f"source.{self._source_attr}"
        elif self._count_field:
            base = f"count({self._count_field})"
        else:
            base = "0"
        if self._op:
            return f"({base} {self._op} {self._operand})"
        return base


# ══════════════════════════════════════════════════════════════
# EntitySelector — unified entity selection
# ══════════════════════════════════════════════════════════════

class EntitySelector:
    """Describes which entities an effect targets.

    Combines a TargetKind with optional filters (race, keyword, cost, etc.)
    for precise selection that TargetSpec alone can't express.

    Usage:
        sel = EntitySelector(TargetKind.ALL_FRIENDLY, filters={"race": "DRAGON"})
        minions = sel.select(state, source)  # List[Minion]
    """

    def __init__(
        self,
        kind: TargetKind,
        side: str = "",
        filters: Optional[dict] = None,
        count: int = 1,
    ):
        self.kind = kind
        self.side = side
        self.filters = filters or {}
        self.count = count

    def select(self, state: Any, source: Any = None) -> list:
        """Return matching entities from the game state."""
        if self.kind in (TargetKind.ALL_ENEMY,):
            candidates = list(state.opponent.board)
        elif self.kind in (TargetKind.ALL_FRIENDLY,):
            candidates = list(state.board)
        elif self.kind in (TargetKind.ALL_MINIONS, TargetKind.ALL):
            candidates = list(state.board) + list(state.opponent.board)
        elif self.kind == TargetKind.FRIENDLY_MINION:
            candidates = list(state.board)
        elif self.kind in (TargetKind.ENEMY, TargetKind.SINGLE_MINION):
            candidates = list(state.opponent.board)
        elif self.kind == TargetKind.RANDOM_ENEMY:
            candidates = list(state.opponent.board)
        elif self.kind == TargetKind.RANDOM:
            if self.side == "enemy":
                candidates = list(state.opponent.board)
            else:
                candidates = list(state.board)
        elif self.kind == TargetKind.SELF:
            return [source] if source else []
        elif self.kind == TargetKind.FRIENDLY_HERO:
            return [state.hero]
        else:
            candidates = list(state.board) + list(state.opponent.board)

        # Apply filters
        result = []
        for e in candidates:
            if self._matches(e):
                result.append(e)

        return result

    def _matches(self, entity) -> bool:
        """Check if entity matches all filters."""
        for key, value in self.filters.items():
            if key == "race":
                race = getattr(entity, 'race', '').upper()
                races = getattr(entity, 'races', None)
                if race != value.upper():
                    if not races or value.upper() not in [r.upper() for r in races]:
                        return False
            elif key == "keyword":
                field_map = {
                    'TAUNT': 'has_taunt', 'DIVINE_SHIELD': 'has_divine_shield',
                    'RUSH': 'has_rush', 'CHARGE': 'has_charge',
                    'STEALTH': 'has_stealth', 'WINDFURY': 'has_windfury',
                    'POISONOUS': 'has_poisonous', 'LIFESTEAL': 'has_lifesteal',
                }
                attr = field_map.get(value.upper())
                if attr and not getattr(entity, attr, False):
                    return False
            elif key == "damaged":
                if not (entity.health < entity.max_health):
                    return False
            elif key == "undamaged":
                if not (entity.health >= entity.max_health):
                    return False
            elif key == "max_cost":
                cost = getattr(entity, 'cost', 999)
                if cost > value:
                    return False
            elif key == "min_cost":
                cost = getattr(entity, 'cost', 0)
                if cost < value:
                    return False
        return True

    def __repr__(self):
        parts = [f"Select({self.kind.value}"]
        if self.filters:
            parts.append(f" where {self.filters}")
        parts.append(")")
        return "".join(parts)


# ══════════════════════════════════════════════════════════════
# Data classes
# ══════════════════════════════════════════════════════════════

@dataclass
class ConditionSpec:
    kind: ConditionKind
    params: dict = field(default_factory=dict)

    def check(self, state, source) -> bool:
        from analysis.card.engine.executor import check_condition
        return check_condition(self, state, source)


@dataclass
class TargetSpec:
    kind: TargetKind
    count: int = 1
    side: str = ""
    filters: list = field(default_factory=list)


@dataclass
class EffectSpec:
    kind: EffectKind
    value: Union[int, LazyValue] = 0
    value2: Union[int, LazyValue] = 0
    subtype: str = ""
    keyword: str = ""
    target: Optional[TargetSpec] = None
    selector: Optional[EntitySelector] = None
    condition: Optional[ConditionSpec] = None
    text_raw: str = ""

    def resolve_value(self, state=None, source=None) -> int:
        """Resolve value to int (handles both int and LazyValue)."""
        v = self.value
        return v.resolve(state, source) if isinstance(v, LazyValue) else v

    def resolve_value2(self, state=None, source=None) -> int:
        """Resolve value2 to int (handles both int and LazyValue)."""
        v = self.value2
        return v.resolve(state, source) if isinstance(v, LazyValue) else v


@dataclass
class CardAbility:
    trigger: AbilityTrigger
    condition: Optional[ConditionSpec] = None
    effects: List[EffectSpec] = field(default_factory=list)
    text_raw: str = ""

    def is_active(self, state, source) -> bool:
        if self.condition is None:
            return True
        return self.condition.check(state, source)

    def execute(self, state, source, target=None):
        from analysis.card.engine.executor import execute_effects
        return execute_effects(state, source, self.effects, target)

    def __repr__(self):
        parts = [f"Ability({self.trigger.value}"]
        if self.condition:
            parts.append(f" if {self.condition.kind.value}")
        if self.effects:
            eff_strs = [e.kind.value for e in self.effects]
            parts.append(f" -> {','.join(eff_strs)}")
        parts.append(")")
        return "".join(parts)


# ══════════════════════════════════════════════════════════════
# Action — merged from actions.py
# ══════════════════════════════════════════════════════════════

class ActionType(Enum):
    PLAY = "PLAY"
    PLAY_WITH_TARGET = "PLAY_WITH_TARGET"
    ATTACK = "ATTACK"
    HERO_POWER = "HERO_POWER"
    ACTIVATE_LOCATION = "ACTIVATE_LOCATION"
    HERO_REPLACE = "HERO_REPLACE"
    DISCOVER_PICK = "DISCOVER_PICK"
    CHOOSE_ONE = "CHOOSE_ONE"
    TRANSFORM = "TRANSFORM"
    END_TURN = "END_TURN"


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

    def describe(self, state=None) -> str:
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

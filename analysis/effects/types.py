"""types.py — Core data types for the unified effect system.

All enums and dataclasses are card-game-agnostic at the type level.
Hearthstone-specific semantics live in the parser and resolver layers.

Design principles:
  1. Every effect is a typed value object (not a raw tuple or dict).
  2. Targets are first-class specs (not inline params).
  3. Conditions are composable (not boolean soup).
  4. No direct coupling to GameState, Card, or any runtime object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ════════════════════════════════════════════════════════════════
# Triggers — when does an ability fire?
# ════════════════════════════════════════════════════════════════

class Trigger(Enum):
    """Timing/event that causes an ability to activate."""
    # Standard triggers
    BATTLECRY = "battlecry"
    DEATHRATTLE = "deathrattle"
    COMBO = "combo"
    SPELLBURST = "spellburst"
    CHOOSE_ONE = "choose_one"
    SECRET = "secret"
    INSPIRE = "inspire"
    FRENZY = "frenzy"
    OUTCAST = "outcast"
    INFUSE = "infuse"
    CORRUPT = "corrupt"
    QUEST = "quest"
    ACTIVATE = "activate"           # Location activation

    # Continuous / event-based
    AURA = "aura"
    TRIGGER_VISUAL = "trigger_visual"

    # Turn lifecycle
    TURN_START = "turn_start"
    TURN_END = "turn_end"

    # Reactive
    ON_ATTACK = "on_attack"
    ON_DAMAGE = "on_damage"
    ON_SPELL_CAST = "on_spell_cast"
    ON_DEATH = "on_death"
    ON_HEAL = "on_heal"
    WHENEVER = "whenever"
    AFTER = "after"

    # Cost modifiers
    PASSIVE_COST = "passive_cost"
    COMBO_DISCOUNT = "combo_discount"

    # Keyword bridges
    HERALD = "herald"
    IMBUE = "imbue"
    KINDRED = "kindred"
    COLOSSAL = "colossal"
    CORPSE = "corpse"
    DORMANT = "dormant"
    DARK_GIFT = "dark_gift"


# ════════════════════════════════════════════════════════════════
# Effect kinds — what does an effect do?
# ════════════════════════════════════════════════════════════════

class EffectKind(Enum):
    """Taxonomy of primitive effect types.

    Each kind maps to one or more executor primitives.
    The Parser produces EffectKind + params; the Resolver dispatches
    to the matching primitive(s).
    """
    # — Damage & healing —
    DAMAGE = "damage"
    HEAL = "heal"
    ARMOR = "armor"
    AOE_DAMAGE = "aoe_damage"
    RANDOM_DAMAGE = "random_damage"
    LIFESTEAL = "lifesteal"

    # — Summon / spawn —
    SUMMON = "summon"
    SUMMON_COPY = "summon_copy"
    SUMMON_FROM_DECK = "summon_from_deck"
    SUMMON_FROM_HAND = "summon_from_hand"
    SUMMON_FROM_GRAVEYARD = "summon_from_graveyard"

    # — Card movement —
    DRAW = "draw"
    DISCARD = "discard"
    SHUFFLE = "shuffle"
    SHUFFLE_INTO = "shuffle_into"       # shuffle cards into deck
    RETURN_TO_HAND = "return_to_hand"
    RETURN_TO_BOARD = "return_to_board"
    TAKE_CONTROL = "take_control"

    # — Stat modification —
    BUFF = "buff"                       # +atk/+hp on board
    DEBUFF = "debuff"                   # -atk/-hp on board
    HAND_BUFF = "hand_buff"             # +atk/+hp in hand
    DECK_BUFF = "deck_buff"             # +atk/+hp in deck
    SET_STATS = "set_stats"             # set atk/hp to specific values
    SWAP_STATS = "swap_stats"           # swap atk and hp

    # — State modification —
    FREEZE = "freeze"
    SILENCE = "silence"
    DESTROY = "destroy"
    TRANSFORM = "transform"
    ENRAGE = "enrage"                   # +atk when damaged

    # — Mana / cost —
    REDUCE_COST = "reduce_cost"
    INCREASE_COST = "increase_cost"
    GAIN_MANA = "gain_mana"
    OVERLOAD = "overload"

    # — Resource —
    CORPSE_GAIN = "corpse_gain"
    CORPSE_SPEND = "corpse_spend"

    # — Equipment —
    WEAPON_EQUIP = "weapon_equip"
    HERO_POWER_SET = "hero_power_set"

    # — Card generation —
    DISCOVER = "discover"
    CREATE = "create"
    COPY_CARD = "copy_card"
    CAST_SPELL = "cast_spell"

    # — Enchantment —
    ENCHANT = "enchant"
    REMOVE_ENCHANT = "remove_enchant"

    # — Keyword bridges —
    HERALD_SUMMON = "herald_summon"
    IMBUE_UPGRADE = "imbue_upgrade"
    KINDRED_BUFF = "kindred_buff"
    COLOSSAL_SUMMON = "colossal_summon"
    CORRUPT_UPGRADE = "corrupt_upgrade"
    DARK_GIFT_APPLY = "dark_gift_apply"
    DORMANT_ENTER = "dormant_enter"
    DORMANT_WAKE = "dormant_wake"

    # — Search / draw modifiers —
    FATIGUE = "fatigue"

    # — Utility —
    TAG = "tag"                         # set a runtime tag on an entity
    UNTAG = "untag"
    CUSTOM = "custom"                   # extension point for ad-hoc effects


# ════════════════════════════════════════════════════════════════
# Targets — who/what does an effect apply to?
# ════════════════════════════════════════════════════════════════

class TargetKind(Enum):
    """Selection strategy for effect application."""
    # — Singular targets —
    NONE = "none"                          # no target (e.g. gain Armor)
    SELECTED = "selected"                  # player-chosen target
    SELF = "self"                          # the card itself

    # — Board characters —
    ANY_CHARACTER = "any_character"
    ANY_MINION = "any_minion"
    FRIENDLY_MINION = "friendly_minion"
    ENEMY_MINION = "enemy_minion"
    ALL_CHARACTERS = "all_characters"
    ALL_MINIONS = "all_minions"
    ALL_ENEMIES = "all_enemies"
    ALL_FRIENDLY = "all_friendly"
    ALL_OTHER_MINIONS = "all_other_minions"
    ADJACENT_MINIONS = "adjacent_minions"
    LEFT_NEIGHBOR = "left_neighbor"
    RIGHT_NEIGHBOR = "right_neighbor"
    OPPOSING_MINION = "opposing_minion"

    # — Heroes —
    HERO = "hero"
    ENEMY_HERO = "enemy_hero"
    FRIENDLY_HERO = "friendly_hero"
    ALL_HEROES = "all_heroes"

    # — Random —
    RANDOM_ENEMY = "random_enemy"
    RANDOM_FRIENDLY = "random_friendly"
    RANDOM_MINION = "random_minion"
    RANDOM_ENEMY_MINION = "random_enemy_minion"
    RANDOM_FRIENDLY_MINION = "random_friendly_minion"
    RANDOM_CHARACTER = "random_character"

    # — Zones —
    HAND = "hand"
    DECK = "deck"
    BOARD = "board"
    GRAVEYARD = "graveyard"
    SECRETS = "secrets"
    ALL_ZONES = "all_zones"

    # — Query-based —
    DAMAGED_CHARACTER = "damaged_character"
    DAMAGED_MINION = "damaged_minion"
    DAMAGED_FRIENDLY = "damaged_friendly"
    DEMON_FRIENDLY = "demon_friendly"
    HIGHEST_ATTACK = "highest_attack"
    LOWEST_HEALTH = "lowest_health"
    LEFTMOST_HAND = "leftmost_hand"
    RIGHTMOST_HAND = "rightmost_hand"

    # — Everything —
    EVERYTHING = "everything"


@dataclass
class TargetSpec:
    """Complete target description for an effect.

    Examples:
      TargetSpec(TargetKind.ANY_MINION)              → "a minion"
      TargetSpec(TargetKind.RANDOM_ENEMY_MINION, count=2) → "2 random enemy minions"
      TargetSpec(TargetKind.DAMAGED_FRIENDLY)         → "a damaged friendly character"
      TargetSpec(TargetKind.SELECTED, owner_filter="enemy") → enemy-chosen target
    """
    kind: TargetKind
    owner_filter: str = ""  # "friendly" | "enemy" | "" (both)
    count: int = 1
    random: bool = False
    exact_count: bool = False     # True = exactly N (not "up to N")
    allow_duplicates: bool = False

    # Sub-filters
    min_attack: int | None = None
    max_attack: int | None = None
    min_health: int | None = None
    max_health: int | None = None
    race_filter: str = ""         # e.g. "DEMON", "MURLOC"
    damaged_only: bool = False
    not_damaged_only: bool = False
    taunt_only: bool = False
    rush_only: bool = False
    price_filter: str = ""        # "≤3", ">5" etc for cost-limited discovers

    def is_singular(self) -> bool:
        return self.count == 1 and not self.random

    def is_aoe(self) -> bool:
        return self.kind in _AOE_KINDS

    def is_random(self) -> bool:
        return self.random or self.kind in _RANDOM_KINDS


_AOE_KINDS: frozenset[TargetKind] = frozenset({
    TargetKind.ALL_CHARACTERS,
    TargetKind.ALL_MINIONS,
    TargetKind.ALL_ENEMIES,
    TargetKind.ALL_FRIENDLY,
    TargetKind.ALL_OTHER_MINIONS,
    TargetKind.EVERYTHING,
})

_RANDOM_KINDS: frozenset[TargetKind] = frozenset({
    TargetKind.RANDOM_ENEMY,
    TargetKind.RANDOM_FRIENDLY,
    TargetKind.RANDOM_MINION,
    TargetKind.RANDOM_ENEMY_MINION,
    TargetKind.RANDOM_FRIENDLY_MINION,
    TargetKind.RANDOM_CHARACTER,
})


# ════════════════════════════════════════════════════════════════
# Conditions — when does an effect (or ability) actually apply?
# ════════════════════════════════════════════════════════════════

class ConditionKind(Enum):
    """Predicate kinds for conditional effects."""
    # — State checks —
    HAS_TAG = "has_tag"                     # entity has a runtime tag
    NOT_TAGGED = "not_tagged"
    HEALTH_ABOVE = "health_above"
    HEALTH_BELOW = "health_below"
    IS_DAMAGED = "is_damaged"
    IS_FROZEN = "is_frozen"

    # — Board state —
    BOARD_SIZE = "board_size"               # compare friendly board size
    ENEMY_BOARD_SIZE = "enemy_board_size"
    HAND_SIZE = "hand_size"
    DECK_REMAINING = "deck_remaining"
    CORPSES_AVAILABLE = "corpses_available"
    MANA_AVAILABLE = "mana_available"

    # — Card properties —
    CARD_TYPE = "card_type"                 # e.g. minion/spell/weapon
    CARD_CLASS = "card_class"
    CARD_RACE = "card_race"
    CARD_COST = "card_cost"
    CARD_ATTACK = "card_attack"
    CARD_HEALTH = "card_health"
    HAS_MECHANIC = "has_mechanic"

    # — History —
    SPELLS_CAST_THIS_TURN = "spells_cast_this_turn"
    CARDS_DRAWN_THIS_TURN = "cards_drawn_this_turn"
    MINIONS_DIED_THIS_TURN = "minions_died_this_turn"
    DAMAGE_TAKEN_THIS_TURN = "damage_taken_this_turn"
    CARDS_PLAYED_THIS_TURN = "cards_played_this_turn"
    LAST_CARD_PLAYED = "last_card_played"
    MINIONS_PLAYED_THIS_GAME = "minions_played_this_game"

    # — Turn state —
    IS_YOUR_TURN = "is_your_turn"
    TURN_NUMBER = "turn_number"
    FATIGUE_COUNT = "fatigue_count"

    # — Composition —
    AND = "and"     # all sub-conditions must pass
    OR = "or"       # any sub-condition must pass
    NOT = "not"     # negate sub-condition


@dataclass
class ConditionSpec:
    """A single condition or logical combinator.

    For atomic conditions:
      kind = ConditionKind.BOARD_SIZE
      params = {"op": ">=", "value": 7}

    For logical combinators (AND/OR/NOT):
      kind = ConditionKind.AND
      sub: list of sub-conditions
    """
    kind: ConditionKind
    params: dict[str, Any] = field(default_factory=dict)
    sub: list[ConditionSpec] = field(default_factory=list)

    @classmethod
    def simple(cls, kind: ConditionKind, **params: Any) -> ConditionSpec:
        return cls(kind=kind, params=params)

    def and_(self, *others: ConditionSpec) -> ConditionSpec:
        return ConditionSpec(
            kind=ConditionKind.AND,
            sub=[self, *others],
        )

    def or_(self, *others: ConditionSpec) -> ConditionSpec:
        return ConditionSpec(
            kind=ConditionKind.OR,
            sub=[self, *others],
        )

    def negate(self) -> ConditionSpec:
        return ConditionSpec(
            kind=ConditionKind.NOT,
            sub=[self],
        )


# ════════════════════════════════════════════════════════════════
# Effects — the core value objects
# ════════════════════════════════════════════════════════════════

@dataclass
class Effect:
    """A single atomic effect from a card ability.

    Parser responsibility: produce a flat list of Effects from card text.
    Resolver responsibility: interpret kind + params + target against GameState.

    The params dict is typed per EffectKind (see PARAMS_SCHEMA below).
    """
    kind: EffectKind
    params: dict[str, Any] = field(default_factory=dict)
    target: TargetSpec = field(default_factory=lambda: TargetSpec(TargetKind.NONE))
    condition: ConditionSpec | None = None

    # ---- Convenience constructors ----

    @classmethod
    def damage(cls, amount: int, target: TargetSpec | None = None) -> Effect:
        return cls(
            kind=EffectKind.DAMAGE,
            params={"amount": amount},
            target=target or TargetSpec(TargetKind.SELECTED),
        )

    @classmethod
    def aoe_damage(cls, amount: int, target: TargetKind = TargetKind.ALL_ENEMIES) -> Effect:
        return cls(
            kind=EffectKind.AOE_DAMAGE,
            params={"amount": amount},
            target=TargetSpec(target),
        )

    @classmethod
    def random_damage(cls, amount: int, count: int = 1,
                      target: TargetKind = TargetKind.RANDOM_ENEMY) -> Effect:
        return cls(
            kind=EffectKind.RANDOM_DAMAGE,
            params={"amount": amount, "splits": count},
            target=TargetSpec(target, random=True),
        )

    @classmethod
    def heal(cls, amount: int, target: TargetSpec | None = None) -> Effect:
        return cls(
            kind=EffectKind.HEAL,
            params={"amount": amount},
            target=target or TargetSpec(TargetKind.SELECTED),
        )

    @classmethod
    def armor(cls, amount: int) -> Effect:
        return cls(
            kind=EffectKind.ARMOR,
            params={"amount": amount},
            target=TargetSpec(TargetKind.SELF),
        )

    @classmethod
    def summon(cls, card_id: str = "", attack: int = 0, health: int = 0,
               count: int = 1) -> Effect:
        params = {"count": count}
        if card_id:
            params["card_id"] = card_id
        if attack or health:
            params["attack"] = attack
            params["health"] = health
        return cls(
            kind=EffectKind.SUMMON,
            params=params,
            target=TargetSpec(TargetKind.BOARD),
        )

    @classmethod
    def draw(cls, count: int = 1) -> Effect:
        return cls(
            kind=EffectKind.DRAW,
            params={"count": count},
            target=TargetSpec(TargetKind.DECK),
        )

    @classmethod
    def buff(cls, attack: int, health: int,
             target: TargetSpec | None = None) -> Effect:
        return cls(
            kind=EffectKind.BUFF,
            params={"attack": attack, "health": health},
            target=target or TargetSpec(TargetKind.SELECTED),
        )

    @classmethod
    def discover(cls, pool: str = "", count: int = 3,
                 from_class: str = "") -> Effect:
        return cls(
            kind=EffectKind.DISCOVER,
            params={"pool": pool, "count": count, "from_class": from_class},
            target=TargetSpec(TargetKind.NONE),
        )

    @classmethod
    def destroy(cls, target: TargetSpec | None = None) -> Effect:
        return cls(
            kind=EffectKind.DESTROY,
            target=target or TargetSpec(TargetKind.SELECTED),
        )

    @classmethod
    def gain_mana(cls, amount: int, temporary: bool = False) -> Effect:
        return cls(
            kind=EffectKind.GAIN_MANA,
            params={"amount": amount, "temporary": temporary},
            target=TargetSpec(TargetKind.SELF),
        )


# ── Param schemas (documentation, not enforced at type level) ──
PARAMS_SCHEMA: dict[EffectKind, dict[str, type]] = {
    # Damage/Healing
    EffectKind.DAMAGE:           {"amount": int},
    EffectKind.AOE_DAMAGE:       {"amount": int},
    EffectKind.RANDOM_DAMAGE:    {"amount": int, "splits": int},
    EffectKind.HEAL:             {"amount": int},
    EffectKind.ARMOR:            {"amount": int},
    EffectKind.LIFESTEAL:        {"amount": int},

    # Summon
    EffectKind.SUMMON:           {"count": int, "card_id": str,
                                   "attack": int, "health": int},
    EffectKind.SUMMON_COPY:      {"source": str},
    EffectKind.SUMMON_FROM_DECK: {"count": int},
    EffectKind.SUMMON_FROM_HAND: {"count": int},
    EffectKind.SUMMON_FROM_GRAVEYARD: {"count": int},
    EffectKind.COLOSSAL_SUMMON:  {"count": int, "appendage_id": str},

    # Card movement
    EffectKind.DRAW:             {"count": int},
    EffectKind.DISCARD:          {"count": int},
    EffectKind.SHUFFLE:          {"count": int},
    EffectKind.SHUFFLE_INTO:     {"cards": list},
    EffectKind.RETURN_TO_HAND:   {},
    EffectKind.RETURN_TO_BOARD:  {},
    EffectKind.TAKE_CONTROL:     {},

    # Stats
    EffectKind.BUFF:             {"attack": int, "health": int},
    EffectKind.DEBUFF:           {"attack": int, "health": int},
    EffectKind.HAND_BUFF:        {"attack": int, "health": int},
    EffectKind.DECK_BUFF:        {"attack": int, "health": int},
    EffectKind.SET_STATS:        {"attack": int, "health": int},
    EffectKind.SWAP_STATS:       {},

    # State
    EffectKind.FREEZE:           {},
    EffectKind.SILENCE:          {},
    EffectKind.DESTROY:          {},
    EffectKind.TRANSFORM:        {"into_card_id": str},
    EffectKind.ENRAGE:           {"attack_bonus": int},

    # Mana
    EffectKind.REDUCE_COST:      {"amount": int},
    EffectKind.INCREASE_COST:    {"amount": int},
    EffectKind.GAIN_MANA:        {"amount": int, "temporary": bool},
    EffectKind.OVERLOAD:         {"amount": int},

    # Resources
    EffectKind.CORPSE_GAIN:      {"amount": int},
    EffectKind.CORPSE_SPEND:     {"amount": int},
    EffectKind.FATIGUE:          {"amount": int},

    # Equipment
    EffectKind.WEAPON_EQUIP:     {"card_id": str, "attack": int,
                                   "durability": int},
    EffectKind.HERO_POWER_SET:   {"card_id": str},

    # Generation
    EffectKind.DISCOVER:         {"pool": str, "count": int, "from_class": str},
    EffectKind.CREATE:           {"card_id": str, "count": int},
    EffectKind.COPY_CARD:        {"source": str, "count": int},
    EffectKind.CAST_SPELL:       {"card_id": str},

    # Enchantment
    EffectKind.ENCHANT:          {"id": str, "attack": int, "health": int,
                                   "text": str},
    EffectKind.REMOVE_ENCHANT:   {"id": str},
}


# ════════════════════════════════════════════════════════════════
# Abilities — a trigger + its effects
# ════════════════════════════════════════════════════════════════

@dataclass
class Ability:
    """A complete card ability: trigger + effects + conditions.

    This is the primary output type of the Parser Layer.
    """
    trigger: Trigger
    effects: list[Effect]
    conditions: list[ConditionSpec] = field(default_factory=list)
    source_card_id: str = ""

    @property
    def is_battlecry(self) -> bool:
        return self.trigger == Trigger.BATTLECRY

    @property
    def is_deathrattle(self) -> bool:
        return self.trigger == Trigger.DEATHRATTLE

    @property
    def has_targeted_effect(self) -> bool:
        return any(
            eff.target.kind == TargetKind.SELECTED and not eff.target.random
            for eff in self.effects
        )

    def all_effects(self) -> list[Effect]:
        """Flatten nested/spawned effects (override in subclasses)."""
        return self.effects


# ════════════════════════════════════════════════════════════════
# Card — parsed card with all abilities
# ════════════════════════════════════════════════════════════════

@dataclass
class ParsedCard:
    """Complete, self-contained description of a card's effects.

    This is the top-level output of the Parser Layer.
    Consumers (rules, simulation, executor) read from this object only.
    """
    card_id: str
    name: str = ""
    cost: int = 0
    original_cost: int = 0
    card_type: str = ""                    # MINION / SPELL / WEAPON / HERO / LOCATION
    card_class: str = ""                   # MAGE / WARRIOR / NEUTRAL / ...
    attack: int = 0
    health: int = 0
    durability: int = 0
    race: str = ""                         # MURLOC / DEMON / BEAST / ...
    spell_school: str = ""
    mechanics: list[str] = field(default_factory=list)
    abilities: list[Ability] = field(default_factory=list)
    text_raw: str = ""                     # the original English text

    def get_ability(self, trigger: Trigger) -> Ability | None:
        for ab in self.abilities:
            if ab.trigger == trigger:
                return ab
        return None

    def has_trigger(self, trigger: Trigger) -> bool:
        return any(ab.trigger == trigger for ab in self.abilities)

    @property
    def battlecry(self) -> Ability | None:
        return self.get_ability(Trigger.BATTLECRY)

    @property
    def deathrattle(self) -> Ability | None:
        return self.get_ability(Trigger.DEATHRATTLE)

    @property
    def is_minion(self) -> bool:
        return self.card_type.upper() == "MINION"

    @property
    def is_spell(self) -> bool:
        return self.card_type.upper() == "SPELL"

    @property
    def is_weapon(self) -> bool:
        return self.card_type.upper() == "WEAPON"

    @property
    def is_hero(self) -> bool:
        return self.card_type.upper() == "HERO"

    @property
    def is_location(self) -> bool:
        return self.card_type.upper() == "LOCATION"

    def has_mechanic(self, mechanic: str) -> bool:
        return mechanic in self.mechanics


# ════════════════════════════════════════════════════════════════
# Resolution — how effects are applied
# ════════════════════════════════════════════════════════════════

@dataclass
class ResolvedEffect:
    """An effect after target resolution.

    The Resolver takes an Effect + GameState and produces one or more
    ResolvedEffects — concrete (action, target_entity_id) pairs ready
    for primitive execution.
    """
    effect: Effect
    target_ids: list[int | str]      # resolved entity IDs
    source_id: int | str = ""
    priority: int = 0

    # Metadata for logging / debugging
    resolution_note: str = ""


# ════════════════════════════════════════════════════════════════
# Actions — player-facing action types
# ════════════════════════════════════════════════════════════════

class ActionKind(Enum):
    """High-level player actions in a turn.

    These are distinct from EffectKind (effects happen *because* of actions).
    An action may trigger multiple effects (e.g., PLAY triggers a Battlecry).
    """
    PLAY = "play"
    PLAY_WITH_TARGET = "play_with_target"
    ATTACK = "attack"
    HERO_POWER = "hero_power"
    ACTIVATE_LOCATION = "activate_location"
    HERO_REPLACE = "hero_replace"
    DISCOVER_PICK = "discover_pick"
    CHOOSE_ONE = "choose_one"
    TRANSFORM = "transform"
    END_TURN = "end_turn"
    PASS = "pass"


@dataclass
class Action:
    """A single action a player can take."""
    # Field names follow the established convention (action_type, card_index,
    # discover_choice_index) for backward compatibility with 30+ consumers.
    action_type: ActionKind
    card_id: str = ""                    # card being played
    card_index: int = -1                 # hand index (aliased from hand_index)
    source_index: int = -1               # board index for attacks
    target_index: int = -1               # target index
    target_id: str = ""                  # target entity id
    position: int = -1                   # board position to play at
    discover_choice_index: int = -1      # discover / choose-one choice
    data: int = 0                        # extra data (e.g., choose-one branch)
    step_order: int = 0
    meta_tags: frozenset[str] = field(default_factory=frozenset)

    def describe(self, state: Any = None) -> str:
        """Return a human-readable description of this action."""
        at = self.action_type
        ci = self.card_index
        ti = self.target_index
        si = self.source_index
        di = self.discover_choice_index
        if at == ActionKind.PLAY:
            card_name = "未知卡牌"
            if state is not None and 0 <= ci < len(state.hand):
                card_name = state.hand[ci].name or f"卡牌#{ci}"
            tgt = f" → 目标#{ti}" if ti > 0 else ""
            return f"手牌[{ci}] 打出 [{card_name}]{tgt}"
        elif at == ActionKind.PLAY_WITH_TARGET:
            card_name = "未知卡牌"
            if state is not None and 0 <= ci < len(state.hand):
                card_name = state.hand[ci].name or f"卡牌#{ci}"
            return f"手牌[{ci}] 定向打出 [{card_name}] → 目标#{ti}"
        elif at == ActionKind.ATTACK:
            src = "英雄武器" if si == -1 else f"随从#{si}"
            return f"{src} 攻击 目标#{ti}"
        elif at == ActionKind.HERO_POWER:
            return "使用英雄技能"
        elif at == ActionKind.END_TURN:
            return "结束回合"
        elif at == ActionKind.ACTIVATE_LOCATION:
            return f"激活地标#{si}"
        elif at == ActionKind.HERO_REPLACE:
            card_name = "未知英雄牌"
            if state is not None and 0 <= ci < len(state.hand):
                card_name = state.hand[ci].name or "英雄牌"
            return f"手牌[{ci}] 替换英雄 [{card_name}]"
        elif at == ActionKind.DISCOVER_PICK:
            return f"发现选择#{di}"
        elif at == ActionKind.TRANSFORM:
            return f"变形 目标#{ti}"
        elif at == ActionKind.CHOOSE_ONE:
            return f"抉择#{self.data} 选择#{di}"
        return f"未知动作({at})"


def action_key(action: Action) -> tuple:
    """Return a hashable key for action comparison.

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

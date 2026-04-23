"""RoleTag classification for card functional categories."""

from __future__ import annotations

from enum import Enum, auto

from analysis.data.card_effects import get_effects


class RoleTag(Enum):
    REMOVAL_SINGLE = auto()
    REMOVAL_AOE = auto()
    HEAL = auto()
    TEMPO_BOARD = auto()
    CARD_DRAW = auto()
    BURST_DAMAGE = auto()
    TAUNT_DEFENSE = auto()
    BUFF = auto()
    UTILITY = auto()


def classify_roles(effects: dict, card=None) -> set[RoleTag]:
    roles: set[RoleTag] = set()

    damage = int(effects.get("damage", 0) or 0)
    aoe_damage = int(effects.get("aoe_damage", 0) or 0)
    random_damage = int(effects.get("random_damage", 0) or 0)
    heal = int(effects.get("heal", 0) or 0)
    armor = int(effects.get("armor", 0) or 0)
    draw = int(effects.get("draw", 0) or 0)
    summon_attack = int(effects.get("summon_attack", 0) or 0)
    summon_health = int(effects.get("summon_health", 0) or 0)
    buff_attack = int(effects.get("buff_attack", 0) or 0)
    buff_health = int(effects.get("buff_health", 0) or 0)

    has_destroy = bool(effects.get("has_destroy", False))
    has_silence = bool(effects.get("has_silence", False))
    has_discover = bool(effects.get("has_discover", False))
    has_summon = bool(effects.get("has_summon", False))

    if aoe_damage > 0:
        roles.add(RoleTag.REMOVAL_AOE)
    if has_destroy or has_silence or damage > 0 or random_damage > 0:
        roles.add(RoleTag.REMOVAL_SINGLE)
    if damage >= 3 or random_damage >= 3:
        roles.add(RoleTag.BURST_DAMAGE)
    if heal > 0 or armor > 0:
        roles.add(RoleTag.HEAL)
    if draw > 0:
        roles.add(RoleTag.CARD_DRAW)
    if buff_attack > 0 or buff_health > 0:
        roles.add(RoleTag.BUFF)
    if has_discover:
        roles.add(RoleTag.UTILITY)

    if has_summon and (summon_attack + summon_health > 0):
        roles.add(RoleTag.TEMPO_BOARD)

    if card is not None:
        card_type = (getattr(card, "card_type", "") or "").upper()
        mechanics = set(getattr(card, "mechanics", []) or [])
        attack = int(getattr(card, "attack", 0) or 0)
        health = int(getattr(card, "health", 0) or 0)

        if card_type == "MINION":
            if attack + health >= 5 or "RUSH" in mechanics or "CHARGE" in mechanics:
                roles.add(RoleTag.TEMPO_BOARD)
            if "TAUNT" in mechanics:
                roles.add(RoleTag.TAUNT_DEFENSE)
            if "DIVINE_SHIELD" in mechanics:
                roles.add(RoleTag.UTILITY)
        elif card_type == "SPELL":
            if not roles:
                roles.add(RoleTag.UTILITY)
        elif card_type == "WEAPON":
            roles.add(RoleTag.BURST_DAMAGE)
        elif card_type == "HERO":
            if heal > 0 or armor > 0:
                roles.add(RoleTag.HEAL)

    if not roles:
        roles.add(RoleTag.UTILITY)
    return roles


def classify_card_roles(card) -> set[RoleTag]:
    effects = get_effects(card)
    eff_dict = {
        "damage": effects.damage,
        "aoe_damage": effects.aoe_damage,
        "random_damage": effects.random_damage,
        "heal": effects.heal,
        "armor": effects.armor,
        "draw": effects.draw,
        "summon_attack": effects.summon_attack,
        "summon_health": effects.summon_health,
        "buff_attack": effects.buff_attack,
        "buff_health": effects.buff_health,
        "has_destroy": effects.has_destroy,
        "has_silence": effects.has_silence,
        "has_discover": effects.has_discover,
        "has_summon": effects.has_summon,
    }
    return classify_roles(eff_dict, card=card)

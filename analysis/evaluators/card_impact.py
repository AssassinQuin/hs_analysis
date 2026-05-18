"""card_impact.py — Card impact evaluation: resource exchange value per card type.

Evaluates how much value each card type generates when played:
  - Minion: resource drain on opponent, damage output, survival expectation
  - Weapon: hit count × attack, durability efficiency, buff synergy
  - Location: activation count × effect value, durability budget

All dimensions are weighted by archetype profile:
  - Aggro: damage_weight high, taunt/heal low, opp_hp_sensitivity high
  - Control: damage_weight low, taunt/heal/draw high, self_hp_sensitivity high
"""
from __future__ import annotations

from analysis.search.game_state import GameState, Minion
from analysis.evaluators.archetype_profile import get_profile


def eval_impact(state: GameState) -> float:
    """Evaluate total card impact value across all card types."""
    impact = 0.0

    for m in state.board:
        impact += _minion_impact(m, state)

    if state.hero.weapon is not None:
        impact += _weapon_impact(state.hero.weapon, state)

    impact += _location_impact(state)

    return impact


def _minion_impact(m: Minion, state: GameState) -> float:
    """Minion resource exchange value, archetype-weighted."""
    if m.health <= 0:
        return 0.0

    profile = get_profile(state.our_playstyle)

    damage = _damage_potential(m, state) * profile["damage_weight"]
    drain = _resource_drain(m, state) * profile["resource_drain_weight"]
    keywords = _keyword_premium(m, state)
    triggers = _trigger_value(m)

    total = damage + drain + keywords + triggers

    if m.has_taunt and len(state.opponent.board) >= 2:
        total *= profile["taunt_value"]

    return total


def _damage_potential(m: Minion, state: GameState) -> float:
    """Expected damage output from this minion."""
    atk = m.attack
    if atk <= 0:
        return 0.0

    profile = get_profile(state.our_playstyle)

    hits = 0.0

    if m.can_attack or m.has_charge:
        hits += 1.0

    if m.has_rush and m.can_attack:
        hits += 0.5

    if m.has_stealth:
        hits += 1.0

    if m.has_divine_shield:
        hits += 0.5

    effective_health = m.health
    if m.has_divine_shield:
        effective_health += atk

    if not m.has_stealth and not m.has_divine_shield:
        max_opp_atk = 0
        for opp in state.opponent.board:
            if opp.attack > max_opp_atk:
                max_opp_atk = opp.attack
        if max_opp_atk > 0:
            if effective_health > max_opp_atk:
                hits += 0.7
            elif effective_health == max_opp_atk:
                hits += 0.3
        else:
            hits += 0.8

    if m.has_windfury:
        hits *= 1.5

    hero_dmg = atk * hits

    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor
    lethal_threshold = 15
    if opp_hp > 0 and opp_hp <= lethal_threshold:
        proximity_bonus = profile["lethal_bonus"] * (lethal_threshold - opp_hp) / lethal_threshold
        hero_dmg *= (1.0 + proximity_bonus)
    if opp_hp > 0 and opp_hp <= hero_dmg:
        hero_dmg *= profile["lethal_bonus"]

    return hero_dmg * 0.5


def _resource_drain(m: Minion, state: GameState) -> float:
    """How many opponent resources needed to remove this minion."""
    if m.health <= 0:
        return 0.0

    effective_health = m.health
    if m.has_divine_shield:
        effective_health += m.attack

    threat_level = m.attack + effective_health

    cards_needed = 1.0
    max_single_damage = 0
    for opp in state.opponent.board:
        if opp.attack > max_single_damage:
            max_single_damage = opp.attack

    if effective_health > max_single_damage:
        cards_needed += (effective_health - max_single_damage) / max(effective_health, 1) * 0.5

    if m.has_stealth:
        cards_needed += 0.5

    mechanics = set(getattr(m, 'mechanics', []) or [])
    if 'DEATHRATTLE' in mechanics:
        cards_needed *= 0.8

    return threat_level * 0.3 * cards_needed


def _keyword_premium(m: Minion, state: GameState) -> float:
    """Flat value bonus for keywords, archetype-weighted."""
    profile = get_profile(state.our_playstyle)
    premium = 0.0

    if m.has_taunt:
        premium += 1.5 * profile["taunt_value"]
    if m.has_divine_shield:
        premium += 2.0
    if m.has_stealth:
        premium += 1.0 * profile["damage_weight"]
    if m.has_poisonous:
        premium += 1.5 * profile["trade_value"]
    if m.has_lifesteal:
        premium += 1.0 * profile["heal_value"]
    if m.has_windfury:
        premium += 1.2 * profile["damage_weight"]
    if m.has_reborn:
        premium += 2.0

    mechanics = set(getattr(m, 'mechanics', []) or [])
    if 'SPELLPOWER' in mechanics or getattr(m, 'spell_power', 0) > 0:
        premium += 0.8 * profile["damage_weight"]

    return premium


def _trigger_value(m: Minion) -> float:
    """Pending trigger value (deathrattle, end-of-turn, etc.)."""
    value = 0.0

    mechanics = getattr(m, 'mechanics', []) or []
    mechanic_set = set(mechanics) if isinstance(mechanics, list) else set()

    if 'DEATHRATTLE' in mechanic_set:
        value += 1.5
    if 'END_OF_TURN' in mechanic_set:
        value += 1.2
    if 'INSPIRE' in mechanic_set:
        value += 1.0
    if 'SPELLBURST' in mechanic_set:
        value += 1.0
    if 'TRIGGER_VISUAL' in mechanic_set:
        value += 0.5

    return value


def _weapon_impact(weapon, state: GameState) -> float:
    """Weapon impact: hit potential × attack value, archetype-weighted."""
    atk = weapon.attack
    durability = weapon.health

    if atk <= 0 or durability <= 0:
        return 0.0

    profile = get_profile(state.our_playstyle)

    max_hits = durability
    hero_dmg = atk * max_hits * 0.5 * profile["damage_weight"]

    trade_value = 0.0
    for opp in state.opponent.board:
        if opp.health <= atk and opp.attack > 0:
            trade_value += (opp.attack + opp.health) * 0.3 * profile["trade_value"]

    total = hero_dmg + trade_value

    opp_hp = state.opponent.hero.hp + state.opponent.hero.armor
    if opp_hp > 0 and opp_hp <= atk * max_hits:
        total *= profile["lethal_bonus"]

    return total


def _location_impact(state: GameState) -> float:
    """Location impact: activation value × remaining durability."""
    total = 0.0

    for m in state.board:
        if getattr(m, 'is_location', False) or (getattr(m, 'card_type', '') or '').upper() == 'LOCATION':
            remaining = getattr(m, 'location_durability', 0)
            if remaining <= 0:
                remaining = max(0, m.health)

            activation_value = m.cost * 0.5 if m.cost > 0 else 1.0

            total += remaining * activation_value

    return total

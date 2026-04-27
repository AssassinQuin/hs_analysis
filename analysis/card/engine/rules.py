"""engine/rules.py — Rules engine for action validation and legal action enumeration.

Provides:
- validate_action(state, action) -> bool: Check if an action is legal
- enumerate_legal(state) -> List[Action]: Generate all legal actions
- check_game_over(state) -> Optional[int]: Check if game is over (returns winner player index or None)
- can_attack(minion_or_hero, state) -> bool: Check if a minion/hero can attack
- get_valid_targets(state, action) -> List[int]: Get valid target indices for an action
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

from analysis.card.abilities.definition import Action, ActionType

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState, HeroState, Minion

log = logging.getLogger(__name__)

# ── Lazy import for spell target resolver ──

_spell_target_resolver = None


def _get_spell_target_resolver():
    global _spell_target_resolver
    if _spell_target_resolver is None:
        try:
            from analysis.search.engine.mechanics.spell_target_resolver import (
                SpellTargetResolver,
            )
            _spell_target_resolver = SpellTargetResolver()
        except (ImportError, AttributeError):
            _spell_target_resolver = False
    return _spell_target_resolver if _spell_target_resolver else None


# ═══════════════════════════════════════════════════════════════
# Action validation
# ═══════════════════════════════════════════════════════════════


def validate_action(state: GameState, action: Action) -> bool:
    """Check if an action is legal in the current game state.

    Args:
        state: Current game state.
        action: Action to validate.

    Returns:
        True if the action is legal, False otherwise.
    """
    at = action.action_type

    if at == ActionType.END_TURN:
        return True

    if at in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        return _validate_play(state, action)

    if at == ActionType.ATTACK:
        return _validate_attack(state, action)

    if at == ActionType.HERO_POWER:
        return _validate_hero_power(state)

    if at == ActionType.ACTIVATE_LOCATION:
        return _validate_location(state, action)

    if at == ActionType.HERO_REPLACE:
        return _validate_hero_replace(state, action)

    if at == ActionType.DISCOVER_PICK:
        return _validate_discover(state, action)

    if at == ActionType.CHOOSE_ONE:
        return _validate_choose_one(state, action)

    if at == ActionType.TRANSFORM:
        return _validate_transform(state, action)

    # Unknown action type — allow by default (fail-open)
    return True


def _validate_play(state: GameState, action: Action) -> bool:
    """Validate a PLAY or PLAY_WITH_TARGET action."""
    idx = action.card_index
    if idx < 0 or idx >= len(state.hand):
        return False

    card = state.hand[idx]
    eff_cost = _effective_cost(state, card, idx)
    if eff_cost > state.mana.available:
        return False

    ctype = (getattr(card, "card_type", "") or "").upper()

    if ctype == "MINION":
        if state.board_full():
            return False
        # For PLAY_WITH_TARGET, verify target is in valid range
        if action.action_type == ActionType.PLAY_WITH_TARGET:
            if action.target_index < 0:
                return False
            if action.position < 0 or action.position > len(state.board):
                return False
        return True

    if ctype == "SPELL":
        # Target validation handled by spell target resolver at enumeration time
        return True

    if ctype == "WEAPON":
        return True

    if ctype == "LOCATION":
        return not state.location_full()

    if ctype == "HERO":
        return True

    return True


def _validate_attack(state: GameState, action: Action) -> bool:
    """Validate an ATTACK action."""
    src_idx = action.source_index
    tgt_idx = action.target_index

    # Hero weapon attack (source_index == -1)
    if src_idx == -1:
        weapon = state.hero.weapon
        if weapon is None or weapon.attack <= 0:
            return False
        if state.hero.hero_power_used and _hero_attacked(state):
            return False
    else:
        # Minion attack
        if src_idx < 0 or src_idx >= len(state.board):
            return False
        minion = state.board[src_idx]
        if not can_attack(minion, state):
            return False

    # Target validation: taunt enforcement
    return _validate_attack_target(state, tgt_idx)


def _validate_hero_power(state: GameState) -> bool:
    """Validate a HERO_POWER action."""
    if state.hero.hero_power_used:
        return False
    return state.mana.available >= state.hero.hero_power_cost


def _validate_location(state: GameState, action: Action) -> bool:
    """Validate an ACTIVATE_LOCATION action."""
    loc_idx = action.source_index
    if loc_idx < 0 or loc_idx >= len(state.locations):
        return False

    loc = state.locations[loc_idx]
    durability = getattr(loc, "durability", 0)
    cooldown = getattr(loc, "cooldown_current", 1)

    if durability <= 0 or cooldown != 0:
        return False

    # Check mana cost (locations typically cost mana)
    loc_cost = getattr(loc, "cost", 0)
    if loc_cost > 0 and loc_cost > state.mana.available:
        return False

    return True


def _validate_hero_replace(state: GameState, action: Action) -> bool:
    """Validate a HERO_REPLACE action."""
    idx = action.card_index
    if idx < 0 or idx >= len(state.hand):
        return False

    card = state.hand[idx]
    ctype = (getattr(card, "card_type", "") or "").upper()
    if ctype != "HERO":
        return False

    eff_cost = _effective_cost(state, card, idx)
    return eff_cost <= state.mana.available


def _validate_discover(state: GameState, action: Action) -> bool:
    """Validate a DISCOVER_PICK action."""
    choice_idx = action.discover_choice_index
    # Discover options are tracked on the state; just check index is non-negative
    return choice_idx >= 0


def _validate_choose_one(state: GameState, action: Action) -> bool:
    """Validate a CHOOSE_ONE action."""
    choice_idx = action.discover_choice_index
    return choice_idx >= 0


def _validate_transform(state: GameState, action: Action) -> bool:
    """Validate a TRANSFORM action."""
    tgt_idx = action.target_index
    if tgt_idx < 0 or tgt_idx >= len(state.board):
        return False
    return True


# ═══════════════════════════════════════════════════════════════
# Can-attack check
# ═══════════════════════════════════════════════════════════════


def can_attack(minion_or_hero: Minion | HeroState, state: GameState) -> bool:
    """Check if a minion can attack this turn.

    A minion can attack if:
    - Not frozen
    - Not dormant
    - Has attack > 0
    - can_attack flag is set (or has_windfury and only attacked once)
    - Not cant_attack

    Args:
        minion_or_hero: The minion to check.
        state: Current game state.

    Returns:
        True if the minion can attack.
    """
    if not isinstance(minion_or_hero, (type(state.board[0]) if state.board else object)):
        # If state.board is empty, just check by attribute presence
        pass

    m = minion_or_hero

    # Dormant minions can't attack
    if getattr(m, "is_dormant", False):
        return False

    # Frozen minions can't attack
    if getattr(m, "frozen_until_next_turn", False):
        return False

    # Minions that explicitly can't attack
    if getattr(m, "cant_attack", False):
        return False

    # Must have attack power
    if getattr(m, "attack", 0) <= 0:
        return False

    # Check can_attack flag
    if not getattr(m, "can_attack", False):
        return False

    # Windfury: can attack twice
    if getattr(m, "has_windfury", False):
        # Can attack if haven't attacked at all, or attacked once and still has turns
        return True

    # Mega windfury: can attack four times
    if getattr(m, "has_mega_windfury", False):
        return True

    # Normal minion: can attack if hasn't attacked yet
    return not getattr(m, "has_attacked_once", False)


def _hero_attacked(state: GameState) -> bool:
    """Check if the hero has already attacked this turn.

    Uses a simple heuristic: if the hero has a weapon with reduced durability,
    assume an attack has occurred.
    """
    weapon = state.hero.weapon
    if weapon is None:
        return False
    # No reliable flag for hero attacks in GameState;
    # the simulation layer tracks this externally
    return False


# ═══════════════════════════════════════════════════════════════
# Attack target validation (taunt / stealth / immune)
# ═══════════════════════════════════════════════════════════════


def _validate_attack_target(state: GameState, target_index: int) -> bool:
    """Validate an attack target respecting taunt, stealth, and immune rules.

    Args:
        state: Current game state.
        target_index: 0 = enemy hero, 1+ = enemy minion index (1-based).

    Returns:
        True if the target is valid.
    """
    enemy_board = state.opponent.board
    enemy_taunts = [m for m in enemy_board if getattr(m, "has_taunt", False)]

    # Face attack (target_index == 0)
    if target_index == 0:
        # Cannot go face if enemy has taunt minions
        if enemy_taunts:
            return False
        return True

    # Minion attack (target_index is 1-based)
    minion_idx = target_index - 1
    if minion_idx < 0 or minion_idx >= len(enemy_board):
        return False

    target_minion = enemy_board[minion_idx]

    # Cannot target stealthed minions
    if getattr(target_minion, "has_stealth", False):
        return False

    # Cannot target immune minions
    if getattr(target_minion, "has_immune", False):
        return False

    # If enemy has taunt minions, must attack a taunt minion
    if enemy_taunts and not getattr(target_minion, "has_taunt", False):
        return False

    return True


# ═══════════════════════════════════════════════════════════════
# Valid targets
# ═══════════════════════════════════════════════════════════════


def get_valid_targets(state: GameState, action: Action) -> List[int]:
    """Get valid target indices for an action.

    For attack actions:
        Returns target indices (0 = face, 1+ = minion) respecting taunt/stealth/immune.

    For spell/minion play:
        Returns target indices from the spell target resolver.

    Args:
        state: Current game state.
        action: The action to get targets for.

    Returns:
        List of valid target indices.
    """
    at = action.action_type

    if at == ActionType.ATTACK:
        return _get_attack_targets(state, action.source_index)

    if at in (ActionType.PLAY_WITH_TARGET,):
        idx = action.card_index
        if 0 <= idx < len(state.hand):
            card = state.hand[idx]
            resolver = _get_spell_target_resolver()
            if resolver is not None:
                try:
                    return resolver.resolve_targets(state, card)
                except (TypeError, AttributeError):
                    pass
        return []

    return []


def _get_attack_targets(state: GameState, source_index: int) -> List[int]:
    """Get valid attack targets for a source (minion or hero).

    Args:
        state: Current game state.
        source_index: -1 for hero, 0+ for board minion index.

    Returns:
        List of valid target indices (0 = face, 1+ = enemy minion, 1-based).
    """
    enemy_board = state.opponent.board
    enemy_taunts = [m for m in enemy_board if getattr(m, "has_taunt", False)]

    targets: List[int] = []

    # Determine if attacker has rush (can't go face)
    has_rush = False
    if source_index >= 0 and source_index < len(state.board):
        has_rush = getattr(state.board[source_index], "has_rush", False)

    if enemy_taunts:
        # Must attack taunt minions only
        for i, m in enumerate(enemy_taunts):
            if not getattr(m, "has_stealth", False):
                real_idx = _find_enemy_minion_index(state, m)
                targets.append(real_idx + 1)
    else:
        # Face attack (unless rush)
        if not has_rush:
            targets.append(0)

        # Enemy minions (skip stealthed)
        for i, m in enumerate(enemy_board):
            if getattr(m, "has_stealth", False):
                continue
            if getattr(m, "has_immune", False):
                continue
            targets.append(i + 1)

    return targets


# ═══════════════════════════════════════════════════════════════
# Legal action enumeration
# ═══════════════════════════════════════════════════════════════


def enumerate_legal(state: GameState) -> List[Action]:
    """Generate all legal actions for the current player turn.

    Actions are generated in priority order:
    1. Attack actions (prioritized for lethal checks)
    2. Play actions (minions, spells, weapons, locations)
    3. Hero power
    4. Location activations
    5. End turn (always available)

    Args:
        state: Current game state.

    Returns:
        List of all legal actions.
    """
    actions: List[Action] = []

    _enumerate_play_actions(state, actions)
    _enumerate_attack_actions(state, actions)
    _enumerate_hero_power(state, actions)
    _enumerate_location_actions(state, actions)
    actions.append(Action(action_type=ActionType.END_TURN))

    _stamp_card_names(actions, state)
    return actions


def _enumerate_play_actions(state: GameState, actions: List[Action]) -> None:
    """Generate all legal PLAY / PLAY_WITH_TARGET actions from hand."""
    for idx, card in enumerate(state.hand):
        tags = _probe_tags_for_card(state, card)
        eff_cost = _effective_cost(state, card, idx)

        if eff_cost > state.mana.available:
            continue

        ctype = (getattr(card, "card_type", "") or "").upper()

        if ctype == "MINION":
            _enum_play_minion(state, idx, card, tags, actions)
        elif ctype == "HERO":
            actions.append(
                Action(
                    action_type=ActionType.HERO_REPLACE,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif ctype == "SPELL":
            _enum_play_spell(state, idx, card, tags, actions)
        elif ctype == "WEAPON":
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
        elif ctype == "LOCATION":
            if not state.location_full():
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )


def _enum_play_minion(
    state: GameState,
    idx: int,
    card,
    tags: set[str],
    actions: List[Action],
) -> None:
    """Enumerate minion play actions (with optional target for battlecry)."""
    if state.board_full():
        return

    resolver = _get_spell_target_resolver()
    targets: list = []
    if resolver is not None:
        try:
            targets = resolver.resolve_targets(state, card)
        except (ImportError, AttributeError, TypeError):
            targets = []

    if targets:
        for tgt in targets:
            for pos in range(len(state.board) + 1):
                actions.append(
                    Action(
                        action_type=ActionType.PLAY_WITH_TARGET,
                        card_index=idx,
                        target_index=tgt,
                        position=pos,
                        meta_tags=frozenset(tags),
                    )
                )
    else:
        for pos in range(len(state.board) + 1):
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    position=pos,
                    meta_tags=frozenset(tags),
                )
            )


def _enum_play_spell(
    state: GameState,
    idx: int,
    card,
    tags: set[str],
    actions: List[Action],
) -> None:
    """Enumerate spell play actions with target resolution."""
    resolver = _get_spell_target_resolver()
    if resolver is not None:
        try:
            targets = resolver.resolve_targets(state, card)
            if targets:
                for tgt in targets:
                    actions.append(
                        Action(
                            action_type=ActionType.PLAY_WITH_TARGET,
                            card_index=idx,
                            target_index=tgt,
                            meta_tags=frozenset(tags),
                        )
                    )
                return

            # targets=[] — three cases:
            # 1. AOE (auto-targets all): can play without selecting target
            # 2. No-target spell (draw, armor, buff-self): can play
            # 3. Targeted spell with no valid targets: CANNOT play
            text = getattr(card, "text", "") or ""

            # Case 1: AOE — detect "所有/全部/all" + damage patterns
            is_aoe = (
                "所有" in text
                or "全部" in text
                or "all enemie" in text.lower()
                or "all minion" in text.lower()
            )
            if is_aoe:
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )
                return

            # Case 2 vs 3: use card_effects to check if card has damage
            try:
                from analysis.card.data.card_effects import get_effects

                eff = get_effects(card)
                has_damage = (
                    eff.damage > 0 or eff.random_damage > 0 or eff.aoe_damage > 0
                )

                from analysis.search.engine.mechanics.spell_target_resolver import (
                    SpellTargetResolver,
                )

                has_target_keyword = SpellTargetResolver.has_targeting_keyword(text)
                if not (has_damage and has_target_keyword):
                    actions.append(
                        Action(
                            action_type=ActionType.PLAY,
                            card_index=idx,
                            meta_tags=frozenset(tags),
                        )
                    )
            except (ImportError, AttributeError, TypeError):
                actions.append(
                    Action(
                        action_type=ActionType.PLAY,
                        card_index=idx,
                        meta_tags=frozenset(tags),
                    )
                )
        except (ImportError, AttributeError, TypeError):
            actions.append(
                Action(
                    action_type=ActionType.PLAY,
                    card_index=idx,
                    meta_tags=frozenset(tags),
                )
            )
    else:
        # No resolver available — allow play (fail-open)
        actions.append(
            Action(
                action_type=ActionType.PLAY,
                card_index=idx,
                meta_tags=frozenset(tags),
            )
        )


def _enumerate_attack_actions(state: GameState, actions: List[Action]) -> None:
    """Generate all legal ATTACK actions (minion + hero weapon)."""
    enemy_taunts = [m for m in state.opponent.board if getattr(m, "has_taunt", False)]

    # Minion attacks
    for src_idx, minion in enumerate(state.board):
        if not can_attack(minion, state):
            continue

        if enemy_taunts:
            for t in enemy_taunts:
                real_idx = _find_enemy_minion_index(state, t)
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=real_idx + 1,
                    )
                )
        else:
            if not minion.has_rush:
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=0,
                    )
                )
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if getattr(enemy_minion, "has_stealth", False):
                    continue
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=src_idx,
                        target_index=tgt_idx + 1,
                    )
                )

    # Hero weapon attacks
    if state.hero.weapon is not None and state.hero.weapon.attack > 0:
        if enemy_taunts:
            for t in enemy_taunts:
                real_idx = _find_enemy_minion_index(state, t)
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,
                        target_index=real_idx + 1,
                    )
                )
        else:
            actions.append(
                Action(action_type=ActionType.ATTACK, source_index=-1, target_index=0)
            )
            for tgt_idx, enemy_minion in enumerate(state.opponent.board):
                if getattr(enemy_minion, "has_stealth", False):
                    continue
                actions.append(
                    Action(
                        action_type=ActionType.ATTACK,
                        source_index=-1,
                        target_index=tgt_idx + 1,
                    )
                )


def _enumerate_hero_power(state: GameState, actions: List[Action]) -> None:
    """Generate HERO_POWER action if available and affordable."""
    hp_cost = state.hero.hero_power_cost
    if not state.hero.hero_power_used and state.mana.available >= hp_cost:
        actions.append(Action(action_type=ActionType.HERO_POWER))


def _enumerate_location_actions(state: GameState, actions: List[Action]) -> None:
    """Generate ACTIVATE_LOCATION actions for ready locations."""
    for loc_idx, loc in enumerate(state.locations):
        durability = getattr(loc, "durability", 0)
        cooldown = getattr(loc, "cooldown_current", 1)

        if durability <= 0 or cooldown != 0:
            continue

        loc_cost = getattr(loc, "cost", 0)
        if loc_cost > 0 and loc_cost > state.mana.available:
            continue

        loc_text = getattr(loc, "text", "") or ""
        loc_targets: list = []
        if loc_text:
            resolver = _get_spell_target_resolver()
            if resolver is not None:
                try:

                    class _LocCard:
                        def __init__(self, text: str):
                            self.text = text
                            self.card_type = "LOCATION"

                    loc_targets = resolver.resolve_targets(state, _LocCard(loc_text))
                except (ImportError, AttributeError, TypeError):
                    loc_targets = []

        if loc_targets:
            for tgt in loc_targets:
                actions.append(
                    Action(
                        action_type=ActionType.ACTIVATE_LOCATION,
                        source_index=loc_idx,
                        target_index=tgt,
                    )
                )
        else:
            actions.append(
                Action(
                    action_type=ActionType.ACTIVATE_LOCATION,
                    source_index=loc_idx,
                )
            )


# ═══════════════════════════════════════════════════════════════
# Game-over check
# ═══════════════════════════════════════════════════════════════


def check_game_over(state: GameState) -> Optional[int]:
    """Check if the game is over.

    Args:
        state: Current game state.

    Returns:
        0 if the current player wins (opponent hero dead),
        1 if the opponent wins (player hero dead),
        None if the game continues.
    """
    opp_hero = state.opponent.hero
    if (opp_hero.hp + opp_hero.armor) <= 0:
        return 0

    player_hero = state.hero
    if (player_hero.hp + player_hero.armor) <= 0:
        return 1

    return None


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


def _effective_cost(state: GameState, card, card_index: int) -> int:
    """Calculate the effective mana cost of a card including all modifiers."""
    eff_cost = state.mana.effective_cost(card)
    return eff_cost


def _stamp_card_names(actions: List[Action], state: GameState) -> None:
    """Stamp each PLAY action with card name for action_key uniqueness."""
    for a in actions:
        if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
            if 0 <= a.card_index < len(state.hand):
                a._card_name = state.hand[a.card_index].name or ""


def _find_enemy_minion_index(state: GameState, minion: Minion) -> int:
    """Find the board index of an enemy minion by identity."""
    for i, m in enumerate(state.opponent.board):
        if m is minion:
            return i
    return 0


def _probe_tags_for_card(state: GameState, card) -> set[str]:
    """Probe card for heuristic meta-tags (secret probing, resource holding)."""
    tags: set[str] = set()
    enemy_has_secret = bool(getattr(state.opponent, "secrets", None))
    card_type = (getattr(card, "card_type", "") or "").upper()
    cost = int(getattr(card, "cost", 0) or 0)
    attack = int(getattr(card, "attack", 0) or 0)
    health = int(getattr(card, "health", 0) or 0)

    if enemy_has_secret:
        if card_type == "SPELL" and cost <= 2:
            tags.add("PROBE_SECRET")
        if card_type == "MINION" and (attack + health) <= 4:
            tags.add("PROBE_SECRET")

    if cost >= 6:
        tags.add("RESOURCE_HOLD")
    return tags


# Backward-compatible alias
enumerate_legal_actions = enumerate_legal

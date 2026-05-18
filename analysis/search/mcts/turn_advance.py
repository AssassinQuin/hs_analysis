#!/usr/bin/env python3
"""turn_advance.py — Cross-turn state advancement for MCTS.

Simulates the full cycle: our END_TURN → opponent turn → our next turn start.

Key improvements (v2):
- Opponent turn uses swap_perspective + real action enumeration + apply_action
  instead of just minion attacks
- Effect chain tracking: card A generates card B → card B is played
- Full death resolution after each action (deathrattle, reborn, corpse)
- Detailed simulation logging via SimLogger
- Both opponent and our greedy play support effect chain playing
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.card.engine.state import GameState

log = logging.getLogger(__name__)

# Graceful fallback for deleted module
try:
    from analysis.card.data.card_effects import get_effects
except ImportError:
    get_effects = None


# ──────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────

_MAX_OPP_PLAYS = 10        # Max cards opponent can play in a turn
_MAX_CHAIN_DEPTH = 3       # Max depth of effect chains (A→B→C)
_MAX_OPP_ATTACKS = 7       # Max attacks per turn
_MAX_SELF_PLAYS = 10       # Max cards we play in greedy
_MAX_SELF_ATTACKS = 7      # Max attacks in greedy self-play


# ──────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────


def _draw_from_deck(state: GameState) -> object | None:
    """Draw a random card from deck_list, or return None if empty."""
    deck = getattr(state, 'deck_list', None)
    if deck and len(deck) > 0:
        import random
        idx = random.randint(0, len(deck) - 1)
        card = deck.pop(idx)
        return card
    return None


def advance_full_turn(state: GameState, *, greedy_opponent: bool = True) -> GameState:
    """Advance state from our END_TURN to the start of our next turn.

    Cycle:
    1. Our end-of-turn cleanup — already done by _apply_end_turn.
    2. Opponent's turn: mana refresh, draw, play cards with effect chains,
       attack, hero power, death resolution.
    3. Opponent's end-of-turn cleanup.
    4. Our next turn: mana refresh, draw, minions can attack, greedy play
       with effect chain support.

    Args:
        state: GameState after our END_TURN has been applied (cleanup done).
        greedy_opponent: If True, simulate opponent playing cards and attacking.

    Returns:
        New GameState at the end of our next turn (after greedy play).
    """
    from analysis.search.sim_logger import get_sim_logger
    sim_log = get_sim_logger()

    s = state.copy()

    with sim_log.phase("opponent_turn", turn=s.turn_number + 1):
        sim_log.log_state_snapshot(s, label="before_opp_turn")

        # === Step 2: Opponent's turn start ===
        s.turn_number += 1

        # Opponent mana refresh
        opp_estimated_max = min(10, max(1, s.turn_number // 2 + 1))

        # Opponent draws a card
        if s.opponent.deck_remaining > 0:
            s.opponent.deck_remaining -= 1
            s.opponent.hand_count += 1
            # If opponent has a sampled hand, add a placeholder
            if s.opponent.hand is not None:
                from analysis.card.models.card import Card
                s.opponent.hand.append(Card(
                    dbf_id=0, name="Opp Draw", cost=0, card_type="SPELL"
                ))

        # Opponent minions can attack
        for m in s.opponent.board:
            if not m.has_rush:
                m.can_attack = True
            m.has_attacked_once = False
            m.frozen_until_next_turn = False
            m.has_immune = False

        # Full opponent turn simulation
        if greedy_opponent:
            s = _simulate_opponent_turn(s)

        sim_log.log_state_snapshot(s, label="after_opp_turn")

    # === Step 3: Opponent's end-of-turn cleanup ===
    for m in s.board:
        m.frozen_until_next_turn = False
        m.has_immune = False
    s.hero.is_immune = False

    with sim_log.phase("our_next_turn", turn=s.turn_number + 1):
        # === Step 4: Our next turn start ===
        s.turn_number += 1

        next_max = min(s.mana.max_mana_cap, s.mana.max_mana + 1)
        s.mana.max_mana = next_max
        s.mana.overloaded = s.mana.overload_next
        s.mana.overload_next = 0
        s.mana.available = max(0, next_max - s.mana.overloaded)
        s.mana.modifiers = []

        # Draw a card
        if s.deck_remaining > 0:
            drawn = _draw_from_deck(s)
            if drawn is not None:
                s.hand.append(drawn)
            s.deck_remaining -= 1
        else:
            s.fatigue_damage += 1
            s.hero.hp -= s.fatigue_damage

        # Our minions can attack
        for m in s.board:
            m.can_attack = True
            m.has_attacked_once = False
            m.frozen_until_next_turn = False
            m.has_immune = False

        s.cards_played_this_turn = []

        _apply_turn_start_triggers(s)

        sim_log.log_state_snapshot(s, label="our_turn_start")

        # === Step 4b: Our greedy play — with effect chain support ===
        s = _greedy_self_play_with_chains(s)

        # Greedy attacks with our minions
        s = _greedy_self_attacks(s)

        sim_log.log_state_snapshot(s, label="our_turn_end")

    return s


# ──────────────────────────────────────────────────────────────────
# Opponent turn simulation — FULL implementation with swap_perspective
# ──────────────────────────────────────────────────────────────────


def _simulate_opponent_turn(state: GameState) -> GameState:
    """Simulate a complete opponent turn using perspective swap.

    Strategy:
    1. Swap to opponent perspective (reuse all action/apply infrastructure)
    2. Greedy card play with effect chain tracking
    3. Attack with minions
    4. Use hero power if beneficial
    5. Swap back to our perspective

    This replaces the old _greedy_opponent_play which only did minion attacks.
    """
    from analysis.search.sim_logger import get_sim_logger
    sim_log = get_sim_logger()

    try:
        return _simulate_opponent_turn_impl(state)
    except Exception as exc:
        log.warning("Opponent turn simulation failed, falling back to basic: %s", exc)
        sim_log.log_warning(f"Opponent turn simulation failed: {exc}")
        # Fallback to basic attack-only simulation
        return _basic_opponent_attacks(state)


def _simulate_opponent_turn_impl(state: GameState) -> GameState:
    """Implementation of full opponent turn simulation."""
    from analysis.search.perspective_swap import swap_perspective, swap_back
    from analysis.search.abilities.enumeration import enumerate_legal_actions
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.actions import ActionType
    from analysis.search.sim_logger import get_sim_logger
    from analysis.card.engine.state import GameState

    sim_log = get_sim_logger()

    # --- Step 1: Swap to opponent perspective ---
    opp_state, saved = swap_perspective(state)

    # Save hand size to detect generated cards
    hand_size_before = len(opp_state.hand)

    # --- Step 2: Opponent greedy card play with effect chains ---
    opp_state = _greedy_play_with_chains(
        opp_state,
        max_plays=_MAX_OPP_PLAYS,
        max_chain_depth=_MAX_CHAIN_DEPTH,
        perspective="opponent",
    )

    # --- Step 3: Opponent attacks with minions ---
    opp_state = _greedy_attacks(opp_state, max_attacks=_MAX_OPP_ATTACKS, perspective="opponent")

    # --- Step 4: Opponent hero power (if beneficial) ---
    opp_state = _try_hero_power(opp_state, perspective="opponent")

    # --- Step 5: End turn cleanup (in opponent perspective) ---
    from analysis.search.abilities.actions import Action
    opp_state = apply_action(opp_state, Action(action_type=ActionType.END_TURN))

    # --- Step 6: Swap back to our perspective ---
    result = swap_back(opp_state, saved)

    return result


def _basic_opponent_attacks(state: GameState) -> GameState:
    """Fallback: basic opponent attack simulation (original logic).

    Used when perspective swap fails. Only simulates minion attacks.
    """
    s = state
    opp_board = s.opponent.board
    our_board = s.board

    for opp_minion in opp_board:
        if not opp_minion.can_attack or opp_minion.has_attacked_once:
            continue

        traded = False

        # Try favorable trade: kill our minion, theirs survives
        for our_minion in our_board:
            if our_minion.health <= 0:
                continue
            if our_minion.health <= opp_minion.attack and opp_minion.health > our_minion.attack:
                our_minion.health -= opp_minion.attack
                opp_minion.health -= our_minion.attack
                opp_minion.has_attacked_once = True
                traded = True
                break

        if traded:
            continue

        # Check for taunts
        taunts = [m for m in our_board if m.health > 0 and m.has_taunt]

        if taunts:
            target = taunts[0]
            target.health -= opp_minion.attack
            opp_minion.health -= target.attack
            opp_minion.has_attacked_once = True
        elif len(our_board) == 0 or all(m.health <= 0 for m in our_board):
            s.hero.hp -= opp_minion.attack
            opp_minion.has_attacked_once = True
        else:
            s.hero.hp -= opp_minion.attack
            opp_minion.has_attacked_once = True

    # Remove dead minions
    s.board = [m for m in s.board if m.health > 0]
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s


# ──────────────────────────────────────────────────────────────────
# Greedy play with effect chain support
# ──────────────────────────────────────────────────────────────────


def _greedy_play_with_chains(
    state: GameState,
    max_plays: int = 10,
    max_chain_depth: int = 3,
    perspective: str = "self",
) -> GameState:
    """Play cards greedily with effect chain tracking.

    After each card play, checks if new cards appeared in hand.
    If so, continues playing generated cards (up to max_chain_depth levels).

    This handles cases like:
    - Play card A → generates card B → play card B
    - Play spell → draws card C → play card C
    - Play minion → battlecry adds card D → play card D

    Args:
        state: Current game state (already in correct perspective).
        max_plays: Maximum total card plays allowed.
        max_chain_depth: Maximum depth of effect chains.
        perspective: "self" or "opponent" for logging.

    Returns:
        Modified game state after greedy play.
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.enumeration import enumerate_legal_actions
    from analysis.search.sim_logger import get_sim_logger
    from analysis.search.deathrattle import resolve_deaths

    sim_log = get_sim_logger()
    s = state
    total_plays = 0

    for play_round in range(max_plays):
        if s.mana.available <= 0:
            break

        actions = enumerate_legal_actions(s)
        playable = [
            a for a in actions
            if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET)
        ]
        if not playable:
            break

        # Pick best card to play (by mana efficiency)
        best = _pick_best_play(playable, s)
        if best is None:
            break

        # Log the action
        card_name = _get_card_name(s, best)
        card_cost = _get_card_cost(s, best)
        sim_log.log_action(
            f"PLAY({perspective})",
            card=card_name,
            cost=card_cost,
            target=_describe_target(s, best),
        )

        # Track hand size before play
        hand_before = len(s.hand)
        hand_cards_before = set(id(c) for c in s.hand)

        # Apply the action
        s = apply_action(s, best)
        total_plays += 1

        # Resolve deaths after each action
        try:
            s = resolve_deaths(s)
            s.board = [m for m in s.board if m.health > 0]
            s.opponent.board = [m for m in s.opponent.board if m.health > 0]
        except Exception:
            log.debug("Death resolution after play failed", exc_info=True)

        # Check if new cards appeared in hand (effect chain)
        hand_after = len(s.hand)
        new_card_count = hand_after - (hand_before - 1)  # -1 for the played card

        if new_card_count > 0 and total_plays < max_plays:
            # New cards were generated — play them as a chain
            s = _play_chain(
                s, source_card=card_name, depth=1,
                max_depth=max_chain_depth,
                total_plays=total_plays, max_plays=max_plays,
                perspective=perspective,
            )
            total_plays = _count_plays_in_log(sim_log, perspective) if sim_log.enabled else total_plays

    return s


def _play_chain(
    state: GameState,
    source_card: str,
    depth: int,
    max_depth: int,
    total_plays: int,
    max_plays: int,
    perspective: str = "self",
) -> GameState:
    """Play generated cards from an effect chain.

    When a card play generates new cards (e.g., "add a random spell to hand"),
    this function attempts to play those generated cards, recursively handling
    further chains up to max_depth.

    Args:
        state: Current game state.
        source_card: Name of the card that generated the chain.
        depth: Current chain depth (1 = first generated card).
        max_depth: Maximum chain depth allowed.
        total_plays: Total plays so far.
        max_plays: Maximum total plays allowed.
        perspective: "self" or "opponent" for logging.

    Returns:
        Modified game state after chain play.
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.enumeration import enumerate_legal_actions
    from analysis.search.sim_logger import get_sim_logger
    from analysis.search.deathrattle import resolve_deaths

    sim_log = get_sim_logger()

    if depth > max_depth or total_plays >= max_plays:
        sim_log.log_chain_end(source_card, depth, reason="depth_limit")
        return state

    sim_log.log_chain_start(source_card, depth=depth)

    s = state
    chain_plays = 0
    max_chain_plays = 3  # Max cards to play per chain level

    for _ in range(max_chain_plays):
        if total_plays + chain_plays >= max_plays:
            break
        if s.mana.available <= 0:
            break

        actions = enumerate_legal_actions(s)
        playable = [
            a for a in actions
            if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET)
        ]
        if not playable:
            break

        # Pick best generated card to play
        best = _pick_best_play(playable, s)
        if best is None:
            break

        card_name = _get_card_name(s, best)
        card_cost = _get_card_cost(s, best)

        sim_log.log_chain_play(depth, card_name, cost=card_cost)

        # Track hand before play for further chain detection
        hand_before = len(s.hand)

        # Apply the action
        s = apply_action(s, best)
        chain_plays += 1

        # Resolve deaths
        try:
            s = resolve_deaths(s)
            s.board = [m for m in s.board if m.health > 0]
            s.opponent.board = [m for m in s.opponent.board if m.health > 0]
        except Exception:
            log.debug("Death resolution in chain failed", exc_info=True)

        # Check for further chain generation
        hand_after = len(s.hand)
        new_cards = hand_after - (hand_before - 1)

        if new_cards > 0 and depth < max_depth:
            s = _play_chain(
                s, source_card=card_name, depth=depth + 1,
                max_depth=max_depth,
                total_plays=total_plays + chain_plays,
                max_plays=max_plays,
                perspective=perspective,
            )

    sim_log.log_chain_end(source_card, depth, plays=chain_plays)
    return s


# ──────────────────────────────────────────────────────────────────
# Greedy attacks
# ──────────────────────────────────────────────────────────────────


def _greedy_attacks(state: GameState, max_attacks: int = 7, perspective: str = "self") -> GameState:
    """Attack greedily with minions using apply_action for proper resolution.

    Priority:
    1. Lethal check — if we can kill the opponent hero, go face
    2. Favorable trades — kill enemy minion, ours survives
    3. Face damage if no taunts
    4. Attack taunts if forced
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.enumeration import enumerate_legal_actions
    from analysis.search.sim_logger import get_sim_logger

    sim_log = get_sim_logger()
    s = state

    for _ in range(max_attacks):
        actions = enumerate_legal_actions(s)
        attacks = [a for a in actions if a.action_type == ActionType.ATTACK]
        if not attacks:
            break

        # Check for lethal: if any face attack can kill
        opp_total_hp = s.opponent.hero.hp + s.opponent.hero.armor
        face_attacks = [a for a in attacks if a.target_index == 0]
        for fa in face_attacks:
            src_idx = fa.source_index
            if src_idx == -1:
                atk_val = s.hero.weapon.attack if s.hero.weapon else 0
            elif 0 <= src_idx < len(s.board):
                atk_val = s.board[src_idx].attack
            else:
                atk_val = 0
            if atk_val >= opp_total_hp:
                sim_log.log_action(f"ATTACK({perspective}) lethal", target="enemy_hero")
                s = apply_action(s, fa)
                return s

        # Prefer face attacks when opponent has no taunts and few minions
        enemy_taunts = [m for m in s.opponent.board if m.has_taunt]

        if not enemy_taunts:
            # Aggressive: prefer face damage unless there's a very favorable trade
            best_attack = _pick_best_attack(attacks, s)
            if best_attack is not None:
                tgt_desc = _describe_attack_target(s, best_attack)
                sim_log.log_action(f"ATTACK({perspective})", target=tgt_desc)
                s = apply_action(s, best_attack)
            else:
                break
        else:
            # Must attack taunts
            taunt_attacks = [a for a in attacks if a.target_index > 0]
            if taunt_attacks:
                best_attack = _pick_best_attack(taunt_attacks, s)
                if best_attack is not None:
                    tgt_desc = _describe_attack_target(s, best_attack)
                    sim_log.log_action(f"ATTACK({perspective})", target=tgt_desc)
                    s = apply_action(s, best_attack)
                else:
                    break
            else:
                break

    return s


def _greedy_self_attacks(state: GameState) -> GameState:
    """Attack greedily with our minions in cross-turn rollout."""
    return _greedy_attacks(state, max_attacks=_MAX_SELF_ATTACKS, perspective="self")


# ──────────────────────────────────────────────────────────────────
# Hero power
# ──────────────────────────────────────────────────────────────────


def _try_hero_power(state: GameState, perspective: str = "self") -> GameState:
    """Try using hero power if it seems beneficial."""
    from analysis.search.abilities.actions import Action, ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.sim_logger import get_sim_logger

    sim_log = get_sim_logger()
    s = state

    if s.hero.hero_power_used:
        return s

    hp_cost = s.hero.hero_power_cost
    if s.mana.available < hp_cost:
        return s

    # Check if hero power does damage (usually worth it)
    hero_class = (s.hero.hero_class or "").upper()
    damage_classes = {"MAGE", "HUNTER", "DRUID"}
    if hero_class in damage_classes and s.mana.available > hp_cost + 2:
        # Use hero power — it's generally beneficial for damage classes
        sim_log.log_action(f"HERO_POWER({perspective})", cost=hp_cost)
        s = apply_action(s, Action(action_type=ActionType.HERO_POWER))

    return s


# ──────────────────────────────────────────────────────────────────
# Self greedy play — upgraded with chain support
# ──────────────────────────────────────────────────────────────────


def _greedy_self_play(state: GameState) -> GameState:
    """Play cards greedily to maximise mana usage (with chain support).

    Strategy: play the most expensive affordable card first, then check
    for generated cards and play those too. Repeat until out of mana.
    """
    return _greedy_play_with_chains(
        state,
        max_plays=_MAX_SELF_PLAYS,
        max_chain_depth=_MAX_CHAIN_DEPTH,
        perspective="self",
    )


def _greedy_self_play_with_chains(state: GameState) -> GameState:
    """Alias for _greedy_self_play — plays cards with effect chain support."""
    return _greedy_self_play(state)


# ──────────────────────────────────────────────────────────────────
# Turn start triggers
# ──────────────────────────────────────────────────────────────────


def _apply_turn_start_triggers(state: GameState) -> None:
    """Apply turn-start effects from card text on board minions.

    Handles patterns like:
    - "在你的回合开始时获得+1/+1"
    - "At the start of your turn, gain +1/+1"
    """
    import re
    _TURN_START_BUFF_EN = re.compile(
        r'start of your turn.*?gain\s*\+(\d+)/\+(\d+)', re.IGNORECASE
    )
    _TURN_START_BUFF_CN = re.compile(r'回合开始时获得\s*\+(\d+)/\+(\d+)')
    for m in state.board:
        text = ''
        en_text = ''
        card_ref = getattr(m, 'card_ref', None)
        if card_ref is not None:
            text = getattr(card_ref, 'text', '') or ''
            en_text = getattr(card_ref, 'english_text', '') or ''
        if not text:
            text = getattr(m, 'text', '') or ''
        if not text and not en_text:
            continue
        match = _TURN_START_BUFF_EN.search(en_text) or _TURN_START_BUFF_CN.search(text)
        if match:
            atk_bonus = int(match.group(1))
            hp_bonus = int(match.group(2))
            m.attack += atk_bonus
            m.health += hp_bonus
            m.max_health += hp_bonus


# ──────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────


def _pick_best_play(playable: list, state: GameState):
    """Pick the best card to play from a list of playable actions.

    Heuristic:
    - Prefer cards with highest (attack + health - cost) for minions
    - Prefer highest damage for spells
    - Prefer weapons with highest attack
    """
    if not playable:
        return None

    def _play_value(a):
        from analysis.search.abilities.actions import ActionType
        idx = a.card_index
        if 0 <= idx < len(state.hand):
            card = state.hand[idx]
            cost = getattr(card, 'cost', 0) or 0
            eff_cost = state.mana.effective_cost(card)
            if eff_cost > state.mana.available:
                return -100

            card_type = getattr(card, 'card_type', '').upper()
            if card_type == "MINION":
                atk = getattr(card, 'attack', 0) or 0
                hp = getattr(card, 'health', 0) or 0
                return (atk + hp - eff_cost) * 1.0  # Tempo value
            elif card_type == "SPELL":
                from analysis.data.card_effects import get_card_damage
                dmg = get_card_damage(card)
                if dmg > 0:
                    return dmg - eff_cost * 0.5
                # Non-damage spells: moderate value
                return max(0, 3 - eff_cost * 0.3)
            elif card_type == "WEAPON":
                atk = getattr(card, 'attack', 0) or 0
                return atk * 2 - eff_cost
            else:
                return 1.0
        return 0

    try:
        best = max(playable, key=_play_value)
        bv = _play_value(best)
        if bv < -50:
            return None
        return best
    except (ValueError, TypeError):
        return None



def _pick_best_attack(attacks: list, state: GameState):
    """Pick the best attack from a list of attack actions.

    Priority:
    1. Face attacks when opponent is low HP
    2. Favorable trades (we kill them, we survive)
    3. Face damage
    """
    if not attacks:
        return None

    def _attack_value(a):
        from analysis.search.abilities.actions import ActionType
        tgt_idx = a.target_index
        src_idx = a.source_index

        # Get source attack value
        if src_idx == -1:
            src_atk = state.hero.weapon.attack if state.hero.weapon else 0
            src_hp = state.hero.hp
        elif 0 <= src_idx < len(state.board):
            src_atk = state.board[src_idx].attack
            src_hp = state.board[src_idx].health
        else:
            return -100

        if tgt_idx == 0:
            # Face attack
            opp_hp = state.opponent.hero.hp + state.opponent.hero.armor
            if src_atk >= opp_hp:
                return 1000  # Lethal
            return src_atk * 1.5  # Face damage is valuable
        else:
            # Minion trade
            enemy_idx = tgt_idx - 1
            if 0 <= enemy_idx < len(state.opponent.board):
                tgt = state.opponent.board[enemy_idx]
                tgt_atk = tgt.attack
                tgt_hp = tgt.health

                # Favorable trade: we kill them, we survive
                if src_atk >= tgt_hp and src_hp > tgt_atk:
                    return 50 + (tgt_atk + tgt_hp) * 0.5
                # Even trade
                elif src_atk >= tgt_hp:
                    return 20 + tgt_atk * 0.5
                # Unfavorable trade
                else:
                    return -10
            return 0

    try:
        return max(attacks, key=_attack_value)
    except (ValueError, TypeError):
        return None


def _get_card_name(state: GameState, action) -> str:
    """Get the name of the card being played."""
    from analysis.search.abilities.actions import ActionType
    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        idx = action.card_index
        if 0 <= idx < len(state.hand):
            return getattr(state.hand[idx], 'name', f'Card#{idx}')
    return str(action.action_type)


def _get_card_cost(state: GameState, action) -> int:
    """Get the effective cost of the card being played."""
    from analysis.search.abilities.actions import ActionType
    if action.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET):
        idx = action.card_index
        if 0 <= idx < len(state.hand):
            card = state.hand[idx]
            return state.mana.effective_cost(card)
    return 0


def _describe_target(state: GameState, action) -> str:
    """Describe the target of an action."""
    from analysis.search.abilities.actions import ActionType
    if action.action_type == ActionType.PLAY_WITH_TARGET:
        tgt_idx = action.target_index
        if tgt_idx == 0:
            return "enemy_hero"
        elif 0 < tgt_idx <= len(state.opponent.board):
            m = state.opponent.board[tgt_idx - 1]
            return f"{m.name}({m.attack}/{m.health})"
    return ""


def _describe_attack_target(state: GameState, action) -> str:
    """Describe the target of an attack action."""
    tgt_idx = action.target_index
    if tgt_idx == 0:
        return "enemy_hero"
    elif 0 < tgt_idx <= len(state.opponent.board):
        m = state.opponent.board[tgt_idx - 1]
        return f"{m.name}({m.attack}/{m.health})"
    return f"target#{tgt_idx}"


def _count_plays_in_log(sim_log, perspective: str) -> int:
    """Count total PLAY actions in the current sim log phase."""
    if not sim_log.enabled or sim_log._current_phase is None:
        return 0
    return sum(
        1 for s in sim_log._current_phase.steps
        if s.step_type == "action" and f"PLAY({perspective})" in s.detail
    )

#!/usr/bin/env python3
"""turn_advance.py — Cross-turn state advancement for MCTS.

Simulates the full cycle: our END_TURN → opponent turn → our next turn start.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.search.game_state import GameState

log = logging.getLogger(__name__)


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
    2. Opponent's turn: mana refresh, draw, minions attack, opponent greedy.
    3. Opponent's end-of-turn cleanup.
    4. Our next turn: mana refresh, draw, minions can attack, greedy play.

    Args:
        state: GameState after our END_TURN has been applied (cleanup done).
        greedy_opponent: If True, simulate opponent attacking greedily.

    Returns:
        New GameState at the end of our next turn (after greedy play).
    """
    s = state.copy()

    # === Step 2: Opponent's turn start ===
    s.turn_number += 1

    opp_estimated_max = min(10, max(1, s.turn_number // 2 + 1))

    if s.opponent.deck_remaining > 0:
        s.opponent.deck_remaining -= 1
        s.opponent.hand_count += 1

    for m in s.opponent.board:
        if not m.has_rush:
            m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    if greedy_opponent:
        s = _greedy_opponent_play(s)

    # === Step 3: Opponent's end-of-turn cleanup ===
    for m in s.board:
        m.frozen_until_next_turn = False
        m.has_immune = False
    s.hero.is_immune = False

    # === Step 4: Our next turn start ===
    s.turn_number += 1

    next_max = min(s.mana.max_mana_cap, s.mana.max_mana + 1)
    s.mana.max_mana = next_max
    # overloaded was set by our _apply_end_turn and preserved across
    # opponent's turn — do NOT overwrite from overload_next (which is 0).
    s.mana.overload_next = 0
    s.mana.available = max(0, next_max - s.mana.overloaded)
    s.mana.modifiers = []

    if s.deck_remaining > 0:
        drawn = _draw_from_deck(s)
        if drawn is not None:
            s.hand.append(drawn)
        s.deck_remaining -= 1
    else:
        s.fatigue_damage += 1
        s.hero.hp -= s.fatigue_damage

    for m in s.board:
        m.can_attack = True
        m.has_attacked_once = False
        m.frozen_until_next_turn = False
        m.has_immune = False

    s.cards_played_this_turn = []

    _apply_turn_start_triggers(s)

    # === Step 4b: Our greedy play — spend mana efficiently ===
    s = _greedy_self_play(s)

    # Greedy attacks with our minions
    s = _greedy_self_attacks(s)

    return s


def _greedy_self_play(state: GameState) -> GameState:
    """Play cards greedily to maximise board impact.

    Evaluates cards by: stats/cost ratio for minions, spell impact from text,
    weapon attack value. Prefers cards with combo/battlecry synergy.
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.enumeration import enumerate_legal_actions

    s = state
    max_plays = 7
    cards_played_count = 0

    for _ in range(max_plays):
        if s.mana.available <= 0:
            break

        actions = enumerate_legal_actions(s)
        playable = [
            a for a in actions
            if a.action_type in (ActionType.PLAY, ActionType.PLAY_WITH_TARGET)
        ]
        if not playable:
            break

        def _play_value(a):
            idx = a.card_index
            if 0 <= idx < len(s.hand):
                card = s.hand[idx]
                eff_cost = s.mana.effective_cost(card)
                from analysis.search.abilities.simulation import _apply_text_cost_reduction
                eff_cost = _apply_text_cost_reduction(card, s.hand, idx, eff_cost)
                if eff_cost > s.mana.available:
                    return -100
                ct = (getattr(card, 'card_type', '') or '').upper()
                atk = getattr(card, 'attack', 0) or 0
                hp = getattr(card, 'health', 0) or 0
                text = (getattr(card, 'text', '') or '').lower()

                # Hand-transform: use transformed stats for evaluation
                try:
                    from analysis.data.card_effects import get_effects
                    _eff = get_effects(card)
                    if _eff.has_hand_transform:
                        atk = _eff.transform_attack
                        hp = _eff.transform_health
                except Exception:
                    pass

                if ct == 'MINION':
                    # Base: stat total / cost efficiency
                    value = atk + hp
                    # Bonus for keywords
                    if '突袭' in text or 'rush' in text:
                        value += 2
                    if '嘲讽' in text or 'taunt' in text:
                        value += 1.5
                    if '战吼' in text or 'battlecry' in text:
                        value += 1.5
                    if '圣盾' in text or 'divine shield' in text:
                        value += 2
                    if '吸血' in text or 'lifesteal' in text:
                        value += 1.5
                    # Combo bonus: second+ card played benefits from combo
                    if cards_played_count > 0 and ('连击' in text or 'combo' in text):
                        value += 3
                elif ct == 'SPELL':
                    # Estimate spell value using structured effects
                    from analysis.data.card_effects import get_effects as _get_eff
                    card_eff = _get_eff(card)
                    value = 0.0
                    if card_eff.damage > 0:
                        value += card_eff.damage * 2.0
                    if card_eff.aoe_damage > 0:
                        enemy_board_size = len(s.opponent.board)
                        value += card_eff.aoe_damage * enemy_board_size * 1.5
                    if card_eff.random_damage > 0:
                        value += card_eff.random_damage * 1.5
                    if card_eff.draw > 0:
                        value += card_eff.draw * 2.5
                    if card_eff.heal > 0:
                        hp_missing = (getattr(s.hero, 'max_hp', 30) or 30) - s.hero.hp
                        value += min(card_eff.heal, hp_missing) * 0.8
                    if card_eff.armor > 0:
                        value += card_eff.armor * 1.0
                    if card_eff.has_summon:
                        if card_eff.summon_attack > 0:
                            value += card_eff.summon_attack + card_eff.summon_health
                        else:
                            value += 3.0  # random summon EV
                    if card_eff.buff_attack > 0:
                        our_board_size = len(s.board)
                        value += card_eff.buff_attack * our_board_size * 1.0
                    if card_eff.has_discover:
                        value += 4.0
                    if card_eff.has_destroy:
                        value += 3.0
                    if card_eff.has_lifesteal and card_eff.damage > 0:
                        value += card_eff.damage * 0.5
                    if value <= 0:
                        value = eff_cost * 1.5  # baseline fallback
                elif ct == 'WEAPON':
                    value = atk * 2
                else:
                    value = atk + hp
                # Normalize by cost for efficiency
                if eff_cost > 0:
                    value = value * (1.0 + 1.0 / eff_cost)
                return value
            return 0

        best = max(playable, key=_play_value)
        bv = _play_value(best)
        if bv < 0:
            break

        s = apply_action(s, best)
        cards_played_count += 1

    return s


def _greedy_self_attacks(state: GameState) -> GameState:
    """Attack with our minions, considering trade value.

    Priority:
    1. Lethal (can kill enemy hero)
    2. Favorable trades (kill high-value enemy minion with low-value attacker)
    3. Face attacks
    """
    from analysis.search.abilities.actions import ActionType
    from analysis.search.abilities.simulation import apply_action
    from analysis.search.abilities.enumeration import enumerate_legal_actions

    s = state

    for _ in range(7):
        actions = enumerate_legal_actions(s)
        attacks = [
            a for a in actions
            if a.action_type == ActionType.ATTACK
        ]
        if not attacks:
            break

        # Check for lethal: can we kill the enemy hero?
        enemy_hero_hp = s.opponent.hero.hp
        face_attacks = [a for a in attacks if a.target_index == 0]
        total_face_damage = 0
        for fa in face_attacks:
            src_idx = fa.source_index
            if src_idx == -1:
                total_face_damage += s.hero.weapon.attack if s.hero.weapon else 0
            elif 0 <= src_idx < len(s.board):
                total_face_damage += s.board[src_idx].attack
        if total_face_damage >= enemy_hero_hp and face_attacks:
            # Go all face for lethal
            s = apply_action(s, face_attacks[0])
            continue

        # Find best trade: maximize (enemy_value_killed - our_value_lost)
        best_trade = None
        best_trade_score = 0.0
        for a in attacks:
            if a.target_index == 0:
                continue  # face attack, handled separately
            src_idx = a.source_index
            tgt_idx = a.target_index - 1  # 0-indexed enemy board
            if src_idx < 0 or src_idx >= len(s.board):
                continue
            if tgt_idx < 0 or tgt_idx >= len(s.opponent.board):
                continue
            our_minion = s.board[src_idx]
            enemy_minion = s.opponent.board[tgt_idx]
            our_value = our_minion.attack + our_minion.health
            enemy_value = enemy_minion.attack + enemy_minion.health
            # Can we kill it?
            can_kill = enemy_minion.health <= our_minion.attack
            # Will we survive?
            we_survive = enemy_minion.attack < our_minion.health
            if can_kill:
                if we_survive:
                    score = enemy_value + 2.0  # bonus for clean kill
                else:
                    score = enemy_value - our_value * 0.5
                if score > best_trade_score:
                    best_trade_score = score
                    best_trade = a

        if best_trade and best_trade_score > 1.0:
            s = apply_action(s, best_trade)
        elif face_attacks:
            s = apply_action(s, face_attacks[0])
        else:
            s = apply_action(s, attacks[0])

    return s


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


def _greedy_opponent_play(state: GameState) -> GameState:
    """Simulate opponent playing cards and attacking greedily.

    Strategy:
    1. Play cards from opponent's sampled hand — minions, weapons, AND spells.
       Spell effects (damage, heal, draw, buff, AOE, discover, summon) are
       applied directly using card_effects structured data.
    2. Attack favorably (kill our minion, theirs survives)
    3. Attack taunts if present
    4. Go face otherwise
    """
    from analysis.data.card_effects import get_effects

    s = state
    opp_board = s.opponent.board
    our_board = s.board

    # --- Phase 1: Play cards from opponent's sampled hand ---
    opp_hand = getattr(s.opponent, 'hand', None)
    opp_mana = getattr(s.opponent, 'mana_available', 0)

    if opp_hand and len(opp_hand) > 0 and opp_mana > 0:
        played = 0
        for _ in range(min(5, len(opp_hand))):
            if opp_mana <= 0:
                break

            # Score all playable cards
            best_idx = -1
            best_value = -1.0
            for i, card in enumerate(opp_hand):
                cost = getattr(card, 'cost', 0) or 0
                if cost > opp_mana:
                    continue
                value = _opp_card_value(card, s)
                if value > best_value:
                    best_value = value
                    best_idx = i

            if best_idx < 0 or best_value <= 0:
                break

            card = opp_hand.pop(best_idx)
            ct = (getattr(card, 'card_type', '') or '').upper()
            cost = getattr(card, 'cost', 0) or 0
            opp_mana -= cost

            # Apply card effects from opponent's perspective
            _apply_opp_card_effects(s, card, ct, get_effects)
            played += 1

        if hasattr(s.opponent, 'mana_available'):
            s.opponent.mana_available = opp_mana

    # --- Phase 2: Attack with opponent minions ---
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

    s.board = [m for m in s.board if m.health > 0]
    s.opponent.board = [m for m in s.opponent.board if m.health > 0]

    return s


def _opp_card_value(card, state: 'GameState') -> float:
    """Score an opponent card for greedy selection.

    Uses get_effects() to evaluate spell/minion/weapon impact.
    """
    from analysis.data.card_effects import get_effects

    cost = getattr(card, 'cost', 0) or 0
    ct = (getattr(card, 'card_type', '') or '').upper()
    eff = get_effects(card)

    if ct == 'MINION':
        atk = getattr(card, 'attack', 0) or 0
        hp = getattr(card, 'health', 0) or 0
        value = atk + hp + eff.damage * 1.5 + eff.draw * 2
        if eff.has_discover:
            value += 4
        if eff.buff_attack > 0:
            value += eff.buff_attack * 1.5
        return value
    elif ct == 'SPELL':
        value = 0.0
        # Damage to us is valuable for opponent
        if eff.damage > 0:
            value += eff.damage * 2.0
        if eff.aoe_damage > 0:
            # AOE scales with our board size
            our_board_size = len(getattr(state, 'board', []))
            value += eff.aoe_damage * our_board_size * 1.5
        if eff.random_damage > 0:
            value += eff.random_damage * 1.5
        # Healing is less valuable unless hero is damaged
        if eff.heal > 0:
            opp_hero = getattr(state.opponent, 'hero', None)
            if opp_hero:
                max_hp = getattr(opp_hero, 'max_hp', 30) or 30
                hp_missing = max_hp - getattr(opp_hero, 'hp', 30)
                value += min(eff.heal, hp_missing) * 0.8
        # Draw is always decent
        if eff.draw > 0:
            value += eff.draw * 2.5
        # Armor is defensive value
        if eff.armor > 0:
            value += eff.armor * 1.0
        # Summon minions
        if eff.summon_attack > 0:
            value += (eff.summon_attack + eff.summon_health)
        elif eff.has_summon:
            value += 3.0  # random summon value estimate
        # Buff existing board
        if eff.buff_attack > 0:
            opp_board_size = len(getattr(state.opponent, 'board', []))
            value += eff.buff_attack * opp_board_size * 1.0
        # Discover
        if eff.has_discover:
            value += 4.0
        # Destroy is very situational
        if eff.has_destroy:
            value += 3.0
        # Silence
        if eff.has_silence:
            value += 2.0
        # Lifesteal bonus
        if eff.has_lifesteal and eff.damage > 0:
            value += eff.damage * 0.5
        return max(value, 0.5) if value > 0 else 0
    elif ct == 'WEAPON':
        atk = getattr(card, 'attack', 0) or 0
        dur = getattr(card, 'health', 0) or getattr(card, 'durability', 0) or 0
        return atk * min(dur, 3)
    return 0


def _apply_opp_card_effects(
    state: 'GameState',
    card,
    card_type: str,
    get_effects_fn,
) -> None:
    """Apply card effects from opponent's perspective (mutates state).

    Handles: minion summon, weapon equip, spell damage/heal/draw/armor/buff/AOE.
    """
    from analysis.search.game_state import Minion as _Minion

    eff = get_effects_fn(card)

    if card_type == 'MINION':
        # Summon minion to opponent board
        opp_board = state.opponent.board
        if len(opp_board) < 7:
            atk = getattr(card, 'attack', 0) or 0
            hp = getattr(card, 'health', 0) or 0
            m = _Minion(
                attack=atk, health=hp, max_health=hp,
                name=getattr(card, 'name', 'Opp Minion'),
                can_attack=True,
            )
            opp_board.append(m)
        # Track opponent's last played minion for hand-transform cards
        state.opponent.opp_last_played_minion = {
            "name": getattr(card, 'name', ''),
            "attack": getattr(card, 'attack', 0) or 0,
            "health": getattr(card, 'health', 0) or 0,
            "card_id": getattr(card, 'card_id', ''),
        }
        # Apply battlecry effects
        if eff.damage > 0:
            state.hero.hp -= eff.damage
        if eff.aoe_damage > 0:
            for our_m in state.board:
                our_m.health -= eff.aoe_damage
        if eff.heal > 0:
            opp_hero = getattr(state.opponent, 'hero', None)
            if opp_hero:
                opp_hero.hp = min(
                    getattr(opp_hero, 'max_hp', 30) or 30,
                    opp_hero.hp + eff.heal
                )
        if eff.draw > 0:
            opp_hc = getattr(state.opponent, 'hand_count', 0)
            state.opponent.hand_count = opp_hc + eff.draw
        if eff.has_discover:
            opp_hc = getattr(state.opponent, 'hand_count', 0)
            state.opponent.hand_count = opp_hc + 1
        if eff.buff_attack > 0:
            for m in state.opponent.board:
                m.attack += eff.buff_attack

    elif card_type == 'WEAPON':
        # Equip weapon to opponent
        atk = getattr(card, 'attack', 0) or 0
        dur = getattr(card, 'health', 0) or getattr(card, 'durability', 0) or 0
        opp_hero = getattr(state.opponent, 'hero', None)
        if opp_hero and hasattr(opp_hero, 'weapon'):
            from analysis.search.game_state import Weapon as _Weapon
            opp_hero.weapon = _Weapon(attack=atk, durability=dur)

    elif card_type == 'SPELL':
        # Direct damage → our hero
        if eff.damage > 0:
            state.hero.hp -= eff.damage
        # AOE → our board
        if eff.aoe_damage > 0:
            for our_m in state.board:
                our_m.health -= eff.aoe_damage
        # Random damage → split between our hero and minions
        if eff.random_damage > 0:
            state.hero.hp -= eff.random_damage
        # Heal → opponent hero
        if eff.heal > 0:
            opp_hero = getattr(state.opponent, 'hero', None)
            if opp_hero:
                opp_hero.hp = min(
                    getattr(opp_hero, 'max_hp', 30) or 30,
                    opp_hero.hp + eff.heal
                )
        # Draw → opponent hand
        if eff.draw > 0:
            opp_hc = getattr(state.opponent, 'hand_count', 0)
            state.opponent.hand_count = opp_hc + eff.draw
        # Armor → opponent hero
        if eff.armor > 0:
            opp_hero = getattr(state.opponent, 'hero', None)
            if opp_hero:
                opp_hero.armor = getattr(opp_hero, 'armor', 0) + eff.armor
        # Summon → opponent board
        if eff.has_summon:
            opp_board = state.opponent.board
            if len(opp_board) < 7:
                sa = eff.summon_attack or 1
                sh = eff.summon_health or 1
                m = _Minion(
                    attack=sa, health=sh, max_health=sh,
                    name='Summoned Minion',
                    can_attack=True,
                )
                opp_board.append(m)
        # Buff → opponent board
        if eff.buff_attack > 0:
            for m in state.opponent.board:
                m.attack += eff.buff_attack
                if eff.buff_health > 0:
                    m.health += eff.buff_health
                    m.max_health += eff.buff_health
        # Discover → opponent hand +1
        if eff.has_discover:
            opp_hc = getattr(state.opponent, 'hand_count', 0)
            state.opponent.hand_count = opp_hc + 1
        # Destroy → remove random our minion
        if eff.has_destroy:
            our_board = state.board
            if our_board:
                import random
                idx = random.randint(0, len(our_board) - 1)
                our_board.pop(idx)
        # Silence → silence random our minion
        if eff.has_silence:
            our_board = state.board
            if our_board:
                import random
                m = random.choice(our_board)
                m.has_taunt = False
                m.has_divine_shield = False
                m.has_poisonous = False
                m.has_windfury = False
                m.has_lifesteal = False
                m.has_reborn = False
                m.has_stealth = False

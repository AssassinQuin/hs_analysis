"""V10 State-Indexed Value (SIV) — per-card state-aware scoring.

Applies 8 multiplicative modifiers on top of V8 contextual score:
  1. lethal_awareness    — boosts damage cards when enemy is low
  2. taunt_constraint    — penalises/buffs based on enemy taunts
  3. curve_tempo         — on-curve vs overflow penalty
  4. hand_position       — outcast / shatter position bonus
  5. trigger_probability — Brann/Rivendare/aura multipliers
  6. race_synergy        — same-race board+hand density
  7. progress_tracker    — imbue/herald/quest progress bonus
  8. counter_awareness   — freeze/secret/AoE counter-play

Entry point: siv_score(card, state) -> float
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from analysis.models.card import Card
from analysis.search.game_state import GameState, Minion
from analysis.scorers.keyword_interactions import get_interaction_multiplier

# ---------------------------------------------------------------------------
# V8 fallback — use contextual_score if available, else card.score
# ---------------------------------------------------------------------------
try:
    from analysis.scorers.v8_contextual import get_scorer as _get_v8_scorer

    def _civ_base(card: Card, state: GameState) -> float:
        try:
            scorer = _get_v8_scorer()
            score = scorer.contextual_score(card, state)
            if score != 0.0:
                return score
        except Exception:
            pass
        return getattr(card, "score", 0.0)

except ImportError:

    def _civ_base(card: Card, state: GameState) -> float:
        return getattr(card, "score", 0.0)


# ===================================================================
# Constants
# ===================================================================
OUTCAST_BONUS = 0.3
MERGE_BONUS = 0.3

# Freeze-prone opponent classes
_FREEZE_CLASSES = frozenset({"MAGE", "SHAMAN"})

# Keywords that indicate damage-dealing capability
_DAMAGE_TEXT_PATTERNS = re.compile(
    r"造成|伤害|Deal|damage", re.IGNORECASE
)
_SILENCE_TEXT_PATTERNS = re.compile(
    r"Silence|沉默", re.IGNORECASE
)
_DESTROY_TEXT_PATTERNS = re.compile(
    r"Destroy|消灭", re.IGNORECASE
)

# Trigger mechanic names (uppercase, matching Card.mechanics convention)
_TRIGGER_MECHANICS = {
    "BATTLECRY",
    "DEATHRATTLE",
    "END_OF_TURN",
    "INSPIRE",
}

# Aura / trigger enabler names on board minions
_BATTLECRY_ENABLERS = frozenset({"BRANN", "青铜龙"})
_DEATHRATTLE_ENABLERS = frozenset({"BARON_RIVENDARE", "瑞文戴尔"})
_EOT_ENABLERS = frozenset({"DRAKKARI", "德拉卡里"})


# ===================================================================
# Modifier 1: lethal_awareness
# ===================================================================
def lethal_modifier(card: Card, state: GameState) -> float:
    """Boost damage/charge/weapon cards when enemy HP is low.

    Formula: 1 + (1 - enemy_total_hp / 30)² × 3.0
    Returns 1.0 for non-damage cards.
    """
    text = getattr(card, "text", "") or ""
    card_type = getattr(card, "card_type", "").upper()
    mechanics = set(getattr(card, "mechanics", []) or [])

    # Is this a damage-dealing card?
    is_damage = (
        _DAMAGE_TEXT_PATTERNS.search(text) is not None
        or "CHARGE" in mechanics
        or "RUSH" in mechanics
        or card_type == "WEAPON"
    )
    if not is_damage:
        return 1.0

    enemy_hp = state.opponent.hero.hp + state.opponent.hero.armor
    enemy_hp = max(enemy_hp, 0)
    ratio = enemy_hp / 30.0
    return 1.0 + (1.0 - ratio) ** 2 * 3.0


# ===================================================================
# Modifier 2: taunt_constraint
# ===================================================================
def taunt_modifier(card: Card, state: GameState) -> float:
    """Adjust card value based on enemy taunt presence.

    Base:  1 + 0.3 × enemy_taunt_count
    Bonus: +0.5 for silence/destroy text, +0.3 for poisonous
    Returns 1.0 if no enemy taunts.
    """
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]
    count = len(enemy_taunts)
    if count == 0:
        return 1.0

    mult = 1.0 + 0.3 * count

    text = getattr(card, "text", "") or ""
    mechanics = set(getattr(card, "mechanics", []) or [])

    if _SILENCE_TEXT_PATTERNS.search(text):
        mult += 0.5
    if _DESTROY_TEXT_PATTERNS.search(text):
        mult += 0.5
    if "POISONOUS" in mechanics:
        mult += 0.3

    return mult


# ===================================================================
# Modifier 3: curve / tempo window
# ===================================================================
def curve_modifier(card: Card, state: GameState) -> float:
    """Penalty for off-curve play; bonus for efficient mana use.

    On-curve (cost <= available):  1.0
    1 mana over:                   0.9
    Further over:                  0.8 - 0.05 × (gap - 1)
    Overflow:                      -0.1 × max(0, cost - turn - 1)
    Floor:                         0.5
    """
    cost = getattr(card, "cost", 0)
    available = state.mana.available
    turn = state.turn_number

    if cost <= available:
        # On curve
        result = 1.0
    elif cost == available + 1:
        result = 0.9
    else:
        gap = cost - available
        result = 0.8 - 0.05 * (gap - 1)

    # Overflow penalty: penalise cards that are too expensive for the turn
    overflow = max(0, cost - turn - 1)
    result -= overflow * 0.1

    return max(0.5, result)


# ===================================================================
# Modifier 4: hand_position
# ===================================================================
def position_modifier(card: Card, state: GameState) -> float:
    """Position-dependent bonus for outcast and shatter mechanics.

    Outcast: if card index is 0 or last → 1 + OUTCAST_BONUS
    Shatter: estimate merge probability → 1 + prob × MERGE_BONUS
    Default: 1.0
    """
    hand = state.hand
    if not hand:
        return 1.0

    # Find card position in hand
    card_idx = None
    for i, c in enumerate(hand):
        if c is card:
            card_idx = i
            break

    if card_idx is None:
        return 1.0

    text = getattr(card, "text", "") or ""
    mechanics = set(getattr(card, "mechanics", []) or [])

    # Outcast check
    if "OUTCAST" in mechanics or "Outcast" in text or "外域" in text:
        if card_idx == 0 or card_idx == len(hand) - 1:
            return 1.0 + OUTCAST_BONUS
        return 1.0

    # Shatter check — rough merge probability based on hand density
    if "SHATTER" in mechanics or "Shatter" in text or "裂变" in text:
        # More cards in hand → higher chance of having merge targets
        merge_prob = min(1.0, (len(hand) - 1) / 7.0)
        return 1.0 + merge_prob * MERGE_BONUS

    return 1.0


# ===================================================================
# Modifier 5: trigger_probability
# ===================================================================
def trigger_modifier(card: Card, state: GameState) -> float:
    """Multiply card value when trigger enablers are on board.

    Brann → ×2.0 for BATTLECRY
    Rivendare → ×2.0 for DEATHRATTLE
    Drakkari → ×2.0 for END_OF_TURN
    Race aura → ×1.3 if board has same-race minion
    """
    mechanics = set(getattr(card, "mechanics", []) or [])
    if not mechanics.intersection(_TRIGGER_MECHANICS):
        return 1.0

    mult = 1.0

    # Check board for trigger enablers
    for m in state.board:
        name_upper = (m.name or "").upper().replace(" ", "_")
        # Brann: doubles battlecry
        if name_upper in _BATTLECRY_ENABLERS or "BRANN" in name_upper:
            if "BATTLECRY" in mechanics:
                mult *= 2.0
        # Rivendare: doubles deathrattle
        if name_upper in _DEATHRATTLE_ENABLERS or "RIVENDARE" in name_upper:
            if "DEATHRATTLE" in mechanics:
                mult *= 2.0
        # Drakkari: doubles end-of-turn
        if name_upper in _EOT_ENABLERS or "DRAKKARI" in name_upper:
            if "END_OF_TURN" in mechanics:
                mult *= 2.0

        # Race aura: boost same-race triggers
        card_race = getattr(card, "race", "") or ""
        minion_race = getattr(m, "race", "") if hasattr(m, "race") else ""
        if card_race and minion_race and card_race == minion_race:
            mult *= 1.3

    return mult


# ===================================================================
# Modifier 6: race_synergy
# ===================================================================
def synergy_modifier(card: Card, state: GameState) -> float:
    """Bonus for same-race density on board + hand.

    Formula: 1 + 0.1 × total_count
    Kindred bonus: if card has 延系 and last-turn race matches → extra +0.2
    """
    card_race = getattr(card, "race", "") or ""
    if not card_race:
        return 1.0

    # Count same-race on board
    board_count = 0
    for m in state.board:
        m_race = getattr(m, "race", "") if hasattr(m, "race") else ""
        if m_race == card_race:
            board_count += 1

    # Count same-race in hand (excluding the card itself)
    hand_count = 0
    for c in state.hand:
        if c is card:
            continue
        c_race = getattr(c, "race", "") or ""
        if c_race == card_race:
            hand_count += 1

    total = board_count + hand_count
    result = 1.0 + 0.1 * total

    # Kindred (延系) bonus
    text = getattr(card, "text", "") or ""
    if "Kindred" in text or "延系" in text:
        result += 0.2

    return result


# ===================================================================
# Modifier 7: progress_tracker
# ===================================================================
def progress_modifier(card: Card, state: GameState) -> float:
    """Bonus for mechanics with progress tracking (imbue/herald/quest).

    Imbue:  1 + 0.3 × (1 - 0.15 × level)
    Herald: threshold at count 1 → 1.5, at count 3 → 1.5, else 1.0
    Quest:  1 + completion_pct² × 2.0
    Default: 1.0
    """
    mechanics = set(getattr(card, "mechanics", []) or [])
    text = getattr(card, "text", "") or ""

    # Imbue check
    if "IMBUE" in mechanics or "Imbue" in text or "灌注" in text:
        level = getattr(state, "imbue_level", None)
        if level is None:
            level = 0
        return 1.0 + 0.3 * (1.0 - 0.15 * level)

    # Herald check
    if "HERALD" in mechanics or "Herald" in text or "先驱" in text:
        count = getattr(state, "herald_count", 0)
        if count >= 3:
            return 1.5
        if count >= 1:
            return 1.5
        return 1.0

    # Quest check
    if "QUEST" in mechanics or "Quest" in text or "任务" in text:
        completion_pct = getattr(state, "quest_completion_pct", 0.0)
        return 1.0 + completion_pct ** 2 * 2.0

    return 1.0


# ===================================================================
# Modifier 8: counter_awareness
# ===================================================================
def counter_modifier(card: Card, state: GameState) -> float:
    """Penalise cards vulnerable to opponent's counters; boost counter-play.

    Freeze threat:   -0.1 if opponent is freeze class and card is key minion
    Secret threat:   -0.05 for battlecry, -0.1 for high-attack minions (atk >= 3)
    AoE potential:   +0.2 for stealth cards if enemy has AoE indicators
    Default:         1.0
    """
    opp_class = getattr(state.opponent.hero, "hero_class", "").upper()
    mechanics = set(getattr(card, "mechanics", []) or [])
    text = getattr(card, "text", "") or ""
    card_type = getattr(card, "card_type", "").upper()
    result = 1.0

    # Freeze threat: key minion vs freeze class
    if opp_class in _FREEZE_CLASSES:
        if card_type == "MINION":
            attack = getattr(card, "attack", 0)
            if attack >= 4:
                result -= 0.1

    # Secret threat
    opp_secrets = getattr(state.opponent, "secrets", [])
    if opp_secrets:
        if "BATTLECRY" in mechanics:
            result -= 0.05
        attack = getattr(card, "attack", 0)
        if card_type == "MINION" and attack >= 3:
            result -= 0.1

    # AoE potential: boost stealth cards
    enemy_board_size = len(state.opponent.board)
    if enemy_board_size <= 1:
        # Weak enemy board suggests they might play AoE
        pass
    if "STEALTH" in mechanics or "Stealth" in text or "潜行" in text:
        # Check if enemy might have AoE (heuristic: mage/shaman/warlock)
        if opp_class in ("MAGE", "SHAMAN", "WARLOCK"):
            result += 0.2

    return result


# ===================================================================
# Entry point
# ===================================================================

def siv_score(card: Card, state: GameState) -> float:
    """Compute SIV for a card: CIV base × all 8 modifiers, clamped.

    Returns value in [0.01, 100.0].
    """
    base = _civ_base(card, state)
    if base == 0.0:
        return 0.0

    modifiers = (
        lethal_modifier(card, state)
        * taunt_modifier(card, state)
        * curve_modifier(card, state)
        * position_modifier(card, state)
        * trigger_modifier(card, state)
        * synergy_modifier(card, state)
        * progress_modifier(card, state)
        * counter_modifier(card, state)
    )

    result = base * modifiers
    return max(0.01, min(100.0, result))


def hand_siv_sum(state: GameState) -> float:
    """Sum of SIV for all cards in hand."""
    return sum(siv_score(c, state) for c in state.hand)

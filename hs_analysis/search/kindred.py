"""kindred.py — 延系 (Kindred) mechanic for Hearthstone search engine.

延系 is a conditional bonus: when playing a card with "延系：..." text,
if the card shares a race or spellSchool with a card played last turn,
the bonus effect triggers.

29 cards in standard pool have 延系 effects. Detection is text-only —
no "KINDRED" mechanic tag exists in card data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from hs_analysis.search.game_state import GameState, Minion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

_KINDRED_RE = re.compile(r'延系[：:]?\s*(.+?)(?:<|$)', re.DOTALL)
_KINDRED_PRESENT_RE = re.compile(r'延系')


def has_kindred(card_text: str) -> bool:
    """Check if card text contains 延系 keyword."""
    return bool(_KINDRED_PRESENT_RE.search(card_text or ""))


def parse_kindred_bonus(card_text: str) -> str | None:
    """Extract the bonus effect text after 延系：or 延系.

    Returns the plain-text bonus description, or None if not found.
    """
    # Strip HTML-like tags for cleaner extraction
    clean = re.sub(r'<[^>]+>', ' ', card_text or "")
    # Find 延系 followed by optional colon, then capture until end or next keyword
    m = re.search(r'延系[：:]?\s*(.+?)(?:\n|$)', clean)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Condition check
# ---------------------------------------------------------------------------

def check_kindred_active(state: GameState, card: dict) -> bool:
    """Check if the card's race/spellSchool overlaps with last turn's plays.

    Cards can have multi-race like "MURLOC ELEMENTAL" — we split on whitespace
    and check each individually.
    """
    # Race check
    race_str = card.get("race", "") or ""
    if isinstance(race_str, str):
        card_races = {r.upper() for r in race_str.split() if r}
    else:
        card_races = set()

    if card_races & state.last_turn_races:
        return True

    # SpellSchool check
    school = card.get("spellSchool", "") or card.get("spell_school", "") or ""
    if isinstance(school, str) and school:
        card_schools = {s.upper() for s in school.split() if s}
        if card_schools & state.last_turn_schools:
            return True

    return False


# ---------------------------------------------------------------------------
# Bonus effect application
# ---------------------------------------------------------------------------

def _apply_bonus_effect(state: GameState, bonus_text: str, card: dict) -> GameState:
    """Parse and apply a single kindred bonus effect.

    Uses a simplified dispatch — common patterns from the 29 kindred cards.
    Falls back gracefully if pattern doesn't match.
    """
    s = state
    text = bonus_text.strip()

    # Pattern: "使你的其他随从获得突袭" → give rush to other friendly minions
    if '突袭' in text:
        for m in s.board:
            m.has_rush = True
        return s

    # Pattern: "使你的其他随从获得圣盾" → divine shield
    if '圣盾' in text and '其他' in text:
        for m in s.board:
            m.has_divine_shield = True
        return s

    # Pattern: "召唤一个本随从的复制" → summon copy
    if '复制' in text:
        if not s.board_full():
            # Find the card's minion on board (last played)
            for m in reversed(s.board):
                if m.name == (card.get("name") or ""):
                    copy_minion = Minion(
                        dbf_id=m.dbf_id, name=m.name,
                        attack=m.attack, health=m.health,
                        max_health=m.max_health, cost=m.cost,
                        has_rush=True,  # summoned copies get rush
                        owner="friendly",
                    )
                    s.board.append(copy_minion)
                    break
        return s

    # Pattern: "重复一次" → this is a meta-effect that would need
    # to re-trigger the card's main effect. Simplified: do nothing extra
    # (the main effect already fired once, which is the common case)
    if '重复' in text:
        logger.debug("Kindred 'repeat' bonus — already applied once")
        return s

    # Pattern: stat buff like "获得+2/+2" or "+1/+3"
    stat_match = re.search(r'[+＋](\d+)/[+＋](\d+)', text)
    if stat_match:
        atk_bonus = int(stat_match.group(1))
        hp_bonus = int(stat_match.group(2))
        if '其他' in text or '友方' in text:
            for m in s.board:
                m.attack += atk_bonus
                m.health += hp_bonus
                m.max_health += hp_bonus
        return s

    # Pattern: "使其获得法术伤害+N"
    spell_dmg = re.search(r'法术伤害[+＋](\d+)', text)
    if spell_dmg:
        # Simplified: buff hero's spell damage notionally
        # (actual spell damage tracked in evaluation)
        logger.debug("Kindred spell damage +%s applied", spell_dmg.group(1))
        return s

    # Pattern: "法力值消耗减少（N）点" → cost reduction for next card
    cost_red = re.search(r'消耗减少[（(]\s*(\d+)\s*[）)]', text)
    if cost_red:
        # Simplified: adjust hand card costs
        amount = int(cost_red.group(1))
        if s.hand:
            # Reduce cost of a random card in hand (simplified)
            for h_card in s.hand:
                if hasattr(h_card, 'cost'):
                    h_card.cost = max(0, h_card.cost - amount)
                break  # Only reduce one card
        return s

    # Fallback: unparseable bonus — log and skip
    logger.debug("Kindred bonus unparseable: %s", text[:60])
    return s


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def apply_kindred(state: GameState, card: dict) -> GameState:
    """Apply 延系 effect if card has it and condition is met.

    Integrates with kindred_double_next flag (蛮鱼挑战者).
    """
    card_text = card.get("text", "") or ""
    if not isinstance(card_text, str):
        card_text = str(card_text)

    if not has_kindred(card_text):
        return state

    try:
        if not check_kindred_active(state, card):
            return state

        bonus = parse_kindred_bonus(card_text)
        if not bonus:
            return state

        # Determine trigger count
        trigger_count = 1
        if state.kindred_double_next:
            trigger_count = 2
            state = replace(state, kindred_double_next=False)

        for _ in range(trigger_count):
            state = _apply_bonus_effect(state, bonus, card)

    except Exception as exc:
        logger.warning("Kindred dispatch failed: %s", exc)

    return state


def set_kindred_double(state: GameState) -> GameState:
    """Set kindred_double_next flag (for 蛮鱼挑战者's battlecry)."""
    return replace(state, kindred_double_next=True)

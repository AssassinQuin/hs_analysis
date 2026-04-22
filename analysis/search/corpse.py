"""corpse.py — 残骸 (Corpse) resource system for Death Knight.

残骸 is a DK-exclusive resource gained when friendly minions die.
23 DK cards in standard pool use 残骸 as a cost/enabler for effects.

Detection is text-only: "消耗N份残骸", "获得一份残骸", etc.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace

from analysis.search.game_state import GameState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CorpseEffect:
    """A parsed corpse cost + effect pair from card text."""
    cost: int
    is_optional: bool
    effect_text: str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# "消耗N份残骸" or "消耗最多N份残骸"
_CORPSE_SPEND_RE = re.compile(r"Spend\s*(\d+)\s*Corpse(?:s)?|Spend\s*up\s*to\s*(\d+)\s*Corpse(?:s)?|消耗最多\s*(\d+)\s*份\s*残骸|消耗\s*(\d+)\s*份\s*残骸")
# "获得一份残骸" or "获得N份残骸"
_CORPSE_GAIN_RE = re.compile(r"Gain\s*(?:a\s+)?(?:(\d+)\s+)?Corpse(?:s)?|获得\s*(?:一份|(\d+)\s*份)\s*残骸")


def parse_corpse_effects(card_text: str) -> list[CorpseEffect]:
    """Parse corpse spend requirements from card text.

    Returns list of CorpseEffect with cost, optionality, and effect text.
    """
    if not card_text:
        return []

    effects: list[CorpseEffect] = []
    text = card_text or ""

    for m in _CORPSE_SPEND_RE.finditer(text):
        spend_exact = m.group(1)
        spend_up_to = m.group(2)
        cn_max_cost = m.group(3)
        cn_exact_cost = m.group(4)

        if spend_up_to or cn_max_cost:
            cost = int(spend_up_to or cn_max_cost)
            effects.append(CorpseEffect(
                cost=cost,
                is_optional=True,
                effect_text=text[m.end():].strip()[:80],
            ))
        elif spend_exact or cn_exact_cost:
            cost = int(spend_exact or cn_exact_cost)
            # Check if the corpse spend is an add-on bonus (optional)
            # Pattern: main effect。消耗N份残骸，bonus
            effects.append(CorpseEffect(
                cost=cost,
                is_optional=False,
                effect_text=text[m.end():].strip()[:80],
            ))

    return effects


def parse_corpse_gain(card_text: str) -> int:
    """Parse corpse gain amount from card text.

    Returns the number of corpses gained, or 0.
    """
    if not card_text:
        return 0

    m = _CORPSE_GAIN_RE.search(card_text)
    if m:
        val = m.group(1) or m.group(2)
        return int(val) if val else 1

    return 0


# ---------------------------------------------------------------------------
# Resource management
# ---------------------------------------------------------------------------

def can_afford_corpses(state: GameState, cost: int) -> bool:
    """Check if player has enough corpses."""
    return state.corpses >= cost


def spend_corpses(state: GameState, cost: int) -> GameState:
    """Deduct corpses from state."""
    new_amount = max(0, state.corpses - cost)
    return replace(state, corpses=new_amount)


def gain_corpses(state: GameState, amount: int) -> GameState:
    """Add corpses to state."""
    return replace(state, corpses=state.corpses + amount)


# ---------------------------------------------------------------------------
# Double corpse generation (法瑞克 passive)
# ---------------------------------------------------------------------------

# 法瑞克 (Falric) — "你获得的残骸量为正常的两倍"
_FALRIC_NAME = "法瑞克"


def has_double_corpse_gen(state: GameState) -> bool:
    """Check if 法瑞克 is on the friendly board for double corpse generation."""
    for m in state.board:
        if _FALRIC_NAME in (m.name or ""):
            return True
    return False


# ---------------------------------------------------------------------------
# Effect resolution
# ---------------------------------------------------------------------------

def resolve_corpse_effects(state: GameState, card: dict) -> GameState:
    """Parse and resolve corpse effects from a DK card.

    For optional effects: apply if affordable, otherwise skip.
    For mandatory effects: always apply (spend what we can).
    """
    card_text = card.get("text", "") or ""
    if not isinstance(card_text, str):
        card_text = str(card_text)

    effects = parse_corpse_effects(card_text)
    if not effects:
        # Check for corpse gain (no spend)
        gain = parse_corpse_gain(card_text)
        if gain > 0:
            state = gain_corpses(state, gain)
        return state

    try:
        for eff in effects:
            if state.corpses < eff.cost:
                # Can't afford — skip if optional
                if eff.is_optional:
                    continue
                # Mandatory but can't afford — skip gracefully
                continue

            # Spend corpses
            state = spend_corpses(state, eff.cost)

            # Apply the bonus effect (simplified dispatch)
            state = _apply_corpse_bonus(state, eff.effect_text, card)

    except Exception as exc:
        logger.warning("Corpse effect resolution failed: %s", exc)

    # Also check for gain effects on the same card
    gain = parse_corpse_gain(card_text)
    if gain > 0:
        state = gain_corpses(state, gain)

    return state


def _apply_corpse_bonus(state: GameState, effect_text: str, card: dict) -> GameState:
    """Apply the bonus effect enabled by corpse spending.

    Simplified dispatch for common DK corpse effect patterns.
    """
    s = state
    text = effect_text.strip()

    # Pattern: stat buff "+1/+1" or "+N/+N"
    stat_match = re.search(r'[+＋](\d+)/[+＋](\d+)', text)
    if stat_match:
        atk = int(stat_match.group(1))
        hp = int(stat_match.group(2))
        # Apply to hand minions (common: "使手牌所有随从牌获得+1/+1")
        if '手牌' in text or '随从' in text:
            for h_card in s.hand:
                if hasattr(h_card, 'attack') and hasattr(h_card, 'health'):
                    h_card.attack = getattr(h_card, 'attack', 0) + atk
                    h_card.health = getattr(h_card, 'health', 0) + hp
        return s

    # Pattern: damage "造成N点伤害"
    dmg_match = re.search(r"Deal\s*(\d+)\s*damage", text, re.IGNORECASE)
    if not dmg_match:
        dmg_match = re.search(r'造成\s*[$(（]\s*(\d+)\s*[)）]?\s*点?\s*伤害', text)
    if not dmg_match:
        dmg_match = re.search(r'造成\s*(\d+)\s*点伤害', text)
    if dmg_match:
        amount = int(dmg_match.group(1))
        # Simplified: damage to enemy hero
        s.opponent.hero.hp -= amount
        return s

    # Pattern: summon "召唤"
    if '召唤' in text:
        # Simplified: skip detailed summon parsing
        logger.debug("Corpse summon effect: %s", text[:50])
        return s

    # Fallback: unparseable — log and skip
    logger.debug("Corpse bonus unparseable: %s", text[:60])
    return s

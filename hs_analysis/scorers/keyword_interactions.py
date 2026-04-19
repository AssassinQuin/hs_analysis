"""V10 keyword interaction multipliers.

Maps keyword pair interactions to score multipliers.
Used by SIV modifiers to adjust card evaluations.
"""

from __future__ import annotations
from typing import Iterable, Tuple

# (source_keyword, target_keyword) → multiplier
# Applied when card has source_keyword and target has target_keyword
INTERACTIONS: dict[Tuple[str, str], float] = {
    # Poisonous destroys Divine Shield without killing
    ("poisonous", "divine_shield"): 0.1,
    # Stealth ignores Taunt
    ("stealth", "taunt"): 0.0,
    # Immune ignores Taunt
    ("immune", "taunt"): 0.0,
    # Freeze halves Windfury effectiveness
    ("freeze", "windfury"): 0.5,
    # Lifesteal cannot heal if enemy has Divine Shield
    ("lifesteal", "divine_shield_enemy"): 0.0,
    # Reborn triggers Deathrattle again
    ("reborn", "deathrattle"): 1.5,
    # Brann doubles Battlecry
    ("brann", "battlecry"): 2.0,
    # Rivendare doubles Deathrattle
    ("rivendare", "deathrattle"): 2.0,
}


def get_interaction_multiplier(
    card_keywords: Iterable[str],
    target_keywords: Iterable[str],
) -> float:
    """Return product of all applicable interaction multipliers.

    Checks all (card_kw, target_kw) pairs against INTERACTIONS table.
    Returns 1.0 if no interactions apply.

    Args:
        card_keywords: Keywords on the source card/mechanic.
        target_keywords: Keywords on the target/context.

    Returns:
        Multiplicative modifier (product of all matching multipliers).
    """
    card_set = set(kw.lower() for kw in card_keywords)
    target_set = set(kw.lower() for kw in target_keywords)

    result = 1.0
    for (src, tgt), mult in INTERACTIONS.items():
        if src in card_set and tgt in target_set:
            result *= mult

    return result

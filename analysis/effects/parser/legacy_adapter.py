#!/usr/bin/env python3
"""legacy_adapter.py — Converts new-format parsed effects to legacy tuple format.

The EffectParser class bridges the new effects.parser system with the legacy
orchestration layer (spell.py, battlecry.py), which still consumes effects
as ``List[Tuple[str, object]]``.
"""

from __future__ import annotations

from typing import List, Tuple, TYPE_CHECKING

from analysis.effects.parser.interface import ChainingParser, parse as new_parse
from analysis.effects.types import EffectKind

if TYPE_CHECKING:
    from analysis.card.models.card import Card


class EffectParser:
    """Parse card effects from a Card object or text fallback.

    Delegates to analysis.effects.parser internally.
    Output format: List[Tuple[str, object]] (legacy format).
    """

    @staticmethod
    def parse(card_text: str, card: Card = None) -> List[Tuple[str, object]]:
        effects: List[Tuple[str, object]] = []
        card_id = getattr(card, 'card_id', '') if card else ''
        text = card_text
        if card:
            text = getattr(card, 'english_text', '') or getattr(card, 'text', '') or ''

        parsed = new_parse(card_id, text)
        if parsed is None and text:
            # Text-only fallback (no card_id found in DB)
            parsed = ChainingParser().parse_text_only("_text_fallback", text)
        if parsed is None:
            return effects

        for ability in parsed.abilities:
            for eff in ability.effects:
                kind = eff.kind
                params = eff.params
                if kind == EffectKind.DAMAGE:
                    amt = params.get("amount", 0)
                    effects.append(('direct_damage', amt))
                elif kind == EffectKind.AOE_DAMAGE:
                    effects.append(('aoe_damage', params.get("amount", 0)))
                elif kind == EffectKind.RANDOM_DAMAGE:
                    effects.append(('random_damage', params.get("amount", 0)))
                elif kind == EffectKind.SUMMON:
                    atk = params.get("attack", 0)
                    hp = params.get("health", 0)
                    if atk > 0 or hp > 0:
                        effects.append(('summon_stats', (atk, hp)))
                    else:
                        effects.append(('summon', True))
                elif kind == EffectKind.DRAW:
                    effects.append(('draw', params.get("count", 1)))
                elif kind == EffectKind.DESTROY:
                    effects.append(('destroy', True))
                elif kind == EffectKind.HEAL:
                    effects.append(('heal', params.get("amount", 0)))
                elif kind == EffectKind.ARMOR:
                    effects.append(('armor', params.get("amount", 0)))
                elif kind in (EffectKind.BUFF, EffectKind.HAND_BUFF):
                    atk = params.get("attack", 0)
                    hp = params.get("health", 0)
                    if atk > 0 and hp > 0:
                        effects.append(('hand_buff', (atk, hp)))
                    elif atk > 0:
                        effects.append(('buff_atk', atk))
                elif kind in (EffectKind.DISCARD,):
                    effects.append(('discard', params.get("count", 1)))
                elif kind in (EffectKind.REDUCE_COST,):
                    effects.append(('cost_reduce', params.get("amount", 0)))

        return effects

from __future__ import annotations

import re
from typing import Optional

from analysis.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, get_card_armor
from analysis.search.game_state import GameState, HeroState
from analysis.models.card import Card


class HeroCardHandler:
    _HERO_POWER_PATTERN_CN = re.compile(r"英雄技能[：:]\s*(.+?)(?:，|$)")
    _HERO_POWER_PATTERN_EN = re.compile(
        r"Hero\s+Power[：:]\s*(.+?)(?:[,.]|$)", re.IGNORECASE
    )

    def apply_hero_card(self, state: GameState, card: Card) -> GameState:
        s = state

        armor = self._parse_armor(card)
        s.hero.armor += armor

        hero_class = getattr(card, "card_class", "") or ""
        if hero_class:
            s.hero.hero_class = hero_class

        s.hero.hero_power_used = False
        s.hero.is_hero_card = True
        s.hero.imbue_level = 0

        self._update_hero_power(s, card)

        self._apply_hero_card_effects(s, card)

        return s

    def _parse_armor(self, card: Card) -> int:
        armor = get_card_armor(card)
        return armor if armor > 0 else 5

    def _update_hero_power(self, state: GameState, card: Card) -> None:
        text = getattr(card, "text", "") or ""

        m = _DAMAGE_CN.search(text) or _DAMAGE_EN.search(text)
        if m:
            state.hero.hero_power_damage = int(m.group(1))

        if "hero_power_cost" in text.lower() or "技能消耗" in text:
            cost_match = re.search(r"(?:cost|消耗)\s*(\d+)", text)
            if cost_match:
                state.hero.hero_power_cost = int(cost_match.group(1))

    def _apply_hero_card_effects(self, state: GameState, card: Card) -> None:
        text = getattr(card, "text", "") or ""

        if "Battlecry" in text or "战吼" in text:
            try:
                from analysis.search.battlecry_dispatcher import dispatch_battlecry

                dummy_minion = None
                state = dispatch_battlecry(state, card, dummy_minion)
            except Exception:
                pass

        try:
            from analysis.utils.spell_simulator import resolve_effects

            card_copy = Card(
                dbf_id=card.dbf_id,
                name=card.name,
                cost=card.cost,
                card_type=card.card_type,
                text="",
                mechanics=card.mechanics,
                card_class=card.card_class,
                rarity=card.rarity,
                race=card.race,
            )
            state = resolve_effects(state, card_copy)
        except Exception:
            pass

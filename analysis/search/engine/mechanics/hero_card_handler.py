from __future__ import annotations

import re
from typing import Optional

from analysis.search.game_state import GameState, HeroState
from analysis.models.card import Card


class HeroCardHandler:
    _ARMOR_PATTERN_CN = re.compile(r"获得\s*(\d+)\s*点护甲")
    _ARMOR_PATTERN_EN = re.compile(r"Gain\s*(\d+)\s*Armor", re.IGNORECASE)
    _HERO_POWER_PATTERN_CN = re.compile(r"英雄技能[：:]\s*(.+?)(?:，|$)")
    _HERO_POWER_PATTERN_EN = re.compile(
        r"Hero\s+Power[：:]\s*(.+?)(?:[,.]|$)", re.IGNORECASE
    )
    _DAMAGE_PATTERN_CN = re.compile(r"造成\s*\$?\s*(\d+)\s*点伤害")
    _DAMAGE_PATTERN_EN = re.compile(r"Deal\s*(\d+)\s*damage", re.IGNORECASE)

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
        armor = getattr(card, "armor", 0) or 0
        if armor > 0:
            return armor

        text = getattr(card, "text", "") or ""
        m = self._ARMOR_PATTERN_CN.search(text)
        if m:
            return int(m.group(1))
        m = self._ARMOR_PATTERN_EN.search(text)
        if m:
            return int(m.group(1))
        return 5

    def _update_hero_power(self, state: GameState, card: Card) -> None:
        text = getattr(card, "text", "") or ""

        m = self._DAMAGE_PATTERN_CN.search(text)
        if not m:
            m = self._DAMAGE_PATTERN_EN.search(text)
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

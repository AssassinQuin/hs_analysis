from __future__ import annotations

import re
from typing import Optional

try:
    from analysis.card.data.card_effects import _DAMAGE_CN, _DAMAGE_EN, get_card_armor
except ImportError:
    _DAMAGE_CN = _DAMAGE_EN = None

    def get_card_armor(card) -> int:
        """Fallback: parse armor from card text."""
        text = getattr(card, 'text', '') or ''
        en = getattr(card, 'english_text', '') or ''
        m = re.search(r'(\d+)\s*(?:点)?(?:护甲|Armor)', text) or \
            re.search(r'(\d+)\s*(?:点)?(?:护甲|Armor)', en)
        if m:
            return int(m.group(1))
        return 0
from analysis.card.engine.state import GameState, HeroState
from analysis.card.models.card import Card


class HeroCardHandler:
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
                from analysis.card.abilities.loader import load_abilities
                from analysis.card.engine.target import orchestrate

                abilities = load_abilities(card.card_id) if card.card_id else []
                state = orchestrate(state, card, abilities, {'source_minion': None})
            except Exception:
                pass

        try:
            from analysis.card.abilities.loader import load_abilities
            from analysis.card.engine.target import orchestrate

            card_copy_id = getattr(card_copy, 'card_id', '')
            abilities = load_abilities(card_copy_id) if card_copy_id else []
            state = orchestrate(state, card_copy, abilities, {'source_minion': None})
        except Exception:
            pass

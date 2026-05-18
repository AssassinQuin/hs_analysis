# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CardSighting:
    card_id: str = ""
    card_name: str = ""
    cost: int = 0
    cardClass: str = ""
    card_type: str = ""
    collectible: bool = False

    @property
    def is_class_card(self) -> bool:
        return self.cardClass not in ("NEUTRAL", "", "HERO")

    @property
    def is_neutral(self) -> bool:
        return self.cardClass == "NEUTRAL"


@dataclass
class DeckCard:
    card_id: str = ""
    name: str = ""
    cost: int = 0
    count: int = 1
    cardClass: str = ""
    card_type: str = ""
    rarity: str = ""
    collectible: bool = False

    @property
    def is_class_card(self) -> bool:
        return self.cardClass not in ("NEUTRAL", "", "HERO")

    @property
    def is_neutral(self) -> bool:
        return self.cardClass == "NEUTRAL"


@dataclass
class DeckInfo:
    name: str = ""
    deck_id: str = ""
    code: str = ""
    hero_class: str = ""
    hero_class_cn: str = ""
    cards: List[DeckCard] = field(default_factory=list)
    card_count: int = 0

    @classmethod
    def from_deck_code(cls, name: str, deck_id: str, code: str) -> "DeckInfo":
        d = cls(name=name, deck_id=deck_id, code=code)
        d._decode()
        return d

    def _decode(self):
        if self.cards:
            return
        try:
            from hearthstone.deckstrings import Deck
            deck = Deck.from_deckstring(self.code)
            hero_dbf = list(deck.heroes)[0] if deck.heroes else None

            from analysis.card.data.hsdb import get_db, get_hero_class_map
            from analysis.utils.hero_class import hero_dbf_to_class, class_to_cn
            hero_class_map = get_hero_class_map()
            db = get_db(load_xml=False, build_indexes=False)

            self.hero_class = "UNKNOWN"
            if hero_dbf is not None:
                self.hero_class = hero_class_map.get(hero_dbf, "")
                if not self.hero_class:
                    hero_card = db.get_by_dbf(hero_dbf)
                    if hero_card:
                        self.hero_class = hero_card.get("cardClass", "UNKNOWN").upper()
            self.hero_class_cn = class_to_cn(self.hero_class)

            for dbf_id, count in deck.cards:
                card = db.get_by_dbf(dbf_id)
                if card:
                    self.cards.append(DeckCard(
                        card_id=card["cardId"],
                        name=card.get("name", card["cardId"]),
                        cost=card.get("cost", 0),
                        count=count,
                        cardClass=card.get("cardClass", ""),
                        card_type=card.get("type", ""),
                        rarity=card.get("rarity", ""),
                        collectible=card.get("collectible", False),
                    ))
                else:
                    self.cards.append(DeckCard(
                        card_id=f"dbf:{dbf_id}",
                        name=f"Unknown(dbf:{dbf_id})",
                        count=count,
                    ))

            self.card_count = sum(c.count for c in self.cards)
        except Exception as e:
            self.hero_class = "ERROR"
            self.hero_class_cn = f"解码失败: {e}"

    @property
    def cards_sorted_by_cost(self) -> List[DeckCard]:
        return sorted(self.cards, key=lambda c: (c.cost, c.name))

    @property
    def class_cards(self) -> List[DeckCard]:
        return [c for c in self.cards if c.is_class_card]

    @property
    def neutral_cards(self) -> List[DeckCard]:
        return [c for c in self.cards if c.is_neutral]


@dataclass
class PlayerInfo:
    name: str = ""
    player_id: int = 0
    hero_card_id: str = ""
    hero_class: str = ""
    hero_class_cn: str = ""
    is_me: bool = False
    account_lo: str = ""
    deck: Optional[DeckInfo] = None
    played_cards: List[CardSighting] = field(default_factory=list)

    @property
    def collectible_played(self) -> List[CardSighting]:
        return [c for c in self.played_cards if c.collectible]

    @property
    def class_played(self) -> List[CardSighting]:
        return sorted(
            [c for c in self.played_cards if c.is_class_card],
            key=lambda c: (c.cost, c.card_name),
        )

    @property
    def neutral_played(self) -> List[CardSighting]:
        return sorted(
            [c for c in self.played_cards if c.is_neutral],
            key=lambda c: (c.cost, c.card_name),
        )


@dataclass
class GameRecord:
    game_index: int = 0
    me: PlayerInfo = field(default_factory=PlayerInfo)
    opponent: PlayerInfo = field(default_factory=PlayerInfo)
    result: str = "UNKNOWN"

    @property
    def won(self) -> bool:
        return self.result == "WON"

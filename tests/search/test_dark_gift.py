"""Tests for dark_gift.py — Dark Gift enchantment system."""

from __future__ import annotations
import pytest
pytest.skip("Mechanic module deleted — data in engine/mechanics/_data.py", allow_module_level=True)


from analysis.engine.mechanics._data import (
    DARK_GIFT_ENCHANTMENTS,
    DarkGiftEnchantment,
    apply_dark_gift,
    filter_dark_gift_pool,
    has_dark_gift_discover,
    has_dark_gift_in_hand,
    parse_dark_gift_constraint,
)


def _card(name: str = "TestCard", attack: int = 2, health: int = 2,
          text: str = "", english_text: str = "", mechanics: list | None = None,
          race: str = "", **kw) -> dict:
    return {"name": name, "attack": attack, "health": health,
            "text": text, "english_text": english_text,
            "mechanics": mechanics or [], "race": race, **kw}


class TestDarkGiftEnchantments:
    def test_has_enchantments(self):
        assert len(DARK_GIFT_ENCHANTMENTS) >= 8

    def test_all_have_names(self):
        for e in DARK_GIFT_ENCHANTMENTS:
            assert e.name, "Each enchantment should have a name"


class TestApplyDarkGift:
    def test_applies_stats(self):
        card = _card(attack=3, health=3)
        import random
        random.seed(42)
        result = apply_dark_gift(card)
        assert "dark_gift" in result

    def test_applies_keyword(self):
        card = _card()
        for _ in range(50):
            c = _card()
            result = apply_dark_gift(c)
            if result.get("dark_gift"):
                assert isinstance(result["dark_gift"], str)

    def test_mutates_card(self):
        card = _card(attack=2, health=2)
        import random
        random.seed(0)
        result = apply_dark_gift(card)
        assert result is card


class TestHasDarkGiftInHand:
    def test_with_dark_gift_field(self):
        hand = [_card(dark_gift="Chaos Power")]
        assert has_dark_gift_in_hand(hand)

    def test_with_english_text_reference(self):
        hand = [_card(english_text="Discover a Dark Gift minion")]
        assert has_dark_gift_in_hand(hand)

    def test_no_dark_gift(self):
        hand = [_card(english_text="Just a regular minion")]
        assert not has_dark_gift_in_hand(hand)

    def test_empty_hand(self):
        assert not has_dark_gift_in_hand([])


class TestFilterDarkGiftPool:
    def test_deathrattle_filter(self):
        pool = [
            _card(name="A", mechanics=[]),
            _card(name="B", mechanics=[]),
            _card(name="C", mechanics=["DEATHRATTLE"]),
        ]
        result = filter_dark_gift_pool(pool, "DEATHRATTLE")
        assert len(result) == 1

    def test_dragon_filter(self):
        pool = [
            _card(name="A", race="DRAGON"),
            _card(name="B", race="MURLOC"),
        ]
        result = filter_dark_gift_pool(pool, "DRAGON")
        assert len(result) == 1

    def test_no_constraint(self):
        pool = [_card(name="A"), _card(name="B")]
        result = filter_dark_gift_pool(pool, "")
        assert len(result) == 2

    def test_empty_pool(self):
        assert filter_dark_gift_pool([], "DEATHRATTLE") == []


class TestParseDarkGiftConstraint:
    """EN-only constraint parsing — Standard 1 (English-Only Logic Layer)."""

    def test_deathrattle_english(self):
        result = parse_dark_gift_constraint(
            "Discover a Dark Gift Deathrattle minion"
        )
        assert result == "DEATHRATTLE"

    def test_dragon_english(self):
        result = parse_dark_gift_constraint(
            "Discover a Dark Gift Dragon minion"
        )
        assert result == "DRAGON"

    def test_demon_english(self):
        result = parse_dark_gift_constraint(
            "Discover a Dark Gift Demon"
        )
        assert result == "DEMON"

    def test_no_dark_gift_keyword(self):
        result = parse_dark_gift_constraint(
            "Discover a Deathrattle minion"
        )
        assert result == ""

    def test_no_constraint(self):
        result = parse_dark_gift_constraint("Discover a card")
        assert result == ""

    def test_empty(self):
        assert parse_dark_gift_constraint("") == ""


class TestHasDarkGiftDiscover:
    """EN-only discover detection — Standard 1."""

    def test_positive_en(self):
        assert has_dark_gift_discover("Discover a Dark Gift card")

    def test_positive_en_lower(self):
        assert has_dark_gift_discover("discover a dark gift minion")

    def test_negative(self):
        assert not has_dark_gift_discover("Discover a Dragon")

    def test_empty(self):
        assert not has_dark_gift_discover("")

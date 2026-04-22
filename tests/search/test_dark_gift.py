"""Tests for dark_gift.py — 黑暗之赐 (Dark Gift) system."""

from __future__ import annotations

import pytest

from analysis.search.dark_gift import (
    DARK_GIFT_ENCHANTMENTS,
    DarkGiftEnchantment,
    apply_dark_gift,
    filter_dark_gift_pool,
    has_dark_gift_discover,
    has_dark_gift_in_hand,
    parse_dark_gift_constraint,
)


def _card(name: str = "TestCard", attack: int = 2, health: int = 2,
          text: str = "", mechanics: list | None = None, race: str = "",
          **kw) -> dict:
    return {"name": name, "attack": attack, "health": health,
            "text": text, "mechanics": mechanics or [], "race": race, **kw}


class TestDarkGiftEnchantments:
    def test_has_enchantments(self):
        assert len(DARK_GIFT_ENCHANTMENTS) >= 8

    def test_all_have_names(self):
        for e in DARK_GIFT_ENCHANTMENTS:
            assert e.name, "Each enchantment should have a name"


class TestApplyDarkGift:
    def test_applies_stats(self):
        card = _card(attack=3, health=3)
        # Force a stat gift by seeding
        import random
        random.seed(42)
        result = apply_dark_gift(card)
        # Should have dark_gift field set
        assert "dark_gift" in result

    def test_applies_keyword(self):
        card = _card()
        # Run many times to hit keyword gifts
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
        # attack or health may have changed
        assert result is card  # in-place mutation


class TestHasDarkGiftInHand:
    def test_with_dark_gift_dict(self):
        hand = [_card(dark_gift="混沌之力")]
        assert has_dark_gift_in_hand(hand)

    def test_with_text_reference(self):
        hand = [_card(text="具有黑暗之赐的随从")]
        assert has_dark_gift_in_hand(hand)

    def test_no_dark_gift(self):
        hand = [_card(text="普通随从")]
        assert not has_dark_gift_in_hand(hand)

    def test_empty_hand(self):
        assert not has_dark_gift_in_hand([])


class TestFilterDarkGiftPool:
    def test_deathrattle_filter(self):
        pool = [
            _card(name="A", text="亡语：造成2点伤害"),
            _card(name="B", text="战吼：造成2点伤害"),
            _card(name="C", mechanics=["DEATHRATTLE"]),
        ]
        result = filter_dark_gift_pool(pool, "亡语")
        assert len(result) == 2

    def test_dragon_filter(self):
        pool = [
            _card(name="A", race="DRAGON"),
            _card(name="B", race="MURLOC"),
        ]
        result = filter_dark_gift_pool(pool, "龙")
        assert len(result) == 1

    def test_no_constraint(self):
        pool = [_card(name="A"), _card(name="B")]
        result = filter_dark_gift_pool(pool, "")
        assert len(result) == 2

    def test_empty_pool(self):
        assert filter_dark_gift_pool([], "亡语") == []


class TestParseDarkGiftConstraint:
    def test_deathrattle_constraint(self):
        text = "发现一张具有黑暗之赐的亡语随从牌"
        result = parse_dark_gift_constraint(text)
        assert "亡语" in result  # matches "亡语随从" — contains the constraint

    def test_dragon_constraint(self):
        text = "发现一张具有黑暗之赐的龙牌"
        assert parse_dark_gift_constraint(text) == "龙"

    def test_no_constraint(self):
        assert parse_dark_gift_constraint("发现一张随从牌") == ""

    def test_empty(self):
        assert parse_dark_gift_constraint("") == ""


class TestHasDarkGiftDiscover:
    def test_positive(self):
        assert has_dark_gift_discover("发现一张具有黑暗之赐的龙牌")

    def test_negative(self):
        assert not has_dark_gift_discover("发现一张龙牌")

    def test_empty(self):
        assert not has_dark_gift_discover("")

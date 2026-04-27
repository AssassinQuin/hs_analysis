# -*- coding: utf-8 -*-
"""验证 CardDB 中卡牌字典包含完整字段。

T1.1 修复了 _load_hsjson() 非收集卡字段丢失问题，补全了
referencedTags, spellDamage, overload, spellSchool, races, englishText 字段。
本模块通过回归测试确保可收集卡和非收集卡均包含完整的预期字段。
"""

from __future__ import annotations

import pytest

from analysis.card.data.card_data import get_db

# 可收集卡和非收集卡均应包含的字段集合
EXPECTED_FIELDS = {
    "dbfId", "cardId", "name", "englishName", "englishText",
    "cost", "attack", "health", "durability", "armor",
    "type", "cardClass", "race", "races", "rarity",
    "spellSchool", "spellDamage", "overload",
    "mechanics", "referencedTags",
    "text", "set", "collectible",
}

# 已知可收集卡：饥饿的蝙蝠
_COLLECTIBLE_CARD_ID = "EX1_006"

# 已知非收集卡：野猪（肯瑞托法师的召唤 token），mechanics=['CHARGE']
_NON_COLLECTIBLE_CARD_ID = "AT_005t"


@pytest.fixture(scope="module")
def db():
    """CardDB 单例，module 级别复用。"""
    return get_db()


@pytest.fixture(scope="module")
def collectible_card(db):
    """获取一张已知可收集卡的原始字典。"""
    card = db.get_card(_COLLECTIBLE_CARD_ID)
    if card is None:
        pytest.skip(f"可收集卡 {_COLLECTIBLE_CARD_ID} 不在数据库中")
    return card


@pytest.fixture(scope="module")
def non_collectible_card(db):
    """获取一张已知非收集卡（token）的原始字典。"""
    card = db._cards.get(_NON_COLLECTIBLE_CARD_ID)
    if card is None:
        pytest.skip(f"非收集卡 {_NON_COLLECTIBLE_CARD_ID} 不在数据库中")
    return card


def test_collectible_card_has_all_fields(collectible_card):
    """验证可收集卡字典包含所有预期字段。"""
    missing = EXPECTED_FIELDS - set(collectible_card.keys())
    assert not missing, (
        f"可收集卡 {_COLLECTIBLE_CARD_ID} 缺少字段: {missing}"
    )


def test_non_collectible_card_has_all_fields(non_collectible_card):
    """验证非收集卡字典包含所有预期字段（含 referencedTags, spellDamage 等）。"""
    missing = EXPECTED_FIELDS - set(non_collectible_card.keys())
    assert not missing, (
        f"非收集卡 {_NON_COLLECTIBLE_CARD_ID} 缺少字段: {missing}"
    )


def test_non_collectible_mechanics_field(non_collectible_card):
    """验证非收集卡的 mechanics 字段为列表类型。"""
    mechanics = non_collectible_card.get("mechanics")
    assert isinstance(mechanics, list), (
        f"非收集卡 {_NON_COLLECTIBLE_CARD_ID} 的 mechanics 应为 list，"
        f"实际为 {type(mechanics).__name__}"
    )

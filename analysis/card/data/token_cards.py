"""token_cards.py — Token 卡牌数据接口。

所有 token（衍生物）和随机随从数据均从 CardDB 动态加载，
不再使用硬编码字典。CardDB 的 _load_hsjson() 会从 cards.json
加载全部非收集卡（含 token、附魔、英雄技能等）。
"""
from __future__ import annotations

import random


def get_token(card_id: str) -> dict | None:
    """从 CardDB 获取 token 卡牌数据。

    部分 token 需要补充自定义触发器字段（trigger_type/trigger_effect），
    这些字段不在 HearthstoneJSON 原始数据中。

    Args:
        card_id: 卡牌 ID（如 "CS2_124t" 麦田傀儡的亡语 token）。

    Returns:
        卡牌字典，包含 name/cost/attack/health/type 等字段；
        不存在时返回 None。
    """
    from analysis.card.data.card_data import get_db

    data = get_db().get_card(card_id)
    if data is None:
        return None

    # 补充自定义触发器字段（模拟引擎需要但 JSON 中没有）
    _TOKEN_TRIGGERS = {
        "CATA_527t2": {
            "trigger_type": "ON_FEL_SPELL_CAST",
            "trigger_effect": "ADD_RANDOM_NAGA",
        },
    }
    extra = _TOKEN_TRIGGERS.get(card_id)
    if extra:
        data = {**data, **extra}

    return data


def get_random_naga(max_cost: int = 99) -> dict:
    """从 CardDB 获取随机娜迦随从数据。

    优先从收集卡中筛选费用 <= max_cost 的娜迦随从；
    若无匹配则回退到全部娜迦随从；最终兜底返回占位数据。

    Args:
        max_cost: 费用上限（默认 99，不过滤）。

    Returns:
        娜迦随从卡牌字典，至少包含 name/cost/attack/health 字段。
    """
    from analysis.card.data.card_data import get_db

    db = get_db()
    # 使用收集卡池按 race=NAGA 过滤
    naga_cards = [
        c
        for c in db.get_collectible_cards()
        if c.get("race", "").upper() == "NAGA" and c.get("cost", 99) <= max_cost
    ]
    if not naga_cards:
        naga_cards = [
            c
            for c in db.get_collectible_cards()
            if c.get("race", "").upper() == "NAGA"
        ]
    if naga_cards:
        return random.choice(naga_cards)
    return {"name": "Naga", "cost": 2, "attack": 1, "health": 1}


def create_naga_card(naga_data: dict) -> object:
    """Create a Card-like object from naga data for hand insertion."""
    from analysis.card.models.card import Card

    return Card(
        card_id="TOKEN_NAGA",
        name=naga_data.get("name", "Naga"),
        cost=naga_data.get("cost", 2),
        original_cost=naga_data.get("cost", 2),
        card_type="MINION",
        attack=naga_data.get("attack", 1),
        health=naga_data.get("health", 1),
        race="NAGA",
    )

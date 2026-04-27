"""test_token_loading.py — Token 卡牌从 CardDB 加载的测试。

验证 token_cards.py 的公共 API（get_token / get_random_naga / create_naga_card）
均从 CardDB 动态加载数据，不再依赖硬编码字典。
"""
from __future__ import annotations

import pytest

from analysis.card.data.token_cards import create_naga_card, get_random_naga, get_token


class TestGetToken:
    """get_token() 从 CardDB 获取非收集卡。"""

    def test_get_token_from_carddb(self):
        """get_token() 应返回非收集卡的完整字典。"""
        # CATA_527t2 = 奈瑟匹拉，脱困古灵 (6/6 NAGA token)
        token = get_token("CATA_527t2")
        assert token is not None
        assert token.get("type", "").upper() == "MINION"

    def test_get_token_nonexistent(self):
        """不存在的 card_id 应返回 None。"""
        token = get_token("NONEXISTENT_CARD_12345")
        assert token is None

    def test_token_has_complete_fields(self):
        """token 卡牌应包含 attack/health/cost/type 等关键字段。"""
        token = get_token("CATA_527t2")
        assert token is not None
        for field in ("attack", "health", "cost", "type", "name"):
            assert field in token, f"token 缺少字段: {field}"
        # mechanics 可能不存在，安全访问
        mechanics = token.get("mechanics", [])
        assert isinstance(mechanics, list)


class TestGetRandomNaga:
    """get_random_naga() 从 CardDB 获取随机娜迦。"""

    def test_get_random_naga_from_carddb(self):
        """get_random_naga() 应返回有效的娜迦随从数据。"""
        naga = get_random_naga()
        assert naga is not None
        assert "name" in naga
        assert naga.get("name", "") != ""

    def test_get_random_naga_with_cost_filter(self):
        """带费用过滤的娜迦查询应返回合法结果或回退到全部娜迦。"""
        naga = get_random_naga(max_cost=1)
        assert naga is not None
        assert "name" in naga

    def test_get_random_naga_fallback(self):
        """兜底情况应返回至少包含 name/cost/attack/health 的字典。"""
        # max_cost=0 很可能无匹配，测试回退逻辑
        naga = get_random_naga(max_cost=0)
        assert naga is not None
        assert "name" in naga


class TestCreateNagaCard:
    """create_naga_card() 从字典创建 Card 对象。"""

    def test_create_naga_card(self):
        """应创建字段正确的 Card 对象。"""
        data = {"name": "测试娜迦", "cost": 3, "attack": 3, "health": 4}
        card = create_naga_card(data)
        assert card is not None
        assert card.name == "测试娜迦"
        assert card.cost == 3
        assert card.original_cost == 3
        assert card.attack == 3
        assert card.health == 4
        assert card.card_type == "MINION"
        assert card.race == "NAGA"
        assert card.card_id == "TOKEN_NAGA"

    def test_create_naga_card_defaults(self):
        """缺少字段时应使用默认值。"""
        card = create_naga_card({})
        assert card.name == "Naga"
        assert card.cost == 2
        assert card.attack == 1
        assert card.health == 1

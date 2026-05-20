"""abilities/loader_v2.py — v2 JSON 加载器。

将 card_abilities_v2.json（或 v1 格式）加载为 CardAbility 对象，
并绑定到 Card 模型上。

不同于 loader.py（加载旧版 card_abilities.json 的 AbilityTrigger/EffectSpec 格式），
此模块加载 v2 SpellDesc 递归 JSON 格式。

用法:
    loader = AbilityLoader()
    ability = loader.load_from_json(json_data)
    card.ability = ability   # v2 挂载点
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from analysis.card.abilities.model import CardAbility, SpellDesc
from analysis.card.abilities.registry import init_all

if TYPE_CHECKING:
    from analysis.card.models.card import Card

log = logging.getLogger(__name__)


class AbilityLoader:
    """v2 JSON 加载器。

    支持从 JSON 文件或 dict 加载 CardAbility。
    """

    def __init__(self, file_path: Optional[str] = None):
        init_all()
        self._cache: Dict[str, CardAbility] = {}
        # 自动从默认路径预加载
        if file_path:
            self.load_from_file(file_path)
        else:
            from analysis.card.abilities.generator_v2 import _DEFAULT_OUTPUT
            default = str(_DEFAULT_OUTPUT)
            if Path(default).exists():
                self.load_from_file(default)

    # ── 加载 v2 JSON ──

    def load_from_dict(self, data: dict) -> CardAbility:
        """从 dict 解析 CardAbility。"""
        return CardAbility.from_json(data)

    def load_from_file(self, path: str) -> Dict[str, CardAbility]:
        """从 JSON 文件加载所有卡牌的 CardAbility。

        文件格式: {"card_id": {...ability json...}, ...}
        """
        path_obj = Path(path)
        if not path_obj.exists():
            log.warning("能力 JSON 文件不存在: %s", path)
            return {}

        with open(path_obj, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        result: Dict[str, CardAbility] = {}
        for card_id, ability_data in raw.items():
            if not isinstance(ability_data, dict):
                continue
            try:
                result[card_id] = self.load_from_dict(ability_data)
            except (ValueError, TypeError, KeyError) as e:
                log.warning("加载卡牌 %s 能力失败: %s", card_id, e)
                result[card_id] = CardAbility.empty()

        self._cache.update(result)
        log.info("从 %s 加载了 %d 张卡牌的能力", path, len(result))
        return result

    # ── 加载 v1 兼容 ──

    def load_from_v1_file(self, path: str) -> Dict[str, CardAbility]:
        """从 v1 card_abilities.json 加载为 v2 格式。

        v1 格式: {"card_id": {"name": ..., "actions": [...]}}
        v2 要求: {"card_id": {"ON_PLAY": {"class": ...}}}
        """
        path_obj = Path(path)
        if not path_obj.exists():
            return {}

        from analysis.card.abilities.generator_v2 import generate_card_ability_v2

        with open(path_obj, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        result: Dict[str, CardAbility] = {}
        for card_id, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            try:
                v2_data = generate_card_ability_v2(entry)
                result[card_id] = self.load_from_dict(v2_data)
            except Exception as e:
                log.warning("v1→v2 转换 %s 失败: %s", card_id, e)
                result[card_id] = CardAbility.empty()
        return result

    # ── 绑定到 Card ──

    def bind_to_card(self, card: "Card", ability_data: dict) -> "Card":
        """将 CardAbility 绑定到 Card 实例。

        使用 v2 挂载点 `card.ability`（即 CardAbility 对象）。
        """
        card.ability = self.load_from_dict(ability_data)
        return card

    def bind_from_file(self, card: "Card", db_path: str) -> "Card":
        """从 JSON 文件按 card_id 查找并绑定能力。"""
        if card.card_id in self._cache:
            card.ability = self._cache[card.card_id]
            return card

        # 从文件延迟加载
        abilities = self.load_from_file(db_path)
        if card.card_id in abilities:
            card.ability = abilities[card.card_id]
        else:
            card.ability = CardAbility.empty()

        return card

    # ── 加载旧版 generator 输出 ──

    def load_from_generator(self, generator_module=None) -> Dict[str, CardAbility]:
        """从 generator 的 _MECHANIC_HANDLERS 加载（无 JSON 文件时）。"""
        from analysis.card.abilities.generator import CARD_ABILITIES_V2

        result: Dict[str, CardAbility] = {}
        for card_id, v2_data in CARD_ABILITIES_V2.items():
            try:
                result[card_id] = self.load_from_dict(v2_data)
            except Exception:
                result[card_id] = CardAbility.empty()
        return result

    def get(self, card_id: str) -> CardAbility:
        """从缓存获取 CardAbility。"""
        return self._cache.get(card_id, CardAbility.empty())


# 全局 loader（延迟初始化）
_GLOBAL_LOADER: Optional[AbilityLoader] = None


def get_loader_v2() -> AbilityLoader:
    global _GLOBAL_LOADER
    if _GLOBAL_LOADER is None:
        _GLOBAL_LOADER = AbilityLoader()
    return _GLOBAL_LOADER

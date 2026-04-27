#!/usr/bin/env python3
"""test_ability_loader.py — 验证 loader.py 新格式支持和 Spell 反射加载。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.card.abilities.loader import load_card_power, load_card_spells
from analysis.card.abilities.spells import (
    SPELL_REGISTRY,
    BuffSpell,
    ConditionalSpell,
    DamageSpell,
    DrawSpell,
    HealSpell,
    MetaSpell,
    NoOpSpell,
    Spell,
    SummonSpell,
)


# ═══════════════════════════════════════════════════════════════
# SPELL_REGISTRY 验证
# ═══════════════════════════════════════════════════════════════

class TestSpellRegistry:

    def test_spell_registry_has_core_spells(self):
        """验证 SPELL_REGISTRY 包含核心 Spell 类名。"""
        core_names = [
            "DamageSpell",
            "HealSpell",
            "SummonSpell",
            "BuffSpell",
            "DrawSpell",
            "MetaSpell",
            "ConditionalSpell",
        ]
        for name in core_names:
            assert name in SPELL_REGISTRY, f"SPELL_REGISTRY 缺少 {name}"


# ═══════════════════════════════════════════════════════════════
# Spell.from_dict() 测试
# ═══════════════════════════════════════════════════════════════

class TestSpellFromDict:

    def test_spell_from_dict_damage(self):
        """测试 DamageSpell 从 dict 正确构造。"""
        data = {"class": "DamageSpell", "value": 6, "target": "TARGET"}
        spell = Spell.from_dict(data)
        assert isinstance(spell, DamageSpell)

    def test_meta_spell_from_dict(self):
        """测试 MetaSpell 组合 — 包含 DrawSpell 和 BuffSpell 子效果。"""
        data = {
            "class": "MetaSpell",
            "spells": [
                {"class": "DrawSpell", "count": 2},
                {"class": "BuffSpell", "attack": 1, "target": "FRIENDLY_MINIONS"},
            ],
        }
        spell = Spell.from_dict(data)
        assert isinstance(spell, MetaSpell)

    def test_unknown_spell_returns_noop(self):
        """测试未知类名返回 NoOpSpell 而不是抛异常。"""
        data = {"class": "NonExistentSpell", "value": 42}
        spell = Spell.from_dict(data)
        assert isinstance(spell, NoOpSpell)


# ═══════════════════════════════════════════════════════════════
# Loader 函数测试
# ═══════════════════════════════════════════════════════════════

class TestLoaderFunctions:

    def test_loader_returns_empty_when_no_json(self, monkeypatch, tmp_path):
        """测试 JSON 文件不存在时返回空列表。"""
        # 使用不存在的路径覆盖 _JSON_PATH
        from analysis.card.abilities import loader as loader_mod
        fake_path = tmp_path / "nonexistent_card_abilities.json"
        monkeypatch.setattr(loader_mod, "_JSON_PATH", fake_path)
        # 重置缓存
        monkeypatch.setattr(loader_mod, "_cache", None)
        result = load_card_spells("EX1_066")
        assert result == []

    def test_loader_can_parse_new_format(self, monkeypatch, tmp_path):
        """测试加载 MetaStone 新格式 JSON（version=1）。"""
        # 构造临时 JSON 文件
        json_data = {
            "version": 1,
            "cards": {
                "EX1_066": {
                    "name": "疯狂投弹手",
                    "abilities": [
                        {
                            "trigger": "BATTLECRY",
                            "actions": [
                                {
                                    "class": "DamageSpell",
                                    "value": 3,
                                    "target": "RANDOM_ENEMY_CHARACTER",
                                }
                            ],
                        }
                    ],
                }
            },
        }
        json_file = tmp_path / "card_abilities.json"
        json_file.write_text(json.dumps(json_data, ensure_ascii=False), encoding="utf-8")

        # 注入临时路径
        from analysis.card.abilities import loader as loader_mod
        monkeypatch.setattr(loader_mod, "_JSON_PATH", json_file)
        monkeypatch.setattr(loader_mod, "_cache", None)

        # 验证 load_card_spells 返回正确 Spell 实例
        spells = load_card_spells("EX1_066")
        assert len(spells) == 1
        assert isinstance(spells[0], DamageSpell)

        # 验证 load_card_power 返回完整定义
        power = load_card_power("EX1_066")
        assert power["name"] == "疯狂投弹手"
        assert len(power["abilities"]) == 1
        assert power["abilities"][0]["trigger"] == "BATTLECRY"

    def test_loader_returns_empty_for_unknown_card(self, monkeypatch, tmp_path):
        """测试查询不存在的卡牌返回空列表。"""
        json_data = {"version": 1, "cards": {}}
        json_file = tmp_path / "card_abilities.json"
        json_file.write_text(json.dumps(json_data), encoding="utf-8")

        from analysis.card.abilities import loader as loader_mod
        monkeypatch.setattr(loader_mod, "_JSON_PATH", json_file)
        monkeypatch.setattr(loader_mod, "_cache", None)

        spells = load_card_spells("UNKNOWN_CARD")
        assert spells == []

        power = load_card_power("UNKNOWN_CARD")
        assert power == {}

#!/usr/bin/env python3
"""test_power.py — CardPower 加载与缓存测试。

测试内容:
- 空能力卡牌
- 从 JSON 构建 CardPower
- 便捷属性（has_battlecry / has_deathrattle 等）
- 触发器分组
- Card.power 延迟加载
- Card.has_battlecry 从 mechanics 判断
- repr 格式
- 从临时 JSON 文件完整加载链路
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from analysis.card.abilities.power import CardPower, TriggerDef, AuraDef, EnchantDef
from analysis.card.abilities.spells import Spell


# ═══════════════════════════════════════════════════════════════
# T4.1 测试: CardPower 基础功能
# ═══════════════════════════════════════════════════════════════


class TestCardPowerEmpty:
    """空能力卡牌测试。"""

    def test_card_power_empty(self):
        """空 CardPower 的 is_empty 为 True，所有 has_X 为 False。"""
        power = CardPower(card_id="EMPTY")
        assert power.is_empty
        assert not power.has_battlecry
        assert not power.has_deathrattle
        assert not power.has_combo
        assert not power.has_spellburst
        assert not power.has_outcast
        assert not power.has_frenzy
        assert not power.has_inspire
        assert not power.has_on_play
        assert not power.has_triggers
        assert not power.has_aura
        assert not power.has_enchant

    def test_card_power_with_spell_not_empty(self):
        """有 Spell 的 CardPower 的 is_empty 为 False。"""
        spell = Spell.from_dict({"class": "DamageSpell", "value": 3})
        power = CardPower(card_id="TEST", battlecry=[spell])
        assert not power.is_empty


class TestCardPowerFromAbilitiesJson:
    """从 abilities JSON 数组构建 CardPower 测试。"""

    def test_card_power_from_abilities_json_battlecry_deathrattle(self):
        """从 JSON 构建，正确分组 battlecry 和 deathrattle。"""
        abilities_data = [
            {
                "trigger": "BATTLECRY",
                "actions": [
                    {"class": "DamageSpell", "value": 3, "target": "RANDOM_ENEMY_CHARACTER"}
                ],
            },
            {
                "trigger": "DEATHRATTLE",
                "actions": [
                    {"class": "SummonSpell", "card_id": "EX1_110t"}
                ],
            },
        ]
        power = CardPower.from_abilities_json("EX1_110", abilities_data)
        assert power.card_id == "EX1_110"
        assert power.has_battlecry
        assert power.has_deathrattle
        assert len(power.battlecry) == 1
        assert len(power.deathrattle) == 1
        # 验证 Spell 类型
        from analysis.card.abilities.spells import DamageSpell, SummonSpell
        assert isinstance(power.battlecry[0], DamageSpell)
        assert isinstance(power.deathrattle[0], SummonSpell)

    def test_card_power_from_abilities_json_combo(self):
        """从 JSON 构建 combo 能力。"""
        abilities_data = [
            {
                "trigger": "COMBO",
                "actions": [
                    {"class": "DrawSpell", "count": 2}
                ],
            }
        ]
        power = CardPower.from_abilities_json("TEST_COMBO", abilities_data)
        assert power.has_combo
        assert len(power.combo) == 1

    def test_card_power_from_abilities_json_spellburst(self):
        """从 JSON 构建 spellburst 能力。"""
        abilities_data = [
            {
                "trigger": "SPELLBURST",
                "actions": [
                    {"class": "BuffSpell", "attack": 1, "target": "FRIENDLY_MINIONS"}
                ],
            }
        ]
        power = CardPower.from_abilities_json("TEST_SB", abilities_data)
        assert power.has_spellburst
        assert len(power.spellburst) == 1

    def test_card_power_from_abilities_json_on_play(self):
        """从 JSON 构建 ON_PLAY（法术主效果）。"""
        abilities_data = [
            {
                "trigger": "ON_PLAY",
                "actions": [
                    {"class": "HealSpell", "value": 5, "target": "FRIENDLY_HERO"}
                ],
            }
        ]
        power = CardPower.from_abilities_json("TEST_SPELL", abilities_data)
        assert power.has_on_play
        assert len(power.on_play) == 1

    def test_card_power_from_abilities_json_empty(self):
        """空 abilities_data 返回空 CardPower。"""
        power = CardPower.from_abilities_json("EMPTY", [])
        assert power.is_empty

    def test_card_power_unknown_trigger_fallback(self):
        """未知触发器归入 on_play。"""
        abilities_data = [
            {
                "trigger": "UNKNOWN_TRIGGER",
                "actions": [
                    {"class": "DamageSpell", "value": 1}
                ],
            }
        ]
        power = CardPower.from_abilities_json("TEST_UNKNOWN", abilities_data)
        # 未知触发器应归入 on_play
        assert power.has_on_play
        assert len(power.on_play) == 1


# ═══════════════════════════════════════════════════════════════
# T4.1 测试: 便捷属性
# ═══════════════════════════════════════════════════════════════


class TestCardPowerConvenienceProperties:
    """便捷属性测试 — 验证所有 has_X 属性。"""

    def test_has_battlecry(self):
        """has_battlecry 正确反映 battlecry 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_battlecry
        power.battlecry.append(Spell.from_dict({"class": "DamageSpell", "value": 1}))
        assert power.has_battlecry

    def test_has_deathrattle(self):
        """has_deathrattle 正确反映 deathrattle 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_deathrattle
        power.deathrattle.append(Spell.from_dict({"class": "SummonSpell", "card_id": "X"}))
        assert power.has_deathrattle

    def test_has_combo(self):
        """has_combo 正确反映 combo 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_combo
        power.combo.append(Spell.from_dict({"class": "DrawSpell", "count": 1}))
        assert power.has_combo

    def test_has_spellburst(self):
        """has_spellburst 正确反映 spellburst 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_spellburst
        power.spellburst.append(Spell.from_dict({"class": "BuffSpell", "attack": 1}))
        assert power.has_spellburst

    def test_has_outcast(self):
        """has_outcast 正确反映 outcast 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_outcast
        power.outcast.append(Spell.from_dict({"class": "DrawSpell", "count": 1}))
        assert power.has_outcast

    def test_has_frenzy(self):
        """has_frenzy 正确反映 frenzy 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_frenzy
        power.frenzy.append(Spell.from_dict({"class": "BuffSpell", "attack": 2}))
        assert power.has_frenzy

    def test_has_on_play(self):
        """has_on_play 正确反映 on_play 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_on_play
        power.on_play.append(Spell.from_dict({"class": "HealSpell", "value": 3}))
        assert power.has_on_play

    def test_has_triggers(self):
        """has_triggers 正确反映 triggers 列表状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_triggers
        power.triggers.append(TriggerDef(trigger_type="TURN_START"))
        assert power.has_triggers

    def test_has_aura(self):
        """has_aura 正确反映 aura 字段状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_aura
        power.aura = AuraDef(target="FRIENDLY_MINIONS", attack=1)
        assert power.has_aura

    def test_has_enchant(self):
        """has_enchant 正确反映 enchant 字段状态。"""
        power = CardPower(card_id="TEST")
        assert not power.has_enchant
        power.enchant = EnchantDef(attack=1, health=1)
        assert power.has_enchant


# ═══════════════════════════════════════════════════════════════
# T4.1 测试: 触发器分组
# ═══════════════════════════════════════════════════════════════


class TestCardPowerTriggerGrouping:
    """触发器分组测试 — TURN_START / ON_DAMAGE 等归入 triggers。"""

    def test_card_power_trigger_grouping(self):
        """TURN_START 和 ON_DAMAGE 归入 triggers 列表。"""
        abilities_data = [
            {
                "trigger": "TURN_START",
                "actions": [{"class": "DrawSpell", "count": 1}],
            },
            {
                "trigger": "ON_DAMAGE",
                "actions": [{"class": "BuffSpell", "attack": 1, "target": "SELF"}],
            },
        ]
        power = CardPower.from_abilities_json("TEST", abilities_data)
        assert power.has_triggers
        assert len(power.triggers) == 2
        assert power.triggers[0].trigger_type == "TURN_START"
        assert power.triggers[1].trigger_type == "ON_DAMAGE"

    def test_trigger_with_condition(self):
        """触发器支持 condition 字段。"""
        abilities_data = [
            {
                "trigger": "TURN_END",
                "condition": {"kind": "BOARD_STATE", "params": {"min_friendly": 3}},
                "actions": [{"class": "DamageSpell", "value": 1, "target": "ENEMY_HERO"}],
            }
        ]
        power = CardPower.from_abilities_json("TEST_COND", abilities_data)
        assert power.has_triggers
        assert len(power.triggers) == 1
        assert power.triggers[0].condition is not None
        assert power.triggers[0].condition["kind"] == "BOARD_STATE"

    def test_all_trigger_types_grouped(self):
        """所有事件触发器类型均归入 triggers。"""
        trigger_types = [
            "TURN_START", "TURN_END", "ON_ATTACK",
            "ON_DAMAGE", "ON_SPELL_CAST", "ON_DEATH",
            "WHENEVER", "AFTER",
        ]
        for tt in trigger_types:
            abilities_data = [
                {"trigger": tt, "actions": [{"class": "DamageSpell", "value": 1}]}
            ]
            power = CardPower.from_abilities_json(f"TEST_{tt}", abilities_data)
            assert power.has_triggers, f"触发器 {tt} 应归入 triggers"
            assert power.triggers[0].trigger_type == tt


# ═══════════════════════════════════════════════════════════════
# T4.2 测试: Card.power 延迟加载
# ═══════════════════════════════════════════════════════════════


class TestCardModelPowerProperty:
    """Card.power 延迟加载测试。"""

    def test_card_model_power_property(self):
        """Card.power 返回 CardPower 实例，不存在时为空。"""
        from analysis.card.models.card import Card

        card = Card(card_id="NONEXISTENT", mechanics=["BATTLECRY"])
        power = card.power
        assert isinstance(power, CardPower)
        assert power.card_id == "NONEXISTENT"
        # 卡牌不存在于 JSON 中，power 应为空
        assert power.is_empty

    def test_card_model_power_cached(self):
        """Card.power 多次访问返回同一实例（缓存）。"""
        from analysis.card.models.card import Card

        card = Card(card_id="CACHE_TEST")
        power1 = card.power
        power2 = card.power
        assert power1 is power2

    def test_card_model_power_setter(self):
        """Card.power setter 可直接赋值。"""
        from analysis.card.models.card import Card

        card = Card(card_id="SETTER_TEST")
        custom_power = CardPower(card_id="SETTER_TEST", battlecry=[
            Spell.from_dict({"class": "DamageSpell", "value": 5})
        ])
        card.power = custom_power
        assert card.power is custom_power
        assert card.power.has_battlecry


# ═══════════════════════════════════════════════════════════════
# T4.2 测试: Card.has_battlecry 从 mechanics 判断
# ═══════════════════════════════════════════════════════════════


class TestCardModelHasMechanics:
    """Card 的 has_X 属性从 mechanics 判断测试。"""

    def test_card_model_has_battlecry(self):
        """Card.has_battlecry 从 mechanics 判断。"""
        from analysis.card.models.card import Card

        card = Card(card_id="TEST", mechanics=["BATTLECRY", "TAUNT"])
        assert card.has_battlecry
        assert not card.has_deathrattle

    def test_card_model_has_deathrattle(self):
        """Card.has_deathrattle 从 mechanics 判断。"""
        from analysis.card.models.card import Card

        card = Card(card_id="TEST", mechanics=["DEATHRATTLE"])
        assert card.has_deathrattle
        assert not card.has_battlecry

    def test_card_model_has_combo(self):
        """Card.has_combo 从 mechanics 判断。"""
        from analysis.card.models.card import Card

        card = Card(card_id="TEST", mechanics=["COMBO"])
        assert card.has_combo

    def test_card_model_has_outcast(self):
        """Card.has_outcast 从 mechanics 判断。"""
        from analysis.card.models.card import Card

        card = Card(card_id="TEST", mechanics=["OUTCAST"])
        assert card.has_outcast


# ═══════════════════════════════════════════════════════════════
# repr 测试
# ═══════════════════════════════════════════════════════════════


class TestCardPowerRepr:
    """CardPower.__repr__ 格式测试。"""

    def test_card_power_repr_empty(self):
        """空 CardPower 的 repr 格式。"""
        power = CardPower(card_id="EMPTY")
        r = repr(power)
        assert "CardPower" in r
        assert "EMPTY" in r

    def test_card_power_repr_with_abilities(self):
        """有能力的 CardPower 的 repr 包含数量信息。"""
        spell = Spell.from_dict({"class": "DamageSpell", "value": 3})
        power = CardPower(
            card_id="EX1_066",
            battlecry=[spell],
            deathrattle=[Spell.from_dict({"class": "SummonSpell", "card_id": "T"})],
            triggers=[TriggerDef(trigger_type="TURN_START")],
        )
        r = repr(power)
        assert "EX1_066" in r
        assert "battlecry=1" in r
        assert "deathrattle=1" in r
        assert "triggers=1" in r

    def test_card_power_repr_with_aura(self):
        """有光环的 CardPower 的 repr 包含 aura 标记。"""
        power = CardPower(
            card_id="AURA_TEST",
            aura=AuraDef(target="FRIENDLY_MINIONS", attack=1),
        )
        r = repr(power)
        assert "AURA_TEST" in r
        assert "aura" in r


# ═══════════════════════════════════════════════════════════════
# T4.3 测试: 从临时 JSON 文件完整加载链路
# ═══════════════════════════════════════════════════════════════


class TestCardPowerFromJsonFile:
    """从临时 JSON 文件加载 CardPower 的完整链路测试。"""

    def test_card_power_from_json_file(self, tmp_path, monkeypatch):
        """通过 monkeypatch 替换 loader._JSON_PATH，验证完整加载链路。"""
        # 构建临时 JSON 数据
        test_json = {
            "version": 1,
            "cards": {
                "EX1_110": {
                    "id": "EX1_110",
                    "abilities": [
                        {
                            "trigger": "BATTLECRY",
                            "actions": [
                                {"class": "DamageSpell", "value": 3, "target": "RANDOM_ENEMY_CHARACTER"}
                            ],
                        },
                        {
                            "trigger": "DEATHRATTLE",
                            "actions": [
                                {"class": "SummonSpell", "card_id": "EX1_110t"}
                            ],
                        },
                    ],
                },
            },
        }
        # 写入临时 JSON 文件
        json_file = tmp_path / "card_abilities.json"
        json_file.write_text(json.dumps(test_json, ensure_ascii=False), encoding="utf-8")

        # monkeypatch loader 的 _JSON_PATH 和缓存
        import analysis.card.abilities.loader as loader_mod
        monkeypatch.setattr(loader_mod, "_JSON_PATH", json_file)
        monkeypatch.setattr(loader_mod, "_cache", None)

        # 通过 Card.power 延迟加载验证
        from analysis.card.models.card import Card

        card = Card(card_id="EX1_110")
        power = card.power

        assert isinstance(power, CardPower)
        assert power.card_id == "EX1_110"
        assert power.has_battlecry
        assert power.has_deathrattle
        assert len(power.battlecry) == 1
        assert len(power.deathrattle) == 1
        from analysis.card.abilities.spells import DamageSpell, SummonSpell
        assert isinstance(power.battlecry[0], DamageSpell)
        assert isinstance(power.deathrattle[0], SummonSpell)

    def test_card_power_from_json_file_not_found(self, tmp_path, monkeypatch):
        """JSON 文件不存在时，Card.power 返回空 CardPower。"""
        # 指向不存在的文件
        missing_file = tmp_path / "nonexistent.json"

        import analysis.card.abilities.loader as loader_mod
        monkeypatch.setattr(loader_mod, "_JSON_PATH", missing_file)
        monkeypatch.setattr(loader_mod, "_cache", None)

        from analysis.card.models.card import Card

        card = Card(card_id="ANY_CARD")
        power = card.power

        assert isinstance(power, CardPower)
        assert power.is_empty

    def test_card_power_from_json_file_card_not_in_json(self, tmp_path, monkeypatch):
        """JSON 存在但卡牌不在其中时，Card.power 返回空 CardPower。"""
        test_json = {"version": 1, "cards": {}}
        json_file = tmp_path / "card_abilities.json"
        json_file.write_text(json.dumps(test_json), encoding="utf-8")

        import analysis.card.abilities.loader as loader_mod
        monkeypatch.setattr(loader_mod, "_JSON_PATH", json_file)
        monkeypatch.setattr(loader_mod, "_cache", None)

        from analysis.card.models.card import Card

        card = Card(card_id="NOT_IN_JSON")
        power = card.power

        assert isinstance(power, CardPower)
        assert power.is_empty

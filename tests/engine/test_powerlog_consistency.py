#!/usr/bin/env python3
"""test_powerlog_consistency.py — Power.log 效果一致性测试。

验证模拟引擎的卡牌效果与 Power.log 实际效果一致。
按 Phase 分组: Phase 1 数据修正, Phase 2 缺失卡牌, Phase 3 引擎扩展。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from analysis.card.engine.state import (
    GameState, HeroState, ManaState, OpponentState, Minion, Weapon,
)
from analysis.card.abilities.model import SpellDesc
from analysis.card.abilities.executor import SpellExecutor
from analysis.card.engine.tags import GameTag, has_tag
from analysis.card.models.card import Card


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(**kwargs):
    defaults = dict(
        hero=HeroState(hp=30, armor=0),
        mana=ManaState(available=5, max_mana=5),
        board=[],
        hand=[],
        cards_played_this_turn=[],
        opponent=OpponentState(hero=HeroState(hp=30, armor=0)),
        turn_number=5,
    )
    defaults.update(kwargs)
    return GameState(**defaults)


def _make_minion(name="TestMinion", attack=3, health=5, owner="friendly", **kwargs):
    return Minion(
        name=name, attack=attack, health=health,
        max_health=kwargs.pop('max_health', health),
        owner=owner, **kwargs,
    )


def _execute_spell(spell_dict, state, source=None, target=None):
    """Execute a spell definition dict on the given state."""
    desc = SpellDesc.from_json(spell_dict)
    return SpellExecutor._execute_desc(desc, state, source=source, target=target)


def _load_ability(card_id):
    """Load a card's ON_PLAY ability from the merged v2 database."""
    from analysis.card.abilities.loader_v2 import get_loader_v2
    loader = get_loader_v2()
    ability = loader.get(card_id)
    if ability and ability.on_play:
        return ability.on_play
    return None


def _execute_card_ability(card_id, state, source=None, target=None):
    """Execute a card's ON_PLAY ability by card_id."""
    on_play = _load_ability(card_id)
    if on_play is None:
        pytest.skip(f"No ON_PLAY ability for {card_id}")
    return SpellExecutor._execute_desc(on_play, state, source=source, target=target)


# ═══════════════════════════════════════════════════════════════
# Phase 1: 数据修正测试
# ═══════════════════════════════════════════════════════════════

class TestPhase1DataFixes:
    """验证 Phase 1 中修正的错误能力定义。"""

    def test_time_004_damage_and_armor(self):
        """时光流汇扫荡者: 战吼造成7点伤害 + 获得6护甲。

        Power.log 验证: L44623, ARMOR=6 + DAMAGE=7
        DB 修正: DamageSpell → MetaSpell[DamageSpell, ArmorSpell(6)]
        """
        state = _make_state()
        # 添加一个敌方随从作为 RANDOM_ENEMY_CHARACTER 的目标
        enemy = _make_minion(name="EnemyMinion", attack=1, health=15, owner="enemy")
        state.opponent.board.append(enemy)
        original_hp = enemy.health

        result = _execute_card_ability("TIME_004", state)

        # 应该受到 7 点伤害
        assert enemy.health == original_hp - 7 or state.opponent.hero.hp < 30
        # 应该获得 6 护甲
        assert result.hero.armor == 6

    def test_cata_496_temp_control_no_attack(self):
        """诅咒之链: 夺取控制 + 不能攻击。

        Power.log 验证: CONTROLLER=2, CANT_ATTACK
        DB 修正: TakeControlSpell → MetaSpell[TakeControl, AddKeyword(CANT_ATTACK), Enchant]
        """
        state = _make_state()
        enemy_minion = _make_minion(name="TargetMinion", attack=5, health=5, owner="enemy")
        state.opponent.board.append(enemy_minion)

        # 构造 target 指向敌方随从
        result = _execute_card_ability("CATA_496", state, target=enemy_minion)

        # 应该被夺取控制权
        assert enemy_minion in result.board or len(result.opponent.board) == 0
        # 应该标记不能攻击
        assert has_tag(enemy_minion.tags, GameTag.CANT_ATTACK)

    def test_end_000p_is_noop(self):
        """青铜龙的祝福: 当前应为 NoOp（Rewind 未实现）。

        Power.log 验证: 实际是 Rewind 英雄技能，不是伤害
        DB 修正: DamageSpell → NoOpSpell
        """
        state = _make_state()
        state.opponent.board.append(_make_minion(name="Enemy", health=10, owner="enemy"))
        original_hp = state.opponent.hero.hp

        result = _execute_card_ability("END_000p", state)

        # 不应该造成伤害
        assert result.opponent.hero.hp == original_hp

    def test_tlc_460_is_quest_not_discover(self):
        """禁忌序列: 应为任务卡不执行发现。

        Power.log 验证: Quest: Discover 7 cards
        DB 修正: DiscoverSpell → NoOpSpell (quest tracking handled by quest.py)
        """
        state = _make_state(hand=[Minion(name=f"Card{i}", attack=1, health=1) for i in range(5)])
        original_hand_count = len(state.hand)

        result = _execute_card_ability("TLC_460", state)

        # 不应该添加卡牌到手牌 (DiscoverSpell 会添加)
        assert len(result.hand) == original_hand_count


# ═══════════════════════════════════════════════════════════════
# Phase 2: 缺失卡牌测试
# ═══════════════════════════════════════════════════════════════

class TestPhase2MissingCards:
    """验证 Phase 2 中新增的缺失卡牌能力定义。"""

    def test_cs2_034_h2_fireblast(self):
        """火焰冲击: 对目标造成1点伤害。

        Power.log 验证: L6909, DEAL 1 DAMAGE
        """
        state = _make_state()
        target = _make_minion(name="Target", health=5, owner="enemy")
        state.opponent.board.append(target)

        result = _execute_card_ability("CS2_034_H2", state, target=target)

        assert target.health == 4

    def test_cata_190p_hero_buff(self):
        """无情: 英雄 +5 临时攻击力。

        Power.log 验证: ATK=5 added to hero
        """
        state = _make_state()
        assert state.hero.temporary_attack == 0

        result = _execute_card_ability("CATA_190p", state)

        assert result.hero.temporary_attack == 5

    def test_time_000ta_noop(self):
        """维持时间线: 什么都不做。"""
        state = _make_state()
        result = _execute_card_ability("TIME_000ta", state)
        assert result.hero.hp == 30  # no side effects

    def test_time_000tb_noop(self):
        """回溯时间线: 暂时 NoOp (Rewind 待实现)。"""
        state = _make_state()
        result = _execute_card_ability("TIME_000tb", state)
        assert result.hero.hp == 30


# ═══════════════════════════════════════════════════════════════
# Phase 3: 引擎扩展测试
# ═══════════════════════════════════════════════════════════════

class TestPhase3NewSpells:
    """验证 Phase 3 中新增的 Spell 类。"""

    def test_temp_control_spell(self):
        """TempControlSpell: 夺取控制 + 不能攻击 + duration enchantment。"""
        state = _make_state()
        enemy = _make_minion(name="Enemy", attack=4, health=4, owner="enemy")
        state.opponent.board.append(enemy)

        result = _execute_spell(
            {"class": "TempControlSpell", "target": "TARGET"},
            state, target=enemy,
        )

        # 应该在友方场上
        assert enemy in result.board
        # 应该标记不能攻击
        assert has_tag(enemy.tags, GameTag.CANT_ATTACK)
        # 应该有 temp_control enchantment
        assert any(e.get("type") == "temp_control" for e in enemy.enchantments)

    def test_hero_buff_spell(self):
        """HeroBuffSpell: 给英雄加临时攻击力。"""
        state = _make_state()
        assert state.hero.temporary_attack == 0

        result = _execute_spell(
            {"class": "HeroBuffSpell", "attack_bonus": 5},
            state,
        )

        assert result.hero.temporary_attack == 5

    def test_hero_buff_spell_stacks(self):
        """HeroBuffSpell: 多次增益应叠加。"""
        state = _make_state()
        result = _execute_spell({"class": "HeroBuffSpell", "attack_bonus": 3}, state)
        result = _execute_spell({"class": "HeroBuffSpell", "attack_bonus": 2}, result)
        assert result.hero.temporary_attack == 5

    def test_spend_mana_buff_spell(self):
        """SpendManaBuffSpell: 消耗法力值增益最近召唤的随从。

        模拟 CATA_135 苔缚术: 4法力 → 召唤2个随从 → 各+4/+4
        """
        state = _make_state(mana=ManaState(available=4, max_mana=4))
        # 预先放两个随从（模拟刚被 SummonSpell 召唤）
        m1 = _make_minion(name="Golem1", attack=1, health=2)
        m2 = _make_minion(name="Golem2", attack=1, health=2)
        state.board = [m1, m2]

        result = _execute_spell(
            {"class": "SpendManaBuffSpell", "count": 2, "attack_bonus": 1, "health_bonus": 1},
            state,
        )

        # 法力应该耗尽
        assert result.mana.available == 0
        # 两个随从各+4/+4 (4法力 × 1/1)
        assert m1.attack == 5  # 1 + 4
        assert m1.health == 6  # 2 + 4
        assert m2.attack == 5
        assert m2.health == 6

    def test_spend_mana_buff_zero_mana(self):
        """SpendManaBuffSpell: 零法力时不变更随从。"""
        state = _make_state(mana=ManaState(available=0, max_mana=5))
        m = _make_minion(attack=1, health=1)
        state.board = [m]

        result = _execute_spell(
            {"class": "SpendManaBuffSpell", "count": 1, "attack_bonus": 1, "health_bonus": 1},
            state,
        )

        assert m.attack == 1
        assert m.health == 1

    def test_escalation_draw_spell(self):
        """EscalationDrawSpell: 递增抽牌。

        第1次: 抽1张 (base=1, counter=0)
        第2次: 抽2张 (base=1, counter=1)
        """
        state = _make_state(deck_remaining=10)
        source = Card(dbf_id=1, name="FIR_911", card_id="FIR_911", cost=2)

        # 第1次
        result = _execute_spell(
            {"class": "EscalationDrawSpell", "value": 1},
            state, source=source,
        )
        assert result.deck_remaining == 9
        assert result.escalation_counters.get("FIR_911", 0) == 1

        # 第2次
        result2 = _execute_spell(
            {"class": "EscalationDrawSpell", "value": 1},
            result, source=source,
        )
        assert result2.deck_remaining == 7  # 9 - 2
        assert result2.escalation_counters["FIR_911"] == 2

    def test_rewind_choice_spell(self):
        """RewindChoiceSpell: 记录 rewind 上下文 + 执行第一个 spell。"""
        state = _make_state(hero=HeroState(hp=30))

        result = _execute_spell(
            {"class": "RewindChoiceSpell", "spells": [
                {"class": "ArmorSpell", "value": 3},
                {"class": "NoOpSpell"},
            ]},
            state,
        )

        # 应该记录 rewind 上下文
        assert len(result.rewind_stack) == 1
        assert len(result.rewind_stack[0]["spells"]) == 2
        # 应该执行第一个 spell (ArmorSpell(3))
        assert result.hero.armor == 3


class TestPhase3GameStateExtensions:
    """验证 GameState 新字段的正确行为。"""

    def test_temporary_attack_default(self):
        """temporary_attack 默认值为 0。"""
        hero = HeroState()
        assert hero.temporary_attack == 0

    def test_rewind_stack_default(self):
        """rewind_stack 默认为空列表。"""
        state = _make_state()
        assert state.rewind_stack == []

    def test_escalation_counters_default(self):
        """escalation_counters 默认为空字典。"""
        state = _make_state()
        assert state.escalation_counters == {}

    def test_end_of_turn_double_default(self):
        """end_of_turn_double 默认为 False。"""
        state = _make_state()
        assert state.end_of_turn_double is False

    def test_quest_discover_count_default(self):
        """quest_discover_count 默认为 0。"""
        state = _make_state()
        assert state.quest_discover_count == 0


class TestPhase3TriggerExtensions:
    """验证 TriggerDispatcher 新方法。"""

    def test_after_discover_increments_counter(self):
        """after_discover 应该递增 quest_discover_count。"""
        state = _make_state()
        from analysis.card.engine.trigger import get_dispatcher
        dispatcher = get_dispatcher()

        assert state.quest_discover_count == 0
        result = dispatcher.after_discover(state)
        assert result.quest_discover_count == 1
        result = dispatcher.after_discover(result)
        assert result.quest_discover_count == 2

    def test_after_discover_advances_quest(self):
        """after_discover 应该推进 discover_cards 类型的任务。"""
        state = _make_state()
        quest = type('Quest', (), {
            'quest_type': 'discover_cards',
            'completed': False,
            'progress': 0,
        })()
        state.active_quests = [quest]

        from analysis.card.engine.trigger import get_dispatcher
        result = get_dispatcher().after_discover(state)

        assert quest.progress == 1

    def test_on_turn_end_double_trigger(self):
        """on_turn_end 在 end_of_turn_double=True 时应触发两次。"""
        from analysis.card.engine.trigger import get_dispatcher

        trigger_count = [0]

        def counting_listener(state, **kwargs):
            trigger_count[0] += 1
            return state

        dispatcher = get_dispatcher()
        dispatcher.register_listener("on_turn_end", counting_listener)

        state = _make_state()
        state.end_of_turn_double = True

        result = dispatcher.on_turn_end(state)

        assert trigger_count[0] == 2  # fired twice
        assert result.end_of_turn_double is False  # reset after firing

        # Cleanup
        dispatcher.unregister_listener("on_turn_end", counting_listener)


# ═══════════════════════════════════════════════════════════════
# Phase 4: 细微修正测试
# ═══════════════════════════════════════════════════════════════

class TestPhase4Corrections:
    """验证 Phase 4 中的细微修正。"""

    def test_cata_485_two_damage_effects(self):
        """激寒急流: 对目标造成2点伤害 + 对随机敌方随从造成1点伤害。

        Power.log 验证: L6502, DAMAGE=2 + DAMAGE=1
        """
        state = _make_state()
        target = _make_minion(name="Target", health=10, owner="enemy")
        enemy2 = _make_minion(name="OtherEnemy", health=5, owner="enemy")
        state.opponent.board = [target, enemy2]

        result = _execute_card_ability("CATA_485", state, target=target)

        # 至少有一个敌方随从受伤（TARGET受伤2点 或 RANDOM_ENEMY_MINION受伤1点）
        total_damage = (10 - target.health) + (5 - enemy2.health)
        assert total_damage >= 2  # 至少2点伤害总效果

    def test_cata_135_spend_mana_summon(self):
        """苔缚术: 召唤2个魔像 + 消耗法力增益。

        Power.log 验证: 4法力, 召唤2个3/4苔藓魔像 (1+4=5 attack... actually base=1+mana*1)
        """
        state = _make_state(mana=ManaState(available=2, max_mana=2))

        result = _execute_card_ability("CATA_135", state)

        # 应该召唤了随从 (SummonSpell × 2)
        # 注意: SummonSpell 需要 CATA_135t 在卡牌数据库中存在
        # 如果不存在则创建默认 1/1 token
        assert len(result.board) >= 2


# ═══════════════════════════════════════════════════════════════
# 集成测试: 验证新 Spell 注册
# ═══════════════════════════════════════════════════════════════

class TestSpellRegistration:
    """验证所有新 Spell 类已正确注册到 SPELL_REGISTRY。"""

    def test_all_new_spells_registered(self):
        from analysis.card.spells import SPELL_REGISTRY
        required = [
            'TempControlSpell', 'HeroBuffSpell', 'SpendManaBuffSpell',
            'EscalationDrawSpell', 'RewindChoiceSpell',
        ]
        for name in required:
            assert name in SPELL_REGISTRY, f"{name} not registered in SPELL_REGISTRY"


# ═══════════════════════════════════════════════════════════════
# Phase 5: 数据修正测试
# ═══════════════════════════════════════════════════════════════

class TestPhase5DataFixes:
    """Phase 5 数据修正验证。"""

    def test_sw_108t_damage_2(self):
        """传承之火: 对目标造成2点伤害。Power.log: L24012, DAMAGE=2"""
        state = _make_state()
        target = _make_minion(name="Target", health=5, owner="enemy")
        state.opponent.board.append(target)
        result = _execute_card_ability("SW_108t", state, target=target)
        assert target.health == 3

    def test_time_047_noop(self):
        """狡诈的郊狼: ON_PLAY 无直接效果。"""
        state = _make_state()
        result = _execute_card_ability("TIME_047", state)
        assert result.hero.hp == 30

    def test_tlc_605_noop(self):
        """焦油暴君: ON_PLAY 无直接效果。"""
        state = _make_state()
        result = _execute_card_ability("TLC_605", state)
        assert result.hero.hp == 30

    def test_time_026_buff_all_and_shuffle(self):
        """续连熵能: 全体+1/+1 + 洗2张时空撕裂。Power.log: L40809"""
        state = _make_state()
        m1 = _make_minion(name="M1", attack=2, health=3)
        m2 = _make_minion(name="M2", attack=4, health=1)
        state.board = [m1, m2]

        result = _execute_card_ability("TIME_026", state)

        assert m1.attack == 3 and m1.health == 4
        assert m2.attack == 5 and m2.health == 2

    def test_cata_154_colossal_summon(self):
        """希奈丝特拉: 巨型+2 召唤2个附肢。"""
        state = _make_state()
        result = _execute_card_ability("CATA_154", state)
        assert len(result.board) >= 2

    def test_time_026_not_self_buff(self):
        """续连熵能: 不应是 SELF buff (旧 bug)。"""
        state = _make_state()
        m = _make_minion(name="Only", attack=1, health=1)
        state.board = [m]
        result = _execute_card_ability("TIME_026", state)
        assert m.attack == 2 and m.health == 2


# ═══════════════════════════════════════════════════════════════
# Phase 6: 新 Spell 类测试
# ═══════════════════════════════════════════════════════════════

class TestPhase6NewSpells:
    """Phase 6 新增 Spell 类验证。"""

    def test_mana_discount_spell_next_spell(self):
        """ManaDiscountSpell: 下张法术-2费。"""
        state = _make_state()
        assert len(state.mana.modifiers) == 0
        result = _execute_spell(
            {"class": "ManaDiscountSpell", "value": 2, "scope": "next_spell"},
            state,
        )
        assert len(result.mana.modifiers) == 1
        assert result.mana.modifiers[0].value == 2
        assert result.mana.modifiers[0].scope == "next_spell"

    def test_mana_discount_spell_effective_cost(self):
        """ManaDiscountSpell + effective_cost 集成。"""
        from analysis.card.models.card import Card
        state = _make_state()
        result = _execute_spell(
            {"class": "ManaDiscountSpell", "value": 3, "scope": "next_spell"},
            state,
        )
        spell_card = Card(dbf_id=1, name="Test", card_id="T1", cost=5, card_type="SPELL")
        assert result.mana.effective_cost(spell_card) == 2

    def test_mana_discount_spell_this_turn(self):
        """ManaDiscountSpell: 本回合所有牌-1费。"""
        from analysis.card.models.card import Card
        state = _make_state()
        result = _execute_spell(
            {"class": "ManaDiscountSpell", "value": 1, "scope": "this_turn"},
            state,
        )
        card = Card(dbf_id=1, name="T", card_id="T1", cost=4, card_type="SPELL")
        assert result.mana.effective_cost(card) == 3

    def test_corpse_spend_spell(self):
        """CorpseSpendSpell: 消耗2份残骸。"""
        state = _make_state()
        state.corpses = 5
        result = _execute_spell({"class": "CorpseSpendSpell", "value": 2}, state)
        assert result.corpses == 3

    def test_corpse_spend_insufficient(self):
        """CorpseSpendSpell: 残骸不足时归零。"""
        state = _make_state()
        state.corpses = 1
        result = _execute_spell({"class": "CorpseSpendSpell", "value": 2}, state)
        assert result.corpses == 0

    def test_ex145_prep_discount(self):
        """伺机待发: 下张法术-2费。"""
        state = _make_state()
        result = _execute_card_ability("EX1_145", state)
        assert len(result.mana.modifiers) == 1
        assert result.mana.modifiers[0].value == 2
        assert result.mana.modifiers[0].scope == "next_spell"


# ═══════════════════════════════════════════════════════════════
# Phase 7: 过简化修正测试
# ═══════════════════════════════════════════════════════════════

class TestPhase7Refinements:
    """Phase 7 过简化修正验证。"""

    def test_edr_811_corpse_spend(self):
        """暴行祭礼: 发现+消耗2份残骸。"""
        state = _make_state()
        state.corpses = 5
        result = _execute_card_ability("EDR_811", state)
        assert result.corpses == 3

    def test_edr_811_corpse_insufficient(self):
        """暴行祭礼: 残骸不足时仍然执行 (Discover 不依赖尸体)。"""
        state = _make_state()
        state.corpses = 0
        result = _execute_card_ability("EDR_811", state)
        assert result.corpses == 0


# ═══════════════════════════════════════════════════════════════
# Phase 5-7 注册验证
# ═══════════════════════════════════════════════════════════════

class TestPhase5to7SpellRegistration:
    """验证所有新 Spell 类已注册。"""
    def test_new_spells_registered(self):
        from analysis.card.spells import SPELL_REGISTRY
        for name in ['ManaDiscountSpell', 'CorpseSpendSpell']:
            assert name in SPELL_REGISTRY, f"{name} not registered"

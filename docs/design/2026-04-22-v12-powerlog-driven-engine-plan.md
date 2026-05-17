---
date: 2026-04-22
topic: "V12 Power.log 驱动的引擎缺陷修复计划"
status: active
version: 1.0
design_ref: 2026-04-22-v12-powerlog-driven-engine-gaps-design.md
supersedes: 2026-04-21-next-gen-engine-architecture-design.md
---

# 目标

基于 Power.log 真实对局分析，修复 V11 引擎 20 个不足，将引擎从"数值评估器"升级为"游戏模拟器"。

# 里程碑

## Phase 1: 卡牌效果模拟层 (P0)

> 解决 10 个场景中 6 个的核心瓶颈：战吼/发现/英雄替换/控制变形无法被 apply_action 处理。

### Task 1.1: BattlecryDispatcher

- [ ] 创建 `engine/mechanics/battlecry_dispatcher.py`
- [ ] 实现战吼文本正则匹配（发现/伤害/召唤/抽牌/护甲）
- [ ] 中英文双语模式支持
- [ ] 战吼分支展开：发现 → top-3 分支，伤害 → 所有合法目标
- [ ] 测试：战吼伤害正确应用、发现选最优、无战吼卡牌 passthrough

### Task 1.2: SpellTargetResolver

- [ ] 创建 `engine/mechanics/spell_target_resolver.py`
- [ ] 解析法术文本提取目标范围（敌方随从/友方随从/任意随从/英雄）
- [ ] 集成到 `_enumerate_card_combos` 法术枚举
- [ ] 测试：定向法术目标选择、AOE 无目标、英雄目标

### Task 1.3: HeroCardHandler

- [ ] 创建 `engine/mechanics/hero_card_handler.py`
- [ ] 实现 `HERO_REPLACE` action type
- [ ] HeroState 新增 `hero_power_cost`/`hero_power_effect`/`is_hero_card` 字段
- [ ] 英雄牌打出流程：替换英雄 → 获得护甲 → 新技能 → 战吼效果链
- [ ] 测试：英雄牌替换后血量/护甲/技能正确更新

### Task 1.4: ManaModifier

- [ ] `ManaState` 新增 `modifiers: List[ManaModifier]` 字段
- [ ] 实现 `effective_cost(card)` 方法（减费/临时法力）
- [ ] 实现 `consume_modifiers(card)` 方法
- [ ] `apply_action("PLAY")` 中调用 effective_cost 并消耗 modifier
- [ ] 测试：伺机待发减费、幸运币临时法力、过载正确计算

### Task 1.5: rhea_engine.py apply_action 扩展

- [ ] 新增 action types: `PLAY_WITH_TARGET`/`TRANSFORM`/`DISCOVER_PICK`/`HERO_REPLACE`
- [ ] PLAY 时触发 BattlecryDispatcher
- [ ] PLAY_WITH_TARGET 时使用 SpellTargetResolver
- [ ] HERO_REPLACE 时使用 HeroCardHandler
- [ ] combo 标签检查：`cards_played_this_turn` 追踪
- [ ] 测试：所有新 action type 的状态变更

## Phase 2: 统一行动序列 (P0)

> 解决场景 7 的核心问题：出牌和攻击阶段强制分离。

### Task 2.1: UnifiedTacticalPlanner

- [ ] 创建 `engine/unified_tactical.py`
- [ ] 实现统一行动序列枚举（出牌+攻击穿插）
- [ ] Beam width=5 剪枝，每步保留 top-5
- [ ] 时间预算截断（<150ms）
- [ ] Lethal early exit 快速路径
- [ ] 测试：出牌→攻击→出牌穿插序列、时间预算截断

### Task 2.2: ActionPruner 扩展

- [ ] 新增剪枝规则：无效法术目标、重复序列、明显劣质发现选项
- [ ] 集成到 UnifiedTacticalPlanner
- [ ] 测试：新规则剪枝效果

## Phase 3: 因子评估增强 (P1)

### Task 3.1: BoardControlFactor 关键词组合

- [ ] 实现 `_weighted_board_value` 方法
- [ ] 关键词权重：嘲讽×1.3、圣盾≈多打一次、风怒×1.5、剧毒+3、潜行×1.2、吸血+0.3×攻击力、复生×1.4
- [ ] 测试：嘲讽+圣盾组合价值高于纯数值

### Task 3.2: LethalThreatFactor 英雄技能+法术

- [ ] `_max_damage` 新增英雄技能伤害（需法力>=2）
- [ ] `_max_damage` 新增手牌法术伤害解析
- [ ] 测试：英雄技能伤害计入致命、手牌法术伤害计入致命

### Task 3.3: ValueFactor 牌质感知

- [ ] 集成 SIV 评分计算手牌质量差
- [ ] `quality_delta` 权重 0.02 + 卡差权重 0.3
- [ ] 测试：高 SIV 手牌的 Value 因子更高

### Task 3.4: SurvivalFactor 自适应阈值

- [ ] 阈值根据 Phase 动态调整：前期 0.5、中后期 0.7
- [ ] 测试：后期生存阈值更敏感

## Phase 4: 数据模型扩展 (P1)

### Task 4.1: Minion 字段扩展

- [ ] 新增 `has_magnetic`/`has_invoke`/`has_corrupt`/`has_spellburst`/`has_outcast`/`race`/`spell_school`/`enchantment_ids`
- [ ] 从 unified_standard.json 填充新字段

### Task 4.2: Action 扩展

- [ ] 新增 `discover_choice_index`/`sub_option` 字段
- [ ] 向后兼容现有代码

## Phase 5: AttackPlanner 升级 (P2)

### Task 5.1: Beam Search

- [ ] 替换纯贪心为 beam_width=3 的 beam search
- [ ] 测试：beam search 找到全局更优攻击序列

### Task 5.2: 多回合致命预估

- [ ] 实现 `_two_turn_lethal_probability` 方法
- [ ] 集成到 LethalThreatFactor 权重

# 回归测试

- [ ] V11 全部 25 个测试继续通过
- [ ] 新增 ~35 个测试覆盖 Phase 1-5

# 参考

- [V12 设计文档](file:///d:/code/game/thoughts/shared/designs/2026-04-22-v12-powerlog-driven-engine-gaps-design.md)
- [V11 架构分析](file:///d:/code/game/thoughts/shared/designs/2026-04-21-next-gen-engine-architecture-design.md)
- [HDT 集成设计](file:///d:/code/game/thoughts/shared/designs/2026-04-21-hdt-live-integration-design.md)
- [炉石完整规则](file:///d:/code/game/thoughts/shared/designs/2026-04-19-hearthstone-complete-rules.md)

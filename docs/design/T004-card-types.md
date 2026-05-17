---
date: 2026-04-18
task_id: T004
title: "卡牌类型适配 (Spell/Weapon/Location/Hero)"
status: pending
priority: medium
depends_on: [T003]
phase: model-v2
---

# T004: 卡牌类型适配

## 目标

为 Spell/Weapon/Location/Hero 四种非随从类型设计独立估值逻辑。

## 前置依赖

- T003 完成后的文本效果解析器

## 执行步骤

### Step 1: 法术卡估值
- 无属性基线，纯效果预算 = Layer 3 文本解析总分
- 法力效率比 = effect_budget / mana_cost
- 与同费随从对比合理性

### Step 2: 武器卡估值
- `weapon_stats = attack * durability`
- 走白板测试：stat_deficit = weapon_stats - curve_expected(mana)
- 叠加文本效果预算

### Step 3: 地标卡估值
- `location_value = charges * effect_value_per_use`
- 从文本解析提取每次使用效果的价值
- charges 默认 3（如无特殊说明）

### Step 4: 英雄卡估值
- `hero_value = armor + hero_power_budget(5.0) + text_effects`
- hero_power_budget 为固定常数（经验值 5.0）
- 叠加 Battlecry 效果

### Step 5: 编写脚本 + 验证
- `scripts/v2_type_adapter.py`
- 验证各类型评分分布合理

## 产出物

- `scripts/v2_type_adapter.py`

## 验收标准

- [ ] 每种类型卡均有评分（无 0 分异常）
- [ ] 高费法术 > 低费弱法术
- [ ] 热门武器卡评分为正

---
date: 2026-04-18
task_id: T002
title: "关键词三层分类 + 经验校准"
status: pending
priority: high
depends_on: [T001]
phase: model-v2
---

# T002: 关键词三层分类 + 经验校准

## 目标

将关键词分为 Power/Mechanical/Niche 三层，基于 T001 的新曲线计算实际 deficit，用线性回归校准基础分值。

## 前置依赖

- T001 完成后的 `v2_curve_params.json`（新白板曲线参数）

## 执行步骤

### Step 1: 重新计算 deficit
- 用 T001 的新曲线计算每张卡的 stat_deficit
- 统计每个关键词关联卡的平均 deficit 分布

### Step 2: 三层分类
- **Power 层**: BATTLECRY, DEATHRATTLE, DISCOVER, DIVINE_SHIELD, RUSH, CHARGE, WINDFURY, TAUNT, LIFESTEAL, STEALTH
- **Mechanical 层**: TRIGGER_VISUAL, AURA, COLOSSAL, QUEST, START_OF_GAME
- **Niche 层**: 其余所有关键词（默认 base=1.0）

### Step 3: 校准 Power 层
- 对 Power 层每个关键词，用关联卡数据拟合 base 值
- 公式：`keyword_value = base * (1 + 0.1 * mana)`
- 用最小二乘拟合每个关键词的 base 参数

### Step 4: Mechanical/Niche 层处理
- Mechanical: 固定 base=0.5-1.0（按实际频率微调）
- Niche: 默认 base=1.0，样本 > 10 时做校准

### Step 5: 编写脚本 + 输出
- `scripts/v2_keyword_model.py`
- 输出 `hs_cards/v2_keyword_params.json`
- 与 V1 固定分值对比报告

## 产出物

- `scripts/v2_keyword_model.py`
- `hs_cards/v2_keyword_params.json`

## 验收标准

- [ ] Power 层关键词 base >= 1.5
- [ ] Mechanical 层关键词 base <= 1.0
- [ ] 含多关键词卡预测偏差 < V1 模型
- [ ] 输出新旧分值对比表

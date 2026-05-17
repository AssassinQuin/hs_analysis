---
date: 2026-04-18
task_id: T005
title: "V2 综合评分引擎 + 验证报告"
status: pending
priority: high
depends_on: [T004]
phase: model-v2
---

# T005: V2 综合评分引擎

## 目标

整合三层模型 + 类型适配 + 职业平衡系数，输出最终评分并与 V1 对比。

## 前置依赖

- T001: 曲线参数
- T002: 关键词参数
- T003: 文本效果解析
- T004: 类型适配逻辑

## 执行步骤

### Step 1: 复合评分公式实现

对随从：
```
L1_fair = curve_expected(mana) * class_multiplier
L1_actual = attack + health
L2_keyword = sum(keyword_base * (1 + 0.1 * mana)) for each keyword
L3_text = sum(effect_value) from text parser

card_value = L1_actual + L2_keyword + L3_text
fair_value = L1_fair
score = card_value - fair_value
```

对非随从：使用 T004 的类型适配逻辑。

### Step 2: 职业平衡系数
按设计文档应用：
- Neutral: 0.85
- DH/Hunter: 0.95
- Warrior: 0.98
- Paladin/Rogue/Mage: 1.00
- DK/Priest/Warlock: 1.02
- Druid/Shaman: 1.05

### Step 3: V1 vs V2 对比分析
- Top 20 排名变化
- Bottom 10 排名变化
- 评分分布直方图对比
- 关键卡牌评分变化明细

### Step 4: 验证测试
- 白板随从评分 ≈ 0
- 已知 Tier S 卡评分 > Tier C 卡
- 评分分布近似正态
- 无极端异常值

### Step 5: 输出完整报告
- `hs_cards/v2_analysis_report.json` — 机器可读的完整数据
- 控制台输出人类可读的摘要报告
- 更新 README.md 反映 V2 模型

## 产出物

- `scripts/v2_scoring_engine.py`
- `hs_cards/v2_analysis_report.json`
- 更新后的 `README.md`

## 验收标准

- [ ] 评分分布近似正态（偏度 < 1.0）
- [ ] Tier S 卡评分 > Tier C 卡
- [ ] 白板随从评分 |值| < 2
- [ ] V1→V2 Top20 变化合理且有数据支撑

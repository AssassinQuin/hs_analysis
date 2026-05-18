---
date: 2026-04-18
phase: model-v2
status: in_progress
tasks: [T001, T002, T003, T004, T005]
design_ref: "../designs/2026-04-17-hearthstone-card-model-v2-design.md"
---

# Phase 1: V2 三层价值模型实现

## 阶段目标

用**三层非线性模型**替代当前线性 `2N+1` 模型，使卡牌评分更准确反映实际强度。

## 前置条件

- ✅ 256 张标准传说卡数据已采集 (Blizzard CN + HSJSON)
- ✅ V1 模型已完成，发现 7 个关键缺陷
- ✅ V2 设计文档已完成 (2026-04-17)

## 任务依赖图

```
T001 (曲线拟合) ──▶ T002 (关键词校准) ──▶ T003 (文本解析) ──▶ T004 (类型适配) ──▶ T005 (综合评分)
  ↗ 无依赖                                                                                      │
                                                                                                └──▶ 输出 V2 完整报告
```

串行依赖链，T001-T005 严格按序执行。

## 各任务摘要

### T001: 非线性白板曲线拟合
- **目标**: `expected_stats(mana) = a * mana^b + c`
- **方法**: scipy.optimize.curve_fit 最小二乘拟合
- **数据**: 227 张传说随从，筛除 mana>=99
- **产出**: v2_vanilla_curve.py + v2_curve_params.json

### T002: 关键词三层分类 + 经验校准
- **目标**: Power/Mechanical/Niche 三层 + `keyword_value = base * (1 + 0.1 * mana)`
- **方法**: 统计每个关键词关联卡的平均 deficit，线性回归校准
- **依赖**: T001 (需要新曲线计算 deficit)
- **产出**: v2_keyword_model.py + v2_keyword_params.json

### T003: 卡牌文本效果解析器
- **目标**: 正则提取 12 种效果类型 + 按预算表计分
- **方法**: 复用 deep_analysis.py 的正则 + 数值提取
- **依赖**: T002 (需要关键词分值做减法)
- **产出**: v2_text_parser.py + v2_text_analysis.json

### T004: 卡牌类型适配
- **目标**: Spell/Weapon/Location/Hero 独立估值逻辑
- **方法**: 按设计文档的各类型公式
- **依赖**: T003 (文本效果解析器)
- **产出**: v2_type_adapter.py

### T005: 综合评分 + 验证
- **目标**: 整合三层 + 类型 + 职业系数 + 对比报告
- **方法**: composite_score 公式
- **依赖**: T004
- **产出**: v2_scoring_engine.py + v2_analysis_report.json + README 更新

## 验证标准

1. 白板随从 (无关键词无文本) 评分 ≈ 0
2. 已知高强度卡 (Tier S) 评分 > 已知弱卡
3. 评分分布近似正态
4. 与 V1 对比，Top20 列表变化合理

## 预计产出文件

```
scripts/
├── v2_vanilla_curve.py      # T001
├── v2_keyword_model.py      # T002
├── v2_text_parser.py        # T003
├── v2_type_adapter.py       # T004
└── v2_scoring_engine.py     # T005

hs_cards/
├── v2_curve_params.json     # T001
├── v2_keyword_params.json   # T002
├── v2_text_analysis.json    # T003
└── v2_analysis_report.json  # T005
```

## 后续阶段预览

Phase 1 完成后:
- **Phase 2 (data-expansion)**: 扩展到全稀有度、数据入 SQLite
- **Phase 3 (opponent-prediction)**: 贝叶斯对手牌预测
- **Phase 4 (card-recognition)**: 画面卡牌识别
- **Phase 5 (decision-engine)**: 对战决策引擎

---
date: 2026-04-18
task_id: T003
title: "卡牌文本效果解析器 (Layer 3)"
status: pending
priority: high
depends_on: [T002]
phase: model-v2
---

# T003: 卡牌文本效果解析器

## 目标

用正则解析卡牌描述文本，提取 12 种效果类型并按预算表计算效果分值。

## 前置依赖

- T002 完成后的关键词校准结果

## 执行步骤

### Step 1: 效果正则模式库
复用 deep_analysis.py 的 22 个模式，新增数值提取：

| 效果 | 正则 | 提取值 |
|------|------|--------|
| 直接伤害 | 造成(\d+)点伤害 | damage=N |
| 召唤 | 召唤.*?(\d+)/(\d+) | atk=N, hp=N |
| 抽牌 | 抽(\d+)张牌 | count=N |
| AOE | 所有.*?(\d+)点伤害 | damage=N, targets=3 |
| 治疗 | 恢复(\d+)点 | heal=N |
| 护甲 | 获得(\d+)点护甲 | armor=N |
| 消灭 | 消灭 | count=1 |
| Buff | \+(\d+)/\+(\d+) | atk=N, hp=N |
| 生成 | 获取.*?一张 | count=1 |
| 复制 | 复制 | count=1 |
| 减费 | 法力值消耗.*?减少(\d+) | reduction=N |
| 条件 | 如果.*?则 | conditional=true |

### Step 2: 效果预算表
按设计文档的公式计算每个效果的预算分值。

### Step 3: 条件折扣
含"如果"条件的文本，整体效果打 0.6 折扣。

### Step 4: 编写脚本
- `scripts/v2_text_parser.py`
- 对全量传说卡运行解析
- 输出解析覆盖率报告

### Step 5: 验证
- 统计解析覆盖率（应 > 80%）
- 抽样检查数值提取准确性

## 产出物

- `scripts/v2_text_parser.py`
- `hs_cards/v2_text_analysis.json`

## 验收标准

- [ ] 含文本卡牌解析覆盖率 > 80%
- [ ] 纯伤害/召唤数值提取准确率 > 90%
- [ ] 条件效果正确标记折扣
